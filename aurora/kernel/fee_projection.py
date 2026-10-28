"""FILL IDENTITY S3：费用补充与投影（离线隔离实现）。

开工令（2026-10-28，基线 8511151）：仅限离线隔离实现。

冻结合同（设计 v6 §3 / F5′ / F6′）：
- §3.2 判定表七行：基线（fills.fee_raw KNOWN/UNKNOWN）× 补充事实 →
  KNOWN / INCOMPLETE / FEE_CONFLICT；冲突不取先到/后到/均值。
- §3.3 deduct-once 四层证明链：stable_event_id UNIQUE /
  fill_fee_projection 版本 / effect_key UNIQUE / 三步单事务。
- F5′ 四规则：①一致补充零影响；②UNKNOWN 首次查明全额一次；
  ③冲突只隔离告警（CONFLICTED，零自动差额）；④仅带凭据的显式
  修正产生新版本——补充到达永远无权解决冲突。
- 跨资产修正=按资产双蹄同事务（REVERSE 旧全额 + APPLY 新全额），
  禁止跨单位相减；同资产才允许 delta（§3.5 精确运算）。
- §3.5 动态精度+Inexact/Rounded 陷阱，一次翻倍重试，prec 上限
  10000，不得突破。仍不精确、或比较在上限内无法确定 → 显式拒绝
  （PrecisionRefused / ComparisonRefused），不当 UNKNOWN、不当相等、
  也不继续加精度。
- 规则①只表示一致补充的增量为零。已知基线的既有经济效果
  （成交行 economic_effect_applied=1 且 fee_raw 仍在）不得被清掉，
  也不得再写一条同额 APPLY。

离线边界（开工令）：
- "记账效果"仅指离线效果记录（fee_effect_ledger）；不写账户余额、
  PnL、风险预算，不写 pnl_reliability 等现有风险标志；
- 不接任何消费方（会计/风险层读取接口 effective_fee 仅供已授权
  方调用）；不接默认 Ledger 初始化、生产入口、funding；
- 事务纪律（FIX7 同款）：写入入口遇调用方未提交事务，写入前
  拒绝；不替调用方 commit/rollback，不改连接配置。
"""
from __future__ import annotations

from decimal import (
    Decimal, Inexact, Rounded, localcontext,
)
from typing import Any, Dict, List, Optional

from aurora.kernel.fill_identity import validate_new_ref
from aurora.p0_boundary import SafetyViolation

# §3.5 冻结常量（第 0 节确定化）
PREC_FLOOR = 28
PREC_EXTRA = 4
PREC_CAP = 10000
ADJUSTED_BOUND = 999999


class FeeConflict(Exception):
    """同稳定事件 ID 以不同内容重放（funding 同纪律）。"""


class PrecisionRefused(Exception):
    """运算在动态精度+陷阱与一次翻倍重试后仍不精确，或操作数
    显著位数超过 10000——拒绝入账。不静默截断，也不把 prec 提到
    上限以上。"""


class ComparisonRefused(Exception):
    """比较在 10000 位资源上限内无法确定。不是 UNKNOWN，也不是相等。"""


