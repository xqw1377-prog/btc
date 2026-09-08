from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import math

@dataclass
class RegimeState:
    regime: str = "TRANSITION"
    confidence: float = 0.5
    duration: int = 0
    entry_time: Optional[datetime] = None
    transitions: int = 0

class RegimeMemoryModel:
    def __init__(self, confirmation_count: int = 3, persistence_bonus: float = 0.02):
        self.confirmation_count = confirmation_count
        self.persistence_bonus = persistence_bonus

        self.current = RegimeState(entry_time=datetime.now())
        self.pending_regime = "TRANSITION"
        self.pending_count = 0

        self.history: List[Dict[str, Any]] = []
        self.transition_penalty = 0.15
        # G0-2：duration/pending_count 只消费唯一已收盘 bar 证据。
        self._last_bar_id = None
        self.bar_anomalies: int = 0
        self.bars_consumed: int = 0  # 只在新 bar 上 +1；转移归零不影响它

    def _bar_status(self, bar_id) -> str:
        """bar_id = (symbol, interval, open_time)。同一 bar 永不二次消费。"""
        if bar_id is None:
            return "NO_VALID_CLOSED_BAR"
        last = self._last_bar_id
        if last is not None:
            if bar_id == last:
                return "SAME_CLOSED_BAR"
            if tuple(bar_id[:2]) != tuple(last[:2]):
                # symbol/interval 改变：证据流断裂，不串联旧确认
                self.pending_count = 0
                self.current.duration = 0
                self._last_bar_id = bar_id
                return "NEW_CLOSED_BAR"
            if bar_id[2] <= last[2]:
                self.bar_anomalies += 1
                return "STALE_OR_OUT_OF_ORDER_BAR"
        self._last_bar_id = bar_id
        return "NEW_CLOSED_BAR"

    def mark_bar_seen(self, bar_id) -> None:
        """持久化证据缺失时保守标记：该 bar 已见，本轮不推进。"""
        if bar_id is not None:
            self._last_bar_id = bar_id

    @property
    def last_bar_id(self):
        return self._last_bar_id

    def update(self, raw_regime: str, raw_confidence: float,
               features: Dict[str, Any], bar_id=None) -> Dict[str, Any]:
        bar_status = self._bar_status(bar_id)
        if bar_status != "NEW_CLOSED_BAR":
            # 非新证据：duration 与 pending_count 都不推进。
            out = self._build_output()
            out['bar_status'] = bar_status
            return out

        self.bars_consumed += 1
        self.current.duration += 1

        if raw_regime == self.current.regime:
            self.pending_count = 0
            self.current.confidence = self._decay_confidence(raw_confidence)
            return self._build_output()

        if raw_regime == self.pending_regime:
            self.pending_count += 1
        else:
            self.pending_regime = raw_regime
            self.pending_count = 1

        if self.pending_count >= self.confirmation_count:
            self._transition(raw_regime, raw_confidence)

        return self._build_output()

    def _transition(self, new_regime: str, new_confidence: float):
        self.history.append({
            'from': self.current.regime,
            'to': new_regime,
            'duration': self.current.duration,
            'timestamp': datetime.now().isoformat()
        })

        self.current.regime = new_regime
        self.current.confidence = new_confidence * (1 - self.transition_penalty)
        self.current.duration = 0
        self.current.entry_time = datetime.now()
        self.current.transitions += 1
        self.pending_count = 0

    def _decay_confidence(self, raw_confidence: float) -> float:
        duration_factor = min(self.current.duration / 20, 1.0)
        bonus = self.persistence_bonus * duration_factor
        return min(raw_confidence + bonus, 0.95)

    def _build_output(self) -> Dict[str, Any]:
        return {
            'regime': self.current.regime,
            'confidence': round(self.current.confidence, 4),
            'duration': self.current.duration,
            'transitions': self.current.transitions,
            'is_stable': self.current.duration >= self.confirmation_count,
            'pending_regime': self.pending_regime,
            'pending_count': self.pending_count,
            'bar_status': 'NEW_CLOSED_BAR',
            'last_bar_id': self._last_bar_id,
            'bar_anomalies': self.bar_anomalies,
        }

    def get_regime_weight(self) -> float:
        if self.current.duration < 3:
            return 0.5
        elif self.current.duration < 10:
            return 0.8
        else:
            return 1.0

    def should_trade(self) -> bool:
        return self.current.duration >= self.confirmation_count