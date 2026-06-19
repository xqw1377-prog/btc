from typing import Dict, Any, List
from dataclasses import dataclass
from .kernel_types import Intent
from .feature_engine import FeatureEngine
from .market_state_engine_v2 import MarketStateEngineV2
from .signal_providers import TrendSignalProvider, BreakoutSignalProvider, MomentumSignalProvider, MeanReversionSignalProvider
from .signal_orthogonalizer import SignalOrthogonalizer
from .regime_memory import RegimeMemoryModel

@dataclass
class AlphaVector:
    direction: float
    confidence: float
    regime: str
    regime_confidence: float
    regime_stable: bool
    components: Dict[str, float]
    reason: str

class AlphaEngine:
    def __init__(self):
        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2(confirmation_count=3)
        self.regime_memory = RegimeMemoryModel(confirmation_count=3)
        self.orthogonalizer = SignalOrthogonalizer()

        self.trend = TrendSignalProvider()
        self.breakout = BreakoutSignalProvider()
        self.momentum = MomentumSignalProvider()
        self.mr = MeanReversionSignalProvider()

        self.weights = {
            "TREND":      {"trend": 0.50, "breakout": 0.25, "momentum": 0.15, "mr": 0.10},
            "RANGE":      {"mr": 0.50, "momentum": 0.20, "trend": 0.15, "breakout": 0.15},
            "TRANSITION": {"breakout": 0.35, "trend": 0.30, "momentum": 0.20, "mr": 0.15},
        }

    def compute(self, df) -> AlphaVector:
        features = self.feature_engine.get_latest_features(df)
        raw_state = self.state_engine.identify_regime(features)
        regime_state = self.regime_memory.update(raw_state['regime'], raw_state['confidence'], features)

        regime = regime_state['regime']
        weights = self.weights.get(regime, self.weights["TRANSITION"])

        signals = [
            self.trend.generate(features, regime),
            self.breakout.generate(features, df),
            self.momentum.generate(features),
            self.mr.generate(features),
        ]

        orthogonal = self.orthogonalizer.orthogonalize(signals)

        direction = 0.0
        confidence_sum = 0.0
        total_weight = 0.0
        components = {}

        for sig in orthogonal:
            if sig.direction == Intent.FLAT:
                components[sig.source] = 0.0
                continue

            w = weights.get(sig.source, 0.0)
            val = (1 if sig.direction == Intent.LONG else -1) * sig.confidence * w
            direction += val
            confidence_sum += sig.confidence * w
            total_weight += w
            components[sig.source] = val

        if total_weight > 0:
            avg_confidence = confidence_sum / total_weight
        else:
            avg_confidence = 0.0

        direction = max(-1.0, min(1.0, direction))

        reasons = []
        for sig in orthogonal:
            if sig.direction != Intent.FLAT:
                reasons.append(f"{sig.source}={sig.direction.value}")

        return AlphaVector(
            direction=direction,
            confidence=avg_confidence,
            regime=regime,
            regime_confidence=regime_state['confidence'],
            regime_stable=regime_state['is_stable'],
            components=components,
            reason=" | ".join(reasons) if reasons else "No signal"
        )