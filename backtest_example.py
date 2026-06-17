from aurora.backtester import Backtester
import pandas as pd

def main():
    backtester = Backtester()
    
    data = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=1000, freq='1min'),
        'open': 45000 + pd.Series(range(1000)) * 10,
        'high': 45000 + pd.Series(range(1000)) * 10 + 50,
        'low': 45000 + pd.Series(range(1000)) * 10 - 50,
        'close': 45000 + pd.Series(range(1000)) * 10 + pd.Series(range(1000)).apply(lambda x: (x % 20 - 10) * 5),
        'volume': 10000 + pd.Series(range(1000)) * 10,
        'vwap': 45000 + pd.Series(range(1000)) * 10,
        'oi': 50000 + pd.Series(range(1000)) * 50,
        'funding_rate': 0.0001
    })
    
    results = backtester.run_backtest(data)
    
    print("=== Backtest Results ===")
    print(f"Total Return: {results['total_return']:.2f}%")
    print(f"Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Win Rate: {results['win_rate']:.2f}%")
    print(f"Final Balance: ${results['final_balance']:.2f}")
    print(f"Total Trades: {results['trades']}")

if __name__ == "__main__":
    main()
