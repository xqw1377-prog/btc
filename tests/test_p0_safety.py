import os
import tempfile
import unittest
from pathlib import Path

from aurora.p0_boundary import (
    AccountLock,
    BrainPosition,
    HaltState,
    Persistence,
    PositionMode,
    PositionQueryKind,
    PositionSnapshot,
    ReconcileStatus,
    RunMode,
    SafetyStore,
    SafetyViolation,
    assert_live_dual_auth,
    boot,
    can_open,
    key_fingerprint,
    query_position,
    reconcile,
    resolve_account_fingerprint,
    resolve_mode,
    restore_or_refuse,
    verify_position_mode,
)
from aurora import production_main


class FakeBroker:
    def __init__(self, url="https://testnet.binancefuture.com"):
        self.futures_url = url
        self.mode = PositionMode.HEDGE
        self.position = PositionSnapshot(kind=PositionQueryKind.FLAT)
        self.orders = {}
        self.create_calls = []
        self.cancel_calls = []
        self.cancel_all_calls = 0
        self.fail_position = False
        self.fail_account = False
        self.fail_types = set()
        self.timeout_once = set()
        self.account_payload = {"assets": []}

    def account(self):
        if self.fail_account:
            raise RuntimeError("account down")
        return self.account_payload

    def get_position_mode(self):
        return self.mode

    def get_position(self, symbol):
        if self.fail_position:
            raise RuntimeError("position query failed")
        return self.position

    def create_order(self, **params):
        self.create_calls.append(params)
        cid = params["newClientOrderId"]
        otype = params.get("type", "MARKET")
        if otype in self.fail_types:
            raise RuntimeError(f"{otype} rejected")
        if cid in self.timeout_once:
            self.timeout_once.discard(cid)
            raise RuntimeError("timeout")
        if cid in self.orders:
            return self.orders[cid]
        if otype == "MARKET" and not params.get("reduceOnly"):
            side = params.get("positionSide") or ("LONG" if params.get("side") == "BUY" else "SHORT")
            self.position = PositionSnapshot(
                kind=PositionQueryKind.OPEN,
                side=side,
                size=float(params["quantity"]),
                entry_price=100.0,
            )
        if otype == "MARKET" and params.get("reduceOnly"):
            self.position = PositionSnapshot(kind=PositionQueryKind.FLAT)
        record = {"orderId": cid, "status": "NEW" if otype != "MARKET" else "FILLED"}
        if otype == "MARKET":
            record["status"] = "FILLED"
        self.orders[cid] = record
        return record

    def get_order(self, symbol, client_order_id):
        if client_order_id not in self.orders:
            raise RuntimeError("unknown order")
        return self.orders[client_order_id]

    def cancel_order(self, symbol, order_id):
        self.cancel_calls.append(order_id)
        return {"orderId": order_id, "status": "CANCELED"}

    def cancel_all(self):
        self.cancel_all_calls += 1
        raise AssertionError("cancel-all must not be called")

    def open_orders(self, symbol):
        return [v for v in self.orders.values() if v.get("status") == "NEW"]


def _tmp_paths():
    tmp = tempfile.TemporaryDirectory()
    persist = os.path.join(tmp.name, "p0.json")
    locks = os.path.join(tmp.name, "locks")
    return tmp, persist, locks


