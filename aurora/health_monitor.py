from typing import Dict, Any, List
from datetime import datetime, timedelta
from collections import deque
import asyncio

class HealthStatus:
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    CRITICAL = "CRITICAL"

class HealthCheck:
    def __init__(self, name: str, check_func, interval_sec: int = 60):
        self.name = name
        self.check_func = check_func
        self.interval_sec = interval_sec
        self.last_check = None
        self.last_status = None
        self.last_error = None
        self.history: deque = deque(maxlen=100)

class HealthMonitor:
    def __init__(self):
        self.checks: Dict[str, HealthCheck] = {}
        self.overall_status = HealthStatus.HEALTHY
        self.status_history: deque = deque(maxlen=1000)
        
        self.metrics = {
            'ws_connected': False,
            'ws_last_update': 0,
            'ws_reconnect_count': 0,
            'api_error_count': 0,
            'api_success_count': 0,
            'api_latency_ms': deque(maxlen=100),
            'data_delay_sec': 0,
            'order_fill_rate': 0,
            'order_timeout_count': 0,
            'memory_usage_mb': 0,
            'cpu_usage_pct': 0
        }
        
        self._setup_default_checks()
    
    def _setup_default_checks(self):
        self.register_check('websocket', self._check_websocket, 30)
        self.register_check('api_health', self._check_api_health, 60)
        self.register_check('data_freshness', self._check_data_freshness, 30)
        self.register_check('order_health', self._check_order_health, 60)
        self.register_check('system_resources', self._check_system_resources, 120)
    
    def register_check(self, name: str, check_func, interval_sec: int = 60):
        self.checks[name] = HealthCheck(name, check_func, interval_sec)
    
    async def _check_websocket(self) -> Dict[str, Any]:
        connected = self.metrics['ws_connected']
        last_update = self.metrics['ws_last_update']
        delay = datetime.now().timestamp() - last_update if last_update > 0 else float('inf')
        
        if not connected:
            return {'status': HealthStatus.CRITICAL, 'message': 'WebSocket disconnected'}
        
        if delay > 60:
            return {'status': HealthStatus.UNHEALTHY, 'message': f'No data for {delay:.0f}s'}
        
        if delay > 30:
            return {'status': HealthStatus.DEGRADED, 'message': f'Data delay {delay:.0f}s'}
        
        return {'status': HealthStatus.HEALTHY, 'message': 'Connected'}
    
    async def _check_api_health(self) -> Dict[str, Any]:
        total = self.metrics['api_error_count'] + self.metrics['api_success_count']
        
        if total == 0:
            return {'status': HealthStatus.HEALTHY, 'message': 'No API calls yet'}
        
        error_rate = self.metrics['api_error_count'] / total
        
        if error_rate > 0.1:
            return {'status': HealthStatus.CRITICAL, 'message': f'API error rate {error_rate:.1%}'}
        
        if error_rate > 0.05:
            return {'status': HealthStatus.UNHEALTHY, 'message': f'API error rate {error_rate:.1%}'}
        
        if error_rate > 0.01:
            return {'status': HealthStatus.DEGRADED, 'message': f'API error rate {error_rate:.1%}'}
        
        return {'status': HealthStatus.HEALTHY, 'message': f'Error rate {error_rate:.2%}'}
    
    async def _check_data_freshness(self) -> Dict[str, Any]:
        delay = self.metrics['data_delay_sec']
        
        if delay > 10:
            return {'status': HealthStatus.CRITICAL, 'message': f'Data delay {delay:.1f}s'}
        
        if delay > 5:
            return {'status': HealthStatus.UNHEALTHY, 'message': f'Data delay {delay:.1f}s'}
        
        if delay > 2:
            return {'status': HealthStatus.DEGRADED, 'message': f'Data delay {delay:.1f}s'}
        
        return {'status': HealthStatus.HEALTHY, 'message': f'Delay {delay:.1f}s'}
    
    async def _check_order_health(self) -> Dict[str, Any]:
        fill_rate = self.metrics['order_fill_rate']
        timeouts = self.metrics['order_timeout_count']
        
        if fill_rate < 0.9 and fill_rate > 0:
            return {'status': HealthStatus.UNHEALTHY, 'message': f'Fill rate {fill_rate:.1%}'}
        
        if timeouts > 5:
            return {'status': HealthStatus.DEGRADED, 'message': f'{timeouts} order timeouts'}
        
        return {'status': HealthStatus.HEALTHY, 'message': f'Fill rate {fill_rate:.1%}'}
    
    async def _check_system_resources(self) -> Dict[str, Any]:
        memory = self.metrics['memory_usage_mb']
        cpu = self.metrics['cpu_usage_pct']
        
        if memory > 1024 or cpu > 90:
            return {'status': HealthStatus.UNHEALTHY, 'message': f'Memory {memory}MB, CPU {cpu}%'}
        
        if memory > 512 or cpu > 70:
            return {'status': HealthStatus.DEGRADED, 'message': f'Memory {memory}MB, CPU {cpu}%'}
        
        return {'status': HealthStatus.HEALTHY, 'message': f'Memory {memory}MB, CPU {cpu}%'}
    
    async def run_checks(self):
        results = {}
        
        for name, check in self.checks.items():
            now = datetime.now().timestamp()
            
            if check.last_check and (now - check.last_check) < check.interval_sec:
                continue
            
            try:
                result = await check.check_func()
                check.last_status = result['status']
                check.last_error = None
                check.last_check = now
                check.history.append({
                    'status': result['status'],
                    'message': result['message'],
                    'timestamp': now
                })
                results[name] = result
            except Exception as e:
                check.last_status = HealthStatus.CRITICAL
                check.last_error = str(e)
                check.last_check = now
                results[name] = {'status': HealthStatus.CRITICAL, 'message': str(e)}
        
        self._update_overall_status()
        return results
    
    def _update_overall_status(self):
        statuses = [check.last_status for check in self.checks.values() if check.last_status]
        
        if not statuses:
            self.overall_status = HealthStatus.HEALTHY
        elif HealthStatus.CRITICAL in statuses:
            self.overall_status = HealthStatus.CRITICAL
        elif HealthStatus.UNHEALTHY in statuses:
            self.overall_status = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            self.overall_status = HealthStatus.DEGRADED
        else:
            self.overall_status = HealthStatus.HEALTHY
        
        self.status_history.append({
            'status': self.overall_status,
            'timestamp': datetime.now().timestamp()
        })
    
    def update_metric(self, metric: str, value: Any):
        if metric in self.metrics:
            if isinstance(self.metrics[metric], deque):
                self.metrics[metric].append(value)
            else:
                self.metrics[metric] = value
    
    def increment_metric(self, metric: str, amount: int = 1):
        if metric in self.metrics and isinstance(self.metrics[metric], (int, float)):
            self.metrics[metric] += amount
    
    def get_api_latency_avg(self) -> float:
        latencies = self.metrics['api_latency_ms']
        if not latencies:
            return 0
        return sum(latencies) / len(latencies)
    
    def get_status(self) -> Dict[str, Any]:
        check_results = {}
        for name, check in self.checks.items():
            check_results[name] = {
                'status': check.last_status,
                'message': check.last_error or 'OK',
                'last_check': check.last_check
            }
        
        return {
            'overall_status': self.overall_status,
            'checks': check_results,
            'metrics': {
                'ws_connected': self.metrics['ws_connected'],
                'ws_reconnect_count': self.metrics['ws_reconnect_count'],
                'api_error_count': self.metrics['api_error_count'],
                'api_success_count': self.metrics['api_success_count'],
                'api_latency_avg_ms': self.get_api_latency_avg(),
                'data_delay_sec': self.metrics['data_delay_sec'],
                'order_fill_rate': self.metrics['order_fill_rate'],
                'order_timeout_count': self.metrics['order_timeout_count']
            }
        }