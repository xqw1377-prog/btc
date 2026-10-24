# AURORA TRADING STRATEGY CONTRACT V1.1

Status: `DESIGN-FROZEN`  
Date: `2026-09-09`  
Supersedes: V1（同日 DESIGN-FROZEN）  
Baseline: HEAD working tree（P2-A in progress · observatory-v1 transport CONNECTED）

```text
AURORA TRADING STRATEGY CONTRACT V1.1    DESIGN-FROZEN
P0  PRODUCT NORTH STAR                   APPROVED
P1  OBSERVATORY V2                       DESIGN-FROZEN
P2  三引擎工程化                         HOLD（本合同为 P2 前置冻结）
P3  DECISION BRAIN                       HOLD
P4  BTC NAV / ACCOUNT TRUTH              HOLD
P5  E3 / OOS                             CLOSED-OFFLINE（≠ LIVE）
```

**不是开工令。** 不授权 AUTO TESTNET、不清 kill、不发 permit、不宣称未实现能力已存在。  
V1.1 **不改三引擎架构**；仅把 **冻结语义** 与 **尚待 E3 证明的数字参数** 彻底拆开。

### V1.1 Amendment 摘要

| ID | 内容 |
|---|---|
| **A1** | `OPEN_IFF` 增加 `PRE_SUBMIT_REVALIDATION`；计划 PASS ≠ 提交时仍 PASS |
| **A2** | 风险数字分层：`FROZEN SEMANTICS` vs `PROVISIONAL_E3_PARAM`；风险预算层级 |
| **A3** | Risk-at-Stop 纳入 fee / slippage / funding / stress；`planned_loss_budget` 非损失保证 |
| **A4** | L0–L5 语义冻结；ADX/ATR 等为研究参数；`Trend Level ≠ Risk Multiplier`；OVEREXTENSION GUARD |
| **A5** | 价值区 ≠ 换仓触发器；ETH/BTC 状态机；禁止 cycle progress 未来高点泄漏 |
| **A6** | Event Evidence Grade ≠ Action Eligibility；UNKNOWN EVENT → ALERT ONLY |
| **A7** | Decision Brain 冲突优先级；Target/Delta 输出；NO DOUBLE COUNTING |
| **A8** | Evidence-based RE-ARM / COOLDOWN（非固定分钟冷却） |
| **+** | `PROPOSED STOP ≠ ACTIVE STOP`；ACK 不能升级成 ACTIVE |

---

## 0. 核心原则

三个引擎**不能**做成三个各自下单的机器人。职责必须正交：

```text
TREND QUANT ENGINE      → 做哪个资产、要不要增加方向风险（PERP OVERLAY）
ETH/BTC VALUE ENGINE    → BTC 与 ETH 现货资本怎么换（CORE SPOT）
EVENT INTELLIGENCE      → 这一刻是否值得临时放大或立即收缩风险
```

三路统一进入：

```text
Decision Brain → RiskGate → Execution Gate → Order → Fill / Ledger / Reconcile
```

与 V2 一致：组合决定须过统一风险门；执行前须重新核验账户、持仓、政策、报价与有效期；**任一版本变化 → 旧计划失效 → 重算**。

North Star 已冻结：三引擎不能分别控制订单；Decision Brain 只输出**一份资本目标状态**（不是 ORDER）。

---

## 1. 统一交易触发链

```text
市场数据 / 账户事实 / 事件事实
                ↓
┌──────────────────────────────────┐
│ 1. TREND QUANT ENGINE            │
│ 2. ETH/BTC VALUE ENGINE          │
│ 3. EVENT INTELLIGENCE ENGINE     │
└──────────────────────────────────┘
                ↓
        DECISION BRAIN  →  TARGET STATE + DELTA
                ↓
          RISK GATE
                ↓
       EXECUTION GATE  →  PRE_SUBMIT_REVALIDATION
                ↓
             ORDER
                ↓
      FILL / LEDGER / RECONCILE
```

### 1.1 统一生命周期状态机

```text
OBSERVE → WATCH → ELIGIBLE → ARMED → OPEN → MANAGE → REDUCE/CLOSE → COOLDOWN
```

**UNKNOWN 纪律：** 任何核心事实为 `UNKNOWN` → `BLOCK NEW RISK`。

### 1.2 开仓与提交（A1 — 两阶段门）

#### 阶段一：计划许可

