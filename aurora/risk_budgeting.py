from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

class RiskCategory(Enum):
    MARKET = "MARKET"
    LIQUIDITY = "LIQUIDITY"
    OPERATIONAL = "OPERATIONAL"
    MODEL = "MODEL"

@dataclass
class RiskBudget:
    category: RiskCategory
    allocated: float
    used: float
    remaining: float
    limit_pct: float

class RiskBudgetManager:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.budgets: Dict[RiskCategory, RiskBudget] = {}
        self.utilization_history: List[Dict[str, Any]] = []
        
        self._initialize_budgets()
    
    def _initialize_budgets(self):
        limits = {
            RiskCategory.MARKET: 0.03,
            RiskCategory.LIQUIDITY: 0.01,
            RiskCategory.OPERATIONAL: 0.005,
            RiskCategory.MODEL: 0.01
        }
        
        for category, limit_pct in limits.items():
            allocated = self.total_capital * limit_pct
            self.budgets[category] = RiskBudget(
                category=category,
                allocated=allocated,
                used=0.0,
                remaining=allocated,
                limit_pct=limit_pct
            )
    
    def update_capital(self, new_capital: float):
        self.total_capital = new_capital
        for category, budget in self.budgets.items():
            budget.allocated = new_capital * budget.limit_pct
            budget.remaining = budget.allocated - budget.used
    
    def check_budget(self, category: RiskCategory, amount: float) -> Dict[str, Any]:
        budget = self.budgets.get(category)
        if not budget:
            return {'approved': False, 'reason': 'Invalid category'}
        
        if amount > budget.remaining:
            return {
                'approved': False,
                'reason': f'Exceeds {category.value} budget',
                'remaining': budget.remaining
            }
        
        return {
            'approved': True,
            'remaining': budget.remaining - amount
        }
    
    def allocate_risk(self, category: RiskCategory, amount: float) -> Dict[str, Any]:
        check = self.check_budget(category, amount)
        if not check['approved']:
            return check
        
        budget = self.budgets[category]
        budget.used += amount
        budget.remaining -= amount
        
        return {
            'success': True,
            'category': category.value,
            'allocated': amount,
            'remaining': budget.remaining
        }
    
    def release_risk(self, category: RiskCategory, amount: float):
        budget = self.budgets.get(category)
        if budget:
            budget.used = max(0, budget.used - amount)
            budget.remaining = budget.allocated - budget.used
    
    def get_utilization(self) -> Dict[str, float]:
        return {
            cat.value: budget.used / budget.allocated if budget.allocated > 0 else 0
            for cat, budget in self.budgets.items()
        }
    
    def get_budget_summary(self) -> Dict[str, Any]:
        return {
            'total_capital': self.total_capital,
            'total_risk_budget': sum(b.allocated for b in self.budgets.values()),
            'total_used': sum(b.used for b in self.budgets.values()),
            'budgets': {
                cat.value: {
                    'allocated': budget.allocated,
                    'used': budget.used,
                    'remaining': budget.remaining,
                    'utilization': budget.used / budget.allocated if budget.allocated > 0 else 0
                }
                for cat, budget in self.budgets.items()
            }
        }
    
    def reset_daily_budgets(self):
        for budget in self.budgets.values():
            budget.used = 0.0
            budget.remaining = budget.allocated

