import time
import pandas as pd
import os
from dotenv import load_dotenv
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v1 import MarketStateEngineV1
from aurora.strategy_router import StrategyRouter
from aurora.order_executor import OrderExecutor
from aurora.risk_engine_v1 import RiskEngine

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
    executor = OrderExecutor(testnet=testnet)
    risk_engine = RiskEngine()
    
    print("🚀 Starting AURORA BTC Engine V1.3 - LIVE TRADING")
    print(f"📡 Connecting to Binance {'Testnet' if testnet else 'Mainnet'}...")
    
    ws.start_in_thread()
    time.sleep(5)
    
    executor.api.set_leverage("BTCUSDT", 3)
    print("✅ Leverage set to 3x")
    
    print("📊 Waiting for data...")
    
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
            
            balance = executor.get_balance()
            current_price = features.get('close', 0)
            position = executor.get_position_info()
            
            risk_engine.update_balance(balance)
            
            risk_metrics = risk_engine.get_risk_metrics()
            
            if risk_metrics['kill_switch']:
                print(f"\n⚠️  Kill switch active: {risk_metrics['kill_switch_reason']}")
                time.sleep(1)
                continue
            
            executor.monitor_orders()
            
            if signal['signal'] != "NONE":
                print(f"\n=== SIGNAL ===")
                print(f"Engine: {signal['engine']}")
                print(f"Signal: {signal['signal']}")
                print(f"Direction: {signal.get('direction')}")
                print(f"Reason: {signal['reason']}")
                
                position_size = executor.calculate_position_size(
                    balance=balance,
                    price=current_price,
                    risk_pct=risk_engine.risk_multiplier,
                    engine_type=signal['engine']
                )
                
                validation = risk_engine.validate_trade(
                    position_size=position_size / current_price,
                    leverage=3.0,
                    market_state=market_state
                )
                
                if not validation['approved']:
                    print(f"❌ Trade rejected: {validation['reason']}")
                else:
                    if signal['signal'] in ["ENTER", "ADD"]:
                        side = 'BUY' if signal.get('direction') == 'LONG' else 'SELL'
                        
                        print(f"📈 Placing order: {side} {position_size:.4f} BTC @ ${current_price:.2f}")
                        
                        result = executor.execute_signal(signal, balance, risk_engine.risk_multiplier)
                        
                        if result.get('success'):
                            print(f"✅ Order placed: {result.get('orderId')}")
                            risk_engine.record_trade_time()
                        else:
                            print(f"❌ Order failed: {result.get('reason')}")
                    
                    elif signal['signal'] == "EXIT":
                        print("📉 Closing position...")
                        position_amt = position.get('positionAmt', 0) if position else 0
                        
                        if position_amt != 0:
                            result = executor.close_position(position_amt)
                            
                            if result.get('success'):
                                pnl = position.get('unrealizedPnl', 0) if position else 0
                                print(f"✅ Position closed")
                                print(f"💰 Trade PnL: ${pnl:.2f}")
                                risk_engine.update_pnl(pnl)
                                if pnl > 0:
                                    risk_engine.winning_trades += 1
                                risk_engine.total_trades += 1
            
            unrealized_pnl = position.get('unrealizedPnl', 0.0) if position else 0.0
            position_amt = position.get('positionAmt', 0) if position else 0
            
            status_line = (
                f"\r💵 Balance: ${balance:.2f} | "
                f"📊 Equity: ${balance + unrealized_pnl:.2f} | "
                f"📈 PnL: ${unrealized_pnl:.2f} | "
                f"🌐 Regime: {market_state['regime']} ({market_state['confidence']:.2f}) | "
                f"🎯 Position: {position_amt:.4f} BTC | "
                f"🛡 Risk: {risk_metrics['risk_level']}"
            )
            print(status_line, end='')
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping AURORA...")
        ws.stop()
        
        final_balance = executor.get_balance()
        final_position = executor.get_position_info()
        risk_metrics = risk_engine.get_risk_metrics()
        
        print("\n=== Final Summary ===")
        print(f"💰 Final Balance: ${final_balance:.2f}")
        
        if final_position and final_position.get('positionAmt', 0) != 0:
            print(f"🎯 Open Position: {final_position['positionAmt']:.4f} BTC")
            print(f"   Entry Price: ${final_position.get('entryPrice', 0):.2f}")
            print(f"   Unrealized PnL: ${final_position.get('unrealizedPnl', 0):.2f}")
        else:
            print("🎯 Open Position: None")
        
        print(f"\n📊 Risk Metrics:")
        print(f"   Risk Level: {risk_metrics['risk_level']}")
        print(f"   Risk Multiplier: {risk_metrics['risk_multiplier']}")
        print(f"   Daily PnL: ${risk_metrics['daily_pnl']:.2f}")
        print(f"   Max Drawdown: {risk_metrics['max_drawdown']:.2%}")
        print(f"   Consecutive Losses: {risk_metrics['consecutive_losses']}")
        print(f"   Total Trades: {risk_metrics['total_trades']}")
        print(f"   Win Rate: {risk_metrics['win_rate']:.1%}")
        print(f"   Kill Switch: {'🔴 ACTIVE' if risk_metrics['kill_switch'] else '🟢 INACTIVE'}")
        
        if risk_metrics['kill_switch']:
            print(f"   Reason: {risk_metrics['kill_switch_reason']}")
        
        print("\n📝 Remember to close any open positions manually if needed!")

if __name__ == "__main__":
    main()