```text
TRADE MAY BE PLANNED
IFF OPEN_IFF_10 = PASS

Governance              = PASS
AND Market Truth        = KNOWN
AND Account / Position Truth = KNOWN
AND One Engine          = ELIGIBLE
AND Decision Brain      = ACTION
AND Funding / Cost      = ACCEPTABLE
AND RiskGate            = PASS
AND SL Plan             = AUTHORITATIVE (approved_stop proposed)
AND No Pending UNKNOWN Order
AND No Incident / Kill
```

缺一项 → `NO PLAN`。

#### 阶段二：提交许可

```text
TRADE MAY BE SUBMITTED
IFF PRE_SUBMIT_REVALIDATION = PASS
```

提交前**必须**重新核验（任一变化 → `PLAN_EXPIRED` → `RECOMPUTE`）：

```text
market_snapshot_version
account_snapshot_version
position_version
open_order_version
policy_hash
strategy_hash
quote freshness
protection plan (confirmed_active_stop where required)
authorization
kill / incident state
```

**纪律：**

```text
Decision PASS  ≠  Execution 时仍然 PASS
```

不能拿「刚才 Brain 已批准」在 stale 快照上继续下单。

**反向不成立：** `CLOSE` / `REDUCE` / `EMERGENCY EXIT` 永远不能被 OPEN / SUBMIT 条件反向阻断。

### 1.3 引擎权力矩阵

| 引擎 | 决定什么 | 不决定什么 |
|---|---|---|
| ETH/BTC Value | Spot **Target 建议** + 状态机 | 永续方向、杠杆、下单 |
| Trend Quant | Overlay **Candidate** + 等级 | 现货换仓、事件放大、最终 size |
| Event Intelligence | **Incremental budget** 申请 / Risk-Off | 独立第三笔、直接杠杆 |
| Decision Brain | **Target State + Delta**（冲突仲裁） | Size、SL 价格、订单 |
| RiskGate | **Size + SL + TP + Can Open** | 策略论点 |
| Execution Gate | 提交前 REVALIDATION + 发单 | 风险预算 |

### 1.4 止损状态机（保护合同）

```text
proposed_stop        ← 策略 / Brain 提案
approved_stop        ← RiskGate 批准
submitted_stop       ← 已发交易所改单
confirmed_active_stop ← 交易所核验 ACTIVE
```

**冻结：**

```text
PROPOSED STOP  ≠  ACTIVE STOP
ACK            ≠  ACTIVE
```

移动止损路径：

```text
propose → risk check → submit → exchange confirm → state commit
```

禁止 UI 先把止损线画到新位置、后台再慢慢改单。

---

## 2. 资本与风险预算（A2 · A3）

### 2.1 资本四层（FROZEN SEMANTICS）

| 资本层 | 作用 |
|---|---|
| Core Spot | BTC + ETH 长期资本 |
| Reserve | USDT / Margin / 应急流动性 |
| Trend Risk | BTC/ETH Overlay（PERP） |
| Event Risk | 重大事件**增量**风险（须为统一预算子集） |

### 2.2 风险预算层级（FROZEN SEMANTICS）

与 V2 风险配置对齐；关键字段为空时**不得**自动产生交易许可：

```text
RISK BUDGET HIERARCHY

per_trade_loss_budget
cluster_loss_budget          ← CRYPTO_BETA_CLUSTER 统一裁定
overlay_pool_loss_budget
event_increment_budget       ← 必须是 overlay 池的子预算，不能账户外叠一份
managed_gross_exposure_max
funding_cost_budget
drawdown_budget
```

```text
CRYPTO_BETA_CLUSTER

BTC per_trade 0.7%  +  ETH per_trade 0.7%
≠  total risk 1.4%

须经过相关性 / 压力场景由 cluster_loss_budget 统一裁定
```

### 2.3 PROVISIONAL_E3_PARAM（研究候选 — 非冻结常数）

以下数字 **status = PROVISIONAL · freeze_gate = E3**。E3 目标不是「最佳点」，而是**稳定区间**（如 ADX 18–24、overlay pool 0.8–1.4% NAV 均有效）。

```text
overlay_pool_loss_budget_candidate     1.5% NAV    PROVISIONAL
per_trade_loss_budget_candidate        0.75% NAV   PROVISIONAL
event_increment_budget_candidate       0.5–0.75%   PROVISIONAL
total_hard_risk_candidate              2.0–2.25%   PROVISIONAL
core_spot_range_candidate              80–95%      PROVISIONAL
reserve_range_candidate                5–20%       PROVISIONAL
managed_gross_exposure_max_candidate   1.5x / 2x / 3x cap   PROVISIONAL
```

