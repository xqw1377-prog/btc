"""P3-R3.1 read-only risk adjudicator.

Calls the existing evaluate_risk() contract. Does not recompute risk math,
does not submit orders, and does not open a trading path.

Canonical algorithm: aurora-canonical-json-v1
Hash algorithm: sha256

The plan log is a local append-only SQLite file. It has no trading writes.
A caller connection that already has an open transaction is refused before
any statement, so uncommitted caller rows stay uncommitted.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aurora.risk_contract_harness import (
    _is_defensive_candidate,
    _is_new_risk_action,
    assert_risk_monotonicity,
    evaluate_risk,
)

CANONICAL_VERSION = "aurora-canonical-json-v1"
HASH_ALG = "sha256"
RUNTIME_KIND = "P3_R3_1_RISK_ADJUDICATOR"
PARAMETER_STATUS = "PROVISIONAL_E3_PARAM"

_BUDGET_FIELDS = (
    "per_trade_loss_budget",
    "cluster_loss_budget",
    "overlay_pool_loss_budget",
    "event_increment_budget",
    "managed_gross_exposure_max",
    "funding_cost_budget",
    "drawdown_budget",
)
_SLA_FIELDS = (
    "sla_decision_sec",
    "sla_account_sec",
    "sla_market_sec",
    "skew_limit_sec",
)
_NON_FINITE_TEXT = frozenset({
    "nan", "inf", "infinity", "+inf", "-inf", "+infinity", "-infinity",
})


class CallerTransactionOpen(RuntimeError):
    """Caller still has an open transaction. Nothing was written or committed."""


class NumericFault(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decimal_text(number: Decimal) -> str:
    if not number.is_finite():
        raise NumericFault("NON_FINITE")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0", "-"):
        text = "0"
    return text


def canonical_dumps(obj: Any) -> str:
    return _canon(obj)


def _canon(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, Decimal):
        return _decimal_text(obj)
    if isinstance(obj, float):
        raise NumericFault("NON_FINITE" if not math.isfinite(obj) else "BINARY_FLOAT")
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list):
        return "[" + ",".join(_canon(item) for item in obj) + "]"
    if isinstance(obj, dict):
        parts = []
        for key in sorted(obj):
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            parts.append(json.dumps(key, ensure_ascii=False) + ":" + _canon(obj[key]))
        return "{" + ",".join(parts) + "}"
    raise TypeError("unsupported canonical value: %s" % type(obj).__name__)


def _connect(log_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(log_path)
    if parent and not os.path.isdir(parent):
        raise OSError("plan log directory is not writable")
    conn = sqlite3.connect(
        log_path, timeout=15, isolation_level=None, check_same_thread=False,
    )
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.rollback()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise CallerTransactionOpen(
            "caller connection has an open transaction; refusing before any write"
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS adjudicator_meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS declaration_binding ("
            "declaration_key TEXT PRIMARY KEY, object_name TEXT NOT NULL, "
            "source_text TEXT NOT NULL, version_claim TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, canonical_body TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS adjudication_record ("
            "risk_plan_key TEXT PRIMARY KEY, record_canonical TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS invalidation_event ("
            "event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "risk_plan_key TEXT NOT NULL, evaluation_at TEXT NOT NULL, "
            "reason TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM adjudicator_meta WHERE key = 'canonical_version'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO adjudicator_meta (key, value) VALUES ('canonical_version', ?)",
                (CANONICAL_VERSION,),
            )
            conn.execute(
                "INSERT INTO adjudicator_meta (key, value) VALUES ('hash_alg', ?)",
                (HASH_ALG,),
            )
        elif row[0] != CANONICAL_VERSION:
            raise sqlite3.DatabaseError("plan log canonical version mismatch")
        conn.commit()
    except CallerTransactionOpen:
        _rollback(conn)
        raise
    except Exception:
        _rollback(conn)
        raise


def open_plan_log(log_path: str) -> sqlite3.Connection:
    conn = _connect(log_path)
    _ensure_schema(conn)
    return conn


def read_records(log_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(log_path):
        return []
    conn = _connect(log_path)
    try:
        try:
            rows = conn.execute(
                "SELECT risk_plan_key, record_canonical FROM adjudication_record "
                "ORDER BY rowid"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {"risk_plan_key": key, "record_canonical": body}
            for key, body in rows
        ]
    finally:
        conn.close()


def read_bindings(log_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(log_path):
        return []
    conn = _connect(log_path)
    try:
        try:
            rows = conn.execute(
                "SELECT declaration_key, object_name, source_text, version_claim, "
                "content_hash, canonical_body FROM declaration_binding ORDER BY rowid"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "declaration_key": key,
                "object_name": name,
                "source_text": source,
                "version_claim": version,
                "content_hash": content,
                "canonical_body": body,
            }
            for key, name, source, version, content, body in rows
        ]
    finally:
        conn.close()


def append_invalidation(
    log_path: str, risk_plan_key: str, evaluation_at: str, reason: str,
) -> None:
    conn = _connect(log_path)
    try:
        _ensure_schema(conn)
        if conn.in_transaction:
            raise CallerTransactionOpen(
                "caller connection has an open transaction; refusing before any write"
            )
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO invalidation_event (risk_plan_key, evaluation_at, reason) "
            "VALUES (?, ?, ?)",
            (risk_plan_key, evaluation_at, reason),
        )
        conn.commit()
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or value == "":
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise NumericFault("RANGE_VIOLATION")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise NumericFault("NON_FINITE" if not math.isfinite(value) else "BINARY_FLOAT")
    if isinstance(value, str):
        if value.strip().lower() in _NON_FINITE_TEXT:
            raise NumericFault("NON_FINITE")
        try:
            return Decimal(value)
        except Exception as exc:
            raise NumericFault("RANGE_VIOLATION") from exc
    raise NumericFault("RANGE_VIOLATION")


def _classify_number(value: Any, *, lo: Decimal, hi: Decimal, unit: str, sign: str) -> List[str]:
    if isinstance(value, dict) and "value" in value and "unit" in value:
        codes = []
        if value.get("unit") != unit:
            codes.append("UNIT_MISMATCH")
        codes.extend(_classify_number(value.get("value"), lo=lo, hi=hi, unit=unit, sign=sign))
        return codes
    if _blank(value):
        return []
    try:
        number = _as_decimal(value)
    except NumericFault as exc:
        return [exc.code]
    if sign == "nonneg" and number < 0:
        return ["SIGN_MISMATCH"]
    if number < lo or number > hi:
        return ["RANGE_VIOLATION"]
    return []


def _walk_nonfinite(obj: Any, found: List[str]) -> None:
    if isinstance(obj, float):
        found.append("NON_FINITE" if not math.isfinite(obj) else "BINARY_FLOAT")
    elif isinstance(obj, Decimal) and not obj.is_finite():
        found.append("NON_FINITE")
    elif isinstance(obj, dict):
        for value in obj.values():
            _walk_nonfinite(value, found)
    elif isinstance(obj, list):
        for value in obj:
            _walk_nonfinite(value, found)


def _is_zero(value: Any) -> bool:
    if isinstance(value, bool) or value is None or value == "":
        return False
    try:
        return _as_decimal(value) == 0
    except NumericFault:
        return False


def _position_unknown(account: Dict[str, Any]) -> bool:
    if "positions" not in account or account.get("positions") is None:
        return True
    positions = account["positions"]
    if isinstance(positions, dict):
        if "status" in positions:
            status = positions.get("status")
            if _blank(status) or str(status).upper() in ("UNKNOWN", "UNAVAILABLE"):
                return True
    return False


def _verifiable_flat(account: Dict[str, Any]) -> bool:
    if _position_unknown(account):
        return False
    positions = account.get("positions")
    if positions == []:
        return True
    if not isinstance(positions, dict):
        return False
    quantities = [
        positions[key]
        for key in ("btc", "eth", "usdt", "btc_overlay", "eth_overlay", "event_increment")
        if key in positions
    ]
    if not quantities:
        return False
    return all(_is_zero(qty) for qty in quantities)


def _existing_label(account: Dict[str, Any]) -> str:
    if _position_unknown(account):
        return "UNKNOWN"
    if _verifiable_flat(account):
        return "NOT_APPLICABLE"
    label = account.get("protection_state")
    if _blank(label):
        return "UNKNOWN"
    return str(label)


def _event_request(decision: Dict[str, Any]) -> Decimal:
    if decision.get("event_increment_request") != "ELIGIBLE":
        return Decimal("0")
    current = (decision.get("current_state") or {}).get("event_increment") or 0
    target = (decision.get("target_state") or {}).get("event_increment") or 0
    try:
        gap = _as_decimal(target) - _as_decimal(current)
    except NumericFault:
        return Decimal("0")
    return gap if gap > 0 else Decimal("0")


def _floatify(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {key: _floatify(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_floatify(value) for value in obj]
    return obj


def _freeze(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return Decimal(str(obj))
    if isinstance(obj, Decimal):
        return obj
    if isinstance(obj, dict):
        return {key: _freeze(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_freeze(value) for value in obj]
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)


def _policy_body(policy: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in policy.items() if key != "policy_hash"}


def _declaration_key(source: Any, object_name: str, version_claim: str) -> str:
    payload = {
        "canonical_version": CANONICAL_VERSION,
        "hash_alg": HASH_ALG,
        "object": object_name,
        "source": source if source is not None else None,
        "version_claim": version_claim,
    }
    return _sha(canonical_dumps(payload))


def _content_hash(obj: Any) -> str:
    return _sha(canonical_dumps(obj))


def _risk_plan_key(hashes: Dict[str, str], evaluation_at: str, sla_rule_id: str) -> str:
    payload = {
        "account_content_hash": hashes["account"],
        "canonical_version": CANONICAL_VERSION,
        "decision_content_hash": hashes["decision"],
        "evaluation_at": evaluation_at,
        "hash_alg": HASH_ALG,
        "market_content_hash": hashes["market"],
        "policy_content_hash": hashes["policy"],
        "sla_rule_id": sla_rule_id,
    }
    return _sha(canonical_dumps(payload))


def _truth(decision: Dict[str, Any], account: Dict[str, Any], market: Dict[str, Any], evaluation_at: str) -> Dict[str, Any]:
    proposed_ok = account.get("proposed_protection_state") == "ACTIVE_CONFIRMED"
    return {
        "as_of": evaluation_at,
        "account_truth": {
            "status": account.get("status"),
            "version": account.get("account_version"),
            "btc_nav": account.get("btc_nav"),
            "equity": account.get("equity"),
        },
        "position_truth": {
            "status": "UNKNOWN" if _position_unknown(account) else "KNOWN",
            "version": account.get("position_version"),
        },
        "protection_truth": {
            "status": "KNOWN",
            "version": account.get("protection_version"),
            "stop_plan_state": "AUTHORITATIVE" if proposed_ok else "PROPOSED",
            "active_protection_state": account.get("protection_state") or "UNKNOWN",
        },
        "portfolio_risk_truth": {"drawdown": account.get("drawdown")},
        "market_cost_truth": {
            "btc_funding": market.get("btc_funding"),
            "spread": market.get("spread"),
            "freshness": market.get("freshness"),
        },
        "governance": {
            "kill": "ACTIVE" if account.get("kill") == "ACTIVE" else "CLEAR",
            "incident": "INCIDENT_LOCKED" if account.get("incident") == "ACTIVE" else "CLEAR",
        },
    }


def _decimal_from_math(value: Any) -> Decimal:
    """Harness results are binary floats. Record text uses the shortest round trip."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return Decimal("0")
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal("0")
    if isinstance(value, int):
        return Decimal(value)
    return _as_decimal(value)


