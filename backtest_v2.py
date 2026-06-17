import pandas as pd
import numpy as np
from datetime import datetime
from aurora.backtest_engine import BacktestEngine
from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v1 import MarketStateEngineV1
from aurora.strategy_router import StrategyRouter
from aurora.position_sizing import PositionSizing

def generate_test_data(days=30):
    timestamps = pd.date_range(start='2024-01-01', periods=days*1440, freq='1min')
    
    base_price = 45000
    prices = []
    current_price = base_price
    
    trend_up = True
    trend_days = 0
    
    for i, ts in enumerate(timestamps):
        if i % 1440 == 0:
            trend_up = np.random.choice([True, False], p=[0.6, 0.4])
            trend_days = 0
        
        trend_days += 1
        
        if trend_up:
            trend_component = trend_days * 5
        else:
            trend_component = -trend_days * 5
        
        noise = np.random.normal(0, 50, 1)[0]
        volatility = np.random.uniform(0.5, 2.0)
        
        current_price = base_price + trend_component + noise * volatility
        
        if i % 60 == 0:
            current_price += np.random.normal(0, 200)
        
        prices.append(current_price)
    
    data = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': [p + np.random.uniform(0, 100) for p in prices],
        'low': [p - np.random.uniform(0, 100) for p in prices],
        'close': prices,
        'volume': [np.random.uniform(5000, 20000) for _ in prices],
        'vwap': prices,
        'oi': [50000 + i * 10 for i in range(len(prices))],
        'funding_rate': [0.0001 for _ in prices]
    })
    
    return data

def create_strategy():
    feature_engine = FeatureEngine()
    state_engine = MarketStateEngineV1()
    router = StrategyRouter()
    position_sizing = PositionSizing()
    
    def strategy(row, idx, current_position):
        df = pd.DataFrame([row])
        
        features = feature_engine.get_latest_features(df)
        market_state = state_engine.identify_regime(features)
        
        if idx > 0:
            signal = router.route(df, market_state)
        else:
            signal = {'signal': 'NONE', 'engine': 'NONE', 'direction': 'LONG'}
        
        if signal['signal'] == 'ENTER':
            size = position_sizing.get_position_size(
                balance=10000,
                price=row['close'],
                regime=market_state['regime'],
                confidence=market_state['confidence'],
                volatility=features.get('volatility', 1.0)
            )
            
            stop_loss = position_sizing.calculate_stop_loss(
                entry_price=row['close'],
                atr=features.get('atr', 100)
            )
            
            take_profit = position_sizing.calculate_take_profit(
                entry_price=row['close'],
                stop_loss=stop_loss
            )
            
            return {
                'signal': 'ENTER',
                'side': signal['direction'],
                'size': size / 10000,
                'stop_loss': stop_loss,
                'take_profit': take_profit
            }
        
        elif signal['signal'] == 'EXIT' and current_position:
            return {'signal': 'EXIT'}
        
        return {'signal': 'NONE'}
    
    return strategy

def main():
    print("🚀 Running AURORA V2 Backtest...")
    
    data = generate_test_data(days=30)
    print(f"📊 Generated {len(data)} minutes of test data")
    
    strategy = create_strategy()
    
    backtester = BacktestEngine()
    results = backtester.run(data, strategy)
    
    print("\n=== Backtest Results ===")
    print(f"💰 Total Return: {results['total_return']}%")
    print(f"📉 Max Drawdown: {results['max_drawdown']}%")
    print(f"📈 Sharpe Ratio: {results['sharpe_ratio']}")
    print(f"🎯 Win Rate: {results['win_rate']}%")
    print(f"🔢 Total Trades: {results['total_trades']}")
    print(f"💵 Final Balance: ${results['final_balance']}")
    print(f"📊 Profit Factor: {results['profit_factor']}")
    
    backtester.save_results('backtest_results.json')
    print("\n✅ Results saved to backtest_results.json")
    
    try:
        backtester.plot_equity_curve()
    except ImportError:
        print("⚠️  matplotlib not installed - skipping plot")

if __name__ == "__main__":
    main()
