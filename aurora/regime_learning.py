from typing import Dict, Any, List
from datetime import datetime, timedelta
import json
import os

class RegimeLearningLayer:
    def __init__(self, data_file: str = "regime_stats.json"):
        self.data_file = data_file
        self.regime_stats = {
            "TREND": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_rate": 0.5,
                "avg_rr": 1.0,
                "sharpe": 0.0
            },
            "RANGE": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_rate": 0.5,
                "avg_rr": 1.0,
                "sharpe": 0.0
            },
            "TRANSITION": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_rate": 0.5,
                "avg_rr": 1.0,
                "sharpe": 0.0
            }
        }
        
        self.trade_history: List[Dict[str, Any]] = []
        self.recent_trades: List[Dict[str, Any]] = []
        self.max_recent_trades = 100
        
        self.load_stats()
    
    def load_stats(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.regime_stats = data.get('regime_stats', self.regime_stats)
                    self.trade_history = data.get('trade_history', [])
                    self.recent_trades = self.trade_history[-self.max_recent_trades:]
            except Exception as e:
                print(f"Error loading stats: {e}")
    
    def save_stats(self):
        try:
            data = {
                'regime_stats': self.regime_stats,
                'trade_history': self.trade_history[-1000:],
                'last_updated': datetime.now().isoformat()
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving stats: {e}")
    
    def record_trade(self, trade_result: Dict[str, Any]):
        regime = trade_result.get('regime', 'TRANSITION')
        pnl = trade_result.get('pnl', 0)
        entry_price = trade_result.get('entry_price', 0)
        exit_price = trade_result.get('exit_price', 0)
        direction = trade_result.get('direction', 'LONG')
        engine = trade_result.get('engine', 'UNKNOWN')
        
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'regime': regime,
            'engine': engine,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'pnl_pct': (exit_price - entry_price) / entry_price if direction == 'LONG' else (entry_price - exit_price) / entry_price
        }
        
        self.trade_history.append(trade_record)
        self.recent_trades.append(trade_record)
        if len(self.recent_trades) > self.max_recent_trades:
            self.recent_trades = self.recent_trades[-self.max_recent_trades:]
        
        stats = self.regime_stats.get(regime, self.regime_stats['TRANSITION'])
        stats['total_trades'] += 1
        stats['total_pnl'] += pnl
        
        if pnl > 0:
            stats['winning_trades'] += 1
            stats['avg_win'] = ((stats['avg_win'] * (stats['winning_trades'] - 1)) + pnl) / stats['winning_trades']
        else:
            stats['losing_trades'] += 1
            stats['avg_loss'] = ((stats['avg_loss'] * (stats['losing_trades'] - 1)) + abs(pnl)) / stats['losing_trades']
        
        if stats['total_trades'] > 0:
            stats['win_rate'] = stats['winning_trades'] / stats['total_trades']
        
        if stats['avg_loss'] > 0:
            stats['avg_rr'] = stats['avg_win'] / stats['avg_loss']
        
        self._calculate_drawdown(regime)
        self._calculate_sharpe(regime)
        
        self.regime_stats[regime] = stats
        
        if len(self.trade_history) % 10 == 0:
            self.save_stats()
    
    def _calculate_drawdown(self, regime: str):
        regime_trades = [t for t in self.recent_trades if t.get('regime') == regime]
        
        if len(regime_trades) < 2:
            return
        
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        
        for trade in regime_trades:
            cumulative_pnl += trade.get('pnl', 0)
            if cumulative_pnl > peak:
                peak = cumulative_pnl
            dd = peak - cumulative_pnl
            if dd > max_dd:
                max_dd = dd
        
        self.regime_stats[regime]['max_drawdown'] = max_dd
    
    def _calculate_sharpe(self, regime: str):
        regime_trades = [t for t in self.recent_trades if t.get('regime') == regime]
        
        if len(regime_trades) < 5:
            return
        
        returns = [t.get('pnl_pct', 0) for t in regime_trades]
        
        mean_return = sum(returns) / len(returns)
        
        if len(returns) > 1:
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            std_return = variance ** 0.5
            
            if std_return > 0:
                sharpe = (mean_return / std_return) * (252 ** 0.5)
                self.regime_stats[regime]['sharpe'] = round(sharpe, 2)
    
    def get_regime_stats(self, regime: str) -> Dict[str, Any]:
        return self.regime_stats.get(regime, self.regime_stats['TRANSITION'])
    
    def get_all_stats(self) -> Dict[str, Any]:
        return self.regime_stats
    
    def get_best_regime(self) -> str:
        best_regime = "TRANSITION"
        best_score = -float('inf')
        
        for regime, stats in self.regime_stats.items():
            if stats['total_trades'] < 3:
                continue
            
            score = stats['win_rate'] * stats['avg_rr'] * (1 + stats['sharpe'])
            
            if score > best_score:
                best_score = score
                best_regime = regime
        
        return best_regime
    
    def get_regime_confidence(self, regime: str) -> float:
        stats = self.get_regime_stats(regime)
        
        if stats['total_trades'] < 5:
            return 0.5
        
        confidence = stats['win_rate'] * 0.4 + min(stats['avg_rr'] / 3, 1) * 0.3 + min(stats['sharpe'] / 2, 1) * 0.3
        
        return min(max(confidence, 0.1), 0.9)
    
    def should_trade_regime(self, regime: str) -> bool:
        stats = self.get_regime_stats(regime)
        
        if stats['total_trades'] < 5:
            return True
        
        if stats['win_rate'] < 0.35:
            return False
        
        if stats['sharpe'] < -1.0:
            return False
        
        return True