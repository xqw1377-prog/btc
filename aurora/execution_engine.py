from .types import MarketState, Signal, Direction, Position, MarketData
from datetime import datetime
from typing import Optional, List
import numpy as np

class ExecutionEngine:
    def __init__(self):
        self.position: Optional[Position] = None
        self.entry_time = None
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
    
    def calculate_structure_score(self, state: MarketState, data: MarketData) -> float:
        if state.structure in ["HH/HL", "LL/LH"]:
            return 25
        if state.regime == "RANGE":
            dist_to_vwap = abs(data.close - data.vwap) / data.vwap
            if dist_to_vwap < 0.005:
                return 20
            elif dist_to_vwap < 0.01:
                return 15
            else:
                return 5
        return 10
    
    def calculate_momentum_score(self, prices: List[float]) -> float:
        if len(prices) < 10:
            return 10
        
        recent = np.array(prices[-10:])
        prev = np.array(prices[-20:-10])
        
        recent_returns = np.log(recent[1:] / recent[:-1])
        prev_returns = np.log(prev[1:] / prev[:-1])
        
        recent_mean = np.mean(recent_returns)
        prev_mean = np.mean(prev_returns)
        
        if recent_mean > 0.001 and recent_mean > prev_mean * 1.5:
            return 25
        elif recent_mean > 0.0005:
            return 15
        elif abs(recent_mean) < 0.0002:
            return 5
        else:
            return 10
    
    def calculate_volatility_score(self, state: MarketState) -> float:
        if state.volatility < 1.0:
            return 10
        elif state.volatility < 2.0:
            return 20
        elif state.volatility < 3.0:
            return 15
        else:
            return 5
    
    def calculate_liquidity_score(self, volume: float) -> float:
        if volume > 10000:
            return 25
        elif volume > 5000:
            return 20
        elif volume > 2000:
            return 15
        else:
            return 10
    
    def calculate_total_score(self, state: MarketState, data: MarketData, prices: List[float]) -> float:
        structure = self.calculate_structure_score(state, data)
        momentum = self.calculate_momentum_score(prices)
        volatility = self.calculate_volatility_score(state)
        liquidity = self.calculate_liquidity_score(data.volume)
        
        return structure + momentum + volatility + liquidity
    
    def check_fast_kill(self, state: MarketState, data: MarketData, prices: List[float]) -> bool:
        if self.position is None:
            return False
        
        if state.structure != "HH/HL" and state.structure != "LL/LH":
            if abs(data.close - data.vwap) / data.vwap > 0.01:
                return True
        
        if len(prices) >= 5:
            recent_returns = np.log(np.array(prices[-5:])[1:] / np.array(prices[-5:])[:-1])
            if np.mean(recent_returns) < -0.002:
                return True
        
        if self.entry_time:
            elapsed = (datetime.now() - self.entry_time).seconds
            if elapsed > 300:
                return True
        
        return False
    
    def check_take_profit(self, current_price: float) -> bool:
        if self.position is None:
            return False
        
        if self.position.direction == "LONG":
            return current_price >= self.take_profit_price
        else:
            return current_price <= self.take_profit_price
    
    def generate_signal(self, state: MarketState, data: MarketData, prices: List[float]) -> Signal:
        if self.position is not None:
            if self.check_fast_kill(state, data, prices):
                pnl = (data.close - self.position.entry_price) * self.position.size
                self.position.pnl = pnl
                self.position.status = "CLOSED"
                signal = Signal(
                    type="EXIT",
                    direction=self.position.direction,
                    confidence=0.85,
                    reason="Fast kill triggered"
                )
                self.position = None
                return signal
            
            if self.check_take_profit(data.close):
                pnl = (data.close - self.position.entry_price) * self.position.size
                self.position.pnl = pnl
                self.position.status = "CLOSED"
                signal = Signal(
                    type="EXIT",
                    direction=self.position.direction,
                    confidence=0.9,
                    reason="Take profit hit"
                )
                self.position = None
                return signal
        
        if self.position is None:
            score = self.calculate_total_score(state, data, prices)
            
            if score > 75:
                direction: Direction = "LONG" if data.close > data.vwap else "SHORT"
                
                atr = state.atr
                self.stop_loss_price = data.close - atr * 0.5 if direction == "LONG" else data.close + atr * 0.5
                self.take_profit_price = data.close + data.close * 0.01 if direction == "LONG" else data.close - data.close * 0.01
                
                return Signal(
                    type="ENTER",
                    direction=direction,
                    confidence=min(0.9, score / 100),
                    reason=f"Score {score:.1f} > 75"
                )
        
        return Signal(type="NONE", direction="NONE", confidence=0.0, reason="No signal")
    
    def update_position(self, signal: Signal, price: float):
        if signal.type == "ENTER":
            self.position = Position(
                symbol="BTCUSDT",
                direction=signal.direction,
                size=0.05,
                entry_price=price,
                open_time=datetime.now(),
                pnl=0.0,
                status="OPEN"
            )
            self.entry_time = datetime.now()
        elif signal.type == "EXIT":
            if self.position:
                self.position.status = "CLOSED"
                self.position.pnl = (price - self.position.entry_price) * self.position.size
                self.position = None
                self.entry_time = None
