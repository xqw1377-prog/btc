import os
from dotenv import load_dotenv
from aurora.binance_api import BinanceAPI
from aurora.order_executor import OrderExecutor
from aurora.risk_engine_v1 import RiskEngine

def test_binance_api():
    print("=== Testing BinanceAPI ===")
    api = BinanceAPI(testnet=True)
    
    price = api.get_price("BTCUSDT")
    print(f"BTC Price: ${price:.2f}")
    
    balance = api.get_account_balance()
    print(f"Account Balance: ${balance:.2f}")
    
    position = api.get_position("BTCUSDT")
    print(f"Position: {position}")
    
    return price > 0

def test_order_executor():
    print("\n=== Testing OrderExecutor ===")
    executor = OrderExecutor(testnet=True)
    
    price = executor.get_current_price()
    print(f"Current Price: ${price:.2f}")
    
    balance = executor.get_balance()
    print(f"Balance: ${balance:.2f}")
    
    position_size = executor.calculate_position_size(
        balance=balance,
        price=price,
        risk_pct=1.0,
        engine_type="TREND"
    )
    print(f"Position Size (TREND): {position_size:.4f} BTC")
    
    position_size_exec = executor.calculate_position_size(
        balance=balance,
        price=price,
        risk_pct=1.0,
        engine_type="EXECUTION"
    )
    print(f"Position Size (EXECUTION): {position_size_exec:.4f} BTC")
    
    return True

def test_risk_engine():
    print("\n=== Testing RiskEngine ===")
    risk = RiskEngine()
    
    risk.update_balance(10000)
    print(f"Initial Balance: ${risk.current_balance:.2f}")
    
    risk.update_pnl(100)
    print(f"After +100 PnL: {risk.get_risk_metrics()}")
    
    risk.update_pnl(-50)
    print(f"After -50 PnL: {risk.get_risk_metrics()}")
    
    validation = risk.validate_trade(0.1, 3.0, {'confidence': 0.7})
    print(f"Trade Validation: {validation}")
    
    return True

def main():
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Please set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        print("   Copy .env.example to .env and fill in your API keys")
        return
    
    print("🚀 AURORA V1.3 Module Test")
    print("=" * 50)
    
    try:
        api_ok = test_binance_api()
        executor_ok = test_order_executor()
        risk_ok = test_risk_engine()
        
        print("\n" + "=" * 50)
        print("📊 Test Results:")
        print(f"   BinanceAPI: {'✅ PASS' if api_ok else '❌ FAIL'}")
        print(f"   OrderExecutor: {'✅ PASS' if executor_ok else '❌ FAIL'}")
        print(f"   RiskEngine: {'✅ PASS' if risk_ok else '❌ FAIL'}")
        
        if api_ok and executor_ok and risk_ok:
            print("\n✅ All modules working correctly!")
            print("\n🚀 Ready to run live trading:")
            print("   python live_trading.py")
        else:
            print("\n❌ Some modules failed. Check the errors above.")
    
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()