"""P4 offline account truth.

Pure function. Binding history is injected. Nothing here reads an account,
opens a ledger, or talks to an exchange.

BTC amounts convert to BTC by identity. Spot balances are gross of the
separately listed liabilities; liabilities are subtracted once at the end.
reality_authority and account_authority stay NOT_ESTABLISHED.
new_risk_usable stays false.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

CANONICAL_VERSION = "aurora-canonical-json-v1"
HASH_ALG = "sha256"
OBJECT_NAME = "account_snapshot"

_NON_FINITE_TEXT = {
    "nan": "nan",
    "inf": "inf",
    "+inf": "inf",
    "infinity": "inf",
    "+infinity": "inf",
    "-inf": "-inf",
    "-infinity": "-inf",
}
_NUMBER = re.compile(
    r"^[+-]?(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$"
)
_POLICY_INTS = (
    "max_input_scale",
    "max_result_scale",
    "max_significant_digits",
    "max_intermediate_digits",
    "max_balance_rows",
    "max_position_rows",
    "max_event_rows",
)


class _Stop(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Q(object):
    def __init__(self, coeff: int, exp: int) -> None:
        self.coeff = coeff
        self.exp = exp

    def is_zero(self) -> bool:
        return self.coeff == 0

    def is_negative(self) -> bool:
        return self.coeff < 0


def canonical_dumps(obj: Any) -> str:
    return _canon(obj)


def _canon(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _marker(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if value > 0:
        return "inf"
    return "-inf"


def _sanitize(value: Any, path: str, found: List[Dict[str, str]]) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        marker = _marker(value) if not math.isfinite(value) else "nan"
        found.append({"path": path, "marker": marker})
        return {"$aurora_non_finite": marker}
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _NON_FINITE_TEXT:
            found.append({"path": path, "marker": _NON_FINITE_TEXT[key]})
            return {"$aurora_non_finite": _NON_FINITE_TEXT[key]}
        return value
    if isinstance(value, list):
        return [_sanitize(item, "%s[%d]" % (path, i), found) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item, "%s.%s" % (path, key), found)
            for key, item in value.items()
        }
    return value


def _span(later: datetime, earlier: datetime) -> Fraction:
    delta = later - earlier
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return Fraction(micros, 1000000)


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    if value.endswith("Z"):
        raw = value[:-1] + "+00:00"
    elif len(value) >= 6 and (value[-6] in "+-") and value[-3] == ":":
        raw = value
    else:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _digit_len(coeff: int) -> int:
    return len(str(abs(coeff)))


def _policy_int(policy: Dict[str, Any], name: str) -> int:
    value = policy.get(name, None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Stop("POLICY_INCOMPLETE")
    return value


def _load_policy(policy: Any) -> Dict[str, Any]:
    if not isinstance(policy, dict):
        raise _Stop("POLICY_INCOMPLETE")
    version = policy.get("arithmetic_policy_version")
    if not isinstance(version, str) or not version:
        raise _Stop("POLICY_INCOMPLETE")
    loaded = {"arithmetic_policy_version": version}
    for name in _POLICY_INTS:
        loaded[name] = _policy_int(policy, name)
    if loaded["max_input_scale"] < 0 or loaded["max_result_scale"] < 0:
        raise _Stop("POLICY_INCOMPLETE")
    if loaded["max_significant_digits"] < 1 or loaded["max_intermediate_digits"] < 1:
        raise _Stop("POLICY_INCOMPLETE")
    if min(loaded["max_balance_rows"], loaded["max_position_rows"], loaded["max_event_rows"]) < 1:
        raise _Stop("POLICY_INCOMPLETE")
    for name in ("exponent_min", "exponent_max"):
        value = policy.get(name, None)
        if isinstance(value, bool) or not isinstance(value, int):
            raise _Stop("POLICY_INCOMPLETE")
        loaded[name] = value
    if loaded["exponent_min"] > loaded["exponent_max"]:
        raise _Stop("POLICY_INCOMPLETE")
    for name in ("sla_account_sec", "skew_limit_sec", "reconcile_tolerance_btc"):
        if name not in policy:
            raise _Stop("POLICY_INCOMPLETE")
        loaded[name] = policy[name]
    if any(loaded[name] > 4096 or loaded[name] < 0 for name in (
        "max_input_scale", "max_result_scale", "max_significant_digits", "max_intermediate_digits",
    )):
        raise _Stop("NUMERIC_LIMIT")
    if loaded["exponent_min"] < -4096 or loaded["exponent_max"] > 4096:
        raise _Stop("NUMERIC_LIMIT")
    return loaded


def _parse_q(value: Any, policy: Dict[str, Any]) -> Q:
    if isinstance(value, bool) or isinstance(value, float):
        raise _Stop("NON_FINITE")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise _Stop("PRECISION_INSUFFICIENT")
    if len(text) > 4096 or len(text) > policy["max_significant_digits"] + 8:
        raise _Stop("NUMERIC_LIMIT")
    if text.lower() in _NON_FINITE_TEXT:
        raise _Stop("NON_FINITE")
    match = _NUMBER.match(text)
    if match is None:
        raise _Stop("PRECISION_INSUFFICIENT")
    whole, frac_a, frac_b, exp_token = match.groups()
    frac = frac_a if frac_a is not None else (frac_b or "")
    digits = (whole or "") + frac
    if digits == "":
        raise _Stop("PRECISION_INSUFFICIENT")
    if len(digits) > policy["max_significant_digits"] or len(digits) > 4096:
        raise _Stop("NUMERIC_LIMIT")
    exp = 0
    if exp_token is not None:
        if len(exp_token.lstrip("+-")) > 6:
            raise _Stop("NUMERIC_LIMIT")
        exp = int(exp_token)
    exp -= len(frac)
    significant = digits.lstrip("0") or "0"
    if len(significant) > policy["max_significant_digits"] or len(significant) > 4096:
        raise _Stop("NUMERIC_LIMIT")
    if exp > policy["exponent_max"] or exp < policy["exponent_min"] or abs(exp) > 4096:
        raise _Stop("NUMERIC_LIMIT")
    scale = max(0, -exp) if exp_token is None else max(0, len(frac) - (int(exp_token) if exp_token else 0))
    if exp_token is None:
        scale = len(frac)
    if scale > policy["max_input_scale"]:
        raise _Stop("PRECISION_INSUFFICIENT")
    try:
        coeff = int(significant)
    except ValueError:
        raise _Stop("NUMERIC_LIMIT")
    if text[0] == "-":
        coeff = -coeff
    if significant == "0":
        coeff = 0
    return Q(coeff, exp)


def _add(left: Q, right: Q, policy: Dict[str, Any]) -> Q:
    exp = min(left.exp, right.exp)
    shift_left = left.exp - exp
    shift_right = right.exp - exp
    if shift_left > policy["max_intermediate_digits"] or shift_right > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    coeff = left.coeff * (10 ** shift_left) + right.coeff * (10 ** shift_right)
    if _digit_len(coeff) > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    return Q(coeff, exp)


def _mul(left: Q, right: Q, policy: Dict[str, Any]) -> Q:
    if _digit_len(left.coeff) + _digit_len(right.coeff) > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    exp = left.exp + right.exp
    if exp > policy["exponent_max"] or exp < policy["exponent_min"]:
        raise _Stop("NUMERIC_LIMIT")
    coeff = left.coeff * right.coeff
    if _digit_len(coeff) > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    return Q(coeff, exp)


def _fraction(number: Q, policy: Dict[str, Any]) -> Fraction:
    if number.exp >= 0:
        if number.exp > policy["max_intermediate_digits"]:
            raise _Stop("NUMERIC_LIMIT")
        return Fraction(number.coeff * (10 ** number.exp), 1)
    if -number.exp > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    return Fraction(number.coeff, 10 ** (-number.exp))


def _format_fraction(number: Fraction, policy: Dict[str, Any]) -> str:
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    denominator = number.denominator
    twos = 0
    fives = 0
    rest = denominator
    while rest % 2 == 0:
        rest //= 2
        twos += 1
    while rest % 5 == 0:
        rest //= 5
        fives += 1
    if rest != 1:
        raise _Stop("PRECISION_INSUFFICIENT")
    scale = max(twos, fives)
    if scale > policy["max_result_scale"]:
        raise _Stop("PRECISION_INSUFFICIENT")
    numerator = number.numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    if _digit_len(numerator) > policy["max_intermediate_digits"]:
        raise _Stop("NUMERIC_LIMIT")
    text = str(numerator)
    if scale:
        text = text.zfill(scale + 1)
        body = text[:-scale] + "." + text[-scale:]
        body = body.rstrip("0").rstrip(".")
    else:
        body = text
    if body in ("", "-"):
        body = "0"
    return sign + body


def _q_text(number: Q, policy: Dict[str, Any]) -> str:
    return _format_fraction(_fraction(number, policy), policy)


def _expect_filter(scope: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    return {
        "environment": scope.get("environment"),
        "account_ref": scope.get("account_ref"),
        "sub_account_ref": scope.get("sub_account_ref"),
        "event_type": event_type,
        "symbols": [],
    }


def _same_filter(left: Any, right: Any) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


def _event_conflicts(events: List[Any], scope: Dict[str, Any]) -> bool:
    seen: Dict[Tuple[Any, ...], str] = {}
    for event in events:
        if not isinstance(event, dict):
            return True
        identity = (
            scope.get("environment"),
            scope.get("account_ref"),
            scope.get("sub_account_ref"),
            event.get("event_type"),
            event.get("stable_id"),
        )
        body = canonical_dumps(event)
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = body
        elif previous != body:
            return True
    return False


def _evidence_covers(manifest: Dict[str, Any]) -> bool:
    evidence = manifest.get("completeness_evidence")
    if not isinstance(evidence, dict) or evidence.get("re_queried_full") is not True:
        return False
    if evidence.get("window_from") != manifest.get("window_from"):
        return False
    if evidence.get("window_to") != manifest.get("window_to"):
        return False
    if not _same_filter(evidence.get("query_filter"), manifest.get("query_filter")):
        return False
    if not _pages_settled(evidence.get("pages_fetched"), evidence.get("pages_declared")):
        return False
    if evidence.get("page_end_token") is not None or evidence.get("truncated") is not False:
        return False
    start = _parse_time(manifest.get("window_from"))
    retained = _parse_time(evidence.get("retained_from"))
    if start is None or retained is None or retained > start:
        return False
    return True


def _pages_settled(fetched: Any, declared: Any) -> bool:
    if isinstance(fetched, bool) or isinstance(declared, bool):
        return False
    if not isinstance(fetched, int) or not isinstance(declared, int):
        return False
    if fetched < 1 or declared < 1:
        return False
    return fetched == declared


def _event_problem(
    event: Any,
    event_type: str,
    start: Optional[datetime],
    end: Optional[datetime],
    evaluation: Optional[datetime],
    policy: Optional[Dict[str, Any]],
    scope: Dict[str, Any],
) -> Optional[str]:
    if not isinstance(event, dict):
        return "INVALID"
    if event.get("event_type") != event_type:
        return "INVALID"
    for field in ("environment", "account_ref", "sub_account_ref"):
        if field in event and event.get(field) != scope.get(field):
            return "INVALID"
    stable_id = event.get("stable_id")
    asset = event.get("asset")
    if not isinstance(stable_id, str) or not stable_id.strip():
        return "INVALID"
    if not isinstance(asset, str) or not asset.strip():
        return "INVALID"
    if policy is None:
        return "INVALID"
    try:
        _parse_q(event.get("amount"), policy)
    except _Stop as exc:
        return exc.code
    moment = _parse_time(event.get("event_time"))
    if moment is None:
        return "TIMESTAMP_INVALID"
    if evaluation is not None and moment > evaluation:
        return "FUTURE_TIMESTAMP"
    if start is None or end is None or not (start <= moment < end):
        return "INVALID"
    return None


def _window(
    manifest: Any,
    scope: Dict[str, Any],
    event_type: str,
    evaluation: Optional[datetime],
    policy: Optional[Dict[str, Any]],
    blockers: List[str],
) -> Dict[str, Any]:
    if manifest is None or not isinstance(manifest, dict):
        return {"status": "UNKNOWN", "total": None, "events": [], "lineage": None}
    if "events" not in manifest or not isinstance(manifest.get("events"), list):
        return {
            "status": "INCOMPLETE",
            "total": None,
            "events": [],
            "lineage": copy.deepcopy(manifest.get("lineage")),
        }
    events = manifest.get("events")
    max_rows = None if policy is None else policy.get("max_event_rows")
    if isinstance(max_rows, int) and len(events) > max_rows:
        blockers.append("RESOURCE_LIMIT")
        return {
            "status": "INCOMPLETE",
            "total": None,
            "events": [],
            "lineage": copy.deepcopy(manifest.get("lineage")),
        }
    view = {
        "status": "INCOMPLETE",
        "total": None,
        "events": copy.deepcopy(events),
        "lineage": copy.deepcopy(manifest.get("lineage")),
    }
    if manifest.get("late_known") is True and not _evidence_covers(manifest):
        view["status"] = "PARTIAL_LATE"
        return view
    expected = _expect_filter(scope, event_type)
    complete_shape = (
        _same_filter(manifest.get("query_filter"), expected)
        and _pages_settled(manifest.get("pages_fetched"), manifest.get("pages_declared"))
        and manifest.get("page_end_token") is None
        and manifest.get("truncated") is False
    )
    start = _parse_time(manifest.get("window_from"))
    end = _parse_time(manifest.get("window_to"))
    retained = _parse_time(manifest.get("retained_from"))
    covers = start is not None and retained is not None and retained <= start
    if not complete_shape or not covers:
        view["status"] = "INCOMPLETE"
        return view
    if start is None or end is None:
        blockers.append("TIMESTAMP_INVALID")
        view["status"] = "INCOMPLETE"
        return view
    if start >= end:
        view["status"] = "INCOMPLETE"
        return view
    if evaluation is not None and end > evaluation:
        blockers.append("FUTURE_TIMESTAMP")
        view["status"] = "INCOMPLETE"
        return view
    if _event_conflicts(events, scope):
        view["status"] = "INCOMPLETE"
        return view
    if len(events) == 0:
        proof = manifest.get("zero_event_proof")
        if (
            isinstance(proof, dict)
            and _same_filter(proof.get("query_filter"), manifest.get("query_filter"))
            and proof.get("page_end_token") == manifest.get("page_end_token")
        ):
            view["status"] = "COMPLETE"
            view["total"] = "0"
            return view
        view["status"] = "UNKNOWN"
        view["total"] = None
        return view
    invalid = False
    seen: Dict[Tuple[Any, ...], str] = {}
    amounts: List[Q] = []
    asset = None
    for event in events:
        problem = _event_problem(event, event_type, start, end, evaluation, policy, scope)
        if problem == "INVALID":
            invalid = True
            continue
        if problem:
            blockers.append(problem)
            invalid = True
            continue
        identity = (
            scope.get("environment"),
            scope.get("account_ref"),
            scope.get("sub_account_ref"),
            event.get("event_type"),
            event.get("stable_id"),
        )
        body = canonical_dumps(event)
        if identity in seen:
            continue
        seen[identity] = body
        if asset is None:
            asset = event.get("asset")
        elif event.get("asset") != asset:
            invalid = True
            continue
        amounts.append(_parse_q(event.get("amount"), policy))
    if invalid or policy is None:
        view["status"] = "INCOMPLETE"
        return view
    try:
        total = Q(0, 0)
        for amount in amounts:
            total = _add(total, amount, policy)
        view["total"] = _q_text(total, policy)
    except _Stop as exc:
        blockers.append(exc.code)
        view["status"] = "INCOMPLETE"
        view["total"] = None
        return view
    view["status"] = "COMPLETE"
    return view


def _ids_assets(rows: List[Dict[str, Any]]) -> List[str]:
    return ["%s|%s|%s" % (row["product"], row["wallet"], row["asset"]) for row in rows]


def _ids_positions(rows: List[Dict[str, Any]]) -> List[str]:
    return ["%s|%s|%s" % (row["product"], row["symbol"], row["side"]) for row in rows]


def _pair_key(pair: Dict[str, Any]) -> Tuple[str, str]:
    return (str(pair.get("base_asset")), str(pair.get("quote_asset")))


def _index_quotes(quotes: Any, policy: Dict[str, Any], blockers: List[str]) -> Dict[Tuple[str, str], Q]:
    found: Dict[Tuple[str, str], Q] = {}
    pairs = []
    if isinstance(quotes, dict):
        pairs = quotes.get("pairs") or []
    if not isinstance(pairs, list):
        blockers.append("QUOTE_UNPINNED")
        return found
    for pair in pairs:
        if not isinstance(pair, dict):
            blockers.append("QUOTE_INVALID")
            continue
        price = pair.get("price", None)
        if price is None:
            continue
        try:
            number = _parse_q(price, policy)
        except _Stop as exc:
            blockers.append(exc.code)
            continue
        if number.is_negative() or number.is_zero():
            blockers.append("QUOTE_INVALID")
            continue
        key = _pair_key(pair)
        previous = found.get(key)
        if previous is not None and _fraction(previous, policy) != _fraction(number, policy):
            blockers.append("QUOTE_INCONSISTENT")
            continue
        found[key] = number
    return found


def _convert(
    amount: Q,
    asset: str,
    quotes: Dict[Tuple[str, str], Q],
    policy: Dict[str, Any],
    pinned: bool,
) -> Fraction:
    if asset == "BTC" or amount.is_zero():
        return _fraction(amount, policy)
    if not pinned:
        raise _Stop("QUOTE_UNPINNED")
    forward = quotes.get((asset, "BTC"))
    backward = quotes.get(("BTC", asset))
    if forward is not None and backward is not None:
        product = _mul(forward, backward, policy)
        if _fraction(product, policy) != 1:
            raise _Stop("QUOTE_INCONSISTENT")
    if forward is not None:
        return _fraction(_mul(amount, forward, policy), policy)
    if backward is not None:
        if _digit_len(amount.coeff) + _digit_len(backward.coeff) > policy["max_intermediate_digits"]:
            raise _Stop("NUMERIC_LIMIT")
        quotient = _fraction(amount, policy) / _fraction(backward, policy)
        _format_fraction(quotient, policy)
        return quotient
    raise _Stop("QUOTE_UNPINNED")


def _needs_external_quote(
    parsed_balances: List[Tuple[Dict[str, Any], Q]],
    liability_rows: List[Tuple[str, Q]],
    position_rows: List[Dict[str, Any]],
    venue: Any,
    ledger: Any,
    policy: Dict[str, Any],
) -> bool:
    for row, total in parsed_balances:
        if str(row.get("asset")) != "BTC" and not total.is_zero():
            return True
    for asset, amount in liability_rows:
        if str(asset) != "BTC" and not amount.is_zero():
            return True
    for row in position_rows:
        if not isinstance(row, dict) or str(row.get("settlement_asset")) == "BTC":
            continue
        try:
            pnl = _pnl(row, policy)
        except _Stop:
            continue
        if not pnl.is_zero():
            return True
    candidates: List[Any] = []
    if isinstance(venue, dict):
        candidates.append(venue)
    if isinstance(ledger, dict):
        anchors = ledger.get("opening_anchor") or []
        if isinstance(anchors, dict):
            candidates.append(anchors)
        elif isinstance(anchors, list):
            candidates.extend(anchors)
    for row in candidates:
        if not isinstance(row, dict) or str(row.get("asset")) == "BTC":
            continue
        try:
            amount = _parse_q(row.get("amount"), policy)
        except _Stop:
            continue
        if not amount.is_zero():
            return True
    return False


def _balance_total(row: Dict[str, Any], policy: Dict[str, Any], blockers: List[str]) -> Optional[Q]:
    if row.get("unpinned_price") is not None:
        blockers.append("NAV_PARTIAL_REJECTED")
    if row.get("mix_into"):
        blockers.append("DOUBLE_COUNT")
    if row.get("count_free_and_total") is True:
        blockers.append("DOUBLE_COUNT")
    has_free = "free" in row
    has_locked = "locked" in row
    has_total = "total" in row
    try:
        free = _parse_q(row["free"], policy) if has_free else None
        locked = _parse_q(row["locked"], policy) if has_locked else None
        total = _parse_q(row["total"], policy) if has_total else None
    except _Stop as exc:
        blockers.append(exc.code)
        return None
    if free is not None and free.is_negative():
        blockers.append("SIGN_MISMATCH")
    if locked is not None and locked.is_negative():
        blockers.append("SIGN_MISMATCH")
    if total is not None and total.is_negative():
        blockers.append("SIGN_MISMATCH")
    if has_free and has_locked and has_total and free is not None and locked is not None and total is not None:
        added = _add(free, locked, policy)
        if _fraction(added, policy) != _fraction(total, policy):
            blockers.append("BALANCE_INCOMPLETE")
        return total
    if has_free and has_locked and free is not None and locked is not None and not has_total:
        return _add(free, locked, policy)
    if has_total and not has_free and not has_locked:
        return total
    if has_total and total is not None and not (has_free and has_locked):
        blockers.append("BALANCE_INCOMPLETE")
        return None
    blockers.append("BALANCE_INCOMPLETE")
    return None


def _pnl(position: Dict[str, Any], policy: Dict[str, Any]) -> Q:
    if position.get("include_notional") is True:
        raise _Stop("NOTIONAL_REJECTED")
    if "wallet_balance_settle" in position:
        raise _Stop("DOUBLE_COUNT")
    if position.get("contract_kind") != "LINEAR_PERPETUAL":
        raise _Stop("UNSUPPORTED_CONTRACT")
    multiplier = _parse_q(position.get("contract_multiplier"), policy)
    if _fraction(multiplier, policy) != 1:
        raise _Stop("UNSUPPORTED_CONTRACT")
    qty = _parse_q(position.get("qty"), policy)
    if qty.is_negative():
        raise _Stop("SIGN_MISMATCH")
    entry = _parse_q(position.get("entry_price"), policy)
    mark = _parse_q(position.get("mark_price"), policy)
    if entry.is_negative() or entry.is_zero() or mark.is_negative() or mark.is_zero():
        raise _Stop("PRECISION_INSUFFICIENT")
    side = position.get("side")
    if side == "LONG":
        direction = Q(1, 0)
    elif side == "SHORT":
        direction = Q(-1, 0)
    else:
        raise _Stop("POSITION_MODE_UNKNOWN")
    diff = _add(mark, Q(-entry.coeff, entry.exp), policy)
    return _mul(_mul(_mul(direction, qty, policy), multiplier, policy), diff, policy)


def _product_rows(scope: Dict[str, Any], blockers: List[str]) -> List[str]:
    products = scope.get("products")
    if not isinstance(products, list) or not products:
        blockers.append("UNSUPPORTED_PRODUCT")
        return []
    names = []
    for product in products:
        if not isinstance(product, dict):
            blockers.append("UNSUPPORTED_PRODUCT")
            continue
        name = product.get("product")
        names.append(name)
        if name not in ("SPOT", "USDS_M"):
            blockers.append("UNSUPPORTED_PRODUCT")
            continue
        position_mode = product.get("position_mode", None)
        margin_mode = product.get("margin_mode", None)
        if name == "SPOT":
            if position_mode != "NOT_APPLICABLE" or margin_mode != "NOT_APPLICABLE":
                blockers.append("POSITION_MODE_UNKNOWN")
        else:
            if position_mode not in ("ONE_WAY", "HEDGE") or margin_mode not in ("CROSS", "ISOLATED"):
                blockers.append("POSITION_MODE_UNKNOWN")
    return [name for name in names if isinstance(name, str)]


def _hedge(scope: Dict[str, Any], positions: List[Dict[str, Any]], blockers: List[str]) -> None:
    modes = {}
    for product in scope.get("products") or []:
        if isinstance(product, dict):
            modes[product.get("product")] = product.get("position_mode")
    grouped: Dict[Tuple[str, str], set] = {}
    for position in positions:
        if not isinstance(position, dict):
            continue
        try:
            qty = _parse_q(position.get("qty"), {"max_input_scale": 18, "max_significant_digits": 18,
                                                  "max_intermediate_digits": 36, "exponent_min": -18,
                                                  "exponent_max": 18, "max_result_scale": 18})
        except _Stop:
            continue
        if qty.is_zero():
            continue
        key = (str(position.get("product")), str(position.get("symbol")))
        grouped.setdefault(key, set()).add(position.get("side"))
    for (product, _symbol), sides in grouped.items():
        if "LONG" in sides and "SHORT" in sides and modes.get(product) != "HEDGE":
            blockers.append("POSITION_MODE_UNKNOWN")


def _transfers(scope: Dict[str, Any], policy: Dict[str, Any], blockers: List[str]) -> None:
    rows = scope.get("transfers") or []
    if not isinstance(rows, list):
        blockers.append("TRANSFER_SCOPE_UNBALANCED")
        return
    nets: Dict[str, Q] = {}
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("TRANSFER_SCOPE_UNBALANCED")
            continue
        try:
            amount = _parse_q(row.get("amount"), policy)
        except _Stop as exc:
            blockers.append(exc.code)
            continue
        if amount.is_negative() or amount.is_zero():
            blockers.append("TRANSFER_SCOPE_UNBALANCED")
            continue
        asset = str(row.get("asset"))
        direction = row.get("direction")
        signed = amount if direction == "IN" else Q(-amount.coeff, amount.exp) if direction == "OUT" else None
        if signed is None:
            blockers.append("TRANSFER_SCOPE_UNBALANCED")
            continue
        nets[asset] = signed if asset not in nets else _add(nets[asset], signed, policy)
    for value in nets.values():
        if not value.is_zero():
            blockers.append("TRANSFER_SCOPE_UNBALANCED")


def _set_proof(scope: Dict[str, Any], assets: List[str], positions: List[str], blockers: List[str]) -> Any:
    proof = scope.get("set_completeness")
    if not isinstance(proof, dict) or proof.get("proof_kind") != "EXPLICIT_SET_EQUAL":
        blockers.append("SET_INCOMPLETE")
        return proof
    required_assets = proof.get("required_assets")
    observed_assets = proof.get("observed_assets")
    required_positions = proof.get("required_positions")
    observed_positions = proof.get("observed_positions")
    if not all(isinstance(item, list) for item in (
        required_assets, observed_assets, required_positions, observed_positions
    )):
        blockers.append("SET_INCOMPLETE")
        return proof
    if set(required_assets) != set(observed_assets) or set(required_positions) != set(observed_positions):
        blockers.append("SET_INCOMPLETE")
    if set(observed_assets) != set(assets) or set(observed_positions) != set(positions):
        blockers.append("SET_INCOMPLETE")
        if set(assets) != set(observed_assets):
            blockers.append("BALANCE_INCOMPLETE")
    if len(required_assets) != len(set(required_assets)) or len(required_positions) != len(set(required_positions)):
        blockers.append("DUPLICATE_ROW")
    return proof


def _apply_events(manifest: Any, blockers: List[str], code: str) -> None:
    if not isinstance(manifest, dict):
        return
    for event in manifest.get("events") or []:
        if isinstance(event, dict) and event.get("apply_to_nav") is True:
            blockers.append("DOUBLE_COUNT")
            blockers.append(code)


def _proposal(binding_state: Any, content: Dict[str, Any], source: str, version: str) -> Dict[str, Any]:
    if not isinstance(binding_state, dict) or "bindings" not in binding_state:
        return {
            "action": "REFUSED",
            "declaration_key": None,
            "content_hash": None,
            "proposed_binding": None,
            "existing_bindings": [],
            "prior_content_hash": None,
        }
    key = _sha(canonical_dumps({
        "object": OBJECT_NAME,
        "source_claim": source,
        "version_claim": version,
    }))
    body = canonical_dumps(content)
    digest = _sha(body)
    existing = copy.deepcopy(list(binding_state.get("bindings") or []))
    found = None
    for item in existing:
        if isinstance(item, dict) and item.get("declaration_key") == key:
            found = item
            break
    if found is None:
        proposed = {
            "declaration_key": key,
            "content_hash": digest,
            "canonical_body": body,
            "version_claim": version,
            "object": OBJECT_NAME,
        }
        return {
            "action": "APPEND",
            "declaration_key": key,
            "content_hash": digest,
            "proposed_binding": proposed,
            "existing_bindings": existing,
            "prior_content_hash": None,
        }
    if found.get("content_hash") == digest:
        return {
            "action": "REPLAY",
            "declaration_key": key,
            "content_hash": digest,
            "proposed_binding": None,
            "existing_bindings": existing,
            "prior_content_hash": digest,
        }
    return {
        "action": "CONFLICT",
        "declaration_key": key,
        "content_hash": digest,
        "proposed_binding": None,
        "existing_bindings": existing,
        "prior_content_hash": found.get("content_hash"),
    }


def _text_ok(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _lineage_ready(face: Any) -> bool:
    return (
        isinstance(face, dict)
        and _text_ok(face.get("receipt_ref"))
        and _text_ok(face.get("raw_response_hash"))
    )


def _anchors_ready(ledger: Any) -> bool:
    if not isinstance(ledger, dict):
        return False
    anchors = ledger.get("opening_anchor")
    if isinstance(anchors, dict):
        anchors = [anchors]
    if not isinstance(anchors, list) or not anchors:
        return False
    for anchor in anchors:
        if not isinstance(anchor, dict):
            return False
        if not _text_ok(anchor.get("anchor_version")) or _parse_time(anchor.get("as_of")) is None:
            return False
    return True


def _face_scope(face: Dict[str, Any], scope: Dict[str, Any], names: List[str]) -> bool:
    return (
        face.get("environment") == scope.get("environment")
        and face.get("account_ref") == scope.get("account_ref")
        and face.get("sub_account_ref") == scope.get("sub_account_ref")
        and set(face.get("products") or []) == set(names)
        and face.get("as_of") == scope.get("as_of")
    )


def _sum_fractions(parts: List[Fraction], policy: Dict[str, Any]) -> Fraction:
    total = Fraction(0)
    for part in parts:
        if (
            _digit_len(part.numerator) > policy["max_intermediate_digits"]
            or _digit_len(part.denominator) > policy["max_intermediate_digits"]
        ):
            raise _Stop("NUMERIC_LIMIT")
        total += part
        if (
            _digit_len(total.numerator) > policy["max_intermediate_digits"]
            or _digit_len(total.denominator) > policy["max_intermediate_digits"]
        ):
            raise _Stop("NUMERIC_LIMIT")
        _format_fraction(total, policy)
    return total


def _rows_text(amounts: Dict[str, Q], policy: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {"asset": asset, "amount": _q_text(amounts[asset], policy)}
        for asset in sorted(amounts)
    ]


def _evaluate_account_truth(
    scope: Any,
    balances: Any,
    liabilities: Any,
    positions: Any,
    fee_manifest: Any,
    funding_manifest: Any,
    quotes: Any,
    venue_reported_equity: Any,
    ledger_reconstruction: Any,
    binding_state: Any,
    collection_proofs: Any,
    policy: Any,
    evaluation_at: Any,
) -> Dict[str, Any]:
    blockers: List[str] = []
    non_finite: List[Dict[str, str]] = []
    loaded = None
    try:
        loaded = _load_policy(policy)
    except _Stop as exc:
        blockers.append(exc.code)

    def _cap_list(value: Any, limit: Any) -> Any:
        if loaded is None or not isinstance(value, list) or not isinstance(limit, int):
            return value
        if len(value) > limit:
            blockers.append("RESOURCE_LIMIT")
            return None
        return value

    def _cap_key(mapping: Any, key: str, limit: Any) -> Any:
        if loaded is None or not isinstance(mapping, dict) or not isinstance(limit, int):
            return mapping
        rows = mapping.get(key)
        if isinstance(rows, list) and len(rows) > limit:
            blockers.append("RESOURCE_LIMIT")
            trimmed = dict(mapping)
            trimmed[key] = None
            return trimmed
        return mapping

    balance_limit = None if loaded is None else loaded["max_balance_rows"]
    position_limit = None if loaded is None else loaded["max_position_rows"]
    event_limit = None if loaded is None else loaded["max_event_rows"]
    scope_s = _sanitize(scope, "scope", non_finite)
    balances_s = _sanitize(_cap_list(balances, balance_limit), "balances", non_finite)
    liabilities_s = _sanitize(_cap_list(liabilities, balance_limit), "liabilities", non_finite)
    positions_s = _sanitize(_cap_list(positions, position_limit), "positions", non_finite)
    quotes_s = _sanitize(quotes, "quotes", non_finite)
    venue_s = _sanitize(venue_reported_equity, "venue_reported_equity", non_finite)
    ledger_s = _sanitize(_cap_key(ledger_reconstruction, "movements", event_limit), "ledger_reconstruction", non_finite)
    fee_s = _sanitize(_cap_key(fee_manifest, "events", event_limit), "fee_manifest", non_finite)
    funding_s = _sanitize(_cap_key(funding_manifest, "events", event_limit), "funding_manifest", non_finite)
    if non_finite:
        blockers.append("NON_FINITE")
    if not isinstance(scope_s, dict):
        scope_s = {}
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
    source = scope_s.get("source_claim")
    version_raw = scope_s.get("version_claim")
    if not isinstance(version_raw, str) or not version_raw.strip():
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
        version = ""
    else:
        version = version_raw
    if not isinstance(scope_s.get("scope_version"), str) or not scope_s.get("scope_version").strip():
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
    content = {
        "policy": policy if isinstance(policy, dict) else None,
        "balances": balances_s,
        "collection_proofs": collection_proofs,
        "fee_manifest": fee_s,
        "funding_manifest": funding_s,
        "ledger_reconstruction": ledger_s,
        "liabilities": liabilities_s,
        "positions": positions_s,
        "quotes": quotes_s,
        "scope": scope_s,
        "venue_reported_equity": venue_s,
    }
    proposal = _proposal(binding_state, content, source if isinstance(source, str) else "", version)
    if proposal["action"] == "REFUSED":
        blockers.append("BINDING_STATE_ABSENT")
    if proposal["action"] == "CONFLICT":
        blockers.append("INPUT_IDENTITY_CONFLICT")

    if loaded is not None:
        for name in ("sla_account_sec", "skew_limit_sec"):
            if loaded[name] is None:
                blockers.append("POLICY_INCOMPLETE")
        tolerance = loaded["reconcile_tolerance_btc"]
        if tolerance is None:
            blockers.append("TOLERANCE_INVALID")
        else:
            try:
                parsed_tolerance = _parse_q(tolerance, loaded)
                if parsed_tolerance.is_negative():
                    blockers.append("TOLERANCE_INVALID")
            except _Stop as exc:
                blockers.append(exc.code if exc.code != "PRECISION_INSUFFICIENT" else "TOLERANCE_INVALID")

    account_ref = scope_s.get("account_ref")
    if not isinstance(account_ref, str) or not account_ref.strip():
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
    if scope_s.get("environment") not in ("MAINNET", "TESTNET", "FIXTURE"):
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
    if not isinstance(scope_s.get("sub_account_ref"), str) or not scope_s.get("sub_account_ref"):
        blockers.append("ACCOUNT_IDENTITY_UNFIXED")
    evaluated = _parse_time(evaluation_at)
    as_of = _parse_time(scope_s.get("as_of"))
    if evaluated is None or as_of is None:
        blockers.append("TIMESTAMP_INVALID")
    elif as_of > evaluated:
        blockers.append("FUTURE_TIMESTAMP")
    if loaded is not None and evaluated is not None and as_of is not None and as_of <= evaluated:
        try:
            sla = _parse_q(loaded["sla_account_sec"], loaded)
            limit = _fraction(sla, loaded)
            if _span(evaluated, as_of) > limit:
                blockers.append("SLA_EXCEEDED")
        except _Stop as exc:
            blockers.append(exc.code)

    names = _product_rows(scope_s, blockers)
    if scope_s.get("includes_settled_flows") is not True:
        blockers.append("WALLET_FLOW_BASIS_UNKNOWN")

    position_state = "UNKNOWN"
    position_rows: List[Dict[str, Any]] = []
    if positions_s is None:
        blockers.append("POSITION_UNKNOWN")
        position_state = "UNKNOWN"
    elif isinstance(positions_s, list):
        position_rows = [row for row in positions_s if isinstance(row, dict)]
        if len(position_rows) != len(positions_s):
            blockers.append("POSITION_MALFORMED")
            position_state = "MALFORMED"
        elif loaded is not None and len(position_rows) > loaded["max_position_rows"]:
            blockers.append("RESOURCE_LIMIT")
        else:
            position_state = "FLAT"
    else:
        blockers.append("POSITION_MALFORMED")
        position_state = "MALFORMED"

    balance_rows: List[Dict[str, Any]] = []
    parsed_balances: List[Tuple[Dict[str, Any], Q]] = []
    if not isinstance(balances_s, list):
        blockers.append("BALANCE_INCOMPLETE")
    elif loaded is not None:
        if len(balances_s) > loaded["max_balance_rows"]:
            blockers.append("RESOURCE_LIMIT")
        seen = set()
        for row in balances_s:
            if not isinstance(row, dict) or row.get("status") != "KNOWN":
                blockers.append("BALANCE_INCOMPLETE")
                continue
            identity = (row.get("product"), row.get("wallet"), row.get("asset"))
            if identity in seen:
                blockers.append("DUPLICATE_ROW")
            seen.add(identity)
            product = row.get("product")
            if product not in ("SPOT", "USDS_M") or product not in set(names):
                blockers.append("UNSUPPORTED_PRODUCT")
            if loaded is None:
                continue
            try:
                total = _balance_total(row, loaded, blockers)
            except _Stop as exc:
                blockers.append(exc.code)
                total = None
            echoed = {
                "product": row.get("product"),
                "wallet": row.get("wallet"),
                "asset": row.get("asset"),
                "status": "KNOWN",
            }
            if total is not None:
                try:
                    echoed["total"] = _q_text(total, loaded)
                except _Stop as exc:
                    blockers.append(exc.code)
                    total = None
            if total is not None:
                parsed_balances.append((row, total))
            elif "total" in row and not isinstance(row.get("total"), dict):
                echoed["total"] = row.get("total")
            balance_rows.append(echoed)

    if loaded is not None and position_state == "FLAT":
        declared = set(names)
        open_qty = False
        for row in position_rows:
            product = row.get("product")
            if product not in ("SPOT", "USDS_M") or product not in declared:
                blockers.append("UNSUPPORTED_PRODUCT")
            try:
                qty = _parse_q(row.get("qty"), loaded)
                _pnl(row, loaded)
            except _Stop as exc:
                blockers.append(exc.code)
                position_state = "MALFORMED"
                break
            if not qty.is_zero():
                open_qty = True
        if position_state != "MALFORMED":
            position_state = "KNOWN" if open_qty else "FLAT"
            _hedge(scope_s, position_rows, blockers)

    liability_rows: List[Tuple[str, Q]] = []
    echoed_liabilities: List[Dict[str, Any]] = []
    if liabilities_s is None or not isinstance(liabilities_s, list):
        blockers.append("BALANCE_INCOMPLETE")
    elif loaded is not None:
        seen_debts = set()
        for row in liabilities_s:
            if not isinstance(row, dict):
                blockers.append("BALANCE_INCOMPLETE")
                continue
            asset = row.get("asset")
            if row.get("status") != "KNOWN" or not isinstance(asset, str) or not asset.strip():
                blockers.append("BALANCE_INCOMPLETE")
                continue
            if "environment" in row and row.get("environment") != scope_s.get("environment"):
                blockers.append("SCOPE_MISMATCH")
                continue
            if "account_ref" in row and row.get("account_ref") != scope_s.get("account_ref"):
                blockers.append("SCOPE_MISMATCH")
                continue
            if asset in seen_debts:
                blockers.append("DUPLICATE_ROW")
                continue
            seen_debts.add(asset)
            try:
                amount = _parse_q(row.get("amount"), loaded)
            except _Stop as exc:
                blockers.append(exc.code)
                continue
            if amount.is_negative():
                blockers.append("SIGN_MISMATCH")
                continue
            try:
                amount_text = _q_text(amount, loaded)
            except _Stop as exc:
                blockers.append(exc.code)
                continue
            liability_rows.append((asset, amount))
            echoed_liabilities.append({
                "asset": asset,
                "amount": amount_text,
                "status": "KNOWN",
            })
    if loaded is not None:
        try:
            _transfers(scope_s, loaded, blockers)
        except _Stop as exc:
            blockers.append(exc.code)
        _set_proof(
            scope_s,
            _ids_assets([row for row, _total in parsed_balances]),
            _ids_positions(position_rows) if position_state in ("FLAT", "KNOWN") else [],
            blockers,
        )

    quote_index: Dict[Tuple[str, str], Q] = {}
    if loaded is not None:
        quote_index = _index_quotes(quotes_s, loaded, blockers)
        needs_clock = _needs_external_quote(
            parsed_balances, liability_rows, position_rows, venue_s, ledger_s, loaded,
        )
        quote_time_present = isinstance(quotes_s, dict) and quotes_s.get("as_of") is not None
        if needs_clock and not quote_time_present:
            blockers.append("TIMESTAMP_INVALID")
        if quote_time_present:
            quote_time = _parse_time(quotes_s.get("as_of"))
            scope_time = _parse_time(scope_s.get("as_of"))
            if quote_time is None or scope_time is None:
                blockers.append("TIMESTAMP_INVALID")
            else:
                if evaluated is not None and quote_time > evaluated:
                    blockers.append("FUTURE_TIMESTAMP")
                try:
                    skew = _parse_q(loaded["skew_limit_sec"], loaded)
                    if abs(_span(quote_time, scope_time)) > _fraction(skew, loaded):
                        blockers.append("SKEW_EXCEEDED")
                except _Stop as exc:
                    blockers.append(exc.code)

    fee_view = _window(fee_s, scope_s, "FEE", evaluated, loaded, blockers)
    funding_view = _window(funding_s, scope_s, "FUNDING", evaluated, loaded, blockers)
    if fee_view["status"] == "UNKNOWN":
        blockers.append("FEE_UNKNOWN")
    elif fee_view["status"] in ("INCOMPLETE", "PARTIAL_LATE"):
        blockers.append("FEE_INCOMPLETE")
    if funding_view["status"] == "UNKNOWN":
        blockers.append("FUNDING_UNKNOWN")
    elif funding_view["status"] in ("INCOMPLETE", "PARTIAL_LATE"):
        blockers.append("FUNDING_INCOMPLETE")
    if _event_conflicts(fee_view["events"], scope_s) or _event_conflicts(funding_view["events"], scope_s):
        blockers.append("EVENT_IDENTITY_CONFLICT")
    _apply_events(fee_s, blockers, "FEE_UNKNOWN")
    _apply_events(funding_s, blockers, "FUNDING_UNKNOWN")

    if source == "AUTHORITATIVE":
        blockers.append("AUTHORITY_NOT_PROVABLE")
    if collection_proofs is not None:
        proof = collection_proofs if isinstance(collection_proofs, dict) else None
        binding = proof.get("account_binding") if isinstance(proof, dict) else None
        valid = (
            isinstance(proof, dict)
            and isinstance(proof.get("receipt_ref"), str)
            and proof.get("receipt_ref")
            and isinstance(proof.get("raw_response_hash"), str)
            and proof.get("raw_response_hash")
            and isinstance(proof.get("verifier"), str)
            and proof.get("verifier")
            and _parse_time(proof.get("verified_at")) is not None
            and isinstance(binding, dict)
            and binding.get("environment") == scope_s.get("environment")
            and binding.get("account_ref") == scope_s.get("account_ref")
            and binding.get("sub_account_ref") == scope_s.get("sub_account_ref")
        )
        if not valid:
            blockers.append("COLLECTION_PROOF_INVALID")

    trace = None
    nav_text = None
    reconciliation = "UNAVAILABLE"
    ledger_view: Dict[str, Any] = {
        "status": "UNKNOWN",
        "mark_equity": None,
        "cash_reconstructed": None,
        "unrealized_pnl": None,
    }
    valuation: Optional[Fraction] = None
    quote_pinned = (
        isinstance(quotes_s, dict)
        and isinstance(quotes_s.get("quote_version"), str)
        and bool(quotes_s.get("quote_version").strip())
    )
    if loaded is not None and position_state in ("FLAT", "KNOWN") and not any(
        code in blockers for code in (
            "NON_FINITE", "NUMERIC_LIMIT", "PRECISION_INSUFFICIENT", "NOTIONAL_REJECTED",
            "DOUBLE_COUNT", "SIGN_MISMATCH", "BALANCE_INCOMPLETE", "POSITION_MALFORMED",
            "POSITION_UNKNOWN", "POSITION_MODE_UNKNOWN", "UNSUPPORTED_CONTRACT",
            "QUOTE_INVALID", "QUOTE_UNPINNED", "QUOTE_INCONSISTENT",
        )
    ):
        try:
            spot_parts = []
            futures_wallet: Dict[str, Q] = {}
            for row, total in parsed_balances:
                if row.get("product") == "SPOT":
                    spot_parts.append(_convert(total, str(row.get("asset")), quote_index, loaded, quote_pinned))
                elif row.get("product") == "USDS_M":
                    key = str(row.get("asset"))
                    futures_wallet[key] = total if key not in futures_wallet else _add(futures_wallet[key], total, loaded)
            pnl_by: Dict[str, Q] = {}
            for row in position_rows:
                pnl = _pnl(row, loaded)
                asset = str(row.get("settlement_asset"))
                pnl_by[asset] = pnl if asset not in pnl_by else _add(pnl_by[asset], pnl, loaded)
            equity = dict(futures_wallet)
            for asset, pnl in pnl_by.items():
                if asset not in equity:
                    if pnl.is_zero():
                        continue
                    raise _Stop("BALANCE_INCOMPLETE")
                equity[asset] = _add(equity[asset], pnl, loaded)
            wallet_btc = [
                _convert(futures_wallet[asset], asset, quote_index, loaded, quote_pinned)
                for asset in futures_wallet
            ]
            pnl_btc = [
                _convert(pnl_by[asset], asset, quote_index, loaded, quote_pinned)
                for asset in pnl_by
            ]
            liability_btc_parts = [
                _convert(amount, asset, quote_index, loaded, quote_pinned)
                for asset, amount in liability_rows
            ]
            spot_total = _sum_fractions(spot_parts, loaded)
            wallet_total = _sum_fractions(wallet_btc, loaded)
            pnl_total = _sum_fractions(pnl_btc, loaded)
            liability_total = _sum_fractions(liability_btc_parts, loaded)
            valuation = spot_total + wallet_total + pnl_total - liability_total
            nav_text = _format_fraction(valuation, loaded)
            trace = {
                "spot_equity_btc": _format_fraction(spot_total, loaded),
                "futures_wallet_btc": _format_fraction(wallet_total, loaded),
                "unrealized_pnl_btc": _format_fraction(pnl_total, loaded),
                "liability_btc": _format_fraction(liability_total, loaded),
                "futures_equity_settle": {
                    asset: _q_text(equity[asset], loaded) for asset in sorted(equity)
                },
                "unrealized_pnl_settle": {
                    asset: _q_text(pnl_by[asset], loaded) for asset in sorted(pnl_by)
                },
            }
        except _Stop as exc:
            blockers.append(exc.code)
            valuation = None
            nav_text = None
            trace = None

    venue_btc = None
    ledger_btc = None
    independent = True
    if isinstance(venue_s, dict) and isinstance(ledger_s, dict) and loaded is not None:
        if not _face_scope(venue_s, scope_s, names) or not _face_scope(ledger_s, scope_s, names):
            blockers.append("SCOPE_MISMATCH")
        if not _lineage_ready(venue_s) or not _lineage_ready(ledger_s) or not _anchors_ready(ledger_s):
            independent = False
        if venue_s.get("receipt_ref") == ledger_s.get("receipt_ref") and venue_s.get("raw_response_hash") == ledger_s.get("raw_response_hash"):
            independent = False
        if ledger_s.get("copied_from") or ledger_s.get("pnl_source") in ("VENUE", "VALUATION", "ACCOUNT_SNAPSHOT"):
            independent = False
        if not independent:
            blockers.append("RECONCILE_NOT_INDEPENDENT")
            reconciliation = "NOT_INDEPENDENT"
        try:
            venue_amount = _parse_q(venue_s.get("amount"), loaded)
            venue_btc = _convert(venue_amount, str(venue_s.get("asset")), quote_index, loaded, quote_pinned)
        except _Stop as exc:
            blockers.append(exc.code)
        if "ledger_positions" not in ledger_s or ledger_s.get("ledger_positions") is None:
            blockers.append("LEDGER_MARK_BASIS_ABSENT")
        else:
            try:
                cash: Dict[str, Q] = {}
                anchors = ledger_s.get("opening_anchor") or []
                if isinstance(anchors, dict):
                    anchors = [anchors]
                for anchor in anchors:
                    amount = _parse_q(anchor.get("amount"), loaded)
                    asset = str(anchor.get("asset"))
                    cash[asset] = amount if asset not in cash else _add(cash[asset], amount, loaded)
                movements = ledger_s.get("movements") or []
                if isinstance(movements, list) and len(movements) > loaded["max_event_rows"]:
                    raise _Stop("RESOURCE_LIMIT")
                for movement in movements:
                    amount = _parse_q(movement.get("amount"), loaded)
                    asset = str(movement.get("asset"))
                    cash[asset] = amount if asset not in cash else _add(cash[asset], amount, loaded)
                unrealized: Dict[str, Q] = {}
                for row in ledger_s.get("ledger_positions") or []:
                    pnl = _pnl(row, loaded)
                    asset = str(row.get("settlement_asset"))
                    unrealized[asset] = pnl if asset not in unrealized else _add(unrealized[asset], pnl, loaded)
                ledger_liabilities: Dict[str, Q] = {}
                for row in ledger_s.get("liabilities") or []:
                    amount = _parse_q(row.get("amount"), loaded)
                    asset = str(row.get("asset"))
                    ledger_liabilities[asset] = amount if asset not in ledger_liabilities else _add(
                        ledger_liabilities[asset], amount, loaded
                    )
                mark: Dict[str, Q] = {}
                for asset in sorted(set(cash) | set(unrealized) | set(ledger_liabilities)):
                    base = cash.get(asset, Q(0, 0))
                    extra = unrealized.get(asset, Q(0, 0))
                    debt = ledger_liabilities.get(asset, Q(0, 0))
                    mark[asset] = _add(_add(base, extra, loaded), Q(-debt.coeff, debt.exp), loaded)
                parts = [_convert(mark[asset], asset, quote_index, loaded, quote_pinned) for asset in mark]
                ledger_btc = _sum_fractions(parts, loaded)
                ledger_view = {
                    "status": "KNOWN",
                    "mark_equity": _rows_text(mark, loaded),
                    "cash_reconstructed": _rows_text(cash, loaded),
                    "unrealized_pnl": _rows_text(unrealized, loaded),
                }
            except _Stop as exc:
                blockers.append(exc.code)
    else:
        blockers.append("RECONCILE_UNAVAILABLE")

    if "SCOPE_MISMATCH" in blockers:
        reconciliation = "UNAVAILABLE"
    elif reconciliation != "NOT_INDEPENDENT" and "RECONCILE_UNAVAILABLE" in blockers:
        reconciliation = "UNAVAILABLE"
    elif (
        reconciliation != "NOT_INDEPENDENT"
        and valuation is not None
        and venue_btc is not None
        and ledger_btc is not None
        and loaded is not None
        and "TOLERANCE_INVALID" not in blockers
        and "SCOPE_MISMATCH" not in blockers
    ):
        try:
            tolerance_q = _parse_q(loaded["reconcile_tolerance_btc"], loaded)
            tolerance_fr = _fraction(tolerance_q, loaded)
            spread = max(valuation, venue_btc, ledger_btc) - min(valuation, venue_btc, ledger_btc)
            if spread > tolerance_fr:
                blockers.append("RECONCILE_MISMATCH")
                reconciliation = "MISMATCH"
            else:
                reconciliation = "MATCH"
        except _Stop as exc:
            blockers.append(exc.code)
    elif reconciliation != "NOT_INDEPENDENT":
        blockers.append("RECONCILE_UNAVAILABLE")
        reconciliation = "UNAVAILABLE"

    publish_blocks = {
        "ACCOUNT_IDENTITY_UNFIXED", "BINDING_STATE_ABSENT", "INPUT_IDENTITY_CONFLICT",
        "TIMESTAMP_INVALID", "FUTURE_TIMESTAMP", "SLA_EXCEEDED", "SKEW_EXCEEDED",
        "UNSUPPORTED_PRODUCT", "UNSUPPORTED_CONTRACT", "SET_INCOMPLETE", "DUPLICATE_ROW",
        "BALANCE_INCOMPLETE", "DOUBLE_COUNT", "TRANSFER_SCOPE_UNBALANCED", "SIGN_MISMATCH",
        "NON_FINITE", "QUOTE_INVALID", "QUOTE_UNPINNED", "NOTIONAL_REJECTED",
        "WALLET_FLOW_BASIS_UNKNOWN", "POSITION_UNKNOWN", "POSITION_MALFORMED",
        "POSITION_MODE_UNKNOWN", "FEE_UNKNOWN", "FUNDING_UNKNOWN", "FEE_INCOMPLETE",
        "FUNDING_INCOMPLETE", "EVENT_IDENTITY_CONFLICT", "COLLECTION_PROOF_INVALID",
        "AUTHORITY_NOT_PROVABLE", "NAV_PARTIAL_REJECTED", "RECONCILE_UNAVAILABLE",
        "RECONCILE_NOT_INDEPENDENT", "LEDGER_MARK_BASIS_ABSENT", "QUOTE_INCONSISTENT",
        "NUMERIC_LIMIT", "RECONCILE_MISMATCH", "SCOPE_MISMATCH", "TOLERANCE_INVALID",
        "PRECISION_INSUFFICIENT", "RESOURCE_LIMIT", "POLICY_INCOMPLETE",
    }
    unique = sorted(set(blockers))
    if any(code in publish_blocks for code in unique):
        nav_text = None
        trace = None
    calculation_ok = nav_text is not None and not unique
    if not calculation_ok:
        nav_text = None
        trace = None
    snapshot = {
        "calculation_ok": calculation_ok,
        "account_authority": "NOT_ESTABLISHED",
        "new_risk_usable": False,
        "reality_authority": "NOT_ESTABLISHED",
        "btc_nav": nav_text,
        "btc_nav_unit": "BTC" if nav_text is not None else None,
        "btc_nav_trace": trace,
        "arithmetic_policy_version": None if loaded is None else loaded["arithmetic_policy_version"],
        "balances": balance_rows if isinstance(balances_s, list) else None,
        "liabilities": echoed_liabilities if isinstance(liabilities_s, list) else None,
        "positions": position_state,
        "fee_manifest": fee_view,
        "funding_manifest": funding_view,
        "set_completeness": copy.deepcopy(scope_s.get("set_completeness")),
        "venue_reported_equity": copy.deepcopy(venue_s) if isinstance(venue_s, dict) else None,
        "ledger_reconstruction": ledger_view,
        "reconciliation": reconciliation if calculation_ok or reconciliation in (
            "MISMATCH", "NOT_INDEPENDENT", "UNAVAILABLE"
        ) else "UNAVAILABLE",
        "binding_proposal": proposal["action"],
        "blockers": unique,
        "source_claim": source if isinstance(source, str) else None,
        "as_of": scope_s.get("as_of"),
        "evaluation_at": evaluation_at,
        "scope_version": scope_s.get("scope_version"),
        "canonical_version": CANONICAL_VERSION,
        "hash_alg": HASH_ALG,
        "order_intent": "ABSENT",
        "execution_eligibility": "DENIED",
        "quotes": copy.deepcopy(quotes_s) if isinstance(quotes_s, dict) else None,
        "non_finite": non_finite,
    }
    return {"snapshot": snapshot, "binding_proposal": proposal}


def _closed_result(code: str, evaluation_at: Any) -> Dict[str, Any]:
    proposal = {
        "action": "REFUSED",
        "declaration_key": None,
        "content_hash": None,
        "proposed_binding": None,
        "existing_bindings": [],
        "prior_content_hash": None,
    }
    snapshot = {
        "calculation_ok": False,
        "account_authority": "NOT_ESTABLISHED",
        "new_risk_usable": False,
        "reality_authority": "NOT_ESTABLISHED",
        "btc_nav": None,
        "btc_nav_unit": None,
        "btc_nav_trace": None,
        "arithmetic_policy_version": None,
        "balances": None,
        "liabilities": None,
        "positions": "UNKNOWN",
        "fee_manifest": {"status": "UNKNOWN", "total": None, "events": [], "lineage": None},
        "funding_manifest": {"status": "UNKNOWN", "total": None, "events": [], "lineage": None},
        "set_completeness": None,
        "venue_reported_equity": None,
        "ledger_reconstruction": {
            "status": "UNKNOWN",
            "mark_equity": None,
            "cash_reconstructed": None,
            "unrealized_pnl": None,
        },
        "reconciliation": "UNAVAILABLE",
        "binding_proposal": "REFUSED",
        "blockers": [code],
        "source_claim": None,
        "as_of": None,
        "evaluation_at": evaluation_at,
        "scope_version": None,
        "canonical_version": CANONICAL_VERSION,
        "hash_alg": HASH_ALG,
        "order_intent": "ABSENT",
        "execution_eligibility": "DENIED",
        "quotes": None,
        "non_finite": [],
    }
    return {"snapshot": snapshot, "binding_proposal": proposal}


def evaluate_account_truth(
    scope: Any,
    balances: Any,
    liabilities: Any,
    positions: Any,
    fee_manifest: Any,
    funding_manifest: Any,
    quotes: Any,
    venue_reported_equity: Any,
    ledger_reconstruction: Any,
    binding_state: Any,
    collection_proofs: Any,
    policy: Any,
    evaluation_at: Any,
) -> Dict[str, Any]:
    try:
        return _evaluate_account_truth(
            scope,
            balances,
            liabilities,
            positions,
            fee_manifest,
            funding_manifest,
            quotes,
            venue_reported_equity,
            ledger_reconstruction,
            binding_state,
            collection_proofs,
            policy,
            evaluation_at,
        )
    except _Stop as exc:
        return _closed_result(exc.code, evaluation_at)
