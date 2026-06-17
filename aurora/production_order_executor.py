import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum

class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

class ProductionOrderExecutor:
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
            'total_slippage': 0.0
        }
    
    def _generate_client_id(self, signal_type: str) -> str:
        unique_id = uuid.uuid4().hex[:8]
        return f"{self.client_id_prefix}_{signal_type}_{unique_id}"
    
    def place_order(
        self,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float = None,
        signal_type: str = "UNKNOWN"
    ) -> Dict[str, Any]:
        
        client_id = self._generate_client_id(signal_type)
        
        if client_id in self.active_orders:
            return {
                'success': False,
                'reason': 'Duplicate order',
                'client_id': client_id
            }
        
        try:
            if order_type == "MARKET":
                order = self.api.futures_create_order(
                    symbol=self.symbol,
                    side=side,
                    type="MARKET",
                    quantity=quantity,
                    newClientOrderId=client_id
                )
            elif order_type == "LIMIT":
                order = self.api.futures_create_order(
                    symbol=self.symbol,
                    side=side,
                    type="LIMIT",
                    timeInForce="GTC",
                    quantity=quantity,
                    price=price,
                    newClientOrderId=client_id
                )
            else:
                return {'success': False, 'reason': f'Unknown order type: {order_type}'}
            
            self.active_orders[client_id] = {
                'order_id': order['orderId'],
                'client_id': client_id,
                'symbol': self.symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity,
                'price': price,
                'status': OrderStatus.SUBMITTED.value,
                'submitted_at': datetime.now(),
                'signal_type': signal_type
            }
            
            self.stats['total_orders'] += 1
            
            return {
                'success': True,
                'order_id': order['orderId'],
                'client_id': client_id,
                'status': OrderStatus.SUBMITTED.value
            }
            
        except Exception as e:
            self.stats['failed_orders'] += 1
            return {
                'success': False,
                'reason': str(e),
                'client_id': client_id
            }
    
    def verify_order(self, client_id: str) -> Dict[str, Any]:
        if client_id not in self.active_orders:
            return {'success': False, 'reason': 'Order not found'}
        
        order_info = self.active_orders[client_id]
        
        try:
            order_status = self.api.futures_get_order(
                symbol=self.symbol,
                origClientOrderId=client_id
            )
            
            status = order_status['status']
            filled_qty = float(order_status.get('executedQty', 0))
            avg_price = float(order_status.get('avgPrice', 0))
            
            if status == 'FILLED':
                order_info['status'] = OrderStatus.FILLED.value
                order_info['filled_quantity'] = filled_qty
                order_info['avg_price'] = avg_price
                order_info['filled_at'] = datetime.now()
                self.stats['filled_orders'] += 1
                
                del self.active_orders[client_id]
                
                return {
                    'success': True,
                    'status': OrderStatus.FILLED.value,
                    'filled_quantity': filled_qty,
                    'avg_price': avg_price
                }
            
            elif status == 'PARTIALLY_FILLED':
                order_info['status'] = OrderStatus.PARTIALLY_FILLED.value
                order_info['filled_quantity'] = filled_qty
                
                return {
                    'success': True,
                    'status': OrderStatus.PARTIALLY_FILLED.value,
                    'filled_quantity': filled_qty
                }
            
            elif status in ['CANCELED', 'REJECTED']:
                order_info['status'] = OrderStatus.CANCELLED.value
                self.stats['cancelled_orders'] += 1
                
                del self.active_orders[client_id]
                
                return {
                    'success': False,
                    'status': status,
                    'reason': order_status.get('status', 'Unknown')
                }
            
            return {
                'success': True,
                'status': status,
                'filled_quantity': filled_qty
            }
            
        except Exception as e:
            return {
                'success': False,
                'reason': str(e)
            }
    
    def check_timeouts(self) -> list:
        cancelled_orders = []
        now = datetime.now()
        
        for client_id in list(self.active_orders.keys()):
            order_info = self.active_orders[client_id]
            submitted_at = order_info['submitted_at']
            
            if now - submitted_at > self.order_timeout:
                try:
                    self.api.futures_cancel_order(
                        symbol=self.symbol,
                        origClientOrderId=client_id
                    )
                    
                    order_info['status'] = OrderStatus.EXPIRED.value
                    self.stats['cancelled_orders'] += 1
                    
                    cancelled_orders.append({
                        'client_id': client_id,
                        'reason': 'Timeout'
                    })
                    
                    del self.active_orders[client_id]
                    
                except Exception as e:
                    print(f"Cancel order error: {e}")
        
        return cancelled_orders
    
    def cancel_order(self, client_id: str) -> Dict[str, Any]:
        if client_id not in self.active_orders:
            return {'success': False, 'reason': 'Order not found'}
        
        try:
            self.api.futures_cancel_order(
                symbol=self.symbol,
                origClientOrderId=client_id
            )
            
            self.active_orders[client_id]['status'] = OrderStatus.CANCELLED.value
            self.stats['cancelled_orders'] += 1
            
            del self.active_orders[client_id]
            
            return {'success': True, 'status': 'CANCELLED'}
            
        except Exception as e:
            return {'success': False, 'reason': str(e)}
    
    def cancel_all_orders(self) -> Dict[str, Any]:
        try:
            self.api.futures_cancel_all_open_orders(symbol=self.symbol)
            
            for client_id in list(self.active_orders.keys()):
                self.active_orders[client_id]['status'] = OrderStatus.CANCELLED.value
            
            count = len(self.active_orders)
            self.active_orders.clear()
            self.stats['cancelled_orders'] += count
            
            return {'success': True, 'cancelled_count': count}
            
        except Exception as e:
            return {'success': False, 'reason': str(e)}
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            'active_orders': len(self.active_orders),
            'fill_rate': self.stats['filled_orders'] / self.stats['total_orders'] if self.stats['total_orders'] > 0 else 0
        }
    
    def get_active_orders(self) -> Dict[str, Any]:
        return self.active_orders