def _vectors(plan: Optional[Dict[str, Any]], decision: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
    if plan is None:
        cluster = decision.get("crypto_beta_cluster") or {}
        try:
            requested = _as_decimal(cluster.get("total_request") or 0)
        except NumericFault:
            requested = Decimal("0")
        return requested, Decimal("0")
    requested = _decimal_from_math(plan["crypto_beta_cluster"]["requested"]["total"])
    requested += _decimal_from_math(plan["event_increment"]["requested"])
    allowed = _decimal_from_math(plan["crypto_beta_cluster"]["allowed"]["total"])
    allowed += _decimal_from_math(plan["event_increment"]["allowed"])
    return requested, allowed


def _row9_state(defensive: bool, new_risk: bool, plan: Optional[Dict[str, Any]]) -> str:
    if defensive and not new_risk:
        return "DEFENSIVE_ONLY"
    if plan is None:
        return "BLOCK_NEW_RISK"
    state = plan.get("risk_state")
    if state == "REDUCED":
        return "REDUCED"
    if state == "PASS":
        return "PASS"
    if state == "DEFENSIVE_ONLY":
        return "DEFENSIVE_ONLY"
    return "BLOCK_NEW_RISK"


def _decide(hits: Sequence[Tuple[int, str]], defensive: bool, new_risk: bool, plan: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    if any(code == "VERSION_UNFIXED" for _, code in hits):
        return "UNKNOWN", False
    if not hits:
        return _row9_state(defensive, new_risk, plan), True
    row = min(item[0] for item in hits)
    if row <= 4:
        return "BLOCK_NEW_RISK", False
    if row == 5 and defensive:
        return "DEFENSIVE_ONLY", True
    if row < 9:
        return "BLOCK_NEW_RISK", True
    return _row9_state(defensive, new_risk, plan), True


def _local_hits(
    decision: Dict[str, Any],
    account: Dict[str, Any],
    market: Dict[str, Any],
    policy: Dict[str, Any],
    evaluation_at: str,
) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    versions = (
        decision.get("decision_key"),
        account.get("account_version"),
        account.get("position_version"),
        account.get("protection_version"),
        market.get("quote_version"),
        policy.get("policy_version"),
        evaluation_at,
    )
    if any(_blank(item) for item in versions) or _parse_ts(evaluation_at) is None:
        hits.append((0, "VERSION_UNFIXED"))

    floated: List[str] = []
    for blob in (decision, account, market, policy):
        _walk_nonfinite(blob, floated)
    for code in floated:
        hits.append((2, code))

    for code in _classify_number(
        account.get("btc_nav"), lo=Decimal("0"), hi=Decimal("1000000"), unit="BTC", sign="nonneg",
    ):
        hits.append((2, code))
    for code in _classify_number(
        account.get("equity"), lo=Decimal("0"), hi=Decimal("1000000000000"), unit="QUOTE", sign="nonneg",
    ):
        hits.append((2, code))
    for code in _classify_number(
        account.get("drawdown"), lo=Decimal("0"), hi=Decimal("1"), unit="RATIO", sign="nonneg",
    ):
        hits.append((2, code))
    for code in _classify_number(
        market.get("btc_funding"), lo=Decimal("-1"), hi=Decimal("1"), unit="RATE", sign="any",
    ):
        hits.append((2, code))
    for code in _classify_number(
        market.get("spread"), lo=Decimal("0"), hi=Decimal("1"), unit="RATIO", sign="nonneg",
    ):
        hits.append((2, code))

    for field in _BUDGET_FIELDS:
        if field not in policy or policy.get(field) is None:
            hits.append((3, "POLICY_INCOMPLETE"))
        else:
            for code in _classify_number(
                policy.get(field), lo=Decimal("0"), hi=Decimal("100"), unit="RATIO", sign="nonneg",
            ):
                hits.append((2, code))
    for field in _SLA_FIELDS:
        if field not in policy or policy.get(field) is None:
            hits.append((3, "POLICY_INCOMPLETE"))
        else:
            for code in _classify_number(
                policy.get(field), lo=Decimal("0"), hi=Decimal("1000000000000"), unit="SEC", sign="nonneg",
            ):
                hits.append((2, code))
    sla_rule = policy.get("sla_rule_id")
    if not isinstance(sla_rule, str) or sla_rule == "":
        hits.append((3, "POLICY_INCOMPLETE"))
    if policy.get("parameter_status") != PARAMETER_STATUS:
        hits.append((3, "PARAMETER_STATUS"))

    if "policy_hash" in policy:
        try:
            computed = _content_hash(_policy_body(policy))
        except (NumericFault, TypeError):
            computed = None
        if computed is None or policy.get("policy_hash") != computed:
            hits.append((1, "INPUT_IDENTITY_CONFLICT"))

    if account.get("kill") == "ACTIVE":
        hits.append((5, "KILL_ACTIVE"))
    if account.get("incident") == "ACTIVE":
        hits.append((5, "INCIDENT_ACTIVE"))

    status = str(account.get("status") or "")
    if status.upper() == "STALE":
        hits.append((6, "ACCOUNT_STALE"))
    elif status.upper() in ("", "UNKNOWN", "UNAVAILABLE"):
        hits.append((6, "ACCOUNT_UNKNOWN"))
    fresh = str(market.get("freshness") or "").lower()
    if fresh == "stale":
        hits.append((6, "MARKET_STALE"))
    elif fresh != "ok":
        hits.append((6, "MARKET_UNKNOWN"))
    if "btc_nav" not in account or _blank(account.get("btc_nav")):
        hits.append((6, "BTC_NAV_UNKNOWN"))
    if "drawdown" not in account or _blank(account.get("drawdown")):
        hits.append((6, "DRAWDOWN_UNKNOWN"))
    if "btc_funding" not in market or _blank(market.get("btc_funding")):
        hits.append((6, "FUNDING_UNKNOWN"))
    if "spread" not in market or _blank(market.get("spread")):
        hits.append((6, "SPREAD_UNKNOWN"))

    evaluation = _parse_ts(evaluation_at)
    stamps = {
        "decision": _parse_ts(decision.get("as_of")),
        "account": _parse_ts(account.get("as_of")),
        "market": _parse_ts(market.get("as_of")),
    }
    if evaluation is not None:
        for moment in stamps.values():
            if moment is not None and moment > evaluation:
                hits.append((6, "FUTURE_TIMESTAMP"))
                break
        limits = {
            "decision": policy.get("sla_decision_sec"),
            "account": policy.get("sla_account_sec"),
            "market": policy.get("sla_market_sec"),
        }
        for name, moment in stamps.items():
            limit = limits[name]
            if moment is None or _blank(limit):
                continue
            try:
                seconds = _as_decimal(limit)
            except NumericFault:
                continue
            delta = Decimal(str((evaluation - moment).total_seconds()))
            if delta > seconds:
                hits.append((6, "SLA_EXCEEDED"))
                break
        skew_limit = policy.get("skew_limit_sec")
        moments = [item for item in stamps.values() if item is not None]
        if not _blank(skew_limit) and len(moments) == 3:
            try:
                limit_seconds = _as_decimal(skew_limit)
            except NumericFault:
                limit_seconds = None
            if limit_seconds is not None:
                gaps = []
                for left, right in ((0, 1), (0, 2), (1, 2)):
                    gaps.append(abs((moments[left] - moments[right]).total_seconds()))
                if Decimal(str(max(gaps))) > limit_seconds:
                    hits.append((6, "SKEW_EXCEEDED"))

    if _position_unknown(account):
        hits.append((7, "POSITION_UNKNOWN"))
    new_risk = _is_new_risk_action(decision)
    label = _existing_label(account)
    if new_risk and account.get("proposed_protection_state") != "ACTIVE_CONFIRMED":
        hits.append((8, "PROTECTION_UNMET"))
    if new_risk and not _position_unknown(account) and not _verifiable_flat(account) and label != "ACTIVE_CONFIRMED":
        hits.append((8, "EXISTING_POSITION_UNPROTECTED"))
    return hits


def _record(
    *,
    decision: Dict[str, Any],
    account: Dict[str, Any],
    market: Dict[str, Any],
    policy: Dict[str, Any],
    evaluation_at: str,
    state: str,
    hits: Sequence[Tuple[int, str]],
    plan: Optional[Dict[str, Any]],
    plan_key: str,
    defensive: bool,
) -> Dict[str, Any]:
    requested, allowed = _vectors(plan, decision)
    if state not in ("PASS", "REDUCED"):
        allowed = Decimal("0")
    blockers = sorted({code for _, code in hits})
    label = _existing_label(account)
    if state in ("PASS", "REDUCED", "DEFENSIVE_ONLY") or "PROTECTION_UNMET" in blockers:
        btc_plan = "ADJUDICATED"
    else:
        btc_plan = "BLOCKED"
    adjusted_target = _freeze(plan["risk_adjusted_target"]) if plan and "risk_adjusted_target" in plan else _freeze(decision.get("target_state") or {})
    adjusted_delta = _freeze(plan["risk_adjusted_delta"]) if plan and "risk_adjusted_delta" in plan else _freeze(decision.get("delta_proposal") or {})
    return {
        "account_authority": "NOT_ESTABLISHED",
        "based_on_decision_key": decision.get("decision_key"),
        "blockers": blockers,
        "canonical_version": CANONICAL_VERSION,
        "claimed_account_source": account.get("source"),
        "claimed_market_source": market.get("source"),
        "defensive_intent_preserved": bool(defensive),
        "defensive_quantity": "UNAVAILABLE",
        "evaluation_at": evaluation_at,
        "execution_eligibility": "DENIED",
        "existing_position_protection": label,
        "hash_alg": HASH_ALG,
        "identity_fence": {
            "btc_overlay_plan": btc_plan,
            "eth_overlay_execution": "DENIED",
            "event_increment_execution": "DENIED",
        },
        "input_versions": {
            "account": account.get("account_version"),
            "decision": decision.get("decision_key"),
            "policy": policy.get("policy_version"),
            "position": account.get("position_version"),
            "protection": account.get("protection_version"),
            "quote": market.get("quote_version"),
        },
        "new_risk": {"allowed": allowed, "requested": requested},
        "new_risk_allowed": state in ("PASS", "REDUCED"),
        "order_intent": "ABSENT",
        "reasons": list(blockers),
        "requested_cluster": {
            "btc": _freeze((decision.get("crypto_beta_cluster") or {}).get("btc_request") or 0),
            "eth": _freeze((decision.get("crypto_beta_cluster") or {}).get("eth_request") or 0),
            "total": _freeze((decision.get("crypto_beta_cluster") or {}).get("total_request") or 0),
        },
        "requested_delta": _freeze(decision.get("delta_proposal") or {}),
        "requested_event_increment": _event_request(decision),
        "requested_target": _freeze(decision.get("target_state") or {}),
        "risk_adjusted_delta": adjusted_delta,
        "risk_adjusted_target": adjusted_target,
        "risk_plan_key": plan_key,
        "risk_state": state,
        "runtime_kind": RUNTIME_KIND,
        "submit_allowed": False,
    }


def _pack(record: Dict[str, Any], *, present: bool, wrote: bool, idempotent: bool, canonical: Optional[str] = None) -> Dict[str, Any]:
    text = canonical if canonical is not None else canonical_dumps(record)
    return {
        "record": record,
        "receipt": {
            "record_present": present,
            "wrote_now": wrote,
            "idempotent": idempotent,
        },
        "record_canonical": text,
    }


def _bindings_for(
    decision: Dict[str, Any],
    account: Dict[str, Any],
    market: Dict[str, Any],
    policy: Dict[str, Any],
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    policy_body = _policy_body(policy)
    bodies = {
        "decision": canonical_dumps(decision),
        "account": canonical_dumps(account),
        "market": canonical_dumps(market),
        "policy": canonical_dumps(policy_body),
    }
    hashes = {name: _sha(body) for name, body in bodies.items()}
    specs_src = (
        ("decision", decision.get("source"), str(decision.get("decision_key")), bodies["decision"], hashes["decision"]),
        ("account", account.get("source"), str(account.get("account_version")), bodies["account"], hashes["account"]),
        ("market", market.get("source"), str(market.get("quote_version")), bodies["market"], hashes["market"]),
        ("policy", policy.get("source"), str(policy.get("policy_version")), bodies["policy"], hashes["policy"]),
    )
    specs = []
    for object_name, source, version, body, content in specs_src:
        specs.append({
            "key": _declaration_key(source, object_name, version),
            "object_name": object_name,
            "source_text": "" if source is None else str(source),
            "version_claim": version,
            "hash": content,
            "body": body,
        })
    return specs, hashes


def _read_outcome(conn: sqlite3.Connection, specs: Sequence[Dict[str, str]], plan_key: str) -> Any:
    conn.execute("BEGIN IMMEDIATE")
    try:
        for spec in specs:
            row = conn.execute(
                "SELECT content_hash FROM declaration_binding WHERE declaration_key = ?",
                (spec["key"],),
            ).fetchone()
            if row is not None and row[0] != spec["hash"]:
                conn.rollback()
                return "conflict"
        existing = conn.execute(
            "SELECT record_canonical FROM adjudication_record WHERE risk_plan_key = ?",
            (plan_key,),
        ).fetchone()
        conn.rollback()
        if existing is not None:
            return ("replay", existing[0])
        return "unwritable"
    except Exception:
        _rollback(conn)
        return "unwritable"


def _persist(
    conn: sqlite3.Connection,
    specs: Sequence[Dict[str, str]],
    plan_key: str,
    text: str,
    before_commit: Any,
) -> Any:
    conn.execute("BEGIN IMMEDIATE")
    try:
        pending = []
        for spec in specs:
            row = conn.execute(
                "SELECT content_hash FROM declaration_binding WHERE declaration_key = ?",
                (spec["key"],),
            ).fetchone()
            if row is None:
                pending.append(spec)
            elif row[0] != spec["hash"]:
                conn.rollback()
                return "conflict"
        existing = conn.execute(
            "SELECT record_canonical FROM adjudication_record WHERE risk_plan_key = ?",
            (plan_key,),
        ).fetchone()
        if existing is not None:
            conn.rollback()
            return ("replay", existing[0])
        for spec in pending:
            conn.execute(
                "INSERT INTO declaration_binding ("
                "declaration_key, object_name, source_text, version_claim, content_hash, canonical_body"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    spec["key"], spec["object_name"], spec["source_text"],
                    spec["version_claim"], spec["hash"], spec["body"],
                ),
            )
        conn.execute(
            "INSERT INTO adjudication_record (risk_plan_key, record_canonical) VALUES (?, ?)",
            (plan_key, text),
        )
        if before_commit is not None:
            before_commit(conn)
        conn.commit()
        return ("wrote", text)
    except sqlite3.IntegrityError:
        _rollback(conn)
        return _read_outcome(conn, specs, plan_key)
    except Exception:
        _rollback(conn)
        return "unwritable"


def _force_block(record: Dict[str, Any], code: str) -> Dict[str, Any]:
    blockers = sorted(set(list(record.get("blockers") or []) + [code]))
    record["blockers"] = blockers
    record["reasons"] = list(blockers)
    record["risk_state"] = "BLOCK_NEW_RISK"
    record["new_risk_allowed"] = False
    if isinstance(record.get("new_risk"), dict):
        record["new_risk"]["allowed"] = Decimal("0")
    fence = record.get("identity_fence") or {}
    if code != "PROTECTION_UNMET":
        fence["btc_overlay_plan"] = "BLOCKED"
        record["identity_fence"] = fence
    return record


def adjudicate_runtime(
    decision: Dict[str, Any],
    account: Dict[str, Any],
    market: Dict[str, Any],
    policy: Dict[str, Any],
    *,
    evaluation_at: str,
    log_path: str,
    risk_evaluator: Any = None,
    before_commit: Any = None,
    connection: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    if connection is not None and connection.in_transaction:
        raise CallerTransactionOpen(
            "caller connection has an open transaction; refusing before any write"
        )
    if decision.get("submit_allowed") not in (False,):
        decision = dict(decision)
        decision["submit_allowed"] = False

    evaluator = risk_evaluator or evaluate_risk
    defensive = _is_defensive_candidate(decision)
    new_risk = _is_new_risk_action(decision)
    hits = _local_hits(decision, account, market, policy, evaluation_at)
    plan = None
    writable_inputs = not any(row <= 4 or row == 0 for row, _ in hits)
    if writable_inputs:
        policy_for = _floatify(_policy_body(policy))
        decision_for = _floatify(decision)
        truth = _floatify(_truth(decision, account, market, evaluation_at))
        plan = evaluator(decision_for, truth, policy_for)
        violations = assert_risk_monotonicity(plan)
        if violations:
            hits = list(hits) + [(4, "RISK_MONOTONICITY_VIOLATION")]
            plan = None

    state, should_write = _decide(hits, defensive, new_risk, plan)
    plan_key = ""
    specs: List[Dict[str, str]] = []
    if not any(row <= 2 or row == 0 for row, _ in hits):
        try:
            specs, hashes = _bindings_for(decision, account, market, policy)
            sla_rule = policy.get("sla_rule_id")
            if isinstance(sla_rule, str) and sla_rule:
                plan_key = _risk_plan_key(hashes, evaluation_at, sla_rule)
        except (NumericFault, TypeError):
            should_write = False
            hits = list(hits) + [(2, "RANGE_VIOLATION")]
            state, should_write = _decide(hits, defensive, new_risk, plan)

    record = _record(
        decision=decision,
        account=account,
        market=market,
        policy=policy,
        evaluation_at=evaluation_at,
        state=state,
        hits=hits,
        plan=plan,
        plan_key=plan_key,
        defensive=defensive,
    )
    if not should_write or not plan_key:
        if not should_write and record["risk_state"] == "UNKNOWN":
            return _pack(record, present=False, wrote=False, idempotent=False)
        if record["risk_state"] == "PASS":
            record = _force_block(record, "LOG_UNWRITABLE")
        return _pack(record, present=False, wrote=False, idempotent=False)

    own = connection is None
    try:
        conn = connection or _connect(log_path)
    except (OSError, sqlite3.Error):
        record = _force_block(record, "LOG_UNWRITABLE")
        return _pack(record, present=False, wrote=False, idempotent=False)
    try:
        try:
            _ensure_schema(conn)
        except CallerTransactionOpen:
            raise
        except (OSError, sqlite3.Error):
            record = _force_block(record, "LOG_UNWRITABLE")
            return _pack(record, present=False, wrote=False, idempotent=False)
        text = canonical_dumps(record)
        outcome = _persist(conn, specs, plan_key, text, before_commit)
        if outcome == "conflict":
            record = _force_block(record, "INPUT_IDENTITY_CONFLICT")
            return _pack(record, present=True, wrote=False, idempotent=False)
        if outcome == "unwritable":
            record = _force_block(record, "LOG_UNWRITABLE")
            return _pack(record, present=False, wrote=False, idempotent=False)
        kind, stored = outcome
        if kind == "replay":
            parsed = json.loads(stored, parse_float=Decimal)
            return _pack(parsed, present=True, wrote=False, idempotent=True, canonical=stored)
        return _pack(record, present=True, wrote=True, idempotent=False, canonical=stored)
    finally:
        if own:
            conn.close()
