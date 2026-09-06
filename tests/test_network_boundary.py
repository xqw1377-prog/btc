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

    def test_authorized_live_refused_before_construction(self):
        # 授权齐全只代表通过身份与开关检查；SDK 构造期 spot ping 会打向
        # 主网 api 主机，而 ALLOWED_LIVE_HOSTS 未包含它——正向白名单校验
        # 必须在实例化之前拒绝，且适配器 0 次。使用真实 Client 类常量。
        self.set_live_env()
        spy = TransportSpy()
        with _patch_transport(spy):
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.LIVE, "c2-test")
            self.assertEqual(len(spy.calls), 0)
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


class ConstructionTargetStrictTests(ScrubbedEnv):
    """构造期首跳目标必须是解析完成的明确允许地址，不是仅'非 testnet'。

    反例覆盖：非 https、未批准端口、URL 用户信息、未批准 host。
    校验发生在 Client 实例化之前——适配器必须 0 次。
    """

    def _assert_refused(self, attr, bad_url):
        from binance.client import Client

        self.set_testnet_env()
        spy = TransportSpy()
        with _patch_transport(spy), mock.patch.object(
            Client, attr, bad_url
        ):
            with self.assertRaises(SafetyViolation):
                safety.build_client(RunMode.TESTNET, "c2-test")
            self.assertEqual(len(spy.calls), 0)

    def test_spot_ping_non_testnet_unapproved_host(self):
        # 授权齐全、期货目标合法，但 spot ping 目标被改成
        # 非测试网、未批准的地址——必须在到达传输层前拒绝。
        self._assert_refused(
            "API_TESTNET_URL", "https://attacker.example.com/api"
        )

    def test_spot_ping_http_scheme(self):
        self._assert_refused(
            "API_TESTNET_URL", "http://testnet.binance.vision/api"
        )

    def test_spot_ping_unapproved_port(self):
        self._assert_refused(
            "API_TESTNET_URL", "https://testnet.binance.vision:8443/api"
        )

    def test_spot_ping_url_userinfo(self):
        self._assert_refused(
            "API_TESTNET_URL", "https://user:pw@testnet.binance.vision/api"
        )

    def test_futures_target_unapproved_host(self):
        self._assert_refused(
            "FUTURES_TESTNET_URL", "https://futures.attacker.example.com/fapi"
        )


class RedirectEnforcementTests(ScrubbedEnv):
    """禁止重定向是传输边界强制规则，调用方不能重新打开第二跳。"""

    REDIRECT_CODES = (301, 302, 303, 307, 308)

    def _client(self, spy):
        self.set_testnet_env()
        with _patch_transport(spy):
            return safety.build_client(RunMode.TESTNET, "c2-test")

    def test_per_request_redirect_override_refused(self):
        # SDK 1.0.19 合并顺序允许单次请求的 requests_params 覆盖全局参数；
        # 传输守卫必须在该覆盖生效前拒绝。
        spy = TransportSpy()
        client = self._client(spy)
        with _patch_transport(spy):
            before = len(spy.calls)
            with self.assertRaises(SafetyViolation):
                client.futures_account(
                    requests_params={"allow_redirects": True}
                )
            self.assertEqual(len(spy.calls), before)

    def test_redirect_sweep_not_followed_same_and_cross_host(self):
        for code in self.REDIRECT_CODES:
            for location in (
                "https://testnet.binancefuture.com/fapi/v1/other",  # 同允许 host
                "https://fapi.binance.com/fapi/v1/other",           # 主网
                "https://unknown.example.com/x",                    # 未知 host
            ):
                with self.subTest(code=code, location=location):
                    spy = TransportSpy()
                    client = self._client(spy)
                    with _patch_transport(spy):
                        spy.handler = lambda req, c=code, loc=location: _fake_response(
                            req, status=c, headers={"Location": loc}
                        )
                        before = len(spy.calls)
                        with self.assertRaises(Exception):
                            client.futures_account()
                        self.assertEqual(len(spy.calls), before + 1)
                        for host in spy.hosts():
                            self.assertTrue(_host_allowed(host), host)

    def test_direct_session_send_default_no_redirect(self):
        # 直接调用受控 session.send 且未传参数：requests 默认允许重定向，
        # 守卫必须强制关闭——302 只应产生一次适配器调用。
        spy = TransportSpy()
        client = self._client(spy)
        with _patch_transport(spy):
            prep = client.session.prepare_request(
                requests.Request(
                    "GET", "https://testnet.binancefuture.com/fapi/v1/time"
                )
            )
            spy.handler = lambda req: _fake_response(
                req, status=302, headers={"Location": "https://fapi.binance.com/x"}
            )
            before = len(spy.calls)
            resp = client.session.send(prep, timeout=1)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(len(spy.calls), before + 1)

    def test_direct_session_send_explicit_redirect_refused(self):
        spy = TransportSpy()
        client = self._client(spy)
        with _patch_transport(spy):
            prep = client.session.prepare_request(
                requests.Request(
                    "GET", "https://testnet.binancefuture.com/fapi/v1/time"
                )
            )
            before = len(spy.calls)
            with self.assertRaises(SafetyViolation):
                client.session.send(prep, allow_redirects=True, timeout=1)
            self.assertEqual(len(spy.calls), before)


if __name__ == "__main__":
    unittest.main()
