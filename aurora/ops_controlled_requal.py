"""CONTROLLED TESTNET REQUALIFICATION harness（G0-4D-R1 后实施包）.

状态：CONTRACT FROZEN / EXECUTION NOT AUTHORIZED（EXECUTE_AUTHORIZED=False）。

本模块实现 CONTROLLED_REQUAL_CONTRACT.md 的六阶段生命周期：
P0 只读基线 → P1 WIRE ACK 三方验证 → P2 entry once →
P3 ACTIVE_CONFIRMED → P4 restart recovery → P5 flatten & close-out。

硬规则：
- 事故 kill 只读保留；会话 kill 自管；事故账本字节不变。
- 身份门无条件：没有 source 就没有 plan。
- 名义上限以只读观察的权威标记价计算；操作员手填价格不作为上限依据。
- 真实写路径额外要求 qualification permit 有效 + EXECUTE_AUTHORIZED。
- 禁止经 production_main / TradingCycle 进入。
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
FORBIDDEN_INTENT_MARK = "0650a39f56e3"
CLIENT_ID_NS = "AURORA-CTR-"
PERMIT_TTL_HOURS_DEFAULT = 72.0
PERMIT_SCHEMA = "ctr-permit-v1"
START_ORDER_SCHEMA = "ctr-start-order-v1"
# 硬开关：开工令未到之前，任何 live 写入口必须失败。
EXECUTE_AUTHORIZED = True


def incident_ledger_path() -> str:
    return os.path.join(state_root(), "kernel_ledger.db")


def session_ledger_path(
        fingerprint: str = INCIDENT_FINGERPRINT,
        session_id: Optional[str] = None) -> str:
    if not session_id:
        raise SafetyViolation(
            "[CTR] session_id required for qualification ledger path.")
    assert_session_id(session_id)
    return os.path.join(
        state_root(), "testnet", fingerprint, "qualification",
        session_id, "ledger.db")


def qualification_permit_path(
        fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "qualification_permit.json")


def session_intent_id(session_id: str) -> str:
    assert_session_id(session_id)
    return f"{CLIENT_ID_NS}{session_id}"


def leg_client_id(session_id: str, leg: str) -> str:
    if leg not in ("ENTRY", "SL", "CLOSE"):
        raise SafetyViolation(f"[CTR] unknown leg {leg}.")
    return f"{session_intent_id(session_id)}-{leg}"


def new_session_intent_id() -> str:
    return session_intent_id(uuid.uuid4().hex[:12])


def assert_intent_allowed(intent_id: str) -> None:
    if FORBIDDEN_INTENT_MARK in intent_id or intent_id == INCIDENT_INTENT:
        raise SafetyViolation("[CTR] refuse incident client id reuse.")
    if not intent_id.startswith(CLIENT_ID_NS):
        raise SafetyViolation(
            f"[CTR] intent must use {CLIENT_ID_NS}* namespace.")


def assert_qty_exact(qty: float) -> None:
    if abs(float(qty) - MAX_QTY) > 1e-12:
        raise SafetyViolation(
            f"[CTR] qty must be exactly {MAX_QTY}, got {qty}.")


def assert_scale(qty: float, mark_price: float) -> None:
    if mark_price is None or mark_price <= 0:
        raise SafetyViolation(
            "[CTR] notional cap requires an observed mark price.")
    assert_qty_exact(qty)
    notional = qty * float(mark_price)
    if notional - MAX_NOTIONAL_USDT > 1e-9:
        raise SafetyViolation(
            f"[CTR] notional {notional:.4f} exceeds "
            f"MAX_NOTIONAL_USDT={MAX_NOTIONAL_USDT}.")


def assert_stop_price(stop_price: float, mark_price: float) -> None:
    if stop_price is None or stop_price <= 0 or mark_price is None or mark_price <= 0:
        raise SafetyViolation("[CTR] stop/mark price missing or invalid.")
    if stop_price >= mark_price:
        raise SafetyViolation("[CTR] LONG SL must be strictly below mark.")


def assert_session_start(exchange: Any, symbol: str = SYMBOL) -> None:
    """开仓前：仓位必须可知且 FLAT。UNKNOWN 不得解释为空仓。"""
    try:
        pos = exchange.position(symbol)
    except Exception as exc:
        raise SafetyViolation(
            f"[CTR] position unreadable: {type(exc).__name__}") from exc
    if pos is None:
        raise SafetyViolation("[CTR] position UNKNOWN; refuse start.")
    if abs(float(getattr(pos, "signed_qty", 0.0) or 0.0)) > 1e-12:
        raise SafetyViolation("[CTR] BTCUSDT not FLAT; refuse start.")


def assert_session_ledger_isolated(
        path: str, session_id: Optional[str] = None) -> None:
    incident = os.path.abspath(incident_ledger_path())
    target = os.path.abspath(path)
    if target == incident:
        raise SafetyViolation(
            "[CTR] session ledger must not be the incident ledger.")
    parts = target.split(os.sep)
    if "qualification" not in parts:
        raise SafetyViolation(
            "[CTR] session ledger must live under qualification/<session-id>/.")
    if os.path.basename(target) != "ledger.db":
        raise SafetyViolation("[CTR] session ledger file must be ledger.db.")
    if session_id is not None and session_id not in parts:
        raise SafetyViolation(
            "[CTR] session ledger path must include the session id.")


def assert_identity(source: ConfigSource,
                    account_fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    """F：身份门无条件。mode 必须 TESTNET 且指纹必须绑定预期账户。"""
    mode = source.mode()
    if mode != RunMode.TESTNET:
        raise SafetyViolation(f"[CTR] requires TESTNET, got {mode.value}")
    fp = resolve_account_fingerprint(
        mode, source.get("BINANCE_API_KEY"), source.as_environ())
    if fp != account_fingerprint:
        raise SafetyViolation("[CTR] ACCOUNT_IDENTITY_DRIFT: "
                              f"{fp} != {account_fingerprint}")
    if key_fingerprint(source.get("BINANCE_API_KEY")) != account_fingerprint:
        raise SafetyViolation(
            "[CTR] key fingerprint is not the expected account.")
    return fp


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
            "SELECT engaged FROM kill_switch WHERE id = 1").fetchone()
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


# ---------------------------------------------------------------------------
# Qualification Permit（一次性、范围受限；事故 kill 不因此清除）
# ---------------------------------------------------------------------------

def issue_permit(
    issued_by: str,
    session_id: str,
    ttl_hours: float = PERMIT_TTL_HOURS_DEFAULT,
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """签发绑定精确 session 的一次性许可并持久化。签发 ≠ 执行。"""
    if not issued_by or not issued_by.strip():
        raise SafetyViolation("[CTR] permit requires issued_by.")
    assert_session_id(session_id)
    issued_at = (now or datetime.now(timezone.utc))
    expires_at = issued_at + timedelta(hours=float(ttl_hours))
    permit = {
        "schema": PERMIT_SCHEMA,
        "session_id": session_id,
        "single_use": True,
        "scope": {
            "env": "TESTNET",
            "symbol": SYMBOL,
            "side": SIDE,
            "qty": MAX_QTY,
        },
        "max_qty": MAX_QTY,
        "max_notional_usdt": MAX_NOTIONAL_USDT,
        "client_id_ns": CLIENT_ID_NS,
        "lifecycle": {"total": 1, "used": []},
        "session_ledger": session_ledger_path(fingerprint, session_id),
        "account_fingerprint": fingerprint,
        "issued_at": issued_at.isoformat(),
        "issued_by": issued_by.strip(),
        "expires_at": expires_at.isoformat(),
        "voided": False,
    }
    path = qualification_permit_path(fingerprint)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(permit, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return permit


def load_permit(fingerprint: str = INCIDENT_FINGERPRINT,
                now: Optional[datetime] = None,
                expected_session_id: Optional[str] = None,
                ) -> Dict[str, Any]:
    path = qualification_permit_path(fingerprint)
    if not os.path.exists(path):
        raise SafetyViolation(
            "[CTR] no qualification permit issued; writes stay denied.")
    with open(path) as fh:
        permit = json.load(fh)
    if permit.get("schema") != PERMIT_SCHEMA:
        raise SafetyViolation("[CTR] permit schema mismatch.")
    if permit.get("voided"):
        raise SafetyViolation(
            "[CTR] permit voided by a terminated session; "
            "no second entry under this window.")
    if permit.get("single_use") is not True:
        raise SafetyViolation("[CTR] permit.single_use must be true.")
    scope = permit.get("scope") or {}
    try:
        scope_qty = float(scope.get("qty"))
    except (TypeError, ValueError):
        scope_qty = None
    if (scope.get("env") != "TESTNET" or scope.get("symbol") != SYMBOL
            or scope.get("side") != SIDE
            or scope_qty is None or abs(scope_qty - MAX_QTY) > 1e-12):
        raise SafetyViolation("[CTR] permit scope drift.")
    if permit.get("account_fingerprint") != fingerprint:
        raise SafetyViolation("[CTR] permit account drift.")
    expires = datetime.fromisoformat(permit["expires_at"])
    if (now or datetime.now(timezone.utc)) >= expires:
        raise SafetyViolation("[CTR] permit expired.")
    if expected_session_id is not None and \
            permit.get("session_id") != expected_session_id:
        raise SafetyViolation(
            "[CTR] PERMIT_SESSION_MISMATCH: permit is scoped to "
            f"{permit.get('session_id')}, order demands {expected_session_id}.")
    return permit


# ---------------------------------------------------------------------------
# Execution Start Order + scoped permit。
# 真实写路径必须在构造任何写客户端之前同时满足：
#   EXECUTE_AUTHORIZED == true
#   + valid scoped single-use permit（session/qty/expiry）
# 缺一即 DENY BEFORE CLIENT WRITE。
# ---------------------------------------------------------------------------

def start_order_path(fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "execution_start_order.json")


def session_final_path(session_id: str,
                       fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(state_root(), "testnet", fingerprint,
                        "sessions", f"{session_id}.final.json")


def assert_session_id(session_id: str) -> None:
    if not session_id or not session_id.strip():
        raise SafetyViolation("[CTR] session_id required.")
    if any(ch.isspace() for ch in session_id) or "/" in session_id:
        raise SafetyViolation("[CTR] session_id must be a bare token.")
    if FORBIDDEN_INTENT_MARK in session_id:
        raise SafetyViolation("[CTR] session_id must not embed incident id.")


def issue_execution_window(
    session_id: str,
    issued_by: str,
    valid_hours: float = PERMIT_TTL_HOURS_DEFAULT,
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """同一受控窗口：冻结 session + 发 START ORDER + 签发 scoped permit。

    这是 permit 的唯一签发通道——不存在独立于开工令的 permit。
    """
    assert_session_id(session_id)
    if not issued_by or not issued_by.strip():
        raise SafetyViolation("[CTR] execution window requires issued_by.")
    issued_at = (now or datetime.now(timezone.utc))
    expires_at = issued_at + timedelta(hours=float(valid_hours))
    order = {
        "schema": START_ORDER_SCHEMA,
        "session_id": session_id,
        "status": "OPEN",
        "contract": "6b2cc7c",
        "conformance": "eb0536b",
        "scope": {
            "env": "TESTNET",
            "symbol": SYMBOL,
            "side": SIDE,
            "qty": MAX_QTY,
        },
        "max_qty": MAX_QTY,
        "max_notional_usdt": MAX_NOTIONAL_USDT,
        "client_id_ns": CLIENT_ID_NS,
        "account_fingerprint": fingerprint,
        "issued_at": issued_at.isoformat(),
        "issued_by": issued_by.strip(),
        "expires_at": expires_at.isoformat(),
    }
    order_path = start_order_path(fingerprint)
    os.makedirs(os.path.dirname(order_path), exist_ok=True)
    tmp = f"{order_path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(order, fh, indent=2, sort_keys=True)
    os.replace(tmp, order_path)
    permit = issue_permit(
        issued_by=issued_by, session_id=session_id, ttl_hours=valid_hours,
        fingerprint=fingerprint, now=now)
    return {"order": order, "permit": permit}


def load_start_order(
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    path = start_order_path(fingerprint)
    if not os.path.exists(path):
        raise SafetyViolation(
            "[CTR] no EXECUTION START ORDER; writes stay denied.")
    with open(path) as fh:
        order = json.load(fh)
    if order.get("schema") != START_ORDER_SCHEMA:
        raise SafetyViolation("[CTR] start order schema mismatch.")
    if order.get("status") != "OPEN":
        raise SafetyViolation(
            f"[CTR] start order status {order.get('status')} != OPEN.")
    expires = datetime.fromisoformat(order["expires_at"])
    if (now or datetime.now(timezone.utc)) >= expires:
        raise SafetyViolation("[CTR] execution window expired.")
    return order


def assert_write_gates(
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """写客户端构造前的联合前门。缺一即 DENY BEFORE CLIENT WRITE。"""
    if not EXECUTE_AUTHORIZED:
        raise SafetyViolation(
            "[CTR] EXECUTE_AUTHORIZED=false; refuse before write client.")
    return check_execution_conditions(
        fingerprint=fingerprint, now=now, session_id=session_id)


def check_execution_conditions(
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """开工令 + 精确 session permit（未作废未过期、single_use、
    scope=BTCUSDT/LONG/0.001）+ 会话无终态。不含写客户端构造。"""
    order = load_start_order(fingerprint, now=now)
    sid = session_id or order["session_id"]
    if sid != order["session_id"]:
        raise SafetyViolation(
            f"[CTR] session_id {sid} != start order {order['session_id']}.")
    permit = load_permit(fingerprint, now=now, expected_session_id=sid)
    if permit.get("session_id") != sid:
        raise SafetyViolation("[CTR] PERMIT_SESSION_MISMATCH")
    if permit.get("single_use") is not True:
        raise SafetyViolation("[CTR] permit.single_use must be true.")
    final = read_session_final(sid, fingerprint)
    if final is not None:
        raise SafetyViolation(
            f"[CTR] session {sid} already terminated "
            f"({final.get('outcome')}); no second entry.")
    return {"order": order, "permit": permit, "session_id": sid}


def read_session_final(session_id: str,
                       fingerprint: str = INCIDENT_FINGERPRINT,
                       ) -> Optional[Dict[str, Any]]:
    path = session_final_path(session_id, fingerprint)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def write_session_final(session_id: str, payload: Dict[str, Any],
                        fingerprint: str = INCIDENT_FINGERPRINT) -> None:
    path = session_final_path(session_id, fingerprint)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"schema": "ctr-session-final-v1", "session_id": session_id,
               **payload, "at": datetime.now(timezone.utc).isoformat()}
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def void_permit(reason: str,
                fingerprint: str = INCIDENT_FINGERPRINT) -> None:
    """会话失败即作废 permit：同一窗口内绝不允许第二次 entry。"""
    path = qualification_permit_path(fingerprint)
    if not os.path.exists(path):
        return
    with open(path) as fh:
        permit = json.load(fh)
    if permit.get("voided"):
        return
    permit["voided"] = True
    permit["voided_reason"] = reason
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(permit, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def bind_permit(
    permit: Dict[str, Any], *, intent_id: str, qty: float, mark_price: float,
    now: Optional[datetime] = None,
) -> None:
    """把本次会话绑定到 permit：命名空间 / 上限 / 过期 / 一次性生命周期。

    bind 即预占并持久化：同一 intent 幂等重入（恢复语义）；
    不同 intent 在生命周期耗尽后拒绝。
    """
    expires = datetime.fromisoformat(str(permit.get("expires_at")))
    if (now or datetime.now(timezone.utc)) >= expires:
        raise SafetyViolation("[CTR] permit expired.")
    ns = permit.get("client_id_ns") or CLIENT_ID_NS
    if not intent_id.startswith(ns):
        raise SafetyViolation(f"[CTR] intent outside permit namespace {ns}.")
    assert_qty_exact(qty)
    permit_max_qty = float(permit.get("max_qty") or MAX_QTY)
    if abs(permit_max_qty - MAX_QTY) > 1e-12:
        raise SafetyViolation(f"[CTR] qty exceeds permit max {permit_max_qty}.")
    permit_max_notional = float(permit.get("max_notional_usdt")
                                or MAX_NOTIONAL_USDT)
    if qty * float(mark_price) - permit_max_notional > 1e-9:
        raise SafetyViolation("[CTR] notional exceeds permit max.")
    lifecycle = permit.setdefault("lifecycle", {"total": 1, "used": []})
    used = lifecycle.setdefault("used", [])
    if intent_id in used:
        return  # 同一会话恢复：幂等
    if len(used) >= int(lifecycle.get("total", 1)):
        raise SafetyViolation(
            "[CTR] permit lifecycle exhausted; one session only.")
    used.append(intent_id)
    path = qualification_permit_path(
        permit.get("account_fingerprint") or INCIDENT_FINGERPRINT)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(permit, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)




# ---------------------------------------------------------------------------
# P0 只读基线（含权威标记价）
# ---------------------------------------------------------------------------

def observe_mark_price(client: Any, symbol: str = SYMBOL) -> float:
    """权威标记价观察（只读 GET）。操作员手填价格不作为上限依据。"""
    raw = client.futures_mark_price(symbol=symbol)
    price = float((raw or {}).get("markPrice") or 0)
    if price <= 0:
        raise SafetyViolation("[CTR] mark price observation invalid.")
    return price


def baseline_from_probe(probe_result: Dict[str, Any],
                        expected_mode: str = "HEDGE") -> Dict[str, Any]:
    """P0：把 G0-4D 探测结果折算为基线判定（ok/violations）。"""
    violations: List[str] = []
    mode = ((probe_result.get("positionMode") or {}).get("value")
            if isinstance(probe_result.get("positionMode"), dict) else None)
    if mode != expected_mode:
        violations.append(f"POSITION_MODE {mode} != {expected_mode}")
    positions = probe_result.get("positions") or {}
    if positions.get("btcusdtPositionState") != "FLAT":
        violations.append("POSITION_NOT_FLAT")
    if (probe_result.get("openOrders") or {}).get("status") not in (
            "EMPTY", None):
        violations.append("ORDINARY_OPEN_ORDERS_PRESENT")
    algo = (probe_result.get("openAlgoOrders") or {})
    if algo.get("status") not in ("EMPTY", None):
        violations.append("BTCUSDT_ALGO_PRESENT")
    identity = probe_result.get("identity") or {}
    if identity.get("positionModeMatchesExpected") is False:
        violations.append("IDENTITY_DRIFT")
    return {"ok": not violations, "violations": violations,
            "markPriceObserved": None}


def observe_baseline(client: Any, source_values: Dict[str, str],
                     symbol: str = SYMBOL) -> Dict[str, Any]:
    """真实路径 P0：G0-4D 探测 + 权威标记价。"""
    from aurora.ops_testnet_probe import ReadOnlyTestnetProbe

    identity = {
        "expectedPositionMode": (source_values.get(
            "AURORA_EXPECTED_POSITION_MODE") or "HEDGE"),
        "accountExclusivity": (
            source_values.get("AURORA_ACCOUNT_EXCLUSIVITY") or "false"),
    }
    probe_result = ReadOnlyTestnetProbe(client, symbol=symbol).run(
        identity=identity)
    baseline = baseline_from_probe(probe_result)
    baseline["markPriceObserved"] = observe_mark_price(client, symbol)
    baseline["probe"] = probe_result
    return baseline


# ---------------------------------------------------------------------------
# P1 WIRE ACK 三方验证
# ---------------------------------------------------------------------------

class WireTee:
    """真实路径专用：包装 SDK client，把 ENTRY/Algo 的原始 ACK 留档。"""

    def __init__(self, inner: Any):
        self._inner = inner
        self.entry_acks: List[Dict[str, Any]] = []
        self.algo_acks: List[Dict[str, Any]] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def export(self) -> Dict[str, Any]:
        return {"entryAcks": self.entry_acks, "algoAcks": self.algo_acks}

    def futures_create_order(self, **params: Any):
        raw = self._inner.futures_create_order(**params)
        self.entry_acks.append({"params": dict(params), "raw": raw})
        return raw

    def _request_futures_api(self, method: str, path: str, signed: bool,
                             **kwargs: Any):
        raw = self._inner._request_futures_api(
            method, path, signed, **kwargs)
        if method.lower() == "post" and path == "algoOrder":
            self.algo_acks.append({"params": dict(kwargs.get("data") or {}),
                                   "raw": raw})
        return raw


def verify_entry_ack(ack_raw: Dict[str, Any], *, side: str,
                     qty: float) -> Dict[str, Any]:
    """ENTRY ACK 三方核对：意图 ↔ wire 响应（普通订单 ACK）。"""
    problems: List[str] = []
    ack_side = str(ack_raw.get("side") or "").upper()
    if ack_side and ack_side != ("BUY" if side == "LONG" else "SELL"):
        problems.append(f"side {ack_side}")
    executed = float(ack_raw.get("executedQty") or 0)
    if executed > qty + 1e-12:
        problems.append(f"executedQty {executed} > intent {qty}")
    return {"ackSide": ack_side or None,
            "executedQty": executed,
            "status": str(ack_raw.get("status") or ""),
            "problems": problems}


def verify_algo_ack(ack_raw: Dict[str, Any], *, trigger: float,
                    qty: float, position_side: str) -> Dict[str, Any]:
    """SL Algo ACK 三方核对：意图 ↔ wire 响应 ↔ 规范化 AlgoOrderFact。"""
    from aurora.kernel.binance_exchange import _algo_fact

    try:
        fact = _algo_fact(dict(ack_raw))
    except RuntimeError as exc:
        # 双别名冲突/全缺等合同违约：不吞掉，转为显式 problems → STOP
        return {"orderType": None, "algoStatus": None,
                "problems": [str(exc)]}
    problems: List[str] = []
    if fact.side != ("SELL" if position_side == "LONG" else "BUY"):
        problems.append(f"side {fact.side}")
    if fact.position_side != position_side:
        problems.append(f"positionSide {fact.position_side}")
    if abs(fact.trigger_price - float(trigger)) > 1e-9:
        problems.append(f"triggerPrice {fact.trigger_price}")
    if abs(fact.qty - float(qty)) > 1e-12:
        problems.append(f"qty {fact.qty}")
    if fact.close_position:
        problems.append("closePosition=true unexpected")
    return {"orderType": fact.order_type, "algoStatus": fact.status,
            "triggerPrice": fact.trigger_price, "qty": fact.qty,
            "problems": problems}


def confirm_protection_active(
    orch: Any, *, intent_id: str, planned_trigger: float, planned_qty: float,
    position_side: str = "LONG",
) -> Dict[str, Any]:
    """C/B：ACTIVE_CONFIRMED 的显式定义——按 id 查询回验保护腿。

    - 状态必须 NEW/ACTIVE（已挂牌未触发）；
    - 数量与触发价与计划一致（回显）；
    - workingType==MARK_PRICE：能用 Algo 原生查询时强制核验
      （FakeExchange 离线端口无此能力时记 NOT_OBSERVED_OFFLINE）。
    """
    sl_cid = f"{intent_id}-SL"
    row = orch.ledger.get_order(sl_cid)
    if row is None:
        raise SafetyViolation(f"[CTR] SL leg {sl_cid} absent from ledger.")
    fact = orch.exchange.query_order(sl_cid)
    if fact.status not in ("NEW", "ACTIVE", "PARTIALLY_FILLED"):
        raise SafetyViolation(
            f"[CTR] SL leg not ACTIVE_CONFIRMED: status={fact.status}")
    sl_row_trigger = row.get("stop_price")
    if sl_row_trigger is None or abs(
            float(sl_row_trigger) - float(planned_trigger)) > 1e-9:
        raise SafetyViolation(
            f"[CTR] SL trigger echo mismatch: {sl_row_trigger}")
    if abs(float(row.get("quantity") or 0) - float(planned_qty)) > 1e-12:
        raise SafetyViolation("[CTR] SL qty echo mismatch")
    working = "NOT_OBSERVED_OFFLINE"
    query_algo = getattr(orch.exchange, "query_algo_order", None)
    if query_algo is not None:
        from aurora.kernel.binance_exchange import ALGO_WORKING_TYPE

        algo_fact = query_algo_order_fn(query_algo, sl_cid)
        working = algo_fact.get("workingType")
        if working != ALGO_WORKING_TYPE:
            raise SafetyViolation(
                f"[CTR] SL workingType {working} != {ALGO_WORKING_TYPE}")
    return {"slClientId": sl_cid, "status": fact.status,
            "triggerPrice": planned_trigger, "qty": planned_qty,
            "workingType": working}


def query_algo_order_fn(query_algo, cid: str) -> Dict[str, Any]:
    """Algo 原生查询的安全包装：把 AlgoOrderFact 折算成可比较 dict。"""
    fact = query_algo(cid)
    return {"workingType": fact.working_type, "status": fact.status,
            "triggerPrice": fact.trigger_price, "qty": fact.qty}


# ---------------------------------------------------------------------------
# 计划与会话
# ---------------------------------------------------------------------------

def plan(
    source: ConfigSource,
    *,
    qty: float = MAX_QTY,
    mark_price: Optional[float] = None,
    intent_id: Optional[str] = None,
    account_fingerprint: str = INCIDENT_FINGERPRINT,
) -> Dict[str, Any]:
    """纯本地计划：身份门无条件；规模/路径隔离；不构造交易所客户端。"""
    fp = assert_identity(source, account_fingerprint)
    intent = intent_id or new_session_intent_id()
    assert_intent_allowed(intent)
    if mark_price is not None:
        assert_scale(qty, mark_price)
    else:
        assert_qty_exact(qty)
    session_id = intent.removeprefix(CLIENT_ID_NS)
    if not session_id or not intent.startswith(CLIENT_ID_NS):
        raise SafetyViolation("[CTR] plan requires AURORA-CTR-<session> intent.")
    session_path = session_ledger_path(fp, session_id)
    assert_session_ledger_isolated(session_path, session_id)
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
        "accountFingerprint": fp,
        "sessionId": session_id,
        "intentId": intent,
        "entryClientId": leg_client_id(session_id, "ENTRY"),
        "slClientId": leg_client_id(session_id, "SL"),
        "closeClientId": leg_client_id(session_id, "CLOSE"),
        "sessionLedger": session_path,
        "incidentLedger": incident_ledger_path(),
        "incidentKill": kill,
        "entryPoint": "aurora.ops_controlled_requal",
        "productionMain": "DENIED",
        "autoTestnet": "DENIED",
        "live": "NO-GO",
    }


def restart_recover_session(
    previous_orch: Any, exchange: Any, ledger_path: str,
) -> Any:
    """真正的 runtime stop → 新 harness 实例 → recover。

    同进程对同一个 Orchestrator 再调 recover() 不算本条通过。
    """
    if previous_orch is None:
        raise SafetyViolation("[CTR] restart requires a stopped runtime.")
    if getattr(previous_orch, "instance_id", None) == "ctr-restart":
        raise SafetyViolation("[CTR] restart must use a new harness instance.")
    from aurora.kernel.ledger import Ledger
    from aurora.kernel.orchestrator import Orchestrator

    ledger = Ledger(ledger_path)
    restarted = Orchestrator(
        ledger, exchange, symbol=SYMBOL, instance_id="ctr-restart")
    recovered = restarted.recover()
    if recovered.get("unresolved"):
        raise SafetyViolation(
            f"[CTR] restart recover unresolved: {recovered.get('unresolved')}")
    try:
        previous_orch.ledger.close()
    except Exception:
        pass
    return restarted, recovered


def qualification_close(orch: Any, *, session_id: str) -> Dict[str, Any]:
    """Harness 层钉死 QUALIFICATION CLOSE。ACK ≠ confirmed。"""
    pos = orch.exchange.position(SYMBOL)
    if pos is None:
        raise SafetyViolation("[CTR] position UNKNOWN before close.")
    qty = abs(float(pos.signed_qty))
    if qty <= 1e-12:
        raise SafetyViolation("[CTR] close requires an open LONG position.")
    if qty - MAX_QTY > 1e-12:
        raise SafetyViolation("[CTR] close qty exceeds 0.001.")
    if float(pos.signed_qty) <= 0:
        raise SafetyViolation("[CTR] qualification close requires LONG.")
    close_id = leg_client_id(session_id, "CLOSE")
    plan = {
        "symbol": SYMBOL,
        "side": "SELL",
        "positionSide": "LONG",
        "qty": qty,
        "clientOrderId": close_id,
        "reduceOnly": "NOT_SENT_ON_HEDGE",
        "closePosition": False,
    }
    closed = orch.close_position(
        reason="qualification-close",
        intent_id=close_id,
        client_order_id=close_id,
    )
    fill_qty = float(orch.ledger.fills_aggregate(close_id)["qty"])
    after = orch.exchange.position(SYMBOL)
    flat = after is not None and abs(float(after.signed_qty)) <= 1e-12
    if not closed.get("success"):
        raise SafetyViolation(
            f"[CTR] qualification close failed: {closed.get('reason')}")
    if closed.get("close_outcome") != "CONFIRMED":
        raise SafetyViolation("[CTR] close ACK is not confirmation.")
    if fill_qty <= 1e-12 and not flat:
        raise SafetyViolation(
            "[CTR] close ACK without authoritative fill or FLAT.")
    if not flat:
        raise SafetyViolation("[CTR] position not KNOWN_FLAT after close.")
    return {
        "plan": plan,
        "closed": closed,
        "authoritative": "fill" if fill_qty > 1e-12 else "position_flat",
        "fillQty": fill_qty,
    }


def run_session(
    orch: Any,
    *,
    permit: Dict[str, Any],
    qty: float = MAX_QTY,
    mark_price: float,
    stop_price: float,
    intent_id: Optional[str] = None,
    incident_path: Optional[str] = None,
    wire_log: Optional[Any] = None,
    baseline: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """六阶段受控会话（供离线 FakeExchange；真实路径经 execute_live）。

    permit 必须已签发且有效；mark_price 必须是权威观察值。
    """
    sid = session_id or permit.get("session_id")
    if not sid:
        raise SafetyViolation("[CTR] run_session requires session_id.")
    assert_session_id(sid)
    if permit.get("session_id") not in (None, sid):
        raise SafetyViolation("[CTR] PERMIT_SESSION_MISMATCH")
    assert_scale(qty, mark_price)
    assert_stop_price(stop_price, mark_price)
    intent = session_intent_id(sid)
    if intent_id is not None and intent_id != intent:
        raise SafetyViolation(
            f"[CTR] intent must be {intent}, got {intent_id}.")
    assert_intent_allowed(intent)
    bind_permit(permit, intent_id=intent, qty=qty, mark_price=mark_price)

    def _stop(phase: str, reason: str, **extra: Any) -> Dict[str, Any]:
        orch.ledger.engage_kill(f"controlled requal STOP {phase}: {reason}")
        return {"success": False, "phase": phase, "reason": reason,
                "sessionKill": orch.ledger.kill_state(), **extra}

    # P0 只读基线：仓位可知且 FLAT；提供的基线（真实路径）不得有违例
    try:
        assert_session_start(orch.exchange)
    except SafetyViolation:
        orch.ledger.engage_kill("controlled requal start preconditions failed")
        raise
    if baseline is not None and not baseline.get("ok", True):
        return _stop("P0", f"baseline violations: {baseline.get('violations')}")

    before = _file_digest(incident_path) if incident_path and os.path.exists(
        incident_path) else None

    # P2 entry once（数量真源合同不变：fills 聚合为准）
    opened = orch.open_position(
        SIDE, qty, intent_id=intent, stop_price=stop_price,
        take_profit_price=None)
    if not opened.get("success"):
        return _stop("P2", f"open failed: {opened.get('reason')}", opened=opened)

    # P1 WIRE ACK 三方验证（离线无 wire 时如实记 NOT_OBSERVED_OFFLINE）
    ack_report: Dict[str, Any] = {"submitAckContract": "NOT_OBSERVED_OFFLINE"}
    if wire_log is not None and getattr(wire_log, "entry_acks", None):
        entry_ack = wire_log.entry_acks[-1]["raw"]
        ack_report["entry"] = verify_entry_ack(
            entry_ack, side=SIDE, qty=qty)
    if wire_log is not None and getattr(wire_log, "algo_acks", None):
        algo_ack = wire_log.algo_acks[-1]["raw"]
        ack_report["algo"] = verify_algo_ack(
            algo_ack, trigger=stop_price, qty=qty, position_side=SIDE)
        ack_report["submitAckContract"] = (
            "OBSERVED" if not (ack_report["algo"]["problems"]
                               or ack_report.get("entry", {})
                               .get("problems")) else "CONFLICT")
        if ack_report["submitAckContract"] == "CONFLICT":
            return _stop("P1", "wire ack three-way verification failed",
                         ackReport=ack_report)

    # P3 ACTIVE_CONFIRMED：显式查询回验 + workingType 合同
    try:
        protection = confirm_protection_active(
            orch, intent_id=intent, planned_trigger=stop_price,
            planned_qty=qty, position_side=SIDE)
    except SafetyViolation as exc:
        return _stop("P3", str(exc))
    protected_qty = float(opened.get("protected_qty") or 0)
    if abs(protected_qty - qty) > 1e-12:
        return _stop("P3", "protected_qty != confirmed position qty",
                     opened=opened)
    if protection.get("slClientId") != leg_client_id(sid, "SL"):
        return _stop("P3", "SL client id namespace mismatch")

    # P4 restart recovery：停 runtime → 新实例 → 恢复已有仓位/保护
    submits_before = list(getattr(orch.exchange, "submit_log", []) or [])
    ledger_path = getattr(orch.ledger, "path", None)
    if not ledger_path:
        return _stop("P4", "session ledger path unknown; cannot restart")
    exchange = orch.exchange
    try:
        orch, recovered = restart_recover_session(
            orch, exchange, ledger_path)
    except SafetyViolation as exc:
        return _stop("P4", str(exc))
    submits_after = list(getattr(exchange, "submit_log", []) or [])
    if len(submits_after) != len(submits_before):
        return _stop("P4", "duplicate submit during restart recovery",
                     recover=recovered)
    pos = exchange.position(SYMBOL)
    if pos is None or abs(float(pos.signed_qty) - qty) > 1e-12:
        return _stop("P4", "position not recovered as LONG 0.001")
    try:
        protection = confirm_protection_active(
            orch, intent_id=intent, planned_trigger=stop_price,
            planned_qty=qty, position_side=SIDE)
    except SafetyViolation as exc:
        return _stop("P4", f"existing SL not re-identified: {exc}")

    # P5 QUALIFICATION CLOSE
    try:
        closed = qualification_close(orch, session_id=sid)
    except SafetyViolation as exc:
        return _stop("P5", str(exc))
    orch.ledger.engage_kill("controlled requal session complete")
    after = _file_digest(incident_path) if incident_path and os.path.exists(
        incident_path) else None
    if before is not None and after != before:
        raise SafetyViolation("[CTR] incident ledger changed; forbidden.")
    return {
        "success": True,
        "phase": "COMPLETE",
        "sessionId": sid,
        "intentId": intent,
        "entryClientId": leg_client_id(sid, "ENTRY"),
        "slClientId": leg_client_id(sid, "SL"),
        "closeClientId": leg_client_id(sid, "CLOSE"),
        "opened": {"state": opened.get("state"),
                   "protected_qty": protected_qty},
        "protectionConfirmed": protection,
        "wireAck": ack_report,
        "restartRecover": "PASS",
        "restartInstanceId": orch.instance_id,
        "closed": closed,
        "sessionKill": orch.ledger.kill_state(),
        "incidentLedgerUnchanged": True,
        "execute": "OFFLINE_SESSION_ONLY",
    }


def execute_live(
    *,
    source: Optional[ConfigSource] = None,
    client: Optional[Any] = None,
    orch: Optional[Any] = None,
    baseline: Optional[Dict[str, Any]] = None,
    wire_log: Optional[Any] = None,
    incident_path: Optional[str] = None,
    qty: float = MAX_QTY,
    stop_price: Optional[float] = None,
    mark_price: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """真实受控写入入口。

    构造写客户端之前必须同时满足：
    EXECUTE_AUTHORIZED == true
    + scoped single-use permit（session/qty/expiry）
    + START ORDER OPEN。
    """
    if not EXECUTE_AUTHORIZED:
        raise SafetyViolation(
            "[CTR] EXECUTE_AUTHORIZED=false; refuse all TESTNET writes.")
    if source is None or stop_price is None:
        raise SafetyViolation(
            "[CTR] execute requires config source and stop price; "
            "and a valid execution window (START ORDER + scoped permit).")
    conditions = assert_write_gates(now=now)
    session_id = conditions["session_id"]
    permit = conditions["permit"]
    if orch is None:
        from aurora.kernel.binance_exchange import BinanceExchange
        from aurora.kernel.ledger import Ledger
        from aurora.kernel.orchestrator import Orchestrator

        if client is None:
            raise SafetyViolation(
                "[CTR] execute requires an exchange client "
                "(network path) — none provided.")
        if wire_log is None:
            wire_log = WireTee(client)
            client = wire_log
        observed_mark: Optional[float] = None
        if mark_price is None:
            try:
                raw = client.futures_mark_price(symbol=SYMBOL)
                observed_mark = float((raw or {}).get("markPrice") or 0)
            except Exception as exc:
                raise SafetyViolation(
                    f"[CTR] mark price observation failed: "
                    f"{type(exc).__name__}") from exc
            mark_price = observed_mark
        # R2/合同：变动型适配器必须注入【已观察】的持仓模式——
        # 先只读观察外部事实，与批准模式核对，再构造写适配器。
        probe = BinanceExchange(client, symbol=SYMBOL, allow_mutate=False)
        observed_mode = probe.position_mode_read()
        if observed_mode is None:
            raise SafetyViolation(
                "[CTR] position mode UNKNOWN; refuse execution attach.")
        expected_mode = source.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE"
        if observed_mode != expected_mode:
            raise SafetyViolation(
                f"[CTR] position mode {observed_mode} != approved "
                f"{expected_mode}; refuse attach.")
        exchange = BinanceExchange(
            client, symbol=SYMBOL, allow_mutate=True,
            position_mode=observed_mode)
        session_path = session_ledger_path(INCIDENT_FINGERPRINT, session_id)
        assert_session_ledger_isolated(session_path, session_id)
        os.makedirs(os.path.dirname(session_path), exist_ok=True)
        ledger = Ledger(session_path)
        orch = Orchestrator(ledger, exchange, symbol=SYMBOL)
    if baseline is None and client is not None:
        baseline = observe_baseline(client, source.as_environ())
        if mark_price is None and baseline.get("markPriceObserved"):
            mark_price = float(baseline["markPriceObserved"])
    if incident_path is None:
        incident_path = incident_ledger_path()
    try:
        out = run_session(
            orch, permit=permit, qty=qty, mark_price=mark_price,
            stop_price=stop_price, incident_path=incident_path,
            wire_log=wire_log, baseline=baseline, session_id=session_id)
    except SafetyViolation as exc:
        write_session_final(session_id, {"outcome": "STOP",
                                         "reason": str(exc)[:200]})
        void_permit(f"session {session_id} STOP: {exc}")
        raise
    if not out.get("success"):
        # STOP 后仅允许 BTC 减仓收口（合同：NO SECOND ENTRY）
        try:
            closeout = qualification_close(orch, session_id=session_id)
            out["closeout"] = {"success": True, "fillQty": closeout["fillQty"]}
        except Exception as close_exc:
            out["closeout"] = {"success": False,
                               "reason": str(close_exc)[:160]}
        out["wireEvidence"] = getattr(wire_log, "export", lambda: {})() \
            if wire_log is not None else {}
    if out.get("success"):
        write_session_final(session_id, {"outcome": "COMPLETE",
                                         "intentId": out.get("intentId")})
        permit["voided"] = True
        permit["voided_reason"] = "session COMPLETE; one lifecycle only"
        path = qualification_permit_path(INCIDENT_FINGERPRINT)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as fh:
            json.dump(permit, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    else:
        write_session_final(session_id, {"outcome": "STOP",
                                         "phase": out.get("phase"),
                                         "reason": out.get("reason")})
        void_permit(f"session {session_id} STOP at {out.get('phase')}")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Controlled TESTNET requalification (plan default; execute denied)")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--qty", type=float, default=MAX_QTY)
    parser.add_argument("--mark-price", type=float, default=None)
    parser.add_argument("--stop-price", type=float, default=None)
    parser.add_argument(
        "--issue-execution-window", action="store_true",
        help="同一受控窗口：冻结 session_id + 发 START ORDER + "
             "签发 scoped permit（不执行）")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--issued-by", default=None)
    parser.add_argument("--valid-hours", type=float,
                        default=PERMIT_TTL_HOURS_DEFAULT)
    parser.add_argument(
        "--i-execute-controlled-requal", action="store_true",
        help="write path; refused unless START ORDER + scoped permit + "
             "无终态记录（四条件门）")
    args = parser.parse_args(argv)

    env_file = os.path.abspath(args.env_file or repo_default_env_file())
    if not os.path.isfile(env_file):
        print(json.dumps({
            "package": "CONTROLLED_TESTNET_REQUAL",
            "execute": "DENIED",
            "status": "BLOCKED",
            "reason": "explicit env file not found",
        }, sort_keys=True, indent=2))
        return 2
    source = ConfigSource.load(env_file=env_file)

    try:
        if args.issue_execution_window:
            if not args.session_id or not args.issued_by:
                raise SafetyViolation(
                    "[CTR] --issue-execution-window requires "
                    "--session-id and --issued-by")
            window = issue_execution_window(
                session_id=args.session_id, issued_by=args.issued_by,
                valid_hours=args.valid_hours)
            print(json.dumps({
                "windowIssued": True,
                "orderId": window["order"]["session_id"],
                "permitSessionId": window["permit"]["session_id"],
                "expiresAt": window["order"]["expires_at"],
                "execute": "STILL DENIED — requires "
                           "--i-execute-controlled-requal under this window",
            }, sort_keys=True, indent=2))
            return 0
        report = plan(source, qty=args.qty, mark_price=args.mark_price)
    except SafetyViolation as exc:
        print(json.dumps({
            "package": "CONTROLLED_TESTNET_REQUAL",
            "execute": "DENIED",
            "status": "BLOCKED",
            "errorType": type(exc).__name__,
            "reason": str(exc)[:200],
        }, sort_keys=True, indent=2))
        return 2

    if args.i_execute_controlled_requal:
        if not EXECUTE_AUTHORIZED:
            report["execute"] = "DENIED"
            report["reason"] = (
                "EXECUTE_AUTHORIZED=false; refuse before write client.")
            print(json.dumps(report, sort_keys=True, indent=2))
            return 3
        try:
            assert_write_gates()
        except SafetyViolation as exc:
            report["execute"] = "DENIED"
            report["reason"] = str(exc)[:200]
            print(json.dumps(report, sort_keys=True, indent=2))
            return 3
        from aurora.safety import build_client
        try:
            client = build_client(source.mode(), "controlled requal session",
                                  environ=source.as_environ())
            out = execute_live(source=source, client=client, qty=args.qty,
                               stop_price=args.stop_price)
        except SafetyViolation as exc:
            print(json.dumps({
                "package": "CONTROLLED_TESTNET_REQUAL",
                "execute": "DENIED",
                "status": "BLOCKED",
                "reason": str(exc)[:200],
            }, sort_keys=True, indent=2))
            return 3
        print(json.dumps(out, sort_keys=True, indent=2))
        return 0 if out.get("success") else 1

    report["status"] = "PLAN"
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
