from typing import Dict, Any, List
from .kernel_types import (
    Signal, Intent, TradeIntent, RiskLevel, PositionManager,
    ThresholdState, valid_threshold,
)
from .risk_gate import RiskGate
from .capital_objective import CapitalObjectiveLayer
from .regime_memory import RegimeMemoryModel
from .signal_orthogonalizer import SignalOrthogonalizer

class PortfolioBrainV2:
    def __init__(self, total_capital: float):
        self.position_mgr = PositionManager()
        self.risk_gate = RiskGate(total_capital)
        self.capital = total_capital

        self.capital_objective = CapitalObjectiveLayer(total_capital)
        self.regime_memory = RegimeMemoryModel(confirmation_count=3)
        self.orthogonalizer = SignalOrthogonalizer()

        self.regime_weights = {
            "TREND":      {"trend": 0.50, "breakout": 0.25, "momentum": 0.15, "mr": 0.10},
            "RANGE":      {"mr": 0.50, "momentum": 0.20, "trend": 0.15, "breakout": 0.15},
            "TRANSITION": {"breakout": 0.35, "trend": 0.30, "momentum": 0.20, "mr": 0.15},
        }

        self.thresholds = {
            'enter': 0.25,
            'exit': 0.10,
            'min_confidence': 0.30,
        }

    def process(self, signals: List[Signal], regime: str, confidence: float,
                volatility: float, price: float, atr: float, current_ts: float,
                features: Dict[str, Any] = None, bar_id=None) -> TradeIntent:

        self.position_mgr.update_price(price)

        regime_state = self.regime_memory.update(
            regime, confidence, features or {}, bar_id=bar_id)
        effective_regime = regime_state['regime']
        effective_confidence = regime_state['confidence']

        if not self.capital_objective.should_trade():
            return TradeIntent(
                action="HOLD", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=0, risk_level=RiskLevel.HIGH,
                reason="Capital objective blocked"
            )

        orthogonal_signals = self.orthogonalizer.orthogonalize(signals)

        if self.position_mgr.position.is_open:
            intent = self._manage_position(orthogonal_signals, effective_regime, price, atr, effective_confidence)
        else:
            if not regime_state['is_stable']:
                return TradeIntent(
                    action="HOLD", side=Intent.FLAT, size_pct=0,
                    stop_loss_pct=0, take_profit_pct=0,
                    confidence=0, risk_level=RiskLevel.LOW,
                    reason=f"Regime not stable ({regime_state['duration']}/{self.regime_memory.confirmation_count})"
                )
            intent = self._evaluate_entry(orthogonal_signals, effective_regime, effective_confidence, volatility, price, atr)

        intent = self.risk_gate.approve(
            intent, self.position_mgr.position,
            volatility=volatility, regime=effective_regime, confidence=effective_confidence,
            current_ts=current_ts
        )

        if intent.action == "OPEN":
            objective_mult = self.capital_objective.get_position_multiplier()
            regime_weight = self.regime_memory.get_regime_weight()
            intent.size_pct *= objective_mult * regime_weight
            intent.size_pct = max(0.02, min(0.35, intent.size_pct))

        return intent

    def _evaluate_entry(self, signals: List[Signal], regime: str,
                        confidence: float, volatility: float,
                        price: float, atr: float) -> TradeIntent:

        weights = self.regime_weights.get(regime, self.regime_weights["TRANSITION"])

        scored = {}
        active_signals = []
        for sig in signals:
            if sig.direction == Intent.FLAT:
                continue
            w = weights.get(sig.source, 0.0)
            dir_val = 1 if sig.direction == Intent.LONG else -1
            scored[sig.source] = dir_val * sig.confidence * w
            active_signals.append(sig)

        if not active_signals:
            return TradeIntent(
                action="HOLD", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=0, risk_level=RiskLevel.LOW,
                reason="No active signals"
            )

        net_score = sum(scored.values())
        avg_conf = sum(s.confidence for s in active_signals) / len(active_signals)

        direction_votes = {'LONG': 0, 'SHORT': 0}
        for sig in active_signals:
            if sig.direction == Intent.LONG:
                direction_votes['LONG'] += sig.confidence * weights.get(sig.source, 0)
            elif sig.direction == Intent.SHORT:
                direction_votes['SHORT'] += sig.confidence * weights.get(sig.source, 0)

        total_vote = direction_votes['LONG'] + direction_votes['SHORT']
        if total_vote == 0:
            agreement = 0.0
        else:
            agreement = max(direction_votes['LONG'], direction_votes['SHORT']) / total_vote

        if abs(net_score) < self.thresholds['enter'] or avg_conf < self.thresholds['min_confidence']:
            return TradeIntent(
                action="HOLD", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=avg_conf, risk_level=RiskLevel.LOW,
                reason=f"Score {net_score:.3f} below threshold"
            )

        side = Intent.LONG if net_score > 0 else Intent.SHORT

        vol_adj = 1.0 / (1.0 + volatility * 3)
        size_pct = min(abs(net_score) * vol_adj * agreement, 0.40)
        size_pct = max(size_pct, 0.03)

        if regime == "TREND":
            sl_mult = 2.0
            tp_mult = 3.0
        elif regime == "RANGE":
            sl_mult = 1.0
            tp_mult = 1.5
        else:
            sl_mult = 1.5
            tp_mult = 2.0

        sl_pct = (atr * sl_mult) / price if price > 0 else 0.02
        tp_pct = (atr * tp_mult) / price if price > 0 else 0.04

        risk_level = RiskLevel.LOW
        if volatility > 0.04:
            risk_level = RiskLevel.HIGH
        elif volatility > 0.025:
            risk_level = RiskLevel.MID

        return TradeIntent(
            action="OPEN",
            side=side,
            size_pct=size_pct,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            confidence=avg_conf * agreement,
            risk_level=risk_level,
            reason=f"Score={net_score:.3f} Agree={agreement:.2f} Regime={regime}",
            signals=active_signals
        )

    def _manage_position(self, signals: List[Signal], regime: str,
                         price: float, atr: float, confidence: float) -> TradeIntent:

        pos = self.position_mgr.position

        if self.position_mgr.should_stop_loss(price):
            return TradeIntent(
                action="CLOSE", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=1.0, risk_level=RiskLevel.HIGH,
                reason=f"Stop loss hit @ ${price:,.2f}"
            )

        if self.position_mgr.should_take_profit(price):
            return TradeIntent(
                action="CLOSE", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=1.0, risk_level=RiskLevel.LOW,
                reason=f"Take profit hit @ ${price:,.2f}"
            )

        opposing = 0
        supporting = 0
        for sig in signals:
            if sig.direction == Intent.FLAT:
                continue
            if pos.side.value == "LONG":
                if sig.direction == Intent.SHORT:
                    opposing += sig.confidence
                elif sig.direction == Intent.LONG:
                    supporting += sig.confidence
            else:
                if sig.direction == Intent.LONG:
                    opposing += sig.confidence
                elif sig.direction == Intent.SHORT:
                    supporting += sig.confidence

        total = opposing + supporting
        if total > 0 and opposing / total > 0.7:
            return TradeIntent(
                action="CLOSE", side=Intent.FLAT, size_pct=0,
                stop_loss_pct=0, take_profit_pct=0,
                confidence=opposing / total,
                risk_level=RiskLevel.MID,
                reason=f"Signal reversal ({opposing:.2f} vs {supporting:.2f})"
            )

        pnl_pct = pos.unrealized_pnl / (pos.entry_price * pos.size) if pos.entry_price * pos.size > 0 else 0

        if pnl_pct > 0.01:
            new_sl = pos.entry_price * (1.005 if pos.side.value == "LONG" else 0.995)
            # trailing 只能更新 STRATEGY 来源的本地候选阈值；
            # 不得把本地移动值当成交易所已确认保护，也不得覆盖 UNKNOWN。
            if (
                pos.stop_loss_state == ThresholdState.VALID
                and pos.stop_loss_source == "STRATEGY"
                and valid_threshold(pos.stop_loss)
                and (
                    (pos.side.value == "LONG" and new_sl > pos.stop_loss)
                    or (pos.side.value == "SHORT" and new_sl < pos.stop_loss)
                )
            ):
                self.position_mgr._position.stop_loss = new_sl

        return TradeIntent(
            action="HOLD", side=Intent.FLAT, size_pct=0,
            stop_loss_pct=0, take_profit_pct=0,
            confidence=supporting / max(total, 1),
            risk_level=RiskLevel.LOW,
            reason="Position maintained"
        )

    def execute_intent(self, intent: TradeIntent, price: float, pnl: float = 0):
        if intent.action == "OPEN":
            size_btc = (self.capital * intent.size_pct) / price if price > 0 else 0
            sl_price = (
                (price * (1 - intent.stop_loss_pct)) if intent.side == Intent.LONG
                else (price * (1 + intent.stop_loss_pct))
            ) if intent.stop_loss_pct > 0 else None
            tp_price = (
                (price * (1 + intent.take_profit_pct)) if intent.side == Intent.LONG
                else (price * (1 - intent.take_profit_pct))
            ) if intent.take_profit_pct > 0 else None

            self.position_mgr.open(
                side=intent.side,
                size=size_btc,
                price=price,
                stop_loss=sl_price,
                take_profit=tp_price,
                reason=intent.reason,
                stop_loss_state=(
                    ThresholdState.NOT_CONFIGURED if intent.stop_loss_pct == 0
                    else None  # 非法/负值 → 保持 UNKNOWN，不悄悄当配置
                ),
                take_profit_state=(
                    ThresholdState.NOT_CONFIGURED if intent.take_profit_pct == 0
                    else None
                ),
                stop_loss_source="STRATEGY",
                protection_note="strategy-configured thresholds",
            )

        elif intent.action == "CLOSE":
            # E0：平仓 PnL 必须来自 ledger fills，不得用 bar 价格记账。
            self.position_mgr.close_without_pnl(intent.reason)

        return 0.0

    def close_position_from_accounting(self, reason: str) -> None:
        """交易所/内核已平仓后，只更新本地仓位视图，不记账。"""
        self.position_mgr.close_without_pnl(reason)

    def get_state(self) -> Dict[str, Any]:
        pos = self.position_mgr.position
        return {
            'position': {
                'side': pos.side.value,
                'size': pos.size,
                'entry_price': pos.entry_price,
                'unrealized_pnl': pos.unrealized_pnl,
                'stop_loss': pos.stop_loss,
                'take_profit': pos.take_profit,
                'stop_loss_state': pos.stop_loss_state.value,
                'take_profit_state': pos.take_profit_state.value,
                'protection_unknown': pos.protection_unknown,
                'protection_note': pos.protection_note,
                'is_open': pos.is_open,
            },
            'risk': self.risk_gate.get_state(),
            'capital_objective': self.capital_objective.get_state(),
            'regime_memory': {
                'regime': self.regime_memory.current.regime,
                'duration': self.regime_memory.current.duration,
                'is_stable': self.regime_memory.current.duration >= self.regime_memory.confirmation_count,
                'transitions': self.regime_memory.current.transitions,
            },
            'signal_correlation': self.orthogonalizer.get_correlation_matrix(),
            'capital': self.capital,
        }