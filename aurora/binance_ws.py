import websocket
import json
import threading
import time
from collections import deque
from typing import Dict, Any

class BinanceWS:
    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol.lower()
        self.stream = f"{self.symbol}@kline_1m"
        self.buffer = deque(maxlen=1000)
        self.ws = None
        self.running = False
        self.lock = threading.Lock()
        self.last_update = 0
    
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            k = data.get('k', {})
            
            if not k:
                return
            
            candle = {
                "time": k['t'],
                "open": float(k['o']),
                "high": float(k['h']),
                "low": float(k['l']),
                "close": float(k['c']),
                "volume": float(k['v']),
                "is_closed": k['x'],
                "quote_volume": float(k['q']),
                "trades": k['n']
            }
            
            with self.lock:
                self.buffer.append(candle)
                self.last_update = time.time()
                
        except Exception as e:
            print(f"WS message error: {e}")
    
    def on_error(self, ws, error):
        print(f"WS error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print("WS connection closed")
        self.running = False
    
    def on_open(self, ws):
        print("WS connection opened")
    
    def start(self):
        url = f"wss://stream.binance.com:9443/ws/{self.stream}"
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        self.running = True
        self.ws.run_forever()
    
    def start_in_thread(self):
        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        return thread
    
    def get_buffer(self) -> list:
        with self.lock:
            return list(self.buffer)
    
    def get_latest_candle(self) -> Dict[str, Any]:
        with self.lock:
            if self.buffer:
                return self.buffer[-1]
            return {}
    
    def get_buffer_size(self) -> int:
        with self.lock:
            return len(self.buffer)
    
    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
