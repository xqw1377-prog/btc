from .types import RiskMetrics, MarketState, Signal, Position, SentimentData
from datetime import datetime
from typing import Optional, List

class RiskEngine:
    def __init__(self):
        self.max_daily_loss = 0.1
        self.max_drawdown = 0.15
        self.max_leverage = 3.0
        self.daily_pnl = 0.0
        self.peak_balance = 1.0
        self.consecutive_losses = 0
        self.last_trade_pnl = 0.0
        self.kill_switch = False
        self.sentiment_data: Optional[SentimentData] = None
    
    def update_daily_pnl(self, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        if self.daily_pnl < -self.max_daily_loss:
            self.kill_switch = True
    
    def update_drawdown(self, current_balance: float):
        self.peak_balance = max(self.peak_balance, current_balance)
        drawdown = (self.peak_balance - current_balance) / self.peak_balance
        
        if drawdown > self.max_drawdown:
            self.kill_switch = True
    
    def check_regime_confidence(self, state: MarketState) -> bool:
        return state.confidence >= 0.5
    
    def check_volatility(self, state: MarketState) -> bool:
        return state.volatility < 3.0
    
    def check_consecutive_losses(self) -> float:
        if self.consecutive_losses >= 3:
            return 0.5
        elif self.consecutive_losses >= 2:
            return 0.75
        return 1.0
    
    def get_risk_multiplier(self, state: MarketState) -> float:
        if self.kill_switch:
            return 0.0
        
        if not self.check_regime_confidence(state):
            return 0.3
        
        if not self.check_volatility(state):
            return 0.3
        
        multiplier = self.check_consecutive_losses()
        
        if self.sentiment_data:
            multiplier *= self.sentiment_data.risk_multiplier
        
        return min(multiplier, 1.2)
    
    def validate_signal(self, signal: Signal, state: MarketState, exposure: float) -> bool:
        if self.kill_switch:
            return False
        
        if not self.check_regime_confidence(state):
            return False
        
        if state.volatility > 3.0:
            return False
        
        if exposure > self.max_leverage:
            return False
        
        if signal.type == "ENTER" and self.consecutive_losses >= 3:
            return False
        
        return True
    
    def get_risk_metrics(self) -> RiskMetrics:
        drawdown = (self.peak_balance - max(self.peak_balance + self.daily_pnl, 0.001)) / self.peak_balance
        
        return RiskMetrics(
            daily_pnl=self.daily_pnl,
            max_drawdown=drawdown,
            current_exposure=0.0,
            leverage=0.0,
            consecutive_losses=self.consecutive_losses
        )
    
    def reset_daily_pnl(self):
        self.daily_pnl = 0.0
        self.peak_balance = 1.0 + self.daily_pnl
    
    def set_sentiment(self, sentiment: SentimentData):
        self.sentiment_data = sentiment
