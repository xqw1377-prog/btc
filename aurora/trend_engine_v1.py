from typing import Dict, Any, Optional
from enum import Enum
import pandas as pd

class TrendSignal(Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    ADD = "ADD"
    NONE = "NONE"

class TrendEngine:
    def __init__(self):
        self.position = None
        self.entry_price = 0.0
        self.add_count = 0
        self.max_adds = 3
        self.last_structure = ""
    
    def detect_structure(self, df: pd.DataFrame) -> str:
        if len(df) < 40:
            return "INDETERMINATE"
        
        recent = df.iloc[-20:]
        prev = df.iloc[-40:-20]
        
        recent_high = recent['high'].max()
        recent_low = recent['low'].min()
        prev_high = prev['high'].max()
        prev_low = prev['low'].min()
        
        if recent_high > prev_high and recent_low > prev_low:
            return "HH/HL"
        elif recent_low < prev_low and recent_high < prev_high:
            return "LL/LH"
        else:
            return "RANGE"
    
    def check_breakout(self, df: pd.DataFrame) -> bool:
        if len(df) < 20:
            return False
        
        recent = df.iloc[-10:]
        prev_range = df.iloc[-30:-10]
        
        recent_high = recent['high'].max()
        prev_high = prev_range['high'].max()
        
        return recent_high > prev_high * 1.001
    
    def check_pullback(self, df: pd.DataFrame) -> bool:
        if not self.position or not self.entry_price:
            return False
        
        latest = df.iloc[-1]
        current_price = latest['close']
        
        if self.position == "LONG":
            pullback_low = self.entry_price * 0.985
            pullback_high = self.entry_price * 1.005
            return pullback_low <= current_price <= pullback_high
        else:
            pullback_low = self.entry_price * 0.995
            pullback_high = self.entry_price * 1.015
            return pullback_low <= current_price <= pullback_high
    
    def check_trend_break(self, df: pd.DataFrame, state: Dict[str, Any]) -> bool:
        if not self.position:
            return False
        
        structure = self.detect_structure(df)
        
        if state['regime'] != "TREND":
            return True
        
        if structure == "RANGE":
            return True
        
        features = state['features']
        if self.position == "LONG" and features['ema20'] < features['ema60']:
            return True
        if self.position == "SHORT" and features['ema20'] > features['ema60']:
            return True
        
        return False
    
    def generate_signal(self, df: pd.DataFrame, state: Dict[str, Any]) -> Dict[str, Any]:
        if not state.get('confidence') or state['confidence'] < 0.6:
            return {"signal": TrendSignal.NONE.value, "reason": "Low confidence"}
        
        structure = self.detect_structure(df)
        
        if self.check_trend_break(df, state):
            signal = TrendSignal.EXIT
            reason = f"Trend break detected: {structure}"
            self.position = None
            self.entry_price = 0.0
            self.add_count = 0
            return {"signal": signal.value, "reason": reason, "direction": self.position}
        
        if self.position is None:
            if state['regime'] == "TREND" and structure in ["HH/HL", "LL/LH"]:
                if self.check_breakout(df):
                    direction = "LONG" if structure == "HH/HL" else "SHORT"
                    self.position = direction
                    self.entry_price = df.iloc[-1]['close']
                    self.last_structure = structure
                    return {
                        "signal": TrendSignal.ENTER.value,
                        "reason": f"Breakout detected: {structure}",
                        "direction": direction,
                        "entry_price": self.entry_price
                    }
            
            return {"signal": TrendSignal.NONE.value, "reason": "No entry condition"}
        
        if self.add_count < self.max_adds and self.check_pullback(df):
            self.add_count += 1
            return {
                "signal": TrendSignal.ADD.value,
                "reason": f"Pullback add #{self.add_count}",
                "direction": self.position
            }
        
        return {"signal": TrendSignal.NONE.value, "reason": "No signal"}
    
    def get_position_info(self) -> Dict[str, Any]:
        return {
            "position": self.position,
            "entry_price": self.entry_price,
            "add_count": self.add_count
        }
