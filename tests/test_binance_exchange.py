"""BinanceExchange 适配器离线测试：映射、未知结果、双腿仓位。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.binance_exchange import BinanceExchange  # noqa: E402
from aurora.kernel.port import (  # noqa: E402
    CancelUnknownError,
    OrderKind,
    OrderRejectedError,
    OrderRequest,
    SubmitUnknownError,
)
from aurora.p0_boundary import SafetyViolation  # noqa: E402


def _req(kind=OrderKind.ENTRY, cid="E1", reduce_only=False, stop=None):
    return OrderRequest(
        client_order_id=cid,
        symbol="BTCUSDT",
        order_kind=kind,
        side="BUY" if kind == OrderKind.ENTRY else "SELL",
        position_side="LONG",
        quantity=0.01,
        stop_price=stop,
        reduce_only=reduce_only,
    )


class RecordingClient:
    def __init__(self):
        self.creates = []
        self.orders = {}
        self.trades = []
        self.rows = []
        self.fail_create = None
        self.fail_query = None
        self.fail_cancel = None
        self.fail_position = False

    def futures_create_order(self, **params):
        self.creates.append(params)
        if self.fail_create:
            raise self.fail_create
        cid = params["newClientOrderId"]
        if params["type"] == "MARKET":
            rec = {
                "orderId": 1000 + len(self.creates),
                "status": "FILLED",
                "executedQty": params["quantity"],
                "avgPrice": 100.0,
            }
            signed = params["quantity"] if params["side"] == "BUY" else -params["quantity"]
            if params.get("reduceOnly"):
                self.rows = []
            else:
                self.rows = [{"positionAmt": str(signed), "entryPrice": "100"}]
            self.trades.append({
                "orderId": rec["orderId"], "id": rec["orderId"],
                "qty": params["quantity"], "price": 100.0,
                "commission": 0.0, "side": params["side"], "time": "t",
            })
        else:
            rec = {
                "orderId": 2000 + len(self.creates),
                "status": "NEW",
                "executedQty": 0,
                "avgPrice": 0,
            }
        self.orders[cid] = rec
        return rec

    def futures_get_order(self, symbol, origClientOrderId):
        if self.fail_query:
            raise self.fail_query
        if origClientOrderId not in self.orders:
            raise RuntimeError("Order does not exist. -2013")
        return self.orders[origClientOrderId]

    def futures_cancel_order(self, symbol, origClientOrderId):
        if self.fail_cancel:
            raise self.fail_cancel
        if origClientOrderId not in self.orders:
            raise RuntimeError("Order does not exist. -2013")
        self.orders[origClientOrderId]["status"] = "CANCELED"
        return self.orders[origClientOrderId]

    def futures_position_information(self, symbol):
        if self.fail_position:
            raise RuntimeError("position down")
        return self.rows

    def futures_account_trades(self, symbol):
        return list(self.trades)


class BinanceExchangeTests(unittest.TestCase):
    def test_entry_and_protection_params(self):
        client = RecordingClient()
        ex = BinanceExchange(client)
        ack = ex.submit_order(_req())
        self.assertEqual(ack.status, "FILLED")
        self.assertEqual(client.creates[0]["type"], "MARKET")
        sl = ex.submit_order(_req(OrderKind.STOP_LOSS, "SL", stop=99.0))
        self.assertEqual(sl.status, "NEW")
        self.assertEqual(client.creates[1]["type"], "STOP_MARKET")
        self.assertTrue(client.creates[1]["reduceOnly"])

    def test_timeout_is_submit_unknown(self):
        client = RecordingClient()
        client.fail_create = TimeoutError("read timed out")
        with self.assertRaises(SubmitUnknownError):
            BinanceExchange(client).submit_order(_req())

    def test_explicit_reject(self):
        client = RecordingClient()
        client.fail_create = RuntimeError("MIN_NOTIONAL -4164")
        with self.assertRaises(OrderRejectedError):
            BinanceExchange(client).submit_order(_req())

    def test_query_not_found(self):
        fact = BinanceExchange(RecordingClient()).query_order("missing")
        self.assertEqual(fact.status, "NOT_FOUND")

    def test_cancel_timeout_is_unknown(self):
        client = RecordingClient()
        client.fail_cancel = TimeoutError("cancel timed out")
        with self.assertRaises(CancelUnknownError):
            BinanceExchange(client).cancel_order("X")

    def test_position_query_failure_is_none(self):
        client = RecordingClient()
        client.fail_position = True
        self.assertIsNone(BinanceExchange(client).position("BTCUSDT"))

    def test_hedge_dual_legs_are_unknown(self):
        client = RecordingClient()
        client.rows = [
            {"positionAmt": "0.01", "entryPrice": "100"},
            {"positionAmt": "-0.01", "entryPrice": "101"},
        ]
        self.assertIsNone(BinanceExchange(client).position("BTCUSDT"))

    def test_read_only_refuses_submit_and_cancel(self):
        ex = BinanceExchange(RecordingClient(), allow_mutate=False)
        with self.assertRaises(SafetyViolation):
            ex.submit_order(_req())
        with self.assertRaises(SafetyViolation):
            ex.cancel_order("X")


if __name__ == "__main__":
    unittest.main()
