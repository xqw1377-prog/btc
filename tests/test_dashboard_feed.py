"""C5：dashboard_feed 只读观察边界。

假数据源 + 隔离环境；本机回环 WS 测试只验证 Origin 握手与初始快照，
不发真实交易所请求。禁止事项：非白名单方法、交易写、秘密泄漏、
失败伪装成 FLAT、旧快照时间被重广播刷新。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402
from aurora.dashboard_feed import (  # noqa: E402
    DashboardFeed,
    ReadOnlyClient,
    allowed_origins,
    redact,
)


class FakeClient:
    def __init__(self, account=None, trades=None, fail_account=False):
        self.account = account or {
            "assets": [{"asset": "USDT", "availableBalance": "1000", "walletBalance": "1000"}],
            "positions": [
                {"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "100000",
                 "markPrice": "100100", "unrealizedProfit": "10", "leverage": "2"}
            ],
            "totalWalletBalance": "1000",
            "totalUnrealizedProfit": "10",
        }
        self.trades = trades or []
        self.fail_account = fail_account
        self.write_calls = 0

    def futures_account(self):
        if self.fail_account:
            raise RuntimeError("account query failed FAKEKEY-SECRET-999")
        return self.account

    def futures_account_trades(self, symbol=None, limit=None):
        return self.trades

    def futures_ticker(self, symbol=None):
        raise RuntimeError("not needed in these tests")

    # 非白名单写方法，用于证明视图拒绝——不在 READ_METHODS 内
    def futures_create_order(self, **kw):
        self.write_calls += 1
        return {}


def _feed(client=None, mode=RunMode.TESTNET):
    return DashboardFeed(client=client or FakeClient(), mode=mode)


class ImportAndConstructionTests(unittest.TestCase):
    def test_import_only_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".env"), "w") as fh:
                fh.write("TRADING_MODE=LIVE\n")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("TRADING_MODE", "TESTNET")}
            env["PYTHONPATH"] = ROOT
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import os, aurora.dashboard_feed; "
                 "print('POLLUTED' if os.environ.get('TRADING_MODE') else 'CLEAN')"],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            self.assertIn("CLEAN", proc.stdout)

    def test_live_and_paper_refused_even_with_injected_client(self):
        for mode in (RunMode.LIVE, RunMode.PAPER):
            with self.subTest(mode=mode):
                with self.assertRaises(SafetyViolation):
                    _feed(mode=mode)


class ReadOnlyCapabilityTests(unittest.TestCase):
    def test_non_whitelisted_method_refused(self):
        feed = _feed()
        with self.assertRaises(SafetyViolation):
            feed.client.futures_create_order(symbol="BTCUSDT")
        with self.assertRaises(SafetyViolation):
            feed.client.futures_change_leverage(symbol="BTCUSDT", leverage=5)
        self.assertEqual(feed.client._client.write_calls, 0)

    def test_whitelisted_reads_work(self):
        feed = _feed()
        account = feed.client.futures_account()
        self.assertIsInstance(account, dict)
        feed.client.futures_account_trades(symbol="BTCUSDT")


class FreshnessAndFailureTests(unittest.TestCase):
    def test_failed_account_query_is_unknown_not_flat(self):
        feed = _feed(FakeClient(fail_account=True))
        ok = feed._run_fetch("account", feed.fetch_account_data)
        self.assertFalse(ok)
        self.assertEqual(feed.meta["account"]["status"], "unknown")
        env = json.loads(feed._envelope("system", "account", feed._system_payload()))
        self.assertEqual(env["payload"]["positionsState"], "UNKNOWN")
        self.assertNotEqual(env["payload"]["positionsState"], "FLAT")

    def test_stale_snapshot_keeps_original_timestamp(self):
        client = FakeClient()
        feed = _feed(client)
        self.assertTrue(feed._run_fetch("account", feed.fetch_account_data))
        first_ts = feed.meta["account"]["updated_at"]
        first_env = feed._envelope("system", "account", feed._system_payload())
        client.fail_account = True
        self.assertFalse(feed._run_fetch("account", feed.fetch_account_data))
        self.assertEqual(feed.meta["account"]["status"], "stale")
        self.assertEqual(feed.meta["account"]["updated_at"], first_ts)
        # 重广播旧数据：updatedAt 与数据本体不变，status 如实降级为 stale
        before = json.loads(first_env)["payload"]
        after = json.loads(
            feed._envelope("system", "account", feed._system_payload())
        )["payload"]
        self.assertEqual(after["meta"]["updatedAt"], before["meta"]["updatedAt"])
        self.assertEqual(after["meta"]["status"], "stale")
        for key in ("balance", "equity", "positions", "positionsState"):
            self.assertEqual(after[key], before[key])

    def test_partial_success_tracks_sections_independently(self):
        client = FakeClient(fail_account=True)
        feed = _feed(client)
        client.futures_ticker = lambda symbol=None: {
            "lastPrice": "100", "priceChange": "1", "priceChangePercent": "1"
        }
        client.futures_klines = lambda symbol=None, interval=None, limit=None: [
            [i, "1", "1", "1", "1", "1", 0, "1", 1, "1", "1", "0"]
            for i in range(100)
        ]
        feed._run_fetch("market", feed.fetch_market_data)
        feed._run_fetch("account", feed.fetch_account_data)
        self.assertIn(feed.meta["market"]["status"], ("ok", "unknown", "stale"))
        self.assertEqual(feed.meta["account"]["status"], "unknown")

    def test_secret_in_exception_is_redacted(self):
        secret = "FAKEKEY-SECRET-999"
        feed = _feed(FakeClient(fail_account=True))
        os.environ["BINANCE_API_KEY"] = secret
        try:
            feed._run_fetch("account", feed.fetch_account_data)
            self.assertNotIn(secret, feed.meta["account"]["last_error"] or "")
            self.assertIn("REDACTED", feed.meta["account"]["last_error"])
        finally:
            os.environ.pop("BINANCE_API_KEY", None)

    def test_envelope_marks_observation_identity(self):
        feed = _feed(mode=RunMode.SHADOW)
        env = json.loads(feed._envelope("system", "account", feed._system_payload()))
        meta = env["payload"]["meta"]
        self.assertEqual(meta["source"], "EXCHANGE_READONLY")
        self.assertEqual(meta["mode"], "SHADOW")
        self.assertFalse(meta["ledgerReconciled"])
        self.assertEqual(meta["protectionStatus"], "NOT_VERIFIED")
        self.assertEqual(env["payload"]["mode"], "SHADOW")

    def test_no_protection_claim_in_payload(self):
        feed = _feed()
        feed._run_fetch("account", feed.fetch_account_data)
        env = json.loads(feed._envelope("system", "account", feed._system_payload()))
        self.assertEqual(env["payload"]["meta"]["protectionStatus"], "NOT_VERIFIED")


class InboundMessageTests(unittest.TestCase):
    def test_client_messages_never_reach_sdk(self):
        class FakeWS:
            def __init__(self):
                self.sent = []

            async def send(self, msg):
                self.sent.append(msg)

            def __aiter__(self):
                async def gen():
                    yield json.dumps({
                        "method": "futures_create_order",
                        "params": {"symbol": "BTCUSDT"},
                    })
                    yield json.dumps({"url": "https://fapi.binance.com/fapi/v1/order"})
                return gen()

        client = FakeClient()
        feed = _feed(client)
        ws = FakeWS()
        asyncio.run(feed.handler(ws))
        self.assertEqual(client.write_calls, 0)
        self.assertGreater(len(ws.sent), 0)  # 初始快照已发，入站内容被忽略


class OriginPolicyTests(unittest.TestCase):
    def test_allowed_origins_default_loopback_vite(self):
        self.assertEqual(
            allowed_origins({}),
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )

    def test_allowed_origins_env_override(self):
        self.assertEqual(
            allowed_origins({"AURORA_DASHBOARD_ORIGINS": "http://a, http://b "}),
            ["http://a", "http://b"],
        )

    def test_loopback_server_enforces_origin(self):
        # 本机回环真实握手验证：合法 Origin 收到初始快照，非法 Origin 被拒。
        websockets = __import__("websockets")
        feed = _feed()

        async def scenario():
            server = await websockets.serve(
                feed.handler, "127.0.0.1", 0,
                origins=["http://allowed.local"],
            )
            try:
                port = server.sockets[0].getsockname()[1]
                uri = f"ws://127.0.0.1:{port}"
                async with websockets.connect(
                    uri, origin="http://allowed.local"
                ) as ws:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    self.assertIn("type", msg)
                with self.assertRaises(Exception):
                    await websockets.connect(uri, origin="http://evil.local")
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(scenario())


class RedactTests(unittest.TestCase):
    def test_redact_known_secret_values(self):
        env = {"BINANCE_API_KEY": "abc123secret", "OTHER": "x"}
        self.assertEqual(
            redact("failed with key abc123secret inside", env),
            "failed with key ***REDACTED*** inside",
        )


if __name__ == "__main__":
    unittest.main()
