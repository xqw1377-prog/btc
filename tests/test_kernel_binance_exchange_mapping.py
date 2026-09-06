"""C3 迁移：P0-B3 请求映射断言 → 现行适配器 BinanceExchange。

原件（tests/test_execution_truth_p0b3.py，已归档至
docs/baseline/reference_tests/）验证已退役 BinancePort 的 raw→typed 映射。
同一业务合同在当前内核适配器上仍然成立：本文件针对
aurora/kernel/binance_exchange.py 重写，使用 MagicMock client，不触网。

仍为 G0-4 的部分（不在本批实现，仅登记）：workingType/closePosition/
timeInForce/price 等条件单字段、HEDGE 与 ONE_WAY 账户模式核对、错误码与
限频语义、真实 testnet 协议验证。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.kernel.binance_exchange import BinanceExchange  # noqa: E402
from aurora.kernel.port import OrderKind, OrderRequest  # noqa: E402


class BinanceExchangeMappingTests(unittest.TestCase):
    def _adapter(self, client):
        return BinanceExchange(client, symbol="BTCUSDT", allow_mutate=True)

    def test_submit_query_cancel_mapping(self):
        client = MagicMock()
        client.futures_create_order.return_value = {
            "orderId": 123,
            "clientOrderId": "AURORA_open_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "positionSide": "LONG",
            "type": "MARKET",
            "origQty": "0.1",
            "status": "FILLED",
            "executedQty": "0.1",
            "avgPrice": "100000.00",
        }
        client.futures_get_order.return_value = client.futures_create_order.return_value
        client.futures_cancel_order.return_value = {
            "orderId": 123,
            "status": "CANCELED",
            "clientOrderId": "AURORA_open_001",
        }
        port = self._adapter(client)

        ack = port.submit_order(OrderRequest(
            client_order_id="AURORA_open_001",
            symbol="BTCUSDT",
            side="BUY",
            position_side="LONG",
            order_kind=OrderKind.ENTRY,
            quantity=0.1,
        ))
        # 请求映射：client_order_id → newClientOrderId，positionSide 透传
        sent = client.futures_create_order.call_args.kwargs
        self.assertEqual(sent["newClientOrderId"], "AURORA_open_001")
        self.assertEqual(sent["positionSide"], "LONG")
        self.assertEqual(sent["type"], "MARKET")
        self.assertEqual(ack.status, "FILLED")
        self.assertEqual(ack.filled_qty, 0.1)
        self.assertEqual(ack.avg_price, 100000.0)
        self.assertEqual(ack.exchange_order_id, "123")

        fact = port.query_order("AURORA_open_001")
        self.assertEqual(fact.status, "FILLED")
        self.assertEqual(fact.filled_qty, 0.1)
        queried = client.futures_get_order.call_args.kwargs
        self.assertEqual(queried["origClientOrderId"], "AURORA_open_001")

        self.assertTrue(port.cancel_order("AURORA_open_001"))

    def test_fills_mapping_includes_fee(self):
        client = MagicMock()
        client.futures_get_order.return_value = {"orderId": 123}
        client.futures_account_trades.return_value = [
            {
                "orderId": 123,
                "id": 9,
                "qty": "0.1",
                "price": "100000.00",
                "commission": "0.05",
                "side": "BUY",
                "time": 1750000000000,
            },
            {"orderId": 999, "id": 10, "qty": "1", "price": "1", "commission": "0", "side": "BUY", "time": 0},
        ]
        port = self._adapter(client)
        fills = port.fills("AURORA_open_001")
        self.assertEqual(len(fills), 1)  # 仅本单 trade，异单过滤
        self.assertEqual(fills[0].fee, 0.05)  # commission → fee
        self.assertEqual(fills[0].qty, 0.1)
        self.assertEqual(fills[0].price, 100000.0)

    def test_position_mapping_long(self):
        client = MagicMock()
        client.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "100000.00"}
        ]
        pos = self._adapter(client).position("BTCUSDT")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.signed_qty, 0.1)
        self.assertEqual(pos.entry_price, 100000.0)

    def test_position_flat(self):
        client = MagicMock()
        client.futures_position_information.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0", "entryPrice": "0"}
        ]
        pos = self._adapter(client).position("BTCUSDT")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.signed_qty, 0.0)

    def test_query_not_found_maps_to_not_found(self):
        client = MagicMock()
        client.futures_get_order.side_effect = Exception("code=-2013 order does not exist")
        fact = self._adapter(client).query_order("missing")
        self.assertEqual(fact.status, "NOT_FOUND")

    def test_read_only_refuses_mutations(self):
        from aurora.p0_boundary import SafetyViolation

        port = BinanceExchange(MagicMock(), symbol="BTCUSDT", allow_mutate=False)
        with self.assertRaises(SafetyViolation):
            port.submit_order(OrderRequest(
                client_order_id="x", symbol="BTCUSDT", side="BUY",
                position_side="LONG", order_kind=OrderKind.ENTRY, quantity=0.1,
            ))
        with self.assertRaises(SafetyViolation):
            port.cancel_order("x")


if __name__ == "__main__":
    unittest.main()
