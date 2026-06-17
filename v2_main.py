import time
import pandas as pd
import os
from dotenv import load_dotenv
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v1 import MarketStateEngineV1
from aurora.strategy_router import StrategyRouter
from aurora.binance_futures import BinanceFutures
from aurora.order_state_machine import OrderStateMachine
from aurora.risk_engine_v1 import RiskEngine
from aurora.position_sizing import PositionSizing
from aurora.portfolio_manager import PortfolioManager

def main():
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'true').lower() == 'true'
    
    if not api_key or not api_secret:
        print("❌ Please set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        return
    
    ws = BinanceWS("btcusdt")
    feature_engine = FeatureEngine()
    state_engine = MarketStateEngineV1()
    router = StrategyRouter()
    futures_client = BinanceFutures(api_key, api_secret, testnet)
    risk_engine = RiskEngine()
    position_sizing = PositionSizing()
    portfolio = PortfolioManager(initial_capital=10000.0)
    
    print("🚀 Starting AURORA BTC Engine V2")
    print(f"📡 Connecting to Binance {'Testnet' if testnet else 'Mainnet'}...")
    
    ws.start_in_thread()
    time.sleep(5)
    
    futures_client.set_leverage("BTCUSDT", 3)
    print("✅ Leverage set to 3x")
    print("✅ Portfolio initialized with $10,000")
    print(f"📊 Trend Allocation: {portfolio.trend_allocation*100}%")
    print(f"📊 Execution Allocation: {portfolio.execution_allocation*100}%")
    
    print("\n📊 Waiting for data...")
    
    try:
        while True:
            buffer = ws.get_buffer()
            
            if len(buffer) < 100:
                print(f"⏳ Buffer: {len(buffer)}/100...", end='\r')
                time.sleep(1)
                continue
            
            df = pd.DataFrame(buffer)
            
            features = feature_engine.get_latest_features(df)
            market_state = state_engine.identify_regime(features)
            
            signal = router.route(df, market_state)
            
            balance = futures_client.get_balance()
            current_price = features.get('close', 0)
            
            risk_engine.update_balance(balance['USDT'])
            risk_metrics = risk_engine.get_risk_metrics()
            
            if risk_metrics['kill_switch']:
                print("\n⚠️  Kill switch activated - No new trades")
                time.sleep(1)
                continue
            
            if signal['signal'] != "NONE":
                print(f"\n=== SIGNAL ===")
                print(f"Engine: {signal['engine']}")
                print(f"Signal: {signal['signal']}")
                print(f"Direction: {signal.get('direction')}")
                print(f"Reason: {signal['reason']}")
                print(f"Confidence: {market_state['confidence']}")
                
                engine_balance = portfolio.get_engine_balance(signal['engine'])
                
                position_qty = position_sizing.get_position_size(
                    balance=engine_balance,
                    price=current_price,
                    regime=market_state['regime'],
                    confidence=market_state['confidence'],
                    volatility=features.get('volatility', 1.0)
                )
                
                position_value = position_qty * current_price
                
                if not portfolio.allocate_capital(signal['engine'], position_value):
                    print("❌ Insufficient capital in engine allocation")
                elif not risk_engine.validate_trade(position_value / balance['USDT'], 3.0):
                    print("❌ Trade rejected by risk engine")
                else:
                    print(f"📈 Placing order: {signal['direction']} {position_qty:.4f} BTC @ ${current_price:.2f}")
                    
                    order_sm = OrderStateMachine(futures_client, "BTCUSDT")
                    success = order_sm.submit_order(
                        side=signal['direction'],
                        order_type='MARKET',
                        quantity=position_qty
                    )
                    
                    if success:
                        result = order_sm.run()
                        if result:
                            print(f"✅ Order filled: {result['filled_quantity']:.4f} BTC @ ${result['filled_price']:.2f}")
                            
                            portfolio.add_position(signal['engine'], {
                                'id': result['order_id'],
                                'side': signal['direction'],
                                'entry_price': result['filled_price'],
                                'qty': result['filled_quantity'],
                                'timestamp': time.time()
                            })
                
                if signal['signal'] == "EXIT":
                    print("📉 Closing position...")
                    result = futures_client.close_position("BTCUSDT")
                    
                    if result['success']:
                        print(f"✅ Position closed at ${result['filled_price']:.2f}")
                        print(f"💰 Trade PnL: ${result['pnl']:.2f}")
                        risk_engine.update_pnl(result['pnl'])
            
            portfolio.update_positions(current_price)
            summary = portfolio.get_summary(current_price)
            
            print(f"\r💵 Balance: ${summary['total_equity']:.2f} | "
                  f"📈 Trend: ${summary['trend_balance']:.2f} | "
                  f"⚡ Exec: ${summary['execution_balance']:.2f} | "
                  f"🌐 Regime: {market_state['regime']} ({market_state['confidence']:.2f}) | "
                  f"🎯 Positions: T{summary['trend_positions']}/E{summary['execution_positions']}", end='')
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping AURORA V2...")
        ws.stop()
        
        final_balance = futures_client.get_balance()
        final_summary = portfolio.get_summary(current_price)
        
        print("\n=== Final Summary ===")
        print(f"💰 Final Equity: ${final_summary['total_equity']:.2f}")
        print(f"📊 Trend Balance: ${final_summary['trend_balance']:.2f}")
        print(f"⚡ Execution Balance: ${final_summary['execution_balance']:.2f}")
        print(f"📈 Risk Multiplier: {risk_engine.risk_multiplier}")
        print(f"🔴 Kill Switch: {'ACTIVE' if risk_engine.kill_switch else 'INACTIVE'}")
        print("\n📝 Remember to close any open positions manually if needed!")

if __name__ == "__main__":
    main()
