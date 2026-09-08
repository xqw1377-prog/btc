from typing import Dict, Any, Optional
from .kernel_types import Intent, RiskLevel, TradeIntent, PositionState
from .risk_kernel import InstitutionalRiskKernel, RiskLimits
from .risk_semantics import (
    DEFAULT_RISK_BUDGET_PCT,
    clamp_sl_tp,
    size_pct_from_risk_budget,
    VOL_ATR_HIGH,
    VOL_ATR_MID,
)


class RiskGate:
    def __init__(self, total_capital: float, limits: Optional[RiskLimits] = None):
        self.kernel = InstitutionalRiskKernel(total_capital, limits)
        self.risk_budget_pct = DEFAULT_RISK_BUDGET_PCT
        self.funding_incomplete = False

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

    def approve(
        self,
        intent: TradeIntent,
        position: PositionState,
        vol_atr_pct: float,
        regime: str,
        confidence: float,
        funding_rate: float = 0.0,
        spread_pct: float = 0.001,
        current_ts: float = 0,
        objective_mult: float = 1.0,
        regime_weight: float = 1.0,
        signal_size_pct: float = 0.0,
    ) -> TradeIntent:
        """Final authority for OPEN sizing and SL/TP. Brain proposals are inputs only."""

        if intent.action == "HOLD":
            return intent

        if intent.action == "OPEN":
            if position.is_open:
                intent.action = "HOLD"
                intent.reason = "Already in position"
                return intent

            if self.funding_incomplete:
                intent.action = "HOLD"
                intent.risk_level = RiskLevel.BLOCKED
                intent.reason = "Funding ledger incomplete; OPEN denied"
                return intent

            try:
                base_size = signal_size_pct if signal_size_pct > 0 else intent.size_pct
                base_size *= max(0.0, objective_mult) * max(0.0, regime_weight)

                assessment = self.kernel.assess(
                    position_pct=base_size,
                    volatility=vol_atr_pct,
                    regime=regime,
                    confidence=confidence,
                    funding_rate=funding_rate,
                    spread_pct=spread_pct,
                    current_ts=current_ts,
                )

                if not assessment.approved:
                    intent.action = "HOLD"
                    intent.risk_level = RiskLevel.BLOCKED
                    intent.reason = f"Risk blocked: {'; '.join(assessment.reasons[:2])}"
                    return intent

                stop_loss_pct, take_profit_pct = clamp_sl_tp(
                    intent.stop_loss_pct,
                    intent.take_profit_pct,
                    assessment.stop_loss_pct,
                    assessment.take_profit_pct,
                )

                if stop_loss_pct <= 0:
                    intent.action = "HOLD"
                    intent.risk_level = RiskLevel.BLOCKED
                    intent.reason = "Stop distance unknown or zero; OPEN denied"
                    return intent

                risk_size = size_pct_from_risk_budget(
                    self.kernel.total_capital,
                    stop_loss_pct,
                    self.risk_budget_pct,
                    assessment.max_position_pct,
                )
                final_size = min(risk_size, base_size, assessment.max_position_pct)
                final_size = max(0.0, final_size)

                if final_size <= 0:
                    intent.action = "HOLD"
                    intent.risk_level = RiskLevel.BLOCKED
                    intent.reason = "Risk-budget sizing zero"
                    return intent

                intent.size_pct = round(final_size, 6)
                intent.stop_loss_pct = stop_loss_pct
                intent.take_profit_pct = take_profit_pct
                intent.risk_level = assessment.risk_level
                if vol_atr_pct >= VOL_ATR_HIGH:
                    intent.risk_level = RiskLevel.HIGH
                elif vol_atr_pct >= VOL_ATR_MID and intent.risk_level == RiskLevel.LOW:
                    intent.risk_level = RiskLevel.MID
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
            # funding_incomplete does not block risk reduction / exit.

        return intent

    def get_state(self) -> Dict[str, Any]:
        state = self.kernel.get_full_report()
        state["risk_budget_pct"] = self.risk_budget_pct
        state["funding_incomplete"] = self.funding_incomplete
        return state

    def save(self, filepath: str = "risk_state.json"):
        self.kernel.save_state(filepath)

    def load(self, filepath: str = "risk_state.json"):
        self.kernel.load_state(filepath)
