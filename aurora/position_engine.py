from .types import Position, Direction, Signal, Order
from datetime import datetime
from typing import Optional, List

class PositionEngine:
    def __init__(self):
        self.positions: List[Position] = []
        self.risk_limit = 1.0
    
    def get_total_exposure(self) -> float:
        total = 0.0
        for pos in self.positions:
            if pos.status == "OPEN":
                total += pos.size
        return total
    
    def can_open_position(self, size: float) -> bool:
        return self.get_total_exposure() + size <= self.risk_limit
    
    def get_open_position(self, direction: Direction) -> Optional[Position]:
        for pos in self.positions:
            if pos.status == "OPEN" and pos.direction == direction:
                return pos
        return None
    
    def create_order(self, signal: Signal, price: float) -> Optional[Order]:
        if signal.type == "NONE":
            return None
        
        if signal.type in ["ENTER", "ADD"]:
            if signal.type == "ENTER":
                size = 0.4 if signal.direction == "LONG" else 0.4
            else:
                size = 0.3 if self.get_total_exposure() + 0.3 <= self.risk_limit else 0.2
            
            if not self.can_open_position(size):
                return None
            
            order = Order(
                id=f"ORD-{datetime.now().timestamp()}",
                symbol="BTCUSDT",
                type="MARKET",
                side=signal.direction,
                size=size,
                price=None,
                status="PENDING",
                filled_size=0.0,
                filled_price=0.0,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            return order
        
        elif signal.type == "EXIT":
            position = self.get_open_position(signal.direction)
            if position:
                order = Order(
                    id=f"ORD-{datetime.now().timestamp()}",
                    symbol="BTCUSDT",
                    type="MARKET",
                    side="SHORT" if signal.direction == "LONG" else "LONG",
                    size=position.size,
                    price=None,
                    status="PENDING",
                    filled_size=0.0,
                    filled_price=0.0,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                return order
        
        return None
    
    def update_position_from_order(self, order: Order):
        if order.status == "FILLED":
            if order.side == "LONG":
                position = Position(
                    symbol="BTCUSDT",
                    direction="LONG",
                    size=order.filled_size,
                    entry_price=order.filled_price,
                    open_time=order.created_at,
                    pnl=0.0,
                    status="OPEN"
                )
                self.positions.append(position)
            else:
                position = self.get_open_position("LONG")
                if position:
                    position.status = "CLOSED"
                    position.pnl = (order.filled_price - position.entry_price) * position.size
    
    def update_pnl(self, current_price: float):
        for pos in self.positions:
            if pos.status == "OPEN":
                if pos.direction == "LONG":
                    pos.pnl = (current_price - pos.entry_price) * pos.size
                else:
                    pos.pnl = (pos.entry_price - current_price) * pos.size
