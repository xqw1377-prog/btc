from typing import Dict, Any, List
import json
from datetime import datetime

class SelfOptimizationLoop:
    def __init__(self):
        self.trade_logs = []
        self.analysis_period = 50
        self.optimization_interval = 10
        
        self.param_history = {
            'trend_weight': [],
            'exec_weight': [],
            'position_size': [],
            'stop_loss_pct': []
        }
        
        self.current_params = {
            'trend_weight': 0.6,
            'exec_weight': 0.4,
            'position_size': 0.1,
            'stop_loss_pct': 0.015
        }
    
    def log_trade(self, trade_data: Dict[str, Any]):
        trade_data['timestamp'] = datetime.now().isoformat()
        self.trade_logs.append(trade_data)
        
        if len(self.trade_logs) > 200:
            self.trade_logs = self.trade_logs[-200:]
    
    def analyze_recent_trades(self) -> Dict[str, Any]:
        if len(self.trade_logs) < self.analysis_period:
            return {'status': 'insufficient_data'}
        
        recent_trades = self.trade_logs[-self.analysis_period:]
        
        trend_trades = [t for t in recent_trades if t.get('engine') == 'TREND']
        exec_trades = [t for t in recent_trades if t.get('engine') == 'EXECUTION']
        
        trend_pnl = sum(t.get('pnl', 0) for t in trend_trades)
        exec_pnl = sum(t.get('pnl', 0) for t in exec_trades)
        
        trend_win_rate = sum(1 for t in trend_trades if t.get('pnl', 0) > 0) / len(trend_trades) if trend_trades else 0
        exec_win_rate = sum(1 for t in exec_trades if t.get('exec_pnl', 0) > 0) / len(exec_trades) if exec_trades else 0
        
        return {
            'total_trades': len(recent_trades),
            'trend_trades': len(trend_trades),
            'exec_trades': len(exec_trades),
            'trend_pnl': trend_pnl,
            'exec_pnl': exec_pnl,
            'trend_win_rate': trend_win_rate,
            'exec_win_rate': exec_win_rate,
            'status': 'complete'
        }
    
    def optimize(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        if analysis_results['status'] != 'complete':
            return {'updated': False, 'reason': 'insufficient data'}
        
        trend_score = analysis_results['trend_win_rate'] * (1 + analysis_results['trend_pnl'] / 1000)
        exec_score = analysis_results['exec_win_rate'] * (1 + analysis_results['exec_pnl'] / 1000)
        
        total = trend_score + exec_score
        
        if total > 0:
            new_trend_weight = trend_score / total
            new_exec_weight = exec_score / total
        else:
            new_trend_weight = 0.5
            new_exec_weight = 0.5
        
        self.current_params['trend_weight'] = new_trend_weight
        self.current_params['exec_weight'] = new_exec_weight
        
        avg_win_rate = (analysis_results['trend_win_rate'] + analysis_results['exec_win_rate']) / 2
        
        if avg_win_rate < 0.4:
            self.current_params['position_size'] = max(0.05, self.current_params['position_size'] * 0.8)
            self.current_params['stop_loss_pct'] = min(0.03, self.current_params['stop_loss_pct'] * 1.2)
        elif avg_win_rate > 0.6:
            self.current_params['position_size'] = min(0.2, self.current_params['position_size'] * 1.1)
            self.current_params['stop_loss_pct'] = max(0.01, self.current_params['stop_loss_pct'] * 0.9)
        
        self._record_params()
        
        return {
            'updated': True,
            'new_params': self.current_params.copy(),
            'analysis': analysis_results
        }
    
    def _record_params(self):
        self.param_history['trend_weight'].append(self.current_params['trend_weight'])
        self.param_history['exec_weight'].append(self.current_params['exec_weight'])
        self.param_history['position_size'].append(self.current_params['position_size'])
        self.param_history['stop_loss_pct'].append(self.current_params['stop_loss_pct'])
        
        for key in self.param_history:
            if len(self.param_history[key]) > 50:
                self.param_history[key] = self.param_history[key][-50:]
    
    def get_params(self) -> Dict[str, float]:
        return self.current_params.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            'current_params': self.current_params,
            'trade_count': len(self.trade_logs),
            'analysis_period': self.analysis_period,
            'optimization_interval': self.optimization_interval
        }
    
    def save_trade_logs(self, filename: str):
        with open(filename, 'w') as f:
            json.dump(self.trade_logs, f, indent=2)
