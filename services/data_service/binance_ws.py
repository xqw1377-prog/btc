import asyncio
import json
import websockets
from typing import Dict, Any, Optional
from datetime import datetime
from collections import deque

class BinanceWebSocket:
    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol
        self.ws = None
        self.running = False
        
        self.streams = [
            f"{symbol}@kline_1m",
            f"{symbol}@markPrice@1s",
            f"{symbol}@depth20@100ms"
        ]
        
        self.buffers = {
            'kline': deque(maxlen=1000),
            'mark_price': deque(maxlen=100),
            'depth': deque(maxlen=100)
        }
        
        self.callbacks = []
        self.reconnect_delay = 5
        self.last_update = 0
    
    def on_data(self, callback):
        self.callbacks.append(callback)
    
    async def _notify_callbacks(self, event_type: str, data: Dict[str, Any]):
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, data)
                else:
                    callback(event_type, data)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def _parse_kline(self, data: Dict) -> Dict[str, Any]:
        k = data['k']
        return {
            'type': 'KLINE',
            'symbol': self.symbol.upper(),
            'timestamp': k['t'],
            'data': {
                'open': float(k['o']),
                'high': float(k['h']),
                'low': float(k['l']),
                'close': float(k['c']),
                'volume': float(k['v']),
                'is_closed': k['x'],
                'quote_volume': float(k['q']),
                'trades': k['n']
            }
        }
    
    def _parse_mark_price(self, data: Dict) -> Dict[str, Any]:
        return {
            'type': 'MARK_PRICE',
            'symbol': self.symbol.upper(),
            'timestamp': data.get('E', datetime.now().timestamp() * 1000),
            'data': {
                'mark_price': float(data['p']),
                'index_price': float(data.get('i', 0)),
                'funding_rate': float(data.get('r', 0)),
                'next_funding_time': data.get('T', 0)
            }
        }
    
    def _parse_depth(self, data: Dict) -> Dict[str, Any]:
        return {
            'type': 'DEPTH',
            'symbol': self.symbol.upper(),
            'timestamp': datetime.now().timestamp() * 1000,
            'data': {
                'bids': [[float(p), float(q)] for p, q in data.get('b', [])],
                'asks': [[float(p), float(q)] for p, q in data.get('a', [])]
            }
        }
    
    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
            
            if 'e' not in data:
                return
            
            event_type = data['e']
            parsed = None
            
            if event_type == 'kline':
                parsed = self._parse_kline(data)
                self.buffers['kline'].append(parsed['data'])
            elif event_type == 'markPriceUpdate':
                parsed = self._parse_mark_price(data)
                self.buffers['mark_price'].append(parsed['data'])
            elif event_type == 'depthUpdate':
                parsed = self._parse_depth(data)
                self.buffers['depth'].append(parsed['data'])
            
            if parsed:
                self.last_update = datetime.now().timestamp()
                await self._notify_callbacks(parsed['type'].lower(), parsed)
                
        except Exception as e:
            print(f"Message handling error: {e}")
    
    async def _connect(self):
        streams = "/".join(self.streams)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        
        async with websockets.connect(url) as ws:
            self.ws = ws
            print(f"WebSocket connected: {self.symbol}")
            
            async for message in ws:
                if not self.running:
                    break
                await self._handle_message(message)
    
    async def start(self):
        self.running = True
        
        while self.running:
            try:
                await self._connect()
            except websockets.exceptions.ConnectionClosed:
                print("WebSocket connection closed")
            except Exception as e:
                print(f"WebSocket error: {e}")
            
            if self.running:
                print(f"Reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
    
    def start_in_thread(self):
        import threading
        thread = threading.Thread(target=lambda: asyncio.run(self.start()), daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.running = False
    
    def get_buffer(self, buffer_type: str = 'kline') -> list:
        return list(self.buffers.get(buffer_type, []))
    
    def get_latest_price(self) -> float:
        if self.buffers['kline']:
            return self.buffers['kline'][-1].get('close', 0)
        return 0
    
    def get_latest_candle(self) -> Optional[Dict[str, Any]]:
        if self.buffers['kline']:
            return self.buffers['kline'][-1]
        return None
    
    def is_connected(self) -> bool:
        return self.running and (datetime.now().timestamp() - self.last_update) < 30