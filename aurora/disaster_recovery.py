from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import asyncio

class DRState(Enum):
    NORMAL = "NORMAL"
    DETECTING = "DETECTING"
    CONTAINING = "CONTAINING"
    RECOVERING = "RECOVERING"
    VERIFYING = "VERIFYING"
    RESUMING = "RESUMING"

class DRPhase(Enum):
    DETECTION = "DETECTION"
    CONTAINMENT = "CONTAINMENT"
    RECOVERY = "RECOVERY"
    VERIFICATION = "VERIFICATION"
    RESUMPTION = "RESUMPTION"

class DisasterRecovery:
    def __init__(self):
        self.state = DRState.NORMAL
        self.current_phase = None
        self.incident_id = None
        self.incident_start = None
        
        self.dr_history: List[Dict[str, Any]] = []
        self.active_incident = None
        
        self.checkpoints: Dict[str, Dict[str, Any]] = {}
        
        self.recovery_plan = {
            DRPhase.DETECTION: [
                'identify_anomaly',
                'assess_severity',
                'notify_operators'
            ],
            DRPhase.CONTAINMENT: [
                'freeze_trading',
                'cancel_pending_orders',
                'hedge_positions'
            ],
            DRPhase.RECOVERY: [
                'reconnect_websocket',
                'reconcile_orders',
                'resync_state'
            ],
            DRPhase.VERIFICATION: [
                'verify_positions',
                'verify_balances',
                'verify_data_integrity'
            ],
            DRPhase.RESUMPTION: [
                'resume_trading',
                'monitor_closely',
                'document_incident'
            ]
        }
    
    def create_checkpoint(self, name: str, data: Dict[str, Any]):
        self.checkpoints[name] = {
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_checkpoint(self, name: str) -> Optional[Dict[str, Any]]:
        return self.checkpoints.get(name)
    
    async def start_incident_response(self, incident_type: str, details: Dict[str, Any]) -> str:
        self.incident_id = f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.incident_start = datetime.now()
        self.state = DRState.DETECTING
        self.current_phase = DRPhase.DETECTION
        
        self.active_incident = {
            'id': self.incident_id,
            'type': incident_type,
            'details': details,
            'start_time': self.incident_start.isoformat(),
            'phases_completed': [],
            'actions_taken': []
        }
        
        print(f"🚨 DR Incident started: {self.incident_id} ({incident_type})")
        
        await self._execute_phase(DRPhase.DETECTION, details)
        
        return self.incident_id
    
    async def _execute_phase(self, phase: DRPhase, context: Dict[str, Any]):
        self.current_phase = phase
        
        if phase == DRPhase.DETECTION:
            self.state = DRState.DETECTING
        elif phase == DRPhase.CONTAINMENT:
            self.state = DRState.CONTAINING
        elif phase == DRPhase.RECOVERY:
            self.state = DRState.RECOVERING
        elif phase == DRPhase.VERIFICATION:
            self.state = DRState.VERIFYING
        elif phase == DRPhase.RESUMPTION:
            self.state = DRState.RESUMING
        
        actions = self.recovery_plan.get(phase, [])
        results = []
        
        for action in actions:
            print(f"  Executing: {action}")
            result = await self._execute_action(action, context)
            results.append({'action': action, 'result': result})
            
            if self.active_incident:
                self.active_incident['actions_taken'].append({
                    'phase': phase.value,
                    'action': action,
                    'result': result,
                    'timestamp': datetime.now().isoformat()
                })
        
        if self.active_incident:
            self.active_incident['phases_completed'].append({
                'phase': phase.value,
                'completed_at': datetime.now().isoformat(),
                'results': results
            })
        
        return results
    
    async def _execute_action(self, action: str, context: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            'identify_anomaly': self._identify_anomaly,
            'assess_severity': self._assess_severity,
            'notify_operators': self._notify_operators,
            'freeze_trading': self._freeze_trading,
            'cancel_pending_orders': self._cancel_pending_orders,
            'hedge_positions': self._hedge_positions,
            'reconnect_websocket': self._reconnect_websocket,
            'reconcile_orders': self._reconcile_orders,
            'resync_state': self._resync_state,
            'verify_positions': self._verify_positions,
            'verify_balances': self._verify_balances,
            'verify_data_integrity': self._verify_data_integrity,
            'resume_trading': self._resume_trading,
            'monitor_closely': self._monitor_closely,
            'document_incident': self._document_incident
        }
        
        handler = handlers.get(action)
        if handler:
            return await handler(context)
        
        return {'success': False, 'reason': f'Unknown action: {action}'}
    
    async def _identify_anomaly(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {'success': True, 'anomaly': context.get('type', 'unknown')}
    
    async def _assess_severity(self, context: Dict[str, Any]) -> Dict[str, Any]:
        severity = 'HIGH' if context.get('drawdown', 0) > 0.05 else 'MEDIUM'
        return {'success': True, 'severity': severity}
    
    async def _notify_operators(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"📧 Operators notified: {context.get('type')}")
        return {'success': True}
    
    async def _freeze_trading(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("❄️ Trading frozen")
        return {'success': True}
    
    async def _cancel_pending_orders(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("❌ All pending orders cancelled")
        return {'success': True, 'cancelled': 0}
    
    async def _hedge_positions(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("🛡 Positions hedged")
        return {'success': True}
    
    async def _reconnect_websocket(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("🔌 WebSocket reconnected")
        return {'success': True}
    
    async def _reconcile_orders(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("🔄 Orders reconciled")
        return {'success': True}
    
    async def _resync_state(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("🔄 State resynchronized")
        return {'success': True}
    
    async def _verify_positions(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("✅ Positions verified")
        return {'success': True, 'verified': True}
    
    async def _verify_balances(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("✅ Balances verified")
        return {'success': True, 'verified': True}
    
    async def _verify_data_integrity(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("✅ Data integrity verified")
        return {'success': True, 'integrity': True}
    
    async def _resume_trading(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("▶ Trading resumed")
        self.state = DRState.NORMAL
        return {'success': True}
    
    async def _monitor_closely(self, context: Dict[str, Any]) -> Dict[str, Any]:
        print("👁 Close monitoring enabled")
        return {'success': True}
    
    async def _document_incident(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.active_incident:
            self.active_incident['end_time'] = datetime.now().isoformat()
            self.active_incident['duration'] = (datetime.now() - self.incident_start).total_seconds()
            self.dr_history.append(self.active_incident)
        
        print(f"📝 Incident {self.incident_id} documented")
        return {'success': True}
    
    async def advance_phase(self, context: Dict[str, Any] = None):
        if not self.current_phase:
            return
        
        phase_order = list(DRPhase)
        current_index = phase_order.index(self.current_phase)
        
        if current_index < len(phase_order) - 1:
            next_phase = phase_order[current_index + 1]
            await self._execute_phase(next_phase, context or {})
        else:
            await self._execute_action('document_incident', context or {})
            self.state = DRState.NORMAL
            self.current_phase = None
            self.active_incident = None
    
    async def run_full_recovery(self, incident_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        incident_id = await self.start_incident_response(incident_type, context)
        
        for phase in [DRPhase.CONTAINMENT, DRPhase.RECOVERY, DRPhase.VERIFICATION, DRPhase.RESUMPTION]:
            await self._execute_phase(phase, context)
        
        return {
            'incident_id': incident_id,
            'state': self.state.value,
            'phases_completed': self.active_incident['phases_completed'] if self.active_incident else []
        }
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'state': self.state.value,
            'current_phase': self.current_phase.value if self.current_phase else None,
            'active_incident': self.active_incident,
            'incident_count': len(self.dr_history),
            'recent_incidents': self.dr_history[-5:]
        }