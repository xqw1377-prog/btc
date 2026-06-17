import json
import os
from typing import Dict, Any, List
from datetime import datetime
from collections import deque

class TradeLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        self.trade_log_file = os.path.join(log_dir, "trades.jsonl")
        self.system_log_file = os.path.join(log_dir, "system.jsonl")
        self.error_log_file = os.path.join(log_dir, "errors.jsonl")
        
        self.recent_trades: deque = deque(maxlen=1000)
        self.recent_events: deque = deque(maxlen=5000)
    
    def log_trade(self, trade_data: Dict[str, Any]):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'TRADE',
            **trade_data
        }
        
        self.recent_trades.append(log_entry)
        self._write_to_file(self.trade_log_file, log_entry)
    
    def log_signal(self, signal_data: Dict[str, Any]):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'SIGNAL',
            **signal_data
        }
        
        self.recent_events.append(log_entry)
        self._write_to_file(self.system_log_file, log_entry)
    
    def log_risk_event(self, risk_data: Dict[str, Any]):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'RISK',
            **risk_data
        }
        
        self.recent_events.append(log_entry)
        self._write_to_file(self.system_log_file, log_entry)
    
    def log_error(self, error_data: Dict[str, Any]):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'ERROR',
            **error_data
        }
        
        self._write_to_file(self.error_log_file, log_entry)
    
    def log_system_event(self, event_type: str, data: Dict[str, Any]):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            **data
        }
        
        self.recent_events.append(log_entry)
        self._write_to_file(self.system_log_file, log_entry)
    
    def _write_to_file(self, file_path: str, data: Dict[str, Any]):
        try:
            with open(file_path, 'a') as f:
                f.write(json.dumps(data) + '\n')
        except Exception as e:
            print(f"Log write error: {e}")
    
    def get_recent_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.recent_trades)[-limit:]
    
    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.recent_events)[-limit:]

class PerformanceMonitor:
    def __init__(self):
        self.equity_history: deque = deque(maxlen=86400)
        self.pnl_history: deque = deque(maxlen=86400)
        self.latency_history: deque = deque(maxlen=1000)
        
        self.metrics = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'current_drawdown': 0.0,
            'peak_equity': 0.0,
            'current_equity': 0.0,
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'sharpe_ratio': 0.0,
            'avg_latency_ms': 0.0,
            'order_fill_rate': 0.0
        }
        
        self.winning_pnl = 0.0
        self.losing_pnl = 0.0
        self.latency_sum = 0.0
        self.latency_count = 0
    
    def update_equity(self, equity: float, timestamp: float = None):
        if timestamp is None:
            timestamp = datetime.now().timestamp()
        
        self.equity_history.append({
            'equity': equity,
            'timestamp': timestamp
        })
        
        self.metrics['current_equity'] = equity
        
        if equity > self.metrics['peak_equity']:
            self.metrics['peak_equity'] = equity
        
        if self.metrics['peak_equity'] > 0:
            drawdown = (self.metrics['peak_equity'] - equity) / self.metrics['peak_equity']
            self.metrics['current_drawdown'] = drawdown
            if drawdown > self.metrics['max_drawdown']:
                self.metrics['max_drawdown'] = drawdown
    
    def record_trade(self, pnl: float, is_win: bool):
        self.metrics['total_trades'] += 1
        self.metrics['total_pnl'] += pnl
        
        if is_win:
            self.metrics['winning_trades'] += 1
            self.winning_pnl += pnl
        else:
            self.metrics['losing_trades'] += 1
            self.losing_pnl += abs(pnl)
        
        total = self.metrics['total_trades']
        if total > 0:
            self.metrics['win_rate'] = self.metrics['winning_trades'] / total
        
        if self.metrics['winning_trades'] > 0:
            self.metrics['avg_win'] = self.winning_pnl / self.metrics['winning_trades']
        
        if self.metrics['losing_trades'] > 0:
            self.metrics['avg_loss'] = self.losing_pnl / self.metrics['losing_trades']
        
        if self.losing_pnl > 0:
            self.metrics['profit_factor'] = self.winning_pnl / self.losing_pnl
        
        self.pnl_history.append({
            'pnl': pnl,
            'timestamp': datetime.now().timestamp()
        })
    
    def record_latency(self, latency_ms: float):
        self.latency_history.append(latency_ms)
        self.latency_sum += latency_ms
        self.latency_count += 1
        self.metrics['avg_latency_ms'] = self.latency_sum / self.latency_count
    
    def record_order_fill(self, filled: bool):
        pass
    
    def calculate_sharpe(self, risk_free_rate: float = 0.02) -> float:
        if len(self.pnl_history) < 2:
            return 0.0
        
        returns = [p['pnl'] for p in self.pnl_history]
        
        mean_return = sum(returns) / len(returns)
        
        if len(returns) > 1:
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            std_return = variance ** 0.5
            
            if std_return > 0:
                annualized_return = mean_return * 252
                annualized_std = std_return * (252 ** 0.5)
                sharpe = (annualized_return - risk_free_rate) / annualized_std
                self.metrics['sharpe_ratio'] = round(sharpe, 2)
                return sharpe
        
        return 0.0
    
    def get_metrics(self) -> Dict[str, Any]:
        self.calculate_sharpe()
        return self.metrics.copy()
    
    def get_equity_curve(self, limit: int = 3600) -> List[Dict[str, Any]]:
        return list(self.equity_history)[-limit:]
    
    def get_pnl_curve(self, limit: int = 3600) -> List[Dict[str, Any]]:
        return list(self.pnl_history)[-limit:]

class MonitoringDashboard:
    def __init__(self, logger: TradeLogger, monitor: PerformanceMonitor):
        self.logger = logger
        self.monitor = monitor
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        metrics = self.monitor.get_metrics()
        recent_trades = self.logger.get_recent_trades(10)
        
        return {
            'performance': metrics,
            'recent_trades': recent_trades,
            'equity_curve': self.monitor.get_equity_curve(100),
            'pnl_curve': self.monitor.get_pnl_curve(100)
        }
    
    def print_summary(self):
        metrics = self.monitor.get_metrics()
        
        print("\n" + "=" * 60)
        print("AURORA MONITORING DASHBOARD")
        print("=" * 60)
        print(f"Equity: ${metrics['current_equity']:.2f}")
        print(f"Peak Equity: ${metrics['peak_equity']:.2f}")
        print(f"Drawdown: {metrics['current_drawdown']:.2%} (Max: {metrics['max_drawdown']:.2%})")
        print(f"Total PnL: ${metrics['total_pnl']:.2f}")
        print(f"Trades: {metrics['total_trades']} (Win Rate: {metrics['win_rate']:.1%})")
        print(f"Avg Win: ${metrics['avg_win']:.2f} | Avg Loss: ${metrics['avg_loss']:.2f}")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"Avg Latency: {metrics['avg_latency_ms']:.1f}ms")
        print("=" * 60)