"""G0-2：唯一已收盘 bar 驱动确认。

不变量：
- 同一 (symbol, interval, open_time) 永不二次消费；
- 确认/时长推进只由新 bar 驱动，与轮询频率无关；
- 非新 bar 时安全/恢复循环照常执行，只有 bar 证据层不推进；
- 持久化缺失时保守处理：第一根 bar 标记已见但不消费。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, strategies as st  # noqa: E402

from aurora.market_state_engine_v2 import MarketStateEngineV2  # noqa: E402
from aurora.regime_memory import RegimeMemoryModel  # noqa: E402
from aurora.kernel_types import Intent, Signal  # noqa: E402

SYM = "BTCUSDT"
B = lambda t, iv="1m": (SYM, iv, t)

TREND_FEATS = {
    "ema20": 110.0, "ema60": 100.0, "adx": 30.0, "adx_mean": 20.0,
    "ema_slope": 1.0, "atr": 1.0, "atr_mean": 1.0, "close": 100.0,
    "volatility": 0.01, "volume": 1.0, "rsi": 60.0, "momentum": 1.0,
    "momentum_pct": 0.01, "vwap": 100.0, "is_uptrend": True,
}


class OuterConfirmationTests(unittest.TestCase):
    def test_same_bar_ten_polls_count_once(self):
        eng = MarketStateEngineV2(confirmation_count=3)
        eng.identify_regime(TREND_FEATS, bar_id=B(1000))
        for _ in range(9):
            out = eng.identify_regime(TREND_FEATS, bar_id=B(1000))
            self.assertEqual(out["bar_status"], "SAME_CLOSED_BAR")
        self.assertEqual(eng.confirmation_counter, 1)

    def test_three_distinct_bars_confirm_once_each(self):
        eng = MarketStateEngineV2(confirmation_count=3)
        r1 = eng.identify_regime(TREND_FEATS, bar_id=B(1000))
        self.assertFalse(r1["confirmed"])
        eng.identify_regime(TREND_FEATS, bar_id=B(1060))
        r3 = eng.identify_regime(TREND_FEATS, bar_id=B(1120))
        self.assertTrue(r3["confirmed"])
        self.assertEqual(eng.current_regime.value, "TREND")

    def test_out_of_order_and_missing_bar_do_not_advance(self):
        eng = MarketStateEngineV2(confirmation_count=3)
        eng.identify_regime(TREND_FEATS, bar_id=B(2000))
        out = eng.identify_regime(TREND_FEATS, bar_id=B(1000))
        self.assertEqual(out["bar_status"], "STALE_OR_OUT_OF_ORDER_BAR")
        self.assertEqual(eng.confirmation_counter, 1)
        out = eng.identify_regime(TREND_FEATS, bar_id=None)
        self.assertEqual(out["bar_status"], "NO_VALID_CLOSED_BAR")
        self.assertEqual(eng.confirmation_counter, 1)

    def test_interval_change_does_not_chain_evidence(self):
        eng = MarketStateEngineV2(confirmation_count=3)
        eng.identify_regime(TREND_FEATS, bar_id=B(1000, "1m"))
        eng.identify_regime(TREND_FEATS, bar_id=B(1000, "1m"))
        self.assertEqual(eng.confirmation_counter, 1)
        out = eng.identify_regime(TREND_FEATS, bar_id=B(5000, "5m"))
        # 流身份变化：计数重置，这根 5m bar 只是新证据流的第 1 次
        self.assertEqual(out["bar_status"], "NEW_CLOSED_BAR")
        self.assertEqual(eng.confirmation_counter, 1)


class RegimeMemoryDedupTests(unittest.TestCase):
    def test_same_bar_never_advances_duration_or_pending(self):
        mem = RegimeMemoryModel(confirmation_count=3)
        mem.update("TREND", 0.8, {}, bar_id=B(1000))
        self.assertEqual(mem.current.duration, 1)
        self.assertEqual(mem.pending_count, 1)
        for _ in range(10):
            out = mem.update("TREND", 0.8, {}, bar_id=B(1000))
            self.assertEqual(out["bar_status"], "SAME_CLOSED_BAR")
        self.assertEqual(mem.current.duration, 1)
        self.assertEqual(mem.pending_count, 1)

    def test_stale_bar_recorded_not_applied(self):
        mem = RegimeMemoryModel(confirmation_count=3)
        mem.update("TREND", 0.8, {}, bar_id=B(2000))
        out = mem.update("RANGE", 0.9, {}, bar_id=B(1500))
        self.assertEqual(out["bar_status"], "STALE_OR_OUT_OF_ORDER_BAR")
        self.assertEqual(mem.bar_anomalies, 1)
        # 乱序 bar 不倒退也不增加：pending 保持 1，regime 不切到 RANGE
        self.assertEqual(mem.pending_count, 1)
        self.assertEqual(mem.current.regime, "TRANSITION")

    def test_no_valid_bar_is_not_evidence(self):
        mem = RegimeMemoryModel(confirmation_count=3)
        out = mem.update("TREND", 0.9, {}, bar_id=None)
        self.assertEqual(out["bar_status"], "NO_VALID_CLOSED_BAR")
        self.assertEqual(mem.current.duration, 0)
        self.assertEqual(mem.pending_count, 0)

    def test_interval_change_resets_chain(self):
        mem = RegimeMemoryModel(confirmation_count=3)
        mem.update("TREND", 0.8, {}, bar_id=B(1000))
        mem.update("TREND", 0.8, {}, bar_id=B(1060))
        self.assertEqual(mem.pending_count, 2)
        out = mem.update("TREND", 0.8, {}, bar_id=B(3000, "5m"))
        self.assertEqual(mem.pending_count, 1)  # 新证据流从头计
        self.assertEqual(mem.current.duration, 1)


class TradingCycleEvidenceTests(unittest.TestCase):
    def _cycle(self, evidence_path, runtime=None):
        from aurora.trading_cycle import TradingCycle
        from aurora.p0_boundary import RunMode

        flat = Signal(source="t", direction=Intent.FLAT, confidence=0.5,
                      timeframe="1m", reason="flat")

        class P:
            def generate(self, *a, **k):
                return flat

        class RT:
            def __init__(self):
                self.recover_calls = 0
                from aurora.kernel.fake_exchange import FakeExchange
                self.exchange = FakeExchange()

            def recover(self):
                self.recover_calls += 1
                return {"resolved": [], "unresolved": [], "kill_engaged": False}

            class ledger:
                @staticmethod
                def kill_state():
                    return {"engaged": False}

        rt = runtime or RT()
        cycle = TradingCycle(runtime=rt, client=None, mode=RunMode.TESTNET,
                             capital=1000.0, evidence_path=evidence_path)
        cycle.features.get_latest_features = (
            lambda df, exclude_forming=True: {**TREND_FEATS,
                                              "bar_open_time": self._bar_time})
        cycle.trend = cycle.breakout = cycle.momentum = cycle.mr = P()
        return cycle, rt

    _bar_time = 1000

    def _decide_at(self, cycle, t):
        self._bar_time = t
        return cycle.decide(None)

    def test_same_bar_polls_do_not_double_consume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ev.json")
            cycle, _ = self._cycle(path)
            self._decide_at(cycle, 1000)   # 首 bar：无持久化证据 → 标记不消费
            self._decide_at(cycle, 1060)   # 新 bar：消费 1 次
            for _ in range(10):
                out = self._decide_at(cycle, 1060)
                self.assertEqual(out["bar_status"], "SAME_CLOSED_BAR")
            # 外层仍是 TRANSITION → 内层 duration 只在 1060 这根 bar 上 +1，
            # 同一 bar 的 10 次轮询不增加任何证据计数。
            self.assertEqual(cycle.brain.regime_memory.current.duration, 1)
            self.assertEqual(cycle.brain.regime_memory.bars_consumed, 1)
            self.assertEqual(cycle.state_engine.bars_consumed, 1)

    def test_safety_loop_runs_even_on_same_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle, rt = self._cycle(os.path.join(tmp, "ev.json"))
            self._decide_at(cycle, 1000)
            self._decide_at(cycle, 1060)
            # step() 的安全路径（recover/kill）与 bar 去重无关，必须每轮执行
            class C:
                def futures_klines(self, **k):
                    return [[i, "1", "1", "1", "1", "1", 0, "1", 1, "1", "1", 0]
                            for i in range(120)]
            cycle.client = C()
            cycle.step(enable=False)
            cycle.step(enable=False)
            self.assertEqual(rt.recover_calls, 2)

    def test_restart_with_persisted_bar_not_reconsumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ev.json")
            c1, _ = self._cycle(path)
            self._decide_at(c1, 1000)
            self._decide_at(c1, 1060)
            # 重启：同一根 bar 不得再次消费
            c2, _ = self._cycle(path)
            out = self._decide_at(c2, 1060)
            self.assertEqual(out["bar_status"], "SAME_CLOSED_BAR")
            self.assertEqual(c2.brain.regime_memory.bars_consumed, 0)
            out = self._decide_at(c2, 1120)
            self.assertEqual(out["bar_status"], "NEW_CLOSED_BAR")
            self.assertEqual(c2.brain.regime_memory.bars_consumed, 1)

    def test_restart_without_evidence_skips_first_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            cycle, _ = self._cycle(missing)
            out = self._decide_at(cycle, 1000)
            # 保守：第一根 bar 不消费，duration 不推进
            self.assertEqual(cycle.brain.regime_memory.current.duration, 0)
            self.assertEqual(cycle.brain.regime_memory.bars_consumed, 0)
            out = self._decide_at(cycle, 1060)
            self.assertEqual(out["bar_status"], "NEW_CLOSED_BAR")
            self.assertEqual(cycle.brain.regime_memory.bars_consumed, 1)


class HypothesisBarInvariants(unittest.TestCase):
    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.integers(min_value=0, max_value=10**9), min_size=1,
                    max_size=40))
    def test_consumed_equals_unique_increasing_bars(self, times):
        # 转移会重置 duration，所以不变量打在 bars_consumed 上：
        # 已消费证据数 == 同身份流中严格递增的 open_time 个数。
        mem = RegimeMemoryModel(confirmation_count=3)
        expected = 0
        last = None
        for t in times:
            mem.update("TREND", 0.8, {}, bar_id=B(t))
            if last is None or t > last:
                expected += 1
                last = t
        self.assertEqual(mem.bars_consumed, expected)

    @settings(max_examples=100, deadline=None)
    @given(st.integers(min_value=0, max_value=10**9),
           st.integers(min_value=1, max_value=20))
    def test_repeats_identical_to_single(self, t, n):
        a = RegimeMemoryModel(confirmation_count=3)
        a.update("TREND", 0.8, {}, bar_id=B(t))
        b = RegimeMemoryModel(confirmation_count=3)
        for _ in range(n):
            b.update("TREND", 0.8, {}, bar_id=B(t))
        self.assertEqual(a.current.duration, b.current.duration)
        self.assertEqual(a.pending_count, b.pending_count)
        self.assertEqual(a.current.regime, b.current.regime)


if __name__ == "__main__":
    unittest.main()
