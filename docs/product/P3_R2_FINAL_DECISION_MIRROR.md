# P3-R2 Observatory Final Decision Mirror

**Status:** PASS · READ-ONLY  
**Runtime:** `aurora/decision_observatory.py` → `observatory.decision`  
**Frontend:** `decisionMirror.js` → LEFT 05 + RIGHT Portfolio Decision  

## Frozen data flow

```text
P2-A Trend · P2-B Value · P2-C Event
       ↓
Entry Gate Normalizers
       ↓
evaluate_decision()
       ↓
PortfolioDecisionCandidate
       ↓
Decision Observatory Projection
       ↓
observatory.decision
       ↓
decisionMirror.js
       ↓
LEFT 05 · RIGHT Portfolio Decision (六层)
```

**Frontend = MIRROR ONLY** — no P0–P5 recompute, no TARGET/DELTA re-derivation.

## Product semantics preserved

| State | Meaning |
|-------|---------|
| TARGET CANDIDATE | Strategy direction formed; not an order |
| DELTA UNAVAILABLE | Target may exist; no authoritative CURRENT |
| CURRENT UNKNOWN | Account/mix truth incomplete |
| EXECUTION DENIED | Always at this stage (P3-R3 HOLD) |

Account UNKNOWN **must not** collapse the entire card to UNKNOWN when TARGET CANDIDATE is valid.

## Acceptance (R2-1 ~ R2-12)

| ID | Criterion |
|----|-----------|
| R2-1 | `observatory.decision` from real `evaluate_decision()` |
| R2-2 | Frontend mirror only (no brain logic in JS) |
| R2-3 | Account UNKNOWN → CURRENT=UNKNOWN, no fabricated mix |
| R2-4 | TARGET CANDIDATE + DELTA UNAVAILABLE together |
| R2-5 | Authoritative CURRENT → CURRENT/TARGET/DELTA consistent |
| R2-6 | RISK_OFF precedence visible in P0–P5 trace |
| R2-7 | CRYPTO_BETA_CLUSTER when BTC+ETH overlay eligible |
| R2-8 | Event increment = request eligibility only |
| R2-9 | TARGET ≠ ORDER · DELTA ≠ EXECUTION resident |
| R2-10 | RiskGate NOT APPLIED · submit_allowed=false |
| R2-11 | Same decision_key → idempotent target (no drift) |
| R2-12 | Top bar: REALTIME · READ ONLY · EXECUTION DENIED |

Tests: `tests/test_decision_observatory_r2.py`

## Ledger line (when accepted)

```text
P3 READ-ONLY DECISION LOOP = COMPLETE
P3-R2 FINAL DECISION MIRROR = PASS
P3-R3 RISKGATE ADAPTER = HOLD
EXECUTION = DENIED · LIVE = NO-GO
```

**Not written:** `P3 COMPLETE` (RiskGate stage still HOLD).
