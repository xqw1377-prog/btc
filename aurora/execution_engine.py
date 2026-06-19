from typing import Dict, Any, Optional
from dataclasses import dataclass
from binance.client import Client

@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    filled_qty: float = 0.0
    filled_price: float = 0.0
    error: Optional[str] = None

class ExecutionEngine:
    def __init__(self, client: Client, symbol: str = "BTCUSDT"):
        self.client = client
        self.symbol = symbol

    def place_order(self, side: str, size_btc: float, sl_price: float, tp_price: float) -> OrderResult:
        if size_btc < 0.001:
            return OrderResult(success=False, error="Size below minimum")

        pos_side = "LONG" if side == "LONG" else "SHORT"
        order_side = "BUY" if side == "LONG" else "SELL"

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=order_side,
                positionSide=pos_side,
                type="MARKET",
                quantity=round(size_btc, 3)
            )

            order_id = order['orderId']

            self._place_sl(pos_side, order_side, size_btc, sl_price)
            self._place_tp(pos_side, order_side, size_btc, tp_price)

            return OrderResult(
                success=True,
                order_id=str(order_id),
                filled_qty=float(order.get('executedQty', size_btc)),
                filled_price=float(order.get('avgPrice', 0))
            )

        except Exception as e:
            return OrderResult(success=False, error=str(e))

    def close_position(self, size_btc: float, side: str) -> OrderResult:
        order_side = "SELL" if side == "LONG" else "BUY"
        pos_side = side

        try:
            self.client.futures_cancel_all_open_orders(symbol=self.symbol)

            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=order_side,
                positionSide=pos_side,
                type="MARKET",
                quantity=round(abs(size_btc), 3)
            )

            return OrderResult(
                success=True,
                order_id=str(order['orderId']),
                filled_qty=float(order.get('executedQty', size_btc)),
                filled_price=float(order.get('avgPrice', 0))
            )

        except Exception as e:
            return OrderResult(success=False, error=str(e))

    def get_position(self) -> Dict[str, Any]:
        try:
            positions = self.client.futures_position_information(symbol=self.symbol)
            for pos in positions:
                amt = float(pos['positionAmt'])
                if amt != 0:
                    return {
                        'side': 'LONG' if amt > 0 else 'SHORT',
                        'size': abs(amt),
                        'entry_price': float(pos['entryPrice']),
                        'unrealized_pnl': float(pos.get('unRealizedProfit', 0)),
                    }
            return {'side': 'NONE', 'size': 0, 'entry_price': 0, 'unrealized_pnl': 0}
        except Exception:
            return {'side': 'NONE', 'size': 0, 'entry_price': 0, 'unrealized_pnl': 0}

    def get_balance(self) -> float:
        try:
            for asset in self.client.futures_account()['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
        except Exception:
            pass
        return 0.0

    def _place_sl(self, pos_side: str, order_side: str, qty: float, sl_price: float):
        sl_side = "SELL" if pos_side == "LONG" else "BUY"
        try:
            self.client.futures_create_order(
                symbol=self.symbol,
                side=sl_side,
                positionSide=pos_side,
                type="STOP_MARKET",
                stopPrice=round(sl_price, 2),
                quantity=round(qty, 3)
            )
        except Exception:
            pass

    def _place_tp(self, pos_side: str, order_side: str, qty: float, tp_price: float):
        tp_side = "SELL" if pos_side == "LONG" else "BUY"
        try:
            self.client.futures_create_order(
                symbol=self.symbol,
                side=tp_side,
                positionSide=pos_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=round(tp_price, 2),
                quantity=round(qty, 3)
            )
        except Exception:
            pass