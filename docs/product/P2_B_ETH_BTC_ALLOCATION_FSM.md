# P2-B.2 ETH/BTC Allocation State Machine

Status: `CONTRACT-PASS · READ-ONLY`  
Date: `2026-09-10`

```text
P2-B.1 VALUE TRUTH           READ-ONLY-TRUTH-COMPLETE
P2-B.2 ALLOCATION FSM        CONTRACT-PASS · READ-ONLY
P2-B.3 OBSERVATORY MIRROR    HOLD
EXECUTION                    DENIED
```

## 纪律（冻结）

```text
tests/fixtures/eth_btc_allocation_b2_cases.py  = CONTRACT FIXTURE
tests/test_eth_btc_allocation_fsm_b2.py        = ACCEPTANCE AUTHORITY
```

## B1–B9 回归门

| ID | 语义 |
|---|---|
| **B1** | cheap + ETH L1 → ETH_CANDIDATE / WATCH_ETH |
| **B2** | cheap + L3+ + RS improving → ETH_CONFIRMED / INCREASE_ETH_ELIGIBLE |
| **B3** | has ETH + weakening → ETH_WEAKENING / REDUCE_ETH_ELIGIBLE |
| **B4** | thesis invalidated → BTC_RETURN / RETURN_BTC_ELIGIBLE |
| **B5** | value UNKNOWN → NO_REALLOCATION · 不得 BTC_RETURN |
| **B6** | value STALE → BLOCK NEW REALLOCATION · 不得强制卖 ETH |
| **B7** | same evidence epoch → idempotent · no duplicate eligibility |
| **B8** | ex-post / future fields → LOOKAHEAD_REJECTED |
| **B9** | INCREASE_ETH_ELIGIBLE → no target_weight / order / execution fields |

## 明确禁止

```text
NO order · NO execution · NO target portfolio % · NO P3 Brain
ELIGIBLE ≠ BUY/SELL · VALUE_ZONE ≠ ALLOCATION_TRIGGER
```

## 实现

- `aurora/eth_btc_allocation_fsm.py` — six-state FSM + idempotency key
- `aurora/observatory_snapshots.py` — eth_btc bundle embeds `allocation`
