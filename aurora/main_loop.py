import asyncio
from datetime import datetime
from .market_state_engine import MarketStateEngine
from .trend_engine import TrendEngine
from .execution_engine import ExecutionEngine
from .position_engine import PositionEngine
from .risk_engine import RiskEngine
from .binance_client import BinanceClient
from .execution_state_machine import ExecutionStateMachine
from .types import MarketData, Signal

class MainLoop:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.market_state_engine = MarketStateEngine()
        self.trend_engine = TrendEngine()
        self.execution_engine = ExecutionEngine()
        self.position_engine = PositionEngine()
        self.risk_engine = RiskEngine()
        self.binance_client = BinanceClient(api_key, api_secret, testnet)
        self.execution_sm = ExecutionStateMachine(self.binance_client)
        self.running = False
        self.prices = []
    
    async def initialize(self):
        historical_data = self.binance_client.get_historical_data('BTC/USDT', '1m', limit=150)
        for data in historical_data:
            self.market_state_engine.add_data(data)
            self.prices.append(data.close)
        
        await self.binance_client.connect_ws()
    
    async def process_market_data(self):
        while self.running:
            message = await self.binance_client.receive()
            if message:
                stream = message.get('stream', '')
                if 'kline' in stream:
                    market_data = self.binance_client.parse_kline(message)
                    if market_data:
                        market_data.oi = self.binance_client.get_open_interest('BTCUSDT')
                        market_data.funding_rate = self.binance_client.get_funding_rate('BTCUSDT')
                        market_data.vwap = market_data.close
                        
                        self.market_state_engine.add_data(market_data)
                        self.prices.append(market_data.close)
                        if len(self.prices) > 500:
                            self.prices = self.prices[-500:]
                        
                        await self.run_strategy(market_data)
            
            await asyncio.sleep(0.1)
    
    async def run_strategy(self, market_data: MarketData):
        state = self.market_state_engine.get_state()
        current_price = market_data.close
        
        trend_signal = self.trend_engine.generate_signal(state, current_price)
        exec_signal = self.execution_engine.generate_signal(state, market_data, self.prices)
        
        signal = self.route_signal(trend_signal, exec_signal)
        
        if signal.type != "NONE":
            if self.risk_engine.validate_signal(signal, state, self.position_engine.get_total_exposure()):
                order = self.position_engine.create_order(signal, current_price)
                if order:
                    self.execution_sm.send_order(order)
                    
                    while not self.execution_sm.is_complete():
                        self.execution_sm.execute()
                        await asyncio.sleep(0.5)
                    
                    result = self.execution_sm.get_result()
                    if result:
                        self.position_engine.update_position_from_order(result)
                        if signal.type == "EXIT":
                            self.risk_engine.update_daily_pnl(result.filled_size * (result.filled_price - self.position_engine.get_open_position(signal.direction).entry_price))
        
        self.position_engine.update_pnl(current_price)
    
    def route_signal(self, trend_signal: Signal, exec_signal: Signal) -> Signal:
        if trend_signal.type == "EXIT":
            return trend_signal
        
        if trend_signal.type in ["ENTER", "ADD"]:
            if trend_signal.confidence > 0.6:
                return trend_signal
        
        if exec_signal.type == "ENTER" and not self.trend_engine.position:
            return exec_signal
        
        return Signal(type="NONE", direction="NONE", confidence=0.0, reason="No signal")
    
    async def start(self):
        self.running = True
        await self.initialize()
        await self.process_market_data()
    
    async def stop(self):
        self.running = False
        await self.binance_client.close()
