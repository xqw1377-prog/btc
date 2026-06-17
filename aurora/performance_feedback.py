from typing import Dict, Any, List
from datetime import datetime, timedelta

class PerformanceFeedback:
    def __init__(self):
        self.feedback_window = 20
        self.min_trades_for_feedback = 5
        
        self.weights = {
            'trend_weight': 1.0,
            'exec_weight': 1.0,
            'risk_multiplier': 1.0
        }
        
        self.performance_history: List[Dict[str, Any]] = []
        self.recent_trades: List[Dict[str, Any]] = []
        
        self.adaptation_rate = 0.1
        self.max_weight = 2.0
        self.min_weight = 0.3
    
    def record_trade(self, trade_result: Dict[str, Any]):
        self.recent_trades.append(trade_result)
        if len(self.recent_trades) > self.feedback_window:
            self.recent_trades = self.recent_trades[-self.feedback_window:]
        
        self._update_weights()
    
    def _update_weights(self):
        if len(self.recent_trades) < self.min_trades_for_feedback:
            return
        
        trend_trades = [t for t in self.recent_trades if t.get('engine') == 'TREND']
        exec_trades = [t for t in self.recent_trades if t.get('engine') == 'EXECUTION']
        
        if trend_trades:
            trend_pnl = sum(t.get('pnl', 0) for t in trend_trades)
            trend_win_rate = len([t for t in trend_trades if t.get('pnl', 0) > 0]) / len(trend_trades)
            
            if trend_pnl < 0 or trend_win_rate < 0.4:
                self.weights['trend_weight'] *= (1 - self.adaptation_rate)
            elif trend_win_rate > 0.6:
                self.weights['trend_weight'] *= (1 + self.adaptation_rate)
        
        if exec_trades:
            exec_pnl = sum(t.get('pnl', 0) for t in exec_trades)
            exec_win_rate = len([t for t in exec_trades if t.get('pnl', 0) > 0]) / len(exec_trades)
            
            if exec_pnl < 0 or exec_win_rate < 0.4:
                self.weights['exec_weight'] *= (1 - self.adaptation_rate)
            elif exec_win_rate > 0.6:
                self.weights['exec_weight'] *= (1 + self.adaptation_rate)
        
        total_pnl = sum(t.get('pnl', 0) for t in self.recent_trades)
        if total_pnl < 0:
            self.weights['risk_multiplier'] *= (1 - self.adaptation_rate * 0.5)
        elif total_pnl > 0:
            self.weights['risk_multiplier'] *= (1 + self.adaptation_rate * 0.25)
        
        for key in self.weights:
            self.weights[key] = max(self.min_weight, min(self.max_weight, self.weights[key]))
    
    def get_weights(self) -> Dict[str, float]:
        return self.weights.copy()
    
    def get_engine_weight(self, engine_type: str) -> float:
        if engine_type == "TREND":
            return self.weights['trend_weight']
        elif engine_type == "EXECUTION":
            return self.weights['exec_weight']
        return 1.0
    
    def get_risk_multiplier(self) -> float:
        return self.weights['risk_multiplier']
    
    def get_performance_summary(self) -> Dict[str, Any]:
        if not self.recent_trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'trend_stats': {},
                'exec_stats': {}
            }
        
        total_trades = len(self.recent_trades)
        winning_trades = len([t for t in self.recent_trades if t.get('pnl', 0) > 0])
        total_pnl = sum(t.get('pnl', 0) for t in self.recent_trades)
        
        trend_trades = [t for t in self.recent_trades if t.get('engine') == 'TREND']
        exec_trades = [t for t in self.recent_trades if t.get('engine') == 'EXECUTION']
        
        def calc_engine_stats(trades):
            if not trades:
                return {'count': 0, 'win_rate': 0, 'total_pnl': 0, 'avg_pnl': 0}
            
            wins = len([t for t in trades if t.get('pnl', 0) > 0])
            pnl = sum(t.get('pnl', 0) for t in trades)
            
            return {
                'count': len(trades),
                'win_rate': wins / len(trades),
                'total_pnl': pnl,
                'avg_pnl': pnl / len(trades)
            }
        
        return {
            'total_trades': total_trades,
            'win_rate': winning_trades / total_trades,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / total_trades,
            'trend_stats': calc_engine_stats(trend_trades),
            'exec_stats': calc_engine_stats(exec_trades),
            'weights': self.weights
        }
    
    def should_reduce_exposure(self) -> bool:
        if len(self.recent_trades) < 5:
            return False
        
        recent_pnl = sum(t.get('pnl', 0) for t in self.recent_trades[-5:])
        if recent_pnl < 0:
            return True
        
        recent_win_rate = len([t for t in self.recent_trades[-5:] if t.get('pnl', 0) > 0]) / 5
        if recent_win_rate < 0.3:
            return True
        
        return False
    
    def should_increase_exposure(self) -> bool:
        if len(self.recent_trades) < 5:
            return False
        
        recent_pnl = sum(t.get('pnl', 0) for t in self.recent_trades[-5:])
        if recent_pnl > 0:
            return True
        
        recent_win_rate = len([t for t in self.recent_trades[-5:] if t.get('pnl', 0) > 0]) / 5
        if recent_win_rate > 0.7:
            return True
        
        return False
    
    def get_adjusted_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        if signal.get('signal') == 'NONE':
            return signal
        
        engine = signal.get('engine', 'UNKNOWN')
        weight = self.get_engine_weight(engine)
        
        if weight < 0.5:
            return {
                **signal,
                'signal': 'NONE',
                'reason': f'Engine weight too low ({weight:.2f})'
            }
        
        if self.should_reduce_exposure():
            signal['size_multiplier'] = 0.5
        elif self.should_increase_exposure():
            signal['size_multiplier'] = 1.2
        else:
            signal['size_multiplier'] = 1.0
        
        signal['engine_weight'] = weight
        signal['risk_multiplier'] = self.get_risk_multiplier()
        
        return signal