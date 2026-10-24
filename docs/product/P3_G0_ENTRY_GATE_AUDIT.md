# P3-G0 Entry Gate Audit

Status: `PASS`  
Date: `2026-09-10`

```text
P2-A TREND INPUT              STABLE
P2-B VALUE INPUT              STABLE
P2-C EVENT INPUT              STABLE · SOURCE INGEST NOT CONNECTED

P2-PRE T1–T10                 PASS · CLOSED

P3-G0 ENTRY GATE AUDIT        PASS
P3 RUNTIME IMPLEMENTATION     GO · READ-ONLY ONLY
P3 → RISK / EXECUTION         HOLD

EXECUTION                     DENIED
LIVE                          NO-GO
ALPHA EVIDENCE                NO-EVIDENCE
```

## 纪律（冻结）

```text
tests/fixtures/decision_brain_v1_1_cases.py     = CONTRACT FIXTURE (hash pinned)
tests/test_decision_brain_contract_v1_1.py       = T1–T10 ACCEPTANCE AUTHORITY
aurora/decision_brain_entry_gate.py               = P3-G0 GATE (not runtime)
tests/test_decision_brain_entry_gate_g0.py        = G1–G14 ACCEPTANCE AUTHORITY
```

**不升级 `portfolio_brain_v2.py`。** 未来 P3 runtime 为全新 `decision_brain.py`（read-only），不 import 旧 Brain / RiskGate / execution。

## 三路 Input Contract

| 引擎 | Schema | Contract Hash |
|------|--------|---------------|
| P2-A Trend | `p2-a-trend-v1` | `CONTRACT_HASH_A` |
| P2-B Value | `p2-b-value-v1` | `CONTRACT_HASH_B` |
| P2-C Event | `p2-c-event-v1` | `CONTRACT_HASH_C` |

Normalizer：`normalize_trend_decision_input` · `normalize_value_decision_input` · `normalize_event_decision_input`

## P0–P5 Priority（Brain 合同）

```text
P0 Account / Position / Protection Truth
P1 Risk constraints
P2 Thesis invalidation / Risk reduction
P3 BTC↔ETH Spot Allocation
P4 Trend Overlay
P5 Event Increment
```

## G1–G14 回归门

| ID | 语义 | 状态 |
|----|------|------|
| **G1** | T1–T10 PASS | PASS |
| **G2** | P2-A schema stable | PASS |
| **G3** | P2-B schema + UNKNOWN not out-voted | PASS |
| **G4** | P2-C schema stable | PASS |
| **G5** | Event NOT_CONNECTED → stable, no boost | PASS |
| **G6** | Account UNKNOWN → delta UNAVAILABLE | PASS |
| **G7** | Position UNKNOWN → block new risk | PASS |
| **G8** | OPEN blocked + CLOSE thesis survives | PASS |
| **G9** | CRYPTO_BETA_CLUSTER | PASS |
| **G10** | Event incremental, no double count | PASS |
| **G11** | brain_decision_key idempotent | PASS |
| **G12** | Forbidden execution imports | PASS |
| **G13** | No order/submit/execute output | PASS |
| **G14** | T1–T10 fixture hash unchanged | PASS |

## T1–T10 Fixture Hash

```text
T1_T10_FIXTURE_HASH = 5c46f0e54e37a08f
```

修改 fixture 语义需显式 bump + 审查。

## 输出边界

```text
CURRENT + TARGET + DELTA PROPOSAL
submit_allowed = False
plan_only = True
```

Account UNKNOWN 时：`delta_status = UNAVAILABLE`，不伪造 Current。

## 明确不做

- P3 live runtime（下一刀 · read-only only）
- RiskGate adapter
- Execution / submit
- 修改 T1–T10 期望语义迁就 runtime
