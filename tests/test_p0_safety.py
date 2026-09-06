import os
import tempfile
import unittest
from pathlib import Path

from aurora.p0_boundary import (
    AccountLock,
    BrainPosition,
    HaltState,
    OrderState,
    Persistence,
    PositionMode,
    PositionQueryKind,
    PositionSnapshot,
    ReconcileStatus,
    RunMode,
    SafeExecutor,
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


class PositionAndCloseTests(unittest.TestCase):
    def test_p0_04_query_failure_is_unknown(self):
        broker = FakeBroker()
        broker.fail_position = True
        snap = query_position(broker, "BTCUSDT")
        self.assertEqual(snap.kind, PositionQueryKind.UNKNOWN)
        store = SafetyStore()
        rec = reconcile(store, snap, "timer")
        self.assertEqual(rec.status, ReconcileStatus.UNKNOWN)
        self.assertTrue(store.brain.is_open is False)

    def test_p0_05_failed_close_blocks_reverse_open(self):
        tmp, persist, locks = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            store = SafetyStore()
            persist_obj = Persistence(persist)
            persist_obj.save(store)
            ex = SafeExecutor(broker, store, persist_obj)
            opened = ex.execute_open("LONG", 0.01, 90.0, 110.0)
            self.assertTrue(opened["success"])
            broker.fail_types.add("MARKET")
            closed = ex.execute_close()
            self.assertFalse(closed["success"])
            self.assertTrue(store.close_failed)
            broker.fail_types.clear()
            again = ex.execute_open("SHORT", 0.01, 110.0, 90.0)
            self.assertFalse(again["success"])
            self.assertIn("close_failed", again["reason"])


class ProtectAndGhostTests(unittest.TestCase):
    def test_p0_06_protect_fail_flattens_and_halts_forever(self):
        tmp, persist, _ = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            broker.fail_types.add("STOP_MARKET")
            broker.fail_types.add("TAKE_PROFIT_MARKET")
            store = SafetyStore()
            persist_obj = Persistence(persist)
            persist_obj.save(store)
            ex = SafeExecutor(broker, store, persist_obj)
            result = ex.execute_open("LONG", 0.01, 90.0, 110.0)
            self.assertFalse(result["success"])
            self.assertEqual(result["halt"], HaltState.HALTED.value)
            self.assertEqual(query_position(broker, "BTCUSDT").kind, PositionQueryKind.FLAT)
            self.assertEqual(persist_obj.load().halt, HaltState.HALTED)
            with self.assertRaises(SafetyViolation):
                restore_or_refuse(persist_obj)

    def test_p0_06_unknown_flatten_is_recovery_required(self):
        tmp, persist, _ = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            store = SafetyStore()
            persist_obj = Persistence(persist)
            persist_obj.save(store)
            ex = SafeExecutor(broker, store, persist_obj)
            broker.fail_types.add("STOP_MARKET")
            broker.fail_types.add("TAKE_PROFIT_MARKET")
            original_get = broker.get_position

            def flaky(symbol):
                if any(c.get("type") == "MARKET" and c.get("reduceOnly") for c in broker.create_calls):
                    raise RuntimeError("cannot see position")
                return original_get(symbol)

            broker.get_position = flaky
            result = ex.execute_open("LONG", 0.01, 90.0, 110.0)
            self.assertEqual(result["halt"], HaltState.RECOVERY_REQUIRED.value)
            with self.assertRaises(SafetyViolation):
                restore_or_refuse(persist_obj)

    def test_p0_07_exchange_sl_clears_brain_ghost(self):
        store = SafetyStore(brain=BrainPosition(True, "LONG", 0.01, 100.0))
        exchange = PositionSnapshot(kind=PositionQueryKind.FLAT)
        rec = reconcile(store, exchange, "exchange_event")
        self.assertEqual(rec.status, ReconcileStatus.MATCHED)
        self.assertFalse(store.brain.is_open)


class PersistenceAndLockTests(unittest.TestCase):
    def test_p0_08_restart_keeps_risk_and_pending(self):
        tmp, persist, _ = _tmp_paths()
        with tmp:
            store = SafetyStore(
                kill_switch=True,
                kill_reason="daily loss",
                daily_pnl=-120.5,
                drawdown=0.08,
                pending_orders=[{"id": "AURORA_SL_1", "type": "SL"}],
            )
            Persistence(persist).save(store)
            loaded = Persistence(persist).load()
            self.assertTrue(loaded.kill_switch)
            self.assertEqual(loaded.daily_pnl, -120.5)
            self.assertEqual(loaded.drawdown, 0.08)
            self.assertEqual(loaded.pending_orders[0]["id"], "AURORA_SL_1")
            with self.assertRaises(SafetyViolation):
                restore_or_refuse(Persistence(persist))

    def test_p0_09_retry_reuses_client_order_id(self):
        tmp, persist, _ = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            persist_obj = Persistence(persist)
            persist_obj.save(SafetyStore())
            ex = SafeExecutor(broker, persist_obj.load(), persist_obj)
            first = ex._place("AURORA_OPEN_deadbeef", side="BUY", positionSide="LONG", type="MARKET", quantity=0.01)
            second = ex._place("AURORA_OPEN_deadbeef", side="BUY", positionSide="LONG", type="MARKET", quantity=0.01)
            self.assertEqual(first.state, OrderState.FILLED)
            self.assertEqual(second.state, OrderState.FILLED)
            open_calls = [c for c in broker.create_calls if c["newClientOrderId"] == "AURORA_OPEN_deadbeef"]
            self.assertEqual(len(open_calls), 1)

    def test_p0_10_account_lock_is_exclusive(self):
        tmp = tempfile.TemporaryDirectory()
        with tmp:
            a = AccountLock(tmp.name, "abc123abc123abcd")
            b = AccountLock(tmp.name, "abc123abc123abcd")
            a.acquire()
            with self.assertRaises(SafetyViolation):
                b.acquire()
            a.release()
            b.acquire()
            b.release()

    def test_p0_11_cancel_all_forbidden(self):
        tmp, persist, _ = _tmp_paths()
        with tmp:
            broker = FakeBroker()
            persist_obj = Persistence(persist)
            persist_obj.save(SafetyStore())
            ex = SafeExecutor(broker, persist_obj.load(), persist_obj)
            with self.assertRaises(SafetyViolation):
                ex.cancel_all_orders()
            self.assertEqual(broker.cancel_all_calls, 0)
            ex.cancel_order("12345")
            self.assertEqual(broker.cancel_calls, ["12345"])


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
