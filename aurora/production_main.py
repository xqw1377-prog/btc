import asyncio
import signal
import sys
from typing import Dict, Any
from datetime import datetime

from .event_bus import EventBus, BinanceDataCollector, Event
from .feature_engine import FeatureEngine
from .market_state_engine_v2 import MarketStateEngineV2
from .strategy_router import StrategyRouter
from .global_risk_engine import GlobalRiskEngine, SystemState
from .production_order_executor import ProductionOrderExecutor
from .monitoring import TradeLogger, PerformanceMonitor, MonitoringDashboard
from .replay_engine import ReplayEngine
from .position_sizing_v2 import PositionSizingEngine
from .regime_learning import RegimeLearningLayer
from .performance_feedback import PerformanceFeedback

class AuroraProductionEngine:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.running = False
        
        self.event_bus = EventBus()
        self.data_collector = BinanceDataCollector("btcusdt")
        
        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2(confirmation_count=3)
        self.router = StrategyRouter()
        
        self.position_sizer = PositionSizingEngine()
        self.regime_learning = RegimeLearningLayer()
        self.feedback = PerformanceFeedback()
        
        self.risk_engine = GlobalRiskEngine()
        
        self.order_executor = None
        
        self.logger = TradeLogger()
        self.monitor = PerformanceMonitor()
        self.dashboard = MonitoringDashboard(self.logger, self.monitor)
        
        self.replay_engine = ReplayEngine()
        
        self.last_state = None
        self.last_signal = None
    
    async def initialize(self, api_key: str = None, api_secret: str = None, testnet: bool = True):
        await self.event_bus.connect_redis()
        
        if api_key and api_secret:
            from binance.client import Client
            client = Client(api_key, api_secret, testnet=testnet)
            self.order_executor = ProductionOrderExecutor(client)
            print(f"Connected to Binance {'Testnet' if testnet else 'Mainnet'}")
        
        self.event_bus.subscribe('kline', self._on_kline)
        self.event_bus.subscribe('markPrice', self._on_mark_price)
        
        print("AURORA Production Engine initialized")
    
    async def _on_kline(self, event: Event):
        try:
            data = event.data
            
            if not data.get('is_closed'):
                return
            
            buffer = self.data_collector.get_buffer('kline')
            
            if len(buffer) < 100:
                return
            
            import pandas as pd
            df = pd.DataFrame(buffer)
            
            features = self.feature_engine.get_latest_features(df)
            
            market_state = self.state_engine.identify_regime(features)
            
            if not self.state_engine.should_trade(market_state):
                return
            
            regime_stats = self.regime_learning.get_all_stats()
            signal = self.router.route(df, market_state)
            
            signal = self.feedback.get_adjusted_signal(signal)
            
            self.logger.log_signal({
                'signal': signal.get('signal'),
                'engine': signal.get('engine'),
                'regime': market_state.get('regime'),
                'confidence': market_state.get('confidence')
            })
            
            if signal.get('signal') != 'NONE':
                await self._execute_signal(signal, market_state, features)
            
            self.last_state = market_state
            self.last_signal = signal
            
        except Exception as e:
            self.logger.log_error({'error': str(e), 'context': 'kline_handler'})
    
    async def _on_mark_price(self, event: Event):
        try:
            price = event.data.get('mark_price', 0)
            if price > 0:
                self.monitor.update_equity(price)
        except Exception as e:
            self.logger.log_error({'error': str(e), 'context': 'mark_price_handler'})
    
    async def _execute_signal(self, signal: Dict[str, Any], market_state: Dict[str, Any], features: Dict[str, Any]):
        if not self.order_executor:
            self.logger.log_error({'error': 'No order executor configured'})
            return
        
        balance = self.order_executor.api.get_account_balance()
        current_price = features.get('close', 0)
        
        position_size = self.position_sizer.calculate_position_size(
            balance=balance,
            price=current_price,
            market_state=market_state,
            engine_type=signal.get('engine', 'UNKNOWN'),
            regime_stats=self.regime_learning.get_all_stats(),
            risk_multiplier=self.feedback.get_risk_multiplier()
        )
        
        validation = self.risk_engine.validate_trade(
            leverage=3.0,
            exposure_pct=position_size.get('position_pct', 0),
            position_size_pct=position_size.get('position_pct', 0),
            volatility=features.get('volatility', 0),
            avg_volatility=features.get('volatility', 0) * 0.8,
            spread_pct=0.001
        )
        
        if not validation.get('approved'):
            self.logger.log_risk_event({
                'reason': validation.get('reason'),
                'level': validation.get('level')
            })
            return
        
        side = 'BUY' if signal.get('direction') == 'LONG' else 'SELL'
        quantity = position_size.get('quantity', 0)
        
        result = self.order_executor.place_order(
            side=side,
            quantity=quantity,
            signal_type=signal.get('engine', 'UNKNOWN')
        )
        
        if result.get('success'):
            self.risk_engine.record_trade()
            
            self.logger.log_trade({
                'order_id': result.get('order_id'),
                'client_id': result.get('client_id'),
                'side': side,
                'quantity': quantity,
                'price': current_price,
                'engine': signal.get('engine'),
                'regime': market_state.get('regime')
            })
            
            await asyncio.sleep(1)
            verify_result = self.order_executor.verify_order(result.get('client_id'))
            
            if verify_result.get('success') and verify_result.get('status') == 'FILLED':
                self.monitor.record_trade(0, True)
        
        else:
            self.logger.log_error({
                'error': result.get('reason'),
                'context': 'order_placement'
            })
    
    async def start(self):
        self.running = True
        
        self.replay_engine.start_recording()
        
        self.data_collector.start_in_thread()
        
        print("AURORA Production Engine started")
        
        try:
            while self.running:
                timeouts = self.order_executor.check_timeouts() if self.order_executor else []
                
                for timeout in timeouts:
                    self.logger.log_system_event('ORDER_TIMEOUT', timeout)
                
                self.dashboard.print_summary()
                
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            await self.stop()
    
    async def stop(self):
        self.running = False
        
        self.data_collector.stop()
        
        if self.order_executor:
            self.order_executor.cancel_all_orders()
        
        self.replay_engine.stop_recording()
        self.replay_engine.save_recording()
        
        self.logger.log_system_event('SHUTDOWN', {
            'metrics': self.monitor.get_metrics()
        })
        
        print("AURORA Production Engine stopped")
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'running': self.running,
            'risk_engine': self.risk_engine.get_status(),
            'monitoring': self.monitor.get_metrics(),
            'order_stats': self.order_executor.get_stats() if self.order_executor else {},
            'state_engine': self.state_engine.get_regime_stats()
        }

def main():
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'true').lower() == 'true'
    
    engine = AuroraProductionEngine()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.run_until_complete(engine.initialize(api_key, api_secret, testnet))
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(engine.stop()))
    
    loop.run_until_complete(engine.start())

if __name__ == "__main__":
    main()