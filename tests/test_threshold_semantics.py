"""G0-1B：SL/TP 阈值三态语义——消灭 0.0/缺失值误平。

不变量：
- UNKNOWN / NOT_CONFIGURED / invalid 阈值不产生任何价格触发；
- VALID 阈值只按 side + threshold + price 决定，不受哨兵/truthiness 影响；
- 未知阈值不误退，但保留保护缺口标记，不伪装成普通 HOLD；
- 本地 trailing 只更新 STRATEGY 候选，不得冒充已确认保护。
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, strategies as st  # noqa: E402

from aurora.kernel_types import (  # noqa: E402
    Intent,
    PositionManager,
    PositionSide,
    ThresholdState,
    valid_threshold,
)


def _mgr(side=Intent.LONG, sl=None, tp=None, sl_state=None, tp_state=None,
         source="STRATEGY"):
    m = PositionManager()
    m.open(side, 0.1, 100.0, sl, tp, "test",
           stop_loss_state=sl_state, take_profit_state=tp_state,
           stop_loss_source=source)
    return m


class ThreeStateTests(unittest.TestCase):
    def test_unknown_thresholds_never_trigger_either_side(self):
        for side in (Intent.LONG, Intent.SHORT):
            m = _mgr(side, sl=None, tp=None)
            for price in (0.0, 1.0, 50.0, 100.0, 200.0, 1e9):
                self.assertFalse(m.should_stop_loss(price), (side, price))
                self.assertFalse(m.should_take_profit(price), (side, price))
            pos = m.position
            self.assertEqual(pos.stop_loss_state, ThresholdState.UNKNOWN)
            self.assertEqual(pos.take_profit_state, ThresholdState.UNKNOWN)
            self.assertTrue(pos.protection_unknown)
            self.assertEqual(pos.protection_note, "")

    def test_zero_and_invalid_values_never_trigger(self):
        bad = [0.0, -5.0, float("nan"), float("inf"), float("-inf"), 0]
        for v in bad:
            for side in (Intent.LONG, Intent.SHORT):
                m = _mgr(side, sl=v, tp=v)
                for price in (1.0, 100.0):
                    self.assertFalse(m.should_stop_loss(price), (side, v))
                    self.assertFalse(m.should_take_profit(price), (side, v))
                # 无效值被归一化为 UNKNOWN，而不是悄悄接受
                self.assertEqual(m.position.stop_loss_state, ThresholdState.UNKNOWN)
                self.assertIsNone(m.position.stop_loss)

    def test_valid_sl_not_configured_tp_long(self):
        m = _mgr(Intent.LONG, sl=95.0, tp=None,
                 tp_state=ThresholdState.NOT_CONFIGURED)
        self.assertFalse(m.should_take_profit(1e9))     # 无 TP 永不触发
        self.assertFalse(m.should_stop_loss(96.0))
        self.assertTrue(m.should_stop_loss(94.0))       # SL 正常工作
        self.assertEqual(m.position.take_profit_state, ThresholdState.NOT_CONFIGURED)
        self.assertFalse(m.position.protection_unknown)

    def test_not_configured_sl_valid_tp_short(self):
        m = _mgr(Intent.SHORT, sl=None, tp=90.0,
                 sl_state=ThresholdState.NOT_CONFIGURED)
        self.assertFalse(m.should_stop_loss(0.0))       # 无 SL 永不触发
        self.assertFalse(m.should_take_profit(95.0))
        self.assertTrue(m.should_take_profit(89.0))     # SHORT: price<=tp

    def test_valid_threshold_direction_regression(self):
        long_ = _mgr(Intent.LONG, sl=95.0, tp=110.0)
        self.assertTrue(long_.should_stop_loss(94.9))
        self.assertFalse(long_.should_stop_loss(95.1))
        self.assertTrue(long_.should_take_profit(110.1))
        self.assertFalse(long_.should_take_profit(109.9))
        short = _mgr(Intent.SHORT, sl=105.0, tp=90.0)
        self.assertTrue(short.should_stop_loss(105.1))
        self.assertFalse(short.should_stop_loss(104.9))
        self.assertTrue(short.should_take_profit(89.9))
        self.assertFalse(short.should_take_profit(90.1))

    def test_one_leg_unknown_does_not_poison_valid_leg(self):
        m = _mgr(Intent.LONG, sl=None, tp=110.0)  # SL 未知但 TP 有效
        self.assertFalse(m.should_stop_loss(0.0))
        self.assertTrue(m.should_take_profit(111.0))
        self.assertTrue(m.position.protection_unknown)


class TrailingBoundaryTests(unittest.TestCase):
    def _brain_manage(self, mgr):
        """调用真实 brain 的 _manage_position 检查 trailing 行为。"""
        from aurora.portfolio_brain_v2 import PortfolioBrainV2
        brain = PortfolioBrainV2(1000.0)
        brain.position_mgr = mgr
        return brain._manage_position([], "TREND", price=103.0, atr=1.0,
                                      confidence=0.5)

    def test_trailing_updates_strategy_candidate_only(self):
        m = _mgr(Intent.LONG, sl=95.0, source="STRATEGY")
        m.position.unrealized_pnl = 30.0  # pnl_pct > 1%
        self._brain_manage(m)
        self.assertGreater(m.position.stop_loss, 95.0)  # 候选被更新
        self.assertEqual(m.position.stop_loss_state, ThresholdState.VALID)

    def test_trailing_cannot_fill_synced_unknown(self):
        m = _mgr(Intent.LONG, sl=None, source="EXCHANGE_SYNC")
        m.position.unrealized_pnl = 30.0
        self._brain_manage(m)
        self.assertIsNone(m.position.stop_loss)          # 不得凭空造出 SL
        self.assertEqual(m.position.stop_loss_state, ThresholdState.UNKNOWN)


class SyncFromExchangeTests(unittest.TestCase):
    def test_sync_opens_with_unknown_thresholds_no_zero(self):
        """重启同步的仓位：无 0 哨兵、不触发任何退出、保留保护缺口标记。"""
        import tempfile
        from aurora.trading_cycle import TradingCycle
        from aurora.p0_boundary import RunMode
        from aurora.kernel.fake_exchange import FakeExchange

        exchange = FakeExchange()
        exchange.seed_external_position(-0.1, 50000.0)  # SHORT 外部仓

        class RT:
            def __init__(self):
                self.exchange = exchange

            def recover(self):
                return {"resolved": [], "unresolved": [], "kill_engaged": False}

            class ledger:
                @staticmethod
                def kill_state():
                    return {"engaged": False}

        cycle = TradingCycle(runtime=RT(), client=None,
                             mode=RunMode.TESTNET, capital=1000.0)
        cycle.sync_brain_from_exchange()
        pos = cycle.brain.position_mgr.position
        self.assertTrue(pos.is_open)
        self.assertEqual(pos.side, PositionSide.SHORT)
        self.assertIsNone(pos.stop_loss)
        self.assertIsNone(pos.take_profit)
        self.assertEqual(pos.stop_loss_state, ThresholdState.UNKNOWN)
        self.assertEqual(pos.take_profit_state, ThresholdState.UNKNOWN)
        self.assertTrue(pos.protection_unknown)
        self.assertIn("PROTECTION_UNKNOWN", pos.protection_note)
        # SHORT + 旧 0 哨兵语义下 price>=0 恒真 → 现在任何价格都不得触发
        for price in (0.001, 100.0, 1e6):
            self.assertFalse(cycle.brain.position_mgr.should_stop_loss(price))
            self.assertFalse(cycle.brain.position_mgr.should_take_profit(price))


class HypothesisInvariants(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(
        price=st.floats(min_value=1e-9, max_value=1e12,
                        allow_nan=False, allow_infinity=False),
        bad=st.one_of(
            st.none(),
            st.just(0.0),
            st.floats(max_value=0.0, allow_infinity=True),
            st.just(float("nan")),
            st.just(float("inf")),
        ),
        side=st.sampled_from([Intent.LONG, Intent.SHORT]),
    )
    def test_invalid_or_unknown_never_triggers(self, price, bad, side):
        m = _mgr(side, sl=bad, tp=bad)
        self.assertFalse(m.should_stop_loss(price))
        self.assertFalse(m.should_take_profit(price))

    @settings(max_examples=200, deadline=None)
    @given(
        price=st.floats(min_value=1e-9, max_value=1e12,
                        allow_nan=False, allow_infinity=False),
        sl=st.floats(min_value=1e-9, max_value=1e12,
                     allow_nan=False, allow_infinity=False),
        tp=st.floats(min_value=1e-9, max_value=1e12,
                     allow_nan=False, allow_infinity=False),
        side=st.sampled_from([Intent.LONG, Intent.SHORT]),
    )
    def test_valid_threshold_pure_function(self, price, sl, tp, side):
        m = _mgr(side, sl=sl, tp=tp)
        if side == Intent.LONG:
            self.assertEqual(m.should_stop_loss(price), price <= sl)
            self.assertEqual(m.should_take_profit(price), price >= tp)
        else:
            self.assertEqual(m.should_stop_loss(price), price >= sl)
            self.assertEqual(m.should_take_profit(price), price <= tp)


if __name__ == "__main__":
    unittest.main()
