"""G0-4D read-only Binance USDⓈ-M TESTNET protocol probe (requalification).

This command only performs GET requests. It never attaches the armed
execution runtime, never opens the local ledger, never clears kill state,
never submits or cancels any order, and never changes account
configuration. Configuration comes from ONE ConfigSource (--env-file,
explicit path, no parent search); os.environ is never mutated.

Incident-disposition context: this probe is the FIRST step of testnet
requalification (INCIDENT_REQUALIFICATION_ELIGIBLE=YES, c612c8d). It grants
no trading capability: every write verb (POST/DELETE) is unreachable by
allowlist, and transport spies in the contract tests fail immediately on any
non-GET.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from aurora.kernel.binance_exchange import ALGO_WORKING_TYPE, BinanceExchange
from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    effective_futures_url,
    key_fingerprint,
)

# GET-only 白名单：任何其他 path 在发送前拒绝。
_READ_PATHS = frozenset((
    "accountConfig", "openAlgoOrders", "algoOrder", "rateLimit/order",
    "userTrades", "allOrders",
))
_ALGO_FIELDS = frozenset((
    "algoId", "clientAlgoId", "symbol", "side", "positionSide", "type",
    "triggerPrice", "quantity", "closePosition", "workingType", "algoStatus",
))
_TRADES_FIELDS = frozenset((
    "symbol", "orderId", "qty", "price", "realizedPnl", "commission", "time",
))
_ALL_ORDERS_FIELDS = frozenset((
    "orderId", "clientOrderId", "symbol", "status", "time", "updateTime",
))


def default_env_file() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )


def _error(exc: BaseException) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "ERROR",
        "errorType": type(exc).__name__,
    }
    code = getattr(exc, "code", None)
    status = getattr(exc, "status_code", None)
    if code is not None:
        result["code"] = code
    if status is not None:
        result["httpStatus"] = status
    return result


def _schema(rows: Any, required: frozenset) -> Dict[str, Any]:
    if not isinstance(rows, list):
        return {"status": "CONTRACT_INCOMPLETE", "reason": "response is not a list"}
    if not rows:
        return {"status": "EMPTY", "count": 0, "schema": "NOT_OBSERVED"}
    missing = sorted(required - set(rows[0]))
    if missing:
        return {"status": "CONTRACT_INCOMPLETE", "count": len(rows), "missing": missing}
    return {"status": "PASS", "count": len(rows), "schema": "OBSERVED"}


class ReadOnlyTestnetProbe:
    """Capability whitelist: public/signed GET only."""

    def __init__(self, client: Any, symbol: str = "BTCUSDT"):
        self.client = client
        self.symbol = symbol

    def _signed_get(self, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
        if path not in _READ_PATHS:
            raise SafetyViolation(f"[G0-4D] read path not allowlisted: {path}")
        return self.client._request_futures_api(
            "get", path, True, data=dict(data or {}))

    def run(
        self,
        client_algo_id: Optional[str] = None,
        identity: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "probe": "G0-4D_TESTNET_READ_ONLY",
            "symbol": self.symbol,
            "futuresHost": effective_futures_url(self.client),
            "writeCapabilities": "ABSENT",
        }

        try:
            raw = self.client.futures_ping()
            result["hostReachable"] = {
                "status": "PASS" if isinstance(raw, dict) else "CONTRACT_INCOMPLETE"
            }
        except Exception as exc:
            result["hostReachable"] = _error(exc)

        observed_mode: Optional[str] = None
        try:
            raw = self.client.futures_get_position_mode()
            dual = raw.get("dualSidePosition") if isinstance(raw, dict) else None
            if isinstance(dual, str) and dual.lower() in ("true", "false"):
                dual = dual.lower() == "true"
            if isinstance(dual, bool):
                observed_mode = "HEDGE" if dual else "ONE_WAY"
                result["positionMode"] = {"status": "PASS", "value": observed_mode}
            else:
                result["positionMode"] = {"status": "CONTRACT_INCOMPLETE"}
        except Exception as exc:
            result["positionMode"] = _error(exc)

        try:
            raw = self._signed_get("accountConfig")
            required = {"dualSidePosition"}
            missing = sorted(required - set(raw)) if isinstance(raw, dict) else sorted(required)
            result["accountConfig"] = (
                {"status": "PASS", "fields": sorted(raw)}
                if isinstance(raw, dict) and not missing
                else {"status": "CONTRACT_INCOMPLETE", "missing": missing}
            )
        except Exception as exc:
            result["accountConfig"] = _error(exc)

        try:
            rows = self.client.futures_position_information(symbol=self.symbol)
            info = _schema(rows, frozenset(("symbol", "positionAmt", "positionSide")))
            if isinstance(rows, list):
                open_legs = [
                    row for row in rows
                    if isinstance(row, dict) and float(row.get("positionAmt") or 0) != 0
                ]
                info["openLegs"] = len(open_legs)
                info["btcusdtPositionState"] = (
                    "OPEN" if open_legs else "FLAT")
            result["positions"] = info
        except Exception as exc:
            result["positions"] = _error(exc)

        try:
            rows = self.client.futures_get_open_orders(symbol=self.symbol)
            result["openOrders"] = _schema(
                rows, frozenset(("orderId", "clientOrderId", "symbol", "status")))
        except Exception as exc:
            result["openOrders"] = _error(exc)

        # 共享账户观察（ACCOUNT_EXCLUSIVITY=FALSE 的现场证据）：
        # 不带 symbol 的全账户 Algo 列表 + 跨品种计数。只观察，不解释成
        # AURORA 事实。
        algo_rows_all: Any = None
        try:
            algo_rows_all = self._signed_get("openAlgoOrders")
            all_algo = _schema(algo_rows_all, _ALGO_FIELDS)
            if isinstance(algo_rows_all, list):
                symbols = sorted({
                    str(r.get("symbol")) for r in algo_rows_all if isinstance(r, dict)})
                all_algo["crossSymbolDistinct"] = symbols
                all_algo["nonAuroraClientIdsObserved"] = sorted(
                    str(r.get("clientAlgoId")) for r in algo_rows_all
                    if isinstance(r, dict)
                    and not str(r.get("clientAlgoId", "")).startswith("AURORA-"))
            result["openAlgoOrdersAllSymbols"] = all_algo
        except Exception as exc:
            result["openAlgoOrdersAllSymbols"] = _error(exc)

        try:
            rows = self._signed_get("openAlgoOrders", {"symbol": self.symbol})
            result["openAlgoOrders"] = _schema(rows, _ALGO_FIELDS)
        except Exception as exc:
            result["openAlgoOrders"] = _error(exc)

        # 单条 Algo 查询：仅允许已有 id。显式给出优先；否则自动取全账户
        # 列表中第一个已观察到的 clientAlgoId（只读已存在对象，绝不臆造）。
        effective_id = client_algo_id
        id_source = "explicit"
        if effective_id is None and isinstance(algo_rows_all, list) and algo_rows_all:
            first = algo_rows_all[0]
            if isinstance(first, dict) and first.get("clientAlgoId"):
                effective_id = str(first["clientAlgoId"])
                id_source = "auto-selected-from-open-list"
        if effective_id is None:
            result["algoQuery"] = {"status": "NOT_RUN",
                                   "reason": "no existing clientAlgoId supplied or observed"}
        else:
            try:
                fact = BinanceExchange(
                    self.client, symbol=self.symbol, allow_mutate=False
                ).query_algo_order(effective_id)
                result["algoQuery"] = (
                    {
                        "status": "PASS",
                        "schema": "MATCHES_G0_4A",
                        "queriedId": effective_id,
                        "idSource": id_source,
                        "algoStatus": fact.status,
                        "workingType": fact.working_type,
                        "workingTypeMatches": fact.working_type == ALGO_WORKING_TYPE,
                        "actualOrderLinked": fact.actual_order_id is not None,
                    }
                    if fact is not None
                    else {"status": "NOT_FOUND", "queriedId": effective_id,
                          "idSource": id_source}
                )
            except Exception as exc:
                result["algoQuery"] = _error(exc)

        # 成交/订单历史窗口能力（问题 7：恢复所需查询窗口是否充分）
        try:
            trades = self._signed_get(
                "userTrades", {"symbol": self.symbol, "limit": 10})
            trades_info = _schema(trades, _TRADES_FIELDS)
            if isinstance(trades, list) and trades:
                first_id = trades[0].get("id")
                # fromId 分页探测：以已观察 id 为锚点（不臆造）
                paged = self._signed_get(
                    "userTrades",
                    {"symbol": self.symbol, "fromId": first_id, "limit": 10})
                trades_info["fromIdPaging"] = (
                    {"status": "PASS", "anchorId": str(first_id)}
                    if isinstance(paged, list) and paged
                    else {"status": "EMPTY_OR_UNSUPPORTED"})
                window = self._signed_get(
                    "userTrades",
                    {"symbol": self.symbol, "startTime": 0, "endTime": 0,
                     "limit": 10})
                trades_info["timeWindowCall"] = (
                    {"status": "PASS(EMPTY_WINDOW)"}
                    if isinstance(window, list)
                    else {"status": "REJECTED"})
            result["userTrades"] = trades_info
        except Exception as exc:
            result["userTrades"] = _error(exc)

        try:
            rows = self._signed_get("allOrders", {"symbol": self.symbol, "limit": 10})
            all_orders = _schema(rows, _ALL_ORDERS_FIELDS)
            if isinstance(rows, list) and rows:
                oid = rows[0].get("orderId")
                by_id = self._signed_get(
                    "allOrders",
                    {"symbol": self.symbol, "orderId": oid, "limit": 10})
                all_orders["orderIdAnchor"] = (
                    {"status": "PASS", "anchorId": str(oid)}
                    if isinstance(by_id, list) else {"status": "REJECTED"})
            result["allOrders"] = all_orders
        except Exception as exc:
            result["allOrders"] = _error(exc)

        try:
            rows = self._signed_get("rateLimit/order")
            result["orderRateLimit"] = _schema(
                rows, frozenset(("rateLimitType", "interval", "intervalNum", "limit")))
        except Exception as exc:
            result["orderRateLimit"] = _error(exc)

        # G0-5C 身份一致性（问题 8）：配置声明 vs 现场观察
        if identity is not None:
            identity = dict(identity)
            identity["observedPositionMode"] = observed_mode
            identity["positionModeMatchesExpected"] = (
                observed_mode == identity.get("expectedPositionMode")
                if observed_mode is not None else None)
            result["identity"] = identity
        return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="G0-4D TESTNET read-only protocol probe")
    parser.add_argument("--env-file", default=default_env_file())
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--client-algo-id")
    args = parser.parse_args(argv)

    from aurora.config_source import ConfigSource

    env_file = os.path.abspath(args.env_file)
    if not os.path.isfile(env_file):
        print(json.dumps({
            "probe": "G0-4D_TESTNET_READ_ONLY",
            "status": "BLOCKED",
            "reason": "explicit env file not found",
            "envFile": env_file,
        }))
        return 2
    source = ConfigSource.load(env_file=env_file)

    try:
        mode = source.mode()
        if mode != RunMode.TESTNET:
            raise SafetyViolation(
                f"[G0-4D] requires TRADING_MODE=TESTNET, got {mode.value}")
        from aurora.safety import build_client
        client = build_client(mode, "G0-4D read-only protocol probe",
                              environ=source.as_environ())
        identity = {
            **source.config_summary(),
            "accountFingerprint": key_fingerprint(source.get("BINANCE_API_KEY")),
            "expectedPositionMode": (
                source.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE"),
            "accountExclusivity": (
                source.get("AURORA_ACCOUNT_EXCLUSIVITY") or "false"),
        }
        result = ReadOnlyTestnetProbe(client, symbol=args.symbol).run(
            client_algo_id=args.client_algo_id, identity=identity)
    except Exception as exc:
        result = {
            "probe": "G0-4D_TESTNET_READ_ONLY",
            "status": "BLOCKED",
            **_error(exc),
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") != "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
