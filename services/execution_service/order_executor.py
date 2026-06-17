import uuid
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

class OrderExecutor:
    def __init__(self, api_client, symbol: str = "BTCUSDT"):
        self.api = api_client
        self.symbol = symbol
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self.order_timeout = timedelta(seconds=3)
        self.client_id_prefix = "AURORA"
        
        self.stats = {
            'total_orders': 0,
            'filled_orders': 0,
            'cancelled_orders': 0,
            'failed_orders': 0,
            'timeout_orders': 0
        }
    
    def _generate_client_id(self, signal_type: str) -> str:
        unique_id = uuid.uuid4().hex[:8]
        return f"{self.client_id_prefix}_{signal_type}_{unique_id}"
    
    def place_market_order(self, side: str, quantity: float, signal_type: str = "UNKNOWN") -> Dict[str, Any]:
        client_id = self._generate_client_id(signal_type)
        
        try:
            order = self.api.futures_create_order(
                symbol=self.symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                newClientOrderId=client_id
            )
            
            self.active_orders[client_id] = {
                'order_id': order['orderId'],
                'client_id': client_id,
                'side': side,
                'quantity': quantity,
                'status': 'SUBMITTED',
                'submitted_at': datetime.now(),
                'signal_type': signal_type
            }
            
            self.stats['total_orders'] += 1
            
            return {
                'success': True,
                'order_id': order['orderId'],
                'client_id': client_id,
                'status': 'SUBMITTED'
            }
            
        except Exception as e:
            self.stats['failed_orders'] += 1
            return {'success': False, 'error': str(e)}
    
    def place_limit_order(self, side: str, quantity: float, price: float, signal_type: str = "UNKNOWN") -> Dict[str, Any]:
        client_id = self._generate_client_id(signal_type)
        
        try:
            order = self.api.futures_create_order(
                symbol=self.symbol,
                side=side,
                type="LIMIT",
                timeInForce="GTC",
                quantity=quantity,
                price=price,
                newClientOrderId=client_id
            )
            
            self.active_orders[client_id] = {
                'order_id': order['orderId'],
                'client_id': client_id,
                'side': side,
                'quantity': quantity,
                'price': price,
                'status': 'SUBMITTED',
                'submitted_at': datetime.now(),
                'signal_type': signal_type
            }
            
            self.stats['total_orders'] += 1
            
            return {
                'success': True,
                'order_id': order['orderId'],
                'client_id': client_id,
                'status': 'SUBMITTED'
            }
            
        except Exception as e:
            self.stats['failed_orders'] += 1
            return {'success': False, 'error': str(e)}
    
    def verify_order(self, client_id: str) -> Dict[str, Any]:
        if client_id not in self.active_orders:
            return {'success': False, 'error': 'Order not found'}
        
        try:
            order = self.api.futures_get_order(
                symbol=self.symbol,
                origClientOrderId=client_id
            )
            
            status = order['status']
            filled_qty = float(order.get('executedQty', 0))
            avg_price = float(order.get('avgPrice', 0))
            
            self.active_orders[client_id]['status'] = status
            self.active_orders[client_id]['filled_quantity'] = filled_qty
            self.active_orders[client_id]['avg_price'] = avg_price
            
            if status == 'FILLED':
                self.stats['filled_orders'] += 1
                del self.active_orders[client_id]
            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                self.stats['cancelled_orders'] += 1
                del self.active_orders[client_id]
            
            return {
                'success': True,
                'status': status,
                'filled_quantity': filled_qty,
                'avg_price': avg_price
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def check_timeouts(self) -> list:
        cancelled = []
        now = datetime.now()
        
        for client_id in list(self.active_orders.keys()):
            order = self.active_orders[client_id]
            elapsed = now - order['submitted_at']
            
            if elapsed > self.order_timeout:
                try:
                    self.api.futures_cancel_order(
                        symbol=self.symbol,
                        origClientOrderId=client_id
                    )
                    self.stats['timeout_orders'] += 1
                    self.stats['cancelled_orders'] += 1
                    
                    cancelled.append({
                        'client_id': client_id,
                        'reason': 'timeout'
                    })
                    
                    del self.active_orders[client_id]
                except Exception as e:
                    print(f"Cancel timeout error: {e}")
        
        return cancelled
    
    def cancel_order(self, client_id: str) -> Dict[str, Any]:
        if client_id not in self.active_orders:
            return {'success': False, 'error': 'Order not found'}
        
        try:
            self.api.futures_cancel_order(
                symbol=self.symbol,
                origClientOrderId=client_id
            )
            
            self.stats['cancelled_orders'] += 1
            del self.active_orders[client_id]
            
            return {'success': True, 'status': 'CANCELLED'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def cancel_all(self) -> Dict[str, Any]:
        try:
            self.api.futures_cancel_all_open_orders(symbol=self.symbol)
            count = len(self.active_orders)
            self.active_orders.clear()
            self.stats['cancelled_orders'] += count
            return {'success': True, 'cancelled': count}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_position(self) -> Dict[str, Any]:
        try:
            positions = self.api.futures_position_information(symbol=self.symbol)
            for pos in positions:
                if pos['symbol'] == self.symbol:
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
            print(f"Get position error: {e}")
            return {}
    
    def get_balance(self) -> float:
        try:
            account = self.api.futures_account()
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
            return 0.0
        except Exception as e:
            print(f"Get balance error: {e}")
            return 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        stats = self.stats.copy()
        stats['active_orders'] = len(self.active_orders)
        stats['fill_rate'] = stats['filled_orders'] / stats['total_orders'] if stats['total_orders'] > 0 else 0
        return stats