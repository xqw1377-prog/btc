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

# 交易所事实六元组 + symbol（身份与比较字段集唯一来源）
FACT_FIELDS = ("symbol", "side", "qty", "price", "fee", "fee_asset")

MAX_FIELD_CMP = 10000  # Decimal 数值位数支持上限（与 S1 _PREC_CAP 同源）


class FillIdentityConflict(Exception):
    """同完整身份键 + 事实内容不同（身份层冲突）。"""


class DerivationDeviation(Exception):
    """同推导上下文重算不一致（推导层，非身份冲突）。"""


def parse_finite(raw: Optional[str]) -> Optional[Decimal]:
    """原始串 → 有限 Decimal；None/不可解析/非有限 → None（=UNKNOWN）。"""
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


def _field_state(raw: Optional[str]) -> str:
    return "KNOWN" if parse_finite(raw) is not None else "UNKNOWN"


def fill_content_mismatch(stored: Dict[str, Any],
                          incoming: Dict[str, Any]) -> Dict[str, Any]:
    """唯一身份校验器：同 (symbol, trade_id) 下比较事实字段。

    输入行须含 FACT_FIELDS 对应的 *_raw 值（EVENT）或 REAL+LEGACY
    标注。返回 MatchReport：
      {"verdict": "MATCH"|"MISMATCH"|"INCOMPLETE",
       "conflict_fields": [...],   # MISMATCH 时不一致字段
       "unverifiable_fields": [...], # INCOMPLETE 时不可证实字段
       "notes": [...]}
    - MATCH       → 两入口判 DUPLICATE（幂等）
    - MISMATCH    → 两入口判 IDENTITY_CONFLICT（FillIdentityConflict）
    - INCOMPLETE  → 两入口判 IDENTITY_UNRESOLVED（隔离告警，不收养）
    """
    conflict: List[str] = []
    unverifiable: List[str] = []
    notes: List[str] = []
    for f in FACT_FIELDS:
        s_raw, i_raw = stored.get(f), incoming.get(f)
        # 非数值字段（symbol/side/fee_asset）：字符串精确比较
        if f in ("symbol", "side", "fee_asset"):
            s_v = s_raw if s_raw not in (None, "") else None
            i_v = i_raw if i_raw not in (None, "") else None
            if s_v is None or i_v is None:
                if not (s_v is None and i_v is None):
                    unverifiable.append(f)
                continue
            if str(s_v) != str(i_v):
                conflict.append(f)
            continue
        # 数值字段（qty/price/fee）：原始串 Decimal 数值相等
        s_d, i_d = parse_finite(s_raw), parse_finite(i_raw)
        if s_d is None or i_d is None:
            unverifiable.append(f)  # 含双 UNKNOWN：字段不可证实
            continue
        if s_d != i_d:
            conflict.append(f)
    if conflict:
        return {"verdict": "MISMATCH", "conflict_fields": conflict,
                "unverifiable_fields": [], "notes": notes}
    if unverifiable:
        return {"verdict": "INCOMPLETE", "conflict_fields": [],
                "unverifiable_fields": unverifiable, "notes": notes}
    return {"verdict": "MATCH", "conflict_fields": [],
            "unverifiable_fields": [], "notes": notes}


def derivation_check(stored_ctx: Optional[str],
                     recomputed_value: Decimal,
                     stored_value: Decimal) -> Dict[str, Any]:
    """推导层校验：同上下文重算不一致 = DERIVATION_DEVIATION。

    - stored_ctx 为 None（LEGACY 行无上下文）→ 不校验（口径标注）
    - 数值不等（Decimal 有限域）→ deviation=true（非身份冲突）
    """
    if stored_ctx is None:
        return {"checked": False, "deviation": False,
                "reason": "LEGACY row has no derivation_ctx"}
    if recomputed_value != stored_value:
        return {"checked": True, "deviation": True,
                "reason": "same-context recomputation differs"}
    return {"checked": True, "deviation": False, "reason": ""}


def order_symbol_for(conn, client_order_id: str) -> Optional[str]:
    """订单归属 symbol：经 orders → intents.symbol 解析。"""
    row = conn.execute(
        "SELECT i.symbol FROM orders o JOIN intents i"
        " ON o.intent_id = i.intent_id"
        " WHERE o.client_order_id = ?", (client_order_id,)).fetchone()
    return row[0] if row else None


def check_attribution(conn, fill_symbol: Optional[str],
                      client_order_id: str) -> Dict[str, Any]:
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


# ---- 引用消解（R1/R2 裸 ID 三分支 + 限定引用目标存在性） ----

def resolve_fill_ref(conn, ref: str) -> Dict[str, Any]:
    """消解一条 fill 引用。

    限定形式 "symbol:trade_id" → 直查目标存在性；
    裸 trade_id → 三分支（唯一 symbol 命中 / 唯一 NULL 行 / 多命中告警）。
    返回 {"resolution": "RESOLVED"|"UNRESOLVED_NULL_LEGACY"|
                          "UNRESOLVED_AMBIGUOUS"|"DANGLING",
          "matches": [...], "audit_location_only": bool}
    定位到 NULL-symbol 历史行只得审计位置（定位≠身份）。
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


def validate_new_ref(conn, ref: str) -> Dict[str, Any]:
    """新写入引用校验：必须限定形式 + 目标存在（格式合规但悬空=拒收）。"""
    if ":" not in ref:
        return {"ok": False, "reason": "bare id forbidden for new refs"}
    res = resolve_fill_ref(conn, ref)
    if res["resolution"] != "RESOLVED":
        return {"ok": False, "reason": f"dangling or unresolved: "
                                       f"{res['resolution']}"}
    return {"ok": True, "reason": ""}
