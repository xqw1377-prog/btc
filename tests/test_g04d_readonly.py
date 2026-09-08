"""G0-4D 只读资格复核：离线合同。零出网。"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.ops_g04d_readonly import (  # noqa: E402
    INCIDENT_ENTRY_ORDER_ID,
    INCIDENT_ENTRY_TRADE_ID,
    INCIDENT_FINGERPRINT,
    G04DReadonlyRequal,
    install_readonly_http_guard,
    main,
    wrap_futures_get_allowlist,
)
from aurora.p0_boundary import SafetyViolation  # noqa: E402


ENTRY_TRADE = {
    "symbol": "BTCUSDT",
    "id": INCIDENT_ENTRY_TRADE_ID,
    "orderId": INCIDENT_ENTRY_ORDER_ID,
    "side": "BUY",
    "qty": "0.0070",
    "time": 1788711270591,
    "positionSide": "LONG",
}
ENTRY_ORDER = {
    "orderId": INCIDENT_ENTRY_ORDER_ID,
    "clientOrderId": "AURORA-0650a39f56e3-ENTRY",
    "symbol": "BTCUSDT",
    "status": "FILLED",
    "side": "BUY",
}
ALGO_FOREIGN = {
    "algoId": 1,
    "clientAlgoId": "V5S_XRP_1",
    "symbol": "XRPUSDT",
    "side": "SELL",
    "positionSide": "LONG",
    "type": "STOP_MARKET",
    "triggerPrice": "1",
    "quantity": "1",
    "closePosition": False,
    "workingType": "MARK_PRICE",
    "algoStatus": "NEW",
}


class FakeRequest:
    def __init__(self, method, url="https://testnet.binancefuture.com/fapi/v1/ping"):
        self.method = method
        self.url = url


class FakeSession:
    def __init__(self):
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append((request.method, request.url, kwargs))
        return {"ok": True}


class ReadClient:
    testnet = True
    FUTURES_TESTNET_URL = "https://testnet.binancefuture.com/fapi"

    def __init__(self):
        self.calls = []
        self.session = FakeSession()
        self.position_rows = [
            {"symbol": "BTCUSDT", "positionAmt": "0.0000", "positionSide": "LONG"},
            {"symbol": "BTCUSDT", "positionAmt": "0.0000", "positionSide": "SHORT"},
        ]
        self.open_orders = []
        self.algos = [dict(ALGO_FOREIGN)]
        self.trades = [dict(ENTRY_TRADE)]
        self.orders = [dict(ENTRY_ORDER)]

    def futures_ping(self):
        self.calls.append(("get", "ping"))
        return {}

    def futures_get_position_mode(self):
        self.calls.append(("get", "positionSide/dual"))
        return {"dualSidePosition": True}

    def futures_position_information(self, **params):
        self.calls.append(("get", "positionRisk", params))
        return list(self.position_rows)

    def futures_get_open_orders(self, **params):
        self.calls.append(("get", "openOrders", params))
        return list(self.open_orders)

    def futures_account_trades(self, **params):
        self.calls.append(("get", "userTrades", params))
        return list(self.trades)

    def futures_get_all_orders(self, **params):
        self.calls.append(("get", "allOrders", params))
        return list(self.orders)

    def _request_futures_api(self, method, path, signed=False, **kwargs):
        self.calls.append((method, path, kwargs.get("data") or {}))
        if method != "get":
            raise AssertionError(f"write attempted: {method} {path}")
        if path == "accountConfig":
            return {"dualSidePosition": True, "multiAssetsMargin": False}
        if path == "openAlgoOrders":
            return list(self.algos)
        if path == "rateLimit/order":
            return [{
                "rateLimitType": "ORDERS", "interval": "MINUTE",
                "intervalNum": 1, "limit": 1200,
            }]
        raise AssertionError(path)


class G04DOfflineTests(unittest.TestCase):
    def test_happy_path_is_closed_readonly_with_partial_evidence(self):
        result = G04DReadonlyRequal(ReadClient()).run(INCIDENT_FINGERPRINT)
        self.assertEqual(result["writeCapabilities"], "ABSENT")
        self.assertEqual(result["contracts"]["authentication"], "PASS")
        self.assertEqual(result["contracts"]["readProtocol"], "PASS")
        self.assertEqual(result["contracts"]["recoveryEvidence"], "PARTIAL")
        self.assertEqual(result["g04d"], "CLOSED-READONLY")
        self.assertFalse(result["systemExecutionQualified"])
        self.assertEqual(result["killClear"], "DENIED")
        self.assertEqual(result["recoveryEvidence"]["manualCloseFill"], "NOT_FOUND")

    def test_http_guard_denies_post_and_delete(self):
        client = ReadClient()
        install_readonly_http_guard(client)
        with self.assertRaises(SafetyViolation):
            client.session.send(FakeRequest("POST"))
        with self.assertRaises(SafetyViolation):
            client.session.send(FakeRequest("DELETE"))
        self.assertEqual(client.session.send(FakeRequest("GET")), {"ok": True})

    def test_futures_allowlist_denies_order_post(self):
        client = ReadClient()
        wrap_futures_get_allowlist(client)
        with self.assertRaises(SafetyViolation):
            client._request_futures_api("post", "order", True, data={})
        with self.assertRaises(SafetyViolation):
            client._request_futures_api("get", "leverage", True, data={})

    def test_futures_allowlist_forwards_version_positional(self):
        client = ReadClient()
        seen = []
        original = client._request_futures_api

        def raw(method, path, signed=False, version=1, **kwargs):
            seen.append(version)
            return original(method, path, signed, **kwargs)

        client._request_futures_api = raw
        wrap_futures_get_allowlist(client)
        client._request_futures_api("get", "accountConfig", True, 2, data={})
        self.assertEqual(seen, [2])

    def test_unexplained_position_fails_closed(self):
        client = ReadClient()
        client.position_rows[0]["positionAmt"] = "0.007"
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertIn("BTCUSDT_UNEXPLAINED_POSITION", result["failClosed"])
        self.assertEqual(result["g04d"], "FAIL")

    def test_position_mode_drift_fails_closed(self):
        client = ReadClient()
        client.futures_get_position_mode = lambda: {"dualSidePosition": False}
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertIn("POSITION_MODE_DRIFT", result["failClosed"])
        self.assertEqual(result["g04d"], "FAIL")

    def test_open_order_residual_fails_closed(self):
        client = ReadClient()
        client.open_orders = [{
            "orderId": 9, "clientOrderId": "x", "symbol": "BTCUSDT",
            "status": "NEW", "side": "SELL",
        }]
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertIn("ORDINARY_OPEN_ORDERS_RESIDUAL", result["failClosed"])
        self.assertEqual(result["g04d"], "FAIL")

    def test_aurora_btc_algo_fails_closed(self):
        client = ReadClient()
        client.algos = [{
            **ALGO_FOREIGN,
            "clientAlgoId": "AURORA-0650a39f56e3-SL",
            "symbol": "BTCUSDT",
        }]
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertIn("AURORA_BTCUSDT_ALGO_RESIDUAL", result["failClosed"])
        self.assertEqual(result["g04d"], "FAIL")

    def test_wrong_fingerprint_fails_auth(self):
        result = G04DReadonlyRequal(ReadClient()).run("deadbeefdeadbeef")
        self.assertEqual(result["contracts"]["authentication"], "FAIL")
        self.assertEqual(result["g04d"], "FAIL")

    def test_full_page_without_sell_is_not_proven(self):
        client = ReadClient()
        client.trades = [dict(ENTRY_TRADE) for _ in range(1000)]
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertEqual(result["contracts"]["recoveryEvidence"], "NOT-PROVEN")
        self.assertEqual(result["g04d"], "PARTIAL")

    def test_found_sell_is_recovery_pass(self):
        client = ReadClient()
        client.trades.append({
            "symbol": "BTCUSDT", "id": 1, "orderId": 2, "side": "SELL",
            "qty": "0.0070", "time": 1, "positionSide": "LONG",
        })
        result = G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT)
        self.assertEqual(result["contracts"]["recoveryEvidence"], "PASS")
        self.assertEqual(result["g04d"], "CLOSED-READONLY")

    def test_foreign_algo_is_not_fail(self):
        result = G04DReadonlyRequal(ReadClient()).run(INCIDENT_FINGERPRINT)
        self.assertNotIn("AURORA_BTCUSDT_ALGO_RESIDUAL", result["failClosed"])
        self.assertEqual(result["reads"]["openAlgoOrders"]["foreign"][0]["symbol"], "XRPUSDT")

    def test_errors_do_not_leak_message(self):
        client = ReadClient()

        def fail():
            raise RuntimeError("secret-like-sensitive-message")

        client.futures_get_position_mode = fail
        rendered = json.dumps(G04DReadonlyRequal(client).run(INCIDENT_FINGERPRINT))
        self.assertNotIn("secret-like-sensitive-message", rendered)

    def test_source_has_no_dotenv_loader(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "aurora", "ops_g04d_readonly.py")).read()
        self.assertNotIn("load_dotenv", src)
        self.assertIn("ConfigSource", src)

    def test_main_missing_env_does_not_build_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "missing.env")
            with mock.patch("aurora.safety.build_client") as build:
                code = main([
                    "--env-file", missing,
                    "--i-understand-readonly-requal",
                ])
            self.assertEqual(code, 2)
            build.assert_not_called()

    def test_main_requires_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            open(path, "w").write("TRADING_MODE=TESTNET\n")
            with mock.patch("aurora.safety.build_client") as build:
                code = main(["--env-file", path])
            self.assertEqual(code, 2)
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
