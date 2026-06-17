import time
import pandas as pd
import os
from dotenv import load_dotenv
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
from aurora.adaptive_regime_model import AdaptiveRegimeModel
from aurora.strategy_router import StrategyRouter
from aurora.binance_futures import BinanceFutures
from aurora.order_state_machine import OrderStateMachine
from aurora.capital_growth_engine import CapitalGrowthEngine

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
    regime_model = AdaptiveRegimeModel()
    router = StrategyRouter()
    futures_client = BinanceFutures(api_key, api_secret, testnet)
    capital_engine = CapitalGrowthEngine(initial_capital=10000.0)
    
    print("🚀 Starting AURORA BTC Engine - CAPITAL GROWTH MODE")
    print(f"📡 Connecting to Binance {'Testnet' if testnet else 'Mainnet'}...")
    
    ws.start_in_thread()
    time.sleep(5)
    
    futures_client.set_leverage("BTCUSDT", 3)
    print("✅ Leverage set to 3x")
    print("✅ Capital Growth Engine initialized")
    
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
            
            regime = regime_model.identify_regime(features)
            
            signal = router.route(df, regime)
            
            balance = futures_client.get_balance()
            current_price = features.get('close', 0)
            
            capital_engine.current_capital = balance['USDT']
            
            drawdown_status = capital_engine.check_drawdown_status()
            risk_multiplier = capital_engine.get_risk_multiplier()
            strategy_weights = capital_engine.get_strategy_weights()
            
            if drawdown_status == 'KILL':
                print("\n🔴 CRITICAL DRAWDOWN - ALL TRADING STOPPED")
                time.sleep(1)
                continue
            
            if signal['signal'] != "NONE":
                engine_type = signal['engine']
                engine_weight = strategy_weights.get(engine_type, 0.5)
                
                position_size = capital_engine.get_position_size(regime) * engine_weight * risk_multiplier
                position_qty = position_size / current_price
                
                print(f"\n=== SIGNAL ===")
                print(f"Engine: {engine_type} (Weight: {engine_weight:.2f})")
                print(f"Signal: {signal['signal']}")
                print(f"Direction: {signal.get('direction')}")
                print(f"Regime: {regime['regime']} ({regime['confidence']:.2f})")
                print(f"Drawdown Status: {drawdown_status}")
                print(f"Risk Multiplier: {risk_multiplier}")
                print(f"Position Size: ${position_size:.2f} ({position_qty:.4f} BTC)")
                
                order_sm = OrderStateMachine(futures_client, "BTCUSDT")
                success = order_sm.submit_order(
                    side=signal['direction'],
                    order_type='MARKET',
                    quantity=position_qty
                )
                
                if success:
                    result = order_sm.run()
                    if result:
                        pnl = 0.0
                        capital_engine.update_pnl(pnl)
            
            summary = capital_engine.get_summary()
            
            print(f"\r💵 Capital: ${summary['current_capital']:.2f} | "
                  f"📉 DD: {summary['drawdown']}% | "
                  f"🎯 Status: {summary['drawdown_status']} | "
                  f"⚖️ T:{strategy_weights['trend']:.2f}/E:{strategy_weights['execution']:.2f} | "
                  f"💹 Trades: {summary['trade_count']} ({summary['win_rate']}% win)", end='')
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping AURORA Capital Growth Engine...")
        ws.stop()
        
        final_summary = capital_engine.get_summary()
        
        print("\n=== Final Summary ===")
        print(f"💰 Initial Capital: ${final_summary['initial_capital']}")
        print(f"💵 Final Capital: ${final_summary['current_capital']:.2f}")
        print(f"📈 Total PnL: ${final_summary['total_pnl']:.2f}")
        print(f"📉 Max Drawdown: {final_summary['max_drawdown']}%")
        print(f"🎯 Win Rate: {final_summary['win_rate']}%")
        print(f"🔢 Total Trades: {final_summary['trade_count']}")
        print(f"⚖️ Final Weights: Trend={strategy_weights['trend']:.2f}, Exec={strategy_weights['execution']:.2f}")

if __name__ == "__main__":
    main()
