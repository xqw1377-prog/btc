from typing import Dict, Any, List, Callable
from datetime import datetime, timedelta
from enum import Enum
import asyncio

class EmergencyMode(Enum):
    NORMAL = "NORMAL"
    FREEZE = "FREEZE"
    HEDGE = "HEDGE"
    KILL = "KILL"

class EmergencyTrigger(Enum):
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    API_ERROR_SPIKE = "API_ERROR_SPIKE"
    DATA_DELAY = "DATA_DELAY"
    WS_DISCONNECTED = "WS_DISCONNECTED"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"
    LIQUIDITY_DROP = "LIQUIDITY_DROP"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

class EmergencyController:
    def __init__(self):
        self.current_mode = EmergencyMode.NORMAL
        self.mode_history: List[Dict[str, Any]] = []
        self.triggers: Dict[str, bool] = {}
        self.callbacks: Dict[str, List[Callable]] = {
            'on_kill': [],
            'on_hedge': [],
            'on_freeze': [],
            'on恢复正常': []
        }
        
        self.thresholds = {
            'drawdown_kill': 0.05,
            'drawdown_hedge': 0.03,
            'api_error_rate': 0.1,
            'data_delay_sec': 5.0,
            'volatility_multiplier': 3.0
        }
        
        self.operator_override = False
        self.override_reason = ""
    
    def register_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)
    
    async def _trigger_callbacks(self, event: str, data: Dict[str, Any]):
        for callback in self.callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def check_triggers(
        self,
        drawdown: float = 0,
        api_error_rate: float = 0,
        data_delay: float = 0,
        volatility_ratio: float = 1.0,
        ws_connected: bool = True,
        liquidity_ratio: float = 1.0
    ) -> EmergencyTrigger:
        
        if drawdown >= self.thresholds['drawdown_kill']:
            return EmergencyTrigger.DRAWDOWN_LIMIT
        
        if api_error_rate >= self.thresholds['api_error_rate']:
            return EmergencyTrigger.API_ERROR_SPIKE
        
        if data_delay >= self.thresholds['data_delay_sec']:
            return EmergencyTrigger.DATA_DELAY
        
        if not ws_connected:
            return EmergencyTrigger.WS_DISCONNECTED
        
        if volatility_ratio >= self.thresholds['volatility_multiplier']:
            return EmergencyTrigger.VOLATILITY_SPIKE
        
        if liquidity_ratio < 0.5:
            return EmergencyTrigger.LIQUIDITY_DROP
        
        if drawdown >= self.thresholds['drawdown_hedge']:
            return EmergencyTrigger.DRAWDOWN_LIMIT
        
        return None
    
    async def evaluate(
        self,
        drawdown: float = 0,
        api_error_rate: float = 0,
        data_delay: float = 0,
        volatility_ratio: float = 1.0,
        ws_connected: bool = True,
        liquidity_ratio: float = 1.0
    ) -> EmergencyMode:
        
        if self.operator_override:
            return self.current_mode
        
        trigger = self.check_triggers(
            drawdown, api_error_rate, data_delay,
            volatility_ratio, ws_connected, liquidity_ratio
        )
        
        if trigger is None:
            if self.current_mode != EmergencyMode.NORMAL:
                await self.transition_to(EmergencyMode.NORMAL, "All conditions normal")
            return EmergencyMode.NORMAL
        
        if trigger == EmergencyTrigger.DRAWDOWN_LIMIT:
            if drawdown >= self.thresholds['drawdown_kill']:
                await self.transition_to(EmergencyMode.KILL, f"Drawdown {drawdown:.2%} >= {self.thresholds['drawdown_kill']:.2%}")
            else:
                await self.transition_to(EmergencyMode.HEDGE, f"Drawdown {drawdown:.2%} >= {self.thresholds['drawdown_hedge']:.2%}")
        
        elif trigger == EmergencyTrigger.API_ERROR_SPIKE:
            await self.transition_to(EmergencyMode.FREEZE, f"API error rate {api_error_rate:.2%}")
        
        elif trigger == EmergencyTrigger.DATA_DELAY:
            await self.transition_to(EmergencyMode.FREEZE, f"Data delay {data_delay:.1f}s")
        
        elif trigger == EmergencyTrigger.WS_DISCONNECTED:
            await self.transition_to(EmergencyMode.FREEZE, "WebSocket disconnected")
        
        elif trigger == EmergencyTrigger.VOLATILITY_SPIKE:
            await self.transition_to(EmergencyMode.HEDGE, f"Volatility spike {volatility_ratio:.1f}x")
        
        elif trigger == EmergencyTrigger.LIQUIDITY_DROP:
            await self.transition_to(EmergencyMode.HEDGE, f"Liquidity drop {liquidity_ratio:.2%}")
        
        return self.current_mode
    
    async def transition_to(self, new_mode: EmergencyMode, reason: str):
        if new_mode == self.current_mode:
            return
        
        old_mode = self.current_mode
        self.current_mode = new_mode
        
        self.mode_history.append({
            'from': old_mode.value,
            'to': new_mode.value,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
        
        print(f"🚨 Emergency mode: {old_mode.value} → {new_mode.value} ({reason})")
        
        if new_mode == EmergencyMode.KILL:
            await self._trigger_callbacks('on_kill', {'reason': reason})
        elif new_mode == EmergencyMode.HEDGE:
            await self._trigger_callbacks('on_hedge', {'reason': reason})
        elif new_mode == EmergencyMode.FREEZE:
            await self._trigger_callbacks('on_freeze', {'reason': reason})
        elif new_mode == EmergencyMode.NORMAL:
            await self._trigger_callbacks('on恢复正常', {'reason': reason})
    
    async def manual_override(self, mode: EmergencyMode, reason: str):
        self.operator_override = True
        self.override_reason = reason
        await self.transition_to(mode, f"Manual override: {reason}")
    
    async def release_override(self):
        self.operator_override = False
        self.override_reason = ""
        await self.transition_to(EmergencyMode.NORMAL, "Override released")
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'current_mode': self.current_mode.value,
            'operator_override': self.operator_override,
            'override_reason': self.override_reason,
            'triggers': self.triggers,
            'recent_transitions': self.mode_history[-10:]
        }