from typing import Dict, Any, Optional
from datetime import datetime

class PortfolioManager:
    def __init__(self, initial_capital: float = 10000.0):
        self.total_capital = initial_capital
        self.trend_allocation = 0.6
        self.execution_allocation = 0.4
        
        self.trend_balance = initial_capital * self.trend_allocation
        self.execution_balance = initial_capital * self.execution_allocation
        
        self.trend_positions = []
        self.execution_positions = []
        
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        
        self.last_rebalance = datetime.now()
    
    def allocate_capital(self, engine_type: str, amount: float) -> bool:
        if engine_type == "TREND":
            if amount <= self.trend_balance:
                self.trend_balance -= amount
                return True
            return False
        
        elif engine_type == "EXECUTION":
            if amount <= self.execution_balance:
                self.execution_balance -= amount
                return True
            return False
        
        return False
    
    def deallocate_capital(self, engine_type: str, amount: float):
        if engine_type == "TREND":
            self.trend_balance += amount
        
        elif engine_type == "EXECUTION":
            self.execution_balance += amount
    
    def add_position(self, engine_type: str, position: Dict[str, Any]):
        if engine_type == "TREND":
            self.trend_positions.append(position)
        else:
            self.execution_positions.append(position)
    
    def close_position(self, engine_type: str, position_id: str) -> Optional[Dict[str, Any]]:
        positions = self.trend_positions if engine_type == "TREND" else self.execution_positions
        
        for i, pos in enumerate(positions):
            if pos.get('id') == position_id:
                closed = positions.pop(i)
                self.deallocate_capital(engine_type, closed['entry_price'] * closed['qty'])
                return closed
        
        return None
    
    def update_positions(self, current_price: float):
        for pos in self.trend_positions:
            if pos['side'] == 'LONG':
                pos['unrealized_pnl'] = (current_price - pos['entry_price']) * pos['qty']
            else:
                pos['unrealized_pnl'] = (pos['entry_price'] - current_price) * pos['qty']
        
        for pos in self.execution_positions:
            if pos['side'] == 'LONG':
                pos['unrealized_pnl'] = (current_price - pos['entry_price']) * pos['qty']
            else:
                pos['unrealized_pnl'] = (pos['entry_price'] - current_price) * pos['qty']
    
    def get_total_equity(self, current_price: float) -> float:
        self.update_positions(current_price)
        
        trend_pnl = sum(pos.get('unrealized_pnl', 0) for pos in self.trend_positions)
        exec_pnl = sum(pos.get('unrealized_pnl', 0) for pos in self.execution_positions)
        
        return self.trend_balance + self.execution_balance + trend_pnl + exec_pnl
    
    def get_engine_balance(self, engine_type: str) -> float:
        if engine_type == "TREND":
            pnl = sum(pos.get('unrealized_pnl', 0) for pos in self.trend_positions)
            return self.trend_balance + pnl
        
        pnl = sum(pos.get('unrealized_pnl', 0) for pos in self.execution_positions)
        return self.execution_balance + pnl
    
    def rebalance(self):
        current_equity = self.get_total_equity(0)
        
        target_trend = current_equity * self.trend_allocation
        target_exec = current_equity * self.execution_allocation
        
        trend_diff = target_trend - self.get_engine_balance("TREND")
        exec_diff = target_exec - self.get_engine_balance("EXECUTION")
        
        self.trend_balance += trend_diff
        self.execution_balance += exec_diff
        
        self.last_rebalance = datetime.now()
    
    def get_summary(self, current_price: float) -> Dict[str, Any]:
        return {
            'total_capital': round(self.total_capital, 2),
            'trend_balance': round(self.trend_balance, 2),
            'execution_balance': round(self.execution_balance, 2),
            'total_equity': round(self.get_total_equity(current_price), 2),
            'trend_positions': len(self.trend_positions),
            'execution_positions': len(self.execution_positions),
            'trend_allocation': self.trend_allocation,
            'execution_allocation': self.execution_allocation,
            'daily_pnl': round(self.daily_pnl, 2),
            'total_pnl': round(self.total_pnl, 2)
        }
