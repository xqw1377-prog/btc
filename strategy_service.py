import asyncio
import json
import os
import redis
from datetime import datetime
from aurora.market_state_engine_v1 import MarketStateEngineV1
from aurora.strategy_router import StrategyRouter

class StrategyService:
    def __init__(self):
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis = redis.Redis(host=self.redis_host, port=self.redis_port)
        
        self.state_engine = MarketStateEngineV1()
        self.router = StrategyRouter()
        
        self.data_buffer = []
        self.last_processed_id = None
    
    def _publish_signal(self, signal):
        signal_event = {
            'type': 'strategy_signal',
            'timestamp': datetime.now().isoformat(),
            'signal': signal
        }
        self.redis.xadd('strategy_signals', {'signal': json.dumps(signal_event)})
    
    async def run(self):
        print("🚀 Strategy Service started")
        
        while True:
            try:
                if self.last_processed_id:
                    messages = self.redis.xread(
                        streams={'market_events': self.last_processed_id},
                        count=10,
                        block=1000
                    )
                else:
                    messages = self.redis.xread(
                        streams={'market_events': '0'},
                        count=10,
                        block=1000
                    )
                
                for stream_name, events in messages:
                    for event_id, event_data in events:
                        self.last_processed_id = event_id
                        
                        try:
                            event = json.loads(event_data.get(b'event').decode())
                            
                            if event['type'] == 'market_update':
                                self.data_buffer.append(event['data'])
                                
                                if len(self.data_buffer) > 200:
                                    self.data_buffer = self.data_buffer[-200:]
                                
                                if len(self.data_buffer) >= 100:
                                    import pandas as pd
                                    df = pd.DataFrame(self.data_buffer)
                                    
                                    features = event['data'].get('features', {})
                                    market_state = self.state_engine.identify_regime(features)
                                    
                                    signal = self.router.route(df, market_state)
                                    
                                    if signal['signal'] != "NONE":
                                        signal['market_state'] = market_state
                                        self._publish_signal(signal)
                                        print(f"📡 Signal published: {signal}")
                            
                        except Exception as e:
                            print(f"Event processing error: {e}")
                
                await asyncio.sleep(0.5)
            
            except Exception as e:
                print(f"Strategy service error: {e}")
                await asyncio.sleep(1)

if __name__ == "__main__":
    service = StrategyService()
    asyncio.run(service.run())
