from typing import Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

class SystemState(Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    RISK_OFF = "RISK_OFF"
    EMERGENCY = "EMERGENCY"

class RiskEngine:
    def __init__(self):
        self.system_state = SystemState.NORMAL
        self.kill_switch = False
        self.kill_switch_reason = ""
        
        self.limits = {
            'max_daily_loss_pct': 0.02,
            'max_drawdown_pct': 0.05,
            'max_consecutive_losses': 5,
            'max_leverage': 3.0,
            'max_exposure_pct': 0.30,
            'max_single_position_pct': 0.10,
            'min_trade_interval_sec': 300
        }
        
        self.daily_pnl = 0.0
        self.peak_balance = 0.0
        self.current_balance = 0.0
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.trade_count_today = 0
        
        self.circuit_breakers = {
            'volatility_spike': False,
            'liquidity_drop': False,
            'connection_loss': False,
            'api_error': False
        }
        
        self.alerts: List[Dict[str, Any]] = []
    
    def update_balance(self, balance: float):
        self.current_balance = balance
        if balance > self.peak_balance:
            self.peak_balance = balance
        self._check_drawdown()
    
    def update_pnl(self, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self._check_daily_loss()
        self._check_consecutive_losses()
    
    def _check_daily_loss(self):
        if self.peak_balance > 0:
            loss_pct = abs(min(0, self.daily_pnl)) / self.peak_balance
            if loss_pct > self.limits['max_daily_loss_pct']:
                self._activate_kill_switch(f"Daily loss {loss_pct:.2%} exceeds {self.limits['max_daily_loss_pct']:.2%}")
    
    def _check_drawdown(self):
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            if drawdown > self.limits['max_drawdown_pct']:
                self._activate_kill_switch(f"Drawdown {drawdown:.2%} exceeds {self.limits['max_drawdown_pct']:.2%}")
    
    def _check_consecutive_losses(self):
        if self.consecutive_losses >= self.limits['max_consecutive_losses']:
            self._activate_kill_switch(f"Consecutive losses {self.consecutive_losses} >= {self.limits['max_consecutive_losses']}")
    
    def _activate_kill_switch(self, reason: str):
        self.kill_switch = True
        self.kill_switch_reason = reason
        self.system_state = SystemState.EMERGENCY
        
        alert = {
            'type': 'KILL_SWITCH',
            'reason': reason,
            'severity': 'CRITICAL',
            'timestamp': datetime.now().isoformat()
        }
        self.alerts.append(alert)
        print(f"🚨 KILL SWITCH: {reason}")
    
    def validate_trade(
        self,
        leverage: float = 3.0,
        position_size_pct: float = 0.02,
        volatility: float = 0,
        avg_volatility: float = 0
    ) -> Dict[str, Any]:
        
        if self.kill_switch:
            return {
                'approved': False,
                'reason': f"Kill switch active: {self.kill_switch_reason}",
                'state': self.system_state.value
            }
        
        if self.system_state == SystemState.RISK_OFF:
            return {
                'approved': False,
                'reason': "System in RISK_OFF state",
                'state': self.system_state.value
            }
        
        if leverage > self.limits['max_leverage']:
            return {
                'approved': False,
                'reason': f"Leverage {leverage} > max {self.limits['max_leverage']}",
                'state': self.system_state.value
            }
        
        if position_size_pct > self.limits['max_single_position_pct']:
            return {
                'approved': False,
                'reason': f"Position {position_size_pct:.2%} > max {self.limits['max_single_position_pct']:.2%}",
                'state': self.system_state.value
            }
        
        if self.last_trade_time:
            elapsed = (datetime.now() - self.last_trade_time).total_seconds()
            if elapsed < self.limits['min_trade_interval_sec']:
                return {
                    'approved': False,
                    'reason': f"Trade interval {elapsed:.0f}s < min {self.limits['min_trade_interval_sec']}s",
                    'state': self.system_state.value
                }
        
        if avg_volatility > 0 and volatility > avg_volatility * 3:
            return {
                'approved': False,
                'reason': "Volatility spike detected",
                'state': self.system_state.value
            }
        
        return {
            'approved': True,
            'state': self.system_state.value,
            'risk_multiplier': self._get_risk_multiplier()
        }
    
    def record_trade(self):
        self.last_trade_time = datetime.now()
        self.trade_count_today += 1
    
    def _get_risk_multiplier(self) -> float:
        if self.system_state == SystemState.EMERGENCY:
            return 0.0
        elif self.system_state == SystemState.CAUTION:
            return 0.5
        
        if self.consecutive_losses >= 3:
            return 0.5
        elif self.consecutive_losses >= 2:
            return 0.75
        return 1.0
    
    def reset_kill_switch(self, manual: bool = False):
        if manual:
            self.kill_switch = False
            self.kill_switch_reason = ""
            self.system_state = SystemState.NORMAL
            self.consecutive_losses = 0
            self.daily_pnl = 0
    
    def trigger_circuit_breaker(self, breaker_type: str):
        if breaker_type in self.circuit_breakers:
            self.circuit_breakers[breaker_type] = True
            self.system_state = SystemState.CAUTION
            self.alerts.append({
                'type': 'CIRCUIT_BREAKER',
                'breaker': breaker_type,
                'timestamp': datetime.now().isoformat()
            })
    
    def get_status(self) -> Dict[str, Any]:
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance if self.peak_balance > 0 else 0
        
        return {
            'system_state': self.system_state.value,
            'kill_switch': self.kill_switch,
            'kill_switch_reason': self.kill_switch_reason,
            'daily_pnl': self.daily_pnl,
            'drawdown': drawdown,
            'consecutive_losses': self.consecutive_losses,
            'trade_count_today': self.trade_count_today,
            'risk_multiplier': self._get_risk_multiplier(),
            'circuit_breakers': self.circuit_breakers,
            'alerts': self.alerts[-10:]
        }