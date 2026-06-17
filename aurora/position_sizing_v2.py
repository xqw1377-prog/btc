from typing import Dict, Any
import numpy as np

class PositionSizingEngine:
    def __init__(self):
        self.base_risk_pct = 0.01
        self.max_position_pct = 0.10
        self.min_position_pct = 0.001
        
        self.trend_factor_map = {
            "TREND": 1.5,
            "RANGE": 0.5,
            "TRANSITION": 0.3
        }
        
        self.engine_factor_map = {
            "TREND": 1.2,
            "EXECUTION": 0.8
        }
    
    def calculate_position_size(
        self,
        balance: float,
        price: float,
        market_state: Dict[str, Any],
        engine_type: str,
        regime_stats: Dict[str, Any] = None,
        risk_multiplier: float = 1.0
    ) -> Dict[str, Any]:
        
        base_risk = balance * self.base_risk_pct
        
        regime = market_state.get('regime', 'TRANSITION')
        confidence = market_state.get('confidence', 0.5)
        features = market_state.get('features', {})
        
        trend_factor = self.trend_factor_map.get(regime, 0.3)
        
        volatility = features.get('volatility', 1.0)
        vol_factor = 1.0 / (1.0 + volatility)
        
        confidence_factor = confidence
        
        regime_factor = 1.0
        if regime_stats:
            regime_data = regime_stats.get(regime, {})
            win_rate = regime_data.get('win_rate', 0.5)
            avg_rr = regime_data.get('avg_rr', 1.0)
            
            regime_factor = (win_rate * avg_rr) / (1.0 + (1.0 - win_rate))
            regime_factor = max(0.3, min(2.0, regime_factor))
        
        engine_factor = self.engine_factor_map.get(engine_type, 1.0)
        
        position_value = (
            base_risk *
            trend_factor *
            vol_factor *
            confidence_factor *
            regime_factor *
            engine_factor *
            risk_multiplier
        )
        
        position_pct = position_value / balance
        position_pct = max(self.min_position_pct, min(self.max_position_pct, position_pct))
        
        position_value = balance * position_pct
        quantity = position_value / price
        quantity = round(quantity, 3)
        
        return {
            'quantity': quantity,
            'position_value': position_value,
            'position_pct': position_pct,
            'factors': {
                'base_risk': base_risk,
                'trend_factor': trend_factor,
                'vol_factor': vol_factor,
                'confidence_factor': confidence_factor,
                'regime_factor': regime_factor,
                'engine_factor': engine_factor,
                'risk_multiplier': risk_multiplier
            }
        }
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        market_state: Dict[str, Any]
    ) -> Dict[str, float]:
        
        regime = market_state.get('regime', 'TRANSITION')
        confidence = market_state.get('confidence', 0.5)
        
        if regime == "TREND":
            atr_multiplier = 2.0
        elif regime == "RANGE":
            atr_multiplier = 1.0
        else:
            atr_multiplier = 1.5
        
        if direction == "LONG":
            stop_loss = entry_price - (atr * atr_multiplier)
            take_profit = entry_price + (atr * atr_multiplier * 2)
        else:
            stop_loss = entry_price + (atr * atr_multiplier)
            take_profit = entry_price - (atr * atr_multiplier * 2)
        
        return {
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2),
            'atr_multiplier': atr_multiplier,
            'risk_reward_ratio': 2.0
        }
    
    def calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        direction: str,
        atr: float
    ) -> Dict[str, Any]:
        
        if direction == "LONG":
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct > 0.02:
                trailing_stop = current_price - (atr * 1.5)
                return {
                    'activate': True,
                    'trailing_stop': round(trailing_stop, 2),
                    'profit_pct': profit_pct
                }
        else:
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct > 0.02:
                trailing_stop = current_price + (atr * 1.5)
                return {
                    'activate': True,
                    'trailing_stop': round(trailing_stop, 2),
                    'profit_pct': profit_pct
                }
        
        return {
            'activate': False,
            'trailing_stop': None,
            'profit_pct': profit_pct if 'profit_pct' in dir() else 0
        }