import asyncio
import json
import os
import redis
from datetime import datetime
from aurora.binance_futures import BinanceFutures
from aurora.order_state_machine import OrderStateMachine

class ExecutionService:
    def __init__(self):
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis = redis.Redis(host=self.redis_host, port=self.redis_port)
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        testnet = os.getenv('TESTNET', 'true').lower() == 'true'
        
        self.futures_client = BinanceFutures(api_key, api_secret, testnet)
        self.futures_client.set_leverage("BTCUSDT", 3)
        
        self.last_processed_id = None
    
    def _publish_execution(self, order_data):
        event = {
            'type': 'execution_update',
            'timestamp': datetime.now().isoformat(),
            'order': order_data
        }
        self.redis.xadd('execution_orders', {'order': json.dumps(event)})
    
    async def run(self):
        print("🚀 Execution Service started")
        
        while True:
            try:
                if self.last_processed_id:
                    messages = self.redis.xread(
                        streams={'execution_orders': self.last_processed_id},
                        count=5,
                        block=1000
                    )
                else:
                    messages = self.redis.xread(
                        streams={'execution_orders': '0'},
                        count=5,
                        block=1000
                    )
                
                for stream_name, events in messages:
                    for event_id, event_data in events:
                        self.last_processed_id = event_id
                        
                        try:
                            order_data = json.loads(event_data.get(b'order').decode())
                            
                            if order_data.get('risk_approved'):
                                signal = order_data
                                direction = signal.get('direction', 'LONG')
                                engine_type = signal.get('engine', 'TREND')
                                
                                balance = self.futures_client.get_balance()
                                current_price = self.futures_client.get_mark_price("BTCUSDT")
                                
                                position_size = balance['USDT'] * 0.1
                                position_qty = position_size / current_price
                                
                                print(f"📊 Placing order: {direction} {position_qty:.4f} BTC")
                                
                                order_sm = OrderStateMachine(self.futures_client, "BTCUSDT")
                                success = order_sm.submit_order(
                                    side=direction,
                                    order_type='MARKET',
                                    quantity=position_qty
                                )
                                
                                if success:
                                    result = order_sm.run()
                                    
                                    if result:
                                        execution_result = {
                                            'order_id': result['order_id'],
                                            'status': result['status'],
                                            'filled_qty': result['filled_quantity'],
                                            'filled_price': result['filled_price'],
                                            'direction': direction,
                                            'engine': engine_type,
                                            'timestamp': datetime.now().isoformat()
                                        }
                                        self._publish_execution(execution_result)
                                        print(f"✅ Order executed: {execution_result}")
                            
                        except Exception as e:
                            print(f"Order processing error: {e}")
                
                await asyncio.sleep(0.5)
            
            except Exception as e:
                print(f"Execution service error: {e}")
                await asyncio.sleep(1)

if __name__ == "__main__":
    service = ExecutionService()
    asyncio.run(service.run())
