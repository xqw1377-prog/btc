from typing import Dict, Any
from datetime import datetime, timedelta
from enum import Enum

class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class RiskEngine:
    def __init__(self):
        self.max_daily_loss = 0.03
        self.max_drawdown = 0.10
        self.max_leverage = 3.0
        self.max_position_size = 0.5
        self.max_consecutive_losses = 5
        
        self.daily_pnl = 0.0
        self.peak_balance = 1.0
        self.current_balance = 1.0
        self.consecutive_losses = 0
        self.last_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        
        self.kill_switch = False
        self.kill_switch_reason = ""
        self.risk_multiplier = 1.0
        self.risk_level = RiskLevel.LOW
        
        self.daily_reset_time = datetime.now()
        self.last_trade_time = None
        self.min_trade_interval = timedelta(minutes=5)
    
    def update_balance(self, balance: float):
        self.current_balance = balance
        
        if balance > self.peak_balance:
            self.peak_balance = balance
        
        self._check_drawdown()
        self._check_daily_reset()
    
    def update_pnl(self, pnl: float):
        self.last_pnl = pnl
        self.daily_pnl += pnl
        
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        self._check_daily_loss()
        self._update_risk_multiplier()
    
    def _check_daily_loss(self):
        if self.daily_pnl < -self.max_daily_loss * self.peak_balance:
            self.kill_switch = True
            print("⚠️  Daily loss limit exceeded - Kill switch activated")
    
    def _check_drawdown(self):
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        
        if drawdown > self.max_drawdown:
            self.kill_switch = True
            print(f"⚠️  Max drawdown exceeded ({drawdown:.2%}) - Kill switch activated")
    
    def _check_daily_reset(self):
        now = datetime.now()
        if now - self.daily_reset_time > self._get_time_until_midnight():
            self.daily_pnl = 0.0
            self.daily_reset_time = now
    
    def _get_time_until_midnight(self):
        now = datetime.now()
        midnight = datetime(now.year, now.month, now.day + 1)
        return midnight - now
    
    def _update_risk_multiplier(self):
        if self.consecutive_losses >= 4:
            self.risk_multiplier = 0.25
            self.risk_level = RiskLevel.CRITICAL
        elif self.consecutive_losses >= 3:
            self.risk_multiplier = 0.5
            self.risk_level = RiskLevel.HIGH
        elif self.consecutive_losses >= 2:
            self.risk_multiplier = 0.75
            self.risk_level = RiskLevel.MEDIUM
        else:
            self.risk_multiplier = 1.0
            self.risk_level = RiskLevel.LOW
    
    def _check_consecutive_losses(self):
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.kill_switch = True
            self.kill_switch_reason = f"Max consecutive losses ({self.max_consecutive_losses}) exceeded"
            print(f"⚠️  {self.kill_switch_reason} - Kill switch activated")
    
    def check_trade_interval(self) -> bool:
        if self.last_trade_time is None:
            return True
        return datetime.now() - self.last_trade_time >= self.min_trade_interval
    
    def record_trade_time(self):
        self.last_trade_time = datetime.now()
    
    def validate_trade(self, position_size: float, leverage: float, market_state: Dict[str, Any] = None) -> Dict[str, Any]:
        if self.kill_switch:
            return {
                'approved': False,
                'reason': self.kill_switch_reason or 'Kill switch active',
                'risk_level': self.risk_level.value
            }
        
        if leverage > self.max_leverage:
            return {
                'approved': False,
                'reason': f'Leverage {leverage} exceeds max {self.max_leverage}',
                'risk_level': self.risk_level.value
            }
        
        if position_size > self.max_position_size:
            return {
                'approved': False,
                'reason': f'Position size {position_size} exceeds max {self.max_position_size}',
                'risk_level': self.risk_level.value
            }
        
        if not self.check_trade_interval():
            return {
                'approved': False,
                'reason': 'Min trade interval not met',
                'risk_level': self.risk_level.value
            }
        
        if market_state:
            confidence = market_state.get('confidence', 0)
            if confidence < 0.5 and self.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                return {
                    'approved': False,
                    'reason': f'Low confidence ({confidence}) with high risk level',
                    'risk_level': self.risk_level.value
                }
        
        return {
            'approved': True,
            'reason': 'Trade approved',
            'risk_level': self.risk_level.value,
            'risk_multiplier': self.risk_multiplier
        }
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        return {
            'daily_pnl': round(self.daily_pnl, 4),
            'max_drawdown': round(drawdown, 4),
            'current_balance': round(self.current_balance, 2),
            'peak_balance': round(self.peak_balance, 2),
            'consecutive_losses': self.consecutive_losses,
            'risk_multiplier': self.risk_multiplier,
            'risk_level': self.risk_level.value,
            'kill_switch': self.kill_switch,
            'kill_switch_reason': self.kill_switch_reason,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': round(win_rate, 2)
        }
    
    def reset_kill_switch(self):
        self.kill_switch = False
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
    
    def get_position_size(self, account_balance: float, price: float, engine_type: str) -> float:
        base_size = 0.4 if engine_type == "TREND" else 0.1
        
        return (account_balance * base_size * self.risk_multiplier) / price