**禁止：** 因 UI、夹具或单次 OOS 把 candidate 写死为 LIVE 常数。

### 2.4 仓位 sizing（A3 — 升级公式）

**FROZEN：** 先决定 unit loss → 再反推 qty；**禁止**为 target notional 硬改窄止损。

```text
unit_loss =
  price_stop_loss
+ adverse_slippage
+ fees
+ stressed_funding

q_risk = allocated_loss_budget / unit_loss

q_final = min(
  q_target,
  q_risk,
  q_exposure,
  q_margin,
  q_stress
)
```

**明确：**

```text
planned_loss_budget = 计划风险预算
≠ 市场极端情况下的损失保证
```

止损看起来 0.5% 但跳价+费用+Funding 超预算 → RiskGate **必须**缩仓或拒绝 OPEN。

### 2.5 杠杆是结果，不是目标

真正约束是 **Risk-at-Stop + 成本 + 压力**，不是杠杆倍数。

---

## 3. 引擎一：Trend Quant Engine（A4 · A8）

**职责：** BTC/ETH 趋势事实 + Overlay Candidate。**1m 不能产生交易资格。**

### 3.1 FROZEN SEMANTICS — 趋势等级

| 等级 | 语义 | 与风险的关系 |
|---|---|---|
| L0 | UNKNOWN | BLOCK |
| L1 | WEAK | 不增加 |
| L2 | FORMING | WATCH |
| L3 | CONFIRMED | 可 ELIGIBLE（仍须 RiskGate） |
| L4 | STRONG | 可 ELIGIBLE |
| L5 | EXTREME | **≠ MAX LEVERAGE**；须 OVEREXTENSION GUARD |

```text
Trend Level  ≠  Risk Multiplier
ActionEligibility  ≠  Position Size
```

### 3.2 PROVISIONAL_E3_PARAM — 趋势研究参数

以下**不得**写成「AURORA 永久认定」：

```text
candidate.adx_min                 20        PROVISIONAL
candidate.ema_slope_window        …         PROVISIONAL
candidate.volume_expansion        …         PROVISIONAL
candidate.atr_sl_multiplier       1.5–2.0   PROVISIONAL
candidate.overextension_atr       …         PROVISIONAL
candidate.confirmation_bars       …         PROVISIONAL
```

E3 须验证参数**族**稳健性，禁止 OOS 精调「最好看的 23.7」。

### 3.3 OVEREXTENSION GUARD（FROZEN SEMANTICS）

```text
L5 + OVEREXTENDED  →  HOLD / NO ADD  （不是继续加杠杆）
```

研究输入（PROVISIONAL）：

```text
distance_to_ema20 / ATR
distance_to_structure / ATR
```

### 3.4 TRIGGER 结构（语义冻结 · 数字 PROVISIONAL）

多头 Overlay **候选**须同时满足（数字见 §3.2 candidate）：

```text
1D 主趋势结构成立
AND 4H != BEAR
AND Volume != COLLAPSED
AND Funding != EXTREME
AND Volatility != UNKNOWN
AND Data Fresh = TRUE
AND NOT OVEREXTENDED
```

→ 映射 **L3+ ELIGIBLE**（Candidate，非 ORDER）

### 3.5 RE-ARM / COOLDOWN（A8 — Trend）

**禁止：** 固定「stop 后 60 分钟」作为唯一冷却。

```text
STOP / STRUCTURE INVALID
→ DISARMED

RE-ARM 必须：
  NEW AUTHORITATIVE HTF EVIDENCE
+ TREND RE-CONFIRMED
+ new evidence_epoch ≠ last_disarm_epoch
```

同一旧证据再次出现 → **NO RE-ENTRY**（见验收 T8）。

### 3.6 SL / TP / EXIT

结构失效 + ATR buffer（倍数 PROVISIONAL）；距离过宽 → **缩仓，不缩止损**。

---

## 4. 引擎二：ETH/BTC Relative Value（A5 · A8）

**职责：** Core Spot 配置。**不是**永续 ETH/BTC 策略。

### 4.1 FROZEN — 价值区 ≠ 触发器

分位区（背景 / 展示）：