def _measure_fee_text(raw: str, field: str):
    """在构造 Decimal 之前量显著位数与 adjusted。

    超长系数不交给 Decimal。非有限、空串、非法文本 → SafetyViolation。
    """
    if not isinstance(raw, str):
        raise SafetyViolation(
            f"{field} must be a finite Decimal text, got {raw!r}")
    s = raw.strip()
    body = s[1:] if s[:1] in "+-" else s
    if body == "" or body.lower() in ("inf", "infinity", "nan", "snan"):
        raise SafetyViolation(
            f"{field} must be a finite Decimal text, got {raw!r}")
    low = body.lower()
    exp = 0
    if "e" in low:
        coeff, exp_s = low.split("e", 1)
        exp_digits = exp_s[1:] if exp_s[:1] in "+-" else exp_s
        if exp_s in ("", "+", "-") or not exp_digits.isdigit():
            raise SafetyViolation(
                f"{field} must be a finite Decimal text, got {raw!r}")
        if len(exp_digits) > 6 and int(exp_digits) > ADJUSTED_BOUND:
            raise SafetyViolation(
                f"{field} exceeds adjusted-exponent bound"
                f" |{exp_s}| > {ADJUSTED_BOUND}: {raw!r}")
        exp = int(exp_s)
        body = coeff
    if (body.count(".") > 1 or body.replace(".", "") == ""
            or not body.replace(".", "").isdigit()):
        raise SafetyViolation(
            f"{field} must be a finite Decimal text, got {raw!r}")
    if "." in body:
        whole, frac = body.split(".", 1)
    else:
        whole, frac = body, ""
    if whole == "":
        whole = "0"
    digits = (whole + frac).lstrip("0")
    if digits == "":
        return 1, 0
    sig = len(digits)
    adjusted = exp - len(frac) + sig - 1
    return sig, adjusted


def fee_values_equal(raw_a: Optional[str],
                     raw_b: Optional[str]) -> Optional[bool]:
    """§3.4 比较算子：Decimal 数值相等（与表示无关，无舍入无损）。

    任一侧 UNKNOWN（None/空）→ None（不可证实）。
    任一侧显著位数或指数超出资源上限 → ComparisonRefused。
    不把无法比较的值当成 UNKNOWN 或相等，也不扩大精度再比。
    """
    if raw_a in (None, "") or raw_b in (None, ""):
        return None
    for label, raw in (("left", raw_a), ("right", raw_b)):
        sig, adjusted = _measure_fee_text(raw, label)
        if sig > PREC_CAP or abs(adjusted) > ADJUSTED_BOUND:
            raise ComparisonRefused(
                f"fee comparison indeterminate within precision"
                f" cap {PREC_CAP} ({label} sig={sig}"
                f" adjusted={adjusted}); not UNKNOWN and not equal")
    return Decimal(raw_a) == Decimal(raw_b)


def checked_fee_decimal(raw: str, field: str) -> Decimal:
    """入口边界（§3.5）：有限 + |adjusted| ≤ 999999 + 显著位数 ≤ 10000。

    超位数在构造 Decimal 之前拒绝（PrecisionRefused）。
    非有限与指数超界仍是 SafetyViolation。
    """
    if raw is None or raw == "":
        raise SafetyViolation(
            f"{field} must be a finite Decimal text, got {raw!r}")
    sig, adjusted = _measure_fee_text(raw, field)
    if abs(adjusted) > ADJUSTED_BOUND:
        raise SafetyViolation(
            f"{field} exceeds adjusted-exponent bound"
            f" |{adjusted}| > {ADJUSTED_BOUND}: {raw!r}")
    if sig > PREC_CAP:
        raise PrecisionRefused(
            f"{field} exceeds precision resource cap {PREC_CAP}"
            f" ({sig} significant digits); refusing before"
            f" allocation")
    d = Decimal(raw)
    if not d.is_finite():
        raise SafetyViolation(
            f"{field} must be a finite Decimal text, got {raw!r}")
    return d


def _needed_prec(vals: List[Decimal]) -> int:
    digits = max(len(v.as_tuple().digits) for v in vals)
    span = (max(v.adjusted() for v in vals)
            - min(v.as_tuple().exponent for v in vals) + 1)
    needed = max(digits, span, PREC_FLOOR) + PREC_EXTRA
    if needed > PREC_CAP:
        return PREC_CAP
    return needed


def _attempt_precs(prec: int) -> List[int]:
    """一次翻倍重试，结果不得大于 PREC_CAP。已到上限则不再加。"""
    if prec > PREC_CAP:
        raise PrecisionRefused(
            f"precision attempt {prec} exceeds cap {PREC_CAP}")
    if prec >= PREC_CAP:
        return [PREC_CAP]
    doubled = prec * 2
    if doubled >= PREC_CAP:
        return [prec, PREC_CAP]
    return [prec, doubled]


