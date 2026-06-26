from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum
from .capital_objective import CapitalObjectiveLayer
from .risk_kernel import InstitutionalRiskKernel, RiskLimits

class RiskState(Enum):
    SAFE = "SAFE"
    REDUCE = "REDUCE"
    BLOCK = "BLOCK"

class Action(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"

@dataclass
class CapitalDecision:
    action: Action
    size: float
    risk_state: RiskState
    stop_loss_pct: float
    take_profit_pct: float
    confidence: float
    reason: str

class CapitalController:
    def __init__(self, capital: float):
        self.capital = capital
        self.objective = CapitalObjectiveLayer(capital)
        self.risk = InstitutionalRiskKernel(capital)

        self.thresholds = {
            'direction': 0.30,
            'confidence': 0.50,
            'max_size': 0.35,
            'min_size': 0.02,
        }

    def decide(self, direction: float, confidence: float,
               regime: str, volatility: float, price: float, atr: float,
               current_ts: float = 0) -> CapitalDecision:

        if not self.objective.should_trade():
            return CapitalDecision(
                action=Action.FLAT, size=0, risk_state=RiskState.BLOCK,
                stop_loss_pct=0, take_profit_pct=0, confidence=0,
                reason="Objective blocked"
            )

        risk_assessment = self.risk.assess(
            position_pct=abs(direction) * 0.3,
            volatility=volatility,
            regime=regime,
            confidence=confidence,
            current_ts=current_ts
        )

        if not risk_assessment.approved:
            return CapitalDecision(
                action=Action.FLAT, size=0, risk_state=RiskState.BLOCK,
                stop_loss_pct=0, take_profit_pct=0, confidence=0,
                reason=f"Risk blocked: {risk_assessment.reasons[0] if risk_assessment.reasons else 'unknown'}"
            )

        risk_state = self._classify_risk(risk_assessment)

        if risk_state == RiskState.BLOCK:
            return CapitalDecision(
                action=Action.FLAT, size=0, risk_state=risk_state,
                stop_loss_pct=0, take_profit_pct=0, confidence=0,
                reason="Risk state BLOCK"
            )

        if regime == "TRANSITION" and confidence < 0.7:
            return CapitalDecision(
                action=Action.FLAT, size=0, risk_state=risk_state,
                stop_loss_pct=0, take_profit_pct=0, confidence=confidence,
                reason=f"TRANSITION regime too weak (conf={confidence:.2f})"
            )

        if abs(direction) < self.thresholds['direction'] or confidence < self.thresholds['confidence']:
            return CapitalDecision(
                action=Action.FLAT, size=0, risk_state=risk_state,
                stop_loss_pct=0, take_profit_pct=0, confidence=confidence,
                reason=f"Below threshold (dir={direction:.3f}, conf={confidence:.2f})"
            )

        action = Action.LONG if direction > 0 else Action.SHORT

        base_size = abs(direction) * confidence
        vol_adj = 1.0 / (1.0 + volatility * 3)
        objective_mult = self.objective.get_position_multiplier()

        size = base_size * vol_adj * objective_mult

        if risk_state == RiskState.REDUCE:
            size *= 0.5

        size = max(self.thresholds['min_size'], min(self.thresholds['max_size'], size))

        sl_pct = risk_assessment.stop_loss_pct
        tp_pct = risk_assessment.take_profit_pct

        return CapitalDecision(
            action=action,
            size=round(size, 4),
            risk_state=risk_state,
            stop_loss_pct=round(sl_pct, 4),
            take_profit_pct=round(tp_pct, 4),
            confidence=round(confidence, 4),
            reason=f"dir={direction:.3f} conf={confidence:.2f} regime={regime}"
        )

    def _classify_risk(self, assessment) -> RiskState:
        if assessment.risk_score >= 0.75:
            return RiskState.BLOCK
        elif assessment.risk_score >= 0.5:
            return RiskState.REDUCE
        return RiskState.SAFE

    def record_result(self, pnl: float):
        self.objective.record(pnl)
        self.risk.record_trade(pnl)
        self.capital += pnl
        self.risk.update_capital(self.capital)

    def get_state(self) -> Dict[str, Any]:
        return {
            'capital': self.capital,
            'objective': self.objective.get_state(),
            'risk': self.risk.get_full_report(),
        }