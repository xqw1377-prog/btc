from typing import Dict, Any
import numpy as np

class CapitalAllocationEngine:
    def __init__(self, initial_capital: float = 10000.0):
        self.total_capital = initial_capital
        self.risk_off_reserve = 0.2
        
        self.trend_allocation = 0.48
        self.execution_allocation = 0.32
        self.idle_allocation = 0.2
        
        self.min_trend = 0.1
        self.min_execution = 0.1
        self.max_trend = 0.7
        self.max_execution = 0.5
    
    def allocate(self, strategy_scores: Dict[str, float], risk_metrics: Dict[str, float]) -> Dict[str, float]:
        trend_score = strategy_scores.get('trend', 0.5)
        exec_score = strategy_scores.get('execution', 0.5)
        
        total_score = trend_score + exec_score
        
        if total_score > 0:
            base_trend = trend_score / total_score * (1 - self.risk_off_reserve)
            base_exec = exec_score / total_score * (1 - self.risk_off_reserve)
        else:
            base_trend = 0.5
            base_exec = 0.5
        
        drawdown = risk_metrics.get('max_drawdown', 0)
        volatility = risk_metrics.get('volatility', 1.0)
        
        risk_adjustment = self._calculate_risk_adjustment(drawdown, volatility)
        
        self.trend_allocation = self._clamp(base_trend * risk_adjustment, self.min_trend, self.max_trend)
        self.execution_allocation = self._clamp(base_exec * risk_adjustment, self.min_execution, self.max_execution)
        self.idle_allocation = 1 - self.trend_allocation - self.execution_allocation
        
        return {
            'trend': self.trend_allocation * self.total_capital,
            'execution': self.execution_allocation * self.total_capital,
            'idle': self.idle_allocation * self.total_capital,
            'allocations': {
                'trend': self.trend_allocation,
                'execution': self.execution_allocation,
                'idle': self.idle_allocation
            }
        }
    
    def _calculate_risk_adjustment(self, drawdown: float, volatility: float) -> float:
        dd_factor = max(0.5, 1 - drawdown * 2)
        vol_factor = max(0.6, 1 - (volatility - 2) * 0.15)
        
        return min(1.0, dd_factor * vol_factor)
    
    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        return max(min_val, min(max_val, value))
    
    def update_total_capital(self, new_capital: float):
        self.total_capital = new_capital
    
    def get_allocation_ratios(self) -> Dict[str, float]:
        return {
            'trend': self.trend_allocation,
            'execution': self.execution_allocation,
            'idle': self.idle_allocation
        }
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            'total_capital': self.total_capital,
            'trend_allocation': self.trend_allocation,
            'execution_allocation': self.execution_allocation,
            'idle_allocation': self.idle_allocation,
            'trend_amount': self.trend_allocation * self.total_capital,
            'execution_amount': self.execution_allocation * self.total_capital,
            'idle_amount': self.idle_allocation * self.total_capital
        }
