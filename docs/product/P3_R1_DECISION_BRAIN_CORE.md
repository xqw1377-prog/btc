# P3-R1 Decision Brain Core

Status: `CONTRACT-PASS · READ-ONLY`  
Date: `2026-09-10`

```text
P3-G0 ENTRY GATE AUDIT        PASS
P3-R1 DECISION BRAIN CORE     CONTRACT-PASS · READ-ONLY

P3-R2 OBSERVATORY MIRROR      HOLD
P3-R3 RISKGATE ADAPTER        HOLD
P3-R4 EXECUTION ADAPTER       FORBIDDEN / HOLD

P3 DECISION SEMANTICS         RUNTIME-IMPLEMENTED
P3 COMPLETE                   NO
EXECUTION                     DENIED
LIVE                          NO-GO
```

## 纪律（冻结）

```text
observatory / runtime facts
        ↓
decision_brain_entry_gate normalizer
        ↓
NormalizedDecisionInput
        ↓
aurora/decision_brain.py :: evaluate_decision()
        ↓
PortfolioDecisionCandidate

tests/test_decision_brain_r1.py = R1–R13 ACCEPTANCE AUTHORITY
```

**Brain 不 import observatory。** 不 import `portfolio_brain_v2` / RiskGate / execution。

## 唯一入口

```python
evaluate_decision(normalized_input, decision_policy) -> PortfolioDecisionCandidate
```

## DecisionPolicySnapshot

所有 spot/overlay 百分比来自版本化 policy 对象，标注 `PROVISIONAL_E3_PARAM` — Brain 内无魔法数字。

## P0–P5 阶段

```text
P0 TRUTH GATE
P1 RISK CONTEXT (consume only)
P2 DEFENSIVE OVERRIDE
P3 SPOT ALLOCATION
P4 TREND OVERLAY (CRYPTO_BETA_CLUSTER)
P5 EVENT INCREMENT
→ compose_target()
```

## 输出边界

```text
TARGET ≠ ORDER
DELTA  ≠ EXECUTION
ELIGIBLE ≠ APPROVED RISK
submit_allowed = false (always)
```

Account UNKNOWN → `current_state.status = UNKNOWN` · `delta_proposal.status = UNAVAILABLE` · `target_state.status` may be `CANDIDATE`.

## R1–R13 回归门

| ID | 语义 | 状态 |
|----|------|------|
| R1 | Trend survives · Event NOT_CONNECTED | PASS |
| R2 | Account UNKNOWN → target CANDIDATE · delta UNAVAILABLE | PASS |
| R3 | Authoritative current → deterministic delta | PASS |
| R4 | CRYPTO_BETA_CLUSTER | PASS |
| R5 | Event incremental · no double count | PASS |
| R6 | RISK_OFF wins · no short | PASS |
| R7 | CLOSE survives OPEN block | PASS |
| R8 | Protection UNKNOWN · reduce survives | PASS |
| R9 | NOT_CONNECTED ≠ NO_EVENT | PASS |
| R10 | Deterministic | PASS |
| R11 | policy_hash → decision_key change | PASS |
| R12 | No execution imports/output | PASS |
| R13 | Idempotent same key · no repeat delta | PASS |

## 明确不做

- P3-R2 Final Decision Observatory Mirror
- RiskGate / Execution adapters
- STOP manager (仅 `protection_change_proposal`)
