"""Funding income ingestion — 幂等资金费入账（外部周报 2026-W43 #4 吸收）。

Freqtrade #13679 教训：交易所止损平仓路径可能漏拉 funding，重算后把
资金费归零。吸收为合同：

- 资金费按交易所稳定事件 ID（income 的 tranId/entryId）幂等入账；
  重复回放（同 ID 再次到达、迟到 funding、重启后重放）不重复记账。
- 拉取失败/无数据 → state=UNKNOWN，events 保持原样；**绝不把
  未取到当作 0**（0 是一个必须由真实事件支撑的值）。
- 平仓路径（含交易所止损触发）与 funding 拉取解耦：无论仓位如何
  关闭，持仓期内的 funding 事件仍须独立拉取并入账。

本模块是纯函数 + 显式存储（调用方传入 dict 存储），不触网、不碰
kernel/ledger 文件；运行时接线（SL 触发恢复路径自动调用）登记为
E0/D2 待办，不在此静默宣称已接。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_funding_event_id(row: Dict[str, Any]) -> Optional[str]:
    """交易所稳定事件 ID：tranId 优先，其次 entryId+timestamp 组合。"""
    tran = row.get("tranId")
    if tran not in (None, ""):
        return f"tran:{tran}"
    entry = row.get("entryId")
    ts = row.get("time")
    if entry not in (None, "") and ts not in (None, ""):
        return f"entry:{entry}:{ts}"
    if ts not in (None, "") and row.get("symbol") and row.get("incomeType"):
        # FUTURES funding 常无 tranId 的兜底键：symbol+type+time
        return (f"inc:{row.get('incomeType')}:{row.get('symbol')}:{ts}")
    return None


def ingest_funding_events(
    rows: Iterable[Dict[str, Any]],
    store: Dict[str, Dict[str, Any]],
    *,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """幂等吸收 funding 事件行到 store。

    rows: 交易所 income 接口原始行（symbol/incomeType=|FUNDING_FEE|/
          amount/time/tranId/entryId...）。None 或异常由调用方先处理——
          本函数只接受"确实拉到的行"。
    返回 {"state": "KNOWN", "added": n, "duplicates": n}。
    无稳定 ID 的行拒绝入账并计入 rejected（fail-closed，不猜）。
    """
    fetched = fetched_at or _now_iso()
    added = duplicates = rejected = 0
    for row in rows or []:
        event_id = stable_funding_event_id(row)
        if event_id is None:
            rejected += 1
            continue
        if event_id in store:
            duplicates += 1
            continue
        try:
            amount = float(row.get("amount") or 0.0)
        except (TypeError, ValueError):
            rejected += 1
            continue
        store[event_id] = {
            "event_id": event_id,
            "symbol": row.get("symbol"),
            "income_type": row.get("incomeType"),
            "amount": amount,  # 正=收，负=付（交易所口径）
            "time": row.get("time"),
            "fetched_at": fetched,
        }
        added += 1
    return {"state": "KNOWN", "added": added,
            "duplicates": duplicates, "rejected": rejected}


def funding_fetch_unavailable(reason: str) -> Dict[str, Any]:
    """拉取失败的标准表达：UNKNOWN ≠ 0，绝不制造零值事件。"""
    return {"state": "UNKNOWN", "reason": reason[:160],
            "added": 0, "duplicates": 0, "rejected": 0}


def funding_total(store: Dict[str, Dict[str, Any]]) -> Optional[float]:
    """已知事件合计；store 为空且从未成功拉取 → 调用方应展示 UNKNOWN。"""
    if not store:
        return None
    return round(sum(e["amount"] for e in store.values()), 10)
