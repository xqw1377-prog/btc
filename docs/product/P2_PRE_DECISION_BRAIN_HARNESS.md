# P2-PRE Decision Brain Contract Harness

Status: `CLOSED`  
Date: `2026-09-10`

```text
P2-PRE / DECISION-BRAIN-CONTRACT-HARNESS = PASS

T1–T8 SEMANTICS          FROZEN
A1 REVALIDATION GUARD     PASS（T9）
STOP AUTHORITY GUARD      PASS（T10）

Decision Brain semantics  TEST-HARNESS-PASS
Decision Brain runtime    NOT IMPLEMENTED
P3                        HOLD
```

## 纪律（冻结）

```text
tests/fixtures/decision_brain_v1_1_cases.py
  = CONTRACT FIXTURE
  不得为了让未来 P3 通过而修改语义

tests/test_decision_brain_contract_v1_1.py
  = ACCEPTANCE AUTHORITY
  P3 可以换实现，不可以换答案
```

## 核心回归门

| ID | 语义 |
|---|---|
| **T5** | UNKNOWN → BLOCK NEW RISK |
| **T6** | OPEN 被阻断 ≠ CLOSE / REDUCE 被阻断 |
| **T8** | STOP 后旧 evidence ≠ 新交易机会 |

## P3 Entry Gate（未满足 — P3 仍 HOLD）

```text
P3 MAY START IFF

  T1–T10 PASS（maintained）
  AND P2-A INPUT CONTRACT STABLE
  AND P2-B INPUT CONTRACT STABLE
  AND P2-C INPUT CONTRACT STABLE
```

测试桩通过 **只表示 Brain 语义准备好**，不代表现在应实现 Brain。

## Artifacts

- `aurora/decision_brain_harness.py` — CONTRACT HARNESS ONLY
- `tests/fixtures/decision_brain_v1_1_cases.py` — frozen inputs
- `tests/test_decision_brain_contract_v1_1.py` — acceptance authority
