import os
import sys
import time
import signal as sig
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance.client import Client
import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v2 import MarketStateEngineV2
from aurora.portfolio_brain_v2 import PortfolioBrainV2
from aurora.execution_engine_v2 import ExecutionEngineV2
from aurora.signal_providers import (
    TrendSignalProvider, BreakoutSignalProvider,
    MomentumSignalProvider, MeanReversionSignalProvider
)
from aurora.online_learner import OnlineLearner
from aurora.capital_optimizer import CapitalCurveOptimizer
from aurora.kernel_types import Intent

class AuroraHedgeFundKernel:
    def __init__(self):
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        self.client = Client(api_key, api_secret)
        self.symbol = 'BTCUSDT'
        self.client.futures_change_leverage(symbol=self.symbol, leverage=3)

        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2(confirmation_count=3)
        self.learner = OnlineLearner()

        self.balance = self._get_balance()
        self.brain = PortfolioBrainV2(self.balance)
        self.executor = ExecutionEngineV2(self.client, self.symbol)
        self.optimizer = CapitalCurveOptimizer(self.balance)

        self.trend_provider = TrendSignalProvider()
        self.breakout_provider = BreakoutSignalProvider()
        self.momentum_provider = MomentumSignalProvider()
        self.mr_provider = MeanReversionSignalProvider()

        self.stats = {
            'start': datetime.now(), 'signals': 0, 'trades': 0,
            'wins': 0, 'losses': 0, 'total_pnl': 0.0
        }
        self.running = False
        self.last_trade_price = 0

        sig.signal(sig.SIGINT, lambda s, f: setattr(self, 'running', False))
        sig.signal(sig.SIGTERM, lambda s, f: setattr(self, 'running', False))

    def _get_balance(self) -> float:
        for asset in self.client.futures_account()['assets']:
            if asset['asset'] == 'USDT':
                return float(asset['availableBalance'])
        return 0.0

    def _sync_brain_position(self):
        exch = self.executor.get_position_info()
        brain_pos = self.brain.position_mgr.position

        if exch and exch.get('size', 0) > 0 and not brain_pos.is_open:
            from aurora.kernel_types import PositionSide
            side = PositionSide.LONG if exch.get('side') == 'LONG' else PositionSide.SHORT
            self.brain.position_mgr._position.side = side
            self.brain.position_mgr._position.size = exch.get('size', 0)
            self.brain.position_mgr._position.entry_price = exch.get('entry_price', 0)

    def _execute_intent(self, intent, price: float, atr: float, signals: list, regime: str):
        if intent.action == "OPEN":
            size_btc = self.balance * intent.size_pct / price if price > 0 else 0
            if size_btc < 0.001:
                return

            sl_price = price * (1 - intent.stop_loss_pct) if intent.side == Intent.LONG else price * (1 + intent.stop_loss_pct)
            tp_price = price * (1 + intent.take_profit_pct) if intent.side == Intent.LONG else price * (1 - intent.take_profit_pct)

            result = self.executor.execute_open(
                side=intent.side.value,
                size_btc=size_btc,
                price=price,
                stop_loss=round(sl_price, 2),
                take_profit=round(tp_price, 2)
            )

            if result.success:
                self.brain.execute_intent(intent, price)
                self.last_trade_price = price
                self.stats['trades'] += 1
                print(f"\n📈 {intent.side.value} {size_btc:.3f} BTC @ ${price:,.2f}")
                print(f"   SL=${sl_price:,.2f} TP=${tp_price:,.2f} | {intent.reason}")

        elif intent.action == "CLOSE":
            pos = self.executor.get_position_info()
            if not pos or pos.get('size', 0) == 0:
                return

            old_pnl = pos.get('unrealized_pnl', 0)
            result = self.executor.execute_close()

            if result.success:
                self.brain.execute_intent(intent, price)
                self.balance = self._get_balance()
                self.brain.capital = self.balance
                self.brain.risk_gate.update_capital(self.balance)

                self.stats['total_pnl'] += old_pnl
                if old_pnl > 0:
                    self.stats['wins'] += 1
                else:
                    self.stats['losses'] += 1

                sig_dicts = [{'source': s.source, 'direction': s.direction.value, 'confidence': s.confidence} for s in signals]
                self.learner.record_trade(regime, sig_dicts, self.last_trade_price, price, pos.get('side', 'LONG'), old_pnl)

                print(f"\n{'💰' if old_pnl > 0 else '⚠️'} CLOSE @ ${price:,.2f} PnL=${old_pnl:,.2f} | {intent.reason}")

    def run(self):
        self.running = True

        print("🧠 AURORA Hedge Fund Kernel")
        print("=" * 60)
        print(f"💰 Capital: ${self.balance:,.2f}")
        print(f"📊 Signal Providers: Trend/BO/Mom/MR")
        print(f"🛡️ Risk Gate: Active")
        print(f"📈 Online Learning: Active")
        print("-" * 60)

        while self.running:
            try:
                klines = self.client.futures_klines(symbol=self.symbol, interval='1m', limit=100)
                df = pd.DataFrame(klines, columns=[
                    'time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'
                ])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)

                features = self.feature_engine.get_latest_features(df)
                market_state = self.state_engine.identify_regime(features)
                price = features['close']
                atr = features.get('atr', 0)

                signals = [
                    self.trend_provider.generate(features, market_state['regime']),
                    self.breakout_provider.generate(features, df),
                    self.momentum_provider.generate(features),
                    self.mr_provider.generate(features),
                ]

                self.stats['signals'] += 1

                intent = self.brain.process(
                    signals=signals,
                    regime=market_state['regime'],
                    confidence=market_state['confidence'],
                    volatility=features.get('volatility', 0),
                    price=price,
                    atr=atr,
                    current_ts=time.time()
                )

                self._execute_intent(intent, price, atr, signals, market_state['regime'])

                self._sync_brain_position()

                pos = self.brain.position_mgr.position
                risk = self.brain.risk_gate.get_state()
                risk_metrics = risk.get('metrics', {})

                pos_str = f"{pos.side.value} {pos.size:.3f}" if pos.is_open else "FLAT"

                sys.stdout.write(
                    f"\r⏰ {(datetime.now() - self.stats['start']).seconds // 60}m | "
                    f"💰 ${price:,.2f} | "
                    f"🧠 {intent.action} {intent.side.value} ({intent.confidence:.2f}) | "
                    f"📊 {pos_str} | "
                    f"🛡 DD={risk_metrics.get('drawdown', 0):.2%} | "
                    f"📈 {self.stats['trades']}T {self.stats['wins']}W/{self.stats['losses']}L | "
                    f"💵 ${self.balance:,.2f}"
                )
                sys.stdout.flush()

                time.sleep(30)

            except Exception as e:
                import traceback
                print(f"\n❌ {e}")
                traceback.print_exc()
                time.sleep(5)

        self._print_summary()

    def _print_summary(self):
        elapsed = (datetime.now() - self.stats['start']).seconds // 60

        print(f"\n\n{'=' * 60}")
        print("🧠 AURORA Hedge Fund Kernel - Session Summary")
        print(f"{'=' * 60}")
        print(f"Duration: {elapsed} minutes")
        print(f"Signals: {self.stats['signals']}")
        print(f"Trades: {self.stats['trades']} ({self.stats['wins']}W / {self.stats['losses']}L)")
        print(f"Total PnL: ${self.stats['total_pnl']:,.2f}")
        print(f"Final Balance: ${self._get_balance():,.2f}")

        regime_stats = self.learner.get_regime_stats()
        print(f"\nRegime Performance:")
        for regime, stats in regime_stats.items():
            print(f"  {regime}: {stats['trades']} trades, WR={stats['win_rate']:.1%}")

        signal_weights = self.learner.get_signal_weights()
        print(f"\nLearned Signal Weights:")
        for source, weight in signal_weights.items():
            print(f"  {source}: {weight:.2f}x")
        print(f"{'=' * 60}")

if __name__ == "__main__":
    AuroraHedgeFundKernel().run()