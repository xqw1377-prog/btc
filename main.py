import asyncio
import signal
import sys
import os
from typing import Dict, Any
from datetime import datetime
import pandas as pd

from core.config import config
from core.event_bus import EventBus, CHANNELS
from core.message_schema import KlineEvent, SignalEvent, RiskEvent, TradeEvent
from services.data_service.binance_ws import BinanceWebSocket
from services.risk_service.risk_engine import RiskEngine, SystemState
from monitoring.alert import TelegramAlert, AlertManager

from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v2 import MarketStateEngineV2
from aurora.strategy_router import StrategyRouter
from aurora.position_sizing_v2 import PositionSizingEngine
from aurora.regime_learning import RegimeLearningLayer
from aurora.performance_feedback import PerformanceFeedback

class AuroraEngine:
    def __init__(self):
        self.running = False
        
        self.event_bus = EventBus(config.get_redis_url())
        self.data_ws = BinanceWebSocket(config.binance['symbol'].lower())
        
        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2(config.strategy['state_confirmation_count'])
        self.router = StrategyRouter()
        self.position_sizer = PositionSizingEngine()
        self.regime_learning = RegimeLearningLayer()
        self.feedback = PerformanceFeedback()
        
        self.risk_engine = RiskEngine()
        
        self.telegram = None
        if config.telegram['bot_token']:
            self.telegram = TelegramAlert(
                config.telegram['bot_token'],
                config.telegram['chat_id']
            )
        self.alert_manager = AlertManager(self.telegram)
        
        self.executor = None
        
        self.stats = {
            'start_time': None,
            'total_signals': 0,
            'total_trades': 0,
            'errors': 0
        }
    
    async def initialize(self):
        errors = config.validate()
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        
        await self.event_bus.connect()
        
        if config.binance['api_key']:
            from binance.client import Client
            client = Client(
                config.binance['api_key'],
                config.binance['api_secret'],
                testnet=config.binance['testnet']
            )
            from services.execution_service.order_executor import OrderExecutor
            self.executor = OrderExecutor(client, config.binance['symbol'])
            self.executor.api.futures_change_leverage(
                symbol=config.binance['symbol'],
                leverage=config.binance['leverage']
            )
        
        self.data_ws.on_data(self._on_market_data)
        
        print(f"AURORA Engine initialized ({'Testnet' if config.is_testnet() else 'LIVE'})")
        return True
    
    async def _on_market_data(self, event_type: str, data: Dict[str, Any]):
        await self.event_bus.publish(CHANNELS['MARKET_DATA'], data)
        
        if event_type == 'kline' and data.get('data', {}).get('is_closed'):
            await self._process_kline(data)
    
    async def _process_kline(self, event: Dict[str, Any]):
        try:
            buffer = self.data_ws.get_buffer('kline')
            if len(buffer) < 100:
                return
            
            df = pd.DataFrame(buffer)
            features = self.feature_engine.get_latest_features(df)
            
            market_state = self.state_engine.identify_regime(features)
            
            if not self.state_engine.should_trade(market_state):
                return
            
            regime_stats = self.regime_learning.get_all_stats()
            signal = self.router.route(df, market_state)
            signal = self.feedback.get_adjusted_signal(signal)
            
            self.stats['total_signals'] += 1
            
            await self.event_bus.publish(CHANNELS['SIGNAL'], signal)
            
            if signal.get('signal') != 'NONE':
                await self._execute_signal(signal, market_state, features)
                
        except Exception as e:
            self.stats['errors'] += 1
            await self.alert_manager.send_alert('api_error', {'error': str(e)})
    
    async def _execute_signal(self, signal: Dict[str, Any], market_state: Dict[str, Any], features: Dict[str, Any]):
        if not self.executor:
            return
        
        balance = self.executor.get_balance()
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
            leverage=config.binance['leverage'],
            position_size_pct=position_size.get('position_pct', 0),
            volatility=features.get('volatility', 0),
            avg_volatility=features.get('volatility', 0) * 0.8
        )
        
        if not validation.get('approved'):
            await self.event_bus.publish(CHANNELS['RISK'], {
                'type': 'TRADE_REJECTED',
                'reason': validation.get('reason')
            })
            return
        
        side = 'BUY' if signal.get('direction') == 'LONG' else 'SELL'
        quantity = position_size.get('quantity', 0)
        
        result = self.executor.place_market_order(
            side=side,
            quantity=quantity,
            signal_type=signal.get('engine', 'UNKNOWN')
        )
        
        if result.get('success'):
            self.risk_engine.record_trade()
            self.stats['total_trades'] += 1
            
            await self.executor.verify_order(result['client_id'])
            
            await self.alert_manager.send_alert('trade', {
                'engine': signal.get('engine'),
                'direction': signal.get('direction'),
                'price': current_price,
                'quantity': quantity,
                'pnl': 0
            })
    
    async def start(self):
        if not await self.initialize():
            return
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        
        ws_thread = self.data_ws.start_in_thread()
        
        print("AURORA Engine started")
        
        try:
            while self.running:
                timeouts = self.executor.check_timeouts() if self.executor else []
                
                if self.executor:
                    position = self.executor.get_position()
                    if position:
                        unrealized_pnl = position.get('unrealizedPnl', 0)
                        self.risk_engine.update_pnl(unrealized_pnl)
                
                risk_status = self.risk_engine.get_status()
                if risk_status['kill_switch']:
                    await self.alert_manager.send_alert('kill_switch', {
                        'reason': risk_status['kill_switch_reason']
                    })
                
                drawdown = risk_status.get('drawdown', 0)
                if drawdown > 0.03:
                    await self.alert_manager.send_alert('drawdown', {'drawdown': drawdown})
                
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            await self.stop()
    
    async def stop(self):
        self.running = False
        
        self.data_ws.stop()
        
        if self.executor:
            self.executor.cancel_all()
        
        await self.alert_manager.send_alert('daily_summary', {
            'daily_pnl': self.risk_engine.daily_pnl,
            'trade_count': self.stats['total_trades'],
            'win_rate': 0,
            'drawdown': self.risk_engine.get_status()['drawdown'],
            'balance': self.executor.get_balance() if self.executor else 0
        })
        
        await self.event_bus.stop()
        
        print("AURORA Engine stopped")
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'running': self.running,
            'uptime': (datetime.now() - self.stats['start_time']).total_seconds() if self.stats['start_time'] else 0,
            'stats': self.stats,
            'risk': self.risk_engine.get_status(),
            'executor': self.executor.get_stats() if self.executor else {}
        }

def main():
    engine = AuroraEngine()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(engine.stop()))
    
    loop.run_until_complete(engine.start())

if __name__ == "__main__":
    main()