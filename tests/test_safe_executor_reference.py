"""Legacy SafeExecutor 行为参照（G0-5D 退休归档）。

OFFLINE_REFERENCE_ONLY：这些测试钉住第一代执行封装的语义供研究对照。
它不再是生产执行路径；生产守卫见 tests/test_g05_identity_isolation.py。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.legacy_safe_executor import OrderRecord, OrderState, SafeExecutor  # noqa: E402
from aurora.p0_boundary import (  # noqa: E402
    HaltState,
    restore_or_refuse,
    AccountLock,
    BrainPosition,
    can_open,
    Persistence,
    PositionMode,
    PositionQueryKind,
    PositionSnapshot,
    ReconcileStatus,
    SafetyStore,
    SafetyViolation,
    reconcile,
    query_position,
)


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
