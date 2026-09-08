"""E0 Accounting Truth — kernel ledger fills are the capital authority.

Strategy/risk layers must not invent PnL from bar prices. Capital, fees,
drawdown and trade statistics are rebuilt from authoritative fills only.

`accounting_truth.json` is a derivative cache beside the ledger. It is never
authoritative; delete it and rebuild_from_ledger() must reproduce the same
equity / net_pnl / drawdown. `last_applied_fill_id` is an incremental replay
watermark only — full replay (watermark=None) is always the correctness oracle.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.kernel.ledger import Ledger

SCHEMA = "accounting-truth-v1"
CLOSING_ORDER_KINDS = frozenset({"CLOSE", "STOP_LOSS", "TAKE_PROFIT"})


@dataclass
class AccountingSnapshot:
    schema: str = SCHEMA
    initial_capital: float = 0.0
    equity: float = 0.0
    peak_equity: float = 0.0
    drawdown: float = 0.0
    gross_realized_pnl: float = 0.0
    total_fees: float = 0.0
    net_pnl: float = 0.0
    funding_paid: float = 0.0
    fill_count: int = 0
    closed_trade_count: int = 0
    last_fill_id: Optional[str] = None
    last_applied_fill_id: Optional[str] = None
    ledger_path: str = ""
    rebuilt_at: str = ""
    source: str = "ledger_rebuild"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _parse_ts(raw: str) -> float:
    if not raw:
        return 0.0
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except Exception:
        return 0.0


def _net_fill(row: Dict[str, Any]) -> float:
    return float(row.get("realized_pnl") or 0.0) - float(row.get("fee") or 0.0)


def accounting_path_for_ledger(ledger_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(ledger_path)),
                        "accounting_truth.json")


def rebuild_from_ledger(ledger: "Ledger", initial_capital: float) -> AccountingSnapshot:
    """Rebuild capital state exclusively from economic fills."""
    rows = ledger.list_economic_fills_with_context()
    gross = 0.0
    fees = 0.0
    funding = 0.0
    closed_trades = 0
    equity = float(initial_capital)
    peak = equity
    max_dd = 0.0
    last_fill_id = None

    for row in rows:
        gross += float(row.get("realized_pnl") or 0.0)
        fees += float(row.get("fee") or 0.0)
        funding += float(row.get("funding_paid") or 0.0)
        net = _net_fill(row)
        equity += net
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        if row.get("order_kind") in CLOSING_ORDER_KINDS and abs(net) > 1e-12:
            closed_trades += 1
        last_fill_id = row.get("fill_id")

    net = gross - fees - funding
    return AccountingSnapshot(
        initial_capital=float(initial_capital),
        equity=round(equity, 10),
        peak_equity=round(peak, 10),
        drawdown=round(max_dd, 10),
        gross_realized_pnl=round(gross, 10),
        total_fees=round(fees, 10),
        net_pnl=round(net, 10),
        funding_paid=round(funding, 10),
        fill_count=len(rows),
        closed_trade_count=closed_trades,
        last_fill_id=last_fill_id,
        ledger_path=getattr(ledger, "path", ""),
        rebuilt_at=datetime.now(timezone.utc).isoformat(),
    )


def fills_after(rows: List[Dict[str, Any]], last_fill_id: Optional[str]) -> List[Dict[str, Any]]:
    if not last_fill_id:
        return list(rows)
    ids = [r.get("fill_id") for r in rows]
    if last_fill_id not in ids:
        return list(rows)
    idx = ids.index(last_fill_id)
    return rows[idx + 1:]


def persist_accounting(snapshot: AccountingSnapshot, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(snapshot.to_dict(), fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_accounting(path: str) -> Optional[AccountingSnapshot]:
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        data = json.load(fh)
    return AccountingSnapshot(**{k: data[k] for k in asdict(AccountingSnapshot()) if k in data})


def sync_brain_from_snapshot(brain, snapshot: AccountingSnapshot,
                             ledger: "Ledger",
                             last_applied_fill_id: Optional[str] = None) -> str:
    """Apply authoritative capital to brain/risk; replay new closing fills."""
    from aurora.portfolio_brain_v2 import PortfolioBrainV2  # noqa: F401

    rows = ledger.list_economic_fills_with_context()
    new_rows = fills_after(rows, last_applied_fill_id)
    brain.capital = snapshot.equity
    brain.risk_gate.update_capital(snapshot.equity)
    brain.risk_gate.kernel.peak_capital = max(
        snapshot.peak_equity, snapshot.initial_capital)

    if last_applied_fill_id is None:
        brain.capital_objective.capital = snapshot.initial_capital
        brain.capital_objective.peak = snapshot.initial_capital
        brain.capital_objective.returns = []
        brain.capital_objective.equity_curve = [snapshot.initial_capital]
        brain.capital_objective.pnl_history = []
        brain.risk_gate.kernel.pnl_history = []
        brain.risk_gate.kernel.returns_history = []
        brain.risk_gate.kernel.equity_curve = [snapshot.initial_capital]
        brain.risk_gate.kernel.consecutive_losses = 0
        brain.risk_gate.kernel.daily_pnl = 0.0
        brain.risk_gate.kernel.weekly_pnl = 0.0
        replay_rows = rows
    else:
        replay_rows = new_rows

    for row in replay_rows:
        net = _net_fill(row)
        ts = _parse_ts(str(row.get("filled_at") or ""))
        if row.get("order_kind") in CLOSING_ORDER_KINDS:
            brain.risk_gate.record_result(net, timestamp=ts if ts > 0 else None)
            brain.capital_objective.record(net)
        elif row.get("order_kind") == "ENTRY" and abs(net) > 1e-12:
            brain.capital_objective.record(net)

    return snapshot.last_fill_id or last_applied_fill_id or ""
