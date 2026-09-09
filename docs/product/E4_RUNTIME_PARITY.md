# E4 RUNTIME PARITY

Status: `CLOSED-OFFLINE`  
Date: `2026-09-09`  
Scope: production overlay thesis vs frozen E3 on the same closed daily bars.

**E4 只证明裁决对等，不调参，不写交易所。**

## Question

> Given the same already-closed daily bars, does the armed decision path
> emit the same overlay OPEN/CLOSE thesis as `e3_walkforward` — even when
> the live 1d frame still carries a forming bar?

## Freeze

```text
E2 参数 / 规则不改（ADX 门槛、overlay size、risk-budget）
E3 裁决数字不改写
PAPER 仍禁止实例化 TradingCycle
FakeExchange + writes disabled 证明循环接线
AUTO TESTNET / LIVE = 不在本包
```

## What was wrong

Production `horizon_from_frame` blindly dropped the last 1d row, so a
closed-only frame was always one day behind E3. Daily fetch limit was 120,
so EMA/ADX lookback could not match E3's window.

## Contract

```text
same closed daily prefix
  + optional forming next bar
→ same horizon close / ema / adx / atr
→ same decide_overlay action
```

OPEN is one-way after RiskGate:

- production **must not** overlay-OPEN when E3/decide_overlay says HOLD
- production **may** HOLD when E3 would OPEN (funding / capital / kill)
- HTF CLOSE still risk-reducing; 1m signals cannot arm overlay

PAPER cannot run `TradingCycle` (P0). Parity of the cycle is proven with
`FakeExchange`, `RunMode.TESTNET` flag, and `submit_log` empty.

## Implementation

| Component | Role |
|---|---|
| `aurora/strategy_v2.py` | `closed_daily_bars` by clock; `HORIZON_FETCH_LIMIT=1500` |
| `aurora/trading_cycle.py` | fetch 1d limit 1500; `overlay_directive()` |
| `aurora/e4_runtime_parity.py` | forming-bar compare / prefix scan |
| `tests/test_e4_runtime_parity.py` | freeze, horizon, cycle, CSV prefixes |

E3 `simulate_overlay` excess BTC after this package: **unchanged**
(`0.0338021862`, 58 trades, `EDGE_PASS_OFFLINE`).

## Explicit non-goals

- Retuning E2 after seeing E3 numbers
- TESTNET / LIVE execution
- Spot BTC CORE executor
- Claiming intent.action always equals E3 fills
