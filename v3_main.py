import time
import pandas as pd
import os
from dotenv import load_dotenv
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
from aurora.strategy_router import StrategyRouter
from aurora.binance_futures import BinanceFutures
from aurora.order_state_machine import OrderStateMachine
from aurora.strategy_evolution import StrategyEvolution
from aurora.adaptive_regime_model import AdaptiveRegimeModel
from aurora.capital_allocation_engine import CapitalAllocationEngine
from aurora.meta_risk_engine import MetaRiskEngine
from aurora.self_optimization_loop import SelfOptimizationLoop

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
    router = StrategyRouter()
    futures_client = BinanceFutures(api_key, api_secret, testnet)
    
    strategy_evolution = StrategyEvolution()
    adaptive_regime = AdaptiveRegimeModel()
    capital_allocator = CapitalAllocationEngine(initial_capital=10000.0)
    meta_risk = MetaRiskEngine()
    self_optimizer = SelfOptimizationLoop()
    
    print("🚀 Starting AURORA BTC Engine V3 - SELF-EVOLVING MODE")
    print(f"📡 Connecting to Binance {'Testnet' if testnet else 'Mainnet'}...")
    
    ws.start_in_thread()
    time.sleep(5)
    
    futures_client.set_leverage("BTCUSDT", 3)
    print("✅ Leverage set to 3x")
    print("✅ Self-evolution system initialized")
    
    print("\n📊 Waiting for data...")
    
    trade_count = 0
    
    try:
        while True:
            buffer = ws.get_buffer()
            
            if len(buffer) < 100:
                print(f"⏳ Buffer: {len(buffer)}/100...", end='\r')
                time.sleep(1)
                continue
            
            df = pd.DataFrame(buffer)
            
            features = feature_engine.get_latest_features(df)
            
            regime = adaptive_regime.identify_regime(features)
            
            signal = router.route(df, regime)
            
            balance = futures_client.get_balance()
            current_price = features.get('close', 0)
            
            strategy_evolution.update_weights()
            strategy_scores = strategy_evolution.get_strategy_scores()
            
            risk_metrics = {
                'max_drawdown': meta_risk.system_drawdown,
                'volatility': features.get('volatility', 1.0)
            }
            
            allocations = capital_allocator.allocate(strategy_scores, risk_metrics)
            
            meta_risk.update_system_drawdown(balance['USDT'])
            meta_risk.system_mode = meta_risk.evaluate_system_mode(features.get('volatility', 1.0))
            
            if not meta_risk.should_trade():
                print("\n⚠️  System in RISK OFF mode - No trading")
                time.sleep(1)
                continue
            
            if signal['signal'] != "NONE" and trade_count % 10 != 0:
                engine_type = signal['engine']
                engine_balance = allocations[engine_type]
                
                position_size = engine_balance * 0.1 * meta_risk.get_risk_multiplier()
                position_qty = position_size / current_price
                
                print(f"\n=== SIGNAL ===")
                print(f"Engine: {engine_type}")
                print(f"Signal: {signal['signal']}")
                print(f"Direction: {signal.get('direction')}")
                print(f"Regime: {regime['regime']} ({regime['confidence']:.2f})")
                print(f"System Mode: {meta_risk.system_mode.value}")
                print(f"Risk Multiplier: {meta_risk.get_risk_multiplier()}")
                
                order_sm = OrderStateMachine(futures_client, "BTCUSDT")
                success = order_sm.submit_order(
                    side=signal['direction'],
                    order_type='MARKET',
                    quantity=position_qty
                )
                
                if success:
                    result = order_sm.run()
                    if result:
                        trade_count += 1
                        pnl = 0.0
                        is_win = True
                        
                        self_optimizer.log_trade({
                            'engine': engine_type,
                            'side': signal['direction'],
                            'qty': result['filled_quantity'],
                            'entry_price': result['filled_price'],
                            'pnl': pnl,
                            'regime': regime['regime']
                        })
                        
                        if engine_type == 'TREND':
                            strategy_evolution.update_trend_stat(pnl, is_win)
                        else:
                            strategy_evolution.update_exec_stat(pnl, is_win)
            
            if trade_count > 0 and trade_count % self_optimizer.optimization_interval == 0:
                analysis = self_optimizer.analyze_recent_trades()
                optimization = self_optimizer.optimize(analysis)
                
                if optimization['updated']:
                    print(f"\n🔄 Self-optimization completed")
                    print(f"   New Weights: Trend={optimization['new_params']['trend_weight']:.2f}, Exec={optimization['new_params']['exec_weight']:.2f}")
            
            summary = {
                'balance': balance['USDT'],
                'regime': regime['regime'],
                'confidence': regime['confidence'],
                'system_mode': meta_risk.system_mode.value,
                'trend_weight': strategy_evolution.weights['trend'],
                'exec_weight': strategy_evolution.weights['execution']
            }
            
            print(f"\r💵 ${summary['balance']:.2f} | "
                  f"🌐 {summary['regime']} ({summary['confidence']:.2f}) | "
                  f"🔧 {summary['system_mode']} | "
                  f"⚖️ T:{summary['trend_weight']:.2f}/E:{summary['exec_weight']:.2f}", end='')
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping AURORA V3...")
        ws.stop()
        
        final_balance = futures_client.get_balance()
        strategy_summary = strategy_evolution.get_summary()
        risk_summary = meta_risk.get_summary()
        
        print("\n=== Final Summary ===")
        print(f"💰 Final Balance: ${final_balance['USDT']:.2f}")
        print(f"📊 System Mode: {risk_summary['system_mode']}")
        print(f"📈 Strategy Weights: Trend={strategy_summary['weights']['trend']:.2f}, Exec={strategy_summary['weights']['execution']:.2f}")
        print(f"🔴 System Drawdown: {risk_summary['system_drawdown']}%")
        print(f"⚡ Total Trades: {trade_count}")
        
        self_optimizer.save_trade_logs('trade_logs_v3.json')
        print("\n✅ Trade logs saved to trade_logs_v3.json")

if __name__ == "__main__":
    main()