```text
0–15%   DEEP CHEAP ETH
15–30%  CHEAP ETH
30–70%  FAIR
70–85%  EXPENSIVE ETH
85–100% EXTREME EXPENSIVE ETH
```

```text
VALUE ZONE  ≠  ALLOCATION TRIGGER
```

### 4.2 FROZEN — 配置状态机（工程实现）

```text
BTC_DEFAULT
ETH_CANDIDATE
ETH_CONFIRMED
ETH_HOLD
ETH_WEAKENING
BTC_RETURN
```

进入 **ETH_CANDIDATE / ETH_CONFIRMED** 须全部（语义冻结）：

```text
Cheap ETH (value background)
AND ETH trend confirmed (≥ L3)
AND ETH/BTC relative trend improving
AND relative strength stops deteriorating
```

**否决例（T1）：**

```text
ETH cheap + ETH L1  →  WATCH ETH / NO REALLOCATION
```

### 4.3 周期进度 — 禁止未来函数（FROZEN）

```text
LIVE / DECISION:
  仅使用 decision_time 已知的 cycle_low · cycle_high_so_far

RESEARCH / REVIEW:
  Ex-post full-cycle progress（事后分析专用）

禁止混用：
  用「本轮最终高点」反推「现已完成 35%」
```

Observatory 展示须区分 `known_range_position` vs `ex_post_progress`（后者不得进入 Brain）。

### 4.4 RE-ARM（A8 — ETH/BTC）

```text
BTC_RETURN
→ 同一状态机 epoch 内不允许立即重新 ALLOCATE ETH
→ 须新的 ratio / trend confirmation epoch
```

---

## 5. 引擎三：Event Intelligence（A6 · A8）

### 5.1 双状态机（FROZEN — 必须分离）

**Evidence Grade（事实层）：**

```text
E0  未核验 / 冲突
E1  事实已核实但方向不清
E2  传导 + 预期差较清晰
E3  进一步得到市场与持续性支持
```

**Action Eligibility（交易层）：**

```text
NONE → WATCH → CONFIRMED → ELIGIBLE → ACTIVE → RISK_OFF
```

```text
Evidence Grade  ≠  Action Eligibility
E3            ≠  ACTIVE
```

即使 E3，仍须过：trend alignment · priced-in · chase distance · cost · liquidity · account · RiskGate · authorization。

### 5.2 UNKNOWN EVENT（FROZEN）

```text
UNKNOWN EVENT CLASS  →  ALERT ONLY  →  NO AUTOMATIC BOOST
```

预先批准类别之外的突发事件，不自动加杠杆。

### 5.3 EVENT BOOST（语义）

Event 只申请 **event_increment_budget**（子预算）；**禁止** double count：

```text
BTC Trend bullish + Fed bullish BTC
≠ confidence 70 + 80 = 150

Event 只能申请 incremental budget，不能创造第二份基础风险
```

### 5.4 RE-ARM（A8 — Event）

```text
EVENT INVALIDATED  →  same event_id DISARMED

RE-ARM 须：
  new evidence_version
+ re-verification
+ new eligibility epoch
```

**T7：** Event RETRACTED → increment removed → **不自动反手**。

---

## 6. Decision Brain（A7 — P3 合同）

### 6.1 冲突优先级（FROZEN）

```text
P0  Account / Position / Protection Truth
P1  Risk constraints
P2  Thesis invalidation / Risk reduction
P3  Spot BTC↔ETH allocation
P4  Trend overlay
P5  Event boost
```

```text
Risk 层要求减仓  不能被  Event A+  反向覆盖
ETH/BTC ALLOCATE  不能绕过  P0/P1 账户与风险真相
```

### 6.2 输出形状（FROZEN）

Brain 输出 **TARGET STATE**，不是 ORDER：

```text
CURRENT STATE
  BTC spot 80% · ETH 10% · USDT 10%
  BTC overlay +10%

TARGET STATE
  BTC spot 70% · ETH 20% · USDT 10%
  BTC overlay +15%
  Event increment +0

DELTA  →  唯一进入执行计划的差异
  BTC spot −10% · ETH spot +10% · BTC overlay +5%
```

只有 **DELTA** 进入 Execution 计划；避免重复信号反复加仓。

### 6.3 NO DOUBLE COUNTING（FROZEN）

Trend + Event 同向 → Event 仅 **incremental budget**（T3）。  
A+ event + Trend L1 → **NO BOOST / WATCH**（T4）。

