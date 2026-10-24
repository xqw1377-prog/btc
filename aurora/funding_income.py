"""Funding income ingestion — 幂等资金费入账（W43 复审收紧 v2）。

合同（对应外部复审 2026-10 复验重点）：
- **Decimal 精度**：原始金额字符串原样保留；计算用 Decimal；
  多币种 funding 不得直接相加——合计按 asset 分列。
- **身份冲突**：同稳定事件 ID 以不同内容重放 → FundingIdentityConflict
  告警，绝不静默忽略。
- **窗口完整性语义**：区分"单条成功入账"与"整个时间窗口查全"。
  window_state 只在「全部页成功且游标到达窗口末端」时为 COMPLETE；
  分页失败/中断 → PARTIAL；成功但零事件 → COMPLETE_ZERO_EVENTS
  （与失败严格区分）。迟到事件（时间戳落在已声明 COMPLETE 的窗口内）
  到达 → 窗口状态降级为 PARTIAL_LATE（完整声明作废，不追溯删除事件）。
- 未取到 ≠ 0；无稳定 ID 的行拒收（fail-closed）。
- 本模块纯函数 + 调用方传入存储；不触网、不碰 kernel/ledger；
  SL 触发路径自动接线仍为 E0/D2 待办。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


class FundingIdentityConflict(Exception):
    """同一稳定事件 ID 以不同内容重放——必须告警。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_funding_event_id(row: Dict[str, Any]) -> Optional[str]:
    """交易所稳定事件 ID：tranId 优先，其次 entryId+time，再次
    incomeType+symbol+time 兜底。无稳定键 → None（拒收）。"""
    tran = row.get("tranId")
    if tran not in (None, ""):
        return f"tran:{tran}"
    entry = row.get("entryId")
    ts = row.get("time")
    if entry not in (None, "") and ts not in (None, ""):
        return f"entry:{entry}:{ts}"
    if ts not in (None, "") and row.get("symbol") and row.get("incomeType"):
        return f"inc:{row.get('incomeType')}:{row.get('symbol')}:{ts}"
    return None


def _row_content_key(row: Dict[str, Any]) -> str:
    return "|".join(str(row.get(k) or "") for k in
                    ("symbol", "incomeType", "amount", "time"))


def ingest_funding_events(
    rows: Iterable[Dict[str, Any]],
    store: Dict[str, Dict[str, Any]],
    *,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """幂等吸收 funding 事件行到 store（Decimal 金额 + 原始串保留）。

    同 ID 且内容一致 → duplicates+1（重放忽略）；
    同 ID 且内容不同 → FundingIdentityConflict。
    """
    fetched = fetched_at or _now_iso()
    added = duplicates = rejected = 0
    for row in rows or []:
        event_id = stable_funding_event_id(row)
        if event_id is None:
            rejected += 1
            continue
        raw_amount = row.get("amount")
        try:
            amount_dec = Decimal(str(raw_amount))
        except Exception:
            rejected += 1
            continue
        content = _row_content_key(row)
        existing = store.get(event_id)
        if existing is not None:
            if existing["content_key"] != content:
                raise FundingIdentityConflict(
                    f"funding event {event_id} re-observed with different "
                    f"content: stored={existing['content_key']!r} "
                    f"incoming={content!r}")
            duplicates += 1
            continue
        store[event_id] = {
            "event_id": event_id,
            "symbol": row.get("symbol"),
            "asset": row.get("asset") or row.get("symbol"),
            "income_type": row.get("incomeType"),
            "amount_raw": str(raw_amount),          # 原始精度原样保留
            "amount_dec": amount_dec,               # Decimal，正确精度
            "time": row.get("time"),
            "content_key": content,
            "fetched_at": fetched,
        }
        added += 1
    return {"state": "KNOWN", "added": added,
            "duplicates": duplicates, "rejected": rejected}


def funding_fetch_unavailable(reason: str) -> Dict[str, Any]:
    """拉取失败的标准表达：UNKNOWN ≠ 0，绝不制造零值事件。"""
    return {"state": "UNKNOWN", "reason": reason[:160],
            "added": 0, "duplicates": 0, "rejected": 0}


def funding_totals_by_asset(
    store: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """按资产分列的 Decimal 合计（字符串形式；多币种不相加）。"""
    totals: Dict[str, Decimal] = {}
    for e in store.values():
        asset = str(e.get("asset") or "UNKNOWN")
        totals[asset] = totals.get(asset, Decimal(0)) + e["amount_dec"]
    return {a: str(d) for a, d in sorted(totals.items())}


# ---- 窗口完整性语义 ----

def declare_window(
    window_start_ms: int, window_end_ms: int,
    *, pages_ok: bool, reached_end: bool, empty_response: bool,
) -> Dict[str, Any]:
    """声明一个查询窗口的完整性格。

    COMPLETE               全部页成功 + 游标到达末端（可能有事件）
    COMPLETE_ZERO_EVENTS   同上且确认为空（与失败严格区分）
    PARTIAL                分页失败/中断/未到末端
    """
    if not pages_ok or not reached_end:
        return {"window": [window_start_ms, window_end_ms],
                "state": "PARTIAL"}
    return {"window": [window_start_ms, window_end_ms],
            "state": ("COMPLETE_ZERO_EVENTS" if empty_response
                      else "COMPLETE")}


def apply_late_event_check(
    window_state: Dict[str, Any], event_time_ms: int,
) -> Dict[str, Any]:
    """迟到事件落在已声明 COMPLETE 的窗口内 → 降级 PARTIAL_LATE。"""
    if window_state.get("state") not in ("COMPLETE", "COMPLETE_ZERO_EVENTS"):
        return window_state
    start, end = window_state["window"]
    if start <= event_time_ms <= end:
        out = dict(window_state)
        out["state"] = "PARTIAL_LATE"
        out["late_event_time"] = event_time_ms
        return out
    return window_state


# 兼容旧调用方（单资产场景便捷视图）
def funding_total(store: Dict[str, Dict[str, Any]]) -> Optional[str]:
    totals = funding_totals_by_asset(store)
    if not totals:
        return None
    if len(totals) == 1:
        return next(iter(totals.values()))
    raise ValueError(
        f"multi-asset funding store; use funding_totals_by_asset: {totals}")
