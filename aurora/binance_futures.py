import ccxt
import time
from typing import Dict, Any, Optional
from datetime import datetime

class BinanceFutures:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'test': testnet
            }
        })
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.last_request_time = 0
        self.rate_limit_ms = 100
    
    def _rate_limit(self):
        now = time.time() * 1000
        if now - self.last_request_time < self.rate_limit_ms:
            time.sleep((self.rate_limit_ms - (now - self.last_request_time)) / 1000)
        self.last_request_time = time.time() * 1000
    
    def get_balance(self) -> Dict[str, float]:
        self._rate_limit()
        try:
            balance = self.exchange.fetch_balance()
            return {
                'USDT': balance.get('USDT', {}).get('free', 0.0),
                'BTC': balance.get('BTC', {}).get('free', 0.0)
            }
        except Exception as e:
            print(f"Failed to get balance: {e}")
            return {'USDT': 0.0, 'BTC': 0.0}
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None) -> Dict[str, Any]:
        self._rate_limit()
        
        try:
            params = {
                'symbol': symbol,
                'side': 'BUY' if side == 'LONG' else 'SELL',
                'type': order_type,
                'quantity': quantity
            }
            
            if order_type == 'LIMIT' and price:
                params['price'] = price
            
            result = self.exchange.create_order(**params)
            return {
                'success': True,
                'order_id': result.get('id'),
                'client_order_id': result.get('clientOrderId'),
                'status': result.get('status'),
                'price': result.get('price'),
                'filled_quantity': result.get('filled', 0.0),
                'timestamp': result.get('timestamp')
            }
        
        except Exception as e:
            print(f"Failed to place order: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        self._rate_limit()
        
        try:
            result = self.exchange.fetch_order(order_id, symbol)
            return {
                'success': True,
                'order_id': result.get('id'),
                'status': result.get('status'),
                'price': result.get('price'),
                'quantity': result.get('amount'),
                'filled_quantity': result.get('filled'),
                'average_price': result.get('average')
            }
        
        except Exception as e:
            print(f"Failed to get order: {e}")
            return {'success': False, 'error': str(e)}
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        self._rate_limit()
        
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            print(f"Failed to cancel order: {e}")
            return False
    
    def get_open_orders(self, symbol: str) -> list:
        self._rate_limit()
        
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return [{
                'order_id': order.get('id'),
                'status': order.get('status'),
                'side': order.get('side'),
                'type': order.get('type'),
                'price': order.get('price'),
                'quantity': order.get('amount'),
                'filled_quantity': order.get('filled')
            } for order in orders]
        
        except Exception as e:
            print(f"Failed to get open orders: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._rate_limit()
        
        try:
            positions = self.exchange.fetch_positions([symbol])
            
            if not positions:
                return None
            
            pos = positions[0]
            return {
                'symbol': pos.get('symbol'),
                'side': 'LONG' if pos.get('side') == 'long' else 'SHORT',
                'size': pos.get('contracts', 0.0),
                'entry_price': pos.get('entryPrice', 0.0),
                'mark_price': pos.get('markPrice', 0.0),
                'liquidation_price': pos.get('liquidationPrice', 0.0),
                'unrealized_pnl': pos.get('unrealizedPnl', 0.0),
                'margin': pos.get('margin', 0.0)
            }
        
        except Exception as e:
            print(f"Failed to get position: {e}")
            return None
    
    def get_mark_price(self, symbol: str) -> float:
        self._rate_limit()
        
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker.get('last', 0.0)
        except Exception as e:
            print(f"Failed to get mark price: {e}")
            return 0.0
    
    def get_funding_rate(self, symbol: str) -> float:
        self._rate_limit()
        
        try:
            info = self.exchange.fapiPublicGetFundingrate({'symbol': symbol})
            if info:
                return float(info[-1].get('fundingRate', 0.0))
            return 0.0
        except Exception as e:
            print(f"Failed to get funding rate: {e}")
            return 0.0
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        self._rate_limit()
        
        try:
            self.exchange.fapiPrivatePostLeverage({
                'symbol': symbol,
                'leverage': leverage
            })
            return True
        except Exception as e:
            print(f"Failed to set leverage: {e}")
            return False
    
    def close_position(self, symbol: str) -> Dict[str, Any]:
        position = self.get_position(symbol)
        
        if not position:
            return {'success': False, 'error': 'No open position'}
        
        side = 'SELL' if position['side'] == 'LONG' else 'BUY'
        
        try:
            result = self.exchange.create_order(
                symbol=symbol,
                type='MARKET',
                side=side,
                amount=position['size']
            )
            
            return {
                'success': True,
                'order_id': result.get('id'),
                'filled_price': result.get('average'),
                'pnl': position.get('unrealized_pnl', 0.0)
            }
        
        except Exception as e:
            print(f"Failed to close position: {e}")
            return {'success': False, 'error': str(e)}
