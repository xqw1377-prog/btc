"""实盘能力：武装内核可开/护/平；未武装 LIVE 仍先拒后建。"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.armed_runtime import ArmedRuntime  # noqa: E402
from aurora.kernel.state_machine import IntentState  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402
from tests.test_binance_exchange import RecordingClient  # noqa: E402


class ArmGateTests(unittest.TestCase):
    def test_paper_and_shadow_cannot_arm(self):
        client = RecordingClient()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.db")
            with self.assertRaises(SafetyViolation):
                ArmedRuntime.attach(RunMode.PAPER, client, path)
            with self.assertRaises(SafetyViolation):
                ArmedRuntime.attach(RunMode.SHADOW, client, path)

    def test_live_without_arm_token_refuses(self):
        client = RecordingClient()
        env = {k: v for k, v in os.environ.items() if k != "AURORA_ARM_LIVE"}
        with mock.patch.dict(os.environ, env, clear=True):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SafetyViolation) as ctx:
                    ArmedRuntime.attach(RunMode.LIVE, client, os.path.join(tmp, "l.db"))
                self.assertIn("NO-GO", str(ctx.exception))

    def test_position_mode_mismatch_or_unknown_refuses_before_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "l.db")
            hedge = RecordingClient()
            hedge.dual_side = "true"
            with mock.patch.dict(
                    os.environ, {"AURORA_EXPECTED_POSITION_MODE": "ONE_WAY"}):
                with self.assertRaises(SafetyViolation):
                    ArmedRuntime.attach(RunMode.TESTNET, hedge, path)
            self.assertFalse(os.path.exists(os.path.dirname(path)))

            class UnknownMode(RecordingClient):
                def futures_get_position_mode(self):
                    raise RuntimeError("query unavailable")

            with mock.patch.dict(
                    os.environ, {"AURORA_EXPECTED_POSITION_MODE": "ONE_WAY"}):
                with self.assertRaises(SafetyViolation):
                    ArmedRuntime.attach(RunMode.TESTNET, UnknownMode(), path)
            self.assertFalse(os.path.exists(os.path.dirname(path)))

    def test_attach_injects_observed_hedge_mode(self):
        client = RecordingClient()
        client.dual_side = "true"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, {"AURORA_EXPECTED_POSITION_MODE": "HEDGE"}):
            rt = ArmedRuntime.attach(
                RunMode.TESTNET, client, os.path.join(tmp, "l.db"))
            try:
                self.assertEqual(rt.exchange.position_mode, "HEDGE")
            finally:
                rt.close()


class ArmedKernelTests(unittest.TestCase):
    def test_testnet_open_protect_close(self):
        client = RecordingClient()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, {"AURORA_EXPECTED_POSITION_MODE": "ONE_WAY"}):
            rt = ArmedRuntime.attach(
                RunMode.TESTNET, client, os.path.join(tmp, "l.db"))
            try:
                opened = rt.open_position("LONG", 0.01, intent_id="LIVE1")
                self.assertTrue(opened["success"])
                self.assertEqual(opened["state"], "PROTECTED")
                self.assertEqual([c["type"] for c in client.creates], ["MARKET"])
                algo_types = [c[3]["data"]["type"] for c in client.algo_calls
                              if c[0] == "post"]
                self.assertEqual(algo_types, ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
                self.assertEqual(
                    rt.ledger.get_intent("LIVE1")["state"], IntentState.PROTECTED.value)
                closed = rt.close_position("capability close")
                self.assertTrue(closed["success"])
                closes = [c for c in client.creates if c.get("reduceOnly") and c["type"] == "MARKET"]
                self.assertEqual(len(closes), 1)
            finally:
                rt.close()

    def test_live_armed_same_path(self):
        client = RecordingClient()
        env = {
            "AURORA_ARM_LIVE": "I_ARM_LIVE_EXECUTION",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "TRADING_MODE": "LIVE",
            "AURORA_EXPECTED_POSITION_MODE": "ONE_WAY",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                rt = ArmedRuntime.attach(
                    RunMode.LIVE, client, os.path.join(tmp, "l.db"))
                try:
                    opened = rt.open_position("LONG", 0.01, intent_id="LIVE2")
                    self.assertTrue(opened["success"])
                    self.assertNotIn(
                        "STOP_MARKET", [c["type"] for c in client.creates])
                    self.assertIn(
                        "STOP_MARKET",
                        [c[3]["data"]["type"] for c in client.algo_calls])
                finally:
                    rt.close()


class ProductionArmWiringTests(unittest.TestCase):
    def test_arm_runtime_skips_shadow_and_paper(self):
        from aurora import production_main

        class Ctx:
            def __init__(self, mode):
                self.mode = mode
                self.broker = mock.Mock()

        self.assertIsNone(production_main._arm_runtime(Ctx(RunMode.PAPER)))
        self.assertIsNone(production_main._arm_runtime(Ctx(RunMode.SHADOW)))

    def test_testnet_arm_wires_orchestrator(self):
        from aurora import production_main

        class Broker:
            client = RecordingClient()

        class Ctx:
            mode = RunMode.TESTNET
            broker = Broker()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {
                "AURORA_LEDGER_PATH": os.path.join(tmp, "k.db"),
                "AURORA_EXPECTED_POSITION_MODE": "ONE_WAY",
            }):
                rt = production_main._arm_runtime(Ctx())
            try:
                self.assertIsNotNone(rt)
                self.assertEqual(rt.mode, RunMode.TESTNET)
                self.assertEqual(rt.boot_report["unresolved"], [])
            finally:
                rt.close()


if __name__ == "__main__":
    unittest.main()
