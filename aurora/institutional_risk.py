from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import numpy as np

@dataclass
class VARResult:
    confidence: float
    horizon_days: int
    var_amount: float
    var_pct: float
    method: str

class VARCalculator:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.confidence_levels = [0.90, 0.95, 0.99]
    
    def calculate_historical_var(self, returns: List[float], confidence: float = 0.95, horizon_days: int = 1) -> VARResult:
        if not returns:
            return VARResult(confidence, horizon_days, 0, 0, 'historical')
        
        sorted_returns = sorted(returns)
        index = int(len(sorted_returns) * (1 - confidence))
        var_daily = abs(sorted_returns[index])
        
        var_horizon = var_daily * (horizon_days ** 0.5)
        var_amount = var_horizon * self.total_capital
        
        return VARResult(
            confidence=confidence,
            horizon_days=horizon_days,
            var_amount=var_amount,
            var_pct=var_horizon,
            method='historical'
        )
    
    def calculate_parametric_var(self, returns: List[float], confidence: float = 0.95, horizon_days: int = 1) -> VARResult:
        if not returns:
            return VARResult(confidence, horizon_days, 0, 0, 'parametric')
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        z_scores = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
        z = z_scores.get(confidence, 1.645)
        
        var_daily = abs(mean_return - z * std_return)
        var_horizon = var_daily * (horizon_days ** 0.5)
        var_amount = var_horizon * self.total_capital
        
        return VARResult(
            confidence=confidence,
            horizon_days=horizon_days,
            var_amount=var_amount,
            var_pct=var_horizon,
            method='parametric'
        )
    
    def calculate_monte_carlo_var(self, returns: List[float], confidence: float = 0.95, horizon_days: int = 1, simulations: int = 10000) -> VARResult:
        if not returns:
            return VARResult(confidence, horizon_days, 0, 0, 'monte_carlo')
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        simulated_returns = np.random.normal(mean_return, std_return, (simulations, horizon_days))
        portfolio_returns = np.sum(simulated_returns, axis=1)
        
        var_pct = abs(np.percentile(portfolio_returns, (1 - confidence) * 100))
        var_amount = var_pct * self.total_capital
        
        return VARResult(
            confidence=confidence,
            horizon_days=horizon_days,
            var_amount=var_amount,
            var_pct=var_pct,
            method='monte_carlo'
        )
    
    def calculate_all_var(self, returns: List[float], confidence: float = 0.95, horizon_days: int = 1) -> Dict[str, VARResult]:
        return {
            'historical': self.calculate_historical_var(returns, confidence, horizon_days),
            'parametric': self.calculate_parametric_var(returns, confidence, horizon_days),
            'monte_carlo': self.calculate_monte_carlo_var(returns, confidence, horizon_days)
        }
    
    def get_var_summary(self, returns: List[float]) -> Dict[str, Any]:
        results = {}
        
        for confidence in self.confidence_levels:
            var = self.calculate_historical_var(returns, confidence)
            results[f'{int(confidence*100)}%'] = {
                'var_amount': var.var_amount,
                'var_pct': var.var_pct
            }
        
        return {
            'total_capital': self.total_capital,
            'var_by_confidence': results
        }

