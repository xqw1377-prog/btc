from typing import Dict, Any, List
import numpy as np

class MarketBehavior(Enum):
    TRENDING = "TRENDING"
    MEAN_REVERTING = "MEAN_REVERTING"
    LIQUIDITY_DRIVEN = "LIQUIDITY_DRIVEN"
    TRANSITION = "TRANSITION"

class AdaptiveRegimeModel:
    def __init__(self):
        self.behavior_history = []
        self.min_samples = 20
    
    def identify_regime(self, features: Dict[str, Any]) -> Dict[str, Any]:
        volatility = features.get('volatility', 0)
        momentum = features.get('momentum_pct', 0)
        volume = features.get('volume', 0)
        adx = features.get('adx', 0)
        ema_slope = features.get('ema_slope', 0)
        funding_rate = features.get('funding_rate', 0)
        
        scores = {
            'trending': self._score_trending(adx, ema_slope, momentum),
            'mean_reverting': self._score_mean_reverting(adx, volatility),
            'liquidity_driven': self._score_liquidity(volume, volatility),
            'transition': self._score_transition(volatility, funding_rate)
        }
        
        max_score = max(scores.values())
        max_key = max(scores, key=scores.get)
        
        behavior_map = {
            'trending': MarketBehavior.TRENDING.value,
            'mean_reverting': MarketBehavior.MEAN_REVERTING.value,
            'liquidity_driven': MarketBehavior.LIQUIDITY_DRIVEN.value,
            'transition': MarketBehavior.TRANSITION.value
        }
        
        confidence = self._calculate_confidence(scores, max_score)
        
        self.behavior_history.append({
            'behavior': behavior_map[max_key],
            'confidence': confidence,
            'timestamp': features.get('timestamp')
        })
        
        if len(self.behavior_history) > 50:
            self.behavior_history = self.behavior_history[-50:]
        
        return {
            'regime': behavior_map[max_key],
            'confidence': confidence,
            'scores': scores,
            'features': features
        }
    
    def _score_trending(self, adx: float, ema_slope: float, momentum: float) -> float:
        score = 0.0
        
        if adx > 25:
            score += 0.3
        elif adx > 15:
            score += 0.15
        
        if ema_slope > 0:
            score += 0.3
        elif ema_slope < 0:
            score += 0.15
        
        if abs(momentum) > 0.005:
            score += 0.4
        elif abs(momentum) > 0.002:
            score += 0.2
        
        return min(1.0, score)
    
    def _score_mean_reverting(self, adx: float, volatility: float) -> float:
        score = 0.0
        
        if adx < 20:
            score += 0.4
        elif adx < 25:
            score += 0.2
        
        if volatility < 1.5:
            score += 0.3
        elif volatility < 2.0:
            score += 0.15
        
        score += 0.3
        
        return min(1.0, score)
    
    def _score_liquidity(self, volume: float, volatility: float) -> float:
        score = 0.0
        
        if volume > 15000:
            score += 0.4
        elif volume > 8000:
            score += 0.2
        
        if volatility > 2.5:
            score += 0.3
        elif volatility > 1.8:
            score += 0.15
        
        score += 0.3
        
        return min(1.0, score)
    
    def _score_transition(self, volatility: float, funding_rate: float) -> float:
        score = 0.0
        
        if volatility > 3.0:
            score += 0.4
        elif volatility > 2.5:
            score += 0.2
        
        if abs(funding_rate) > 0.002:
            score += 0.3
        elif abs(funding_rate) > 0.001:
            score += 0.15
        
        score += 0.3
        
        return min(1.0, score)
    
    def _calculate_confidence(self, scores: Dict[str, float], max_score: float) -> float:
        sorted_scores = sorted(scores.values(), reverse=True)
        
        if len(sorted_scores) >= 2:
            diff = sorted_scores[0] - sorted_scores[1]
            confidence = 0.5 + diff * 2
        else:
            confidence = max_score
        
        return min(1.0, max(0.3, confidence))
    
    def get_recent_behavior(self, window: int = 10) -> List[Dict[str, Any]]:
        return self.behavior_history[-window:]
    
    def get_dominant_behavior(self) -> str:
        if not self.behavior_history:
            return MarketBehavior.TRANSITION.value
        
        behaviors = [h['behavior'] for h in self.behavior_history[-20:]]
        counts = {b: behaviors.count(b) for b in set(behaviors)}
        return max(counts, key=counts.get)

from enum import Enum
