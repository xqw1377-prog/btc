import time
from typing import Dict, Any, Optional
from enum import Enum
from .binance_api import BinanceAPI
from .order_state_machine import OrderStateMachine, OrderState

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"

class OrderExecutor:
    def __init__(self, testnet: bool = True):
        self.api = BinanceAPI(testnet=testnet)
        self.symbol = "BTCUSDT"
        self.active_orders: Dict[int, OrderStateMachine] = {}
        self.order_history = []
        self.slippage_tolerance = 0.001
    
    def get_current_price(self) -> float:
        return self.api.get_price(self.symbol)
    
    def calculate_position_size(self, balance: float, price: float, risk_pct: float, engine_type: str) -> float:
        base_risk = 0.4 if engine_type == "TREND" else 0.1
        position_value = balance * base_risk * risk_pct
        quantity = position_value / price
        
        quantity = round(quantity, 3)
        
        if quantity < 0.001:
            quantity = 0.001
        
        return quantity
    
    def execute_signal(self, signal: Dict[str, Any], balance: float, risk_multiplier: float = 1.0) -> Dict[str, Any]:
        if signal.get('signal') == 'NONE':
            return {'success': False, 'reason': 'No signal'}
        
        engine = signal.get('engine', 'UNKNOWN')
        direction = signal.get('direction', 'LONG')
        side = 'BUY' if direction == 'LONG' else 'SELL'
        
        current_price = self.get_current_price()
        if current_price == 0:
            return {'success': False, 'reason': 'Failed to get price'}
        
        quantity = self.calculate_position_size(
            balance=balance,
            price=current_price,
            risk_pct=risk_multiplier,
            engine_type=engine
        )
        
        result = self._place_safe_order(side, quantity, current_price)
        
        if result.get('success'):
            order_id = result.get('orderId')
            fsm = OrderStateMachine(order_id, self.symbol)
            fsm.transition(OrderState.SUBMITTED)
            self.active_orders[order_id] = fsm
            
            self.order_history.append({
                'orderId': order_id,
                'signal': signal,
                'result': result,
                'timestamp': time.time()
            })
        
        return result
    
    def _place_safe_order(self, side: str, quantity: float, current_price: float) -> Dict[str, Any]:
        result = self.api.place_market_order(self.symbol, side, quantity)
        
        if not result.get('success'):
            limit_price = current_price * (1 + self.slippage_tolerance) if side == 'BUY' else current_price * (1 - self.slippage_tolerance)
            limit_price = round(limit_price, 2)
            result = self.api.place_limit_order(self.symbol, side, quantity, limit_price)
        
        return result
    
    def place_stop_loss(self, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        stop_side = 'SELL' if side == 'BUY' else 'BUY'
        stop_price = round(stop_price, 2)
        return self.api.place_stop_order(self.symbol, stop_side, quantity, stop_price)
    
    def close_position(self, position_amt: float) -> Dict[str, Any]:
        if position_amt == 0:
            return {'success': False, 'reason': 'No position to close'}
        
        side = 'SELL' if position_amt > 0 else 'BUY'
        quantity = abs(position_amt)
        
        result = self.api.place_market_order(self.symbol, side, quantity)
        
        if result.get('success'):
            self.api.cancel_all_orders(self.symbol)
        
        return result
    
    def monitor_orders(self) -> Dict[str, Any]:
        completed = []
        failed = []
        
        for order_id, fsm in list(self.active_orders.items()):
            order_info = self.api.get_order_status(self.symbol, order_id)
            
            if not order_info:
                continue
            
            status = order_info.get('status')
            
            if status == 'FILLED':
                fsm.transition(OrderState.FILLED)
                completed.append(order_id)
                del self.active_orders[order_id]
            elif status == 'CANCELED':
                fsm.transition(OrderState.CANCELLED)
                failed.append(order_id)
                del self.active_orders[order_id]
            elif status == 'REJECTED':
                fsm.transition(OrderState.FAILED)
                failed.append(order_id)
                del self.active_orders[order_id]
        
        return {
            'completed': completed,
            'failed': failed,
            'active': len(self.active_orders)
        }
    
    def get_position_info(self) -> Dict[str, Any]:
        return self.api.get_position(self.symbol)
    
    def get_balance(self) -> float:
        return self.api.get_account_balance()
    
    def emergency_close_all(self) -> Dict[str, Any]:
        position = self.get_position_info()
        if position and position.get('positionAmt', 0) != 0:
            result = self.close_position(position['positionAmt'])
            return result
        return {'success': True, 'reason': 'No position to close'}