### 6.4 P2 前验收用例（T1–T8 — 八项全过才闭合）

| ID | 场景 | 期望 |
|---|---|---|
| **T1** | ETH cheap + ETH L1 | WATCH ETH · NO REALLOCATION |
| **T2** | BTC L4 + ETH L4 | Beta Cluster cap · 不各拿完整 per_trade budget |
| **T3** | Trend + Event 同向 | Event 仅 incremental · 不 double count |
| **T4** | A+ event + Trend L1 | NO BOOST · WATCH |
| **T5** | Account or Protection UNKNOWN | BLOCK NEW RISK |
| **T6** | CLOSE 条件成立 + OPEN blocked | CLOSE **仍必须通过** |
| **T7** | Event RETRACTED | increment removed · 不自动反手 |
| **T8** | STOP 后同一旧证据再现 | NO RE-ENTRY · 须 fresh evidence RE-ARM |

V1 三例（A/B/C）保留为语义说明；**P2 开工前以 T1–T8 为 Decision Brain 测试桩验收标准**。

**Harness 实现（CONTRACT ONLY · 非 P3 runtime）：**

```text
aurora/decision_brain_harness.py
tests/test_decision_brain_contract_v1_1.py
tests/fixtures/decision_brain_v1_1_cases.py
```

Contract guards：**T9** PRE_SUBMIT_REVALIDATION · **T10** PROPOSED STOP ≠ ACTIVE。

**P2-PRE 收口：** `docs/product/P2_PRE_DECISION_BRAIN_HARNESS.md`（CLOSED · PASS）。

**P3 Entry Gate：** T1–T10 PASS + P2-A/B/C input contracts stable → 才允许 P3 runtime。

---

## 7. 与现有工程合同的关系

| 合同 | 关系 |
|---|---|
| `AURORA_V2_PRD.md` | 风险字段分层、Evidence vs Eligibility、重算纪律 |
| `E2_STRATEGY_V2.md` | BTC HTF overlay 子集；LONG only |
| `E1_RISK_SEMANTICS.md` | RiskGate 最终 authority；funding veto |
| `E0_ACCOUNTING_TRUTH.md` | NAV / 费用真源 |
| `PRE_EXECUTION_CONFORMANCE.md` | OPEN 前 kill / protection / UNKNOWN |

**冲突时：** 治理与安全 > 本文 > 产品展示 > 夹具。

---

## 8. 能力现状（严格口径）

```text
TRADING STRATEGY CONTRACT V1.1   DESIGN-FROZEN

OBSERVATORY-V1 TRANSPORT         CONNECTED（只读 · ≠ 引擎能力成立）
Trend Quant Engine               PARTIAL（P2-A in progress）
Decision Brain                   PROPOSED / NOT LIVE
Execution                        DENIED · KILL ACTIVE · TRADING NO-GO
```

---

## 9. P2 实施顺序（不变）

```text
TRANSPORT → P2-A → P2-B → P2-C → P3 → P4 → P5 → E3 → SHADOW
```

REALTIME FEED ≠ LIVE TRADING。FIXTURE 可 synthetic；REALTIME 禁止 synthetic。

---

## 10. 冻结清单（V1.1）

```text
THREE ENGINES ORTHOGONAL
OPEN_IFF_10 + PRE_SUBMIT_REVALIDATION
PLAN_EXPIRED → RECOMPUTE
FROZEN SEMANTICS vs PROVISIONAL_E3_PARAM
RISK BUDGET HIERARCHY + CRYPTO_BETA_CLUSTER
unit_loss includes fee/slip/funding/stress
Trend Level ≠ Risk Multiplier · L5 ≠ MAX LEV · OVEREXTENSION GUARD
VALUE ZONE ≠ ALLOCATION TRIGGER · NO FUTURE CYCLE HIGH
Event Evidence ≠ Action Eligibility · UNKNOWN EVENT → ALERT ONLY
Decision PRIORITY P0–P5 · TARGET/DELTA · NO DOUBLE COUNT
EVIDENCE-BASED RE-ARM（not fixed minutes）
PROPOSED STOP ≠ ACTIVE STOP
T1–T8 ACCEPTANCE BEFORE P2 DECISION BRAIN CODE
```

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-09 | **V1.1** — A1–A8 + 止损状态机 + T1–T8 验收；语义/参数分离 |
| 2026-09-09 | V1 DESIGN-FROZEN — 三引擎触发链初版 |
