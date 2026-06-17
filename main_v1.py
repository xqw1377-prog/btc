import time
import pandas as pd
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v1 import MarketStateEngineV1
from aurora.strategy_router import StrategyRouter
from aurora.paper_trading import PaperTradingAccount

def main():
    ws = BinanceWS("btcusdt")
    feature_engine = FeatureEngine()
    state_engine = MarketStateEngineV1()
    router = StrategyRouter()
    paper_account = PaperTradingAccount(initial_balance=10000.0)
    
    print("Starting AURORA BTC Engine V1...")
    print("Connecting to Binance WebSocket...")
    
    ws.start_in_thread()
    
    time.sleep(5)
    
    print("Connected. Waiting for data...")
    
    try:
        while True:
            buffer = ws.get_buffer()
            
            if len(buffer) < 100:
                print(f"Buffer: {len(buffer)}/100...", end='\r')
                time.sleep(1)
                continue
            
            df = pd.DataFrame(buffer)
            
            features = feature_engine.get_latest_features(df)
            
            market_state = state_engine.identify_regime(features)
            
            signal = router.route(df, market_state)
            
            current_price = features.get('close', 0)
            paper_account.update(current_price)
            
            if signal['signal'] != "NONE":
                print(f"\n=== SIGNAL ===")
                print(f"Engine: {signal['engine']}")
                print(f"Signal: {signal['signal']}")
                print(f"Direction: {signal.get('direction')}")
                print(f"Reason: {signal['reason']}")
                
                if signal['signal'] == "ENTER":
                    position_size = 0.1 if signal['engine'] == "EXECUTION" else 0.4
                    size_in_btc = (paper_account.balance * position_size) / current_price
                    
                    result = paper_account.place_order(
                        symbol="BTCUSDT",
                        side=signal['direction'],
                        order_type="MARKET",
                        size=size_in_btc,
                        price=current_price
                    )
                    
                    if result['success']:
                        print(f"Order filled at: ${result['fill_price']:.2f}")
                        print(f"Position size: {size_in_btc:.4f} BTC")
                
                elif signal['signal'] == "ADD":
                    position_size = 0.3
                    size_in_btc = (paper_account.balance * position_size) / current_price
                    
                    result = paper_account.place_order(
                        symbol="BTCUSDT",
                        side=signal['direction'],
                        order_type="MARKET",
                        size=size_in_btc,
                        price=current_price
                    )
                    
                    if result['success']:
                        print(f"Added position at: ${result['fill_price']:.2f}")
                
                elif signal['signal'] == "EXIT":
                    result = paper_account.close_position("BTCUSDT")
                    
                    if result['success']:
                        print(f"Position closed at: ${result['close_price']:.2f}")
                        print(f"Trade PnL: ${result['pnl']:.2f}")
            
            account_summary = paper_account.get_account_summary()
            
            print(f"\rBalance: ${account_summary['balance']:.2f} | "
                  f"Equity: ${account_summary['equity']:.2f} | "
                  f"Regime: {market_state['regime']} ({market_state['confidence']:.2f}) | "
                  f"Positions: {len(account_summary['positions'])}", end='')
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\nStopping AURORA...")
        ws.stop()
        print("Disconnected from Binance.")
        
        final_summary = paper_account.get_account_summary()
        print("\n=== Final Account Summary ===")
        print(f"Initial Balance: $10,000.00")
        print(f"Final Balance: ${final_summary['balance']:.2f}")
        print(f"Final Equity: ${final_summary['equity']:.2f}")
        print(f"Total Trades: {final_summary['total_trades']}")
        print(f"Open Positions: {len(final_summary['positions'])}")

if __name__ == "__main__":
    main()
