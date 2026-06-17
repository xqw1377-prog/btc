from typing import Dict, Any, Optional
import numpy as np

class StrategyEvolution:
    def __init__(self):
        self.trend_stats = {
            'total_pnl': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
            'win_trades': 0
        }
        
        self.exec_stats = {
            'total_pnl': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
            'win_trades': 0
        }
        
        self.weights = {'trend': 0.6, 'execution': 0.4}
        self.min_weight = 0.1
        self.max_weight = 0.9
    
    def update_trend_stat(self, pnl: float, is_win: bool):
        self.trend_stats['total_pnl'] += pnl
        self.trend_stats['total_trades'] += 1
        if is_win:
            self.trend_stats['win_trades'] += 1
        
        self._calculate_metrics()
    
    def update_exec_stat(self, pnl: float, is_win: bool):
        self.exec_stats['total_pnl'] += pnl
        self.exec_stats['total_trades'] += 1
        if is_win:
            self.exec_stats['win_trades'] += 1
        
        self._calculate_metrics()
    
    def _calculate_metrics(self):
        if self.trend_stats['total_trades'] > 0:
            self.trend_stats['win_rate'] = self.trend_stats['win_trades'] / self.trend_stats['total_trades']
        
        if self.exec_stats['total_trades'] > 0:
            self.exec_stats['win_rate'] = self.exec_stats['win_trades'] / self.exec_stats['total_trades']
    
    def update_weights(self):
        trend_score = self._calculate_strategy_score(self.trend_stats)
        exec_score = self._calculate_strategy_score(self.exec_stats)
        
        total = trend_score + exec_score
        
        if total > 0:
            self.weights['trend'] = trend_score / total
            self.weights['execution'] = exec_score / total
        
        self.weights['trend'] = max(self.min_weight, min(self.max_weight, self.weights['trend']))
        self.weights['execution'] = max(self.min_weight, min(self.max_weight, self.weights['execution']))
    
    def _calculate_strategy_score(self, stats: Dict[str, Any]) -> float:
        if stats['total_trades'] < 5:
            return 0.5
        
        sharpe_component = stats.get('sharpe', 0) * 0.4
        win_rate_component = stats.get('win_rate', 0) * 0.3
        dd_component = max(0, 1 - stats.get('max_drawdown', 0)) * 0.3
        
        return sharpe_component + win_rate_component + dd_component
    
    def get_weights(self) -> Dict[str, float]:
        return self.weights.copy()
    
    def get_strategy_scores(self) -> Dict[str, float]:
        return {
            'trend': self._calculate_strategy_score(self.trend_stats),
            'execution': self._calculate_strategy_score(self.exec_stats)
        }
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            'weights': self.weights,
            'trend_stats': self.trend_stats,
            'exec_stats': self.exec_stats,
            'trend_score': self._calculate_strategy_score(self.trend_stats),
            'exec_score': self._calculate_strategy_score(self.exec_stats)
        }
