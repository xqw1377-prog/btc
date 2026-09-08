# E1 RISK SEMANTICS

Status: `CLOSED-OFFLINE`  
Date: `2026-09-08`  
Scope: risk semantics only; no exchange writes, no Strategy V2, no backtest.

**E1 冻结风险语义，不证明策略 edge。** `ACCOUNTING TRUTH` 与 `STRATEGY EDGE` 仍须分开表述。

## Contract

```text
FeatureEngine → vol_atr_pct / vol_daily
PortfolioBrainV2 → direction + ATR stop proposal + signal score
RiskGate.approve → FINAL size_pct, stop_loss_pct, take_profit_pct
TradingCycle.execute → qty from authorized intent
ledger income_events → funding_net → equity
```

### Authority matrix

| Decision | Proposer | Final authority |
|---|---|---|
| OPEN/CLOSE/HOLD | Brain | Brain (Gate vetoes OPEN) |
| size_pct | Brain signal score | **RiskGate** (risk-budget ∩ signal ∩ kernel cap) |
| stop_loss_pct / take_profit_pct | Brain ATR distance | **RiskGate** (ATR proposal + bounds; kernel no longer replaces) |
| vol input | FeatureEngine | **vol_atr_pct** (not annualized 1m vol) |
| funding paid | income_events ledger | **accounting_truth rebuild** |
| funding_rate veto | exchange read | **RiskGate assess** |
| funding_incomplete | sync failure | OPEN denied; CLOSE allowed |

### Sizing

Primary: `size_pct = min(risk_budget_pct / stop_loss_pct, signal_size, max_position_pct)`

Default `risk_budget_pct = 0.005` (0.5% equity at risk).

### SL/TP

Brain proposes ATR multiples per regime (`proposed_sl_tp_pct`). RiskGate clamps to
`[MIN_STOP_PCT, MAX_STOP_PCT]` / `[MIN_TP_PCT, MAX_TP_PCT]`. Exchange prices derive
from **authorized** pct only.

### Funding

- `income_events` table (idempotent `FUNDING_FEE` rows)
- `equity = initial + Σ(fill net) + Σ(funding_net signed)`
- `funding_incomplete=True` → OPEN HOLD (not kill)

## Implementation

| Component | Role |
|---|---|
| `aurora/risk_semantics.py` | vol units, ATR SL/TP proposal, risk-budget math, funding read helpers |
| `aurora/risk_gate.py` | final OPEN authority |
| `aurora/portfolio_brain_v2.py` | proposals only; no post-Gate size scaling |
| `aurora/feature_engine.py` | `vol_atr_pct`, `vol_daily` |
| `aurora/kernel/ledger.py` | `income_events`, `sum_funding_net` |
| `aurora/accounting_truth.py` | funding in equity rebuild |
| `aurora/trading_cycle.py` | funding sync, spread/funding_rate wiring |

## Verification

```text
tests/test_risk_semantics.py
Full offline regression (465+ prior + E1 new)
Exchange writes: 0
```

## Explicit non-goals (remain E2+)

- Strategy V2 signal redesign
- Backtest / walk-forward / BTC HODL benchmark
- LIVE / AUTO TESTNET authorization
- Trailing stop exchange sync
