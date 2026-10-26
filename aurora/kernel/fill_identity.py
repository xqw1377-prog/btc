"""FILL IDENTITY S2：统一身份校验器（隔离实现——显式调用专用）。

S1 边界延续 + S2 新增边界（开工令 2026-10-26）：
- 不接入默认 Ledger 初始化、不迁移真实账本、不实现 S3 费用投影；
- 唯一身份校验器 fill_content_mismatch + MatchReport；
- 两入口（insert_fill IntegrityError 分支 / apply_fill_event 预检）
  共用本模块——本模块是字段集与比较算子的唯一来源；
- 推导上下文（derivation_ctx）分类：DERIVATION_DEVIATION ≠ 身份冲突；
- 归属异常（事件 symbol ≠ 订单 symbol）与历史未解析身份
  （IDENTITY_UNRESOLVED）分类；
- 引用消解（裸 ID 三分支 + 限定引用目标存在性）。

比较算子（冻结，与设计 v6/计划 §0 一致）：
- 交易所事实字段：symbol/side/qty/price/fee/fee_asset——已知值比较
  用原始串有限 Decimal 数值相等（§3.4/3.5）；
- KNOWN vs UNKNOWN = INCOMPLETE（任何方向）；UNKNOWN vs UNKNOWN =
  字段不可证实（不计入确认相等）；
- REAL 展示值不参与比较（EVENT 行以 *_raw 为准；LEGACY 行 REAL
  即事实、标 LEGACY_APPROXIMATE，跨等级=COMPARISON_INCOMPLETE）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "4"

# 身份与比较字段集唯一来源：cid + 六事实字段（S2-01 修正：cid 入集）
FACT_FIELDS = ("client_order_id", "symbol", "side", "qty", "price",
               "fee", "fee_asset")
_NONNUMERIC = ("client_order_id", "symbol", "side", "fee_asset")
_POSITIVE_NUMERIC = ("qty", "price")  # 非法（≤0/非有限）= 拒收，非 UNKNOWN

MAX_FIELD_CMP = 10000  # Decimal 数值位数支持上限（与 S1 _PREC_CAP 同源）


class FillIdentityConflict(Exception):
    """同完整身份键 + 事实内容不同（身份层冲突）。"""


class DerivationDeviation(Exception):
    """同推导上下文重算不一致（推导层，非身份冲突）。"""


def parse_finite(raw):
    """原始串 → 有限 Decimal；None/空/不可解析/非有限 → None（=UNKNOWN）。"""
    from decimal import Decimal, InvalidOperation
    if raw is None or raw == "":
        return None
    try:
        d = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not d.is_finite():
        return None
    if len(d.as_tuple().digits) > MAX_FIELD_CMP:
        return None  # 超支持范围视为不可比较（fail-closed）
    return d


def _normalize_row(row):
    """统一输入模型（S2-03 修正）。

    - EVENT 行：数值字段只认 *_raw；qty/price 必须为正有限值，
      非法（≤0/NaN/垃圾）→ ValueError 拒收（不是 UNKNOWN，更不是
      可确认重复）
    - LEGACY 行：数值字段以 REAL 为近似事实（tier=APPROXIMATE）
    - 缺 origin 按 LEGACY 处理（fail-closed 侧）
    - fee 为可选数值字段：raw 缺失=UNKNOWN（INCOMPLETE 口径），
      提供则须合法有限（负值允许——费用可为收入/支出）
    """
    origin = row.get("origin") or "LEGACY"
    out = {"origin": origin, "tier": None}
    for f in _NONNUMERIC:
        v = row.get(f)
        out[f] = None if v in (None, "") else str(v)
    if origin == "EVENT":
        out["tier"] = "EXACT"
        for f in _POSITIVE_NUMERIC:
            raw_v = row.get(f + "_raw")
            d = parse_finite(raw_v)
            if d is None or d <= 0:
                raise ValueError(
                    f"EVENT {f}_raw invalid (must be finite positive):"
                    f" {raw_v!r}")
            out[f] = d
        fee_d = parse_finite(row.get("fee_raw"))
        if row.get("fee_raw") not in (None, "") and fee_d is None:
            raise ValueError(
                f"EVENT fee_raw invalid: {row.get('fee_raw')!r}")
        out["fee"] = fee_d
    else:
        out["tier"] = "APPROXIMATE"
        for f in ("qty", "price", "fee"):
            v = row.get(f)
            if v is None:
                out[f] = None
            else:
                d = parse_finite(str(v))
                out[f] = d
    return out


def fill_content_mismatch(stored, incoming):
    """唯一身份校验器（S2-01/02/03 修正版）。

    输入：含 origin 的行（EVENT 认 *_raw；LEGACY 认 REAL 近似）。
    MATCH/MISMATCH/INCOMPLETE 三裁决 + ValueError（非法输入拒收）。
    跨精度等级（EXACT vs APPROXIMATE）→ INCOMPLETE（不可确认匹配）。
    """
    s = _normalize_row(stored)
    i = _normalize_row(incoming)
    notes = []
    if s["tier"] != i["tier"]:
        notes.append(
            f"cross precision tier {s['tier']} vs {i['tier']}:"
            " cannot confirm match")
        return {"verdict": "INCOMPLETE", "conflict_fields": [],
                "unverifiable_fields": [], "notes": notes}
    conflict, unverifiable = [], []
    for f in FACT_FIELDS:
        s_v, i_v = s[f], i[f]
        if s_v is None or i_v is None:
            # S2-02：双 UNKNOWN 也算不可证实——绝不计入确认匹配
            unverifiable.append(f)
            continue
        if f in _NONNUMERIC:
            if s_v != i_v:
                conflict.append(f)
        else:
            if s_v != i_v:
                conflict.append(f)
    if conflict:
        return {"verdict": "MISMATCH", "conflict_fields": conflict,
                "unverifiable_fields": [], "notes": notes}
    if unverifiable:
        return {"verdict": "INCOMPLETE", "conflict_fields": [],
                "unverifiable_fields": unverifiable, "notes": notes}
    return {"verdict": "MATCH", "conflict_fields": [],
            "unverifiable_fields": [], "notes": notes}


def order_symbol_for(conn, client_order_id):
    """订单归属 symbol：经 orders → intents.symbol 解析。"""
    row = conn.execute(
        "SELECT i.symbol FROM orders o JOIN intents i"
        " ON o.intent_id = i.intent_id"
        " WHERE o.client_order_id = ?", (client_order_id,)).fetchone()
    return row[0] if row else None


def check_attribution(conn, fill_symbol, client_order_id):
    """归属校验：事件 symbol ≠ 所属订单 symbol → ATTRIBUTION_ANOMALY。"""
    order_sym = order_symbol_for(conn, client_order_id)
    if order_sym is None:
        return {"verdict": "ORDER_NOT_FOUND"}
    if fill_symbol is None:
        return {"verdict": "SYMBOL_UNKNOWN"}
    if str(fill_symbol) != str(order_sym):
        return {"verdict": "ATTRIBUTION_ANOMALY",
                "fill_symbol": fill_symbol, "order_symbol": order_sym}
    return {"verdict": "OK", "order_symbol": order_sym}


def resolve_fill_ref(conn, ref):
    """消解一条 fill 引用。

    限定形式 "symbol:trade_id" → 直查目标存在性；
    裸 trade_id → 三分支。定位到 NULL-symbol 历史行只得审计位置。
    """
    if ":" in ref:
        sym, tid = ref.split(":", 1)
        rows = conn.execute(
            "SELECT symbol, fill_id, origin FROM fills"
            " WHERE symbol = ? AND fill_id = ?", (sym, tid)).fetchall()
        if rows:
            return {"resolution": "RESOLVED",
                    "matches": [dict(r) for r in rows],
                    "audit_location_only": False}
        return {"resolution": "DANGLING", "matches": [],
                "audit_location_only": False}
    rows = conn.execute(
        "SELECT symbol, fill_id, origin FROM fills WHERE fill_id = ?",
        (ref,)).fetchall()
    if len(rows) == 0:
        return {"resolution": "DANGLING", "matches": [],
                "audit_location_only": False}
    null_rows = [r for r in rows if r["symbol"] is None]
    sym_rows = [r for r in rows if r["symbol"] is not None]
    if len(sym_rows) == 1 and not null_rows:
        return {"resolution": "RESOLVED",
                "matches": [dict(r) for r in sym_rows],
                "audit_location_only": False}
    if len(null_rows) == 1 and not sym_rows:
        return {"resolution": "UNRESOLVED_NULL_LEGACY",
                "matches": [dict(r) for r in null_rows],
                "audit_location_only": True}  # 定位≠身份
    return {"resolution": "UNRESOLVED_AMBIGUOUS",
            "matches": [dict(r) for r in rows],
            "audit_location_only": True}


def validate_new_ref(conn, ref):
    """新写入引用校验：必须限定形式 + 目标存在（悬空=拒收）。"""
    if ":" not in ref:
        return {"ok": False, "reason": "bare id forbidden for new refs"}
    res = resolve_fill_ref(conn, ref)
    if res["resolution"] != "RESOLVED":
        return {"ok": False,
                "reason": f"dangling or unresolved: {res['resolution']}"}
    return {"ok": True, "reason": ""}


def derivation_check(stored_ctx, recompute_ctx,
                     recomputed_value, stored_value):
    """推导层校验（S2-04 修正：比较两个上下文）。

    - stored_ctx == recompute_ctx → 检查 DEVIATION（数值不等即偏离）
    - stored_ctx != recompute_ctx → 显式重算路径（不判 DEVIATION）
    - 双方均无 ctx（LEGACY）→ 不校验（口径标注）
    """
    if stored_ctx is None and recompute_ctx is None:
        return {"checked": False, "deviation": False,
                "path": "NO_CTX", "reason": "LEGACY row has no ctx"}
    if stored_ctx != recompute_ctx:
        return {"checked": False, "deviation": False,
                "path": "EXPLICIT_RECOMPUTE",
                "reason": f"ctx changed: {stored_ctx!r} -> {recompute_ctx!r}"}
    if recomputed_value != stored_value:
        return {"checked": True, "deviation": True, "path": "CHECK",
                "reason": "same-context recomputation differs"}
    return {"checked": True, "deviation": False, "path": "CHECK",
            "reason": ""}