class PortfolioRiskManager:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.budget_manager = RiskBudgetManager(total_capital)
        
        self.var_confidence = 0.95
        self.var_horizon_days = 1
        
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.correlation_matrix: Dict[str, Dict[str, float]] = {}
        
        self.stress_scenarios = {
            'btc_crash_10': {'BTCUSDT': -0.10},
            'btc_crash_20': {'BTCUSDT': -0.20},
            'liquidity_crisis': {'BTCUSDT': -0.05, 'spread_mult': 3.0},
            'volatility_spike': {'BTCUSDT': -0.03, 'vol_mult': 2.0}
        }
    
    def add_position(self, symbol: str, size: float, entry_price: float, direction: str):
        self.positions[symbol] = {
            'size': size,
            'entry_price': entry_price,
            'direction': direction,
            'current_price': entry_price,
            'unrealized_pnl': 0
        }
    
    def update_position(self, symbol: str, current_price: float):
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos['current_price'] = current_price
            
            if pos['direction'] == 'LONG':
                pos['unrealized_pnl'] = (current_price - pos['entry_price']) * pos['size']
            else:
                pos['unrealized_pnl'] = (pos['entry_price'] - current_price) * pos['size']
    
    def calculate_var(self, returns: List[float], confidence: float = None) -> float:
        if not returns:
            return 0.0
        
        confidence = confidence or self.var_confidence
        sorted_returns = sorted(returns)
        index = int(len(sorted_returns) * (1 - confidence))
        
        return abs(sorted_returns[index]) * self.total_capital
    
    def calculate_portfolio_var(self, historical_returns: Dict[str, List[float]]) -> float:
        if not historical_returns:
            return 0.0
        
        total_var = 0
        for symbol, returns in historical_returns.items():
            if symbol in self.positions:
                var = self.calculate_var(returns)
                total_var += var
        
        return total_var
    
    def run_stress_test(self, scenario_name: str = None) -> Dict[str, Any]:
        results = {}
        
        scenarios = {scenario_name: self.stress_scenarios[scenario_name]} if scenario_name else self.stress_scenarios
        
        for name, scenario in scenarios.items():
            total_loss = 0
            
            for symbol, pos in self.positions.items():
                if symbol in scenario:
                    shock = scenario[symbol]
                    
                    if pos['direction'] == 'LONG':
                        loss = pos['size'] * pos['current_price'] * shock
                    else:
                        loss = pos['size'] * pos['current_price'] * (-shock)
                    
                    total_loss += loss
            
            results[name] = {
                'total_loss': total_loss,
                'loss_pct': total_loss / self.total_capital if self.total_capital > 0 else 0,
                'survives': abs(total_loss) < self.total_capital * 0.5
            }
        
        return results
    
    def check_correlation_risk(self, strategy_returns: Dict[str, List[float]]) -> Dict[str, Any]:
        if len(strategy_returns) < 2:
            return {'correlated': False, 'max_correlation': 0}
        
        strategies = list(strategy_returns.keys())
        max_corr = 0
        
        for i in range(len(strategies)):
            for j in range(i + 1, len(strategies)):
                returns_a = strategy_returns[strategies[i]]
                returns_b = strategy_returns[strategies[j]]
                
                if len(returns_a) == len(returns_b) and len(returns_a) > 1:
                    mean_a = sum(returns_a) / len(returns_a)
                    mean_b = sum(returns_b) / len(returns_b)
                    
                    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b)) / len(returns_a)
                    std_a = (sum((a - mean_a) ** 2 for a in returns_a) / len(returns_a)) ** 0.5
                    std_b = (sum((b - mean_b) ** 2 for b in returns_b) / len(returns_b)) ** 0.5
                    
                    if std_a > 0 and std_b > 0:
                        corr = cov / (std_a * std_b)
                        max_corr = max(max_corr, abs(corr))
        
        return {
            'correlated': max_corr > 0.7,
            'max_correlation': max_corr,
            'warning': 'High correlation detected' if max_corr > 0.7 else None
        }
    
    def get_risk_summary(self) -> Dict[str, Any]:
        total_exposure = sum(
            pos['size'] * pos['current_price'] 
            for pos in self.positions.values()
        )
        
        total_unrealized_pnl = sum(
            pos['unrealized_pnl'] 
            for pos in self.positions.values()
        )
        
        return {
            'total_capital': self.total_capital,
            'total_exposure': total_exposure,
            'exposure_pct': total_exposure / self.total_capital if self.total_capital > 0 else 0,
            'unrealized_pnl': total_unrealized_pnl,
            'positions': len(self.positions),
            'budget_summary': self.budget_manager.get_budget_summary()
        }