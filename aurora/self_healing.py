from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

class RecoveryAction:
    def __init__(self, name: str, action_func, priority: int = 0):
        self.name = name
        self.action_func = action_func
        self.priority = priority
        self.last_executed = None
        self.execution_count = 0

class SelfHealingSystem:
    def __init__(self):
        self.recovery_actions: Dict[str, RecoveryAction] = {}
        self.recovery_history: List[Dict[str, Any]] = []
        self.is_recovering = False
        
        self.config = {
            'ws_reconnect_delay_sec': 5,
            'ws_max_reconnect_attempts': 10,
            'order_reconcile_interval_sec': 30,
            'state_resync_interval_sec': 60,
            'max_recovery_attempts': 3
        }
        
        self.state = {
            'ws_reconnect_attempts': 0,
            'last_order_reconcile': None,
            'last_state_resync': None,
            'recovery_attempts': 0
        }
        
        self._setup_recovery_actions()
    
    def _setup_recovery_actions(self):
        self.register_action('reconnect_websocket', self._reconnect_websocket, priority=1)
        self.register_action('reconcile_orders', self._reconcile_orders, priority=2)
        self.register_action('resync_state', self._resync_state, priority=3)
        self.register_action('cancel_stale_orders', self._cancel_stale_orders, priority=4)
        self.register_action('reset_connections', self._reset_connections, priority=5)
    
    def register_action(self, name: str, action_func, priority: int = 0):
        self.recovery_actions[name] = RecoveryAction(name, action_func, priority)
    
    async def _reconnect_websocket(self, ws_client) -> Dict[str, Any]:
        print("Attempting WebSocket reconnection...")
        
        for attempt in range(self.config['ws_max_reconnect_attempts']):
            try:
                ws_client.stop()
                await asyncio.sleep(self.config['ws_reconnect_delay_sec'])
                
                ws_client.start_in_thread()
                await asyncio.sleep(5)
                
                if ws_client.is_connected():
                    self.state['ws_reconnect_attempts'] = 0
                    return {'success': True, 'attempts': attempt + 1}
                
            except Exception as e:
                print(f"Reconnect attempt {attempt + 1} failed: {e}")
        
        self.state['ws_reconnect_attempts'] += 1
        return {'success': False, 'attempts': self.config['ws_max_reconnect_attempts']}
    
    async def _reconcile_orders(self, executor) -> Dict[str, Any]:
        print("Reconciling orders...")
        
        try:
            active_orders = executor.get_active_orders()
            
            for client_id in list(active_orders.keys()):
                result = executor.verify_order(client_id)
                
                if not result.get('success'):
                    executor.cancel_order(client_id)
            
            self.state['last_order_reconcile'] = datetime.now()
            
            return {
                'success': True,
                'reconciled': len(active_orders)
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _resync_state(self, ws_client, feature_engine) -> Dict[str, Any]:
        print("Resyncing state...")
        
        try:
            buffer = ws_client.get_buffer('kline')
            
            if len(buffer) < 100:
                return {'success': False, 'reason': 'Insufficient data'}
            
            import pandas as pd
            df = pd.DataFrame(buffer)
            features = feature_engine.get_latest_features(df)
            
            self.state['last_state_resync'] = datetime.now()
            
            return {
                'success': True,
                'features': features
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _cancel_stale_orders(self, executor) -> Dict[str, Any]:
        print("Cancelling stale orders...")
        
        try:
            result = executor.cancel_all()
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _reset_connections(self, redis_client=None) -> Dict[str, Any]:
        print("Resetting connections...")
        
        results = {}
        
        if redis_client:
            try:
                await redis_client.close()
                await asyncio.sleep(1)
                await redis_client.connect()
                results['redis'] = {'success': True}
            except Exception as e:
                results['redis'] = {'success': False, 'error': str(e)}
        
        return results
    
    async def execute_recovery(self, action_name: str, **kwargs) -> Dict[str, Any]:
        if action_name not in self.recovery_actions:
            return {'success': False, 'error': f'Unknown action: {action_name}'}
        
        action = self.recovery_actions[action_name]
        
        try:
            result = await action.action_func(**kwargs)
            
            action.last_executed = datetime.now()
            action.execution_count += 1
            
            self.recovery_history.append({
                'action': action_name,
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
            
            return result
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def run_recovery_sequence(self, **kwargs) -> Dict[str, Any]:
        if self.is_recovering:
            return {'success': False, 'reason': 'Recovery already in progress'}
        
        self.is_recovering = True
        results = {}
        
        sorted_actions = sorted(
            self.recovery_actions.values(),
            key=lambda a: a.priority
        )
        
        for action in sorted_actions:
            print(f"Executing recovery: {action.name}")
            result = await self.execute_recovery(action.name, **kwargs)
            results[action.name] = result
            
            if not result.get('success') and action.priority <= 2:
                print(f"Critical recovery action failed: {action.name}")
                break
        
        self.is_recovering = False
        self.state['recovery_attempts'] += 1
        
        return {
            'success': all(r.get('success') for r in results.values()),
            'results': results
        }
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'is_recovering': self.is_recovering,
            'state': self.state,
            'recent_recoveries': self.recovery_history[-10:]
        }