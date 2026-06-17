import pandas as pd
import numpy as np
from typing import Dict, Any, List
from datetime import datetime
import json

class BacktestEngine:
    def __init__(self):
        self.equity_curve = []
        self.trades = []
        self.current_position = None
        self.balance = 10000.0
        self.initial_balance = 10000.0
        self.peak_equity = 10000.0
        self.max_drawdown = 0.0
        self.risk_engine = None
    
    def run(self, data: pd.DataFrame, strategy_func) -> Dict[str, Any]:
        self.equity_curve = []
        self.trades = []
        self.current_position = None
        self.balance = self.initial_balance
        self.peak_equity = self.initial_balance
        self.max_drawdown = 0.0
        
        for idx, row in data.iterrows():
            result = strategy_func(row, idx, self.current_position)
            
            if result.get('signal') == 'ENTER':
                position_size = result.get('size', 0.1)
                entry_price = row['close']
                qty = (self.balance * position_size) / entry_price
                
                self.current_position = {
                    'side': result['side'],
                    'entry_price': entry_price,
                    'qty': qty,
                    'size': position_size,
                    'entry_time': row['timestamp'],
                    'stop_loss': result.get('stop_loss'),
                    'take_profit': result.get('take_profit')
                }
            
            elif result.get('signal') == 'EXIT' and self.current_position:
                exit_price = row['close']
                
                if self.current_position['side'] == 'LONG':
                    pnl = (exit_price - self.current_position['entry_price']) * self.current_position['qty']
                else:
                    pnl = (self.current_position['entry_price'] - exit_price) * self.current_position['qty']
                
                self.balance += pnl
                
                self.trades.append({
                    'entry_time': self.current_position['entry_time'],
                    'exit_time': row['timestamp'],
                    'side': self.current_position['side'],
                    'entry_price': self.current_position['entry_price'],
                    'exit_price': exit_price,
                    'qty': self.current_position['qty'],
                    'pnl': pnl,
                    'pnl_pct': pnl / (self.current_position['entry_price'] * self.current_position['qty'])
                })
                
                self.current_position = None
            
            if self.current_position:
                if self.current_position['side'] == 'LONG':
                    unrealized_pnl = (row['close'] - self.current_position['entry_price']) * self.current_position['qty']
                else:
                    unrealized_pnl = (self.current_position['entry_price'] - row['close']) * self.current_position['qty']
                
                equity = self.balance + unrealized_pnl
            else:
                equity = self.balance
            
            self.equity_curve.append({
                'timestamp': row['timestamp'],
                'equity': equity,
                'balance': self.balance,
                'position': self.current_position is not None
            })
            
            self.peak_equity = max(self.peak_equity, equity)
            drawdown = (self.peak_equity - equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, drawdown)
        
        return self.generate_report()
    
    def generate_report(self) -> Dict[str, Any]:
        equity_values = [ec['equity'] for ec in self.equity_curve]
        equity_array = np.array(equity_values)
        
        total_return = (equity_array[-1] - self.initial_balance) / self.initial_balance * 100
        
        returns = equity_array[1:] / equity_array[:-1] - 1
        sharpe_ratio = self.calculate_sharpe(returns)
        
        win_trades = [t for t in self.trades if t['pnl'] > 0]
        win_rate = len(win_trades) / len(self.trades) * 100 if self.trades else 0
        
        avg_win = np.mean([t['pnl'] for t in win_trades]) if win_trades else 0
        avg_loss = np.mean([t['pnl'] for t in self.trades if t['pnl'] <= 0]) if self.trades else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        
        max_win = max([t['pnl'] for t in self.trades]) if self.trades else 0
        max_loss = min([t['pnl'] for t in self.trades]) if self.trades else 0
        
        return {
            'total_return': round(total_return, 2),
            'max_drawdown': round(self.max_drawdown * 100, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'win_rate': round(win_rate, 2),
            'total_trades': len(self.trades),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_win': round(max_win, 2),
            'max_loss': round(max_loss, 2),
            'final_balance': round(self.balance, 2),
            'equity_curve': self.equity_curve,
            'trades': self.trades
        }
    
    def calculate_sharpe(self, returns: np.ndarray) -> float:
        if len(returns) == 0:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        return np.sqrt(252 * 24) * mean_return / std_return
    
    def plot_equity_curve(self):
        import matplotlib.pyplot as plt
        
        timestamps = [ec['timestamp'] for ec in self.equity_curve]
        equity = [ec['equity'] for ec in self.equity_curve]
        
        plt.figure(figsize=(12, 6))
        plt.plot(timestamps, equity, label='Equity')
        plt.title('Equity Curve')
        plt.xlabel('Time')
        plt.ylabel('Equity ($)')
        plt.legend()
        plt.grid(True)
        plt.show()
    
    def save_results(self, filename: str):
        results = self.generate_report()
        results['equity_curve'] = [{
            'timestamp': str(ec['timestamp']),
            'equity': ec['equity'],
            'balance': ec['balance'],
            'position': ec['position']
        } for ec in results['equity_curve']]
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
