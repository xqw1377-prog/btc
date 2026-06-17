from typing import Dict, Any
from datetime import datetime, timedelta
from enum import Enum

class SystemState(Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    RISK_OFF = "RISK_OFF"
    EMERGENCY = "EMERGENCY"

class GlobalRiskEngine:
    def __init__(self):
        self.system_state = SystemState.NORMAL
        
        self.account_limits = {
            'max_leverage': 3.0,
            'max_exposure_pct': 0.30,
            'max_single_position_pct': 0.10
        }
        
        self.system_limits = {
            'max_daily_loss_pct': 0.03,
            'max_drawdown_pct': 0.10,
            'max_consecutive_losses': 5,
            'min_trade_interval_sec': 300
        }
        
        self.market_limits = {
            'max_volatility_multiplier': 3.0,
            'min_liquidity_usd': 1000000,
            'max_spread_pct': 0.005
        }
        
        self.daily_pnl = 0.0
        self.peak_balance = 0.0
        self.current_balance = 0.0
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.trade_count_today = 0
        
        self.kill_switch = False
        self.kill_switch_reason = ""
        self.kill_switch_time = None
        
        self.circuit_breakers = {
            'volatility_spike': False,
            'liquidity_drop': False,
            'connection_loss': False,
            'api_error': False
        }
        
        self.alerts = []
    
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
    
    def check_account_level(self, leverage: float, exposure_pct: float) -> Dict[str, Any]:
        if leverage > self.account_limits['max_leverage']:
            return {
                'approved': False,
                'reason': f'Leverage {leverage} exceeds max {self.account_limits["max_leverage"]}',
                'level': 'ACCOUNT'
            }
        
        if exposure_pct > self.account_limits['max_exposure_pct']:
            return {
                'approved': False,
                'reason': f'Exposure {exposure_pct:.2%} exceeds max {self.account_limits["max_exposure_pct"]:.2%}',
                'level': 'ACCOUNT'
            }
        
        return {'approved': True, 'level': 'ACCOUNT'}
    
    def check_system_level(self, position_size_pct: float) -> Dict[str, Any]:
        if self.kill_switch:
            return {
                'approved': False,
                'reason': self.kill_switch_reason,
                'level': 'SYSTEM',
                'system_state': self.system_state.value
            }
        
        if self.system_state == SystemState.RISK_OFF:
            return {
                'approved': False,
                'reason': 'System in RISK_OFF state',
                'level': 'SYSTEM',
                'system_state': self.system_state.value
            }
        
        if self.last_trade_time:
            elapsed = (datetime.now() - self.last_trade_time).total_seconds()
            if elapsed < self.system_limits['min_trade_interval_sec']:
                return {
                    'approved': False,
                    'reason': f'Min trade interval not met ({elapsed:.0f}s < {self.system_limits["min_trade_interval_sec"]}s)',
                    'level': 'SYSTEM'
                }
        
        return {'approved': True, 'level': 'SYSTEM', 'system_state': self.system_state.value}
    
    def check_market_level(self, volatility: float, avg_volatility: float, spread_pct: float) -> Dict[str, Any]:
        if avg_volatility > 0:
            vol_ratio = volatility / avg_volatility
            if vol_ratio > self.market_limits['max_volatility_multiplier']:
                self.circuit_breakers['volatility_spike'] = True
                return {
                    'approved': False,
                    'reason': f'Volatility spike ({vol_ratio:.2f}x average)',
                    'level': 'MARKET'
                }
        
        if spread_pct > self.market_limits['max_spread_pct']:
            return {
                'approved': False,
                'reason': f'Spread {spread_pct:.4%} exceeds max {self.market_limits["max_spread_pct"]:.4%}',
                'level': 'MARKET'
            }
        
        return {'approved': True, 'level': 'MARKET'}
    
    def validate_trade(
        self,
        leverage: float,
        exposure_pct: float,
        position_size_pct: float,
        volatility: float = 0,
        avg_volatility: float = 0,
        spread_pct: float = 0
    ) -> Dict[str, Any]:
        
        account_check = self.check_account_level(leverage, exposure_pct)
        if not account_check['approved']:
            return account_check
        
        system_check = self.check_system_level(position_size_pct)
        if not system_check['approved']:
            return system_check
        
        market_check = self.check_market_level(volatility, avg_volatility, spread_pct)
        if not market_check['approved']:
            return market_check
        
        return {
            'approved': True,
            'level': 'ALL',
            'system_state': self.system_state.value,
            'risk_multiplier': self._get_risk_multiplier()
        }
    
    def record_trade(self):
        self.last_trade_time = datetime.now()
        self.trade_count_today += 1
    
    def _check_daily_loss(self):
        if self.peak_balance > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.peak_balance
            if daily_loss_pct > self.system_limits['max_daily_loss_pct']:
                self._activate_kill_switch(f'Daily loss limit exceeded ({daily_loss_pct:.2%})')
    
    def _check_drawdown(self):
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            if drawdown > self.system_limits['max_drawdown_pct']:
                self._activate_kill_switch(f'Max drawdown exceeded ({drawdown:.2%})')
    
    def _check_consecutive_losses(self):
        if self.consecutive_losses >= self.system_limits['max_consecutive_losses']:
            self._activate_kill_switch(f'Max consecutive losses ({self.consecutive_losses})')
    
    def _activate_kill_switch(self, reason: str):
        self.kill_switch = True
        self.kill_switch_reason = reason
        self.kill_switch_time = datetime.now()
        self.system_state = SystemState.EMERGENCY
        
        self.alerts.append({
            'type': 'KILL_SWITCH',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
        
        print(f"🚨 KILL SWITCH ACTIVATED: {reason}")
    
    def _get_risk_multiplier(self) -> float:
        if self.system_state == SystemState.EMERGENCY:
            return 0.0
        elif self.system_state == SystemState.RISK_OFF:
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
            self.kill_switch_time = None
            self.system_state = SystemState.NORMAL
            self.consecutive_losses = 0
            self.daily_pnl = 0
            print("Kill switch manually reset")
    
    def set_system_state(self, state: SystemState):
        self.system_state = state
        print(f"System state changed to: {state.value}")
    
    def trigger_circuit_breaker(self, breaker_type: str):
        if breaker_type in self.circuit_breakers:
            self.circuit_breakers[breaker_type] = True
            
            self.alerts.append({
                'type': 'CIRCUIT_BREAKER',
                'breaker': breaker_type,
                'timestamp': datetime.now().isoformat()
            })
            
            self.system_state = SystemState.CAUTION
    
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