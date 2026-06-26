#!/usr/bin/env python3
"""
检查 AURORA 系统状态
"""

import os
from dotenv import load_dotenv
from binance.client import Client

def main():
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    client = Client(api_key, api_secret)
    
    print("=" * 60)
    print("AURORA 系统状态检查")
    print("=" * 60)
    
    try:
        # 检查账户余额
        account = client.futures_account()
        
        balance = 0
        equity = 0
        for asset in account['assets']:
            if asset['asset'] == 'USDT':
                balance = float(asset['availableBalance'])
                equity = float(asset['walletBalance'])
                break
        
        print(f"\n💰 账户余额: ${balance:,.2f}")
        print(f"📊 账户权益: ${equity:,.2f}")
        
        # 检查持仓
        positions = []
        total_unrealized_pnl = 0
        
        for pos in account['positions']:
            amt = float(pos['positionAmt'])
            if amt != 0:
                unrealized_pnl = float(pos.get('unrealizedProfit', 0))
                total_unrealized_pnl += unrealized_pnl
                
                positions.append({
                    'symbol': pos['symbol'],
                    'side': 'LONG' if amt > 0 else 'SHORT',
                    'size': abs(amt),
                    'entry_price': float(pos.get('entryPrice', 0)),
                    'unrealized_pnl': unrealized_pnl,
                    'leverage': int(pos.get('leverage', 3))
                })
        
        print(f"\n📈 当前持仓:")
        if positions:
            for pos in positions:
                print(f"   {pos['symbol']}: {pos['side']} {pos['size']:.3f} BTC")
                print(f"      开仓价: ${pos['entry_price']:,.2f}")
                print(f"      未实现盈亏: ${pos['unrealized_pnl']:,.2f}")
                print(f"      杠杆: {pos['leverage']}x")
        else:
            print("   ✅ 无持仓")
        
        print(f"\n💵 总未实现盈亏: ${total_unrealized_pnl:,.2f}")
        
        # 检查最近交易
        trades = client.futures_account_trades(symbol='BTCUSDT', limit=10)
        
        print(f"\n📋 最近交易 (最近10笔):")
        for t in trades:
            pnl = float(t.get('realizedPnl', 0))
            side = t.get('side', '')
            qty = float(t.get('qty', 0))
            price = float(t.get('price', 0))
            time_str = t.get('time', 0)
            
            from datetime import datetime
            dt = datetime.fromtimestamp(time_str / 1000)
            
            print(f"   {dt.strftime('%H:%M:%S')} {side} {qty:.3f} @ ${price:,.2f} PnL=${pnl:,.2f}")
        
        # 检查 BTC 价格
        ticker = client.futures_ticker(symbol='BTCUSDT')
        price = float(ticker['lastPrice'])
        change_pct = float(ticker['priceChangePercent'])
        
        print(f"\n📊 BTC/USDT 价格: ${price:,.2f}")
        print(f"   24h 涨跌: {change_pct:+.2f}%")
        
        print("\n" + "=" * 60)
        
        # 系统运行状态
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        
        aurora_running = 'aurora_final.py' in result.stdout
        ws_running = 'ws_server.py' in result.stdout
        
        print("🚀 系统运行状态:")
        print(f"   主交易系统: {'✅ 运行中' if aurora_running else '❌ 已停止'}")
        print(f"   WebSocket服务: {'✅ 运行中' if ws_running else '❌ 已停止'}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")

if __name__ == "__main__":
    main()