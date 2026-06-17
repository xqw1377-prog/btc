from enum import Enum
from datetime import datetime, timedelta
from .types import Order, Direction
from typing import Optional, Callable

class OrderStatus(Enum):
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class ExecutionStateMachine:
    def __init__(self, client):
        self.client = client
        self.current_order: Optional[Order] = None
        self.status = OrderStatus.SENT
        self.created_at = None
        self.retry_count = 0
        self.max_retries = 3
        self.timeout = timedelta(seconds=30)
    
    def send_order(self, order: Order):
        self.current_order = order
        self.status = OrderStatus.SENT
        self.created_at = datetime.now()
        self.retry_count = 0
        
        result = self.client.place_order(order)
        if result:
            self.current_order.id = result.get('id', self.current_order.id)
            self.current_order.status = "PENDING"
        else:
            self.status = OrderStatus.REJECTED
    
    def update_status(self):
        if not self.current_order:
            return
        
        now = datetime.now()
        
        if self.status == OrderStatus.SENT:
            result = self.client.get_order_status(self.current_order.id, self.current_order.symbol)
            if result:
                status = result.get('status')
                if status == 'FILLED':
                    self.status = OrderStatus.FILLED
                    self.current_order.status = "FILLED"
                    self.current_order.filled_size = result.get('filled', 0.0)
                    self.current_order.filled_price = result.get('average', 0.0)
                elif status == 'PARTIALLY_FILLED':
                    self.status = OrderStatus.PARTIAL
                    self.current_order.status = "PARTIAL"
                    self.current_order.filled_size = result.get('filled', 0.0)
                    self.current_order.filled_price = result.get('average', 0.0)
                elif status == 'CANCELED':
                    self.status = OrderStatus.CANCELLED
                    self.current_order.status = "CANCELLED"
                elif status == 'REJECTED':
                    self.status = OrderStatus.REJECTED
                    self.current_order.status = "REJECTED"
        
        if self.created_at and now - self.created_at > self.timeout:
            self.cancel_order()
    
    def check_time_and_price(self) -> str:
        if not self.current_order:
            return "REJECT"
        
        if self.created_at:
            elapsed = (datetime.now() - self.created_at).seconds
            if elapsed > 10:
                return "REPRICE"
        
        return "CONTINUE"
    
    def cancel_order(self):
        if self.current_order:
            self.client.cancel_order(self.current_order.id, self.current_order.symbol)
            self.status = OrderStatus.CANCELLED
            self.current_order.status = "CANCELLED"
    
    def reprice_order(self, new_price: float):
        if self.current_order:
            self.cancel_order()
            self.current_order.price = new_price
            self.send_order(self.current_order)
    
    def execute(self):
        self.update_status()
        
        if self.status == OrderStatus.PARTIAL:
            action = self.check_time_and_price()
            if action == "REPRICE":
                self.reprice_order(self.client.last_price)
            elif action == "REJECT":
                self.cancel_order()
        
        return self.status
    
    def is_complete(self) -> bool:
        return self.status in [OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED]
    
    def get_result(self) -> Optional[Order]:
        return self.current_order if self.status == OrderStatus.FILLED else None
