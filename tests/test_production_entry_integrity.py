"""P0-A 回归钉子（B2.2）：production_main 依赖完整性与 LIVE 先拒后建。

来源：复审发现的三项回归——
1) LIVE 拒绝前构造主网 Client（构造本身即网络请求）；
2) 只读 broker 携带真实 cancel 能力；
3) production_main 依赖未跟踪的冻结线模块（execution_truth/binance_port/
   shadow_adapter/reconciler），已隔离至仓库外，本测试防止其回归。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora import production_main  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402

ROOT = Path(production_main.__file__).parent.parent
FORBIDDEN_REFERENCES = (
    "execution_truth",
    "binance_port",
    "shadow_adapter",
    "reconciler",
    "DurableExecutor",
    "SafeBinancePort",
)


class SourceIntegrityTests(unittest.TestCase):
    def test_production_main_references_only_committed_modules(self):
        source = Path(production_main.__file__).read_text()
        for banned in FORBIDDEN_REFERENCES:
            self.assertNotIn(banned, source, f"production_main 引用了违规模块: {banned}")

    def test_no_violating_modules_in_tracked_tree(self):
        for banned in ("binance_port.py", "shadow_adapter.py", "reconciler.py"):
            self.assertFalse(
                (ROOT / "aurora" / banned).exists(),
                f"违规模块重新出现: aurora/{banned}",
            )


class LiveRefusalOrderTests(unittest.TestCase):
    ENV_KEYS = (
        "TRADING_MODE", "TESTNET", "ALLOW_LIVE_TRADING", "AURORA_LIVE_CONFIRM",
        "AURORA_LIVE_KEY_SHA256", "AURORA_ACCOUNT_FINGERPRINT",
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
    )

    def _scrubbed(self, extra):
        env = {k: v for k, v in os.environ.items() if k not in self.ENV_KEYS}
        env.update(extra)
        return env

    def test_live_refuses_before_any_client_construction(self):
        """即便双重授权齐全，LIVE 也必须在构造任何 Client 之前拒绝。"""
        env = self._scrubbed({
            "TRADING_MODE": "LIVE",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
        })
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                production_main, "_build_network_broker",
                side_effect=AssertionError("LIVE must not construct any client"),
            ):
                with self.assertRaises(SafetyViolation) as ctx:
                    production_main.run_boot()
        self.assertIn("NO-GO", str(ctx.exception))

    def test_build_network_broker_refuses_live(self):
        with self.assertRaises(SafetyViolation):
            production_main._build_network_broker(RunMode.LIVE)


class ReadOnlyBrokerTests(unittest.TestCase):
    def _broker(self):
        class _DummyClient:
            FUTURES_URL = "https://testnet.binancefuture.com"
        return production_main.BinanceBroker(_DummyClient(), RunMode.TESTNET)

    def test_create_order_refused(self):
        with self.assertRaises(SafetyViolation):
            self._broker().create_order(symbol="BTCUSDT", side="BUY", type="MARKET")

    def test_cancel_order_refused(self):
        with self.assertRaises(SafetyViolation):
            self._broker().cancel_order("BTCUSDT", "123")


if __name__ == "__main__":
    unittest.main()
