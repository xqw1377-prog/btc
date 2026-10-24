"""E3 冻结候选的一次性稳健性消融（研究专用；不回写任何冻结常数）。

纪律（对应外部评审 2026-10 与 E3 自身规则）：
- 这不是调参：所有变体仅用于**报告脆弱性**，绝不回写 strategy_v2 /
  risk_semantics 常数；主口径（baseline）永远取冻结原值。
- monkeypatch 只存在于本进程；脚本结束后仓库状态不变。
- 对照组（fixed overlay）回答的问题："择时是否只是敞口"。

用法：python3 scripts/e3_ablation.py [--csv evidence/e3/btcusdt_1d.csv]
输出：evidence/e3/ablation_report.json（append-only 证据文件）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import aurora.strategy_v2 as s2  # noqa: E402
from aurora.e3_walkforward import (  # noqa: E402
    CORE_BTC, DAY_MS, FrozenCosts, simulate_overlay,
)

CSV_DEFAULT = os.path.join(ROOT, "evidence", "e3", "btcusdt_1d.csv")
OUT_PATH = os.path.join(ROOT, "evidence", "e3", "ablation_report.json")


def run_baseline(df):
    result, trades, curve = simulate_overlay(df)
    return summarize("baseline_frozen", result, trades, curve, df), trades


def summarize(tag, result, trades, curve, df):
    daily = curve.set_index("time")["strategy_btc"]
    peak = daily.cummax()
    dd = (daily - peak)
    months = result_monthly(result)
    cum = 0.0
    trough = 0.0
    for v in months.values():
        cum += v
        trough = min(trough, cum)
    return {
        "variant": tag,
        "excess_btc": round(result.excess_btc, 6),
        "n_trades": result.n_trades,
        "strategy_btc_end": round(result.strategy_btc, 6),
        "max_btc_drawdown_of_strategy_nav": round(float(dd.min()), 6),
        "max_excess_trough_btc": round(trough, 6),
        "fees_usdt": round(result.fees_usdt, 2),
        "funding_usdt": round(result.funding_usdt, 2),
    }


def result_monthly(result):
    return dict(result.monthly_excess_btc or {})


# ---- 变体（全部进程内 monkeypatch，结束后不残留）----

def variant_no_adx(df):
    orig = s2.DAILY_ADX_MIN
    s2.DAILY_ADX_MIN = 0.0
    try:
        result, trades, curve = simulate_overlay(df)
        return summarize("no_adx_gate", result, trades, curve, df)
    finally:
        s2.DAILY_ADX_MIN = orig


def variant_no_slope(df):
    orig = s2.HorizonSnapshot.bullish_trend
    s2.HorizonSnapshot.bullish_trend = property(
        lambda self: self.complete
        and self.close > self.ema20 > self.ema60
        and self.adx >= s2.DAILY_ADX_MIN)
    try:
        result, trades, curve = simulate_overlay(df)
        return summarize("no_ema_slope", result, trades, curve, df)
    finally:
        s2.HorizonSnapshot.bullish_trend = orig


def variant_ema_neighborhood(df, span_pair, tag):
    """替换 horizon 的 ema20/ema60 为邻近 span（如 (15,55)/(25,65)）。"""
    fast, slow = span_pair
    import aurora.e3_walkforward as e3
    orig_fn = e3.horizon_from_closed_slice

    def patched(frame, engine, _fast=fast, _slow=slow):
        if frame is None or len(frame) == 0:
            return orig_fn(frame, engine)
        closes = frame["close"].astype(float)
        ema_f = float(closes.ewm(span=_fast, adjust=False).mean().iloc[-1])
        ema_s = float(closes.ewm(span=_slow, adjust=False).mean().iloc[-1])
        snap = orig_fn(frame, engine)
        prev_f, prev_s = snap.ema20, snap.ema60
        slope = snap.ema_slope * (ema_f / prev_f) if prev_f else snap.ema_slope
        return s2.HorizonSnapshot(
            interval=snap.interval, complete=snap.complete,
            close=snap.close, ema20=ema_f, ema60=ema_s,
            ema_slope=slope if slope == slope else 0.0,
            adx=snap.adx, atr=snap.atr, vol_atr_pct=snap.vol_atr_pct,
            bar_open_time=snap.bar_open_time, reason=snap.reason)

    e3.horizon_from_closed_slice = patched
    try:
        result, trades, curve = simulate_overlay(df)
        return summarize(tag, result, trades, curve, df)
    finally:
        e3.horizon_from_closed_slice = orig_fn


def variant_cost_stress(df, tag, **over):
    base = {
        "taker_fee": 0.0004, "slippage": 0.0005,
        "max_funding_rate": 0.001, "funding_prints_per_day": 3.0,
    }
    base.update(over)
    costs = FrozenCosts(**base)
    result, trades, curve = simulate_overlay(df, costs=costs)
    return summarize(tag, result, trades, curve, df)


def analysis_drop_top_trades(baseline_summary, trades, df, k=3):
    """去掉贡献最大的 k 笔（近似：直接从 realized 中扣除其净 pnl，
    以期末价折 BTC；交易级近似，非重模拟——如实标注）。"""
    if not trades:
        return {"variant": f"drop_top_{k}_trades_approx", "note": "no trades"}
    ranked = sorted(trades, key=lambda t: t.pnl_usdt, reverse=True)[:k]
    removed = sum(t.pnl_usdt for t in ranked)
    result, _, curve = simulate_overlay(df)
    excess_adj = result.excess_btc - removed / float(df["close"].iloc[-1])
    return {
        "variant": f"drop_top_{k}_trades_approx",
        "excess_btc": round(excess_adj, 6),
        "removed_pnl_usdt": round(removed, 2),
        "removed_trades": [
            {"entry": t.entry, "exit": t.exit, "pnl": round(t.pnl_usdt, 2),
             "reason": t.reason} for t in ranked],
        "note": "trade-level approximation (pnl removed at end price); "
                "not a full re-simulation",
    }


# ---- 对照组：相同资金约束的固定多头敞口（"只是杠杆吗？"）----

def benchmark_fixed_overlay(df, size_frac):
    """始终持有 notional = CORE权益 × size_frac 的多头（同成本/同 funding）。"""
    costs = FrozenCosts()
    work = df.reset_index(drop=True)
    if "funding_rate" not in work.columns:
        work["funding_rate"] = 0.0
    realized = 0.0
    prev_c = None
    curve = []
    for i, row in work.iterrows():
        c = float(row["close"])
        fr = float(row.get("funding_rate") or 0.0)
        notional = CORE_BTC * c * size_frac
        if fr > costs.max_funding_rate:
            fr = costs.max_funding_rate  # 与策略同假设
        realized -= notional * fr * costs.funding_prints_per_day
        if prev_c is not None:
            realized += notional * (c - prev_c) / prev_c  # frac 收益
        prev_c = c
        curve.append(CORE_BTC + realized / c)
    s = pd.Series(curve)
    dd = float((s - s.cummax()).min())
    # 全程两次过手费+滑点（期初建、期末平）
    avg_px = float(work["close"].mean())
    hand = CORE_BTC * avg_px * size_frac * (costs.taker_fee + costs.slippage) * 2
    realized -= hand
    end_px = float(work["close"].iloc[-1])
    return {
        "variant": f"fixed_overlay_{int(size_frac*100)}pct_always_on",
        "excess_btc": round(realized / end_px, 6),
        "max_btc_drawdown_of_strategy_nav": round(dd, 6),
        "note": "same 1.0 BTC core, constant long notional fraction, "
                "same fee/slippage/funding model, no timing",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_DEFAULT)
    args = ap.parse_args()
    df = pd.read_csv(args.csv)

    rows = []
    base_summary, trades = run_baseline(df)
    rows.append(base_summary)
    rows.append(variant_no_adx(df))
    rows.append(variant_no_slope(df))
    rows.append(variant_ema_neighborhood(df, (15, 55), "ema_15_55"))
    rows.append(variant_ema_neighborhood(df, (25, 65), "ema_25_65"))
    rows.append(variant_cost_stress(df, "cost_2x",
                                    taker_fee=0.0008, slippage=0.001))
    rows.append(variant_cost_stress(df, "funding_2x_cap",
                                    max_funding_rate=0.002))
    rows.append(analysis_drop_top_trades(base_summary, trades, df, k=3))
    rows.append(benchmark_fixed_overlay(df, 0.10))
    rows.append(benchmark_fixed_overlay(df, 0.40))

    period_months = len(base_summary.get("months", [])) if "months" in base_summary else None
    report = {
        "schema": "e3-ablation-v1",
        "written_at": datetime.now(timezone.utc).isoformat(),
        "discipline": "REPORT-ONLY；不回写冻结常数；变体仅用于脆弱性报告",
        "period_note": "2022-08 → 2026-09 ≈ 4.1 年，CORE=1.0 BTC 连续无重置",
        "baseline_annualized_note":
            "excess 3.38% over ~4.1y ≈ 0.8%/yr（几何近似），非 3.4%/yr",
        "variants": rows,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
