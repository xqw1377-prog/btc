from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class StrategyType(Enum):
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    MOMENTUM = "MOMENTUM"

@dataclass
class StrategyAllocation:
    strategy_type: StrategyType
    weight: float
    capital: float
    risk_budget: float
    sharpe: float = 0.0
    win_rate: float = 0.0
    drawdown: float = 0.0

class PortfolioMixer:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.strategies: Dict[StrategyType, StrategyAllocation] = {}
        self.signal_history: List[Dict[str, Any]] = []
        
        self._initialize_strategies()
    
    def _initialize_strategies(self):
        allocations = {
            StrategyType.TREND: {'weight': 0.50, 'risk': 0.03},
            StrategyType.MEAN_REVERSION: {'weight': 0.20, 'risk': 0.02},
            StrategyType.BREAKOUT: {'weight': 0.20, 'risk': 0.025},
            StrategyType.MOMENTUM: {'weight': 0.10, 'risk': 0.015}
        }
        
        for strategy, params in allocations.items():
            self.strategies[strategy] = StrategyAllocation(
                strategy_type=strategy,
                weight=params['weight'],
                capital=self.total_capital * params['weight'],
                risk_budget=self.total_capital * params['weight'] * params['risk']
            )
    
    def update_capital(self, new_capital: float):
        self.total_capital = new_capital
        for strategy in self.strategies.values():
            strategy.capital = new_capital * strategy.weight
            strategy.risk_budget = strategy.capital * 0.03
    
    def update_performance(self, strategy: StrategyType, sharpe: float, win_rate: float, drawdown: float):
        if strategy in self.strategies:
            alloc = self.strategies[strategy]
            alloc.sharpe = sharpe
            alloc.win_rate = win_rate
            alloc.drawdown = drawdown
    
    def adjust_weights(self):
        scores = {}
        total_score = 0
        
        for strategy, alloc in self.strategies.items():
            score = 1.0
            
            if alloc.sharpe > 0:
                score *= (1 + alloc.sharpe * 0.5)
            
            score *= alloc.win_rate
            
            if alloc.drawdown > 0:
                score *= (1 - alloc.drawdown * 2)
            
            score = max(0.1, score)
            scores[strategy] = score
            total_score += score
        
        for strategy, alloc in self.strategies.items():
            alloc.weight = scores[strategy] / total_score
            alloc.capital = self.total_capital * alloc.weight
            alloc.risk_budget = alloc.capital * 0.03
    
    def get_combined_signal(self, signals: Dict[StrategyType, Dict[str, Any]]) -> Dict[str, Any]:
        combined_direction = 0
        combined_confidence = 0
        total_weight = 0
        
        for strategy, signal in signals.items():
            if strategy in self.strategies:
                alloc = self.strategies[strategy]
                
                direction = 1 if signal.get('direction') == 'LONG' else -1
                confidence = signal.get('confidence', 0.5)
                
                combined_direction += direction * confidence * alloc.weight
                combined_confidence += confidence * alloc.weight
                total_weight += alloc.weight
        
        if total_weight > 0:
            combined_confidence /= total_weight
        
        if combined_direction > 0.1:
            final_direction = 'LONG'
        elif combined_direction < -0.1:
            final_direction = 'SHORT'
        else:
            final_direction = 'NEUTRAL'
        
        result = {
            'direction': final_direction,
            'confidence': combined_confidence,
            'strength': abs(combined_direction),
            'strategies': {
                s.value: {
                    'direction': sig.get('direction'),
                    'confidence': sig.get('confidence'),
                    'weight': self.strategies[s].weight
                }
                for s, sig in signals.items() if s in self.strategies
            }
        }
        
        self.signal_history.append({
            'timestamp': datetime.now().isoformat(),
            'signals': signals,
            'combined': result
        })
        
        return result
    
    def get_position_size(self, strategy: StrategyType, risk_multiplier: float = 1.0) -> Dict[str, Any]:
        alloc = self.strategies.get(strategy)
        if not alloc:
            return {'size': 0, 'reason': 'Unknown strategy'}
        
        size = alloc.capital * risk_multiplier
        
        return {
            'strategy': strategy.value,
            'capital': alloc.capital,
            'size': size,
            'risk_budget': alloc.risk_budget,
            'weight': alloc.weight
        }
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        return {
            'total_capital': self.total_capital,
            'strategies': {
                strategy.value: {
                    'weight': alloc.weight,
                    'capital': alloc.capital,
                    'risk_budget': alloc.risk_budget,
                    'sharpe': alloc.sharpe,
                    'win_rate': alloc.win_rate,
                    'drawdown': alloc.drawdown
                }
                for strategy, alloc in self.strategies.items()
            },
            'total_risk_budget': sum(a.risk_budget for a in self.strategies.values())
        }