def _precise_binop(a_raw: str, b_raw: str, op) -> str:
    a = checked_fee_decimal(a_raw, "operand")
    b = checked_fee_decimal(b_raw, "operand")
    prec = _needed_prec([a, b])
    last_err: Optional[Exception] = None
    for attempt in _attempt_precs(prec):
        if attempt > PREC_CAP:
            raise PrecisionRefused(
                f"precision attempt {attempt} exceeds cap {PREC_CAP}")
        with localcontext() as ctx:
            ctx.prec = attempt
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            try:
                return str(op(a, b))
            except (Inexact, Rounded) as exc:
                last_err = exc
                continue
    raise PrecisionRefused(
        f"operation inexact after precision retry (prec attempts"
        f" capped at {PREC_CAP}): {a_raw!r} vs {b_raw!r}: {last_err}")


def precise_sub(a_raw: str, b_raw: str) -> str:
    """§3.5 精确差（仅同资产且双操作数有限时成立）。"""
    return _precise_binop(a_raw, b_raw, lambda x, y: x - y)


def precise_add(a_raw: str, b_raw: str) -> str:
    return _precise_binop(a_raw, b_raw, lambda x, y: x + y)


def evaluate_fee_state(
    baseline_raw: Optional[str], baseline_asset: Optional[str],
    supplements: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """§3.2 判定表（冻结七行）。

    supplements: [{fee_raw_s, fee_asset_s}, ...]（已入账全部补充）。
    返回 {verdict, effective_raw, effective_asset, reason}；
    冲突时 effective 保留基线值（无基线则 None），绝不取均值。
    """
    known = [(s["fee_raw_s"], s["fee_asset_s"])
             for s in supplements if s["fee_raw_s"] not in (None, "")]
    if known:
        first_raw, first_asset = known[0]
        for raw, asset in known[1:]:
            if fee_values_equal(first_raw, raw) is not True \
                    or str(first_asset) != str(asset):
                return {"verdict": "FEE_CONFLICT",
                        "effective_raw": baseline_raw
                        if baseline_raw not in (None, "") else None,
                        "effective_asset": baseline_asset,
                        "reason": "conflicting supplements"}
        sup_val = (first_raw, first_asset)
    else:
        sup_val = None
    if baseline_raw not in (None, ""):
        if sup_val is not None and (
                fee_values_equal(baseline_raw, sup_val[0]) is not True
                or str(baseline_asset) != str(sup_val[1])):
            return {"verdict": "FEE_CONFLICT",
                    "effective_raw": baseline_raw,
                    "effective_asset": baseline_asset,
                    "reason": "supplement conflicts with baseline V0"}
        return {"verdict": "KNOWN", "effective_raw": baseline_raw,
                "effective_asset": baseline_asset,
                "reason": "baseline V0"}
    if sup_val is None:
        return {"verdict": "INCOMPLETE", "effective_raw": None,
                "effective_asset": None,
                "reason": "baseline UNKNOWN and no KNOWN supplement"}
    return {"verdict": "KNOWN", "effective_raw": sup_val[0],
            "effective_asset": sup_val[1],
            "reason": "first KNOWN supplement (rule ②)"}


def _guard_own_txn(ledger) -> None:
    """FIX7 事务纪律：调用方未提交事务 → 写入前拒绝。"""
    if ledger._conn.in_transaction:
        raise SafetyViolation(
            "fee_projection write entry must own its transaction:"
            " caller connection has an open transaction; refusing"
            " before any write (finish or rollback the outer"
            " transaction first)")


def _require_s1_schema(ledger) -> None:
    if not ledger._fills_has_symbol():
        raise SafetyViolation(
            "fee projection requires S1 schema (fee_raw/fee_asset"
            " columns); run isolated migration first")


def _validate_fill_ref(ledger, fill_ref: str) -> None:
    if not isinstance(fill_ref, str) or ":" not in fill_ref:
        raise SafetyViolation(
            f"fill_ref must be qualified 'symbol:trade_id',"
            f" bare id forbidden: {fill_ref!r}")
    res = validate_new_ref(ledger._conn, fill_ref)
    if not res["ok"]:
        raise SafetyViolation(
            f"fill_ref does not resolve: {fill_ref!r} ({res['reason']})")


def _baseline_of(ledger, fill_ref: str):
    sym, tid = fill_ref.split(":", 1)
    row = ledger._conn.execute(
        "SELECT fee_raw, fee_asset FROM fills"
        " WHERE symbol = ? AND fill_id = ?", (sym, tid)).fetchone()
    if row is None:
        raise SafetyViolation(f"fill_ref target missing: {fill_ref!r}")
    return row["fee_raw"], row["fee_asset"]


def _effect_key(fill_ref: str, version: int, asset: str) -> str:
    return f"{fill_ref}:FEE:v{version}:{asset}"


def _require_known_baseline_booking(conn, fill_ref: str,
                                    baseline_raw: str) -> None:
    """一致补充的零增量不能代替已知基线的首次记账。

    成交行必须仍是 economic_effect_applied=1，且 fee_raw 与基线
    数值相等。本函数不写效果、不改成交行：既有记账留在 fills，
    补充路径不得再插一条同额 APPLY。
    """
    sym, tid = fill_ref.split(":", 1)
    row = conn.execute(
        "SELECT fee_raw, economic_effect_applied FROM fills"
        " WHERE symbol = ? AND fill_id = ?", (sym, tid)).fetchone()
    intact = (
        row is not None
        and row["fee_raw"] not in (None, "")
        and int(row["economic_effect_applied"]) == 1
        and fee_values_equal(row["fee_raw"], baseline_raw) is True
    )
    if not intact:
        raise SafetyViolation(
            "known baseline economic booking is absent or does"
            " not match the projected baseline; a consistent"
            " supplement has zero incremental effect and cannot"
            " exempt or replace the first booking")


def _write_effect(conn, key: str, kind: str, amount_raw: str,
                  asset: str, fill_ref: str, now: str) -> None:
    conn.execute(
        "INSERT INTO fee_effect_ledger (effect_key, kind, amount_raw,"
        " asset, fill_ref, written_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key, kind, amount_raw, asset, fill_ref, now))


def record_fee_supplement(
    ledger, *, stable_event_id: str, fill_ref: str,
    fee_raw_s: Optional[str] = None,
    fee_asset_s: Optional[str] = None,
    observed_at: str = "",
) -> Dict[str, Any]:
    """补充事实入账 + 判定表求值 + 投影/效果更新（三步单事务）。

    F5′：①一致→零影响；②首次查明→v1 全额 APPLY 一次；③冲突→
    CONFLICTED 隔离告警（零自动差额）。同 stable_event_id 异容 →
    FeeConflict；同容重放 → 零新增。
    """
    from aurora.kernel.ledger import utc_now
    _guard_own_txn(ledger)
    _require_s1_schema(ledger)
    if not stable_event_id or not str(stable_event_id).strip():
        raise SafetyViolation(
            "supplement requires a stable event id (venue tranId"
            " discipline; unstable-id observations are refused)")
    _validate_fill_ref(ledger, fill_ref)
    if fee_raw_s not in (None, ""):
        checked_fee_decimal(fee_raw_s, "fee_raw_s")
        if not fee_asset_s:
            raise SafetyViolation(
                "fee KNOWN requires fee_asset (F4 口径)")
    else:
        fee_raw_s, fee_asset_s = None, None  # UNKNOWN 观察
    ledger.ensure_fee_projection_schema()
    now = observed_at or utc_now()
    conn = ledger._conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        # (1) 补充幂等：stable_event_id UNIQUE；同 ID 异容=冲突
        dup = conn.execute(
            "SELECT fill_ref, fee_raw_s, fee_asset_s"
            " FROM fill_fee_supplements WHERE stable_event_id = ?",
            (stable_event_id,)).fetchone()
        if dup is not None:
            same = (dup["fill_ref"] == fill_ref
                    and fee_values_equal(dup["fee_raw_s"], fee_raw_s)
                    in (True, None)
                    and (dup["fee_raw_s"] in (None, ""))
                    == (fee_raw_s in (None, ""))
                    and str(dup["fee_asset_s"] or "") ==
                    str(fee_asset_s or ""))
            if not same:
                raise FeeConflict(
                    f"stable event id {stable_event_id!r} replayed"
                    f" with different content: stored="
                    f"({dup['fill_ref']}, {dup['fee_raw_s']},"
                    f" {dup['fee_asset_s']}) incoming="
                    f"({fill_ref}, {fee_raw_s}, {fee_asset_s})")
            conn.rollback()
            cur_state = evaluate_fee_state(
                *_baseline_of(ledger, fill_ref),
                ledger.fee_supplements(fill_ref))
            return {"verdict": cur_state["verdict"], "rule": "replay",
                    "replayed": True, "version": 0,
                    "effect_keys": [],
                    "effective_raw": cur_state["effective_raw"]}
        # (a) 补充事实
        conn.execute(
            "INSERT INTO fill_fee_supplements (stable_event_id,"
            " fill_ref, fee_raw_s, fee_asset_s, observed_at,"
            " recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (stable_event_id, fill_ref, fee_raw_s, fee_asset_s,
             now, utc_now()))
        # 求值（基线 + 全部补充）
        baseline_raw, baseline_asset = _baseline_of(ledger, fill_ref)
        state = evaluate_fee_state(
            baseline_raw, baseline_asset,
            ledger.fee_supplements(fill_ref))
        proj = ledger.fee_projection_row(fill_ref)
        if state["verdict"] == "FEE_CONFLICT":
            # ③ 冲突只隔离告警：保留既有有效值，零差额
            eff_raw = (proj["effective_raw"] if proj
                       else state["effective_raw"])
            eff_asset = (proj["effective_asset"] if proj
                         else state["effective_asset"])
            version = proj["projection_version"] if proj else 0
            _upsert_projection(
                conn, fill_ref, "CONFLICTED", version,
                eff_raw, eff_asset,
                proj["applied_effect_key"] if proj else None, utc_now())
            conn.commit()
            return {"verdict": "FEE_CONFLICT", "rule": "③",
                    "replayed": False, "version": version,
                    "effect_keys": [], "conflict": state["reason"],
                    "effective_raw": eff_raw}
        if state["verdict"] == "INCOMPLETE":
            # 不投影、不写 0、不判重复（行 2/7）
            conn.commit()
            return {"verdict": "INCOMPLETE", "rule": "—",
                    "replayed": False, "version": 0,
                    "effect_keys": [], "effective_raw": None}
        # KNOWN：
        consistent_with_known = (
            fee_raw_s not in (None, "")
            and fee_values_equal(fee_raw_s, state["effective_raw"]) is True
            and str(fee_asset_s) == str(state["effective_asset"])
        )
        if proj is None and baseline_raw not in (None, "") \
                and consistent_with_known:
            # ① 与基线 V0 一致：补充增量为零。基线首次记账仍在成交行，
            # 这里不另写 APPLY，也不改 fee / economic_effect_applied。
            _require_known_baseline_booking(
                conn, fill_ref, baseline_raw)
            _upsert_projection(
                conn, fill_ref, "KNOWN", 0,
                state["effective_raw"], state["effective_asset"],
                None, utc_now())
            conn.commit()
            return {"verdict": "KNOWN", "rule": "①", "replayed": False,
                    "version": 0, "effect_keys": [],
                    "effective_raw": state["effective_raw"]}
        if proj is not None and proj["status"] == "KNOWN" \
                and fee_values_equal(
                    proj["effective_raw"], state["effective_raw"]) \
                is True \
                and str(proj["effective_asset"]) == \
                str(state["effective_asset"]):
            # ① 与已投影有效值一致 → 补充增量为零。已知基线的
            # 既有记账必须仍在，且不新增效果。
            if baseline_raw not in (None, ""):
                _require_known_baseline_booking(
                    conn, fill_ref, baseline_raw)
            conn.commit()
            return {"verdict": "KNOWN", "rule": "①", "replayed": False,
                    "version": proj["projection_version"],
                    "effect_keys": [], "effective_raw":
                        proj["effective_raw"]}
        if proj is not None and proj["status"] == "KNOWN":
            # 已知有效值 + 不一致已知补充 → 判定表已判冲突；此处
            # 仅在求值未捕获的组合上防御（不产生任何差额）
            conn.commit()
            return {"verdict": "KNOWN", "rule": "①",
                    "replayed": False,
                    "version": proj["projection_version"],
                    "effect_keys": [],
                    "effective_raw": proj["effective_raw"]}
        # ② UNKNOWN 首次查明 → v1 全额恰一次
        version = (proj["projection_version"] + 1) if proj else 1
        eff_raw = state["effective_raw"]
        eff_asset = str(state["effective_asset"])
        key = _effect_key(fill_ref, version, eff_asset)
        # (b) 投影更新
        _upsert_projection(conn, fill_ref, "KNOWN", version,
                           eff_raw, eff_asset, key, utc_now())
        # (c) 记账效果（离线效果记录；全额）
        _write_effect(conn, key, "APPLY", eff_raw, eff_asset,
                      fill_ref, utc_now())
        conn.commit()
        return {"verdict": "KNOWN", "rule": "②", "replayed": False,
                "version": version, "effect_keys": [key],
                "effective_raw": eff_raw}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _upsert_projection(conn, fill_ref, status, version, eff_raw,
                       eff_asset, effect_key, now) -> None:
    row = conn.execute(
        "SELECT 1 FROM fill_fee_projection WHERE fill_ref = ?",
        (fill_ref,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO fill_fee_projection (fill_ref, status,"
            " projection_version, effective_raw, effective_asset,"
            " applied_effect_key, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fill_ref, status, version, eff_raw, eff_asset,
             effect_key, now))
    else:
        conn.execute(
            "UPDATE fill_fee_projection SET status = ?,"
            " projection_version = ?, effective_raw = ?,"
            " effective_asset = ?, applied_effect_key = ?,"
            " updated_at = ? WHERE fill_ref = ?",
            (status, version, eff_raw, eff_asset, effect_key, now,
             fill_ref))


def apply_fee_correction(
    ledger, *, fill_ref: str, new_fee_raw: str,
    new_fee_asset: str, credential_ref: str,
    note: str = "",
) -> Dict[str, Any]:
    """F5′ ④：显式修正/解决事件（唯一产生新版本的通道）。

    - 凭据引用必须通过机器/人工引用校验（带凭据）；
    - 同资产 → delta 重算（§3.5 精确差），只应用差额；
    - 跨资产 → 按资产双蹄同事务（REVERSE 旧全额 + APPLY 新全额），
      任一蹄证据不足 → 两蹄都不应用；
    - 当前无有效值（INCOMPLETE）→ 首次查明语义 v1 全额。
    """
    from aurora.kernel.ledger import utc_now
    _guard_own_txn(ledger)
    _require_s1_schema(ledger)
    ledger._validate_resolution_ref(credential_ref or "")
    new_val = checked_fee_decimal(new_fee_raw, "new_fee_raw")
    if not new_fee_asset:
        raise SafetyViolation("correction requires new fee asset")
    _validate_fill_ref(ledger, fill_ref)
    ledger.ensure_fee_projection_schema()
    conn = ledger._conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        proj = ledger.fee_projection_row(fill_ref)
        old_raw = proj["effective_raw"] if proj else None
        old_asset = (str(proj["effective_asset"]) if proj else None)
        old_version = proj["projection_version"] if proj else 0
        new_version = old_version + 1
        new_asset = str(new_fee_asset)
        effects: List[Dict[str, Any]] = []
        mode: str
        delta_raw: Optional[str] = None
        if old_raw in (None, ""):
            # 首次查明（含 CONFLICTED 无保留值——修正即解决）：
            # 若此前 CONFLICTED 由冲突补充造成且无保留有效值，
            # REVERSE 无从谈起 → 全额 APPLY（首次查明语义）
            mode = "FIRST"
            key = _effect_key(fill_ref, new_version, new_asset)
            effects.append({"key": key, "kind": "APPLY",
                            "amount_raw": new_fee_raw,
                            "asset": new_asset})
        elif old_asset == new_asset:
            # 同资产：delta 重算，绝不再扣全额
            mode = "DELTA"
            delta_raw = precise_sub(new_fee_raw, old_raw)
            if Decimal(delta_raw) != 0:
                key = _effect_key(fill_ref, new_version, new_asset)
                effects.append({"key": key, "kind": "APPLY",
                                "amount_raw": delta_raw,
                                "asset": new_asset})
        else:
            # 跨资产：按资产双蹄，禁止跨单位相减。
            # CONFLICTED 的保留数字不是可撤销的完整证据。
            mode = "DOUBLE_LEG"
            conflicted = bool(proj) and proj["status"] == "CONFLICTED"
            if conflicted or old_raw in (None, "") or not old_asset:
                raise SafetyViolation(
                    "cross-asset correction requires complete"
                    " evidence for both legs (old effective value"
                    " unknown or CONFLICTED → REVERSE leg"
                    " impossible → neither leg applied)")
            effects.append({
                "key": _effect_key(fill_ref, new_version, old_asset),
                "kind": "REVERSE", "amount_raw": old_raw,
                "asset": old_asset})
            effects.append({
                "key": _effect_key(fill_ref, new_version, new_asset),
                "kind": "APPLY", "amount_raw": new_fee_raw,
                "asset": new_asset})
        # 追加修正记录（append-only）
        conn.execute(
            "INSERT INTO fee_corrections (fill_ref,"
            " old_effective_raw, old_effective_asset,"
            " new_effective_raw, new_effective_asset, mode,"
            " delta_raw, credential_ref, note, corrected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fill_ref, old_raw, old_asset, new_fee_raw, new_asset,
             mode, delta_raw, credential_ref, note, utc_now()))
        primary_key = effects[-1]["key"] if effects else None
        _upsert_projection(conn, fill_ref, "KNOWN", new_version,
                           new_fee_raw, new_asset, primary_key,
                           utc_now())
        for eff in effects:
            _write_effect(conn, eff["key"], eff["kind"],
                          eff["amount_raw"], eff["asset"], fill_ref,
                          utc_now())
        conn.commit()
        return {"verdict": "CORRECTED", "mode": mode,
                "version": new_version, "delta_raw": delta_raw,
                "effect_keys": [e["key"] for e in effects],
                "legs": effects}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def effective_fee(ledger, fill_ref: str) -> Dict[str, Any]:
    """只读投影访问器（会计/风险层唯一允许的费用值来源）。

    无投影行 = INCOMPLETE（费用 UNKNOWN 非 0）；CONFLICTED →
    拒绝投影（消费方语义：费用按 UNKNOWN 阻断新增风险——本层
    只如实报状态，不接消费方）。
    """
    row = ledger.fee_projection_row(fill_ref)
    if row is None:
        return {"status": "INCOMPLETE", "effective_raw": None,
                "effective_asset": None, "projection_version": 0}
    return {"status": row["status"],
            "effective_raw": row["effective_raw"],
            "effective_asset": row["effective_asset"],
            "projection_version": row["projection_version"]}
