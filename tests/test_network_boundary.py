"""C2 传输边界测试：真实 SDK 构造 + 传输层出站拦截。

方法：Client / ping() / URL 生成全部走 python-binance 1.0.19 真实路径，
只在 HTTPAdapter.send 处替换网络（出站前最后一跳）。任何测试都不触网；
本文件不在 P0 源文件扫描清单内，因此允许 import requests。
凭证全部为假值；如不慎捕获到真实凭证即视为测试环境被污染。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402  （本文件允许；扫描清单外的测试专用）
from requests.adapters import HTTPAdapter  # noqa: E402

from aurora.p0_boundary import (  # noqa: E402
    ALLOWED_TESTNET_HOSTS,
    LIVE_ARM_TOKEN,
    RunMode,
    SafetyViolation,
    key_fingerprint,
)
import aurora.safety as safety  # noqa: E402
import aurora.production_main as production_main  # noqa: E402

FAKE_KEY = "c2-fake-key"
FAKE_SECRET = "c2-fake-secret"

SAFETY_KEYS = (
    "TRADING_MODE",
    "TESTNET",
    "ALLOW_LIVE_TRADING",
    "AURORA_LIVE_CONFIRM",
    "AURORA_LIVE_ARM_TOKEN",
    "AURORA_LIVE_KEY_SHA256",
    "AURORA_ACCOUNT_FINGERPRINT",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
)


def _fake_response(request, status=200, body=b"{}", headers=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.url = request.url
    resp.request = request
    resp.headers.update(headers or {})
    resp.reason = "FAKE"
    return resp


class TransportSpy:
    """替换 HTTPAdapter.send：记录每个 PreparedRequest，按脚本应答。"""

    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (lambda req: _fake_response(req))

    def __call__(self, request, **kwargs):
        self.calls.append(request)
        return self.handler(request)

    def hosts(self):
        from urllib.parse import urlparse

        return [urlparse(r.url).hostname for r in self.calls]


def _patch_transport(spy):
    return mock.patch.object(
        HTTPAdapter, "send", lambda _adapter, request, **kw: spy(request, **kw)
    )


def _host_allowed(host):
    return host in ALLOWED_TESTNET_HOSTS


class ScrubbedEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in SAFETY_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def set_testnet_env(self):
        os.environ["TRADING_MODE"] = "TESTNET"
        os.environ["BINANCE_API_KEY"] = FAKE_KEY
        os.environ["BINANCE_API_SECRET"] = FAKE_SECRET
        os.environ["AURORA_ACCOUNT_FINGERPRINT"] = key_fingerprint(FAKE_KEY)

    def set_live_env(self, drop=None):
        env = {
            "TRADING_MODE": "LIVE",
            "ALLOW_LIVE_TRADING": "true",
            "AURORA_LIVE_CONFIRM": "I_UNDERSTAND_LIVE_RISK",
            "AURORA_LIVE_ARM_TOKEN": LIVE_ARM_TOKEN,
            "BINANCE_API_KEY": FAKE_KEY,
            "BINANCE_API_SECRET": FAKE_SECRET,
            "AURORA_ACCOUNT_FINGERPRINT": key_fingerprint(FAKE_KEY),
        }
        for key in (drop or ()):
            env.pop(key, None)
        os.environ.update(env)


class UnauthorizedLiveTests(ScrubbedEnv):
    """LIVE 授权不完整/错误：Client 构造 0 次、传输请求 0 次。"""

    def _assert_refused_before_network(self, builder, drop):
        self.set_live_env(drop=drop)
        spy = TransportSpy()
        with _patch_transport(spy), mock.patch(
            "binance.client.Client"
        ) as ctor:
            with self.assertRaises(SafetyViolation):
                builder()
            self.assertEqual(ctor.call_count, 0)
            self.assertEqual(len(spy.calls), 0)

    def test_safety_build_client_each_missing_condition(self):
        for drop in (
            ("TRADING_MODE",),
            ("ALLOW_LIVE_TRADING",),
            ("AURORA_LIVE_CONFIRM",),
            ("AURORA_LIVE_ARM_TOKEN",),
            ("BINANCE_API_KEY",),
            ("BINANCE_API_SECRET",),
            ("AURORA_ACCOUNT_FINGERPRINT",),
        ):
            with self.subTest(missing=drop):
                self.setUp()
                self._assert_refused_before_network(
                    lambda: safety.build_client(RunMode.LIVE, "c2-test"), drop
                )
                self.tearDown()

    def test_production_main_network_broker_each_missing_condition(self):
        for drop in (
            ("ALLOW_LIVE_TRADING",),
            ("AURORA_LIVE_CONFIRM",),
            ("AURORA_LIVE_ARM_TOKEN",),
            ("BINANCE_API_KEY",),
        ):
            with self.subTest(missing=drop):
                self.setUp()
                self._assert_refused_before_network(
                    lambda: production_main._build_network_broker(RunMode.LIVE), drop
                )
                self.tearDown()

    def test_fully_authorized_live_still_zero_transport(self):
        # 语义边界：授权全齐时允许到达构造（ctor 被 mock），但构造后校验/守卫
        # 仍保证 0 真实出站——本批不改变"arm token 前 LIVE 已被拒"的既有语义。
        self.set_live_env()
        spy = TransportSpy()
        with _patch_transport(spy), mock.patch(
            "binance.client.Client"
        ) as ctor:
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.LIVE, "c2-test")
            self.assertEqual(len(spy.calls), 0)
        with _patch_transport(spy), mock.patch(
            "binance.client.Client"
        ) as ctor:
            with self.assertRaises(SafetyViolation):
                production_main._build_network_broker(RunMode.LIVE)
            self.assertEqual(len(spy.calls), 0)

    def test_paper_zero_construction(self):
        spy = TransportSpy()
        with _patch_transport(spy), mock.patch(
            "binance.client.Client"
        ) as ctor:
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.PAPER, "c2-test")
            self.assertEqual(ctor.call_count, 0)
            self.assertEqual(len(spy.calls), 0)


class TestnetConstructionTests(ScrubbedEnv):
    """真实 SDK 构造：构造期 ping 与后续期货请求都必须命中 testnet。"""

    def test_safety_client_ping_and_futures_targets(self):
        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            client = safety.build_client(RunMode.TESTNET, "c2-test")
            # 构造期 ping：spot API 目标必须是 testnet.binance.vision
            self.assertGreaterEqual(len(spy.calls), 1)
            self.assertEqual(spy.hosts()[0], "testnet.binance.vision")
            self.assertIn("/api/", spy.calls[0].url)
            # 后续期货请求：必须走 testnet.binancefuture.com
            client.futures_account()
            last = spy.calls[-1]
            self.assertEqual(spy.hosts()[-1], "testnet.binancefuture.com")
            self.assertIn("/fapi/", last.url)
            # 凭证只携带假 key，且所有出站 host 都在允许列表内
            self.assertEqual(last.headers.get("X-MBX-APIKEY"), FAKE_KEY)
            for host in spy.hosts():
                self.assertTrue(_host_allowed(host), host)
            self.assertTrue(client.testnet is True)
            self.assertTrue(client.session._aurora_guarded is True)

    def test_production_main_broker_construction(self):
        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            broker = production_main._build_network_broker(RunMode.TESTNET)
            account = broker.account()
            self.assertIsInstance(account, dict)
            self.assertGreaterEqual(len(spy.calls), 2)
            self.assertEqual(spy.hosts()[0], "testnet.binance.vision")
            self.assertEqual(spy.hosts()[-1], "testnet.binancefuture.com")
            for host in spy.hosts():
                self.assertTrue(_host_allowed(host), host)

    def test_shadow_construction_targets_testnet(self):
        self.set_testnet_env()
        os.environ["TRADING_MODE"] = "SHADOW"
        spy = TransportSpy()
        with _patch_transport(spy):
            client = safety.build_client(RunMode.SHADOW, "c2-test")
            self.assertTrue(client.testnet is True)
            for host in spy.hosts():
                self.assertTrue(_host_allowed(host), host)


class RedirectBoundaryTests(ScrubbedEnv):
    """任何 3xx 都不产生第二次出站；跨域目标绝不收到请求。"""

    def test_constructor_ping_redirect_not_followed(self):
        self.set_testnet_env()
        spy = TransportSpy(
            handler=lambda req: _fake_response(
                req, status=302, headers={"Location": "https://fapi.binance.com/x"}
            )
        )
        with _patch_transport(spy):
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.TESTNET, "c2-test")
        self.assertEqual(len(spy.calls), 1)  # 302 没有被跟随，不存在第二跳
        for host in spy.hosts():
            self.assertTrue(_host_allowed(host), host)

    def test_late_redirect_not_followed(self):
        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            client = safety.build_client(RunMode.TESTNET, "c2-test")
            spy.handler = lambda req: _fake_response(
                req, status=302, headers={"Location": "https://fapi.binance.com/y"}
            )
            before = len(spy.calls)
            with self.assertRaises(Exception):
                client.futures_account()
            self.assertEqual(len(spy.calls), before + 1)
            for host in spy.hosts():
                self.assertTrue(_host_allowed(host), host)


class OutboundOverrideTests(ScrubbedEnv):
    """构造后被篡改的目标在出站前被守卫拦截。"""

    def test_spot_url_override_blocked(self):
        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            client = safety.build_client(RunMode.TESTNET, "c2-test")
            # testnet 模式下 spot URI 取自 API_TESTNET_URL
            client.API_TESTNET_URL = "https://api.binance.com/api"
            before = len(spy.calls)
            with self.assertRaises(SafetyViolation):
                client.ping()
            self.assertEqual(len(spy.calls), before)

    def test_futures_url_override_blocked(self):
        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            client = safety.build_client(RunMode.TESTNET, "c2-test")
            client.FUTURES_TESTNET_URL = "https://fapi.binance.com/fapi"
            before = len(spy.calls)
            with self.assertRaises(SafetyViolation):
                client.futures_account()
            self.assertEqual(len(spy.calls), before)


class ErrorPathTests(ScrubbedEnv):
    """连接错误/超时：不回落主网、不换域名，原错误可追溯。"""

    def test_connection_error_no_fallback(self):
        self.set_testnet_env()
        spy = TransportSpy(
            handler=lambda req: (_ for _ in ()).throw(
                requests.ConnectionError("c2 fake conn error")
            )
        )
        with _patch_transport(spy):
            with self.assertRaises(SafetyViolation) as ctx:
                safety.build_client(RunMode.TESTNET, "c2-test")
            self.assertIn("connect failed", str(ctx.exception))
            self.assertIn("c2 fake conn error", str(ctx.exception))
        self.assertEqual(len(spy.calls), 1)
        for host in spy.hosts():
            self.assertTrue(_host_allowed(host), host)

    def test_error_response_not_silently_retried_elsewhere(self):
        self.set_testnet_env()
        spy = TransportSpy(
            handler=lambda req: _fake_response(req, status=500, body=b"<html/>")
        )
        with _patch_transport(spy):
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.TESTNET, "c2-test")
        self.assertEqual(len(spy.calls), 1)


if __name__ == "__main__":
    unittest.main()
