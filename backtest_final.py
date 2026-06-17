import pandas as pd
import numpy as np
from datetime import datetime
from aurora.backtest_engine import BacktestEngine
from aurora.feature_engine import FeatureEngine
from aurora.adaptive_regime_model import AdaptiveRegimeModel
from aurora.strategy_router import StrategyRouter
from aurora.capital_growth_engine import CapitalGrowthEngine

def generate_test_data(days=60):
    timestamps = pd.date_range(start='2024-01-01', periods=days*1440, freq='1min')
    
    base_price = 45000
    prices = []
    current_price = base_price
    
    trend_up = True
    trend_length = 0
    
    for i, ts in enumerate(timestamps):
        if i % (1440 * 5) == 0:
            trend_up = np.random.choice([True, False], p=[0.6, 0.4])
            trend_length = 0
        
        trend_length += 1
        
        trend_component = trend_length * 3 if trend_up else -trend_length * 3
        noise = np.random.normal(0, 80, 1)[0]
        volatility = np.random.uniform(0.5, 3.0)
        
        current_price = base_price + trend_component + noise * volatility
        
        if i % 60 == 0:
            current_price += np.random.normal(0, 300)
        
        prices.append(current_price)
    
    data = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': [p + np.random.uniform(0, 150) for p in prices],
        'low': [p - np.random.uniform(0, 150) for p in prices],
        'close': prices,
        'volume': [np.random.uniform(5000, 30000) for _ in prices],
        'vwap': prices,
        'oi': [50000 + i * 20 for i in range(len(prices))],
        'funding_rate': [0.0001 * np.random.uniform(-2, 2) for _ in prices]
    })
    
    return data

def main():
    print("🚀 Running AURORA Final Backtest - Capital Growth Mode")
    
    data = generate_test_data(days=60)
    print(f"📊 Generated {len(data)} minutes of test data")
    
    feature_engine = FeatureEngine()
    regime_model = AdaptiveRegimeModel()
    router = StrategyRouter()
    capital_engine = CapitalGrowthEngine(initial_capital=10000.0)
    
    def strategy(row, idx, current_position):
        df = pd.DataFrame([row])
        
        features = feature_engine.get_latest_features(df)
        regime = regime_model.identify_regime(features)
        
        if idx > 100:
            signal = router.route(df, regime)
        else:
            signal = {'signal': 'NONE', 'engine': 'NONE', 'direction': 'LONG'}
        
        if signal['signal'] == 'ENTER':
            if not capital_engine.should_trade():
                return {'signal': 'NONE'}
            
            position_size = capital_engine.get_position_size(regime) / capital_engine.current_capital
            
            return {
                'signal': 'ENTER',
                'side': signal['direction'],
                'size': position_size
            }
        
        elif signal['signal'] == 'EXIT' and current_position:
            return {'signal': 'EXIT'}
        
        return {'signal': 'NONE'}
    
    backtester = BacktestEngine()
    results = backtester.run(data, strategy)
    
    print("\n=== Backtest Results ===")
    print(f"💰 Total Return: {results['total_return']}%")
    print(f"📉 Max Drawdown: {results['max_drawdown']}%")
    print(f"📈 Sharpe Ratio: {results['sharpe_ratio']}")
    print(f"🎯 Win Rate: {results['win_rate']}%")
    print(f"🔢 Total Trades: {results['trades']}")
    print(f"💵 Final Balance: ${results['final_balance']}")
    print(f"📊 Profit Factor: {results['profit_factor']}")
    
    backtester.save_results('backtest_final_results.json')
    print("\n✅ Results saved to backtest_final_results.json")
    
    try:
        backtester.plot_equity_curve()
    except ImportError:
        print("⚠️  matplotlib not installed - skipping plot")

if __name__ == "__main__":
    main()
