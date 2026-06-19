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

    def update(self, raw_regime: str, raw_confidence: float, features: Dict[str, Any]) -> Dict[str, Any]:
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
            'pending_count': self.pending_count
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