class ModeTests(unittest.TestCase):
    def test_p0_01_default_paper_never_mainnet(self):
        self.assertEqual(resolve_mode({}), RunMode.PAPER)
        tmp, persist, locks = _tmp_paths()
        with tmp:
            ctx = boot(persist, locks, broker=None, environ={"TRADING_MODE": ""})
            self.assertEqual(ctx.mode, RunMode.PAPER)
            self.assertIsNone(ctx.broker)
            with self.assertRaises(SafetyViolation):
                boot(
                    persist,
                    locks,
                    broker=FakeBroker(url="https://fapi.binance.com"),
                    environ={"TRADING_MODE": "PAPER"},
                )

    def test_p0_02_endpoint_and_fingerprint(self):
        key = "test-key-aaa"
        fp = key_fingerprint(key)
        env = {
            "TRADING_MODE": "TESTNET",
            "BINANCE_API_KEY": key,
            "AURORA_ACCOUNT_FINGERPRINT": fp,
        }
        self.assertEqual(resolve_account_fingerprint(RunMode.TESTNET, key, env), fp)
        with self.assertRaises(SafetyViolation):
            resolve_account_fingerprint(
                RunMode.TESTNET, key, {**env, "AURORA_ACCOUNT_FINGERPRINT": "deadbeefdeadbeef"}
            )
        tmp, persist, locks = _tmp_paths()
        with tmp:
            with self.assertRaises(SafetyViolation):
                boot(
                    persist,
                    locks,
                    broker=FakeBroker(url="https://fapi.binance.com"),
                    environ=env,
                )

    def test_p0_03_live_needs_dual_auth(self):
        key = "live-key"
        fp = key_fingerprint(key)
        live_only = {"TRADING_MODE": "LIVE", "BINANCE_API_KEY": key}
        with self.assertRaises(SafetyViolation):
            assert_live_dual_auth(live_only)
        with self.assertRaises(SafetyViolation):
            assert_live_dual_auth({**live_only, "ALLOW_LIVE_TRADING": "true"})
        assert_live_dual_auth({
            **live_only,
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
        })
        tmp, persist, locks = _tmp_paths()
        with tmp:
            with self.assertRaises(SafetyViolation) as ctx:
                boot(
                    persist,
                    locks,
                    broker=FakeBroker(url="https://fapi.binance.com"),
                    environ={
                        "TRADING_MODE": "LIVE",
                        "ALLOW_LIVE_TRADING": "true",
                        "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
                        "BINANCE_API_KEY": key,
                        "AURORA_ACCOUNT_FINGERPRINT": fp,
                        "AURORA_LIVE_KEY_SHA256": fp,
                    },
                )
            self.assertIn("NO-GO", str(ctx.exception))

    def test_p0_03b_live_armed_boot_succeeds(self):
        key = "live-key-armed"
        fp = key_fingerprint(key)
        tmp, persist, locks = _tmp_paths()
        with tmp:
            ctx = boot(
                persist,
                locks,
                broker=FakeBroker(url="https://fapi.binance.com"),
                environ={
                    "TRADING_MODE": "LIVE",
                    "ALLOW_LIVE_TRADING": "true",
                    "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
                    "AURORA_ARM_LIVE": "I_ARM_LIVE_EXECUTION",
                    "BINANCE_API_KEY": key,
                    "AURORA_ACCOUNT_FINGERPRINT": fp,
                    "AURORA_LIVE_KEY_SHA256": fp,
                },
            )
            self.assertEqual(ctx.mode, RunMode.LIVE)
            ctx.lock.release()


class EntryTests(unittest.TestCase):
    def test_p0_12_production_main_cannot_fall_through(self):
        source = Path(production_main.__file__).read_text()
        self.assertNotIn("import aurora_hf_kernel", source)
        self.assertNotIn("import aurora_final", source)
        self.assertNotIn("from aurora_hf_kernel", source)
        self.assertNotIn("from aurora_final", source)
        self.assertIn("aurora_hf_kernel", production_main.FORBIDDEN_IMPORTS)
        from aurora.safety import trading_client

        with self.assertRaises(SafetyViolation):
            trading_client()
        tmp, persist, locks = _tmp_paths()
        with tmp:
            with self.assertRaises(SafetyViolation):
                boot(persist, locks, broker=FakeBroker(), environ={"TRADING_MODE": "NOPE"})

    def test_boot_drift_refuses_start(self):
        key = "k"
        fp = key_fingerprint(key)
        tmp, persist, locks = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            broker.position = PositionSnapshot(kind=PositionQueryKind.OPEN, side="LONG", size=0.2)
            with self.assertRaises(SafetyViolation):
                boot(
                    persist,
                    locks,
                    broker=broker,
                    environ={
                        "TRADING_MODE": "TESTNET",
                        "BINANCE_API_KEY": key,
                        "AURORA_ACCOUNT_FINGERPRINT": fp,
                    },
                )

    def test_position_mode_is_read_only(self):
        broker = FakeBroker()
        broker.mode = PositionMode.ONE_WAY
        with self.assertRaises(SafetyViolation) as ctx:
            verify_position_mode(broker, PositionMode.HEDGE)
        self.assertIn("will not change account mode", str(ctx.exception))

    def test_only_matched_allows_open(self):
        store = SafetyStore()
        rec = reconcile(store, PositionSnapshot(kind=PositionQueryKind.UNKNOWN), "before_open")
        self.assertFalse(can_open(store, rec))
        rec = reconcile(store, PositionSnapshot(kind=PositionQueryKind.FLAT), "before_open")
        self.assertTrue(can_open(store, rec))


if __name__ == "__main__":
    unittest.main()
