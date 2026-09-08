# E0 ACCOUNTING TRUTH

Status: `CLOSED-OFFLINE`  
Date: `2026-09-08`  
Scope: authoritative capital chain only; no exchange writes, no strategy tuning.

**E0 证明“账开始可信”，不证明策略赚钱。** 两者不得在台账或文档中合并表述。

## Contract

Capital truth flows exclusively from kernel ledger fills:

```text
fills (economic_effect_applied=1)
  → gross_realized_pnl / total_fees / net_pnl
  → equity = initial_capital + net_pnl
  → peak_equity / drawdown
  → PortfolioBrainV2.capital
  → RiskGate / CapitalObjective replay (closing legs only)
```

Forbidden:

- Using bar/K-line price to book CLOSE PnL in production cycle
- Mutating `brain.capital += pnl` from strategy-local price math
- Treating `availableBalance` refresh as realized PnL

## Implementation

| Component | Role |
|---|---|
| `aurora/kernel/ledger.py` | `list_economic_fills_with_context()`, `accounting_aggregate()` |
| `aurora/accounting_truth.py` | rebuild, persist, brain sync |
| `aurora/trading_cycle.py` | `_sync_accounting()` each step; CLOSE no longer books bar PnL |
| `aurora/portfolio_brain_v2.py` | `close_without_pnl()`; OPEN still updates local position view |
| `aurora/kernel_types.py` | `PositionManager.close_without_pnl()` |
| `state/.../accounting_truth.json` | derivative cache beside ledger; ledger remains authority |

Persistence file records `last_applied_fill_id` watermark for incremental risk replay.
**Ledger rebuild is always the correctness oracle**; deleting `accounting_truth.json`
must reproduce identical equity / net_pnl / drawdown.

## Fees / funding / slippage

- **Fees**: included via `fills.fee` in net PnL
- **Funding**: `NOT YET AUTHORITATIVE / E1` — column hook reserved (`funding_paid`
  defaults 0); current `equity` is **not** full economic NAV until E1
- **Slippage**: implicit in fill price vs intent; no separate synthetic slippage ledger in E0

## Verification

```text
tests/test_accounting_truth.py
Full offline regression: 465 passed
Exchange writes: 0
```

Acceptance checks:

1. Entry + close round-trip: `equity = initial + sum(realized_pnl - fee)`
2. Restart: `accounting_truth.json` watermark + ledger rebuild agree
3. `TradingCycle.execute(CLOSE)` with absurd bar price does not move capital
4. `sync_brain_from_exchange(flat)` clears local position without bar-price PnL

## Explicit non-goals (remain E1+)

- Risk-budget sizing — **E1 CLOSED-OFFLINE**（见 E1_RISK_SEMANTICS.md）
- Unified SL/TP semantics — **E1 CLOSED-OFFLINE**（见 E1_RISK_SEMANTICS.md）
- BTC HODL benchmark / backtest harness
- LIVE / AUTO TESTNET authorization
