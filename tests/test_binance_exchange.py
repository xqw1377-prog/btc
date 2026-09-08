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
        self.algo_calls = []          # (method, path, signed, kwargs)
        self.orders = {}
        self.algo_orders = {}
        self.trades = []
        self.rows = []
        self.dual_side = "false"
        self.fail_create = None
        self.fail_query = None
        self.fail_cancel = None
        self.fail_position = False
        self.fail_algo = None

    def _request_futures_api(self, method, path, signed=False, version=1, **kwargs):
        self.algo_calls.append((method, path, signed, kwargs))
        if self.fail_algo:
            raise self.fail_algo
        params = kwargs.get("data") or kwargs.get("params") or {}
        cid = params.get("clientAlgoId")
        if method == "post" and path == "algoOrder":
            rec = {
                "algoId": 9000 + len(self.algo_calls),
                "clientAlgoId": cid,
                "algoStatus": "NEW",
                "symbol": params.get("symbol"),
                "side": params.get("side"),
                "positionSide": params.get("positionSide"),
                "type": params.get("type"),
                "triggerPrice": params.get("triggerPrice"),
                "quantity": params.get("quantity"),
                "workingType": params.get("workingType"),
            "closePosition": params.get("closePosition", False),
            }
            self.algo_orders[cid] = rec
            return rec
        if method == "get" and path == "algoOrder":
            if cid not in self.algo_orders:
                raise RuntimeError("algo order does not exist -2013")
            return self.algo_orders[cid]
        if method == "delete" and path == "algoOrder":
            if cid not in self.algo_orders:
                raise RuntimeError("algo order does not exist -2013")
            self.algo_orders[cid]["algoStatus"] = "CANCELED"
            return self.algo_orders[cid]
        raise RuntimeError(f"unexpected api call {method} {path}")

    def futures_get_position_mode(self):
        return {"dualSidePosition": self.dual_side}

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
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ack = ex.submit_order(_req())
        self.assertEqual(ack.status, "FILLED")
        self.assertEqual(client.creates[0]["type"], "MARKET")
        sl = ex.submit_order(_req(OrderKind.STOP_LOSS, "G4-SL", stop=99.0))
        self.assertEqual(sl.status, "NEW")
        # 条件保护腿唯一路径：Algo API；不再调 futures_create_order。
        self.assertEqual(len(client.creates), 1)
        method, path, signed, kwargs = client.algo_calls[0]
        self.assertEqual((method, path), ("post", "algoOrder"))
        params = kwargs["data"]
        self.assertEqual(params["algoType"], "CONDITIONAL")
        self.assertEqual(params["type"], "STOP_MARKET")
        self.assertEqual(params["triggerPrice"], 99.0)
        self.assertEqual(params["quantity"], 0.01)
        self.assertEqual(params["workingType"], "MARK_PRICE")
        self.assertEqual(params["clientAlgoId"], "G4-SL")
        self.assertEqual(params["positionSide"], "BOTH")  # ONE-WAY 合同
        self.assertNotIn("closePosition", params)
        self.assertTrue(params["reduceOnly"])
        self.assertNotIn("newClientOrderId", params)

    def test_algo_submit_side_contract_all_four(self):
        # LONG SL/TP→SELL，SHORT SL/TP→BUY；HEDGE 按腿显式 positionSide。
        cases = (
            (OrderKind.STOP_LOSS, "LONG", "SELL", "a-SL"),
            (OrderKind.TAKE_PROFIT, "LONG", "SELL", "a-TP"),
            (OrderKind.STOP_LOSS, "SHORT", "BUY", "b-SL"),
            (OrderKind.TAKE_PROFIT, "SHORT", "BUY", "b-TP"),
        )
        for kind, position_side, side, cid in cases:
            with self.subTest(kind=kind, position_side=position_side):
                client = RecordingClient()
                ex = BinanceExchange(client, position_mode="HEDGE")
                req = _req(kind, cid, stop=99.0)
                ex.submit_order(OrderRequest(**{
                    **req.__dict__, "side": side,
                    "position_side": position_side,
                }))
                p = client.algo_calls[0][3]["data"]
                self.assertEqual((p["side"], p["positionSide"]),
                                 (side, position_side))
                self.assertNotIn("reduceOnly", p)

    def test_algo_rejects_direction_mismatch_without_retry(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="HEDGE")
        req = _req(OrderKind.STOP_LOSS, "bad-SL", stop=99.0)
        with self.assertRaises(OrderRejectedError):
            ex.submit_order(OrderRequest(**{**req.__dict__, "side": "BUY"}))
        self.assertEqual(client.algo_calls, [])

    def test_unverified_position_mode_refuses_algo_submit(self):
        client = RecordingClient()
        with self.assertRaises(SafetyViolation):
            BinanceExchange(client).submit_order(
                _req(OrderKind.STOP_LOSS, "mode-SL", stop=99.0))
        self.assertEqual(client.algo_calls, [])

    def test_algo_response_missing_identity_is_unknown(self):
        class BadClient(RecordingClient):
            def _request_futures_api(self, *a, **k):
                return {"algoStatus": "NEW"}  # 缺 algoId/clientAlgoId
        with self.assertRaises(SubmitUnknownError):
            BinanceExchange(
                BadClient(), position_mode="ONE_WAY").submit_order(
                _req(OrderKind.STOP_LOSS, "x-SL", stop=99.0))

    def test_algo_terminal_submit_response_is_rejected_not_filled(self):
        for status in ("REJECTED", "CANCELED", "EXPIRED"):
            class TerminalClient(RecordingClient):
                def _request_futures_api(self, *args, **kwargs):
                    raw = super()._request_futures_api(*args, **kwargs)
                    raw["algoStatus"] = status
                    return raw
            with self.subTest(status=status), self.assertRaises(OrderRejectedError):
                BinanceExchange(
                    TerminalClient(), position_mode="ONE_WAY").submit_order(
                    _req(OrderKind.STOP_LOSS, "terminal-SL", stop=99.0))

    def test_algo_submit_timeout_throttle_and_contract_error(self):
        client = RecordingClient()
        client.fail_algo = TimeoutError("read timed out")
        with self.assertRaises(SubmitUnknownError):
            BinanceExchange(client, position_mode="ONE_WAY").submit_order(
                _req(OrderKind.STOP_LOSS, "t-SL", stop=99.0))
        for message in ("HTTP 429 too many requests", "-1003 rate limit",
                        "-1008 system overload", "HTTP 503 service unavailable"):
            client = RecordingClient()
            client.fail_algo = RuntimeError(message)
            with self.assertRaises(SubmitUnknownError):
                BinanceExchange(client, position_mode="ONE_WAY").submit_order(
                    _req(OrderKind.STOP_LOSS, "rate-SL", stop=99.0))
            self.assertEqual(len(client.algo_calls), 1)  # 无自动重提交
        client = RecordingClient()
        client.fail_algo = RuntimeError("-4120 STOP_ORDER_SWITCH_ALGO")
        with self.assertRaises(OrderRejectedError):
            BinanceExchange(client, position_mode="ONE_WAY").submit_order(
                _req(OrderKind.STOP_LOSS, "t-SL", stop=99.0))
        for message in ("TLS handshake failed", "unclassified HTTP 500"):
            client = RecordingClient()
            client.fail_algo = RuntimeError(message)
            with self.assertRaises(SubmitUnknownError):
                BinanceExchange(client, position_mode="ONE_WAY").submit_order(
                    _req(OrderKind.STOP_LOSS, "unknown-SL", stop=99.0))

    def test_legacy_conditional_path_retired(self):
        from aurora.kernel.binance_exchange import BinanceExchange as BE
        client = RecordingClient()
        ex = BE(client)
        with self.assertRaises(OrderRejectedError):
            BE._params(_req(OrderKind.STOP_LOSS, "z-SL", stop=99.0))
        self.assertEqual(client.creates, [])
        self.assertEqual(client.algo_calls, [])

    def test_close_position_mutex_rejected_locally(self):
        from aurora.kernel.binance_exchange import (
            validate_algo_protection_contract)
        with self.assertRaises(OrderRejectedError):
            validate_algo_protection_contract(close_position=True, quantity=0.01)
        with self.assertRaises(OrderRejectedError):
            validate_algo_protection_contract(close_position=True,
                                              reduce_only=True)
        # 合法组合不报错
        validate_algo_protection_contract(close_position=False, quantity=0.01,
                                          reduce_only=True)
        validate_algo_protection_contract(close_position=True)

    def test_algo_query_and_cancel_contract(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.TAKE_PROFIT, "q-TP", stop=110.0))
        fact = ex.query_order("q-TP")
        self.assertEqual(fact.status, "NEW")
        mapped = ex.query_algo_order("q-TP")
        self.assertEqual(mapped.client_algo_id, "q-TP")
        self.assertEqual(mapped.symbol, "BTCUSDT")
        self.assertEqual(mapped.side, "SELL")
        self.assertEqual(mapped.position_side, "BOTH")
        self.assertEqual(mapped.order_type, "TAKE_PROFIT_MARKET")
        self.assertEqual(mapped.trigger_price, 110.0)
        self.assertEqual(mapped.qty, 0.01)
        self.assertFalse(mapped.close_position)
        self.assertEqual(mapped.working_type, "MARK_PRICE")
        self.assertEqual(mapped.status, "NEW")
        get_call = client.algo_calls[-1]
        self.assertEqual(get_call[:3], ("get", "algoOrder", True))
        self.assertEqual(get_call[3]["data"], {"clientAlgoId": "q-TP"})
        self.assertTrue(ex.cancel_order("q-TP"))
        delete_call = client.algo_calls[-1]
        self.assertEqual(delete_call[:3], ("delete", "algoOrder", True))
        self.assertEqual(delete_call[3]["data"], {"clientAlgoId": "q-TP"})
        fact = ex.query_order("q-TP")
        self.assertEqual(fact.status, "CANCELLED")
        fact = ex.query_order("ghost-SL")
        self.assertEqual(fact.status, "NOT_FOUND")

    def test_algo_cancel_timeout_is_unknown_without_retry(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.STOP_LOSS, "cancel-SL", stop=99.0))
        client.fail_algo = TimeoutError("cancel timed out")
        with self.assertRaises(CancelUnknownError):
            ex.cancel_order("cancel-SL")
        self.assertEqual(
            len([c for c in client.algo_calls if c[0] == "delete"]), 1)

    def test_algo_query_incomplete_or_working_type_mismatch_fails_closed(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.STOP_LOSS, "query-SL", stop=99.0))
        del client.algo_orders["query-SL"]["positionSide"]
        with self.assertRaises(RuntimeError):
            ex.query_order("query-SL")

        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.STOP_LOSS, "working-SL", stop=99.0))
        client.algo_orders["working-SL"]["workingType"] = "CONTRACT_PRICE"
        with self.assertRaises(RuntimeError):
            ex.query_order("working-SL")

    def test_algo_triggered_not_treated_as_filled_by_adapter(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.STOP_LOSS, "u-SL", stop=99.0))
        client.algo_orders["u-SL"]["algoStatus"] = "TRIGGERED"
        fact = ex.query_order("u-SL")
        self.assertEqual(fact.status, "TRIGGERED")  # 不是 FILLED
        # TRIGGERED 但 actualOrderId 缺失/为空 → 不得编造 fill
        self.assertEqual(ex.fills("u-SL"), [])
        client.algo_orders["u-SL"]["actualOrderId"] = ""
        self.assertEqual(ex.fills("u-SL"), [])
        # actualOrderId 存在但无权威成交记录 → 仍无财务事实
        client.algo_orders["u-SL"]["actualOrderId"] = "777"
        client.trades = []
        self.assertEqual(ex.fills("u-SL"), [])
        # actualOrderId + 权威成交 → 才能产生 fill
        client.trades = [{"orderId": 777, "id": 1, "qty": "0.01",
                          "price": "99", "commission": "0", "side": "SELL",
                          "time": "t"}]
        fills = ex.fills("u-SL")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].qty, 0.01)

    def test_recovery_suffixes_route_to_algo_query(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        for cid in ("x-SL2", "x-TP3", "x-SL-TOPUP", "x-TP-TOPUP2",
                    "x-SL-R", "x-TP-R2"):
            req = _req(OrderKind.STOP_LOSS if "-SL" in cid
                       else OrderKind.TAKE_PROFIT, cid, stop=99.0)
            ex.submit_order(req)
            ex.query_order(cid)
        self.assertEqual(len(client.creates), 0)
        self.assertEqual(
            len([c for c in client.algo_calls if c[0] == "get"]), 6)

    def test_algo_finished_not_filled(self):
        client = RecordingClient()
        ex = BinanceExchange(client, position_mode="ONE_WAY")
        ex.submit_order(_req(OrderKind.STOP_LOSS, "f-SL", stop=99.0))
        client.algo_orders["f-SL"]["algoStatus"] = "FINISHED"
        fact = ex.query_order("f-SL")
        self.assertEqual(fact.status, "FINISHED")
        self.assertNotEqual(fact.status, "FILLED")

    def test_position_mode_is_external_fact(self):
        client = RecordingClient()
        client.dual_side = "true"
        self.assertEqual(BinanceExchange(client, position_mode="ONE_WAY").position_mode_read(), "HEDGE")
        client.dual_side = "false"
        self.assertEqual(BinanceExchange(client, position_mode="ONE_WAY").position_mode_read(), "ONE_WAY")
        class Bad(RecordingClient):
            def futures_get_position_mode(self):
                raise RuntimeError("down")
        self.assertIsNone(BinanceExchange(Bad()).position_mode_read())
        for bad in ({}, {"dualSidePosition": None},
                    {"dualSidePosition": "garbage"}):
            client = RecordingClient()
            client.futures_get_position_mode = lambda value=bad: value
            self.assertIsNone(BinanceExchange(client).position_mode_read())

        client = RecordingClient()
        client.dual_side = "true"
        ex = BinanceExchange(client)
        with self.assertRaises(SafetyViolation):
            ex.verify_position_mode("ONE_WAY")
        self.assertIsNone(ex.position_mode)
        self.assertEqual(ex.verify_position_mode("HEDGE"), "HEDGE")

    def test_timeout_is_submit_unknown(self):
        client = RecordingClient()
        client.fail_create = TimeoutError("read timed out")
        with self.assertRaises(SubmitUnknownError):
            BinanceExchange(client, position_mode="ONE_WAY").submit_order(_req())

    def test_explicit_reject(self):
        client = RecordingClient()
        client.fail_create = RuntimeError("MIN_NOTIONAL -4164")
        with self.assertRaises(OrderRejectedError):
            BinanceExchange(client, position_mode="ONE_WAY").submit_order(_req())

    def test_query_not_found(self):
        fact = BinanceExchange(RecordingClient()).query_order("missing")
        self.assertEqual(fact.status, "NOT_FOUND")

    def test_cancel_timeout_is_unknown(self):
        client = RecordingClient()
        client.fail_cancel = TimeoutError("cancel timed out")
        with self.assertRaises(CancelUnknownError):
            BinanceExchange(client, position_mode="ONE_WAY").cancel_order("X")

    def test_position_query_failure_is_none(self):
        client = RecordingClient()
        client.fail_position = True
        self.assertIsNone(BinanceExchange(client, position_mode="ONE_WAY").position("BTCUSDT"))

    def test_hedge_dual_legs_are_unknown(self):
        client = RecordingClient()
        client.rows = [
            {"positionAmt": "0.01", "entryPrice": "100"},
            {"positionAmt": "-0.01", "entryPrice": "101"},
        ]
        self.assertIsNone(BinanceExchange(client, position_mode="ONE_WAY").position("BTCUSDT"))

    def test_read_only_refuses_submit_and_cancel(self):
        ex = BinanceExchange(RecordingClient(), allow_mutate=False)
        with self.assertRaises(SafetyViolation):
            ex.submit_order(_req())
        with self.assertRaises(SafetyViolation):
            ex.cancel_order("X")


if __name__ == "__main__":
    unittest.main()
