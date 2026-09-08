from typing import Dict, Any, Optional
from .kernel_types import Intent, RiskLevel, TradeIntent, PositionState
from .risk_kernel import InstitutionalRiskKernel, RiskLimits

class RiskGate:
    def __init__(self, total_capital: float, limits: Optional[RiskLimits] = None):
        self.kernel = InstitutionalRiskKernel(total_capital, limits)

    @property
    def capital(self):
        return self.kernel.total_capital

    @property
    def kill_switch(self):
        return self.kernel.kill_switch

    @property
    def kill_reason(self):
        return self.kernel.kill_reason

    def update_capital(self, capital: float):
        self.kernel.update_capital(capital)

    def record_result(self, pnl: float, timestamp: Optional[float] = None):
        self.kernel.record_trade(pnl, timestamp=timestamp)

    def approve(self, intent: TradeIntent, position: PositionState,
                volatility: float, regime: str, confidence: float,
                funding_rate: float = 0.0, spread_pct: float = 0.001,
                current_ts: float = 0) -> TradeIntent:

        if intent.action == "HOLD":
            return intent

        if intent.action == "OPEN":
            if position.is_open:
                intent.action = "HOLD"
                intent.reason = "Already in position"
                return intent

            try:
                assessment = self.kernel.assess(
                    position_pct=intent.size_pct,
                    volatility=volatility,
                    regime=regime,
                    confidence=confidence,
                    funding_rate=funding_rate,
                    spread_pct=spread_pct,
                    current_ts=current_ts
                )

                if not assessment.approved:
                    intent.action = "HOLD"
                    intent.risk_level = RiskLevel.BLOCKED
                    intent.reason = f"Risk blocked: {'; '.join(assessment.reasons[:2])}"
                    return intent

                intent.size_pct = min(intent.size_pct, assessment.max_position_pct)
                intent.stop_loss_pct = assessment.stop_loss_pct
                intent.take_profit_pct = assessment.take_profit_pct
                intent.risk_level = assessment.risk_level
            except Exception as e:
                intent.action = "HOLD"
                intent.risk_level = RiskLevel.BLOCKED
                intent.reason = f"Risk gate failed closed: {e}"
                return intent

        elif intent.action == "CLOSE":
            if not position.is_open:
                intent.action = "HOLD"
                intent.reason = "No position to close"
                return intent

        return intent

    def get_state(self) -> Dict[str, Any]:
        return self.kernel.get_full_report()

    def save(self, filepath: str = "risk_state.json"):
        self.kernel.save_state(filepath)

    def load(self, filepath: str = "risk_state.json"):
        self.kernel.load_state(filepath)