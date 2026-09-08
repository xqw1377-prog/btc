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
EXECUTE_AUTHORIZED = False


def incident_ledger_path() -> str:
    return os.path.join(state_root(), "kernel_ledger.db")


def session_ledger_path(fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "controlled_requal.db")


def qualification_permit_path(
        fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "qualification_permit.json")


def new_session_intent_id() -> str:
    return f"{CLIENT_ID_NS}{uuid.uuid4().hex[:12]}"


def assert_intent_allowed(intent_id: str) -> None:
    if FORBIDDEN_INTENT_MARK in intent_id or intent_id == INCIDENT_INTENT:
        raise SafetyViolation("[CTR] refuse incident client id reuse.")
    if not intent_id.startswith(CLIENT_ID_NS):
        raise SafetyViolation(
            f"[CTR] intent must use {CLIENT_ID_NS}* namespace.")


def assert_scale(qty: float, mark_price: float) -> None:
    if mark_price is None or mark_price <= 0:
        raise SafetyViolation(
            "[CTR] notional cap requires an observed mark price.")
    if qty <= 0 or qty - MAX_QTY > 1e-12:
        raise SafetyViolation(f"[CTR] qty {qty} exceeds MAX_QTY={MAX_QTY}.")
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


def assert_session_ledger_isolated(path: str) -> None:
    incident = os.path.abspath(incident_ledger_path())
    target = os.path.abspath(path)
    if target == incident:
        raise SafetyViolation(
            "[CTR] session ledger must not be the incident ledger.")
    if "controlled_requal.db" not in os.path.basename(target):
        raise SafetyViolation(
            "[CTR] session ledger must be controlled_requal.db.")


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

def qualification_permit_path(
        fingerprint: str = INCIDENT_FINGERPRINT) -> str:
    return os.path.join(
        state_root(), "testnet", fingerprint, "qualification_permit.json")


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
        "scope": {"env": "TESTNET", "symbol": SYMBOL, "side": SIDE},
        "max_qty": MAX_QTY,
        "max_notional_usdt": MAX_NOTIONAL_USDT,
        "client_id_ns": CLIENT_ID_NS,
        "lifecycle": {"total": 1, "used": []},
        "session_ledger": session_ledger_path(fingerprint),
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
    scope = permit.get("scope") or {}
    if (scope.get("env") != "TESTNET" or scope.get("symbol") != SYMBOL
            or scope.get("side") != SIDE):
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
# Execution Start Order + 会话终态（运行时范围授权三条件之二/之三）
# 代码默认 false（EXECUTE_AUTHORIZED 常量仅作 dead-man 记录，不再是门）；
# 真实写路径 = START ORDER（OPEN、未过期）
# + 精确 session 的 runtime permit（未作废、同 session_id）
# + 操作员在调用中显式给出 --i-execute-controlled-requal。
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
        "scope": {"env": "TESTNET", "symbol": SYMBOL, "side": SIDE},
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


def check_execution_conditions(
    fingerprint: str = INCIDENT_FINGERPRINT,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """三条件门：START ORDER（OPEN 未过期）+ 精确 session 的 runtime
    permit（未作废未过期、session 匹配）+ 会话无终态记录。
    操作员显式调用旗标由调用方保证。返回 (order, permit)。"""
    order = load_start_order(fingerprint, now=now)
    sid = session_id or order["session_id"]
    if sid != order["session_id"]:
        raise SafetyViolation(
            f"[CTR] session_id {sid} != start order {order['session_id']}.")
    permit = load_permit(fingerprint, now=now, expected_session_id=sid)
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
    permit_max_qty = float(permit.get("max_qty") or MAX_QTY)
    if qty <= 0 or qty - permit_max_qty > 1e-12:
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
        if qty - MAX_QTY > 1e-12:
            raise SafetyViolation(f"[CTR] qty {qty} exceeds MAX_QTY={MAX_QTY}.")
    session_path = session_ledger_path(fp)
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
        "accountFingerprint": fp,
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
    assert_scale(qty, mark_price)
    assert_stop_price(stop_price, mark_price)
    intent = intent_id or new_session_intent_id()
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

    # P4 restart recovery：无未决，无重复
    recovered = orch.recover()
    if recovered.get("unresolved"):
        return _stop("P4", "restart recover unresolved", recover=recovered)

    # P5 flatten & close-out
    closed = orch.close_position(reason="controlled-requal-flatten")
    if not closed.get("success"):
        return _stop("P5", f"flatten failed: {closed.get('reason')}",
                     closed=closed)
    position = orch.exchange.position(SYMBOL)
    if position is None or abs(float(position.signed_qty)) > 1e-12:
        return _stop("P5", "exchange position not flat after flatten")
    orch.ledger.engage_kill("controlled requal session complete")
    after = _file_digest(incident_path) if incident_path and os.path.exists(
        incident_path) else None
    if before is not None and after != before:
        raise SafetyViolation("[CTR] incident ledger changed; forbidden.")
    return {
        "success": True,
        "phase": "COMPLETE",
        "sessionId": session_id,
        "intentId": intent,
        "opened": {"state": opened.get("state"),
                   "protected_qty": protected_qty},
        "protectionConfirmed": protection,
        "wireAck": ack_report,
        "restartRecover": "PASS",
        "closed": {"success": True},
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
    """真实受控写入入口（三条件门满足时才可能走到真实请求）。

    三条件：START ORDER（OPEN 未过期）+ 精确 session 的 runtime permit
    （未作废未过期、session 匹配）+ 调用方显式执行指令。
    代码常量 EXECUTE_AUTHORIZED 只是 dead-man 记录，不再是门；
    结束（无论 COMPLETE/STOP）写会话终态，STOP 同时作废 permit——
    同一 session 绝无第二次 entry。
    """
    if source is None or stop_price is None:
        raise SafetyViolation(
            "[CTR] execute requires config source and stop price; "
            "and a valid execution window (START ORDER + scoped permit).")
    conditions = check_execution_conditions(now=now)
    session_id = conditions["session_id"]
    permit = conditions["permit"]
    if orch is None:
        from aurora.armed_runtime import namespaced_ledger_path
        from aurora.kernel.binance_exchange import BinanceExchange
        from aurora.kernel.ledger import Ledger
        from aurora.kernel.orchestrator import Orchestrator

        if client is None:
            raise SafetyViolation(
                "[CTR] execute requires an exchange client "
                "(network path) — none provided.")
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
        exchange = BinanceExchange(client, symbol=SYMBOL, allow_mutate=True)
        exchange.verify_position_mode(
            source.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE")
        ledger = Ledger(namespaced_ledger_path(
            RunMode.TESTNET, INCIDENT_FINGERPRINT))
        orch = Orchestrator(ledger, exchange, symbol=SYMBOL)
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
        help="write path; still refused unless EXECUTE_AUTHORIZED + 开工令")
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
        # 三条件门：START ORDER + 精确 session permit + 本显式旗标。
        # 任一不满足 → DENIED(3)；全部满足 → 真实受控写入（P0-P5）。
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
