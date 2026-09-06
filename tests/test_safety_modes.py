"""P0-A 模式门禁补充测试：新旧配置冲突、探活失败、endpoint 矩阵、环境默认值。

与 tests/test_p0_safety.py 互补；本文件聚焦 reviewer 点名但尚未覆盖的场景。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.p0_boundary import (  # noqa: E402
    Persistence,
    RunMode,
    SafetyStore,
    SafetyViolation,
    assert_client_endpoint,
    assert_endpoint,
    boot,
    effective_futures_url,
    resolve_mode,
)

try:
    from test_p0_safety import FakeBroker  # noqa: E402
except ImportError:  # tests/ 存在 __init__.py 时按包导入
    from tests.test_p0_safety import FakeBroker  # noqa: E402


SAFETY_KEYS = (
    "TRADING_MODE",
    "TESTNET",
    "ALLOW_LIVE_TRADING",
    "AURORA_LIVE_CONFIRM",
    "AURORA_LIVE_KEY_SHA256",
    "AURORA_ACCOUNT_FINGERPRINT",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
)


class ScrubbedEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in SAFETY_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class LegacyConflictTests(ScrubbedEnv):
    """新旧配置冲突必须拒绝启动。"""

    def test_live_with_legacy_testnet_true_rejected(self):
        os.environ["TRADING_MODE"] = "LIVE"
        os.environ["TESTNET"] = "true"
        with self.assertRaises(SafetyViolation):
            resolve_mode()

    def test_testnet_with_legacy_false_rejected(self):
        os.environ["TRADING_MODE"] = "TESTNET"
        os.environ["TESTNET"] = "false"
        with self.assertRaises(SafetyViolation):
            resolve_mode()

    def test_shadow_with_legacy_false_rejected(self):
        os.environ["TRADING_MODE"] = "SHADOW"
        os.environ["TESTNET"] = "false"
        with self.assertRaises(SafetyViolation):
            resolve_mode()

    def test_paper_ignores_legacy_value(self):
        os.environ["TRADING_MODE"] = "PAPER"
        os.environ["TESTNET"] = "false"
        self.assertEqual(resolve_mode(), RunMode.PAPER)

    def test_live_with_legacy_truthy_aliases_rejected(self):
        os.environ["TRADING_MODE"] = "LIVE"
        for raw in ("1", "yes", "on"):
            os.environ["TESTNET"] = raw
            with self.subTest(legacy=raw):
                with self.assertRaises(SafetyViolation):
                    resolve_mode()

    def test_testnet_with_legacy_falsy_aliases_rejected(self):
        os.environ["TRADING_MODE"] = "TESTNET"
        for raw in ("0", "no", "off"):
            os.environ["TESTNET"] = raw
            with self.subTest(legacy=raw):
                with self.assertRaises(SafetyViolation):
                    resolve_mode()

    def test_unknown_legacy_testnet_rejected(self):
        os.environ["TRADING_MODE"] = "TESTNET"
        os.environ["TESTNET"] = "maybe"
        with self.assertRaises(SafetyViolation):
            resolve_mode()

    def test_testnet_accepts_legacy_truthy_aliases(self):
        os.environ["TRADING_MODE"] = "TESTNET"
        for raw in ("true", "1", "yes", "on"):
            os.environ["TESTNET"] = raw
            with self.subTest(legacy=raw):
                self.assertEqual(resolve_mode(), RunMode.TESTNET)

    def test_live_accepts_legacy_falsy_aliases(self):
        os.environ["TRADING_MODE"] = "LIVE"
        for raw in ("false", "0", "no", "off"):
            os.environ["TESTNET"] = raw
            with self.subTest(legacy=raw):
                self.assertEqual(resolve_mode(), RunMode.LIVE)


class ProbeFailureTests(ScrubbedEnv):
    """探活失败必须拒绝进入交易流程。"""

    def test_boot_account_probe_failure_refused(self):
        from aurora.p0_boundary import key_fingerprint

        key = "probe-key"
        with tempfile.TemporaryDirectory() as tmp:
            broker = FakeBroker()
            broker.fail_account = True
            with self.assertRaises(SafetyViolation) as ctx:
                boot(
                    os.path.join(tmp, "p0.json"),
                    os.path.join(tmp, "locks"),
                    broker=broker,
                    environ={
                        "TRADING_MODE": "TESTNET",
                        "BINANCE_API_KEY": key,
                        "AURORA_ACCOUNT_FINGERPRINT": key_fingerprint(key),
                    },
                )
            self.assertIn("probe failed", str(ctx.exception))


class EndpointMatrixTests(ScrubbedEnv):
    """endpoint 与模式必须一一对应；PAPER 不得携带任何 endpoint。"""

    MAINNET = "https://fapi.binance.com/fapi/v1/order"
    TESTNET_URL = "https://testnet.binancefuture.com/fapi/v1/order"

    def test_paper_any_endpoint_rejected(self):
        for url in (self.MAINNET, self.TESTNET_URL, "https://example.com"):
            with self.assertRaises(SafetyViolation):
                assert_endpoint(url, RunMode.PAPER)

    def test_testnet_mainnet_rejected(self):
        with self.assertRaises(SafetyViolation):
            assert_endpoint(self.MAINNET, RunMode.TESTNET)

    def test_shadow_mainnet_rejected(self):
        with self.assertRaises(SafetyViolation):
            assert_endpoint(self.MAINNET, RunMode.SHADOW)

    def test_live_testnet_rejected(self):
        with self.assertRaises(SafetyViolation):
            assert_endpoint(self.TESTNET_URL, RunMode.LIVE)

    def test_matching_endpoints_accepted(self):
        assert_endpoint(self.TESTNET_URL, RunMode.TESTNET)
        assert_endpoint(self.TESTNET_URL, RunMode.SHADOW)
        assert_endpoint("https://testnet.binance.vision/fapi/v1/order", RunMode.TESTNET)
        assert_endpoint(self.MAINNET, RunMode.LIVE)

    def test_substring_testnet_host_rejected(self):
        with self.assertRaises(SafetyViolation):
            assert_endpoint("https://eviltestnet.example.com/fapi/v1/order", RunMode.TESTNET)
        with self.assertRaises(SafetyViolation):
            assert_endpoint("https://evil.com/?next=testnet.binancefuture.com", RunMode.SHADOW)

    def test_effective_url_follows_client_testnet_flag(self):
        class _Client:
            FUTURES_URL = "https://fapi.binance.com/fapi"
            FUTURES_TESTNET_URL = "https://testnet.binancefuture.com/fapi"

            def __init__(self, testnet):
                self.testnet = testnet

        self.assertEqual(
            effective_futures_url(_Client(True)),
            "https://testnet.binancefuture.com/fapi",
        )
        self.assertEqual(
            effective_futures_url(_Client(False)),
            "https://fapi.binance.com/fapi",
        )
        assert_client_endpoint(_Client(True), RunMode.TESTNET)
        assert_client_endpoint(_Client(False), RunMode.LIVE)
        with self.assertRaises(SafetyViolation):
            assert_client_endpoint(_Client(False), RunMode.TESTNET)
        with self.assertRaises(SafetyViolation):
            assert_client_endpoint(_Client(True), RunMode.LIVE)


class EnvDefaultTests(ScrubbedEnv):
    def test_unset_mode_resolves_paper_from_os_environ(self):
        self.assertEqual(resolve_mode(), RunMode.PAPER)

    def test_unknown_mode_rejected_from_os_environ(self):
        os.environ["TRADING_MODE"] = "BOGUS"
        with self.assertRaises(SafetyViolation):
            resolve_mode()


if __name__ == "__main__":
    unittest.main()
