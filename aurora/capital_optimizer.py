from typing import Dict, Any, List
from dataclasses import dataclass
import math

@dataclass
class CapitalAllocation:
    trend_pct: float
    execution_pct: float
    reserve_pct: float
    reason: str

@dataclass
class GrowthMetrics:
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float
    expectancy: float

class CapitalCurveOptimizer:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.min_reserve_pct = 0.10
        self.max_single_pct = 0.60

    def calculate_optimal_allocation(self, returns: List[float],
                                     regime_stats: Dict[str, Any]) -> CapitalAllocation:
        if len(returns) < 10:
            return CapitalAllocation(
                trend_pct=0.40, execution_pct=0.20,
                reserve_pct=0.40, reason="Insufficient data, conservative allocation"
            )

        metrics = self._calculate_metrics(returns)

        if metrics.sharpe > 1.5 and metrics.max_drawdown < 0.05:
            trend_pct = 0.55
            exec_pct = 0.25
            reason = f"High Sharpe ({metrics.sharpe:.2f}), low DD ({metrics.max_drawdown:.1%})"
        elif metrics.sharpe > 1.0 and metrics.max_drawdown < 0.08:
            trend_pct = 0.45
            exec_pct = 0.25
            reason = f"Good Sharpe ({metrics.sharpe:.2f}), moderate DD ({metrics.max_drawdown:.1%})"
        elif metrics.sharpe > 0.5:
            trend_pct = 0.35
            exec_pct = 0.20
            reason = f"Moderate Sharpe ({metrics.sharpe:.2f})"
        else:
            trend_pct = 0.25
            exec_pct = 0.15
            reason = f"Low Sharpe ({metrics.sharpe:.2f}), defensive"

        if metrics.max_drawdown > 0.10:
            reduction = min(0.20, (metrics.max_drawdown - 0.10) * 2)
            trend_pct -= reduction
            exec_pct -= reduction * 0.5
            reason += f" | DD penalty -{reduction:.0%}"

        best_regime = max(regime_stats.items(), key=lambda x: x[1].get('win_rate', 0) * x[1].get('avg_rr', 0))
        if best_regime[1].get('win_rate', 0) > 0.6:
            if best_regime[0] == 'TREND':
                trend_pct += 0.05
            elif best_regime[0] == 'RANGE':
                exec_pct += 0.05

        trend_pct = max(0.15, min(self.max_single_pct, trend_pct))
        exec_pct = max(0.10, min(0.40, exec_pct))
        reserve_pct = max(self.min_reserve_pct, 1.0 - trend_pct - exec_pct)

        total = trend_pct + exec_pct + reserve_pct
        if total > 1.0:
            excess = total - 1.0
            reserve_pct -= excess

        return CapitalAllocation(
            trend_pct=round(trend_pct, 2),
            execution_pct=round(exec_pct, 2),
            reserve_pct=round(reserve_pct, 2),
            reason=reason
        )

    def calculate_kelly_fraction(self, win_rate: float, avg_win: float,
                                  avg_loss: float, fraction: float = 0.5) -> float:
        if avg_loss == 0 or win_rate <= 0:
            return 0.0

        b = avg_win / avg_loss
        kelly = (win_rate * b - (1 - win_rate)) / b

        return max(0, min(0.25, kelly * fraction))

    def calculate_position_size_kelly(self, returns: List[float], price: float) -> float:
        if len(returns) < 10:
            return self.total_capital * 0.02 / price

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        if not wins or not losses:
            return self.total_capital * 0.02 / price

        win_rate = len(wins) / len(returns)
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))

        kelly = self.calculate_kelly_fraction(win_rate, avg_win, avg_loss, 0.5)

        position_value = self.total_capital * kelly
        return round(position_value / price, 3)

    def _calculate_metrics(self, returns: List[float]) -> GrowthMetrics:
        if not returns:
            return GrowthMetrics(0, 0, 0, 0, 0, 0, 0, 0)

        mean_ret = sum(returns) / len(returns)

        variance = sum((r - mean_ret) ** 2 for r in returns) / max(len(returns) - 1, 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.001

        sharpe = (mean_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0

        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
            downside_std = math.sqrt(downside_var)
            sortino = (mean_ret / downside_std) * math.sqrt(252) if downside_std > 0 else 0
        else:
            sortino = sharpe * 2

        cumulative = 0
        peak = 0
        max_dd = 0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        calmar = (mean_ret * 252) / max_dd if max_dd > 0 else 0

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        win_rate = len(wins) / len(returns) if returns else 0

        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0.001
        profit_factor = total_wins / total_losses

        expectancy = mean_ret

        return GrowthMetrics(
            sharpe=round(sharpe, 2),
            sortino=round(sortino, 2),
            calmar=round(calmar, 2),
            max_drawdown=round(max_dd, 4),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 2),
            avg_trade_pnl=round(mean_ret, 6),
            expectancy=round(expectancy, 6)
        )

    def get_growth_report(self, returns: List[float]) -> Dict[str, Any]:
        metrics = self._calculate_metrics(returns)

        annual_return = metrics.avg_trade_pnl * 252
        monthly_return = annual_return / 12

        return {
            'sharpe': metrics.sharpe,
            'sortino': metrics.sortino,
            'calmar': metrics.calmar,
            'max_drawdown': metrics.max_drawdown,
            'win_rate': metrics.win_rate,
            'profit_factor': metrics.profit_factor,
            'annual_return': round(annual_return, 4),
            'monthly_return': round(monthly_return, 4),
            'expectancy': metrics.expectancy,
        }