import os
from typing import Dict, Any, Optional
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv

load_dotenv()

class BinanceAPI:
    def __init__(self, testnet: bool = True):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        self.testnet = testnet
        
        if testnet:
            self.client = Client(self.api_key, self.api_secret, testnet=True)
        else:
            self.client = Client(self.api_key, self.api_secret)
    
    def get_price(self, symbol: str = "BTCUSDT") -> float:
        try:
            mark_price = self.client.futures_mark_price(symbol=symbol)
            return float(mark_price['markPrice'])
        except Exception as e:
            print(f"Error getting price: {e}")
            return 0.0
    
    def get_klines(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 500) -> list:
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            return klines
        except Exception as e:
            print(f"Error getting klines: {e}")
            return []
    
    def get_account_balance(self) -> float:
        try:
            account = self.client.futures_account()
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
            return 0.0
        except Exception as e:
            print(f"Error getting balance: {e}")
            return 0.0
    
    def get_position(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if pos['symbol'] == symbol:
                    return {
                        'symbol': pos['symbol'],
                        'positionAmt': float(pos['positionAmt']),
                        'entryPrice': float(pos['entryPrice']),
                        'markPrice': float(pos['markPrice']),
                        'unrealizedPnl': float(pos['unRealizedProfit']),
                        'leverage': int(pos['leverage'])
                    }
            return {}
        except Exception as e:
            print(f"Error getting position: {e}")
            return {}
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=quantity
            )
            return {
                'success': True,
                'orderId': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'type': order['type'],
                'quantity': float(order['origQty']),
                'price': float(order.get('price', 0)),
                'status': order['status']
            }
        except Exception as e:
            print(f"Error placing market order: {e}")
            return {'success': False, 'error': str(e)}
    
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=FUTURE_ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                price=price
            )
            return {
                'success': True,
                'orderId': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'type': order['type'],
                'quantity': float(order['origQty']),
                'price': float(order['price']),
                'status': order['status']
            }
        except Exception as e:
            print(f"Error placing limit order: {e}")
            return {'success': False, 'error': str(e)}
    
    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=stop_price,
                quantity=quantity
            )
            return {
                'success': True,
                'orderId': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'type': order['type'],
                'quantity': float(order['origQty']),
                'stopPrice': stop_price,
                'status': order['status']
            }
        except Exception as e:
            print(f"Error placing stop order: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_order_status(self, symbol: str, order_id: int) -> Dict[str, Any]:
        try:
            order = self.client.futures_get_order(
                symbol=symbol,
                orderId=order_id
            )
            return {
                'orderId': order['orderId'],
                'symbol': order['symbol'],
                'status': order['status'],
                'type': order['type'],
                'side': order['side'],
                'quantity': float(order['origQty']),
                'executedQty': float(order['executedQty']),
                'price': float(order['price']),
                'avgPrice': float(order.get('avgPrice', 0))
            }
        except Exception as e:
            print(f"Error getting order status: {e}")
            return {}
    
    def cancel_order(self, symbol: str, order_id: int) -> bool:
        try:
            result = self.client.futures_cancel_order(
                symbol=symbol,
                orderId=order_id
            )
            return True
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False
    
    def cancel_all_orders(self, symbol: str = "BTCUSDT") -> bool:
        try:
            result = self.client.futures_cancel_all_open_orders(symbol=symbol)
            return True
        except Exception as e:
            print(f"Error cancelling all orders: {e}")
            return False
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            return True
        except Exception as e:
            print(f"Error setting leverage: {e}")
            return False