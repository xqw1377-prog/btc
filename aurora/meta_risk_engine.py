from typing import Dict, Any
from enum import Enum

class SystemMode(Enum):
    NORMAL = "NORMAL"
    CAUTIOUS = "CAUTIOUS"
    RISK_OFF = "RISK_OFF"
    EMERGENCY = "EMERGENCY"

class MetaRiskEngine:
    def __init__(self):
        self.system_mode = SystemMode.NORMAL
        self.max_system_drawdown = 0.15
        self.volatility_shock_threshold = 3.5
        self.consecutive_loss_limit = 5
        
        self.system_drawdown = 0.0
        self.peak_equity = 1.0
        self.consecutive_losses = 0
        self.correlation_stress = 0.0
        
        self.trend_pnl_history = []
        self.exec_pnl_history = []
    
    def update_system_drawdown(self, current_equity: float):
        self.peak_equity = max(self.peak_equity, current_equity)
        self.system_drawdown = (self.peak_equity - current_equity) / self.peak_equity
    
    def update_pnl_history(self, trend_pnl: float, exec_pnl: float):
        self.trend_pnl_history.append(trend_pnl)
        self.exec_pnl_history.append(exec_pnl)
        
        if len(self.trend_pnl_history) > 20:
            self.trend_pnl_history = self.trend_pnl_history[-20:]
            self.exec_pnl_history = self.exec_pnl_history[-20:]
        
        self._calculate_correlation_stress()
    
    def _calculate_correlation_stress(self):
        if len(self.trend_pnl_history) < 5:
            self.correlation_stress = 0.0
            return
        
        trend_negative = sum(1 for pnl in self.trend_pnl_history[-5:] if pnl < 0)
        exec_negative = sum(1 for pnl in self.exec_pnl_history[-5:] if pnl < 0)
        
        if trend_negative >= 4 and exec_negative >= 4:
            self.correlation_stress = min(1.0, self.correlation_stress + 0.2)
        else:
            self.correlation_stress = max(0.0, self.correlation_stress - 0.1)
    
    def update_consecutive_losses(self, is_loss: bool):
        if is_loss:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
    
    def evaluate_system_mode(self, volatility: float) -> SystemMode:
        if self.system_drawdown > self.max_system_drawdown:
            return SystemMode.EMERGENCY
        
        if self.consecutive_losses >= self.consecutive_loss_limit:
            return SystemMode.RISK_OFF
        
        if volatility > self.volatility_shock_threshold:
            return SystemMode.CAUTIOUS
        
        if self.correlation_stress > 0.7:
            return SystemMode.CAUTIOUS
        
        return SystemMode.NORMAL
    
    def get_risk_multiplier(self) -> float:
        if self.system_mode == SystemMode.EMERGENCY:
            return 0.1
        elif self.system_mode == SystemMode.RISK_OFF:
            return 0.3
        elif self.system_mode == SystemMode.CAUTIOUS:
            return 0.6
        return 1.0
    
    def should_trade(self) -> bool:
        return self.system_mode != SystemMode.EMERGENCY
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            'system_mode': self.system_mode.value,
            'system_drawdown': round(self.system_drawdown * 100, 2),
            'peak_equity': round(self.peak_equity, 2),
            'consecutive_losses': self.consecutive_losses,
            'correlation_stress': round(self.correlation_stress, 2),
            'risk_multiplier': self.get_risk_multiplier()
        }
    
    def reset(self):
        self.system_drawdown = 0.0
        self.peak_equity = 1.0
        self.consecutive_losses = 0
        self.correlation_stress = 0.0
        self.system_mode = SystemMode.NORMAL
