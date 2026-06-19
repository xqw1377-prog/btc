import asyncio
import json
import websockets
from typing import Dict, Any, Set
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from binance.client import Client
from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v2 import MarketStateEngineV2

class WebSocketServer:
    def __init__(self, host: str = 'localhost', port: int = 8000):
        self.host = host
        self.port = port
        self.clients: Set = set()
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        self.client = Client(api_key, api_secret)
        
        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2()
        
        self.market_data = {
            'price': 0,
            'priceChange': 0,
            'priceChangePercent': 0,
            'regime': 'TRANSITION',
            'confidence': 0,
            'ema20': 0,
            'ema60': 0,
            'atr': 0,
            'adx': 0,
            'volatility': 0,
            'volume': 0,
            'klines': []
        }
        
        self.account_data = {
            'balance': 0,
            'equity': 0,
            'unrealizedPnl': 0,
            'positions': []
        }
        
        self.risk_data = {
            'currentDrawdown': 0,
            'maxDrawdown': 0,
            'dailyPnl': 0,
            'weeklyPnl': 0,
            'totalPnl': 0,
            'status': 'SAFE'
        }
        
        self.pnl_data = []
        self.trade_data = []
    
    async def register(self, websocket):
        self.clients.add(websocket)
        print(f"Client connected. Total: {len(self.clients)}")
        await self.send_initial_data(websocket)
    
    async def unregister(self, websocket):
        self.clients.discard(websocket)
        print(f"Client disconnected. Total: {len(self.clients)}")
    
    async def send_initial_data(self, websocket):
        await websocket.send(json.dumps({'type': 'market', 'payload': self.market_data}))
        await websocket.send(json.dumps({'type': 'system', 'payload': self.account_data}))
        await websocket.send(json.dumps({'type': 'risk', 'payload': self.risk_data}))
        await websocket.send(json.dumps({'type': 'pnl', 'payload': self.pnl_data}))
        await websocket.send(json.dumps({'type': 'score', 'payload': 50}))
    
    async def broadcast(self, message: str):
        if self.clients:
            await asyncio.gather(*[client.send(message) for client in self.clients], return_exceptions=True)
    
    def fetch_market_data(self):
        try:
            ticker = self.client.futures_ticker(symbol='BTCUSDT')
            self.market_data['price'] = float(ticker['lastPrice'])
            self.market_data['priceChange'] = float(ticker['priceChange'])
            self.market_data['priceChangePercent'] = float(ticker['priceChangePercent'])
            
            klines = self.client.futures_klines(symbol='BTCUSDT', interval='1m', limit=100)
            df = pd.DataFrame(klines, columns=[
                'time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            self.market_data['klines'] = [
                {
                    'time': int(row['time']),
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume']
                }
                for _, row in df.tail(50).iterrows()
            ]
            
            features = self.feature_engine.get_latest_features(df)
            
            self.market_data['ema20'] = features.get('ema20', 0)
            self.market_data['ema60'] = features.get('ema60', 0)
            self.market_data['atr'] = features.get('atr', 0)
            self.market_data['adx'] = features.get('adx', 0)
            self.market_data['volatility'] = features.get('volatility', 0)
            self.market_data['volume'] = features.get('volume', 0)
            
            market_state = self.state_engine.identify_regime(features)
            self.market_data['regime'] = market_state.get('regime', 'TRANSITION')
            self.market_data['confidence'] = market_state.get('confidence', 0)
            
        except Exception as e:
            print(f"Error fetching market data: {e}")
    
    def fetch_account_data(self):
        try:
            account = self.client.futures_account()
            
            balance = 0
            equity = 0
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    balance = float(asset['availableBalance'])
                    equity = float(asset['walletBalance'])
                    break
            
            self.account_data['balance'] = balance
            self.account_data['equity'] = equity
            
            positions = []
            total_unrealized_pnl = 0
            
            for pos in account['positions']:
                amt = float(pos['positionAmt'])
                if amt != 0:
                    unrealized_pnl = float(pos.get('unrealizedProfit', 0))
                    total_unrealized_pnl += unrealized_pnl
                    
                    entry_price = float(pos.get('entryPrice', 0))
                    mark_price = float(pos.get('markPrice', 0))
                    
                    if mark_price == 0:
                        try:
                            ticker = self.client.futures_ticker(symbol=pos['symbol'])
                            mark_price = float(ticker['lastPrice'])
                        except:
                            mark_price = entry_price
                    
                    positions.append({
                        'symbol': pos['symbol'],
                        'side': 'LONG' if amt > 0 else 'SHORT',
                        'size': abs(amt),
                        'entryPrice': entry_price,
                        'markPrice': mark_price,
                        'unrealizedPnl': unrealized_pnl,
                        'leverage': int(pos.get('leverage', 3))
                    })
            
            self.account_data['positions'] = positions
            self.account_data['unrealizedPnl'] = total_unrealized_pnl
            
        except Exception as e:
            print(f"Error fetching account data: {e}")
    
    def fetch_risk_data(self):
        try:
            account = self.client.futures_account()
            
            total_balance = float(account.get('totalWalletBalance', 0))
            total_unrealized = float(account.get('totalUnrealizedProfit', 0))
            
            self.risk_data['dailyPnl'] = total_unrealized
            self.risk_data['totalPnl'] = total_unrealized
            
            if total_balance > 0:
                drawdown_pct = abs(min(0, total_unrealized)) / total_balance * 100
                self.risk_data['currentDrawdown'] = drawdown_pct
                
                if drawdown_pct > self.risk_data['maxDrawdown']:
                    self.risk_data['maxDrawdown'] = drawdown_pct
            
            if self.risk_data['currentDrawdown'] > 5:
                self.risk_data['status'] = 'DANGER'
            elif self.risk_data['currentDrawdown'] > 2:
                self.risk_data['status'] = 'WARNING'
            else:
                self.risk_data['status'] = 'SAFE'
            
        except Exception as e:
            print(f"Error fetching risk data: {e}")
    
    def update_pnl_history(self):
        now = datetime.now()
        pnl = self.account_data.get('unrealizedPnl', 0)
        
        self.pnl_data.append({
            'time': now.isoformat(),
            'pnl': round(pnl, 2)
        })
        
        if len(self.pnl_data) > 100:
            self.pnl_data = self.pnl_data[-100:]
    
    def fetch_trades(self):
        try:
            trades = self.client.futures_account_trades(symbol='BTCUSDT', limit=20)
            
            self.trade_data = []
            for t in trades:
                pnl = float(t.get('realizedPnl', 0))
                self.trade_data.append({
                    'id': str(t.get('id', '')),
                    'timestamp': datetime.fromtimestamp(t['time'] / 1000).isoformat(),
                    'side': t.get('side', ''),
                    'engine': 'KERNEL',
                    'entryPrice': float(t.get('price', 0)),
                    'exitPrice': float(t.get('price', 0)),
                    'quantity': float(t.get('qty', 0)),
                    'pnl': pnl,
                    'pnl_pct': 0,
                    'reason': 'Executed',
                    'regime': 'UNKNOWN'
                })
            
        except Exception as e:
            print(f"Error fetching trades: {e}")
    
    async def handler(self, websocket, path=None):
        await self.register(websocket)
        try:
            async for message in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)
    
    async def update_loop(self):
        while True:
            try:
                self.fetch_market_data()
                self.fetch_account_data()
                self.fetch_risk_data()
                self.fetch_trades()
                self.update_pnl_history()
                
                await self.broadcast(json.dumps({'type': 'market', 'payload': self.market_data}))
                await self.broadcast(json.dumps({'type': 'system', 'payload': self.account_data}))
                await self.broadcast(json.dumps({'type': 'risk', 'payload': self.risk_data}))
                await self.broadcast(json.dumps({'type': 'pnl', 'payload': self.pnl_data}))
                await self.broadcast(json.dumps({'type': 'trades', 'payload': self.trade_data}))
                
                score = int(self.market_data.get('confidence', 0) * 100)
                await self.broadcast(json.dumps({'type': 'score', 'payload': score}))
                
                pos_count = len(self.account_data.get('positions', []))
                trade_count = len(self.trade_data)
                sys.stdout.write(f"\r📊 ${self.market_data['price']:,.2f} | 💰 ${self.account_data['balance']:,.2f} | 📈 Pos:{pos_count} Trades:{trade_count} | 🔄 {self.market_data['regime']}")
                sys.stdout.flush()
                
            except Exception as e:
                print(f"\nError: {e}")
            
            await asyncio.sleep(5)
    
    async def start(self):
        print(f"🚀 Starting WebSocket server on ws://{self.host}:{self.port}")
        server = await websockets.serve(self.handler, self.host, self.port)
        await self.update_loop()

def main():
    server = WebSocketServer()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        print("\n🛑 Stopping server...")

if __name__ == "__main__":
    main()