class StressTestEngine:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        
        self.scenarios = {
            'btc_flash_crash': {
                'name': 'BTC Flash Crash (-10%)',
                'shocks': {'BTCUSDT': -0.10},
                'description': 'Sudden 10% drop in BTC price'
            },
            'btc_major_crash': {
                'name': 'BTC Major Crash (-20%)',
                'shocks': {'BTCUSDT': -0.20},
                'description': 'Major market crash with 20% drop'
            },
            'liquidity_crisis': {
                'name': 'Liquidity Crisis',
                'shocks': {'BTCUSDT': -0.05, 'spread_mult': 3.0, 'volume_mult': 0.3},
                'description': 'Liquidity dries up, spreads widen'
            },
            'volatility_spike': {
                'name': 'Volatility Spike',
                'shocks': {'BTCUSDT': -0.03, 'vol_mult': 2.5},
                'description': 'Sudden spike in volatility'
            },
            'funding_crisis': {
                'name': 'Funding Rate Crisis',
                'shocks': {'BTCUSDT': -0.02, 'funding_rate': 0.003},
                'description': 'Extreme funding rates'
            },
            'exchange_outage': {
                'name': 'Exchange Outage',
                'shocks': {'duration_hours': 2, 'price_gap': -0.05},
                'description': 'Exchange goes down for 2 hours'
            }
        }
    
    def run_scenario(self, scenario_name: str, positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        scenario = self.scenarios.get(scenario_name)
        if not scenario:
            return {'error': f'Unknown scenario: {scenario_name}'}
        
        total_loss = 0
        position_losses = {}
        
        for symbol, pos in positions.items():
            if symbol in scenario['shocks']:
                shock = scenario['shocks'][symbol]
                
                if pos['direction'] == 'LONG':
                    loss = pos['size'] * pos['current_price'] * shock
                else:
                    loss = pos['size'] * pos['current_price'] * (-shock)
                
                position_losses[symbol] = loss
                total_loss += loss
        
        return {
            'scenario': scenario['name'],
            'description': scenario['description'],
            'total_loss': total_loss,
            'loss_pct': total_loss / self.total_capital if self.total_capital > 0 else 0,
            'position_losses': position_losses,
            'survives': abs(total_loss) < self.total_capital * 0.5,
            'remaining_capital': self.total_capital + total_loss
        }
    
    def run_all_scenarios(self, positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        results = {}
        
        for scenario_name in self.scenarios:
            results[scenario_name] = self.run_scenario(scenario_name, positions)
        
        worst_case = min(results.values(), key=lambda x: x['total_loss'])
        
        return {
            'scenarios': results,
            'worst_case': {
                'scenario': worst_case['scenario'],
                'loss': worst_case['total_loss'],
                'loss_pct': worst_case['loss_pct']
            },
            'all_survive': all(r['survives'] for r in results.values())
        }
    
    def add_custom_scenario(self, name: str, shocks: Dict[str, Any], description: str = ''):
        self.scenarios[name] = {
            'name': name,
            'shocks': shocks,
            'description': description
        }

class InstitutionalRiskManager:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.var_calculator = VARCalculator(total_capital)
        self.stress_engine = StressTestEngine(total_capital)
        
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.historical_returns: List[float] = []
        
        self.risk_limits = {
            'max_var_95_pct': 0.05,
            'max_stress_loss_pct': 0.15,
            'max_single_position_pct': 0.10,
            'max_correlation': 0.7
        }
    
    def update_capital(self, new_capital: float):
        self.total_capital = new_capital
        self.var_calculator.total_capital = new_capital
        self.stress_engine.total_capital = new_capital
    
    def add_position(self, symbol: str, size: float, entry_price: float, direction: str):
        self.positions[symbol] = {
            'size': size,
            'entry_price': entry_price,
            'direction': direction,
            'current_price': entry_price
        }
    
    def update_position_price(self, symbol: str, current_price: float):
        if symbol in self.positions:
            self.positions[symbol]['current_price'] = current_price
    
    def add_return(self, ret: float):
        self.historical_returns.append(ret)
        if len(self.historical_returns) > 1000:
            self.historical_returns = self.historical_returns[-1000:]
    
    def calculate_var(self, confidence: float = 0.95) -> VARResult:
        return self.var_calculator.calculate_historical_var(self.historical_returns, confidence)
    
    def run_stress_test(self) -> Dict[str, Any]:
        return self.stress_engine.run_all_scenarios(self.positions)
    
    def check_risk_limits(self) -> Dict[str, Any]:
        violations = []
        
        var = self.calculate_var(0.95)
        if var.var_pct > self.risk_limits['max_var_95_pct']:
            violations.append({
                'limit': 'max_var_95_pct',
                'current': var.var_pct,
                'limit_value': self.risk_limits['max_var_95_pct']
            })
        
        stress_results = self.run_stress_test()
        worst_loss_pct = abs(stress_results['worst_case']['loss_pct'])
        if worst_loss_pct > self.risk_limits['max_stress_loss_pct']:
            violations.append({
                'limit': 'max_stress_loss_pct',
                'current': worst_loss_pct,
                'limit_value': self.risk_limits['max_stress_loss_pct']
            })
        
        for symbol, pos in self.positions.items():
            position_value = pos['size'] * pos['current_price']
            position_pct = position_value / self.total_capital
            if position_pct > self.risk_limits['max_single_position_pct']:
                violations.append({
                    'limit': 'max_single_position_pct',
                    'symbol': symbol,
                    'current': position_pct,
                    'limit_value': self.risk_limits['max_single_position_pct']
                })
        
        return {
            'compliant': len(violations) == 0,
            'violations': violations
        }
    
    def get_risk_report(self) -> Dict[str, Any]:
        var_results = self.var_calculator.get_var_summary(self.historical_returns)
        stress_results = self.run_stress_test()
        limit_check = self.check_risk_limits()
        
        return {
            'total_capital': self.total_capital,
            'positions': len(self.positions),
            'var_analysis': var_results,
            'stress_test': {
                'worst_case': stress_results['worst_case'],
                'all_survive': stress_results['all_survive']
            },
            'limit_check': limit_check,
            'generated_at': datetime.now().isoformat()
        }