import math
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class CapitalObjective:
    target_sharpe: float = 1.5
    max_drawdown: float = 0.08
    risk_free_rate: float = 0.02

class CapitalObjectiveLayer:
    def __init__(self, initial_capital: float, objective: Optional[CapitalObjective] = None):
        self.capital = initial_capital
        self.peak = initial_capital
        self.objective = objective or CapitalObjective()

        self.returns: List[float] = []
        self.equity_curve: List[float] = [initial_capital]
        self.pnl_history: List[float] = []

    def record(self, pnl: float):
        self.pnl_history.append(pnl)
        self.capital += pnl

        if self.capital > self.peak:
            self.peak = self.capital

        ret = pnl / self.peak if self.peak > 0 else 0
        self.returns.append(ret)
        if len(self.returns) > 252:
            self.returns = self.returns[-252:]

        self.equity_curve.append(self.capital)
        if len(self.equity_curve) > 252:
            self.equity_curve = self.equity_curve[-252:]

    def compute_sharpe(self) -> float:
        if len(self.returns) < 10:
            return 0.0
        mean = sum(self.returns) / len(self.returns)
        var = sum((r - mean) ** 2 for r in self.returns) / max(len(self.returns) - 1, 1)
        std = math.sqrt(var) if var > 0 else 0.001
        return (mean * 252 - self.objective.risk_free_rate) / (std * math.sqrt(252))

    def compute_sortino(self) -> float:
        if len(self.returns) < 10:
            return 0.0
        mean = sum(self.returns) / len(self.returns)
        downside = [r for r in self.returns if r < 0]
        if not downside:
            return self.compute_sharpe() * 2
        down_var = sum(r ** 2 for r in downside) / len(downside)
        down_std = math.sqrt(down_var)
        return (mean * 252 - self.objective.risk_free_rate) / (down_std * math.sqrt(252))

    def compute_max_drawdown(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def compute_calmar(self) -> float:
        if len(self.returns) < 10:
            return 0.0
        annual_ret = sum(self.returns) / len(self.returns) * 252
        max_dd = self.compute_max_drawdown()
        return annual_ret / max_dd if max_dd > 0 else 0.0

    def get_objective_score(self) -> float:
        sharpe = self.compute_sharpe()
        max_dd = self.compute_max_drawdown()

        sharpe_score = min(sharpe / self.objective.target_sharpe, 1.5) / 1.5
        dd_penalty = 1.0 if max_dd < self.objective.max_drawdown else max(0, 1 - (max_dd - self.objective.max_drawdown) * 5)

        return sharpe_score * dd_penalty

    def should_trade(self) -> bool:
        if self.compute_max_drawdown() > self.objective.max_drawdown * 1.2:
            return False
        return True

    def get_position_multiplier(self) -> float:
        score = self.get_objective_score()

        if score > 0.8:
            return 1.2
        elif score > 0.5:
            return 1.0
        elif score > 0.3:
            return 0.7
        else:
            return 0.4

    def get_state(self) -> Dict[str, Any]:
        return {
            'capital': self.capital,
            'peak': self.peak,
            'sharpe': round(self.compute_sharpe(), 2),
            'sortino': round(self.compute_sortino(), 2),
            'calmar': round(self.compute_calmar(), 2),
            'max_drawdown': round(self.compute_max_drawdown(), 4),
            'objective_score': round(self.get_objective_score(), 4),
            'position_multiplier': round(self.get_position_multiplier(), 2),
            'should_trade': self.should_trade(),
        }