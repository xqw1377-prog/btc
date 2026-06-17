import pandas as pd
import numpy as np
from datetime import datetime
from .market_state_engine import MarketStateEngine
from .trend_engine import TrendEngine
from .execution_engine import ExecutionEngine
from .position_engine import PositionEngine
from .risk_engine import RiskEngine
from .types import MarketData, Signal

class Backtester:
    def __init__(self):
        self.market_state_engine = MarketStateEngine()
        self.trend_engine = TrendEngine()
        self.execution_engine = ExecutionEngine()
        self.position_engine = PositionEngine()
        self.risk_engine = RiskEngine()
        self.prices = []
        self.results = []
    
    def load_data(self, file_path: str) -> pd.DataFrame:
        df = pd.read_csv(file_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    
    def run_backtest(self, data: pd.DataFrame):
        initial_balance = 10000.0
        balance = initial_balance
        equity_curve = []
        positions = []
        
        for idx, row in data.iterrows():
            market_data = MarketData(
                timestamp=row['timestamp'],
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row.get('volume', 0.0),
                vwap=row.get('vwap', row['close']),
                oi=row.get('oi', 0.0),
                funding_rate=row.get('funding_rate', 0.0)
            )
            
            self.market_state_engine.add_data(market_data)
            self.prices.append(market_data.close)
            
            if len(self.prices) < 100:
                equity_curve.append(balance)
                continue
            
            state = self.market_state_engine.get_state()
            current_price = market_data.close
            
            trend_signal = self.trend_engine.generate_signal(state, current_price)
            exec_signal = self.execution_engine.generate_signal(state, market_data, self.prices)
            
            signal = self.route_signal(trend_signal, exec_signal)
            
            if signal.type != "NONE":
                if self.risk_engine.validate_signal(signal, state, self.position_engine.get_total_exposure()):
                    size = self.get_position_size(signal, balance, current_price)
                    
                    if signal.type == "ENTER":
                        positions.append({
                            'timestamp': row['timestamp'],
                            'direction': signal.direction,
                            'size': size,
                            'entry_price': current_price,
                            'status': 'OPEN'
                        })
                    
                    elif signal.type == "EXIT" and positions:
                        pos = positions[-1]
                        if pos['status'] == 'OPEN' and pos['direction'] == signal.direction:
                            pnl = (current_price - pos['entry_price']) * pos['size']
                            balance += pnl
                            pos['status'] = 'CLOSED'
                            pos['exit_price'] = current_price
                            pos['pnl'] = pnl
            
            equity_curve.append(balance)
        
        return self.generate_report(equity_curve, initial_balance, positions)
    
    def route_signal(self, trend_signal: Signal, exec_signal: Signal) -> Signal:
        if trend_signal.type == "EXIT":
            return trend_signal
        
        if trend_signal.type in ["ENTER", "ADD"]:
            if trend_signal.confidence > 0.6:
                return trend_signal
        
        if exec_signal.type == "ENTER" and not self.trend_engine.position:
            return exec_signal
        
        return Signal(type="NONE", direction="NONE", confidence=0.0, reason="No signal")
    
    def get_position_size(self, signal: Signal, balance: float, price: float) -> float:
        risk_multiplier = self.risk_engine.get_risk_multiplier(self.market_state_engine.get_state())
        
        if signal.type == "ENTER":
            return (balance * 0.4 * risk_multiplier) / price
        elif signal.type == "ADD":
            return (balance * 0.3 * risk_multiplier) / price
        return 0.0
    
    def generate_report(self, equity_curve: list, initial_balance: float, positions: list) -> dict:
        equity_array = np.array(equity_curve)
        returns = equity_array[1:] / equity_array[:-1] - 1
        
        total_return = (equity_array[-1] - initial_balance) / initial_balance * 100
        max_drawdown = self.calculate_max_drawdown(equity_array)
        sharpe_ratio = self.calculate_sharpe_ratio(returns)
        win_rate = self.calculate_win_rate(positions)
        
        return {
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'final_balance': equity_array[-1],
            'trades': len([p for p in positions if p['status'] == 'CLOSED']),
            'equity_curve': equity_curve
        }
    
    def calculate_max_drawdown(self, equity: np.ndarray) -> float:
        peak = equity[0]
        max_dd = 0.0
        
        for value in equity:
            peak = max(peak, value)
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)
        
        return max_dd * 100
    
    def calculate_sharpe_ratio(self, returns: np.ndarray) -> float:
        if len(returns) == 0:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        return np.sqrt(252 * 24) * mean_return / std_return
    
    def calculate_win_rate(self, positions: list) -> float:
        closed_positions = [p for p in positions if p['status'] == 'CLOSED']
        
        if len(closed_positions) == 0:
            return 0.0
        
        winning_trades = sum(1 for p in closed_positions if p['pnl'] > 0)
        return winning_trades / len(closed_positions) * 100
