import numpy as np
from .types import MarketData, MarketState, Regime, Direction
from datetime import datetime
from typing import List, Optional

class MarketStateEngine:
    def __init__(self):
        self.history: List[MarketData] = []
        self.min_history = 100
        self.adx_period = 14
        self.ema_short = 20
        self.ema_long = 60
        self.atr_period = 14
    
    def add_data(self, data: MarketData) -> None:
        self.history.append(data)
        if len(self.history) > 500:
            self.history = self.history[-500:]
    
    def calculate_adx(self, prices: np.ndarray, high: np.ndarray, low: np.ndarray, period: int) -> float:
        if len(prices) < period + 1:
            return 0.0
        
        up_move = high[1:] - high[:-1]
        down_move = low[:-1] - low[1:]
        
        plus_dm = np.where(up_move > down_move, np.maximum(up_move, 0), 0)
        minus_dm = np.where(down_move > up_move, np.maximum(down_move, 0), 0)
        
        tr = np.maximum(
            high[1:] - low[1:],
            np.abs(high[1:] - prices[:-1]),
            np.abs(low[1:] - prices[:-1])
        )
        
        atr = np.mean(tr[-period:])
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr
        
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = np.mean(dx[-period:])
        
        return adx
    
    def calculate_ema(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period:
            return np.mean(prices)
        
        alpha = 2 / (period + 1)
        ema = np.zeros_like(prices)
        ema[0] = prices[0]
        
        for i in range(1, len(prices)):
            ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
        
        return ema[-1]
    
    def calculate_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        if len(high) < period + 1:
            return 0.0
        
        tr = np.maximum(
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
        
        return np.mean(tr[-period:])
    
    def identify_structure(self, prices: np.ndarray) -> str:
        if len(prices) < 20:
            return "INDETERMINATE"
        
        recent = prices[-20:]
        highs = recent.max()
        lows = recent.min()
        prev_highs = prices[-40:-20].max()
        prev_lows = prices[-40:-20].min()
        
        if highs > prev_highs and lows > prev_lows:
            return "HH/HL"
        elif lows < prev_lows and highs < prev_highs:
            return "LL/LH"
        else:
            return "RANGE"
    
    def calculate_volatility(self, prices: np.ndarray, period: int = 20) -> float:
        if len(prices) < period:
            return 0.0
        returns = np.log(prices[1:] / prices[:-1])
        return np.std(returns[-period:]) * np.sqrt(24 * 365)
    
    def check_transition(self, oi: np.ndarray, funding: np.ndarray, volatility: float) -> bool:
        if len(oi) < 20 or len(funding) < 20:
            return False
        
        recent_oi = oi[-10:]
        oi_surge = (recent_oi[-1] - recent_oi[0]) / recent_oi[0] > 0.15
        
        funding_extreme = np.abs(funding[-5:]).mean() > 0.003
        
        return oi_surge or funding_extreme or volatility > 2.0
    
    def get_state(self) -> MarketState:
        if len(self.history) < self.min_history:
            return MarketState(
                regime="RANGE",
                direction="NONE",
                confidence=0.5,
                adx=0.0,
                atr=0.0,
                volatility=0.0,
                structure="INDETERMINATE"
            )
        
        prices = np.array([d.close for d in self.history])
        high = np.array([d.high for d in self.history])
        low = np.array([d.low for d in self.history])
        oi = np.array([d.oi for d in self.history])
        funding = np.array([d.funding_rate for d in self.history])
        
        adx = self.calculate_adx(prices, high, low, self.adx_period)
        atr = self.calculate_atr(high, low, prices, self.atr_period)
        volatility = self.calculate_volatility(prices)
        structure = self.identify_structure(prices)
        
        ema_short = self.calculate_ema(prices, self.ema_short)
        ema_long = self.calculate_ema(prices, self.ema_long)
        
        is_transition = self.check_transition(oi, funding, volatility)
        
        if is_transition:
            regime: Regime = "TRANSITION"
            direction: Direction = "NONE"
            confidence = min(0.8, 0.5 + volatility / 4)
        elif adx > 25 and ema_short > ema_long:
            regime = "TREND"
            direction = "LONG"
            confidence = min(0.95, adx / 50 + 0.5)
        elif adx > 25 and ema_short < ema_long:
            regime = "TREND"
            direction = "SHORT"
            confidence = min(0.95, adx / 50 + 0.5)
        elif adx < 20:
            regime = "RANGE"
            direction = "NONE"
            confidence = min(0.85, (20 - adx) / 20 + 0.5)
        else:
            regime = "TRANSITION"
            direction = "NONE"
            confidence = 0.6
        
        return MarketState(
            regime=regime,
            direction=direction,
            confidence=confidence,
            adx=adx,
            atr=atr,
            volatility=volatility,
            structure=structure
        )
