"""G0-4D read-only TESTNET probe contracts; all tests are offline."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.ops_testnet_probe import ReadOnlyTestnetProbe, main  # noqa: E402
from aurora.p0_boundary import SafetyViolation  # noqa: E402


ALGO = {
    "algoId": 42,
    "clientAlgoId": "V5S_XRP_1",
    "symbol": "BTCUSDT",
    "side": "SELL",
    "positionSide": "BOTH",
    "type": "STOP_MARKET",
    "triggerPrice": "9",
    "quantity": "100",
    "closePosition": False,
    "workingType": "MARK_PRICE",
    "algoStatus": "NEW",
    "actualOrderId": "",
}

TRADE = {
    "symbol": "BTCUSDT", "orderId": 28574233916, "qty": "0.007",
    "price": "79680.2", "realizedPnl": "0", "commission": "0.0001",
    "time": 1788711270591,
}

ORDER = {
    "orderId": 28574233916, "clientOrderId": "AURORA-x-ENTRY",
    "symbol": "BTCUSDT", "status": "FILLED", "time": 1788711270591,
    "updateTime": 1788711270591,
}


class StrictGetOnlyTransport:
    """传输间谍：任何写形方法立即失败（POST/DELETE 零容忍）；
    未知属性按标准 AttributeError 处理（getattr 默认值可用）。"""

    WRITE_MARKERS = ("post", "put", "delete", "patch", "create", "cancel",
                     "change", "margin", "leverage", "countdown", "modify")
    testnet = True
    FUTURES_TESTNET_URL = "https://testnet.binancefuture.com/fapi"
    FUTURES_URL = "https://fapi.binance.com/fapi"

    def __init__(self):
        self.calls = []
        self.recorded_writes = []

    def __getattr__(self, name):
        lowered = name.lower()
        if any(m in lowered for m in self.WRITE_MARKERS):
            def _write(*args, **kwargs):
                self.recorded_writes.append(name)
                raise AssertionError(f"write attempted via {name}")
            return _write
        raise AttributeError(
            f"transport method not allowlisted: {name}")

    def futures_ping(self):
        self.calls.append(("get", "ping", {}))
        return {}

    def futures_get_position_mode(self):
        self.calls.append(("get", "positionSide/dual", {}))
        return {"dualSidePosition": True}

    def futures_position_information(self, **params):
        self.calls.append(("get", "positionRisk", params))
        return [{
            "symbol": "BTCUSDT", "positionAmt": "0",
            "positionSide": "LONG", "entryPrice": "0",
        }]

    def futures_get_open_orders(self, **params):
        self.calls.append(("get", "openOrders", params))
        return []

    def _request_futures_api(self, method, path, signed=False, **kwargs):
        self.calls.append((method, path, kwargs.get("data") or {}))
        if method.lower() != "get":
            self.recorded_writes.append(f"{method} {path}")
            raise AssertionError(f"write attempted: {method} {path}")
        if path == "accountConfig":
            return {"dualSidePosition": True, "multiAssetsMargin": False}
        if path == "openAlgoOrders":
            xrp = dict(ALGO)
            xrp["algoId"] = 43
            xrp["clientAlgoId"] = "V5S_XRP_2"
            xrp["symbol"] = "XRPUSDT"
            return [dict(ALGO), xrp]
        if path == "algoOrder":
            return dict(ALGO)
        if path == "rateLimit/order":
            return [{
                "rateLimitType": "ORDERS", "interval": "MINUTE",
                "intervalNum": 1, "limit": 1200,
            }]
        if path == "userTrades":
            data = kwargs.get("data") or {}
            self.calls.append(("get", "userTrades:params", dict(data)))
            if data.get("startTime") == 0 and data.get("endTime") == 0:
                return []
            return [dict(TRADE)]
        if path == "allOrders":
            return [dict(ORDER)]
        raise AssertionError(path)


def _state_tree_digest(root):
    digest = hashlib.sha256()
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            fh_path = os.path.join(base, name)
            digest.update(fh_path.encode())
            try:
                with open(fh_path, "rb") as fh:
                    digest.update(fh.read())
            except OSError:
                digest.update(b"<unreadable>")
    return digest.hexdigest()


class ProbeContractTests(unittest.TestCase):
    def setUp(self):
        self.client = StrictGetOnlyTransport()

    def test_full_probe_is_get_only_and_schema_matches(self):
        result = ReadOnlyTestnetProbe(self.client).run("V5S_XRP_1")
        self.assertEqual(result["probe"], "G0-4D_TESTNET_READ_ONLY")
        self.assertEqual(result["writeCapabilities"], "ABSENT")
        self.assertEqual(result["hostReachable"]["status"], "PASS")
        self.assertEqual(result["positionMode"], {"status": "PASS", "value": "HEDGE"})
        self.assertEqual(result["accountConfig"]["status"], "PASS")
        self.assertEqual(result["positions"]["btcusdtPositionState"], "FLAT")
        self.assertEqual(result["openOrders"]["status"], "EMPTY")
        self.assertEqual(result["openAlgoOrders"]["status"], "PASS")
        self.assertEqual(result["algoQuery"]["schema"], "MATCHES_G0_4A")
        self.assertTrue(result["algoQuery"]["workingTypeMatches"])
        self.assertEqual(result["orderRateLimit"]["status"], "PASS")
        self.assertTrue(all(call[0] == "get" for call in self.client.calls))
        self.assertEqual(self.client.recorded_writes, [])

    def test_any_write_transport_fails_immediately(self):
        # 间谍在类层面把一切 POST/DELETE/写方法变成立即失败；
        # 探针跑完仍然零写入、零异常逃逸。
        result = ReadOnlyTestnetProbe(self.client).run()
        self.assertEqual(self.client.recorded_writes, [])
        for section in ("hostReachable", "positionMode", "positions",
                        "openOrders", "openAlgoOrdersAllSymbols",
                        "openAlgoOrders", "userTrades", "allOrders",
                        "orderRateLimit"):
            self.assertIn(section, result)

    def test_shared_account_observation_records_cross_symbol(self):
        result = ReadOnlyTestnetProbe(self.client).run()
        observed = result["openAlgoOrdersAllSymbols"]
        self.assertEqual(observed["status"], "PASS")
        self.assertIn("XRPUSDT", observed["crossSymbolDistinct"])
        self.assertIn("BTCUSDT", observed["crossSymbolDistinct"])
        self.assertIn("V5S_XRP_1", observed["nonAuroraClientIdsObserved"])
        self.assertIn("V5S_XRP_2", observed["nonAuroraClientIdsObserved"])

    def test_specific_algo_query_auto_selects_existing_id_only(self):
        result = ReadOnlyTestnetProbe(self.client).run()
        self.assertEqual(result["algoQuery"]["status"], "PASS")
        self.assertEqual(result["algoQuery"]["queriedId"], "V5S_XRP_1")
        self.assertEqual(result["algoQuery"]["idSource"],
                         "auto-selected-from-open-list")

    def test_empty_algo_list_means_specific_query_not_run(self):
        original = self.client._request_futures_api

        def request(method, path, signed=False, **kwargs):
            if path == "openAlgoOrders":
                self.client.calls.append((method, path, kwargs.get("data") or {}))
                return []
            return original(method, path, signed, **kwargs)

        self.client._request_futures_api = request
        result = ReadOnlyTestnetProbe(self.client).run()
        self.assertEqual(result["openAlgoOrdersAllSymbols"]["status"], "EMPTY")
        self.assertEqual(result["algoQuery"]["status"], "NOT_RUN")
        self.assertFalse(any(path == "algoOrder" for _, path, _ in self.client.calls))

    def test_trades_window_and_paging_probes_present(self):
        result = ReadOnlyTestnetProbe(self.client).run()
        trades = result["userTrades"]
        self.assertEqual(trades["status"], "PASS")
        self.assertIn("fromIdPaging", trades)
        self.assertEqual(trades["fromIdPaging"]["status"], "PASS")
        self.assertIn("timeWindowCall", trades)
        all_orders = result["allOrders"]
        self.assertEqual(all_orders["status"], "PASS")
        self.assertEqual(all_orders["orderIdAnchor"]["status"], "PASS")

    def test_incomplete_schema_fails_closed(self):
        original = self.client._request_futures_api

        def request(method, path, signed=False, **kwargs):
            if path == "openAlgoOrders":
                return [{"algoId": 1}]
            return original(method, path, signed, **kwargs)

        self.client._request_futures_api = request
        result = ReadOnlyTestnetProbe(self.client).run()
        self.assertEqual(result["openAlgoOrders"]["status"], "CONTRACT_INCOMPLETE")
        self.assertIn("clientAlgoId", result["openAlgoOrders"]["missing"])

    def test_read_path_allowlist_rejects_unknown(self):
        with self.assertRaises(SafetyViolation):
            ReadOnlyTestnetProbe(StrictGetOnlyTransport())._signed_get("order")

    def test_identity_block_consistency_fields(self):
        identity = {
            "trading_mode": "TESTNET",
            "expectedPositionMode": "HEDGE",
            "accountFingerprint": "3fbc5d4f1f9ddc7d",
            "accountExclusivity": "false",
        }
        result = ReadOnlyTestnetProbe(self.client).run(identity=identity)
        identity_out = result["identity"]
        self.assertEqual(identity_out["observedPositionMode"], "HEDGE")
        self.assertTrue(identity_out["positionModeMatchesExpected"])
        self.assertEqual(identity_out["accountExclusivity"], "false")

    def test_errors_report_type_not_exception_message(self):
        def fail():
            raise RuntimeError("secret-like-sensitive-message")

        self.client.futures_get_position_mode = fail
        result = ReadOnlyTestnetProbe(self.client).run()
        rendered = json.dumps(result)
        self.assertEqual(result["positionMode"]["status"], "ERROR")
        self.assertNotIn("secret-like-sensitive-message", rendered)

    def test_missing_explicit_env_blocks_without_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "missing.env")
            with mock.patch("aurora.safety.build_client") as build:
                code = main(["--env-file", missing])
            self.assertEqual(code, 2)
            build.assert_not_called()

    def test_main_uses_config_source_not_load_dotenv(self):
        import inspect
        from aurora import ops_testnet_probe
        src = inspect.getsource(ops_testnet_probe)
        self.assertNotIn("load_dotenv", src)
        self.assertIn("ConfigSource", src)
        self.assertNotIn("production_main", src)

    def test_probe_execution_leaves_state_tree_byte_identical(self):
        root = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))), "state")
        before = _state_tree_digest(root)
        ReadOnlyTestnetProbe(self.client).run("V5S_XRP_1")
        after = _state_tree_digest(root)
        self.assertEqual(before, after)  # state 树逐字节不变

    def test_no_ledger_or_kill_imports_in_probe(self):
        import inspect
        from aurora import ops_testnet_probe
        src = inspect.getsource(ops_testnet_probe)
        for banned in ("ArmedRuntime", "kernel.ledger", "Ledger(",
                       "engage_kill", "clear_kill", "production_main",
                       "submit_order(", "cancel_order("):
            self.assertNotIn(banned, src, banned)


if __name__ == "__main__":
    unittest.main()
