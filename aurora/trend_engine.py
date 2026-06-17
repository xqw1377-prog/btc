from .types import MarketState, Signal, Direction, Position
from datetime import datetime
from typing import Optional, List

class TrendEngine:
    def __init__(self):
        self.position: Optional[Position] = None
        self.entry_price = 0.0
        self.last_structure = ""
        self.add_count = 0
    
    def check_trend_entry(self, state: MarketState) -> bool:
        if state.regime != "TREND":
            return False
        if state.confidence < 0.6:
            return False
        if state.structure not in ["HH/HL", "LL/LH"]:
            return False
        return True
    
    def check_pullback(self, current_price: float, state: MarketState) -> bool:
        if self.position is None:
            return False
        
        if state.structure != self.last_structure:
            return False
        
        if state.direction == "LONG":
            pullback_range = (self.entry_price * 0.98, self.entry_price * 1.01)
            return pullback_range[0] <= current_price <= pullback_range[1]
        else:
            pullback_range = (self.entry_price * 0.99, self.entry_price * 1.02)
            return pullback_range[0] <= current_price <= pullback_range[1]
    
    def check_trend_break(self, state: MarketState) -> bool:
        if self.position is None:
            return False
        
        if state.regime != "TREND":
            return True
        
        if state.direction != self.position.direction:
            return True
        
        if state.structure == "RANGE":
            return True
        
        return False
    
    def generate_signal(self, state: MarketState, current_price: float) -> Signal:
        if self.check_trend_break(state):
            self.position = None
            self.add_count = 0
            return Signal(
                type="EXIT",
                direction=self.position.direction if self.position else "NONE",
                confidence=0.9,
                reason="Trend structure broken"
            )
        
        if self.position is None:
            if self.check_trend_entry(state):
                self.entry_price = current_price
                self.last_structure = state.structure
                return Signal(
                    type="ENTER",
                    direction=state.direction,
                    confidence=state.confidence,
                    reason=f"Trend entry: {state.structure}"
                )
            return Signal(type="NONE", direction="NONE", confidence=0.0, reason="No signal")
        
        if self.add_count < 3 and self.check_pullback(current_price, state):
            self.add_count += 1
            return Signal(
                type="ADD",
                direction=state.direction,
                confidence=min(0.8, state.confidence - 0.1),
                reason=f"Pullback add position #{self.add_count}"
            )
        
        return Signal(type="NONE", direction="NONE", confidence=0.0, reason="No signal")
    
    def update_position(self, signal: Signal, price: float):
        if signal.type == "ENTER":
            self.position = Position(
                symbol="BTCUSDT",
                direction=signal.direction,
                size=0.4,
                entry_price=price,
                open_time=datetime.now(),
                pnl=0.0,
                status="OPEN"
            )
            self.add_count = 0
        elif signal.type == "ADD":
            if self.position:
                avg_price = (self.position.size * self.position.entry_price + 0.3 * price) / (self.position.size + 0.3)
                self.position.size += 0.3
                self.position.entry_price = avg_price
        elif signal.type == "EXIT":
            if self.position:
                self.position.status = "CLOSED"
                self.position.pnl = (price - self.position.entry_price) * self.position.size
