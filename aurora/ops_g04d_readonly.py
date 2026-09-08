"""G0-4D READ-ONLY TESTNET REQUALIFICATION.

证明三件事，且只通过 authenticated GET：
  AUTHENTICATION CONTRACT
  READ PROTOCOL CONTRACT
  RECOVERY EVIDENCE COMPLETENESS   (PASS / PARTIAL / NOT-PROVEN)

禁止：POST / DELETE / 下单 / 撤单 / 改 mode / 改杠杆 / 清 kill /
启动 production_main / 武装内核。配置只来自 ConfigSource。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from aurora.config_source import ConfigSource, repo_default_env_file
from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    effective_futures_url,
    key_fingerprint,
    resolve_account_fingerprint,
    state_root,
)

INCIDENT_INTENT = "AURORA-0650a39f56e3"
INCIDENT_FINGERPRINT = "3fbc5d4f1f9ddc7d"
INCIDENT_SYMBOL = "BTCUSDT"
INCIDENT_ENTRY_ORDER_ID = 28574233916
INCIDENT_ENTRY_TRADE_ID = 535229485
EXPECTED_POSITION_MODE = "HEDGE"
PAGE_LIMIT = 1000

ALLOWED_FUTURES_GET = frozenset((
    "ping",
    "positionSide/dual",
    "accountConfig",
    "positionRisk",
    "openOrders",
    "allOrders",
    "userTrades",
    "openAlgoOrders",
    "algoOrder",
    "rateLimit/order",
))
# 列表端点只要能判定 AURORA BTC 残留；G0-4A 单笔查询字段另记，不把
# 列表缺 type 误判成资格失败。
_ALGO_ID_FIELDS = frozenset(("clientAlgoId", "symbol", "algoStatus"))
_ALGO_G04A_FIELDS = frozenset((
    "algoId", "side", "positionSide", "type", "triggerPrice", "quantity",
    "closePosition", "workingType",
))
_POS_FIELDS = frozenset(("symbol", "positionAmt", "positionSide"))
_ORDER_FIELDS = frozenset(("orderId", "clientOrderId", "symbol", "status", "side"))
_TRADE_FIELDS = frozenset(("id", "orderId", "symbol", "side", "qty", "time"))
_RATE_FIELDS = frozenset(("rateLimitType", "interval", "intervalNum", "limit"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(exc: BaseException) -> Dict[str, Any]:
    out: Dict[str, Any] = {"status": "ERROR", "errorType": type(exc).__name__}
    code = getattr(exc, "code", None)
    status = getattr(exc, "status_code", None)
    if code is not None:
        out["code"] = code
    if status is not None:
        out["httpStatus"] = status
    return out


def _schema(rows: Any, required: frozenset) -> Dict[str, Any]:
    if not isinstance(rows, list):
        return {"status": "CONTRACT_INCOMPLETE", "reason": "response is not a list"}
    if not rows:
        return {"status": "EMPTY", "count": 0, "schema": "NOT_OBSERVED"}
    missing = sorted(required - set(rows[0]))
    if missing:
        return {
            "status": "CONTRACT_INCOMPLETE",
            "count": len(rows),
            "missing": missing,
        }
    return {"status": "PASS", "count": len(rows), "schema": "OBSERVED"}


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def install_readonly_http_guard(client: Any) -> None:
    """出站层第二道门：HTTP 方法只允许 GET。必须叠在 outbound host 守卫之后。"""
    session = getattr(client, "session", None)
    if session is None:
        raise SafetyViolation("[G0-4D] client has no transport session.")
    if getattr(session, "_aurora_readonly", False) is True:
        return
    inner = session.send

    def _send(request: Any, **kwargs: Any) -> Any:
        method = (getattr(request, "method", "") or "").upper()
        if method != "GET":
            raise SafetyViolation(
                f"[G0-4D] HTTP {method} denied before send."
            )
        return inner(request, **kwargs)

    session.send = _send
    session._aurora_readonly = True


def wrap_futures_get_allowlist(client: Any) -> None:
    raw = client._request_futures_api

    def _guarded(method: str, path: str, signed: bool = False, *args: Any, **kwargs: Any) -> Any:
        if str(method).lower() != "get":
            raise SafetyViolation(f"[G0-4D] futures {method} {path} denied.")
        if path not in ALLOWED_FUTURES_GET:
            raise SafetyViolation(f"[G0-4D] read path not allowlisted: {path}")
        return raw(method, path, signed, *args, **kwargs)

    client._request_futures_api = _guarded


def local_kill_snapshot() -> Dict[str, Any]:
    """只读打开事故遗留账本，确认 kill 仍在。绝不写回。"""
    path = os.path.join(state_root(), "kernel_ledger.db")
    if not os.path.exists(path):
        return {"status": "ABSENT", "path": "state/kernel_ledger.db"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT engaged FROM kill_switch WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"status": "MISSING_ROW", "written": False}
    return {
        "status": "ACTIVE" if int(row[0]) == 1 else "CLEAR",
        "engaged": int(row[0]),
        "written": False,
        "source": "legacy_ledger_readonly",
    }


class G04DReadonlyRequal:
    def __init__(self, client: Any, symbol: str = INCIDENT_SYMBOL):
        self.client = client
        self.symbol = symbol
        self.http_calls: List[str] = []

    def _signed_get(self, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
        self.http_calls.append(path)
        return self.client._request_futures_api(
            "get", path, True, data=dict(data or {}))

    def run(self, expected_fingerprint: str) -> Dict[str, Any]:
        fail_closed: List[str] = []
        report: Dict[str, Any] = {
            "probe": "G0-4D_READ_ONLY_REQUAL",
            "intent": INCIDENT_INTENT,
            "symbol": self.symbol,
            "capturedAt": _utc_now(),
            "writeCapabilities": "ABSENT",
            "httpMethodsAllowed": ["GET"],
            "failClosed": fail_closed,
        }

        host = effective_futures_url(self.client)
        report["futuresHost"] = host
        if "testnet.binancefuture.com" not in (host or "").lower():
            fail_closed.append("ENDPOINT_NOT_TESTNET")

        auth = self._authentication(expected_fingerprint)
        report["authentication"] = auth
        if auth.get("status") != "PASS":
            fail_closed.append("AUTHENTICATION")

        proto_reads = self._protocol_reads()
        report["reads"] = proto_reads

        drift = self._fail_closed_from_reads(proto_reads)
        fail_closed.extend(drift)

        evidence = self._recovery_evidence(proto_reads)
        report["recoveryEvidence"] = evidence

        report["localKill"] = local_kill_snapshot()
        if report["localKill"].get("status") == "CLEAR":
            fail_closed.append("KILL_UNEXPECTEDLY_CLEAR")

        contracts = self._contracts(auth, proto_reads, evidence, fail_closed)
        report["contracts"] = contracts
        report["g04d"] = contracts["g04d"]
        report["systemExecutionQualified"] = False
        report["killClear"] = "DENIED"
        report["autoTestnet"] = "DENIED"
        report["live"] = "NO-GO"
        return report

    def _authentication(self, expected_fingerprint: str) -> Dict[str, Any]:
        try:
            raw = self._signed_get("accountConfig")
        except Exception as exc:
            return {**_error(exc), "fingerprint": expected_fingerprint}
        if not isinstance(raw, dict) or "dualSidePosition" not in raw:
            return {
                "status": "FAIL",
                "reason": "accountConfig missing dualSidePosition",
                "fingerprint": expected_fingerprint,
            }
        if expected_fingerprint != INCIDENT_FINGERPRINT:
            return {
                "status": "FAIL",
                "reason": "fingerprint is not the incident account",
                "fingerprint": expected_fingerprint,
            }
        return {
            "status": "PASS",
            "fingerprint": expected_fingerprint,
            "incidentFingerprint": INCIDENT_FINGERPRINT,
            "accountConfigFields": sorted(raw),
        }

    def _protocol_reads(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        try:
            raw = self.client.futures_ping()
            self.http_calls.append("ping")
            out["hostReachable"] = {
                "status": "PASS" if isinstance(raw, dict) else "CONTRACT_INCOMPLETE"
            }
        except Exception as exc:
            out["hostReachable"] = _error(exc)

        try:
            raw = self.client.futures_get_position_mode()
            self.http_calls.append("positionSide/dual")
            dual = _as_bool(raw.get("dualSidePosition") if isinstance(raw, dict) else None)
            if dual is None:
                out["positionMode"] = {"status": "CONTRACT_INCOMPLETE"}
            else:
                value = "HEDGE" if dual else "ONE_WAY"
                out["positionMode"] = {"status": "PASS", "value": value}
        except Exception as exc:
            out["positionMode"] = _error(exc)

        try:
            rows = self.client.futures_position_information(symbol=self.symbol)
            self.http_calls.append("positionRisk")
            info = _schema(rows, _POS_FIELDS)
            legs = []
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    amt = float(row.get("positionAmt") or 0)
                    if amt != 0:
                        legs.append({
                            "positionSide": row.get("positionSide"),
                            "positionAmt": amt,
                        })
            info["openLegs"] = legs
            out["positions"] = info
        except Exception as exc:
            out["positions"] = _error(exc)

        try:
            rows = self.client.futures_get_open_orders(symbol=self.symbol)
            self.http_calls.append("openOrders")
            out["openOrders"] = _schema(rows, _ORDER_FIELDS)
        except Exception as exc:
            out["openOrders"] = _error(exc)

        try:
            rows = self._signed_get("openAlgoOrders")
            info = _schema(rows, _ALGO_ID_FIELDS)
            if isinstance(rows, list) and rows:
                missing_g04a = sorted(_ALGO_G04A_FIELDS - set(rows[0]))
                info["g04aListFields"] = (
                    "OBSERVED" if not missing_g04a else "PARTIAL"
                )
                if missing_g04a:
                    info["g04aListMissing"] = missing_g04a
            aurora_btc = []
            foreign = []
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    cid = str(row.get("clientAlgoId") or "")
                    rec = {
                        "clientAlgoId": cid,
                        "symbol": row.get("symbol"),
                        "algoStatus": row.get("algoStatus"),
                    }
                    if cid.startswith("AURORA") and row.get("symbol") == self.symbol:
                        aurora_btc.append(rec)
                    else:
                        foreign.append(rec)
            info["auroraBtcusdt"] = aurora_btc
            info["foreign"] = foreign
            out["openAlgoOrders"] = info
        except Exception as exc:
            out["openAlgoOrders"] = _error(exc)

        try:
            rows = self.client.futures_account_trades(
                symbol=self.symbol, limit=PAGE_LIMIT)
            self.http_calls.append("userTrades")
            info = _schema(rows, _TRADE_FIELDS)
            info["pageLimit"] = PAGE_LIMIT
            info["pageFull"] = isinstance(rows, list) and len(rows) >= PAGE_LIMIT
            out["userTrades"] = self._summarize_trades(rows, info)
        except Exception as exc:
            out["userTrades"] = _error(exc)

        try:
            rows = self.client.futures_get_all_orders(
                symbol=self.symbol, limit=PAGE_LIMIT)
            self.http_calls.append("allOrders")
            info = _schema(rows, _ORDER_FIELDS)
            info["pageLimit"] = PAGE_LIMIT
            info["pageFull"] = isinstance(rows, list) and len(rows) >= PAGE_LIMIT
            out["allOrders"] = self._summarize_orders(rows, info)
        except Exception as exc:
            out["allOrders"] = _error(exc)

        try:
            rows = self._signed_get("rateLimit/order")
            out["orderRateLimit"] = _schema(rows, _RATE_FIELDS)
        except Exception as exc:
            out["orderRateLimit"] = _error(exc)

        return out

    def _summarize_trades(self, rows: Any, info: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(rows, list):
            return info
        sells = []
        entry = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            tid = row.get("id")
            if tid == INCIDENT_ENTRY_TRADE_ID:
                entry = {
                    "id": tid,
                    "orderId": row.get("orderId"),
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "positionSide": row.get("positionSide"),
                }
            if str(row.get("side") or "").upper() == "SELL":
                sells.append({
                    "id": tid,
                    "orderId": row.get("orderId"),
                    "qty": row.get("qty"),
                    "time": row.get("time"),
                    "positionSide": row.get("positionSide"),
                })
        info["entryTrade"] = entry or "NOT_FOUND"
        info["sellCount"] = len(sells)
        info["sells"] = sells
        return info

    def _summarize_orders(self, rows: Any, info: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(rows, list):
            return info
        entry = None
        closes = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            oid = row.get("orderId")
            if oid == INCIDENT_ENTRY_ORDER_ID:
                entry = {
                    "orderId": oid,
                    "clientOrderId": row.get("clientOrderId"),
                    "status": row.get("status"),
                    "side": row.get("side"),
                    "executedQty": row.get("executedQty"),
                }
            side = str(row.get("side") or "").upper()
            reduce = row.get("reduceOnly")
            if side == "SELL" or reduce in (True, "true"):
                closes.append({
                    "orderId": oid,
                    "clientOrderId": row.get("clientOrderId"),
                    "status": row.get("status"),
                    "side": side,
                    "reduceOnly": reduce,
                })
        info["entryOrder"] = entry or "NOT_FOUND"
        info["closeOrderCount"] = len(closes)
        info["closeOrders"] = closes
        return info

    def _fail_closed_from_reads(self, reads: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        mode = reads.get("positionMode") or {}
        if mode.get("status") == "PASS" and mode.get("value") != EXPECTED_POSITION_MODE:
            reasons.append("POSITION_MODE_DRIFT")
        elif mode.get("status") != "PASS":
            reasons.append("POSITION_MODE_UNREADABLE")

        pos = reads.get("positions") or {}
        if pos.get("openLegs"):
            reasons.append("BTCUSDT_UNEXPLAINED_POSITION")
        elif pos.get("status") not in ("PASS", "EMPTY"):
            reasons.append("POSITION_UNREADABLE")

        orders = reads.get("openOrders") or {}
        if orders.get("status") == "PASS" and int(orders.get("count") or 0) > 0:
            reasons.append("ORDINARY_OPEN_ORDERS_RESIDUAL")
        elif orders.get("status") not in ("PASS", "EMPTY"):
            reasons.append("OPEN_ORDERS_UNREADABLE")

        algo = reads.get("openAlgoOrders") or {}
        if algo.get("auroraBtcusdt"):
            reasons.append("AURORA_BTCUSDT_ALGO_RESIDUAL")
        elif algo.get("status") not in ("PASS", "EMPTY"):
            reasons.append("ALGO_UNREADABLE")

        for key in ("hostReachable", "userTrades", "allOrders", "orderRateLimit"):
            status = (reads.get(key) or {}).get("status")
            if status in ("ERROR", "CONTRACT_INCOMPLETE"):
                reasons.append(f"{key.upper()}_CONTRACT")
        return reasons

    def _recovery_evidence(self, reads: Dict[str, Any]) -> Dict[str, Any]:
        trades = reads.get("userTrades") or {}
        orders = reads.get("allOrders") or {}
        if trades.get("status") in ("ERROR", "CONTRACT_INCOMPLETE") or orders.get(
            "status"
        ) in ("ERROR", "CONTRACT_INCOMPLETE"):
            return {
                "status": "NOT-PROVEN",
                "reason": "trade/order hunt did not complete",
            }
        if trades.get("pageFull") or orders.get("pageFull"):
            return {
                "status": "NOT-PROVEN",
                "reason": "page was full; window may be truncated",
                "entryTrade": trades.get("entryTrade"),
                "entryOrder": orders.get("entryOrder"),
            }
        sell_found = int(trades.get("sellCount") or 0) > 0
        close_found = int(orders.get("closeOrderCount") or 0) > 0
        if sell_found or close_found:
            return {
                "status": "PASS",
                "manualCloseFill": "FOUND" if sell_found else "NOT_FOUND",
                "manualCloseOrder": "FOUND" if close_found else "NOT_FOUND",
                "sells": trades.get("sells") or [],
                "closeOrders": orders.get("closeOrders") or [],
            }
        return {
            "status": "PARTIAL",
            "reason": "FLAT gap reconfirmed; no authoritative SELL/close",
            "exitMechanism": "UNKNOWN",
            "manualCloseFill": "NOT_FOUND",
            "manualCloseOrder": "NOT_FOUND",
            "exitProvenance": "OPEN / APPEND-ONLY",
            "entryTrade": trades.get("entryTrade"),
            "entryOrder": orders.get("entryOrder"),
        }

    def _contracts(
        self,
        auth: Dict[str, Any],
        reads: Dict[str, Any],
        evidence: Dict[str, Any],
        fail_closed: Iterable[str],
    ) -> Dict[str, Any]:
        failed = list(fail_closed)
        auth_v = "PASS" if auth.get("status") == "PASS" and "AUTHENTICATION" not in failed else "FAIL"

        proto_keys = (
            "hostReachable", "positionMode", "positions", "openOrders",
            "openAlgoOrders", "userTrades", "allOrders", "orderRateLimit",
        )
        proto_states = [(reads.get(k) or {}).get("status") for k in proto_keys]
        if any(s in ("ERROR", "CONTRACT_INCOMPLETE") for s in proto_states):
            proto_v = "FAIL"
        elif any(s is None for s in proto_states):
            proto_v = "PARTIAL"
        else:
            proto_v = "PASS"

        evidence_v = evidence.get("status") or "NOT-PROVEN"
        if failed or auth_v == "FAIL" or proto_v == "FAIL":
            g04d = "FAIL"
        elif evidence_v == "NOT-PROVEN" or proto_v == "PARTIAL":
            g04d = "PARTIAL"
        else:
            g04d = "CLOSED-READONLY"
        return {
            "authentication": auth_v,
            "readProtocol": proto_v,
            "recoveryEvidence": evidence_v,
            "g04d": g04d,
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="G0-4D read-only TESTNET requalification")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--symbol", default=INCIDENT_SYMBOL)
    parser.add_argument("--write-report", default=None)
    parser.add_argument(
        "--i-understand-readonly-requal",
        action="store_true",
        help="required to construct a TESTNET client; still GET-only",
    )
    args = parser.parse_args(argv)

    env_file = os.path.abspath(args.env_file or repo_default_env_file())
    if not os.path.isfile(env_file):
        print(json.dumps({
            "probe": "G0-4D_READ_ONLY_REQUAL",
            "status": "BLOCKED",
            "reason": "explicit env file not found",
            "envFile": env_file,
        }, sort_keys=True))
        return 2
    if not args.i_understand_readonly_requal:
        print(json.dumps({
            "probe": "G0-4D_READ_ONLY_REQUAL",
            "status": "BLOCKED",
            "reason": "pass --i-understand-readonly-requal",
        }, sort_keys=True))
        return 2

    try:
        source = ConfigSource.load(env_file=env_file)
        mode = source.mode()
        if mode != RunMode.TESTNET:
            raise SafetyViolation(
                f"[G0-4D] requires TRADING_MODE=TESTNET, got {mode.value}")
        fp = resolve_account_fingerprint(
            mode, source.get("BINANCE_API_KEY"), source.as_environ())
        if fp != INCIDENT_FINGERPRINT:
            raise SafetyViolation(
                "[G0-4D] ACCOUNT_IDENTITY_DRIFT: not the incident fingerprint.")
        if key_fingerprint(source.get("BINANCE_API_KEY")) != INCIDENT_FINGERPRINT:
            raise SafetyViolation(
                "[G0-4D] key fingerprint is not the incident account.")
        from aurora.safety import build_client

        client = build_client(
            mode, "G0-4D read-only requalification", environ=source.as_environ())
        install_readonly_http_guard(client)
        wrap_futures_get_allowlist(client)
        result = G04DReadonlyRequal(client, symbol=args.symbol).run(fp)
    except Exception as exc:
        result = {
            "probe": "G0-4D_READ_ONLY_REQUAL",
            "status": "BLOCKED",
            "g04d": "FAIL",
            **_error(exc),
        }

    text = json.dumps(result, sort_keys=True, indent=2)
    print(text)
    if args.write_report:
        os.makedirs(os.path.dirname(os.path.abspath(args.write_report)) or ".", exist_ok=True)
        with open(args.write_report, "w") as fh:
            fh.write(text)
            fh.write("\n")
    return 0 if result.get("g04d") in ("CLOSED-READONLY", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
