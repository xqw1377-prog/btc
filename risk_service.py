import asyncio
import json
import os
import redis
from datetime import datetime
from aurora.meta_risk_engine import MetaRiskEngine

class RiskService:
    def __init__(self):
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis = redis.Redis(host=self.redis_host, port=self.redis_port)
        
        self.meta_risk = MetaRiskEngine()
        self.kill_switch_active = False
        
        self.last_processed_signal_id = None
        self.last_processed_exec_id = None
    
    def _publish_risk_event(self, event_type, data):
        event = {
            'type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        self.redis.xadd('risk_events', {'event': json.dumps(event)})
    
    def _check_kill_switch(self):
        if self.meta_risk.system_mode.value in ['RISK_OFF', 'EMERGENCY']:
            if not self.kill_switch_active:
                self.kill_switch_active = True
                self._publish_risk_event('kill_switch_activated', {
                    'mode': self.meta_risk.system_mode.value,
                    'reason': 'Risk threshold exceeded'
                })
                print("🔴 Kill switch activated!")
        else:
            if self.kill_switch_active:
                self.kill_switch_active = False
                self._publish_risk_event('kill_switch_deactivated', {
                    'mode': self.meta_risk.system_mode.value
                })
                print("🟢 Kill switch deactivated")
    
    def _validate_signal(self, signal):
        if self.kill_switch_active:
            return False
        
        features = signal.get('market_state', {}).get('features', {})
        volatility = features.get('volatility', 1.0)
        
        self.meta_risk.system_mode = self.meta_risk.evaluate_system_mode(volatility)
        self._check_kill_switch()
        
        return self.meta_risk.should_trade()
    
    async def process_signals(self):
        while True:
            try:
                if self.last_processed_signal_id:
                    messages = self.redis.xread(
                        streams={'strategy_signals': self.last_processed_signal_id},
                        count=5,
                        block=500
                    )
                else:
                    messages = self.redis.xread(
                        streams={'strategy_signals': '0'},
                        count=5,
                        block=500
                    )
                
                for stream_name, events in messages:
                    for event_id, event_data in events:
                        self.last_processed_signal_id = event_id
                        
                        try:
                            event = json.loads(event_data.get(b'signal').decode())
                            
                            if event['type'] == 'strategy_signal':
                                signal = event['signal']
                                
                                if self._validate_signal(signal):
                                    signal['risk_approved'] = True
                                    self.redis.xadd('execution_orders', {'order': json.dumps(signal)})
                                    print(f"✅ Signal approved by risk engine")
                                else:
                                    print(f"❌ Signal rejected by risk engine")
                            
                        except Exception as e:
                            print(f"Signal processing error: {e}")
                
                await asyncio.sleep(0.3)
            
            except Exception as e:
                print(f"Risk service signal error: {e}")
                await asyncio.sleep(1)
    
    async def process_executions(self):
        while True:
            try:
                if self.last_processed_exec_id:
                    messages = self.redis.xread(
                        streams={'execution_orders': self.last_processed_exec_id},
                        count=5,
                        block=500
                    )
                else:
                    messages = self.redis.xread(
                        streams={'execution_orders': '0'},
                        count=5,
                        block=500
                    )
                
                for stream_name, events in messages:
                    for event_id, event_data in events:
                        self.last_processed_exec_id = event_id
                        
                        try:
                            order = json.loads(event_data.get(b'order').decode())
                            
                            if order.get('status') == 'FILLED':
                                pnl = order.get('pnl', 0)
                                self.meta_risk.update_pnl_history(pnl, pnl)
                                self.meta_risk.update_consecutive_losses(pnl < 0)
                            
                        except Exception as e:
                            print(f"Execution processing error: {e}")
                
                await asyncio.sleep(0.3)
            
            except Exception as e:
                print(f"Risk service execution error: {e}")
                await asyncio.sleep(1)
    
    async def run(self):
        print("🚀 Risk Service started")
        
        await asyncio.gather(
            self.process_signals(),
            self.process_executions()
        )

if __name__ == "__main__":
    service = RiskService()
    asyncio.run(service.run())
