from typing import Dict, Any, Optional
from enum import Enum
import pandas as pd
import numpy as np

class ExecSignal(Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    NONE = "NONE"

class ExecutionEngine:
    def __init__(self):
        self.position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.min_score = 75
    
    def calculate_structure_score(self, df: pd.DataFrame, state: Dict[str, Any]) -> float:
        features = state.get('features', {})
        structure = self._detect_short_term_structure(df)
        
        if structure == "BULLISH":
            return 25
        elif structure == "BEARISH":
            return 25
        elif structure == "NEUTRAL":
            dist_to_vwap = abs(features.get('close', 0) - features.get('vwap', 0)) / (features.get('vwap', 1) + 1e-10)
            if dist_to_vwap < 0.005:
                return 20
            elif dist_to_vwap < 0.01:
                return 15
            else:
                return 5
        return 10
    
    def calculate_momentum_score(self, df: pd.DataFrame) -> float:
        if len(df) < 10:
            return 10
        
        recent = df.iloc[-10:]
        prev = df.iloc[-20:-10]
        
        recent_returns = recent['close'].pct_change().dropna()
        prev_returns = prev['close'].pct_change().dropna()
        
        recent_mean = recent_returns.mean()
        prev_mean = prev_returns.mean()
        
        if recent_mean > 0.001 and recent_mean > prev_mean * 1.5:
            return 25
        elif recent_mean > 0.0005:
            return 15
        elif abs(recent_mean) < 0.0002:
            return 5
        else:
            return 10
    
    def calculate_volatility_score(self, state: Dict[str, Any]) -> float:
        volatility = state.get('features', {}).get('volatility', 0)
        
        if volatility < 1.0:
            return 10
        elif volatility < 2.0:
            return 20
        elif volatility < 3.0:
            return 15
        else:
            return 5
    
    def calculate_liquidity_score(self, df: pd.DataFrame) -> float:
        if len(df) < 5:
            return 10
        
        recent_volume = df.iloc[-5:]['volume'].mean()
        
        if recent_volume > 10000:
            return 25
        elif recent_volume > 5000:
            return 20
        elif recent_volume > 2000:
            return 15
        else:
            return 10
    
    def _detect_short_term_structure(self, df: pd.DataFrame) -> str:
        if len(df) < 10:
            return "NEUTRAL"
        
        recent = df.iloc[-10:]
        ema20 = recent['close'].ewm(span=20).mean().iloc[-1]
        
        if df.iloc[-1]['close'] > ema20 and recent['close'].iloc[-1] > recent['close'].iloc[0]:
            return "BULLISH"
        elif df.iloc[-1]['close'] < ema20 and recent['close'].iloc[-1] < recent['close'].iloc[0]:
            return "BEARISH"
        return "NEUTRAL"
    
    def calculate_total_score(self, df: pd.DataFrame, state: Dict[str, Any]) -> float:
        structure = self.calculate_structure_score(df, state)
        momentum = self.calculate_momentum_score(df)
        volatility = self.calculate_volatility_score(state)
        liquidity = self.calculate_liquidity_score(df)
        
        return structure + momentum + volatility + liquidity
    
    def check_fast_kill(self, df: pd.DataFrame, state: Dict[str, Any]) -> bool:
        if not self.position:
            return False
        
        features = state.get('features', {})
        current_price = features.get('close', 0)
        
        dist_to_vwap = abs(current_price - features.get('vwap', 0)) / (features.get('vwap', 1) + 1e-10)
        if dist_to_vwap > 0.015:
            return True
        
        if len(df) >= 5:
            recent_returns = df.iloc[-5:]['close'].pct_change().dropna()
            if recent_returns.mean() < -0.003:
                return True
        
        return False
    
    def check_take_profit(self, df: pd.DataFrame) -> bool:
        if not self.position or not self.entry_price:
            return False
        
        current_price = df.iloc[-1]['close']
        target_pct = 0.01
        
        if self.position == "LONG":
            return current_price >= self.entry_price * (1 + target_pct)
        else:
            return current_price <= self.entry_price * (1 - target_pct)
    
    def generate_signal(self, df: pd.DataFrame, state: Dict[str, Any]) -> Dict[str, Any]:
        if self.position is not None:
            if self.check_fast_kill(df, state):
                signal = ExecSignal.EXIT
                reason = "Fast kill triggered"
                pnl = self._calculate_pnl(df.iloc[-1]['close'])
                result = {"signal": signal.value, "reason": reason, "direction": self.position, "pnl": pnl}
                self._reset()
                return result
            
            if self.check_take_profit(df):
                signal = ExecSignal.EXIT
                reason = "Take profit hit"
                pnl = self._calculate_pnl(df.iloc[-1]['close'])
                result = {"signal": signal.value, "reason": reason, "direction": self.position, "pnl": pnl}
                self._reset()
                return result
        
        if self.position is None:
            score = self.calculate_total_score(df, state)
            
            if score >= self.min_score:
                features = state.get('features', {})
                direction = "LONG" if features.get('close', 0) > features.get('vwap', 0) else "SHORT"
                
                atr = features.get('atr', 0)
                current_price = features.get('close', 0)
                
                self.position = direction
                self.entry_price = current_price
                self.stop_loss = current_price - atr * 0.5 if direction == "LONG" else current_price + atr * 0.5
                self.take_profit = current_price * 1.01 if direction == "LONG" else current_price * 0.99
                
                return {
                    "signal": ExecSignal.ENTER.value,
                    "reason": f"Score {score:.1f} >= {self.min_score}",
                    "direction": direction,
                    "entry_price": current_price,
                    "stop_loss": self.stop_loss,
                    "take_profit": self.take_profit,
                    "score": score
                }
        
        return {"signal": ExecSignal.NONE.value, "reason": "No signal"}
    
    def _calculate_pnl(self, current_price: float) -> float:
        if not self.position or not self.entry_price:
            return 0.0
        
        if self.position == "LONG":
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price
    
    def _reset(self):
        self.position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.stop_loss = 0.0
        self.take_profit = 0.0
    
    def get_position_info(self) -> Dict[str, Any]:
        return {
            "position": self.position,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit
        }
