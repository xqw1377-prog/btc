#!/usr/bin/env python3
"""
Binance API Key 验证脚本
检查 API Key 是否有效，并获取账户信息
"""

import os
import sys
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException

def load_config():
    """加载配置文件"""
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'true').lower() == 'true'
    
    if not api_key or not api_secret:
        print("❌ 错误：请在 .env 文件中配置 BINANCE_API_KEY 和 BINANCE_API_SECRET")
        sys.exit(1)
    
    return api_key, api_secret, testnet

def create_client(api_key, api_secret, testnet):
    """创建 Binance 客户端"""
    client = Client(api_key, api_secret)
    
    if testnet:
        client.API_URL = 'https://testnet.binance.vision/api'
        print("🔧 使用测试网模式")
    else:
        print("🔧 使用主网模式")
    
    return client

def test_connection(client):
    """测试连接"""
    print("\n📡 正在测试连接...")
    try:
        time_diff = client.get_server_time()
        print(f"✅ 连接成功！服务器时间: {time_diff['serverTime']}")
        return True
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False

def get_account_info(client):
    """获取账户信息"""
    print("\n💰 获取账户信息...")
    try:
        account = client.futures_account()
        print(f"✅ 账户状态: {'正常' if account['canTrade'] else '受限'}")
        print(f"📊 账户权益: {account['totalWalletBalance']} USDT")
        print(f"📈 账户余额: {account['totalMarginBalance']} USDT")
        print(f"💹 可用余额: {account['availableBalance']} USDT")
        print(f"📉 未实现盈亏: {account['unrealizedProfit']} USDT")
        return account
    except BinanceAPIException as e:
        print(f"❌ 获取账户信息失败: {e}")
        return None

def get_positions(client):
    """获取当前持仓"""
    print("\n📦 获取当前持仓...")
    try:
        positions = client.futures_position_information()
        active_positions = [p for p in positions if float(p['positionAmt']) != 0]
        
        if active_positions:
            print(f"✅ 当前有 {len(active_positions)} 个持仓")
            for pos in active_positions:
                symbol = pos['symbol']
                side = '多头' if float(pos['positionAmt']) > 0 else '空头'
                size = abs(float(pos['positionAmt']))
                entry_price = pos['entryPrice']
                mark_price = pos['markPrice']
                pnl = pos['unrealizedProfit']
                
                print(f"\n  📌 {symbol}")
                print(f"     方向: {side}")
                print(f"     数量: {size}")
                print(f"     开仓价: {entry_price}")
                print(f"     标记价: {mark_price}")
                print(f"     浮动盈亏: {pnl} USDT")
        else:
            print("ℹ️ 当前无持仓")
            
        return positions
    except BinanceAPIException as e:
        print(f"❌ 获取持仓失败: {e}")
        return None

def get_open_orders(client):
    """获取当前挂单"""
    print("\n📋 获取当前挂单...")
    try:
        orders = client.futures_get_open_orders()
        
        if orders:
            print(f"✅ 当前有 {len(orders)} 个挂单")
            for order in orders:
                print(f"\n  📌 {order['symbol']}")
                print(f"     类型: {order['side']} {order['type']}")
                print(f"     价格: {order['price']}")
                print(f"     数量: {order['origQty']}")
        else:
            print("ℹ️ 当前无挂单")
            
        return orders
    except BinanceAPIException as e:
        print(f"❌ 获取挂单失败: {e}")
        return None

def get_market_price(client):
    """获取 BTC 价格"""
    print("\n📈 获取 BTC 价格...")
    try:
        ticker = client.futures_mark_price(symbol='BTCUSDT')
        price = float(ticker['markPrice'])
        print(f"✅ BTC/USDT 标记价格: ${price:,.2f}")
        return price
    except BinanceAPIException as e:
        print(f"❌ 获取价格失败: {e}")
        return None

def main():
    print("="*60)
    print("    AURORA BTC Engine - Binance API 验证工具")
    print("="*60)
    
    # 加载配置
    api_key, api_secret, testnet = load_config()
    
    # 创建客户端
    client = create_client(api_key, api_secret, testnet)
    
    # 测试连接
    if not test_connection(client):
        print("\n❌ API Key 验证失败，请检查你的密钥是否正确")
        sys.exit(1)
    
    # 获取账户信息
    account = get_account_info(client)
    
    # 获取持仓
    get_positions(client)
    
    # 获取挂单
    get_open_orders(client)
    
    # 获取市场价格
    get_market_price(client)
    
    print("\n" + "="*60)
    print("✅ API Key 验证完成！")
    print("="*60)

if __name__ == "__main__":
    main()
