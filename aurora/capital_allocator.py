from typing import Dict, Any, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class CapitalBucket(Enum):
    AGGRESSIVE = "AGGRESSIVE"
    TREND = "TREND"
    RESERVE = "RESERVE"
    STABLE = "STABLE"

@dataclass
class BucketAllocation:
    bucket: CapitalBucket
    target_pct: float
    current_pct: float
    capital: float
    max_loss_pct: float
    risk_budget: float

class CapitalAllocator:
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.buckets: Dict[CapitalBucket, BucketAllocation] = {}
        self.allocation_history: List[Dict[str, Any]] = []
        
        self._initialize_buckets()
    
    def _initialize_buckets(self):
        self.buckets = {
            CapitalBucket.AGGRESSIVE: BucketAllocation(
                bucket=CapitalBucket.AGGRESSIVE,
                target_pct=0.20,
                current_pct=0.20,
                capital=self.total_capital * 0.20,
                max_loss_pct=0.05,
                risk_budget=self.total_capital * 0.20 * 0.05
            ),
            CapitalBucket.TREND: BucketAllocation(
                bucket=CapitalBucket.TREND,
                target_pct=0.50,
                current_pct=0.50,
                capital=self.total_capital * 0.50,
                max_loss_pct=0.03,
                risk_budget=self.total_capital * 0.50 * 0.03
            ),
            CapitalBucket.RESERVE: BucketAllocation(
                bucket=CapitalBucket.RESERVE,
                target_pct=0.20,
                current_pct=0.20,
                capital=self.total_capital * 0.20,
                max_loss_pct=0.01,
                risk_budget=self.total_capital * 0.20 * 0.01
            ),
            CapitalBucket.STABLE: BucketAllocation(
                bucket=CapitalBucket.STABLE,
                target_pct=0.10,
                current_pct=0.10,
                capital=self.total_capital * 0.10,
                max_loss_pct=0.005,
                risk_budget=self.total_capital * 0.10 * 0.005
            )
        }
    
    def update_capital(self, new_capital: float):
        self.total_capital = new_capital
        for bucket, alloc in self.buckets.items():
            alloc.capital = new_capital * alloc.current_pct
            alloc.risk_budget = alloc.capital * alloc.max_loss_pct
    
    def get_allocation(self, bucket: CapitalBucket) -> BucketAllocation:
        return self.buckets.get(bucket)
    
    def get_available_capital(self, bucket: CapitalBucket) -> float:
        alloc = self.buckets.get(bucket)
        if alloc:
            return alloc.capital
        return 0.0
    
    def allocate_trade(self, bucket: CapitalBucket, amount: float) -> Dict[str, Any]:
        alloc = self.buckets.get(bucket)
        if not alloc:
            return {'success': False, 'reason': 'Invalid bucket'}
        
        if amount > alloc.capital:
            return {'success': False, 'reason': f'Insufficient capital in {bucket.value}'}
        
        alloc.capital -= amount
        
        return {
            'success': True,
            'bucket': bucket.value,
            'allocated': amount,
            'remaining': alloc.capital
        }
    
    def release_capital(self, bucket: CapitalBucket, amount: float, pnl: float = 0):
        alloc = self.buckets.get(bucket)
        if alloc:
            alloc.capital += amount + pnl
    
    def rebalance(self, performance: Dict[str, float] = None):
        if performance:
            self._dynamic_rebalance(performance)
        else:
            self._equal_rebalance()
    
    def _equal_rebalance(self):
        for bucket, alloc in self.buckets.items():
            alloc.current_pct = alloc.target_pct
            alloc.capital = self.total_capital * alloc.target_pct
            alloc.risk_budget = alloc.capital * alloc.max_loss_pct
    
    def _dynamic_rebalance(self, performance: Dict[str, float]):
        total_score = 0
        scores = {}
        
        for bucket, alloc in self.buckets.items():
            perf = performance.get(bucket.value, 0)
            score = max(0.1, 1 + perf)
            scores[bucket] = score
            total_score += score
        
        for bucket, alloc in self.buckets.items():
            new_pct = scores[bucket] / total_score
            alloc.current_pct = new_pct
            alloc.capital = self.total_capital * new_pct
            alloc.risk_budget = alloc.capital * alloc.max_loss_pct
        
        self.allocation_history.append({
            'timestamp': datetime.now().isoformat(),
            'performance': performance,
            'new_allocation': {b.value: a.current_pct for b, a in self.buckets.items()}
        })
    
    def get_allocation_summary(self) -> Dict[str, Any]:
        return {
            'total_capital': self.total_capital,
            'buckets': {
                bucket.value: {
                    'target_pct': alloc.target_pct,
                    'current_pct': alloc.current_pct,
                    'capital': alloc.capital,
                    'max_loss_pct': alloc.max_loss_pct,
                    'risk_budget': alloc.risk_budget
                }
                for bucket, alloc in self.buckets.items()
            }
        }