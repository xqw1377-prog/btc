from typing import Dict, Any
from enum import Enum

class MarketRegime(Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"

class MarketStateEngineV1:
    def __init__(self):
        self.min_buffer_size = 50
    
    def identify_regime(self, features: Dict[str, Any]) -> Dict[str, Any]:
        if not features:
            return {"regime": MarketRegime.TRANSITION.value, "confidence": 0.5}
        
        ema20 = features['ema20']
        ema60 = features['ema60']
        adx = features['adx']
        atr = features['atr']
        atr_mean = features['atr_mean']
        adx_mean = features['adx_mean']
        ema_slope = features['ema_slope']
        
        regime = MarketRegime.TRANSITION
        confidence = 0.6
        
        if adx > 25 and adx > adx_mean:
            if ema20 > ema60 and ema_slope > 0:
                regime = MarketRegime.TREND
                confidence = min(0.9, 0.6 + (adx - 25) / 50 + ema_slope / 100)
            elif ema20 < ema60 and ema_slope < 0:
                regime = MarketRegime.TREND
                confidence = min(0.9, 0.6 + (adx - 25) / 50 - ema_slope / 100)
        
        elif adx < 20 and atr < atr_mean * 0.8:
            regime = MarketRegime.RANGE
            confidence = min(0.85, 0.6 + (20 - adx) / 20)
        
        else:
            regime = MarketRegime.TRANSITION
            volatility_ratio = atr / atr_mean if atr_mean > 0 else 1
            confidence = min(0.7, 0.5 + volatility_ratio * 0.2)
        
        return {
            "regime": regime.value,
            "confidence": round(confidence, 2),
            "features": features
        }
    
    def get_trend_direction(self, features: Dict[str, Any]) -> str:
        if features.get('is_uptrend', False):
            return "LONG"
        elif not features.get('is_uptrend', True):
            return "SHORT"
        return "NONE"
    
    def should_trade(self, state: Dict[str, Any]) -> bool:
        return state['confidence'] >= 0.6
