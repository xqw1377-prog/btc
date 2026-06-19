import os
import sys
import time
import signal as sig
from datetime import datetime
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance.client import Client
import pandas as pd

from aurora.alpha_engine import AlphaEngine
from aurora.capital_controller import CapitalController, Action, RiskState
from aurora.execution_engine import ExecutionEngine

class AuroraFinal:
    def __init__(self):
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        self.client = Client(api_key, api_secret)
        self.symbol = 'BTCUSDT'
        self.client.futures_change_leverage(symbol=self.symbol, leverage=3)

        self._ensure_hedge_mode()

        self.alpha = AlphaEngine()
        self.balance = self._get_balance()
        self.controller = CapitalController(self.balance)
        self.execution = ExecutionEngine(self.client, self.symbol)

        self.stats = {
            'start': datetime.now(), 'signals': 0, 'trades': 0,
            'wins': 0, 'losses': 0, 'total_pnl': 0.0
        }
        self.running = False

        sig.signal(sig.SIGINT, lambda s, f: setattr(self, 'running', False))
        sig.signal(sig.SIGTERM, lambda s, f: setattr(self, 'running', False))

    def _ensure_hedge_mode(self):
        try:
            self.client.futures_change_position_mode(dualSidePosition='true')
            print("✅ Position mode: Hedge")
        except Exception as e:
            if 'No need to change' in str(e):
                print("✅ Position mode: Hedge (already set)")
            else:
                print(f"⚠️ Position mode: {e}")

    def _get_balance(self) -> float:
        for asset in self.client.futures_account()['assets']:
            if asset['asset'] == 'USDT':
                return float(asset['availableBalance'])
        return 0.0

    def _get_position(self) -> Dict[str, Any]:
        return self.execution.get_position()

    def _execute_decision(self, decision, price: float, atr: float, alpha):
        if decision.action == Action.FLAT:
            return

        if decision.action in [Action.LONG, Action.SHORT]:
            pos = self._get_position()

            if pos['size'] > 0:
                pos_is_long = pos['side'] == 'LONG'
                signal_is_long = decision.action == Action.LONG

                if pos_is_long != signal_is_long:
                    print(f"\n🔄 Reversing: closing {pos['side']} before opening {decision.action.value}")
                    result = self.execution.close_position(pos['size'], pos['side'])
                    if result.success:
                        pnl = pos['unrealized_pnl']
                        self.controller.record_result(pnl)
                        self.balance = self._get_balance()
                        self.stats['total_pnl'] += pnl
                        if pnl > 0:
                            self.stats['wins'] += 1
                        else:
                            self.stats['losses'] += 1
                        print(f"   Closed: PnL=${pnl:,.2f}")
                else:
                    return

            size_btc = self.balance * decision.size / price
            if size_btc < 0.001:
                return

            sl_price = price * (1 - decision.stop_loss_pct) if decision.action == Action.LONG else price * (1 + decision.stop_loss_pct)
            tp_price = price * (1 + decision.take_profit_pct) if decision.action == Action.LONG else price * (1 - decision.take_profit_pct)

            result = self.execution.place_order(
                side=decision.action.value,
                size_btc=size_btc,
                sl_price=round(sl_price, 2),
                tp_price=round(tp_price, 2)
            )

            if result.success:
                self.stats['trades'] += 1
                print(f"\n📈 {decision.action.value} {size_btc:.3f} BTC @ ${price:,.2f}")
                print(f"   SL=${sl_price:,.2f} TP=${tp_price:,.2f} | {decision.reason}")

    def _manage_position(self, price: float, alpha):
        pos = self._get_position()
        if pos['size'] == 0:
            return

        entry = pos['entry_price']
        if entry == 0:
            return

        if abs(alpha.direction) > 0.3:
            pos_is_long = pos['side'] == 'LONG'
            signal_against = (pos_is_long and alpha.direction < -0.3) or \
                             (not pos_is_long and alpha.direction > 0.3)
            if signal_against:
                result = self.execution.close_position(pos['size'], pos['side'])
                if result.success:
                    pnl = pos['unrealized_pnl']
                    self.controller.record_result(pnl)
                    self.balance = self._get_balance()
                    self.stats['total_pnl'] += pnl
                    if pnl > 0:
                        self.stats['wins'] += 1
                    else:
                        self.stats['losses'] += 1
                    print(f"\n{'💰' if pnl > 0 else '⚠️'} CLOSE @ ${price:,.2f} PnL=${pnl:,.2f} | Signal reversal α={alpha.direction:+.2f}")

    def run(self):
        self.running = True

        print("🧠 AURORA vFinal - Capital Control System")
        print("=" * 60)
        print(f"💰 Capital: ${self.balance:,.2f}")
        print(f"📊 Alpha → Controller → Execution")
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

                alpha = self.alpha.compute(df)
                self.stats['signals'] += 1

                price = df.iloc[-1]['close']
                atr = 100

                self._manage_position(price, alpha)

                decision = self.controller.decide(
                    direction=alpha.direction,
                    confidence=alpha.confidence,
                    regime=alpha.regime,
                    volatility=0.02,
                    price=price,
                    atr=atr,
                    current_ts=time.time()
                )

                self._execute_decision(decision, price, atr, alpha)

                pos = self._get_position()
                pos_str = f"{pos['side']} {pos['size']:.3f}" if pos['size'] > 0 else "FLAT"

                sys.stdout.write(
                    f"\r⏰ {(datetime.now() - self.stats['start']).seconds // 60}m | "
                    f"💰 ${price:,.2f} | "
                    f"α={alpha.direction:+.3f} c={alpha.confidence:.2f} | "
                    f"🎯 {decision.action.value} sz={decision.size:.2%} risk={decision.risk_state.value} | "
                    f"📊 {pos_str} | "
                    f"💵 ${self.balance:,.2f}"
                )
                sys.stdout.flush()

                time.sleep(30)

            except Exception as e:
                print(f"\n❌ {e}")
                time.sleep(5)

        self._print_summary()

    def _print_summary(self):
        elapsed = (datetime.now() - self.stats['start']).seconds // 60
        print(f"\n\n{'=' * 60}")
        print("AURORA vFinal - Session Summary")
        print(f"{'=' * 60}")
        print(f"Duration: {elapsed}m")
        print(f"Signals: {self.stats['signals']}")
        print(f"Trades: {self.stats['trades']} ({self.stats['wins']}W/{self.stats['losses']}L)")
        print(f"PnL: ${self.stats['total_pnl']:,.2f}")
        print(f"Balance: ${self._get_balance():,.2f}")
        print(f"{'=' * 60}")

if __name__ == "__main__":
    AuroraFinal().run()