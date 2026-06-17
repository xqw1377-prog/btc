from typing import Dict, Any, Optional, Callable
from datetime import datetime
from enum import Enum
import asyncio

class OperatorCommand(Enum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CLOSE_ALL = "CLOSE_ALL"
    CANCEL_ALL = "CANCEL_ALL"
    SWITCH_MODE = "SWITCH_MODE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    MANUAL_ORDER = "MANUAL_ORDER"
    RESET_KILL_SWITCH = "RESET_KILL_SWITCH"

class TradingMode(Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    SEMI_AUTO = "SEMI_AUTO"

class OperatorPanel:
    def __init__(self):
        self.trading_mode = TradingMode.AUTO
        self.is_paused = False
        self.operator_override = False
        self.override_reason = ""
        
        self.command_history: list = []
        self.pending_commands: list = []
        
        self.command_handlers: Dict[OperatorCommand, Callable] = {}
        
        self.permissions = {
            'pause': True,
            'resume': True,
            'close_all': True,
            'cancel_all': True,
            'emergency_stop': True,
            'manual_order': True
        }
    
    def register_handler(self, command: OperatorCommand, handler: Callable):
        self.command_handlers[command] = handler
    
    async def execute_command(self, command: OperatorCommand, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.permissions.get(command.value.lower().replace('_', '_'), True):
            return {'success': False, 'reason': 'Permission denied'}
        
        result = None
        
        if command == OperatorCommand.PAUSE:
            result = await self._pause(params)
        elif command == OperatorCommand.RESUME:
            result = await self._resume(params)
        elif command == OperatorCommand.CLOSE_ALL:
            result = await self._close_all(params)
        elif command == OperatorCommand.CANCEL_ALL:
            result = await self._cancel_all(params)
        elif command == OperatorCommand.EMERGENCY_STOP:
            result = await self._emergency_stop(params)
        elif command == OperatorCommand.MANUAL_ORDER:
            result = await self._manual_order(params)
        elif command == OperatorCommand.SWITCH_MODE:
            result = await self._switch_mode(params)
        elif command == OperatorCommand.RESET_KILL_SWITCH:
            result = await self._reset_kill_switch(params)
        
        if result:
            self.command_history.append({
                'command': command.value,
                'params': params,
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
        
        return result
    
    async def _pause(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        self.is_paused = True
        self.operator_override = True
        self.override_reason = params.get('reason', 'Operator pause') if params else 'Operator pause'
        
        if OperatorCommand.PAUSE in self.command_handlers:
            await self.command_handlers[OperatorCommand.PAUSE](params)
        
        return {'success': True, 'state': 'PAUSED'}
    
    async def _resume(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        self.is_paused = False
        self.operator_override = False
        self.override_reason = ""
        
        if OperatorCommand.RESUME in self.command_handlers:
            await self.command_handlers[OperatorCommand.RESUME](params)
        
        return {'success': True, 'state': 'RESUMED'}
    
    async def _close_all(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if OperatorCommand.CLOSE_ALL in self.command_handlers:
            result = await self.command_handlers[OperatorCommand.CLOSE_ALL](params)
            return result
        
        return {'success': True, 'action': 'CLOSE_ALL'}
    
    async def _cancel_all(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if OperatorCommand.CANCEL_ALL in self.command_handlers:
            result = await self.command_handlers[OperatorCommand.CANCEL_ALL](params)
            return result
        
        return {'success': True, 'action': 'CANCEL_ALL'}
    
    async def _emergency_stop(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        self.is_paused = True
        self.operator_override = True
        self.override_reason = "EMERGENCY STOP"
        self.trading_mode = TradingMode.MANUAL
        
        if OperatorCommand.EMERGENCY_STOP in self.command_handlers:
            await self.command_handlers[OperatorCommand.EMERGENCY_STOP](params)
        
        return {'success': True, 'state': 'EMERGENCY_STOP'}
    
    async def _manual_order(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if self.trading_mode != TradingMode.MANUAL:
            return {'success': False, 'reason': 'Not in MANUAL mode'}
        
        if not params or 'side' not in params or 'quantity' not in params:
            return {'success': False, 'reason': 'Missing order parameters'}
        
        if OperatorCommand.MANUAL_ORDER in self.command_handlers:
            result = await self.command_handlers[OperatorCommand.MANUAL_ORDER](params)
            return result
        
        return {'success': True, 'action': 'MANUAL_ORDER', 'params': params}
    
    async def _switch_mode(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not params or 'mode' not in params:
            return {'success': False, 'reason': 'Missing mode parameter'}
        
        try:
            new_mode = TradingMode(params['mode'])
            self.trading_mode = new_mode
            
            if new_mode == TradingMode.MANUAL:
                self.operator_override = True
                self.override_reason = "Switched to MANUAL mode"
            
            return {'success': True, 'mode': new_mode.value}
        except ValueError:
            return {'success': False, 'reason': f'Invalid mode: {params["mode"]}'}
    
    async def _reset_kill_switch(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if OperatorCommand.RESET_KILL_SWITCH in self.command_handlers:
            result = await self.command_handlers[OperatorCommand.RESET_KILL_SWITCH](params)
            return result
        
        return {'success': True, 'action': 'RESET_KILL_SWITCH'}
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'trading_mode': self.trading_mode.value,
            'is_paused': self.is_paused,
            'operator_override': self.operator_override,
            'override_reason': self.override_reason,
            'recent_commands': self.command_history[-10:]
        }

class TelegramOperatorPanel(OperatorPanel):
    def __init__(self, telegram_alert=None):
        super().__init__()
        self.telegram = telegram_alert
        self._setup_telegram_handlers()
    
    def _setup_telegram_handlers(self):
        self.register_handler(OperatorCommand.PAUSE, self._telegram_pause_handler)
        self.register_handler(OperatorCommand.RESUME, self._telegram_resume_handler)
        self.register_handler(OperatorCommand.EMERGENCY_STOP, self._telegram_emergency_handler)
    
    async def _telegram_pause_handler(self, params):
        if self.telegram:
            await self.telegram.send_message("⏸ Trading PAUSED by operator")
    
    async def _telegram_resume_handler(self, params):
        if self.telegram:
            await self.telegram.send_message("▶ Trading RESUMED by operator")
    
    async def _telegram_emergency_handler(self, params):
        if self.telegram:
            await self.telegram.send_message("🚨 EMERGENCY STOP activated by operator")
    
    async def send_status_update(self):
        if self.telegram:
            status = self.get_status()
            message = f"""
📊 <b>Operator Panel Status</b>

<b>Mode:</b> {status['trading_mode']}
<b>Paused:</b> {status['is_paused']}
<b>Override:</b> {status['operator_override']}
"""
            await self.telegram.send_message(message)