"""P0-A 回归钉子（B2.2）：production_main 依赖完整性与 LIVE 先拒后建。

来源：复审发现的三项回归——
1) LIVE 拒绝前构造主网 Client（构造本身即网络请求）；
2) 只读 broker 携带真实 cancel 能力；
3) production_main 依赖未跟踪的冻结线模块（execution_truth/binance_port/
   shadow_adapter/reconciler），已隔离至仓库外，本测试防止其回归。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora import production_main  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402

ROOT = Path(production_main.__file__).parent.parent
FORBIDDEN_REFERENCES = (
    "execution_truth",
    "binance_port",
    "shadow_adapter",
    "reconciler",
    "DurableExecutor",
    "SafeBinancePort",
)


class SourceIntegrityTests(unittest.TestCase):
    def test_production_main_references_only_committed_modules(self):
        source = Path(production_main.__file__).read_text()
        for banned in FORBIDDEN_REFERENCES:
            self.assertNotIn(banned, source, f"production_main 引用了违规模块: {banned}")

    def test_no_violating_modules_in_tracked_tree(self):
        for banned in ("binance_port.py", "shadow_adapter.py", "reconciler.py"):
            self.assertFalse(
                (ROOT / "aurora" / banned).exists(),
                f"违规模块重新出现: aurora/{banned}",
            )


class LiveRefusalOrderTests(unittest.TestCase):
    ENV_KEYS = (
        "TRADING_MODE", "TESTNET", "ALLOW_LIVE_TRADING", "AURORA_LIVE_CONFIRM",
        "AURORA_LIVE_KEY_SHA256", "AURORA_ACCOUNT_FINGERPRINT",
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
    )

    def _scrubbed(self, extra):
        env = {k: v for k, v in os.environ.items() if k not in self.ENV_KEYS}
        env.update(extra)
        return env

    def test_live_refuses_before_any_client_construction(self):
        """即便双重授权齐全，LIVE 也必须在构造任何 Client 之前拒绝。"""
        env = self._scrubbed({
            "TRADING_MODE": "LIVE",
            "TESTNET": "false",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
        })
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                production_main, "_build_network_broker",
                side_effect=AssertionError("LIVE must not construct any client"),
            ):
                with self.assertRaises(SafetyViolation) as ctx:
                    production_main.run_boot()
        self.assertIn("NO-GO", str(ctx.exception))

    def test_build_network_broker_refuses_live(self):
        with self.assertRaises(SafetyViolation) as ctx:
            production_main._build_network_broker(RunMode.LIVE)
        self.assertIn("NO-GO", str(ctx.exception))

    def test_build_network_broker_live_armed_refused_spot_ping_target(self):
        # 授权齐全只代表通过身份与开关检查；构造期 spot ping 目标
        # （主网 api 主机）不在 ALLOWED_LIVE_HOSTS，构造前拒绝是正确结果。
        env = self._scrubbed({
            "TRADING_MODE": "LIVE",
            "TESTNET": "false",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "AURORA_ARM_LIVE": "I_ARM_LIVE_EXECUTION",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
            "AURORA_ACCOUNT_FINGERPRINT": "x",
            "AURORA_LIVE_KEY_SHA256": "x",
        })
        fake = mock.Mock()
        fake.testnet = False
        fake.FUTURES_URL = "https://fapi.binance.com"
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("binance.client.Client", return_value=fake) as ctor:
                # 构造期出站目标校验读取类常量，mock 类需给出真实值
                ctor.API_URL = "https://api{}.binance.{}/api"
                ctor.FUTURES_URL = "https://fapi.binance.{}/fapi"
                ctor.BASE_ENDPOINT_DEFAULT = ""
                with self.assertRaises(SafetyViolation):
                    production_main._build_network_broker(RunMode.LIVE)
                self.assertEqual(ctor.call_count, 0)

    def test_build_network_broker_testnet_uses_testnet_url(self):
        env = self._scrubbed({
            "TRADING_MODE": "TESTNET",
            "TESTNET": "true",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
            "AURORA_ACCOUNT_FINGERPRINT": "x",
        })
        fake = mock.Mock()
        fake.testnet = True
        fake.FUTURES_URL = "https://fapi.binance.com/fapi"
        fake.FUTURES_TESTNET_URL = "https://testnet.binancefuture.com/fapi"
        fake.session = mock.Mock()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("binance.client.Client", return_value=fake) as ctor:
                # 构造期出站目标校验读取类常量，mock 类需给出真实值
                ctor.API_TESTNET_URL = "https://testnet.binance.vision/api"
                ctor.FUTURES_TESTNET_URL = "https://testnet.binancefuture.com/fapi"
                broker = production_main._build_network_broker(RunMode.TESTNET)
        ctor.assert_called_once()
        self.assertTrue(ctor.call_args.kwargs.get("testnet"))
        self.assertEqual(broker.futures_url, "https://testnet.binancefuture.com/fapi")


class ReadOnlyBrokerTests(unittest.TestCase):
    def _broker(self, rows=None):
        class _DummyClient:
            FUTURES_URL = "https://testnet.binancefuture.com"

            def __init__(self, payload):
                self._payload = payload

            def futures_position_information(self, symbol):
                return self._payload

        return production_main.BinanceBroker(_DummyClient(rows), RunMode.TESTNET)

    def test_create_order_refused(self):
        with self.assertRaises(SafetyViolation):
            self._broker([]).create_order(symbol="BTCUSDT", side="BUY", type="MARKET")

    def test_cancel_order_refused(self):
        with self.assertRaises(SafetyViolation):
            self._broker([]).cancel_order("BTCUSDT", "123")

    def test_empty_position_list_is_flat(self):
        snap = self._broker([]).get_position("BTCUSDT")
        self.assertEqual(snap.kind, production_main.PositionQueryKind.FLAT)

    def test_hedge_dual_nonzero_legs_are_unknown(self):
        snap = self._broker([
            {"positionAmt": "0.01", "entryPrice": "100", "positionSide": "LONG"},
            {"positionAmt": "-0.01", "entryPrice": "101", "positionSide": "SHORT"},
        ]).get_position("BTCUSDT")
        self.assertEqual(snap.kind, production_main.PositionQueryKind.UNKNOWN)

    def test_single_open_leg_is_open(self):
        snap = self._broker([
            {"positionAmt": "0.0", "entryPrice": "0", "positionSide": "SHORT"},
            {"positionAmt": "0.02", "entryPrice": "99.5", "positionSide": "LONG"},
        ]).get_position("BTCUSDT")
        self.assertEqual(snap.kind, production_main.PositionQueryKind.OPEN)
        self.assertEqual(snap.side, "LONG")
        self.assertAlmostEqual(snap.size, 0.02)


class BuildClientRefusalTests(unittest.TestCase):
    ENV_KEYS = LiveRefusalOrderTests.ENV_KEYS

    def test_live_build_client_refuses_before_binance_client(self):
        from aurora import safety as safety_mod
        from aurora.safety import build_client

        source = Path(safety_mod.__file__).read_text()
        live_idx = source.find("assert_not_live_trading(mode_enum")
        client_idx = source.find("Client(")
        self.assertGreater(live_idx, 0)
        self.assertGreater(client_idx, live_idx)

        env = {k: v for k, v in os.environ.items() if k not in self.ENV_KEYS}
        env.update({
            "TRADING_MODE": "LIVE",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
        })
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.dict(sys.modules):
                fake_mod = mock.MagicMock()
                sys.modules["binance"] = mock.MagicMock()
                sys.modules["binance.client"] = fake_mod
                with self.assertRaises(SafetyViolation) as ctx:
                    build_client(RunMode.LIVE, "trading")
                fake_mod.Client.assert_not_called()
        self.assertIn("NO-GO", str(ctx.exception))


class RetiredEngineTests(unittest.TestCase):
    def test_execution_engine_constructor_refused(self):
        from aurora.execution_engine import ExecutionEngine
        from aurora.p0_boundary import SafetyViolation

        with self.assertRaises(SafetyViolation):
            ExecutionEngine(object())

    def test_execution_engine_v2_constructor_refused(self):
        from aurora.execution_engine_v2 import ExecutionEngineV2
        from aurora.p0_boundary import SafetyViolation

        with self.assertRaises(SafetyViolation):
            ExecutionEngineV2(object())


if __name__ == "__main__":
    unittest.main()
