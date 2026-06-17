from typing import Dict, Any
from enum import Enum

class MarketRegime(Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"

class MarketStateEngineV2:
    def __init__(self, confirmation_count: int = 3):
        self.confirmation_count = confirmation_count
        
        self.current_regime = MarketRegime.TRANSITION
        self.pending_regime = MarketRegime.TRANSITION
        self.confirmation_counter = 0
        
        self.regime_history = []
        self.max_history = 100
        
        self.trend_thresholds = {
            'adx_min': 25,
            'adx_mean_multiplier': 1.0,
            'ema_slope_min': 0
        }
        
        self.range_thresholds = {
            'adx_max': 20,
            'atr_mean_multiplier': 0.8
        }
    
    def identify_regime(self, features: Dict[str, Any]) -> Dict[str, Any]:
        if not features:
            return {
                'regime': self.current_regime.value,
                'confidence': 0.5,
                'confirmed': True,
                'confirmation_count': 0
            }
        
        detected_regime = self._detect_regime(features)
        
        if detected_regime == self.current_regime:
            self.confirmation_counter = 0
            confirmed = True
        elif detected_regime == self.pending_regime:
            self.confirmation_counter += 1
            confirmed = self.confirmation_counter >= self.confirmation_count
            
            if confirmed:
                self.current_regime = self.pending_regime
                self.confirmation_counter = 0
        else:
            self.pending_regime = detected_regime
            self.confirmation_counter = 1
            confirmed = False
        
        confidence = self._calculate_confidence(features, confirmed)
        
        self.regime_history.append({
            'regime': self.current_regime.value,
            'confidence': confidence,
            'confirmed': confirmed
        })
        if len(self.regime_history) > self.max_history:
            self.regime_history = self.regime_history[-self.max_history:]
        
        return {
            'regime': self.current_regime.value,
            'confidence': confidence,
            'confirmed': confirmed,
            'confirmation_count': self.confirmation_counter,
            'pending_regime': self.pending_regime.value,
            'features': features
        }
    
    def _detect_regime(self, features: Dict[str, Any]) -> MarketRegime:
        ema20 = features.get('ema20', 0)
        ema60 = features.get('ema60', 0)
        adx = features.get('adx', 0)
        atr = features.get('atr', 0)
        atr_mean = features.get('atr_mean', 0)
        adx_mean = features.get('adx_mean', 0)
        ema_slope = features.get('ema_slope', 0)
        
        if (adx > self.trend_thresholds['adx_min'] and 
            adx > adx_mean * self.trend_thresholds['adx_mean_multiplier']):
            if (ema20 > ema60 and ema_slope > self.trend_thresholds['ema_slope_min']):
                return MarketRegime.TREND
            elif (ema20 < ema60 and ema_slope < -self.trend_thresholds['ema_slope_min']):
                return MarketRegime.TREND
        
        if (adx < self.range_thresholds['adx_max'] and 
            atr < atr_mean * self.range_thresholds['atr_mean_multiplier']):
            return MarketRegime.RANGE
        
        return MarketRegime.TRANSITION
    
    def _calculate_confidence(self, features: Dict[str, Any], confirmed: bool) -> float:
        ema20 = features.get('ema20', 0)
        ema60 = features.get('ema60', 0)
        adx = features.get('adx', 0)
        atr = features.get('atr', 0)
        atr_mean = features.get('atr_mean', 0)
        ema_slope = features.get('ema_slope', 0)
        
        base_confidence = 0.5
        
        if self.current_regime == MarketRegime.TREND:
            adx_score = min((adx - 25) / 25, 1.0) * 0.3
            ema_score = abs(ema_slope) / 100 * 0.2
            base_confidence = 0.6 + adx_score + ema_score
        
        elif self.current_regime == MarketRegime.RANGE:
            adx_score = min((20 - adx) / 20, 1.0) * 0.3
            atr_score = (1 - atr / atr_mean) * 0.2 if atr_mean > 0 else 0
            base_confidence = 0.6 + adx_score + atr_score
        
        else:
            volatility_ratio = atr / atr_mean if atr_mean > 0 else 1
            base_confidence = 0.5 + volatility_ratio * 0.1
        
        if confirmed:
            base_confidence = min(base_confidence + 0.1, 0.95)
        
        return round(min(max(base_confidence, 0.1), 0.95), 2)
    
    def get_trend_direction(self, features: Dict[str, Any]) -> str:
        if features.get('is_uptrend', False):
            return "LONG"
        elif not features.get('is_uptrend', True):
            return "SHORT"
        return "NONE"
    
    def should_trade(self, state: Dict[str, Any]) -> bool:
        if not state.get('confirmed', False):
            return False
        return state['confidence'] >= 0.6
    
    def get_regime_stats(self) -> Dict[str, Any]:
        if not self.regime_history:
            return {}
        
        regime_counts = {}
        for entry in self.regime_history:
            regime = entry['regime']
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        total = len(self.regime_history)
        return {
            'current_regime': self.current_regime.value,
            'regime_distribution': {k: v/total for k, v in regime_counts.items()},
            'total_observations': total
        }