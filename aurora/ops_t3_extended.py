"""T3 EXTENDED CONTROLLED TESTNET RUN — bounded production-loop validation.

Purpose: run the real TradingCycle + PortfolioBrainV2 + kernel on TESTNET
for a bounded number of cycles or bounded time, with strict exposure caps.

Governance:
- TESTNET only; LIVE is refused before any client construction.
- Incident kill must remain ACTIVE (the harness never clears it).
- Isolated ledger under state/testnet/<fingerprint>/t3/<session>/ledger.db.
- Start order + scoped permit (multi-cycle) required; single lifecycle CTR
  permits are not accepted.
- max_qty caps every opening order (default 0.001 BTCUSDT).
- Stop on SafetyViolation, unresolved recovery, kill switch, or cycle/time budget.
- End-of-session close: any remaining position is closed and reconciled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from aurora.config_source import ConfigSource, repo_default_env_file
from aurora.incident_governance import read_incident_state
from aurora.kernel.ledger import Ledger
from aurora.kernel.state_machine import utc_now
from aurora.ops_controlled_requal import (
    INCIDENT_FINGERPRINT,
    SYMBOL,
    SIDE,
    CLIENT_ID_NS,
    assert_identity,
    assert_session_id,
    incident_ledger_path,
)
from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    resolve_account_fingerprint,
    state_root,
)
from aurora.safety import build_client
from aurora.trading_cycle import TradingCycle


# T3-20260910-01 smoke: xinquanwang authorized; disarm after session.
T3_EXECUTE_AUTHORIZED = True
T3_CLIENT_ID_NS = "AURORA-T3-"
T3_PERMIT_SCHEMA = "t3-permit-v1"
T3_START_ORDER_SCHEMA = "t3-start-order-v1"
T3_MAX_QTY = 0.001
T3_MAX_NOTIONAL_USDT = 120.0
T3_DEFAULT_MAX_CYCLES = 120
T3_DEFAULT_MAX_RUNTIME_SEC = 3600
T3_DEFAULT_CYCLE_INTERVAL_SEC = 30


def t3_session_ledger_path(
        fingerprint: str = INCIDENT_FINGERPRINT,
        session_id: Optional[str] = None) -> str:
    if not session_id:
        raise SafetyViolation("[T3] session_id required for T3 ledger path.")
    assert_session_id(session_id)
    return os.path.join(
        state_root(), "testnet", fingerprint, "t3",
        session_id, "ledger.db")


def t3_permit_path(fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "t3_permit.json")


def t3_start_order_path(fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "t3_start_order.json")


def t3_evidence_dir(session_id: str,
                    fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    assert_session_id(session_id)
    return os.path.join(
        state_root(), "testnet", fingerprint, "t3", session_id)


def _file_digest(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def issue_t3_window(
    session_id: str,
    issued_by: str,
    *,
    fingerprint: str = INCIDENT_FINGERPRINT,
    max_cycles: int = T3_DEFAULT_MAX_CYCLES,
    max_runtime_sec: int = T3_DEFAULT_MAX_RUNTIME_SEC,
    max_qty: float = T3_MAX_QTY,
    max_notional_usdt: float = T3_MAX_NOTIONAL_USDT,
    valid_hours: float = 72.0,
    cycle_interval_sec: int = T3_DEFAULT_CYCLE_INTERVAL_SEC,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """签发 T3 多周期受控运行窗口：start order + permit。"""
    assert_session_id(session_id)
    if not issued_by or not issued_by.strip():
        raise SafetyViolation("[T3] window requires issued_by.")
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(hours=float(valid_hours))
    base = {
        "schema": T3_START_ORDER_SCHEMA,
        "session_id": session_id,
        "status": "OPEN",
        "env": "TESTNET",
        "symbol": SYMBOL,
        "side": SIDE,
        "scope": {
            "max_cycles": int(max_cycles),
            "max_runtime_sec": int(max_runtime_sec),
            "max_qty": float(max_qty),
            "max_notional_usdt": float(max_notional_usdt),
            "cycle_interval_sec": int(cycle_interval_sec),
        },
        "account_fingerprint": fingerprint,
        "issued_at": issued_at.isoformat(),
        "issued_by": issued_by.strip(),
        "expires_at": expires_at.isoformat(),
    }
    _atomic_write(t3_start_order_path(fingerprint), base)
    permit = {
        "schema": T3_PERMIT_SCHEMA,
        "session_id": session_id,
        "single_use": False,
        "cycles_used": 0,
        "max_cycles": int(max_cycles),
        "max_runtime_sec": int(max_runtime_sec),
        "max_qty": float(max_qty),
        "max_notional_usdt": float(max_notional_usdt),
        "cycle_interval_sec": int(cycle_interval_sec),
        "env": "TESTNET",
        "symbol": SYMBOL,
        "side": SIDE,
        "account_fingerprint": fingerprint,
        "issued_at": issued_at.isoformat(),
        "issued_by": issued_by.strip(),
        "expires_at": expires_at.isoformat(),
        "voided": False,
    }
    _atomic_write(t3_permit_path(fingerprint), permit)
    return {"start_order": base, "permit": permit}


def load_t3_start_order(
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    path = t3_start_order_path(fingerprint)
    if not os.path.isfile(path):
        raise SafetyViolation("[T3] no start order; T3 execution denied.")
    with open(path) as fh:
        order = json.load(fh)
    if order.get("schema") != T3_START_ORDER_SCHEMA:
        raise SafetyViolation("[T3] start order schema mismatch.")
    if order.get("status") != "OPEN":
        raise SafetyViolation(f"[T3] start order status={order.get('status')}.")
    expires = datetime.fromisoformat(order["expires_at"])
    if (now or datetime.now(timezone.utc)) >= expires:
        raise SafetyViolation("[T3] start order expired.")
    return order


def load_t3_permit(
    fingerprint: str = INCIDENT_FINGERPRINT,
    expected_session_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    path = t3_permit_path(fingerprint)
    if not os.path.isfile(path):
        raise SafetyViolation("[T3] no permit; T3 execution denied.")
    with open(path) as fh:
        permit = json.load(fh)
    if permit.get("schema") != T3_PERMIT_SCHEMA:
        raise SafetyViolation("[T3] permit schema mismatch.")
    if permit.get("voided"):
        raise SafetyViolation("[T3] permit voided.")
    if expected_session_id and permit.get("session_id") != expected_session_id:
        raise SafetyViolation("[T3] permit session mismatch.")
    expires = datetime.fromisoformat(permit["expires_at"])
    if (now or datetime.now(timezone.utc)) >= expires:
        raise SafetyViolation("[T3] permit expired.")
    return permit


def assert_t3_gates(
    source: ConfigSource,
    session_id: str,
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """T3 写入口冻结合同：硬开关 + 开工令 + 许可 + 身份 + 事故锁 ACTIVE。"""
    if T3_EXECUTE_AUTHORIZED is not True:
        raise SafetyViolation(
            "[T3] T3_EXECUTE_AUTHORIZED=false; execution denied before client.")
    mode = source.mode()
    if mode != RunMode.TESTNET:
        raise SafetyViolation(f"[T3] TESTNET only, got {mode.value}")
    fp = assert_identity(source, fingerprint)
    order = load_t3_start_order(fingerprint, now=now)
    if order["session_id"] != session_id:
        raise SafetyViolation("[T3] start order session mismatch.")
    permit = load_t3_permit(fingerprint, session_id, now=now)
    state = read_incident_state(incident_ledger_path())
    if state["status"] != "ACTIVE":
        raise SafetyViolation(
            f"[T3] incident kill not ACTIVE ({state['status']}); T3 refused.")
    ledger_path = t3_session_ledger_path(fp, session_id)
    target_abs = os.path.abspath(ledger_path)
    incident_abs = os.path.abspath(incident_ledger_path())
    if target_abs == incident_abs or "t3" not in target_abs.split(os.sep):
        raise SafetyViolation("[T3] ledger path must be isolated from incident ledger.")
    return {
        "order": order,
        "permit": permit,
        "fingerprint": fp,
        "ledger_path": ledger_path,
        "incident_state": state,
    }


def void_t3_permit(reason: str, fingerprint: str = INCIDENT_FINGERPRINT) -> None:
    path = t3_permit_path(fingerprint)
    if not os.path.isfile(path):
        return
    with open(path) as fh:
        permit = json.load(fh)
    if permit.get("voided"):
        return
    permit["voided"] = True
    permit["voided_reason"] = reason
    permit["voided_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(path, permit)


def close_start_order(reason: str, fingerprint: str = INCIDENT_FINGERPRINT) -> None:
    path = t3_start_order_path(fingerprint)
    if not os.path.isfile(path):
        return
    with open(path) as fh:
        order = json.load(fh)
    order["status"] = "CLOSED"
    order["closed_reason"] = reason
    order["closed_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(path, order)


def run_t3_session(
    source: ConfigSource,
    session_id: str,
    *,
    stop_price: Optional[float] = None,
    capital: float = 0.0,
    fingerprint: str = INCIDENT_FINGERPRINT,
) -> Dict[str, Any]:
    """执行受控 T3 多周期 TESTNET 运行。"""
    assert_session_id(session_id)
    if session_id.startswith(CLIENT_ID_NS):
        raise SafetyViolation("[T3] session_id must not reuse CTR namespace.")
    gates = assert_t3_gates(source, session_id, fingerprint=fingerprint)
    order = gates["order"]
    permit = gates["permit"]
    ledger_path = gates["ledger_path"]
    scope = order["scope"]
    max_cycles = int(scope["max_cycles"])
    max_runtime_sec = int(scope["max_runtime_sec"])
    max_qty = float(scope["max_qty"])
    cycle_interval = int(scope.get("cycle_interval_sec", T3_DEFAULT_CYCLE_INTERVAL_SEC))

    mode = source.mode()
    if mode != RunMode.TESTNET:
        raise SafetyViolation(f"[T3] TESTNET only, got {mode.value}")

    from aurora.armed_runtime import ArmedRuntime

    client = build_client(mode, "t3-extended-testnet", environ=source.as_environ())
    runtime = ArmedRuntime.attach(
        mode,
        client,
        ledger_path=ledger_path,
        symbol=SYMBOL,
        expected_mode=(
            source.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE"),
    )
    if runtime.ledger.kill_state().get("engaged"):
        raise SafetyViolation("[T3] session ledger kill engaged at boot.")

    incident_digest_before = _file_digest(incident_ledger_path())
    cycle = TradingCycle(
        runtime, client, symbol=SYMBOL, mode=mode,
        capital=capital, max_qty=max_qty,
        evidence_path=os.path.join(
            t3_evidence_dir(session_id, fingerprint), "strategy_evidence.json"),
    )

    evidence_dir = t3_evidence_dir(session_id, fingerprint)
    os.makedirs(evidence_dir, exist_ok=True)
    cycles: List[Dict[str, Any]] = []
    stop_reason = "max_cycles"
    start_at = time.time()
    end_at = start_at + max_runtime_sec

    try:
        for i in range(1, max_cycles + 1):
            if time.time() >= end_at:
                stop_reason = "max_runtime"
                break
            try:
                out = cycle.step(enable=True)
            except SafetyViolation as exc:
                stop_reason = f"safety_violation: {exc}"
                break
            cycle_record = {
                "cycle": i,
                "at": datetime.now(timezone.utc).isoformat(),
                "action": out.get("action"),
                "submitted": out.get("submitted"),
                "reason": out.get("reason") or out.get("decision_reason"),
                "recover_unresolved": bool(out.get("recover", {}).get("unresolved")),
                "kill_engaged": bool(runtime.ledger.kill_state().get("engaged")),
            }
            cycles.append(cycle_record)
            if out.get("recover", {}).get("unresolved"):
                stop_reason = f"unresolved_recovery cycle={i}"
                break
            if runtime.ledger.kill_state().get("engaged"):
                stop_reason = f"kill_engaged cycle={i}"
                break
            if out.get("submitted"):
                # 一旦提交，立即记录详细证据；循环继续
                pass
            if i < max_cycles and time.time() < end_at:
                time.sleep(cycle_interval)
    finally:
        final_pos = runtime.exchange.position(SYMBOL)
        close_result: Optional[Dict[str, Any]] = None
        if final_pos is not None and abs(final_pos.signed_qty) > 1e-12:
            try:
                close_result = runtime.close_position("t3-session-end")
            except Exception as exc:
                close_result = {"success": False, "reason": str(exc)}
        final_recover = runtime.recover()
        final_position_fact = runtime.ledger.get_position_fact(SYMBOL)
        final_kill = runtime.ledger.kill_state()
        runtime.close()
        incident_digest_after = _file_digest(incident_ledger_path())

    # 更新许可周期计数
    permit["cycles_used"] = len(cycles)
    _atomic_write(t3_permit_path(fingerprint), permit)

    # 更新开工令状态
    order["status"] = "CLOSED"
    order["closed_reason"] = stop_reason
    order["closed_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(t3_start_order_path(fingerprint), order)

    report = {
        "schema": "t3-session-report-v1",
        "session_id": session_id,
        "success": stop_reason in ("max_cycles", "max_runtime"),
        "stop_reason": stop_reason,
        "cycles_run": len(cycles),
        "max_cycles": max_cycles,
        "max_runtime_sec": max_runtime_sec,
        "max_qty": max_qty,
        "start_at": datetime.fromtimestamp(start_at, timezone.utc).isoformat(),
        "end_at": datetime.now(timezone.utc).isoformat(),
        "cycles": cycles,
        "close_result": close_result,
        "final_recover_unresolved": final_recover.get("unresolved"),
        "final_position_fact": final_position_fact,
        "final_kill": final_kill,
        "incident_ledger_unchanged": incident_digest_before == incident_digest_after,
        "incident_digest_before": incident_digest_before,
        "incident_digest_after": incident_digest_after,
        "session_ledger": ledger_path,
    }
    _atomic_write(os.path.join(evidence_dir, "report.json"), report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="T3 extended controlled TESTNET production-loop harness")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--issue-window", action="store_true")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--issued-by", default=None)
    parser.add_argument("--max-cycles", type=int, default=T3_DEFAULT_MAX_CYCLES)
    parser.add_argument("--max-runtime-sec", type=int, default=T3_DEFAULT_MAX_RUNTIME_SEC)
    parser.add_argument("--max-qty", type=float, default=T3_MAX_QTY)
    parser.add_argument("--valid-hours", type=float, default=72.0)
    parser.add_argument("--cycle-interval-sec", type=int, default=T3_DEFAULT_CYCLE_INTERVAL_SEC)
    parser.add_argument("--capital", type=float, default=0.0)
    parser.add_argument("--i-execute-t3", action="store_true")
    parser.add_argument("--stop-price", type=float, default=None)
    args = parser.parse_args(argv)

    env_file = os.path.abspath(args.env_file or repo_default_env_file())
    if not os.path.isfile(env_file):
        print(json.dumps({"execute": "DENIED", "reason": "env file not found"}, indent=2))
        return 2
    source = ConfigSource.load(env_file=env_file)

    if args.issue_window:
        if not args.session_id or not args.issued_by:
            print(json.dumps({"execute": "DENIED", "reason": "--session-id and --issued-by required"}, indent=2))
            return 2
        window = issue_t3_window(
            args.session_id, args.issued_by,
            max_cycles=args.max_cycles,
            max_runtime_sec=args.max_runtime_sec,
            max_qty=args.max_qty,
            valid_hours=args.valid_hours,
            cycle_interval_sec=args.cycle_interval_sec)
        print(json.dumps({"windowIssued": True, **{k: v.get("session_id") or v.get("scope") for k, v in window.items() if k in ("start_order", "permit")}}, indent=2, default=str))
        return 0

    if args.i_execute_t3:
        if not args.session_id:
            print(json.dumps({"execute": "DENIED", "reason": "--session-id required"}, indent=2))
            return 2
        try:
            report = run_t3_session(
                source, args.session_id,
                stop_price=args.stop_price,
                capital=args.capital)
        except SafetyViolation as exc:
            print(json.dumps({"execute": "DENIED", "reason": str(exc)}, indent=2))
            return 3
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("success") else 1

    print(json.dumps({"execute": "DENIED", "reason": "no action requested"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
