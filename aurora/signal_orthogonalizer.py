import math
from typing import Dict, Any, List
from .kernel_types import Signal, Intent

class SignalOrthogonalizer:
    def __init__(self):
        self.signal_history: Dict[str, List[float]] = {
            'trend': [],
            'breakout': [],
            'momentum': [],
            'mr': []
        }
        self.max_history = 50

    def orthogonalize(self, signals: List[Signal]) -> List[Signal]:
        signal_map = {}
        for sig in signals:
            signal_map[sig.source] = sig
            if sig.source in self.signal_history:
                val = self._signal_to_value(sig)
                self.signal_history[sig.source].append(val)
                if len(self.signal_history[sig.source]) > self.max_history:
                    self.signal_history[sig.source] = self.signal_history[sig.source][-self.max_history:]

        sources = list(signal_map.keys())
        orthogonal_signals = []

        for i, source in enumerate(sources):
            sig = signal_map[source]

            if sig.direction == Intent.FLAT:
                orthogonal_signals.append(sig)
                continue

            correlation_penalty = 0.0
            for j, other_source in enumerate(sources):
                if i == j or other_source not in signal_map:
                    continue
                other_sig = signal_map[other_source]
                if other_sig.direction == Intent.FLAT:
                    continue

                corr = self._compute_correlation(source, other_source)
                if corr > 0.7 and sig.direction == other_sig.direction:
                    correlation_penalty += (corr - 0.7) * 0.5

            adjusted_confidence = max(0.1, sig.confidence - correlation_penalty)

            orthogonal_signals.append(Signal(
                source=sig.source,
                direction=sig.direction,
                confidence=adjusted_confidence,
                timeframe=sig.timeframe,
                reason=f"{sig.reason} (orthogonalized)"
            ))

        return orthogonal_signals

    def _signal_to_value(self, sig: Signal) -> float:
        if sig.direction == Intent.FLAT:
            return 0.0
        val = sig.confidence if sig.direction == Intent.LONG else -sig.confidence
        return val

    def _compute_correlation(self, source_a: str, source_b: str) -> float:
        hist_a = self.signal_history.get(source_a, [])
        hist_b = self.signal_history.get(source_b, [])

        n = min(len(hist_a), len(hist_b))
        if n < 5:
            return 0.0

        a = hist_a[-n:]
        b = hist_b[-n:]

        mean_a = sum(a) / n
        mean_b = sum(b) / n

        cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b)) / n
        var_a = sum((x - mean_a) ** 2 for x in a) / n
        var_b = sum((y - mean_b) ** 2 for y in b) / n

        std_a = math.sqrt(var_a) if var_a > 0 else 0.001
        std_b = math.sqrt(var_b) if var_b > 0 else 0.001

        corr = cov / (std_a * std_b)
        return max(-1, min(1, corr))

    def get_correlation_matrix(self) -> Dict[str, Dict[str, float]]:
        sources = list(self.signal_history.keys())
        matrix = {}
        for a in sources:
            matrix[a] = {}
            for b in sources:
                if a == b:
                    matrix[a][b] = 1.0
                else:
                    matrix[a][b] = round(self._compute_correlation(a, b), 3)
        return matrix