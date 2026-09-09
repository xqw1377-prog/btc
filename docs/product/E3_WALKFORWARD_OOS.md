# E3 WALK-FORWARD / OOS

Status: `CLOSED-OFFLINE`  
Date: `2026-09-09`  
Scope: verdict-only simulation of frozen Strategy V2 vs BTC HODL.

**E3 只裁决，不调参。** 看到 OOS 结果之后禁止回写 E2 / E1 常数。
本包已跑完本地日线样本；**未**因此改 `strategy_v2` / `risk_semantics`。

## Question

> After fees, funding and slippage, does frozen Strategy V2 accumulate
> more BTC than simply holding BTC — and is that gap not a single month,
> single regime, or handful of trades?

## Freeze

```text
E2 参数 / 规则先冻结
→ 再打开 OOS
→ OOS 只用于裁决，不用于调参
```

Imported live from E2/E1 (`OVERLAY_SIGNAL_SIZE_PCT`, `DEFAULT_RISK_BUDGET_PCT`,
HTF rules). Changing them in an E3 `FrozenCosts` instance raises.

## Economics

```text
HODL          = 1.0 BTC (numeraire benchmark)
CORE          = 1.0 BTC held throughout
OVERLAY       = optional USDT-margined LONG
strategy_btc  = 1.0 + overlay_usdt / price
excess_btc    = strategy_btc − 1.0
```

No look-ahead: decide on closed bar `t`, fill at `t+1` open.
Forming (unclosed) daily bars are dropped before simulation.
Costs (frozen, not fitted): taker 4 bps, slip 5 bps, funding = 8h rate × 3 / day.
Funding-rate veto uses E1 `max_funding_rate_pct`.

## Robustness gates for EDGE_PASS_OFFLINE

All required:

- `excess_btc > 0`
- `n_trades >= 10`
- share of calendar-year folds with positive excess `>= 50%`
- no single month `> 50%` of positive excess
- no single trade `> 40%` of positive trade PnL

Otherwise `NO-EVIDENCE` (negative excess or concentrated / thin sample).

`EDGE_PASS_OFFLINE` still ≠ LIVE and ≠ AUTO TESTNET.

## Local-CSV verdict (2026-09-09)

Source: `evidence/e3/btcusdt_1d.csv`。装入时剔除尚未收盘的日线（形成中 bar
不得参与决策）。本次有效样本：2022-08-02 → 2026-09-08 UTC。
Harness 无主网 host。书面真源：`evidence/e3/verdict.json`。

```text
verdict              EDGE_PASS_OFFLINE
edge_claim           OFFLINE-OOS-ONLY
hodl_btc             1.0
strategy_btc         1.0338021862
excess_btc           +0.0338021862
n_trades             58
fees_usdt            245.26
funding_usdt         20.60
slippage_usdt        306.58
positive_fold_frac   0.80   (4/5 calendar years)
2022 excess          −0.00662   (n_trades=1)   ← 负折，门仍过是因为占比门槛是 ≥50%
2023 excess          +0.02068   (17)
2024 excess          +0.00895   (26)
2025 excess          +0.00682   (12)
2026 excess          +0.00533   (2；年至 9-08)
max_month_share      0.186
max_trade_share      0.083
```

这不是 LIVE 许可，也不是调参许可。2022 年为负超额；样本前段 funding 列为 0
的日期不得被解读成「当时资金费真为零」。

## Implementation

| Component | Role |
|---|---|
| `aurora/e3_walkforward.py` | simulator + verdict; **no exchange hosts** |
| `tests/test_e3_walkforward.py` | freeze, look-ahead, HODL, cost drag, gates |
| `evidence/e3/btcusdt_1d.csv` | optional local daily OHLC (+ funding_rate) |
| `evidence/e3/verdict.json` | optional local-CSV run |

Public history is supplied as a local CSV (`evidence/e3/btcusdt_1d.csv` or
`E3_OHLC_CSV`). The harness never embeds mainnet hosts (P0 bypass scan).

## Explicit non-goals

- Retuning E2 after seeing numbers
- TESTNET / LIVE execution
- Claiming STRATEGY EDGE from synthetic tests alone
