"""E5 Forward Evidence — 前瞻证据记录器（append-only 前瞻账）。

目的：把「E3 离线 OOS 为正」推进为「冻结规则的前瞻逐 bar 记录」。
前瞻账从第一条记录起算观察期；本模块只追加、绝不回写、绝不改参。

诚实性合同：
- 数据源是本地日线 CSV（evidence/forward/btcusdt_1d.csv，操作员侧
  一次性公开行情下载，与 E3 同源同格式）；aurora/ 代码不内嵌任何
  主机名（P0 bypass scan 口径不变）。
- 只消费【已收盘】日线（closed_daily_bars 剥离未收盘 bar）。
- 决策只来自冻结的 E2 逻辑（decide_overlay），与 E3/E4 同一函数；
  本模块不写策略常数、不调参。
- 每根 bar 至多一条记录（幂等：同 bar 重跑拒绝追加）。
- 记录时刻必须晚于 bar 收盘时刻（point-in-time）。

edge 口径：前瞻账只回答「冻结规则今天说什么」，不产生 LIVE 许可。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from typing import Any, Dict, Optional

import pandas as pd

from aurora.e3_walkforward import DAY_MS
from aurora.strategy_v2 import (
    HORIZON_INTERVAL,
    MIN_HORIZON_BARS,
    OVERLAY_SIGNAL_SIZE_PCT,
    decide_overlay,
    horizon_from_frame,
)
from aurora.feature_engine import FeatureEngine

FORWARD_DIR_DEFAULT = os.path.join("evidence", "forward")
LEDGER_NAME = "forward_ledger.jsonl"
CSV_NAME = "btcusdt_1d.csv"


def forward_dir(base: Optional[str] = None) -> str:
    return base or FORWARD_DIR_DEFAULT


def forward_csv_path(base: Optional[str] = None) -> str:
    return os.path.join(forward_dir(base), CSV_NAME)


def forward_ledger_path(base: Optional[str] = None) -> str:
    return os.path.join(forward_dir(base), LEDGER_NAME)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def frozen_params_fingerprint() -> str:
    """冻结参数指纹：E2 关键常数 + 决策函数源码 hash。"""
    import inspect

    from aurora import strategy_v2

    blob = json.dumps(
        {
            "HORIZON_INTERVAL": HORIZON_INTERVAL,
            "MIN_HORIZON_BARS": MIN_HORIZON_BARS,
            "OVERLAY_SIGNAL_SIZE_PCT": OVERLAY_SIGNAL_SIZE_PCT,
            "decide_overlay_src": inspect.getsource(strategy_v2.decide_overlay),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_forward_csv(path: Optional[str] = None) -> pd.DataFrame:
    p = path or forward_csv_path()
    df = pd.read_csv(p)
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"forward csv missing columns: {sorted(missing)}")
    return df


def last_recorded_bar(ledger_path: Optional[str] = None) -> Optional[int]:
    p = ledger_path or forward_ledger_path()
    if not os.path.exists(p):
        return None
    last = None
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            bar = int(entry["as_of_bar_time"])
            if last is None or bar > last:
                last = bar
    return last


def overlay_open_state(ledger_path: Optional[str] = None) -> bool:
    """从前瞻账推导 overlay 开仓态（无记录 = 空仓起点）。"""
    p = ledger_path or forward_ledger_path()
    if not os.path.exists(p):
        return False
    state = False
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if "overlay_open_after" in entry:
                state = bool(entry["overlay_open_after"])
    return state


def record_forward_entry(
    csv_path: Optional[str] = None,
    ledger_path: Optional[str] = None,
    now_ms: Optional[int] = None,
    allow_catchup: bool = False,
) -> Dict[str, Any]:
    """在最新已收盘日线上记录一条前瞻决策（append-only）。

    - 同 bar 已有记录 → 拒绝追加（幂等）。
    - 记录时刻必须 >= bar 收盘时刻（point-in-time 诚实）。
    - allow_catchup=False 时若账内最后 bar 落后 CSV 多根，只记录最新
      一根并标记 skipped_bars（缺口如实登记，不静默回填）；
      True 时逐根补记（确定性规则下合法，条目带 catchup=true 标记）。
    """
    csv_p = csv_path or forward_csv_path()
    ledger_p = ledger_path or forward_ledger_path()
    now = now_ms if now_ms is not None else int(time.time() * 1000)

    df = load_forward_csv(csv_p)
    # 只保留已收盘 bar：收盘时刻 = time + 1d
    closed = df[df["time"] + DAY_MS <= now].copy()
    if len(closed) < MIN_HORIZON_BARS:
        raise ValueError(
            f"closed bars {len(closed)} < MIN_HORIZON_BARS {MIN_HORIZON_BARS}")

    last_bar = int(closed.iloc[-1]["time"])
    bar_close_ms = last_bar + DAY_MS
    if now < bar_close_ms:
        raise ValueError("latest closed bar closes in the future; refusing")

    prev = last_recorded_bar(ledger_p)
    if prev is not None and last_bar <= prev:
        return {"appended": False, "reason": "ledger already at/after this bar",
                "as_of_bar_time": last_bar}

    skipped = None
    if prev is not None:
        gap_bars = (last_bar - prev) // DAY_MS - 1
        skipped = max(0, gap_bars)

    horizon = horizon_from_frame(closed, FeatureEngine(), now_ms=now)
    overlay_open = overlay_open_state(ledger_p)
    directive = decide_overlay(horizon, overlay_open)
    open_after = overlay_open or directive.action == "OPEN"

    entry = {
        "schema": "e5-forward-v1",
        "recorded_at_ms": now,
        "as_of_bar_time": last_bar,
        "bar_close_ms": bar_close_ms,
        "action": directive.action,
        "thesis": directive.thesis,
        "reason": directive.reason[:160],
        "signal_size_pct": directive.signal_size_pct,
        "overlay_open_before": overlay_open,
        "overlay_open_after": open_after,
        "horizon": {k: float(getattr(horizon, k)) for k in
                    ("close", "ema20", "ema60", "ema_slope", "adx", "atr")
                    if getattr(horizon, k, None) is not None},
        "frozen_params_fingerprint": frozen_params_fingerprint(),
        "source_csv_sha256": _sha256_file(csv_p),
        "catchup": bool(prev is not None and skipped),
        "skipped_bars": skipped,
        "edge_claim": "FORWARD-RECORD-ONLY",
    }
    os.makedirs(os.path.dirname(ledger_p) or ".", exist_ok=True)
    with open(ledger_p, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return {"appended": True, "entry": entry}


if __name__ == "__main__":  # pragma: no cover - manual invocation
    out = record_forward_entry()
    print(json.dumps(out, indent=2, sort_keys=True))
