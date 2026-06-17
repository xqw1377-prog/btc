from typing import Dict, Any, Optional
import numpy as np
from datetime import datetime

class CapitalGrowthEngine:
    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        
        self.risk_adjuster = RiskAdjustedPositioning()
        self.dd_compressor = DrawdownCompressionEngine()
        self.sharpe_controller = SharpeMaximizationController()
        
        self.equity_curve = []
        self.drawdown_history = []
        
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0
        
        self.last_rebalance_time = datetime.now()
    
    def update_pnl(self, pnl: float):
        self.total_pnl += pnl
        self.current_capital += pnl
        
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        self.drawdown_history.append(drawdown)
        
        if len(self.drawdown_history) > 100:
            self.drawdown_history = self.drawdown_history[-100:]
        
        self.equity_curve.append({
            'timestamp': datetime.now(),
            'capital': self.current_capital,
            'drawdown': drawdown,
            'pnl': pnl
        })
        
        if pnl > 0:
            self.win_count += 1
        self.trade_count += 1
    
    def get_position_size(self, market_state: Dict[str, Any]) -> float:
        edge = self._calculate_edge(market_state)
        confidence = market_state.get('confidence', 0.5)
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        
        return self.risk_adjuster.calculate_position(
            balance=self.current_capital,
            edge=edge,
            confidence=confidence,
            drawdown=drawdown
        )
    
    def _calculate_edge(self, market_state: Dict[str, Any]) -> float:
        regime = market_state.get('regime', 'TRANSITION')
        
        edge_map = {
            'TRENDING': 1.5,
            'MEAN_REVERTING': 1.0,
            'LIQUIDITY_DRIVEN': 0.8,
            'TRANSITION': 0.3
        }
        
        return edge_map.get(regime, 0.5)
    
    def check_drawdown_status(self) -> str:
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        return self.dd_compressor.get_status(drawdown)
    
    def get_strategy_weights(self) -> Dict[str, float]:
        trend_sharpe = self._calculate_engine_sharpe('trend')
        exec_sharpe = self._calculate_engine_sharpe('execution')
        
        return self.sharpe_controller.adjust_weights(trend_sharpe, exec_sharpe)
    
    def _calculate_engine_sharpe(self, engine_type: str) -> float:
        if self.trade_count < 10:
            return 0.5
        
        pnl_history = [e['pnl'] for e in self.equity_curve[-50:]]
        
        if len(pnl_history) < 10:
            return 0.5
        
        returns = np.array(pnl_history) / self.initial_capital
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.5
        
        sharpe = np.sqrt(252 * 24) * mean_return / std_return
        return max(0, min(2, sharpe))
    
    def should_trade(self) -> bool:
        status = self.check_drawdown_status()
        return status != 'KILL'
    
    def get_risk_multiplier(self) -> float:
        status = self.check_drawdown_status()
        
        if status == 'KILL':
            return 0.0
        elif status == 'REDUCE_50':
            return 0.5
        return 1.0
    
    def get_summary(self) -> Dict[str, Any]:
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        max_dd = max(self.drawdown_history) if self.drawdown_history else 0
        
        return {
            'initial_capital': round(self.initial_capital, 2),
            'current_capital': round(self.current_capital, 2),
            'peak_capital': round(self.peak_capital, 2),
            'drawdown': round(drawdown * 100, 2),
            'max_drawdown': round(max_dd * 100, 2),
            'total_pnl': round(self.total_pnl, 2),
            'trade_count': self.trade_count,
            'win_rate': round(self.win_count / max(self.trade_count, 1) * 100, 2),
            'equity_curve_length': len(self.equity_curve),
            'risk_multiplier': self.get_risk_multiplier(),
            'drawdown_status': self.check_drawdown_status()
        }

class RiskAdjustedPositioning:
    def __init__(self):
        self.base_risk = 0.01
        self.max_position_ratio = 0.5
        self.min_position_ratio = 0.05
    
    def calculate_position(self, balance: float, edge: float, confidence: float, drawdown: float) -> float:
        stability = max(0.1, 1 - drawdown / 0.1)
        
        position_ratio = self.base_risk * edge * confidence * stability
        
        position_ratio = max(self.min_position_ratio, min(self.max_position_ratio, position_ratio))
        
        return balance * position_ratio

class DrawdownCompressionEngine:
    def __init__(self, critical_threshold: float = 0.05, warning_threshold: float = 0.03):
        self.critical_threshold = critical_threshold
        self.warning_threshold = warning_threshold
    
    def get_status(self, drawdown: float) -> str:
        if drawdown > self.critical_threshold:
            return 'KILL'
        elif drawdown > self.warning_threshold:
            return 'REDUCE_50'
        return 'OK'
    
    def get_reduction_factor(self, drawdown: float) -> float:
        status = self.get_status(drawdown)
        
        if status == 'KILL':
            return 0.0
        elif status == 'REDUCE_50':
            return 0.5
        return 1.0

class SharpeMaximizationController:
    def __init__(self):
        self.min_weight = 0.1
        self.max_weight = 0.9
    
    def adjust_weights(self, sharpe_trend: float, sharpe_exec: float) -> Dict[str, float]:
        total = sharpe_trend + sharpe_exec + 1e-6
        
        trend_weight = sharpe_trend / total
        exec_weight = sharpe_exec / total
        
        trend_weight = max(self.min_weight, min(self.max_weight, trend_weight))
        exec_weight = max(self.min_weight, min(self.max_weight, exec_weight))
        
        total_weight = trend_weight + exec_weight
        if total_weight > 0:
            trend_weight /= total_weight
            exec_weight /= total_weight
        
        return {
            'trend': round(trend_weight, 2),
            'execution': round(exec_weight, 2)
        }
