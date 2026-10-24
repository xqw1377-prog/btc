# P2-C.2 Event Action Eligibility

Status: `CONTRACT-PASS · READ-ONLY`  
Date: `2026-09-10`

```text
P2-C.0 CONTRACT HARNESS    CONTRACT-PASS
P2-C.1 EVENT TRUTH         READ-ONLY-TRUTH-COMPLETE
P2-C.2 ACTION ELIGIBILITY  CONTRACT-PASS · READ-ONLY

EVENT BOOST                ELIGIBILITY ONLY
EVENT ACTIVE               UNREACHABLE
EVENT EXECUTION            NOT IMPLEMENTED

P2-C.3 OBSERVATORY MIRROR  HOLD
P3 / EXECUTION             HOLD / DENIED
ALPHA EVIDENCE             NO-EVIDENCE
```

## 纪律（冻结）

```text
tests/fixtures/event_action_eligibility_c2_cases.py  = CONTRACT FIXTURE
tests/test_event_action_eligibility_c2.py              = ACCEPTANCE AUTHORITY
aurora/event_action_eligibility.py                     = READ-ONLY ELIGIBILITY ONLY
```

**三问分离（承接 C0/C1）：**

| 层 | 函数 | 回答 |
|----|------|------|
| C2-A | `assess_impact()` | 潜在作用方向与强度（≠ 概率） |
| C2-B | `assess_priced_in()` | 市场是否已反映（anchor = first_observed_at） |
| C2-C | `assess_action_eligibility()` | 是否具备改变风险预算的**资格** |

```text
Evidence Grade  ≠  Action Eligibility
ELIGIBLE        ≠  boost amount / target_weight
ACTIVE          =  UNREACHABLE_BY_POLICY
RISK_OFF        ≠  OPEN SHORT
```

## Event Class Policy Registry v1

首批 class：`FED_RATE_DECISION` · `CPI_RELEASE` · `NFP_RELEASE` · `SEC_CRYPTO_REGULATION` · `ETF_APPROVAL_REJECTION` · `MAJOR_EXCHANGE_FAILURE` · `SYSTEMIC_HACK` · `OFFICIAL_SOCIAL_RUMOR`

Impact 来自 **policy + truth fields**，非 LLM 自由打分。

## Priced-in 机制

```text
anchor_time = first_observed_at
chase_distance = vol-normalized move (PROVISIONAL_E3_PARAM thresholds)
```

数字阈值（0.5 / 1.5 ATR）标记为 `PROVISIONAL_E3_PARAM` — 机制冻结，数值非 Alpha 真源。

## 不对称门

| 方向 | 趋势要求 |
|------|----------|
| 正向 EVENT_BOOST | 需要 trend >= L3 + alignment |
| 防守 RISK_OFF | **不**要求 bearish trend 确认 |

RISK_OFF 仅输出 overlay 资格：`BLOCK_NEW_LONG_ELIGIBLE` · `REMOVE_EVENT_INCREMENT_ELIGIBLE` · `REDUCE_OVERLAY_ELIGIBLE`

## C2-1 ~ C2-12 回归门

| ID | 语义 | 状态 |
|----|------|------|
| **C2-1** | E0 rumor → WATCH / NO_BOOST | PASS |
| **C2-2** | E1 direction UNKNOWN → CONFIRMED / NO_BOOST | PASS |
| **C2-3** | E3 + priced_in MOST → NO_BOOST | PASS |
| **C2-4** | E3 + L4 + PARTIAL → EVENT_BOOST_ELIGIBLE | PASS |
| **C2-5** | E3 + L1 → CONFIRMED / NO_BOOST | PASS |
| **C2-6** | E3 + priced_in UNKNOWN → NO_BOOST | PASS |
| **C2-7** | E3 negative systemic + L5 → RISK_OFF, no short | PASS |
| **C2-8** | RETRACTED → NONE | PASS |
| **C2-9** | STALE → no new boost | PASS |
| **C2-10** | same context → IDEMPOTENT | PASS |
| **C2-11** | future price → LOOKAHEAD_REJECTED | PASS |
| **C2-12** | ELIGIBLE output 无 execution 字段 | PASS |

## 历史负例

SEC 未授权社交账号虚假 ETF 消息 → E0 / WATCH / NEVER BOOST（`SEC-SOCIAL-NEG` fixture）

## 明确不做

- target_weight / leverage / order_qty / execute
- 账户余额 / RiskGate / Execution Auth 输入
- 前端 Event Mirror（P2-C.3）
- P3 Brain runtime
