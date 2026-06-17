import pandas as pd
import numpy as np
from typing import Dict, Any, List
from datetime import datetime

class BacktestEngine:
    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity_curve: List[float] = []
        self.trades: List[Dict[str, Any]] = []
        self.current_position = None
        self.trade_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        self.commission_rate = 0.0004
        self.slippage_rate = 0.0001
    
    def reset(self):
        self.balance = self.initial_balance
        self.equity_curve = []
        self.trades = []
        self.current_position = None
        self.trade_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
    
    def simulate_trade(
        self,
        signal: Dict[str, Any],
        current_price: float,
        market_state: Dict[str, Any],
        timestamp: Any = None
    ) -> Dict[str, Any]:
        
        if signal.get('signal') == 'NONE':
            return {'action': 'HOLD'}
        
        if signal.get('signal') == 'ENTER':
            return self._open_position(signal, current_price, market_state, timestamp)
        elif signal.get('signal') == 'EXIT':
            return self._close_position(current_price, timestamp)
        elif signal.get('signal') == 'ADD':
            return self._add_position(signal, current_price, timestamp)
        
        return {'action': 'HOLD'}
    
    def _open_position(
        self,
        signal: Dict[str, Any],
        price: float,
        market_state: Dict[str, Any],
        timestamp: Any
    ) -> Dict[str, Any]:
        
        if self.current_position is not None:
            return {'action': 'HOLD', 'reason': 'Already in position'}
        
        direction = signal.get('direction', 'LONG')
        engine = signal.get('engine', 'UNKNOWN')
        
        position_pct = 0.02
        if signal.get('size_multiplier'):
            position_pct *= signal['size_multiplier']
        
        position_value = self.balance * position_pct
        quantity = position_value / price
        
        commission = position_value * self.commission_rate
        slippage = position_value * self.slippage_rate
        
        if direction == 'LONG':
            entry_price = price * (1 + self.slippage_rate)
        else:
            entry_price = price * (1 - self.slippage_rate)
        
        self.current_position = {
            'direction': direction,
            'engine': engine,
            'entry_price': entry_price,
            'quantity': quantity,
            'entry_time': timestamp,
            'regime': market_state.get('regime', 'UNKNOWN'),
            'commission': commission
        }
        
        self.balance -= commission
        
        return {
            'action': 'OPEN',
            'direction': direction,
            'price': entry_price,
            'quantity': quantity,
            'commission': commission
        }
    
    def _close_position(
        self,
        price: float,
        timestamp: Any
    ) -> Dict[str, Any]:
        
        if self.current_position is None:
            return {'action': 'HOLD', 'reason': 'No position to close'}
        
        direction = self.current_position['direction']
        entry_price = self.current_position['entry_price']
        quantity = self.current_position['quantity']
        
        if direction == 'LONG':
            exit_price = price * (1 - self.slippage_rate)
            pnl = (exit_price - entry_price) * quantity
        else:
            exit_price = price * (1 + self.slippage_rate)
            pnl = (entry_price - exit_price) * quantity
        
        commission = (quantity * exit_price) * self.commission_rate
        net_pnl = pnl - commission
        
        self.balance += net_pnl
        self.trade_count += 1
        
        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        trade_record = {
            'direction': direction,
            'engine': self.current_position['engine'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'quantity': quantity,
            'pnl': net_pnl,
            'pnl_pct': net_pnl / (entry_price * quantity),
            'commission': commission + self.current_position['commission'],
            'regime': self.current_position['regime'],
            'entry_time': self.current_position['entry_time'],
            'exit_time': timestamp
        }
        
        self.trades.append(trade_record)
        self.current_position = None
        
        return {
            'action': 'CLOSE',
            'pnl': net_pnl,
            'pnl_pct': trade_record['pnl_pct'],
            'price': exit_price
        }
    
    def _add_position(
        self,
        signal: Dict[str, Any],
        price: float,
        timestamp: Any
    ) -> Dict[str, Any]:
        
        if self.current_position is None:
            return self._open_position(signal, price, {'regime': 'UNKNOWN'}, timestamp)
        
        return {'action': 'HOLD', 'reason': 'Add not implemented in backtest'}
    
    def update_equity(self, current_price: float):
        if self.current_position:
            direction = self.current_position['direction']
            entry_price = self.current_position['entry_price']
            quantity = self.current_position['quantity']
            
            if direction == 'LONG':
                unrealized_pnl = (current_price - entry_price) * quantity
            else:
                unrealized_pnl = (entry_price - current_price) * quantity
            
            equity = self.balance + unrealized_pnl
        else:
            equity = self.balance
        
        self.equity_curve.append(equity)
    
    def get_results(self) -> Dict[str, Any]:
        if not self.equity_curve:
            return {}
        
        equity_series = pd.Series(self.equity_curve)
        
        total_return = (self.balance - self.initial_balance) / self.initial_balance
        
        peak = equity_series.expanding().max()
        drawdown = (equity_series - peak) / peak
        max_drawdown = drawdown.min()
        
        daily_returns = equity_series.pct_change().dropna()
        
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
        
        win_rate = self.winning_trades / self.trade_count if self.trade_count > 0 else 0
        
        winning_pnl = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        losing_pnl = sum(abs(t['pnl']) for t in self.trades if t['pnl'] < 0)
        avg_win = winning_pnl / self.winning_trades if self.winning_trades > 0 else 0
        avg_loss = losing_pnl / self.losing_trades if self.losing_trades > 0 else 0
        profit_factor = winning_pnl / losing_pnl if losing_pnl > 0 else float('inf')
        
        total_commission = sum(t['commission'] for t in self.trades)
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': round(self.balance, 2),
            'total_return': round(total_return * 100, 2),
            'total_trades': self.trade_count,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(win_rate * 100, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'total_commission': round(total_commission, 2),
            'equity_curve': self.equity_curve
        }
    
    def get_trade_analysis(self) -> Dict[str, Any]:
        if not self.trades:
            return {}
        
        trades_df = pd.DataFrame(self.trades)
        
        regime_analysis = {}
        for regime in trades_df['regime'].unique():
            regime_trades = trades_df[trades_df['regime'] == regime]
            regime_analysis[regime] = {
                'count': len(regime_trades),
                'win_rate': len(regime_trades[regime_trades['pnl'] > 0]) / len(regime_trades),
                'total_pnl': regime_trades['pnl'].sum(),
                'avg_pnl': regime_trades['pnl'].mean()
            }
        
        engine_analysis = {}
        for engine in trades_df['engine'].unique():
            engine_trades = trades_df[trades_df['engine'] == engine]
            engine_analysis[engine] = {
                'count': len(engine_trades),
                'win_rate': len(engine_trades[engine_trades['pnl'] > 0]) / len(engine_trades),
                'total_pnl': engine_trades['pnl'].sum(),
                'avg_pnl': engine_trades['pnl'].mean()
            }
        
        return {
            'regime_analysis': regime_analysis,
            'engine_analysis': engine_analysis
        }