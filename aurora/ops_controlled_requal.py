"""CONTROLLED TESTNET REQUALIFICATION harness.

默认只做计划 / 离线会话验收。执行写路径必须同时给出开工旗标；
本模块被 import 或 --plan-only 时零出网、不改事故账本。
禁止经 production_main / TradingCycle 进入。
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from typing import Any, Dict, Optional

from aurora.config_source import ConfigSource, repo_default_env_file
from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    key_fingerprint,
    resolve_account_fingerprint,
    state_root,
)

INCIDENT_INTENT = "AURORA-0650a39f56e3"
INCIDENT_FINGERPRINT = "3fbc5d4f1f9ddc7d"
SYMBOL = "BTCUSDT"
SIDE = "LONG"
MAX_QTY = 0.001
MAX_NOTIONAL_USDT = 120.0
SESSION_LEDGER_REL = os.path.join(
    "state", "testnet", INCIDENT_FINGERPRINT, "controlled_requal.db")
FORBIDDEN_INTENT_MARK = "0650a39f56e3"
# 硬开关：开工令未到之前，任何 live 写入口必须失败。
EXECUTE_AUTHORIZED = False


def incident_ledger_path() -> str:
    return os.path.join(state_root(), "kernel_ledger.db")


def session_ledger_path() -> str:
    return os.path.join(state_root(), "testnet", INCIDENT_FINGERPRINT, "controlled_requal.db")


def new_session_intent_id() -> str:
    return f"AURORA-CTR-{uuid.uuid4().hex[:12]}"


def assert_intent_allowed(intent_id: str) -> None:
    if FORBIDDEN_INTENT_MARK in intent_id or intent_id == INCIDENT_INTENT:
        raise SafetyViolation("[CTR] refuse incident client id reuse.")


def assert_scale(qty: float, mark_price: float) -> None:
    if qty <= 0 or qty - MAX_QTY > 1e-12:
        raise SafetyViolation(f"[CTR] qty {qty} exceeds MAX_QTY={MAX_QTY}.")
    notional = qty * mark_price
    if notional - MAX_NOTIONAL_USDT > 1e-9:
        raise SafetyViolation(
            f"[CTR] notional {notional:.4f} exceeds MAX_NOTIONAL_USDT={MAX_NOTIONAL_USDT}."
        )


def assert_stop_price(stop_price: float, mark_price: float) -> None:
    if stop_price <= 0 or mark_price <= 0:
        raise SafetyViolation("[CTR] stop/mark price missing or invalid.")
    if stop_price >= mark_price:
        raise SafetyViolation("[CTR] LONG SL must be strictly below mark.")


def assert_session_start(exchange: Any, symbol: str = SYMBOL) -> None:
    """开仓前：仓位必须可知且 FLAT。UNKNOWN 不得解释为空仓。"""
    try:
        pos = exchange.position(symbol)
    except Exception as exc:
        raise SafetyViolation(f"[CTR] position unreadable: {type(exc).__name__}") from exc
    if pos is None:
        raise SafetyViolation("[CTR] position UNKNOWN; refuse start.")
    if abs(float(getattr(pos, "signed_qty", 0.0) or 0.0)) > 1e-12:
        raise SafetyViolation("[CTR] BTCUSDT not FLAT; refuse start.")


def execute_live(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    """真实写入口。未单独开工前恒拒，且不构造客户端。"""
    raise SafetyViolation(
        "[CTR] EXECUTE_AUTHORIZED=false; refuse all TESTNET writes."
    )


def assert_session_ledger_isolated(path: str) -> None:
    incident = os.path.abspath(incident_ledger_path())
    target = os.path.abspath(path)
    if target == incident:
        raise SafetyViolation("[CTR] session ledger must not be the incident ledger.")
    if "controlled_requal.db" not in os.path.basename(target):
        raise SafetyViolation("[CTR] session ledger must be controlled_requal.db.")


def incident_kill_snapshot() -> Dict[str, Any]:
    """只读打开事故账本。禁止经 Ledger() 写入 WAL/schema。"""
    import sqlite3

    path = incident_ledger_path()
    if not os.path.exists(path):
        return {"status": "ABSENT", "path": path, "digest": None}
    digest = _file_digest(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT engaged FROM kill_switch WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    engaged = int(row[0]) if row is not None else 0
    return {
        "status": "ACTIVE" if engaged == 1 else "CLEAR",
        "engaged": engaged,
        "digest": digest,
        "written": False,
    }


def _file_digest(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(
    source: Optional[ConfigSource] = None,
    qty: float = MAX_QTY,
    mark_price: Optional[float] = None,
    intent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """纯本地计划：检查身份、规模、路径隔离。不构造交易所客户端。"""
    src = source or ConfigSource.load(environ={})
    mode = src.mode() if source is not None else RunMode.TESTNET
    if source is not None and mode != RunMode.TESTNET:
        raise SafetyViolation(f"[CTR] requires TESTNET, got {mode.value}")
    if source is not None:
        fp = resolve_account_fingerprint(
            mode, src.get("BINANCE_API_KEY"), src.as_environ())
        if fp != INCIDENT_FINGERPRINT:
            raise SafetyViolation("[CTR] ACCOUNT_IDENTITY_DRIFT.")
        if key_fingerprint(src.get("BINANCE_API_KEY")) != INCIDENT_FINGERPRINT:
            raise SafetyViolation("[CTR] key fingerprint is not the incident account.")
    intent = intent_id or new_session_intent_id()
    assert_intent_allowed(intent)
    if mark_price is not None:
        assert_scale(qty, mark_price)
    else:
        if qty - MAX_QTY > 1e-12:
            raise SafetyViolation(f"[CTR] qty {qty} exceeds MAX_QTY={MAX_QTY}.")
    session_path = session_ledger_path()
    assert_session_ledger_isolated(session_path)
    kill = incident_kill_snapshot()
    if kill.get("status") == "CLEAR":
        raise SafetyViolation("[CTR] incident kill unexpectedly CLEAR; refuse.")
    return {
        "package": "CONTROLLED_TESTNET_REQUAL",
        "execute": "DENIED",
        "symbol": SYMBOL,
        "side": SIDE,
        "qty": qty,
        "maxQty": MAX_QTY,
        "maxNotionalUsdt": MAX_NOTIONAL_USDT,
        "intentId": intent,
        "sessionLedger": session_path,
        "incidentLedger": incident_ledger_path(),
        "incidentKill": kill,
        "entryPoint": "aurora.ops_controlled_requal",
        "productionMain": "DENIED",
        "autoTestnet": "DENIED",
        "live": "NO-GO",
    }


def run_session(
    orch: Any,
    *,
    qty: float = MAX_QTY,
    mark_price: float,
    stop_price: float,
    intent_id: Optional[str] = None,
    incident_path: Optional[str] = None,
) -> Dict[str, Any]:
    """用已注入的 Orchestrator 跑完一次受控会话（供离线 FakeExchange）。"""
    assert_scale(qty, mark_price)
    assert_stop_price(stop_price, mark_price)
    intent = intent_id or new_session_intent_id()
    assert_intent_allowed(intent)
    try:
        assert_session_start(orch.exchange)
    except SafetyViolation:
        orch.ledger.engage_kill("controlled requal start preconditions failed")
        raise
    before = _file_digest(incident_path) if incident_path and os.path.exists(incident_path) else None

    opened = orch.open_position(
        SIDE, qty, intent_id=intent, stop_price=stop_price, take_profit_price=None)
    if not opened.get("success"):
        orch.ledger.engage_kill(f"controlled requal open failed: {opened.get('reason')}")
        return {"success": False, "phase": "OPEN", "opened": opened}

    if opened.get("state") != "PROTECTED":
        orch.ledger.engage_kill("controlled requal SL not PROTECTED")
        return {"success": False, "phase": "SL", "opened": opened, "reason": "SL not ACTIVE_CONFIRMED"}

    protected_qty = float(opened.get("protected_qty") or 0)
    if abs(protected_qty - qty) > 1e-12:
        orch.ledger.engage_kill("controlled requal protected_qty != position")
        return {
            "success": False, "phase": "SL", "opened": opened,
            "reason": "protected_qty != confirmed qty",
        }

    recovered = orch.recover()
    if recovered.get("unresolved"):
        orch.ledger.engage_kill("controlled requal restart recover unresolved")
        return {"success": False, "phase": "RESTART", "recover": recovered}

    closed = orch.close_position(reason="controlled-requal-flatten")
    if not closed.get("success"):
        orch.ledger.engage_kill(f"controlled requal flatten failed: {closed.get('reason')}")
        return {"success": False, "phase": "FLATTEN", "closed": closed}

    orch.ledger.engage_kill("controlled requal session complete")
    after = _file_digest(incident_path) if incident_path and os.path.exists(incident_path) else None
    if before is not None and after != before:
        raise SafetyViolation("[CTR] incident ledger changed; forbidden.")
    return {
        "success": True,
        "phase": "COMPLETE",
        "intentId": intent,
        "opened": {"state": opened.get("state"), "protected_qty": protected_qty},
        "restartRecover": "PASS",
        "closed": {"success": True},
        "sessionKill": orch.ledger.kill_state(),
        "incidentLedgerUnchanged": True,
        "execute": "OFFLINE_SESSION_ONLY",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Controlled TESTNET requalification (plan default; execute denied)")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--qty", type=float, default=MAX_QTY)
    parser.add_argument("--mark-price", type=float, default=None)
    parser.add_argument("--stop-price", type=float, default=None)
    parser.add_argument(
        "--i-execute-controlled-requal",
        action="store_true",
        help="write path; still refused unless separately authorized in this process",
    )
    args = parser.parse_args(argv)

    env_file = os.path.abspath(args.env_file or repo_default_env_file())
    source = None
    if os.path.isfile(env_file):
        source = ConfigSource.load(env_file=env_file)
    try:
        report = plan(
            source=source if source is not None else None,
            qty=args.qty,
            mark_price=args.mark_price,
        )
    except SafetyViolation as exc:
        print(json.dumps({
            "package": "CONTROLLED_TESTNET_REQUAL",
            "execute": "DENIED",
            "status": "BLOCKED",
            "errorType": type(exc).__name__,
        }, sort_keys=True, indent=2))
        return 2

    if args.i_execute_controlled_requal or not EXECUTE_AUTHORIZED:
        if args.i_execute_controlled_requal:
            report["execute"] = "DENIED"
            report["reason"] = (
                "EXECUTE_AUTHORIZED=false; flag alone does not start TESTNET writes."
            )
            print(json.dumps(report, sort_keys=True, indent=2))
            return 3

    report["status"] = "PLAN"
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
