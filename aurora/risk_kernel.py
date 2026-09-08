from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import math
import json
import os

class RiskLevel(Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    BLOCKED = "BLOCKED"

class CircuitBreakerType(Enum):
    DRAWDOWN = "drawdown"
    DAILY_LOSS = "daily_loss"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    VOLATILITY_SPIKE = "volatility_spike"
    VAR_BREACH = "var_breach"
    FUNDING_RATE = "funding_rate"
    LIQUIDITY = "liquidity"
    API_ERROR = "api_error"

@dataclass
class RiskLimits:
    max_drawdown_pct: float = 0.08
    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.06
    max_position_pct: float = 0.40
    max_leverage: float = 3.0
    max_consecutive_losses: int = 4
    min_trade_interval_sec: int = 120
    var_confidence: float = 0.95
    var_max_pct: float = 0.05
    cvar_max_pct: float = 0.07
    max_volatility_multiple: float = 3.0
    max_funding_rate_pct: float = 0.001
    min_liquidity_usd: float = 100000.0
    max_spread_pct: float = 0.002
    max_correlation: float = 0.8
    max_exposure_pct: float = 0.50

@dataclass
class RiskMetrics:
    drawdown: float = 0.0
    daily_loss_pct: float = 0.0
    weekly_loss_pct: float = 0.0
    consecutive_losses: int = 0
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    current_exposure_pct: float = 0.0
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW

@dataclass
class CircuitBreaker:
    type: CircuitBreakerType
    threshold: float
    current_value: float
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    cooldown_sec: int = 3600

    def check(self, value: float) -> bool:
        if self.triggered:
            if self.triggered_at and (datetime.now() - self.triggered_at).total_seconds() > self.cooldown_sec:
                self.triggered = False
                self.triggered_at = None
            else:
                return True

        if value >= self.threshold:
            self.triggered = True
            self.triggered_at = datetime.now()
            return True
        return False

@dataclass
class StressScenario:
    name: str
    description: str
    price_shock_pct: float
    volatility_mult: float
    liquidity_mult: float
    funding_rate: float = 0.0

    def apply(self, capital: float, position_value: float, side: str) -> float:
        if side == "LONG":
            loss = position_value * self.price_shock_pct
        else:
            loss = position_value * (-self.price_shock_pct)
        return loss

@dataclass
class RiskAssessment:
    approved: bool
    risk_level: RiskLevel
    risk_score: float
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    reasons: List[str]
    metrics: RiskMetrics
    circuit_breakers: Dict[str, bool]
    stress_results: Dict[str, float]

class InstitutionalRiskKernel:
    def __init__(self, total_capital: float, limits: Optional[RiskLimits] = None):
        self.total_capital = total_capital
        self.peak_capital = total_capital
        self.limits = limits or RiskLimits()

        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.consecutive_losses = 0
        self.last_trade_ts = 0.0
        self.trade_count_today = 0
        self.trade_count_week = 0

        self.returns_history: List[float] = []
        self.pnl_history: List[float] = []
        self.equity_curve: List[float] = [total_capital]
        self.volatility_history: List[float] = []

        self.circuit_breakers = {
            CircuitBreakerType.DRAWDOWN: CircuitBreaker(
                CircuitBreakerType.DRAWDOWN, self.limits.max_drawdown_pct, 0, cooldown_sec=7200
            ),
            CircuitBreakerType.DAILY_LOSS: CircuitBreaker(
                CircuitBreakerType.DAILY_LOSS, self.limits.max_daily_loss_pct, 0, cooldown_sec=86400
            ),
            CircuitBreakerType.CONSECUTIVE_LOSSES: CircuitBreaker(
                CircuitBreakerType.CONSECUTIVE_LOSSES, self.limits.max_consecutive_losses, 0, cooldown_sec=3600
            ),
            CircuitBreakerType.VOLATILITY_SPIKE: CircuitBreaker(
                CircuitBreakerType.VOLATILITY_SPIKE, self.limits.max_volatility_multiple, 0, cooldown_sec=1800
            ),
            CircuitBreakerType.VAR_BREACH: CircuitBreaker(
                CircuitBreakerType.VAR_BREACH, self.limits.var_max_pct, 0, cooldown_sec=3600
            ),
            CircuitBreakerType.FUNDING_RATE: CircuitBreaker(
                CircuitBreakerType.FUNDING_RATE, self.limits.max_funding_rate_pct, 0, cooldown_sec=3600
            ),
        }

        self.stress_scenarios = {
            "flash_crash": StressScenario("Flash Crash", "BTC -10% in minutes", -0.10, 3.0, 0.3),
            "major_crash": StressScenario("Major Crash", "BTC -20% over hours", -0.20, 2.5, 0.5),
            "liquidity_crisis": StressScenario("Liquidity Crisis", "Spread widens 5x", -0.05, 2.0, 0.1),
            "volatility_spike": StressScenario("Volatility Spike", "ATR doubles", -0.03, 2.0, 0.7),
            "funding_crisis": StressScenario("Funding Crisis", "Extreme funding rates", -0.02, 1.5, 0.8, 0.003),
            "black_swan": StressScenario("Black Swan", "BTC -30% in 1 hour", -0.30, 5.0, 0.05),
        }

        self.kill_switch = False
        self.kill_reason = ""
        self.alerts: List[Dict[str, Any]] = []

    def update_capital(self, new_capital: float):
        self.total_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital
        self.equity_curve.append(new_capital)
        if len(self.equity_curve) > 252:
            self.equity_curve = self.equity_curve[-252:]

    def record_trade(self, pnl: float, timestamp: Optional[float] = None):
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.pnl_history.append(pnl)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.total_capital > 0:
            ret = pnl / self.total_capital
            self.returns_history.append(ret)
            if len(self.returns_history) > 252:
                self.returns_history = self.returns_history[-252:]

        self.trade_count_today += 1
        self.trade_count_week += 1

        if timestamp:
            self.last_trade_ts = timestamp

        self._check_all_breakers(pnl)

    def assess(self, position_pct: float, volatility: float, regime: str,
               confidence: float, funding_rate: float = 0.0,
               spread_pct: float = 0.001, current_ts: float = 0) -> RiskAssessment:

        if self.kill_switch:
            return RiskAssessment(
                approved=False, risk_level=RiskLevel.BLOCKED, risk_score=1.0,
                max_position_pct=0, stop_loss_pct=0, take_profit_pct=0,
                reasons=[f"Kill switch: {self.kill_reason}"],
                metrics=self._compute_metrics(volatility),
                circuit_breakers=self._breaker_status(),
                stress_results={}
            )

        metrics = self._compute_metrics(volatility)

        reasons = []
        risk_score = self._compute_risk_score(metrics, position_pct, volatility, funding_rate, spread_pct)

        if metrics.drawdown >= self.limits.max_drawdown_pct:
            reasons.append(f"DD {metrics.drawdown:.2%} >= {self.limits.max_drawdown_pct:.2%}")

        if metrics.daily_loss_pct >= self.limits.max_daily_loss_pct:
            reasons.append(f"Daily loss {metrics.daily_loss_pct:.2%} >= {self.limits.max_daily_loss_pct:.2%}")

        if self.consecutive_losses >= self.limits.max_consecutive_losses:
            reasons.append(f"Consec losses {self.consecutive_losses} >= {self.limits.max_consecutive_losses}")

        if position_pct > self.limits.max_position_pct:
            reasons.append(f"Position {position_pct:.2%} > max {self.limits.max_position_pct:.2%}")

        if metrics.var_95 > self.limits.var_max_pct:
            reasons.append(f"VaR95 {metrics.var_95:.2%} > {self.limits.var_max_pct:.2%}")

        if metrics.cvar_95 > self.limits.cvar_max_pct:
            reasons.append(f"CVaR95 {metrics.cvar_95:.2%} > {self.limits.cvar_max_pct:.2%}")

        if funding_rate > self.limits.max_funding_rate_pct:
            reasons.append(f"Funding {funding_rate:.4%} > {self.limits.max_funding_rate_pct:.4%}")

        if spread_pct > self.limits.max_spread_pct:
            reasons.append(f"Spread {spread_pct:.4%} > {self.limits.max_spread_pct:.4%}")

        if current_ts > 0 and current_ts - self.last_trade_ts < self.limits.min_trade_interval_sec:
            reasons.append("Trade interval not met")

        stress_results = self._run_stress_tests(position_pct, volatility)

        max_stress_loss = max(stress_results.values()) if stress_results else 0
        if max_stress_loss > 0.15:
            reasons.append(f"Stress test worst case {max_stress_loss:.1%}")

        approved = len(reasons) == 0 and risk_score < 0.75

        risk_level = self._classify_risk(risk_score)

        max_pos = self._calculate_max_position(risk_score, volatility, confidence)
        sl_pct = self._calculate_stop_loss(volatility, regime)
        tp_pct = self._calculate_take_profit(volatility, regime, confidence)

        return RiskAssessment(
            approved=approved,
            risk_level=risk_level,
            risk_score=round(risk_score, 4),
            max_position_pct=round(max_pos, 4),
            stop_loss_pct=round(sl_pct, 4),
            take_profit_pct=round(tp_pct, 4),
            reasons=reasons,
            metrics=metrics,
            circuit_breakers=self._breaker_status(),
            stress_results=stress_results
        )

    def _compute_metrics(self, volatility: float) -> RiskMetrics:
        try:
            dd = self._drawdown()
            daily_loss = abs(min(0, self.daily_pnl)) / self.total_capital if self.total_capital > 0 else 0
            weekly_loss = abs(min(0, self.weekly_pnl)) / self.total_capital if self.total_capital > 0 else 0

            var95 = self._var(0.95)
            var99 = self._var(0.99)
            cvar95 = self._cvar(0.95)
            sharpe = self._sharpe()
            sortino = self._sortino()
            calmar = self._calmar()
            skew = self._skewness()
            kurt = self._kurtosis()

            risk_score = self._compute_risk_score_raw(dd, daily_loss, self.consecutive_losses, var95, volatility)

            return RiskMetrics(
                drawdown=round(dd, 4),
                daily_loss_pct=round(daily_loss, 4),
                weekly_loss_pct=round(weekly_loss, 4),
                consecutive_losses=self.consecutive_losses,
                var_95=round(var95, 4),
                var_99=round(var99, 4),
                cvar_95=round(cvar95, 4),
                sharpe=round(sharpe, 2),
                sortino=round(sortino, 2),
                calmar=round(calmar, 2),
                max_drawdown=round(self._max_drawdown(), 4),
                volatility=round(volatility, 4),
                skewness=round(skew, 2),
                kurtosis=round(kurt, 2),
                risk_score=round(risk_score, 4),
                risk_level=self._classify_risk(risk_score)
            )
        except Exception:
            return RiskMetrics()

    def _drawdown(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return max(0, (self.peak_capital - self.total_capital) / self.peak_capital)

    def _max_drawdown(self) -> float:
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

    def _var(self, confidence: float) -> float:
        if len(self.returns_history) < 5:
            return 0.0
        sorted_ret = sorted(self.returns_history)
        idx = int(len(sorted_ret) * (1 - confidence))
        return abs(sorted_ret[max(0, idx)])

    def _cvar(self, confidence: float) -> float:
        if len(self.returns_history) < 10:
            return 0.0
        sorted_ret = sorted(self.returns_history)
        cutoff = int(len(sorted_ret) * (1 - confidence))
        if cutoff == 0:
            return abs(sorted_ret[0])
        tail = sorted_ret[:cutoff]
        return abs(sum(tail) / len(tail))

    def _sharpe(self, risk_free: float = 0.02) -> float:
        if len(self.returns_history) < 5:
            return 0.0
        mean = sum(self.returns_history) / len(self.returns_history)
        var = sum((r - mean) ** 2 for r in self.returns_history) / max(len(self.returns_history) - 1, 1)
        std = math.sqrt(var) if var > 0 else 0.001
        return (mean * 252 - risk_free) / (std * math.sqrt(252))

    def _sortino(self, risk_free: float = 0.02) -> float:
        if len(self.returns_history) < 5:
            return 0.0
        mean = sum(self.returns_history) / len(self.returns_history)
        downside = [r for r in self.returns_history if r < 0]
        if not downside:
            return self._sharpe(risk_free) * 2
        down_var = sum(r ** 2 for r in downside) / len(downside)
        down_std = math.sqrt(down_var)
        return (mean * 252 - risk_free) / (down_std * math.sqrt(252))

    def _calmar(self) -> float:
        if len(self.returns_history) < 10:
            return 0.0
        annual_ret = sum(self.returns_history) / len(self.returns_history) * 252
        max_dd = self._max_drawdown()
        return annual_ret / max_dd if max_dd > 0 else 0.0

    def _skewness(self) -> float:
        if len(self.returns_history) < 10:
            return 0.0
        n = len(self.returns_history)
        mean = sum(self.returns_history) / n
        var = sum((r - mean) ** 2 for r in self.returns_history) / n
        std = math.sqrt(var) if var > 0 else 0.001
        skew = sum(((r - mean) / std) ** 3 for r in self.returns_history) / n
        return skew

    def _kurtosis(self) -> float:
        if len(self.returns_history) < 10:
            return 0.0
        n = len(self.returns_history)
        mean = sum(self.returns_history) / n
        var = sum((r - mean) ** 2 for r in self.returns_history) / n
        std = math.sqrt(var) if var > 0 else 0.001
        kurt = sum(((r - mean) / std) ** 4 for r in self.returns_history) / n - 3
        return kurt

    def _compute_risk_score(self, metrics: RiskMetrics, position_pct: float,
                            volatility: float, funding_rate: float, spread_pct: float) -> float:
        scores = [
            self._score_limit(metrics.drawdown, self.limits.max_drawdown_pct) * 0.20,
            self._score_limit(metrics.daily_loss_pct, self.limits.max_daily_loss_pct) * 0.15,
            self._score_limit(self.consecutive_losses, self.limits.max_consecutive_losses) * 0.10,
            self._score_limit(metrics.var_95, self.limits.var_max_pct) * 0.15,
            self._score_limit(metrics.cvar_95, self.limits.cvar_max_pct) * 0.10,
            self._score_limit(volatility, 0.03) * 0.10,
            self._score_limit(position_pct, self.limits.max_position_pct) * 0.10,
            self._score_limit(funding_rate, self.limits.max_funding_rate_pct) * 0.05,
            self._score_limit(spread_pct, self.limits.max_spread_pct) * 0.05,
        ]
        return min(sum(scores), 1.0)

    def _compute_risk_score_raw(self, dd: float, daily_loss: float,
                                consec: int, var: float, vol: float) -> float:
        scores = [
            self._score_limit(dd, self.limits.max_drawdown_pct) * 0.25,
            self._score_limit(daily_loss, self.limits.max_daily_loss_pct) * 0.20,
            self._score_limit(consec, self.limits.max_consecutive_losses) * 0.15,
            self._score_limit(var, self.limits.var_max_pct) * 0.20,
            self._score_limit(vol, 0.03) * 0.20,
        ]
        return min(sum(scores), 1.0)

    def _score_limit(self, value: float, limit: float) -> float:
        if limit <= 0:
            return 0.0
        return min(value / limit, 1.0)

    def _classify_risk(self, score: float) -> RiskLevel:
        if score >= 0.8:
            return RiskLevel.CRITICAL
        if score >= 0.6:
            return RiskLevel.HIGH
        if score >= 0.3:
            return RiskLevel.MID
        return RiskLevel.LOW

    def _calculate_max_position(self, risk_score: float, volatility: float, confidence: float) -> float:
        base = self.limits.max_position_pct
        risk_adj = max(0.2, 1.0 - risk_score * 0.6)
        vol_adj = 1.0 / (1.0 + volatility * 50)
        conf_adj = 0.5 + confidence * 0.5
        consec_adj = max(0.3, 1.0 - self.consecutive_losses * 0.15)
        return base * risk_adj * vol_adj * conf_adj * consec_adj

    def _calculate_stop_loss(self, volatility: float, regime: str) -> float:
        base = {"TREND": 0.02, "RANGE": 0.01, "TRANSITION": 0.015}.get(regime, 0.015)
        vol_adj = 1.0 + volatility * 2
        consec_adj = max(0.7, 1.0 - self.consecutive_losses * 0.05)
        return base * vol_adj * consec_adj

    def _calculate_take_profit(self, volatility: float, regime: str, confidence: float) -> float:
        base = {"TREND": 0.04, "RANGE": 0.015, "TRANSITION": 0.025}.get(regime, 0.025)
        vol_adj = 1.0 + volatility * 2
        conf_adj = 0.8 + confidence * 0.4
        return base * vol_adj * conf_adj

    def _run_stress_tests(self, position_pct: float, volatility: float) -> Dict[str, float]:
        position_value = self.total_capital * position_pct
        results = {}
        for name, scenario in self.stress_scenarios.items():
            loss = abs(scenario.apply(self.total_capital, position_value, "LONG"))
            results[name] = round(loss / self.total_capital, 4)
        return results

    def _check_all_breakers(self, last_pnl: float):
        try:
            dd = self._drawdown()
            self.circuit_breakers[CircuitBreakerType.DRAWDOWN].current_value = dd
            if self.circuit_breakers[CircuitBreakerType.DRAWDOWN].check(dd):
                self._activate_kill(f"Drawdown {dd:.2%}")

            daily_loss = abs(min(0, self.daily_pnl)) / self.total_capital if self.total_capital > 0 else 0
            self.circuit_breakers[CircuitBreakerType.DAILY_LOSS].current_value = daily_loss
            if self.circuit_breakers[CircuitBreakerType.DAILY_LOSS].check(daily_loss):
                self._activate_kill(f"Daily loss {daily_loss:.2%}")

            self.circuit_breakers[CircuitBreakerType.CONSECUTIVE_LOSSES].current_value = self.consecutive_losses
            if self.circuit_breakers[CircuitBreakerType.CONSECUTIVE_LOSSES].check(self.consecutive_losses):
                self._activate_kill(f"Consecutive losses {self.consecutive_losses}")

            var = self._var(0.95)
            self.circuit_breakers[CircuitBreakerType.VAR_BREACH].current_value = var
            if self.circuit_breakers[CircuitBreakerType.VAR_BREACH].check(var):
                self._activate_kill(f"VaR breach {var:.2%}")
        except Exception as e:
            pass

    def _activate_kill(self, reason: str):
        self.kill_switch = True
        self.kill_reason = reason
        self.alerts.append({
            'type': 'KILL_SWITCH',
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'capital': self.total_capital,
            'drawdown': self._drawdown()
        })
        print(f"\n🚨 KILL SWITCH: {reason}")

    def _breaker_status(self) -> Dict[str, bool]:
        return {bt.value: cb.triggered for bt, cb in self.circuit_breakers.items()}

    def reset_kill(self, reason: str = "manual"):
        self.kill_switch = False
        self.kill_reason = ""
        for cb in self.circuit_breakers.values():
            cb.triggered = False
            cb.triggered_at = None
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.alerts.append({
            'type': 'KILL_RESET',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.trade_count_today = 0

    def reset_weekly(self):
        self.weekly_pnl = 0.0
        self.trade_count_week = 0

    def get_full_report(self) -> Dict[str, Any]:
        metrics = self._compute_metrics(
            self.volatility_history[-1] if self.volatility_history else 0.01
        )
        stress = self._run_stress_tests(0.10, 0.02)

        return {
            'capital': self.total_capital,
            'peak': self.peak_capital,
            'metrics': {
                'drawdown': metrics.drawdown,
                'max_drawdown': metrics.max_drawdown,
                'daily_loss': metrics.daily_loss_pct,
                'weekly_loss': metrics.weekly_loss_pct,
                'consecutive_losses': self.consecutive_losses,
                'var_95': metrics.var_95,
                'var_99': metrics.var_99,
                'cvar_95': metrics.cvar_95,
                'sharpe': metrics.sharpe,
                'sortino': metrics.sortino,
                'calmar': metrics.calmar,
                'skewness': metrics.skewness,
                'kurtosis': metrics.kurtosis,
                'risk_score': metrics.risk_score,
                'risk_level': metrics.risk_level.value,
            },
            'circuit_breakers': self._breaker_status(),
            'kill_switch': self.kill_switch,
            'kill_reason': self.kill_reason,
            'stress_test': stress,
            'worst_stress': max(stress.values()) if stress else 0,
            'trades_today': self.trade_count_today,
            'trades_week': self.trade_count_week,
            'alerts': self.alerts[-10:],
        }

    def save_state(self, filepath: str = "risk_state.json"):
        try:
            state = {
                'capital': self.total_capital,
                'peak': self.peak_capital,
                'daily_pnl': self.daily_pnl,
                'weekly_pnl': self.weekly_pnl,
                'consecutive_losses': self.consecutive_losses,
                'returns_history': self.returns_history[-100:],
                'equity_curve': self.equity_curve[-100:],
                'kill_switch': self.kill_switch,
                'kill_reason': self.kill_reason,
                'saved_at': datetime.now().isoformat(),
            }
            with open(filepath, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def load_state(self, filepath: str = "risk_state.json"):
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    state = json.load(f)
                    self.total_capital = state.get('capital', self.total_capital)
                    self.peak_capital = state.get('peak', self.peak_capital)
                    self.daily_pnl = state.get('daily_pnl', 0)
                    self.weekly_pnl = state.get('weekly_pnl', 0)
                    self.consecutive_losses = state.get('consecutive_losses', 0)
                    self.returns_history = state.get('returns_history', [])
                    self.equity_curve = state.get('equity_curve', [self.total_capital])
                    self.kill_switch = state.get('kill_switch', False)
                    self.kill_reason = state.get('kill_reason', '')
        except Exception:
            pass