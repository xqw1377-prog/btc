# P2-C.0 Event Intelligence Contract Harness

Status: `CONTRACT-PASS`  
Date: `2026-09-10`

```text
P2-C.0 EVENT CONTRACT HARNESS = PASS
P2-C.1 EVENT TRUTH            = READ-ONLY-TRUTH-COMPLETE
P3 ENTRY GATE PREP            = HOLD
P3 DECISION BRAIN RUNTIME     = HOLD
EXECUTION                     = DENIED
```

## 纪律（冻结）

```text
tests/fixtures/event_intelligence_c0_cases.py  = CONTRACT FIXTURE
tests/test_event_intelligence_contract_c0.py   = ACCEPTANCE AUTHORITY
aurora/event_intelligence_harness.py           = CONTRACT HARNESS ONLY
```

## 三问分离

| 层 | 对象 | 回答 |
|----|------|------|
| A | EventRecord | 发生了什么？ |
| B | EventAssessment | 对 BTC/ETH 可能意味着什么？ |
| C | EventActionEligibility | 是否具备改变风险预算的资格？ |

```text
Evidence Grade  ≠  Action Eligibility
E3            ≠  ELIGIBLE（须 trend / priced_in / freshness）
ACTIVE        =  UNREACHABLE_BY_POLICY
```

## C1–C10 回归门

| ID | 语义 |
|----|------|
| **C1** | 未经核验传闻 → E0 / WATCH / NO BOOST |
| **C2** | 官方事实、方向不清 → E1 / CONFIRMED_FACT |
| **C3** | priced_in MOST → NO BOOST |
| **C4** | E3 + L4 + PARTIAL + fresh → ELIGIBLE / EVENT_BOOST_ELIGIBLE |
| **C5** | E3 + L1 → CONFIRMED / NO BOOST |
| **C6** | UNKNOWN event_class → 永不 ELIGIBLE |
| **C7** | RETRACTED → 移除资格 · 不自动反手 |
| **C8** | 同 evidence_version → IDEMPOTENT |
| **C9** | 100 转载同一 cluster → corroboration_count = 1 |
| **C10** | 未来修订注入 → LOOKAHEAD_REJECTED |

## 输出边界

允许：`EVENT_BOOST_ELIGIBLE` · `RISK_OFF_ELIGIBLE` · `EventContextCandidate`

禁止：`target_weight` · `order_qty` · `buy` · `sell` · `submit` · `execute` · `open_short`

## P3 Entry Gate

须 **P2-C.0 + P2-C.1 + P2-C.2** 稳定后才启动 P3 Entry Gate Audit。当前 **HOLD**。
