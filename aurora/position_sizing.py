import numpy as np
from typing import Dict, Any, Optional

class PositionSizing:
    def __init__(self):
        self.default_risk_per_trade = 0.01
        self.max_position_size = 0.5
        self.min_position_size = 0.05
    
    def kelly_criterion(self, win_rate: float, reward_risk: float) -> float:
        if win_rate <= 0 or reward_risk <= 0:
            return 0.0
        
        kelly_fraction = win_rate - (1 - win_rate) / reward_risk
        
        return max(0.0, min(kelly_fraction, 0.2))
    
    def volatility_sizing(self, volatility: float, target_risk: float = 0.01) -> float:
        if volatility <= 0:
            return self.min_position_size
        
        position_size = target_risk / volatility
        
        return max(self.min_position_size, min(position_size, self.max_position_size))
    
    def regime_based_sizing(self, regime: str, confidence: float, base_size: float = 0.1) -> float:
        if regime == "TREND":
            return base_size * (1 + confidence)
        elif regime == "RANGE":
            return base_size * 0.7
        elif regime == "TRANSITION":
            return base_size * 0.3
        return base_size
    
    def get_position_size(self, 
                          balance: float, 
                          price: float, 
                          regime: str, 
                          confidence: float,
                          volatility: float,
                          win_rate: Optional[float] = None,
                          reward_risk: Optional[float] = None) -> float:
        
        if win_rate and reward_risk:
            kelly_size = self.kelly_criterion(win_rate, reward_risk)
            vol_size = self.volatility_sizing(volatility)
            regime_size = self.regime_based_sizing(regime, confidence)
            
            size = min(kelly_size, vol_size, regime_size)
        else:
            vol_size = self.volatility_sizing(volatility)
            regime_size = self.regime_based_sizing(regime, confidence)
            size = min(vol_size, regime_size)
        
        size = max(self.min_position_size, min(size, self.max_position_size))
        
        return (balance * size) / price
    
    def calculate_stop_loss(self, entry_price: float, atr: float, risk_pct: float = 0.01) -> float:
        if atr <= 0:
            return entry_price * (1 - risk_pct)
        
        stop_distance = atr * 1.5
        
        return entry_price - stop_distance
    
    def calculate_take_profit(self, entry_price: float, stop_loss: float, reward_risk: float = 2.0) -> float:
        risk_distance = entry_price - stop_loss
        return entry_price + risk_distance * reward_risk
