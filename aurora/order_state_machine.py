from enum import Enum
from typing import Dict, Any, List
from datetime import datetime

class OrderState(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

class OrderEvent(Enum):
    SUBMIT = "SUBMIT"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCEL = "CANCEL"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"
    TIMEOUT = "TIMEOUT"

VALID_TRANSITIONS = {
    OrderState.PENDING: [OrderState.SUBMITTED, OrderState.FAILED],
    OrderState.SUBMITTED: [OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED],
    OrderState.PARTIALLY_FILLED: [OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED],
    OrderState.FILLED: [],
    OrderState.CANCELLED: [],
    OrderState.FAILED: [],
    OrderState.EXPIRED: []
}

EVENT_TO_STATE = {
    OrderEvent.SUBMIT: OrderState.SUBMITTED,
    OrderEvent.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,
    OrderEvent.FILL: OrderState.FILLED,
    OrderEvent.CANCEL: OrderState.CANCELLED,
    OrderEvent.REJECT: OrderState.FAILED,
    OrderEvent.EXPIRE: OrderState.EXPIRED
}

class OrderStateMachine:
    def __init__(self, order_id: int, symbol: str):
        self.order_id = order_id
        self.symbol = symbol
        self.state = OrderState.PENDING
        self.history: List[Dict[str, Any]] = []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.filled_quantity = 0.0
        self.total_quantity = 0.0
        self.avg_price = 0.0
    
    def can_transition(self, new_state: OrderState) -> bool:
        return new_state in VALID_TRANSITIONS.get(self.state, [])
    
    def transition(self, new_state: OrderState, details: Dict[str, Any] = None) -> bool:
        if not self.can_transition(new_state):
            print(f"Invalid transition: {self.state} -> {new_state}")
            return False
        
        old_state = self.state
        self.state = new_state
        self.updated_at = datetime.now()
        
        self.history.append({
            'from': old_state.value,
            'to': new_state.value,
            'timestamp': self.updated_at,
            'details': details or {}
        })
        
        return True
    
    def handle_event(self, event: OrderEvent, details: Dict[str, Any] = None) -> bool:
        new_state = EVENT_TO_STATE.get(event)
        if new_state:
            return self.transition(new_state, details)
        return False
    
    def update_fill(self, filled_qty: float, price: float):
        self.filled_quantity = filled_qty
        if self.total_quantity > 0 and self.filled_quantity >= self.total_quantity:
            self.transition(OrderState.FILLED, {'price': price, 'quantity': filled_qty})
        elif self.filled_quantity > 0:
            self.transition(OrderState.PARTIALLY_FILLED, {'price': price, 'quantity': filled_qty})
        self.avg_price = price
    
    def is_active(self) -> bool:
        return self.state in [OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED]
    
    def is_complete(self) -> bool:
        return self.state in [OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED, OrderState.EXPIRED]
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'state': self.state.value,
            'filled_quantity': self.filled_quantity,
            'total_quantity': self.total_quantity,
            'avg_price': self.avg_price,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'history': self.history
        }