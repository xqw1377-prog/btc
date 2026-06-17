import asyncio
import json
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime
from collections import deque
import redis.asyncio as aioredis

class EventBus:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.pubsub = None
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_history: deque = deque(maxlen=10000)
        self.running = False
    
    async def connect(self):
        try:
            self.redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()
            self.pubsub = self.redis.pubsub()
            print(f"Connected to Redis: {self.redis_url}")
            return True
        except Exception as e:
            print(f"Redis connection failed: {e}")
            return False
    
    async def disconnect(self):
        if self.pubsub:
            await self.pubsub.unsubscribe()
        if self.redis:
            await self.redis.close()
    
    def subscribe(self, channel: str, callback: Callable):
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        self.subscribers[channel].append(callback)
    
    async def publish(self, channel: str, event: Dict[str, Any]):
        if not self.redis:
            return
        
        event['published_at'] = datetime.now().timestamp()
        
        await self.redis.publish(channel, json.dumps(event))
        self.event_history.append({
            'channel': channel,
            'event': event,
            'timestamp': event['published_at']
        })
    
    async def start_listening(self):
        if not self.pubsub:
            return
        
        self.running = True
        
        for channel in self.subscribers:
            await self.pubsub.subscribe(channel)
        
        async for message in self.pubsub.listen():
            if not self.running:
                break
            
            if message['type'] == 'message':
                channel = message['channel']
                data = json.loads(message['data'])
                
                if channel in self.subscribers:
                    for callback in self.subscribers[channel]:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(data)
                            else:
                                callback(data)
                        except Exception as e:
                            print(f"Subscriber error on {channel}: {e}")
    
    async def stop(self):
        self.running = False
        await self.disconnect()

CHANNELS = {
    'MARKET_DATA': 'aurora:market_data',
    'KLINE': 'aurora:kline',
    'MARK_PRICE': 'aurora:mark_price',
    'DEPTH': 'aurora:depth',
    'SIGNAL': 'aurora:signal',
    'ORDER': 'aurora:order',
    'TRADE': 'aurora:trade',
    'RISK': 'aurora:risk',
    'SYSTEM': 'aurora:system',
    'ALERT': 'aurora:alert'
}