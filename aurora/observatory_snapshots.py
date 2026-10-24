"""V2 Observatory snapshot builders — read-only, fail-closed.

Each builder returns a dict with capability, status, and payload fields.
PROPOSED modules never masquerade as LIVE.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from aurora.feature_engine import FeatureEngine
from aurora.incident_governance import read_incident_state
from aurora.strategy_v2 import (
    HORIZON_INTERVAL,
    horizon_from_frame,
    HorizonSnapshot,
)
from aurora.eth_btc_allocation_fsm import evaluate_allocation_fsm
from aurora.eth_btc_value_truth import build_eth_btc_value_snapshot
from aurora.decision_observatory import build_decision_observatory_snapshot
from aurora.event_observatory import build_event_observatory_snapshot
from aurora.trend_truth import build_dual_asset_trend_truth

CAP_PARTIAL = "PARTIAL"
CAP_PROPOSED = "PROPOSED"
CAP_UNKNOWN = "UNKNOWN"
CAP_FIXTURE = "FIXTURE"
CAP_D2_HOLD = "D2 HOLD"
CAP_STATIC = "STATIC SNAPSHOT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _klines_to_df(klines: List[dict]) -> Optional[pd.DataFrame]:
    if not klines:
        return None
    df = pd.DataFrame(klines)
    for col in ("open", "high", "low", "close", "volume", "time"):
        if col in df.columns:
            df[col] = df[col].astype(float if col != "time" else "int64")
    return df


def build_trend_quant_snapshot(
    btc_horizon: Optional[HorizonSnapshot] = None,
    *,
    btc_klines_3m: Optional[List[dict]] = None,
    eth_klines_3m: Optional[List[dict]] = None,
    btc_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    eth_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    btc_funding: Optional[Dict[str, Any]] = None,
    eth_funding: Optional[Dict[str, Any]] = None,
    market_meta: Optional[dict] = None,
) -> Dict[str, Any]:
    """P2-A dual-asset HTF trend truth. Legacy 3m-only args folded into by_tf."""
    btc_by_tf = dict(btc_klines_by_tf or {})
    eth_by_tf = dict(eth_klines_by_tf or {})
    if btc_klines_3m and "3m" not in btc_by_tf:
        btc_by_tf["3m"] = btc_klines_3m
    if eth_klines_3m and "3m" not in eth_by_tf:
        eth_by_tf["3m"] = eth_klines_3m
    if btc_horizon and btc_horizon.complete and "1d" not in btc_by_tf:
        # Legacy test path: horizon passed without 1d klines — synthesize minimal 1d
        # from horizon fields is not possible; tests should pass klines_by_tf.
        pass
    return build_dual_asset_trend_truth(
        btc_klines_by_tf=btc_by_tf or None,
        eth_klines_by_tf=eth_by_tf or None,
        btc_funding=btc_funding,
        eth_funding=eth_funding,
        market_meta=market_meta,
    )


def _chart_from_klines(klines: Optional[List[dict]], meta: Optional[dict]) -> Dict[str, Any]:
    if not klines:
        return {"status": "unknown", "klines": [], "metrics": {}}
    df = _klines_to_df(klines)
    if df is None or len(df) == 0:
        return {"status": "unknown", "klines": [], "metrics": {}}
    engine = FeatureEngine()
    feats = engine.get_latest_features(df, exclude_forming=True)
    last = klines[-1]
    status = (meta or {}).get("status", "ok")
    return {
        "status": status,
        "klines": klines[-80:],
        "price": float(last.get("close") or 0),
        "metrics": {
            "price": f"${float(last.get('close') or 0):,.2f}",
            "ema20": f"{feats.get('ema20', 0):,.2f}" if feats.get("ema20") else "—",
            "ema60": f"{feats.get('ema60', 0):,.2f}" if feats.get("ema60") else "—",
            "adx": f"{feats.get('adx', 0):.1f}" if feats.get("adx") else "—",
        },
    }


def build_eth_btc_snapshot(
    *,
    btc_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    eth_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    market_meta: Optional[dict] = None,
    now_ms: Optional[int] = None,
    btc_trend: Optional[Dict[str, Any]] = None,
    eth_trend: Optional[Dict[str, Any]] = None,
    relative_strength: Optional[Dict[str, Any]] = None,
    previous_allocation: Optional[Dict[str, Any]] = None,
    has_eth_allocation: bool = False,
) -> Dict[str, Any]:
    """P2-B.1 value truth + P2-B.2 allocation FSM (read-only · no execution)."""
    value = build_eth_btc_value_snapshot(
        btc_klines_by_tf=btc_klines_by_tf,
        eth_klines_by_tf=eth_klines_by_tf,
        market_meta=market_meta,
        now_ms=now_ms,
    )
    allocation = evaluate_allocation_fsm({
        "value": value,
        "btc_trend": btc_trend or {},
        "eth_trend": eth_trend or {},
        "relative_strength": relative_strength or {},
        "previous_state": previous_allocation or {},
        "has_eth_allocation": has_eth_allocation,
    })
    return {
        **value,
        "allocation": allocation,
        "allocation_state": allocation["state"],
        "signal": allocation["allocation_signal"],
    }


def build_event_snapshot(
    *,
    items: Optional[List[dict]] = None,
    official_sources_connected: bool = False,
    source_fetch_status: str = "not_connected",
    btc_trend: Optional[Dict[str, Any]] = None,
    eth_trend: Optional[Dict[str, Any]] = None,
    market_freshness: str = "ok",
    as_of_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """P2-C.3 — C1 + C2 → observatory event bundle (not static placeholder)."""
    return build_event_observatory_snapshot(
        official_sources_connected=official_sources_connected,
        source_fetch_status=source_fetch_status,
        fixture_pipeline=items,
        btc_trend=btc_trend,
        eth_trend=eth_trend,
        market_freshness=market_freshness,
        as_of_ms=as_of_ms,
    )


def build_decision_snapshot(
    trend: Dict[str, Any],
    exchange: Dict[str, Any],
    *,
    eth_btc: Optional[Dict[str, Any]] = None,
    event_bundle: Optional[Dict[str, Any]] = None,
    account_meta: Optional[Dict[str, Any]] = None,
    authoritative_current: Optional[Dict[str, Any]] = None,
    previous_decision: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """P3-R2 — project evaluate_decision() into observatory.decision (mirror only upstream)."""
    return build_decision_observatory_snapshot(
        trend_quant=trend,
        eth_btc=eth_btc or {},
        event_bundle=event_bundle or build_event_snapshot(),
        exchange=exchange,
        account_meta=account_meta,
        authoritative_current=authoritative_current,
        previous_decision=previous_decision,
        **kwargs,
    )


def build_exchange_observation(
    account_data: Dict[str, Any],
    risk_data: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    status = meta.get("status", "unknown")
    positions = account_data.get("positions") or []
    pos_state = account_data.get("positionsState", "UNKNOWN")
    if status != "ok":
        pos_state = "UNKNOWN" if status == "unknown" else pos_state

    perp = "FLAT"
    leverage = "—"
    if positions:
        p = positions[0]
        perp = f"{p.get('side', '—')} {p.get('size', '—')} · {p.get('leverage', '—')}x"
        leverage = f"{p.get('leverage', '—')}x"

    assets = account_data.get("assets") or []
    wallet = {"usdt": "—", "btc": "—", "eth": "—"}
    for a in assets:
        sym = (a.get("asset") or "").upper()
        bal = a.get("availableBalance")
        if sym == "USDT":
            wallet["usdt"] = f"{float(bal):,.2f}" if bal is not None else "—"
        elif sym == "BTC":
            wallet["btc"] = f"{float(bal):,.6f}" if bal is not None else "—"
        elif sym == "ETH":
            wallet["eth"] = f"{float(bal):,.4f}" if bal is not None else "—"

    risk_status = risk_data.get("status", "UNKNOWN")

    return {
        "capability": CAP_PARTIAL,
        "status": status,
        "as_of": meta.get("updatedAt") or _now_iso(),
        "wallet": wallet,
        "actual_mix": {
            "capability": CAP_PARTIAL,
            "source": "EXCHANGE_OBSERVATION",
            "values": wallet,
            "percent": None,
            "note": "Percentage requires price truth; raw wallet balances only",
        },
        "target_mix": {
            "capability": CAP_PROPOSED,
            "source": "P3 HOLD",
            "percent": None,
            "note": "Target allocation not available until P3",
        },
        "perp": perp,
        "leverage": leverage,
        "positions": pos_state,
        "risk_status": {
            "capability": CAP_PARTIAL,
            "label": "RISK PROXY",
            "value": "NOT AUTHORITATIVE",
            "source": "EXCHANGE_OBSERVATION",
            "raw_status": risk_status,
            "note": "RiskGate truth not connected",
        },
        "risk_budget": None,
        "equity_usdt": account_data.get("equity"),
        "unrealized_pnl": account_data.get("unrealizedPnl"),
        "ledger_reconciled": False,
        "warning": None if status == "ok" else "Exchange observation degraded · cannot infer flat",
    }


def build_accounting_snapshot(ledger_search_root: Optional[str] = None) -> Dict[str, Any]:
    """Load offline accounting_truth.json if present; never invent BTC NAV."""
    root = ledger_search_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"
    )
    paths = glob.glob(os.path.join(root, "**", "accounting_truth.json"), recursive=True)
    if not paths:
        return {
            "capability": CAP_D2_HOLD,
            "status": "unknown",
            "as_of": _now_iso(),
            "nav_btc": None,
            "hodl_btc": None,
            "excess_btc": None,
            "equity_usdt": None,
            "note": "D2 HOLD · no accounting_truth on disk · ≠ BTC NAV authoritative",
        }
    try:
        with open(paths[0], encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return {
            "capability": CAP_UNKNOWN,
            "status": "unknown",
            "as_of": _now_iso(),
            "note": f"accounting_truth unreadable: {type(exc).__name__}",
        }
    return {
        "capability": CAP_D2_HOLD,
        "status": "stale",
        "as_of": data.get("rebuilt_at") or _now_iso(),
        "nav_btc": None,
        "hodl_btc": None,
        "excess_btc": None,
        "equity_usdt": data.get("equity"),
        "net_pnl": data.get("net_pnl"),
        "drawdown": data.get("drawdown"),
        "fill_count": data.get("fill_count"),
        "note": "E0 offline cache · USDT equity · BTC NAV not authoritative",
    }


def build_governance_snapshot(
    *,
    mode: str,
    execute_authorized: bool = False,
) -> Dict[str, Any]:
    incident = read_incident_state()
    kill = incident.get("status", "UNKNOWN")
    return {
        "capability": CAP_PARTIAL,
        "as_of": _now_iso(),
        "source_commit": os.environ.get("AURORA_SOURCE_COMMIT", "unknown"),
        "incident_lock": "INCIDENT_LOCKED" if kill == "ACTIVE" else "CLEAR",
        "kill": kill,
        "execute_authorized": execute_authorized,
        "execution_qualified": False,
        "auto_testnet": "DENIED",
        "live": "NO_GO",
        "mode": mode,
    }


def build_observatory_bundle(
    *,
    btc_horizon: Optional[HorizonSnapshot] = None,
    btc_klines_3m: Optional[List[dict]] = None,
    eth_klines_3m: Optional[List[dict]] = None,
    btc_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    eth_klines_by_tf: Optional[Dict[str, List[dict]]] = None,
    btc_funding: Optional[Dict[str, Any]] = None,
    eth_funding: Optional[Dict[str, Any]] = None,
    account_data: Dict[str, Any],
    risk_data: Dict[str, Any],
    account_meta: Dict[str, Any],
    market_meta: Dict[str, Any],
    mode: str,
    execute_authorized: bool = False,
    event_items: Optional[List[dict]] = None,
    official_sources_connected: bool = False,
    source_fetch_status: str = "not_connected",
    ledger_root: Optional[str] = None,
    previous_eth_btc_allocation: Optional[Dict[str, Any]] = None,
    has_eth_allocation: bool = False,
) -> Dict[str, Any]:
    trend = build_trend_quant_snapshot(
        btc_horizon,
        btc_klines_3m=btc_klines_3m,
        eth_klines_3m=eth_klines_3m,
        btc_klines_by_tf=btc_klines_by_tf,
        eth_klines_by_tf=eth_klines_by_tf,
        btc_funding=btc_funding,
        eth_funding=eth_funding,
        market_meta=market_meta,
    )
    exchange = build_exchange_observation(account_data, risk_data, account_meta)
    eth_btc = build_eth_btc_snapshot(
        btc_klines_by_tf=btc_klines_by_tf,
        eth_klines_by_tf=eth_klines_by_tf,
        market_meta=market_meta,
        btc_trend=trend.get("btc"),
        eth_trend=trend.get("eth"),
        relative_strength=trend.get("relative_strength"),
        previous_allocation=previous_eth_btc_allocation,
        has_eth_allocation=has_eth_allocation,
    )
    event_snap = build_event_snapshot(
        items=event_items,
        official_sources_connected=official_sources_connected,
        source_fetch_status=source_fetch_status,
        btc_trend=trend.get("btc"),
        eth_trend=trend.get("eth"),
    )
    decision = build_decision_snapshot(
        trend,
        exchange,
        eth_btc=eth_btc,
        event_bundle=event_snap,
        account_meta=account_meta,
    )
    return {
        "schema": "observatory-v1",
        "as_of": _now_iso(),
        "governance": build_governance_snapshot(mode=mode, execute_authorized=execute_authorized),
        "trend_quant": trend,
        "eth_btc": eth_btc,
        "event": event_snap,
        "decision": decision,
        "exchange_observation": exchange,
        "accounting": build_accounting_snapshot(ledger_root),
    }


def fetch_klines_df(client: Any, symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(
        klines,
        columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ],
    )
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def fetch_horizon_daily(client: Any, symbol: str = "BTCUSDT") -> HorizonSnapshot:
    from aurora.strategy_v2 import closed_daily_bars

    df = fetch_klines_df(client, symbol, HORIZON_INTERVAL, 1500)
    if df is None:
        return HorizonSnapshot(interval=HORIZON_INTERVAL, complete=False, reason="HTF fetch failed")
    closed = closed_daily_bars(df)
    return horizon_from_frame(closed)


def klines_records(df: pd.DataFrame, tail: int = 80) -> List[dict]:
    if df is None or len(df) == 0:
        return []
    rows = []
    for _, row in df.tail(tail).iterrows():
        rows.append({
            "time": int(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })
    return rows
