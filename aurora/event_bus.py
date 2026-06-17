import asyncio
import json
import websockets
from typing import Dict, Any, List, Callable
from datetime import datetime
from collections import deque

class Event:
    def __init__(self, event_type: str, symbol: str, data: Dict[str, Any]):
        self.event_type = event_type
        self.symbol = symbol
        self.data = data
        self.timestamp = datetime.now().timestamp()
        self.id = f"{symbol}_{event_type}_{self.timestamp}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.event_type,
            'symbol': self.symbol,
            'ts': self.timestamp,
            'data': self.data
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())

class EventBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_history: deque = deque(maxlen=10000)
        self.redis_client = None
    
    async def connect_redis(self, redis_url: str = "redis://localhost:6379"):
        try:
            import redis.asyncio as aioredis
            self.redis_client = await aioredis.from_url(redis_url)
            print("Connected to Redis")
        except Exception as e:
            print(f"Redis connection failed: {e}")
            self.redis_client = None
    
    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
    
    async def publish(self, event: Event):
        self.event_history.append(event)
        
        if self.redis_client:
            try:
                await self.redis_client.publish(
                    f"aurora:{event.event_type}",
                    event.to_json()
                )
            except Exception as e:
                print(f"Redis publish error: {e}")
        
        if event.event_type in self.subscribers:
            for callback in self.subscribers[event.event_type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    print(f"Subscriber error: {e}")
    
    def get_recent_events(self, event_type: str = None, limit: int = 100) -> List[Event]:
        events = list(self.event_history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

class BinanceDataCollector:
    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol
        self.event_bus = EventBus()
        self.ws = None
        self.running = False
        
        self.streams = [
            f"{symbol}@kline_1m",
            f"{symbol}@markPrice",
            f"{symbol}@depth20"
        ]
        
        self.buffer = {
            'kline': deque(maxlen=1000),
            'markPrice': deque(maxlen=100),
            'depth': deque(maxlen=100)
        }
    
    def _parse_kline(self, data: Dict) -> Event:
        k = data['k']
        return Event(
            event_type='kline',
            symbol=self.symbol.upper(),
            data={
                'time': k['t'],
                'open': float(k['o']),
                'high': float(k['h']),
                'low': float(k['l']),
                'close': float(k['c']),
                'volume': float(k['v']),
                'is_closed': k['x'],
                'quote_volume': float(k['q']),
                'trades': k['n']
            }
        )
    
    def _parse_mark_price(self, data: Dict) -> Event:
        return Event(
            event_type='markPrice',
            symbol=self.symbol.upper(),
            data={
                'mark_price': float(data['p']),
                'index_price': float(data.get('i', 0)),
                'funding_rate': float(data.get('r', 0)),
                'next_funding_time': data.get('T', 0)
            }
        )
    
    def _parse_depth(self, data: Dict) -> Event:
        return Event(
            event_type='depth',
            symbol=self.symbol.upper(),
            data={
                'bids': [[float(p), float(q)] for p, q in data.get('b', [])],
                'asks': [[float(p), float(q)] for p, q in data.get('a', [])]
            }
        )
    
    async def _on_message(self, message: str):
        try:
            data = json.loads(message)
            
            if 'e' not in data:
                return
            
            event_type = data['e']
            
            if event_type == 'kline':
                event = self._parse_kline(data)
                self.buffer['kline'].append(event.data)
            elif event_type == 'markPriceUpdate':
                event = self._parse_mark_price(data)
                self.buffer['markPrice'].append(event.data)
            elif event_type == 'depthUpdate':
                event = self._parse_depth(data)
                self.buffer['depth'].append(event.data)
            else:
                return
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            print(f"Message parsing error: {e}")
    
    async def _connect(self):
        streams = "/".join(self.streams)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        
        async with websockets.connect(url) as ws:
            self.ws = ws
            print(f"Connected to Binance WebSocket: {self.symbol}")
            
            async for message in ws:
                if not self.running:
                    break
                await self._on_message(message)
    
    async def start(self):
        self.running = True
        
        while self.running:
            try:
                await self._connect()
            except Exception as e:
                print(f"WebSocket error: {e}")
                if self.running:
                    await asyncio.sleep(5)
                    print("Reconnecting...")
    
    def start_in_thread(self):
        import threading
        thread = threading.Thread(target=lambda: asyncio.run(self.start()), daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.running = False
    
    def get_buffer(self, buffer_type: str = 'kline') -> list:
        return list(self.buffer.get(buffer_type, []))
    
    def get_latest_price(self) -> float:
        if self.buffer['kline']:
            return self.buffer['kline'][-1].get('close', 0)
        return 0