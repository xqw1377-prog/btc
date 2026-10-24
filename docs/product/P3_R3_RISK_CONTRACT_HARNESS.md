# P3-R3.0 Risk Contract Harness

Status: `CONTRACT-PASS`  
Date: `2026-09-10`

```text
P3 READ-ONLY DECISION LOOP        COMPLETE
P3-R3.0 RISK CONTRACT HARNESS     CONTRACT-PASS

P3-R3.1 RISK ADJUDICATOR          HOLD
P3-R3.2 RISK OBSERVATORY          HOLD
P3-R4 EXECUTION                   FORBIDDEN / HOLD

RISK SEMANTICS                    FROZEN
EXECUTION                         DENIED
LIVE                              NO-GO
ALPHA                             NO-EVIDENCE
```

## 宪法级原则 — RISK MONOTONICITY

```text
RiskAdjustedPlan <= PortfolioDecisionCandidate

Risk 层只能：KEEP · REDUCE · BLOCK
绝不能：BOOST · INCREASE · RESTORE · ROUND-UP ABOVE APPROVAL
```

`assert_risk_monotonicity()` 在每次 `evaluate_risk()` 输出时强制执行（R3-16）。

## 冻结数据流

```text
PortfolioDecisionCandidate
        +
RiskTruthSnapshot（事实）
        +
RiskPolicySnapshot（政策 · PROVISIONAL_E3_PARAM）
        ↓
aurora/risk_contract_harness.py :: evaluate_risk()
        ↓
RiskAdjudicatedPortfolioPlan

tests/test_risk_contract_r3.py = R3-1~R3-16 ACCEPTANCE AUTHORITY
```

**禁止 import：** `portfolio_brain_v2` · `risk_gate` · `risk_kernel` · `binance_exchange` · `armed_runtime` · `execution`

旧 `risk_gate.py` 仅作历史参考，不是新合同 authority。

## 输入分离

| 层 | 职责 |
|----|------|
| `RiskTruthSnapshot` | 账户 / 持仓 / 保护 / 组合风险 / 成本 / pending / governance — UNKNOWN 即 UNKNOWN，禁止 0 fallback |
| `RiskPolicySnapshot` | 全部风险数字 — `parameter_status: PROVISIONAL_E3_PARAM` |

## 输出边界

```text
RiskAdjudicatedPortfolioPlan
  risk_state: PASS | REDUCED | BLOCK_NEW_RISK | DEFENSIVE_ONLY | UNKNOWN
  requested_* vs risk_adjusted_*
  crypto_beta_cluster { requested, allowed, state }
  event_increment { requested, allowed, state }
  loss_budget { requested, allowed, status }
  submit_allowed = false（永远）
```

```text
RISK-ADJUDICATED ≠ EXECUTABLE
Risk PASS ≠ ORDER
RiskAdjustedDelta ≠ exchange quantity
```

## 风险预算层级（嵌套，非独立钱包）

```text
per_trade_loss_budget
  ⊂ cluster_loss_budget
      ⊂ overlay_pool_loss_budget
          ⊂ portfolio risk
Event increment ⊂ unified budget remainder（不 double-count）
```

## 关键语义

- **Risk-at-stop:** `q_risk = allocated_loss_budget / unit_loss`；`unit_loss` 含 fee / slippage / stressed funding
- **Funding UNKNOWN:** block OPEN/ADD — **不** block CLOSE
- **OPEN gate fail + thesis invalid:** defensive candidate survives（`DEFENSIVE_ONLY`）
- **Position UNKNOWN + defensive:** intent preserved，`risk_adjusted_delta.status = UNAVAILABLE`
- **Stop plan PROPOSED:** 不允许新 overlay 风险
- **KILL ACTIVE:** `new_risk_allowed = false`，`defensive_reduction_preserved = true`

## 验收矩阵 R3-1 ~ R3-16

| ID | 场景 | 必须结果 |
|----|------|----------|
| R3-1 | BTC NAV UNKNOWN | BLOCK NEW RISK，不假造预算 |
| R3-2 | drawdown UNKNOWN | BLOCK NEW RISK |
| R3-3 | Brain 10 / Risk 6 | allowed ≤ 6 |
| R3-4 | BTC+ETH overlay | CRYPTO_BETA_CLUSTER 联合裁决 |
| R3-5 | Trend + Event | Event 吃剩余统一预算 |
| R3-6 | funding UNKNOWN | block OPEN/ADD，不 block CLOSE |
| R3-7 | spread STALE | block new overlay |
| R3-8 | OPEN fail + invalidation | defensive survives |
| R3-9 | Position UNKNOWN + defensive | delta UNAVAILABLE |
| R3-10 | Stop PROPOSED | no new overlay |
| R3-11 | unit_loss 上升 | q_allowed 只减不增 |
| R3-12 | policy null | fail-closed |
| R3-13 | same versions | deterministic + idempotent |
| R3-14 | version/hash 变 | risk_plan_key 变 |
| R3-15 | import/output scan | 无 execute/exchange |
| R3-16 | property | **allowed ≤ requested（全部 fixtures）** |

## 与 Accounting 的关系

```text
BTC NAV AUTHORITATIVE = NO
        ↓
RiskTruth.btc_nav = UNKNOWN
        ↓
BLOCK_NEW_RISK
```

Accounting/D2 不阻塞 **合同层**；阻塞 **R3.1 actionable risk-sized plan**。

## 下一刀（R3.1 GO 后）

```text
Decision Candidate → Risk Adjudication → Risk-Adjusted Portfolio Plan
```

仍非订单。R3.2 再做 Observatory 镜像。

## 台账纪律

R2 PASS **不自动等于** `OBSERVATORY CONTRACT CLEANUP` PASS。TOTAL RISK proxy / Actual-Target Mix / trade formatter 等清理项继续单列。
