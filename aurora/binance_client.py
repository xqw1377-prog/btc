import asyncio
import json
import websockets
import ccxt
from datetime import datetime
from typing import Optional, Dict, Any, List
from .types import MarketData, Order

class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.ws_url = "wss://stream.binancefuture.com/ws" if not testnet else "wss://testnet.binancefuture.com/ws"
        self.rest_url = "https://fapi.binance.com" if not testnet else "https://testnet.binancefuture.com"
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'test': testnet
            }
        })
        self.ws_connection = None
        self.last_price = 0.0
        self.last_kline = {}
        self.order_callbacks = {}
    
    async def connect_ws(self):
        try:
            self.ws_connection = await websockets.connect(self.ws_url)
            await self.subscribe('btcusdt@kline_1m')
            await self.subscribe('btcusdt@markPrice')
            await self.subscribe('btcusdt@openInterest')
            await self.subscribe('btcusdt@fundingRate')
        except Exception as e:
            print(f"WS connection error: {e}")
    
    async def subscribe(self, stream: str):
        if self.ws_connection:
            subscribe_msg = json.dumps({
                "method": "SUBSCRIBE",
                "params": [stream],
                "id": 1
            })
            await self.ws_connection.send(subscribe_msg)
    
    async def receive(self):
        if not self.ws_connection:
            return None
        
        try:
            message = await self.ws_connection.recv()
            return json.loads(message)
        except Exception as e:
            print(f"WS receive error: {e}")
            return None
    
    def parse_kline(self, data: Dict) -> Optional[MarketData]:
        kline = data.get('k', {})
        if not kline:
            return None
        
        return MarketData(
            timestamp=datetime.fromtimestamp(kline['t'] / 1000),
            open=float(kline['o']),
            high=float(kline['h']),
            low=float(kline['l']),
            close=float(kline['c']),
            volume=float(kline['v']),
            vwap=0.0,
            oi=0.0,
            funding_rate=0.0
        )
    
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> List[MarketData]:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            data = []
            for candle in ohlcv:
                data.append(MarketData(
                    timestamp=datetime.fromtimestamp(candle[0] / 1000),
                    open=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5],
                    vwap=0.0,
                    oi=0.0,
                    funding_rate=0.0
                ))
            return data
        except Exception as e:
            print(f"Failed to fetch historical data: {e}")
            return []
    
    def place_order(self, order: Order) -> Optional[Dict]:
        try:
            params = {
                'symbol': order.symbol,
                'side': 'BUY' if order.side == 'LONG' else 'SELL',
                'type': order.type,
                'quantity': order.size
            }
            
            if order.type == 'LIMIT' and order.price:
                params['price'] = order.price
            
            result = self.exchange.create_order(**params)
            return result
        except Exception as e:
            print(f"Failed to place order: {e}")
            return None
    
    def get_order_status(self, order_id: str, symbol: str) -> Optional[Dict]:
        try:
            result = self.exchange.fetch_order(order_id, symbol)
            return result
        except Exception as e:
            print(f"Failed to get order status: {e}")
            return None
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            print(f"Failed to cancel order: {e}")
            return False
    
    def get_balance(self) -> float:
        try:
            balances = self.exchange.fetch_balance()
            usdt_balance = balances.get('USDT', {}).get('free', 0.0)
            return usdt_balance
        except Exception as e:
            print(f"Failed to get balance: {e}")
            return 0.0
    
    def get_open_interest(self, symbol: str) -> float:
        try:
            response = self.exchange.fapiPublicGetOpeninterest({'symbol': symbol})
            return float(response.get('openInterest', 0.0))
        except Exception as e:
            print(f"Failed to get OI: {e}")
            return 0.0
    
    def get_funding_rate(self, symbol: str) -> float:
        try:
            response = self.exchange.fapiPublicGetFundingrate({'symbol': symbol})
            return float(response[-1].get('fundingRate', 0.0)) if response else 0.0
        except Exception as e:
            print(f"Failed to get funding rate: {e}")
            return 0.0
    
    async def close(self):
        if self.ws_connection:
            await self.ws_connection.close()