class BTCMultiStrategy:
    def __init__(self, capital: float):
        self.mixer = PortfolioMixer(capital)
        self.capital = capital
    
    def generate_trend_signal(self, features: Dict[str, Any]) -> Dict[str, Any]:
        ema20 = features.get('ema20', 0)
        ema60 = features.get('ema60', 0)
        adx = features.get('adx', 0)
        
        if adx > 25 and ema20 > ema60:
            return {'direction': 'LONG', 'confidence': min(adx / 50, 1.0)}
        elif adx > 25 and ema20 < ema60:
            return {'direction': 'SHORT', 'confidence': min(adx / 50, 1.0)}
        
        return {'direction': 'NEUTRAL', 'confidence': 0.3}
    
    def generate_mean_reversion_signal(self, features: Dict[str, Any]) -> Dict[str, Any]:
        close = features.get('close', 0)
        vwap = features.get('vwap', 0)
        rsi = features.get('rsi', 50)
        
        if close and vwap:
            deviation = (close - vwap) / vwap
            
            if deviation < -0.02 and rsi < 30:
                return {'direction': 'LONG', 'confidence': min(abs(deviation) * 10, 1.0)}
            elif deviation > 0.02 and rsi > 70:
                return {'direction': 'SHORT', 'confidence': min(abs(deviation) * 10, 1.0)}
        
        return {'direction': 'NEUTRAL', 'confidence': 0.3}
    
    def generate_breakout_signal(self, features: Dict[str, Any], df: Any = None) -> Dict[str, Any]:
        atr = features.get('atr', 0)
        close = features.get('close', 0)
        
        if df is not None and len(df) >= 20:
            high_20 = df['high'].tail(20).max()
            low_20 = df['low'].tail(20).min()
            
            if close > high_20 * 0.999:
                return {'direction': 'LONG', 'confidence': 0.8}
            elif close < low_20 * 1.001:
                return {'direction': 'SHORT', 'confidence': 0.8}
        
        return {'direction': 'NEUTRAL', 'confidence': 0.3}
    
    def generate_momentum_signal(self, features: Dict[str, Any]) -> Dict[str, Any]:
        momentum = features.get('momentum', 0)
        momentum_pct = features.get('momentum_pct', 0)
        
        if momentum_pct > 0.01:
            return {'direction': 'LONG', 'confidence': min(momentum_pct * 10, 1.0)}
        elif momentum_pct < -0.01:
            return {'direction': 'SHORT', 'confidence': min(abs(momentum_pct) * 10, 1.0)}
        
        return {'direction': 'NEUTRAL', 'confidence': 0.3}
    
    def generate_combined_signal(self, features: Dict[str, Any], df: Any = None) -> Dict[str, Any]:
        signals = {
            StrategyType.TREND: self.generate_trend_signal(features),
            StrategyType.MEAN_REVERSION: self.generate_mean_reversion_signal(features),
            StrategyType.BREAKOUT: self.generate_breakout_signal(features, df),
            StrategyType.MOMENTUM: self.generate_momentum_signal(features)
        }
        
        return self.mixer.get_combined_signal(signals)
    
    def get_position_allocation(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        direction = signal.get('direction', 'NEUTRAL')
        confidence = signal.get('confidence', 0)
        
        if direction == 'NEUTRAL':
            return {'size': 0, 'reason': 'Neutral signal'}
        
        total_size = 0
        allocations = {}
        
        for strategy_type in StrategyType:
            strategy_signal = signal.get('strategies', {}).get(strategy_type.value, {})
            
            if strategy_signal.get('direction') == direction:
                pos = self.mixer.get_position_size(strategy_type, confidence)
                total_size += pos['size']
                allocations[strategy_type.value] = pos
        
        return {
            'direction': direction,
            'total_size': total_size,
            'allocations': allocations
        }