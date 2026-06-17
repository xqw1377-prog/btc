from typing import Dict, Any
from enum import Enum
from .trend_engine_v1 import TrendEngine, TrendSignal
from .execution_engine_v1 import ExecutionEngine, ExecSignal

class EngineType(Enum):
    TREND = "TREND"
    EXECUTION = "EXECUTION"

class StrategyRouter:
    def __init__(self):
        self.trend_engine = TrendEngine()
        self.exec_engine = ExecutionEngine()
        self.active_engine = None
    
    def route(self, df, market_state: Dict[str, Any]) -> Dict[str, Any]:
        regime = market_state.get('regime', "TRANSITION")
        
        if regime == "TREND":
            return self._handle_trend_regime(df, market_state)
        elif regime == "RANGE":
            return self._handle_range_regime(df, market_state)
        else:
            return self._handle_transition_regime(df, market_state)
    
    def _handle_trend_regime(self, df, market_state: Dict[str, Any]) -> Dict[str, Any]:
        trend_signal = self.trend_engine.generate_signal(df, market_state)
        
        if trend_signal['signal'] != TrendSignal.NONE.value:
            self.active_engine = EngineType.TREND
            return {
                **trend_signal,
                "engine": EngineType.TREND.value
            }
        
        exec_signal = self.exec_engine.generate_signal(df, market_state)
        
        if exec_signal['signal'] != ExecSignal.NONE.value and not self.trend_engine.position:
            self.active_engine = EngineType.EXECUTION
            return {
                **exec_signal,
                "engine": EngineType.EXECUTION.value
            }
        
        return {"signal": "NONE", "reason": "No signal from either engine", "engine": "NONE"}
    
    def _handle_range_regime(self, df, market_state: Dict[str, Any]) -> Dict[str, Any]:
        exec_signal = self.exec_engine.generate_signal(df, market_state)
        
        if exec_signal['signal'] != ExecSignal.NONE.value:
            self.active_engine = EngineType.EXECUTION
            return {
                **exec_signal,
                "engine": EngineType.EXECUTION.value
            }
        
        return {"signal": "NONE", "reason": "No execution signal in range", "engine": "NONE"}
    
    def _handle_transition_regime(self, df, market_state: Dict[str, Any]) -> Dict[str, Any]:
        if self.trend_engine.position:
            trend_signal = self.trend_engine.generate_signal(df, market_state)
            if trend_signal['signal'] == TrendSignal.EXIT.value:
                self.active_engine = EngineType.TREND
                return {
                    **trend_signal,
                    "engine": EngineType.TREND.value
                }
        
        if self.exec_engine.position:
            exec_signal = self.exec_engine.generate_signal(df, market_state)
            if exec_signal['signal'] == ExecSignal.EXIT.value:
                self.active_engine = EngineType.EXECUTION
                return {
                    **exec_signal,
                    "engine": EngineType.EXECUTION.value
                }
        
        return {"signal": "NONE", "reason": "Transition regime - no new entries", "engine": "NONE"}
    
    def get_engine_status(self) -> Dict[str, Any]:
        return {
            "trend_position": self.trend_engine.get_position_info(),
            "exec_position": self.exec_engine.get_position_info(),
            "active_engine": self.active_engine.value if self.active_engine else None
        }
