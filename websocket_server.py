#!/usr/bin/env python3
"""
AURORA WebSocket Server
提供实时市场数据和系统状态
"""

import asyncio
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client

# 加载配置
load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
testnet = os.getenv('TESTNET', 'true').lower() == 'true'

# 创建 Binance 客户端
client = Client(api_key, api_secret)
if testnet:
    client.API_URL = 'https://testnet.binance.vision/api'

# 全局状态
market_state = {
    'price': 0,
    'priceChange': 0,
    'priceChangePercent': 0,
    'regime': 'TREND',
    'confidence': 0.82,
    'ema20': 0,
    'ema60': 0,
    'atr': 0,
    'volatility': 0,
    'volume': 0,
    'spread': 0
}

system_state = {
    'mode': 'NORMAL',
    'engine': 'TREND',
    'exposure': 42.3,
    'leverage': 2.1,
    'position': 'LONG',
    'killSwitch': False,
    'engines': {
        'trend': True,
        'execution': True
    }
}

risk_state = {
    'currentDrawdown': 2.31,
    'maxDrawdown': 5.0,
    'dailyPnl': 1234.56,
    'weeklyPnl': 3456.78,
    'totalPnl': 5234.67,
    'status': 'SAFE'
}

trade_score = 85

# K线数据缓存
kline_data = []

# WebSocket 客户端列表
clients = []

async def broadcast(message):
    """向所有客户端广播消息"""
    for ws in clients:
        try:
            await ws.send(json.dumps(message))
        except Exception as e:
            print(f"发送消息失败: {e}")

def process_kline_message(msg):
    """处理 K线消息"""
    global market_state, kline_data
    
    kline = msg['k']
    symbol = msg['s']
    
    if symbol == 'BTCUSDT':
        price = float(kline['c'])
        market_state['price'] = price
        
        # 更新 K线数据
        if kline['x']:  # K线关闭
            candle = {
                'time': kline['t'],
                'open': float(kline['o']),
                'high': float(kline['h']),
                'low': float(kline['l']),
                'close': price,
                'volume': float(kline['v'])
            }
            kline_data.append(candle)
            if len(kline_data) > 200:
                kline_data = kline_data[-200:]

async def update_market_data():
    """定期更新市场数据"""
    global market_state, risk_state, trade_score
    
    while True:
        try:
            # 获取 BTC 价格
            ticker = client.futures_mark_price(symbol='BTCUSDT')
            market_state['price'] = float(ticker['markPrice'])
            
            # 获取 24h 统计
            stats = client.futures_ticker(symbol='BTCUSDT')
            market_state['priceChange'] = float(stats['priceChange'])
            market_state['priceChangePercent'] = float(stats['priceChangePercent'])
            market_state['volume'] = float(stats['volume'])
            
            # 计算指标
            klines = client.futures_klines(symbol='BTCUSDT', interval=Client.KLINE_INTERVAL_1HOUR, limit=100)
            
            if len(klines) >= 60:
                closes = [float(k[4]) for k in klines]
                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                
                # EMA
                market_state['ema20'] = sum(closes[-20:]) / 20
                market_state['ema60'] = sum(closes[-60:]) / 60
                
                # ATR
                tr_sum = 0
                for i in range(1, len(klines)):
                    tr = max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i-1]),
                        abs(lows[i] - closes[i-1])
                    )
                    tr_sum += tr
                market_state['atr'] = tr_sum / (len(klines) - 1)
                
                # 波动率
                returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                market_state['volatility'] = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5 * 100
            
            # 更新市场状态
            if market_state['ema20'] > market_state['ema60']:
                market_state['regime'] = 'TREND'
                market_state['confidence'] = min(0.95, 0.7 + market_state['volatility'] / 100)
            else:
                market_state['regime'] = 'RANGE'
                market_state['confidence'] = min(0.85, 0.6 + (1 - market_state['volatility'] / 100) * 0.3)
            
            # 更新风险状态
            if market_state['regime'] == 'TREND':
                risk_state['status'] = 'SAFE'
                trade_score = min(100, 80 + int(market_state['confidence'] * 20))
            else:
                risk_state['status'] = 'WARNING'
                trade_score = max(40, 60 + int(market_state['confidence'] * 10))
            
            # 广播市场状态
            await broadcast({
                'type': 'market',
                'payload': market_state
            })
            
            # 广播风险状态
            await broadcast({
                'type': 'risk',
                'payload': risk_state
            })
            
            # 广播交易评分
            await broadcast({
                'type': 'score',
                'payload': trade_score
            })
            
            # 广播系统状态
            await broadcast({
                'type': 'system',
                'payload': system_state
            })
            
        except Exception as e:
            print(f"更新市场数据失败: {e}")
        
        await asyncio.sleep(5)

async def handle_client(websocket, path):
    """处理客户端连接"""
    print("新客户端连接")
    clients.append(websocket)
    
    try:
        # 发送初始数据
        await websocket.send(json.dumps({
            'type': 'market',
            'payload': market_state
        }))
        await websocket.send(json.dumps({
            'type': 'risk',
            'payload': risk_state
        }))
        await websocket.send(json.dumps({
            'type': 'score',
            'payload': trade_score
        }))
        await websocket.send(json.dumps({
            'type': 'system',
            'payload': system_state
        }))
        
        # 保持连接
        async for message in websocket:
            print(f"收到消息: {message}")
            
    except Exception as e:
        print(f"客户端连接异常: {e}")
    finally:
        clients.remove(websocket)
        print("客户端断开连接")

async def main():
    """主函数"""
    print("启动 AURORA WebSocket 服务...")
    
    # 启动市场数据更新任务
    asyncio.create_task(update_market_data())
    
    # 启动 WebSocket 服务器
    import websockets
    async with websockets.serve(handle_client, "0.0.0.0", 8000):
        print("WebSocket 服务器已启动在 ws://localhost:8000")
        await asyncio.Future()  # 永远运行

if __name__ == "__main__":
    asyncio.run(main())
