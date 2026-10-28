# P3-R3.1 Risk Adjudicator — 只读运行时实施方案

Status: `DOCUMENT CANDIDATE / IMPLEMENTATION NOT AUTHORIZED`  
Date: `2026-10-28`  
修订: `R31-D1～D3 已窄修；仍是文档候选，不是开工令`

```text
本文件 = 实施方案 + 旧链隔离方案 + 验收清单
本文件 ≠ 开工令
本文件 ≠ 交易授权

LIVE                     = NO-GO
REAL TESTNET WRITE       = DENIED
TRADING AUTHORITY        = UNCHANGED
EXECUTE_AUTHORIZED       = FALSE
KILL / INCIDENT_LOCK     = 不解除

E2 / E1                  = FROZEN（本计划不改常数、不改身份）
S3                       = CLOSED / OFFLINE PASS（不能替代本阶段或任何交易资格）
费用投影消费方 / funding = HOLD
真实账本迁移             = NOT AUTHORIZED
P3-R3.2 OBSERVATORY      = HOLD
P3-R4 EXECUTION          = FORBIDDEN / HOLD
```

开发授权格式（未签发）：

```text
「批准 P3-R3.1 只读运行时开工」
```

在这句出现之前，不新增 `risk_adjudicator` 运行时模块，不把 `evaluate_risk` 接到 `trading_cycle` / `production_main`，不改 `strategy_v2.py` / `risk_semantics.py`。

---

## 0. 这一刀回答什么

R3.0 只证明纯函数合同。R3.1 要证明一件更窄的事：

> 同一条只读运行时，吃进版本固定的决策目标、账户快照、行情和风险政策，给出批准、缩减或拒绝，以及理由。重启之后同一输入不漂。故障注入时拒绝新增风险。这条链到不了下单。

它不回答账户是否权威、保护是否在交易所生效、事故是否可关闭、测试网或主网是否放行，也不回答策略是否赚钱。

两张证书分开：

| 证书 | R3.1 是否颁发 |
|---|---|
| 能否安全执行 | 否。R3.1 只证明只读裁决链成立 |
| 是否有盈利证据 | 否。E2 的离线超额不能外推，三引擎配置仍无 OOS |

---

## 1. 冻结数据流

```text
PortfolioDecisionCandidate          版本：decision_key / as_of
AccountSnapshot                     版本：account_version / position_version / protection_version
MarketSnapshot                      版本：quote_version / freshness / as_of
RiskPolicySnapshot                  版本：policy_hash（PROVISIONAL_E3_PARAM）
        ↓
aurora/risk_adjudicator.py :: adjudicate_runtime()
        ↓
调用已有 evaluate_risk()（不重写第二套风险数学）
        ↓
仅本地追加的计划日志，无交易写入（与成交账、下单账分离）
        ↓
RiskRuntimeRecord
        submit_allowed = false
        order_intent   = ABSENT
        execution_eligibility = DENIED
```

运行时是合同的调用壳，不是新的决策脑。禁止在壳里重算 P0–P5、重算 TARGET、或在 `evaluate_risk` 之后把任何风险数字加回去。

---

## 2. 输入

四份输入都必须带版本。缺版本视同未知。版本号不是内容身份；内容哈希、`evaluation_at` 与来源字段见 §11。

### 2.1 决策目标

只接受已经由 `evaluate_decision()` 产生的 `PortfolioDecisionCandidate`。

必须带上：`decision_key`、`as_of`、`current_state`、`target_state`、`delta_proposal`、`crypto_beta_cluster`、`event_increment_request`、`submit_allowed`。

候选里的 `submit_allowed` 必须已经是 `false`。运行时不得把它改成 `true`。

### 2.2 账户快照

```text
status            KNOWN | UNKNOWN | STALE
account_version
position_version
protection_version
btc_nav           数字 | null
equity            数字 | null
positions         结构 | null
protection_state  ACTIVE_CONFIRMED | PENDING | PROPOSED | NOT_APPLICABLE | UNKNOWN
as_of
```

`null`、空串、缺失键都是未知。禁止用 `0` 填充 `btc_nav`、回撤、资金费或持仓数量。

R3.1 不新建权威净值。快照从调用方注入。接线到真实账本属于后续「权威账户真相」工单，不在本刀。

### 2.3 行情

```text
quote_version
freshness         ok | stale | unknown
as_of
btc_funding       数字 | null
spread            数字 | null
```

`freshness != ok`，或资金费 / 价差未知，对新增风险一律拒绝。不得把未知成本当成 `0`。

### 2.4 风险政策

沿用 `RiskPolicySnapshot`。`parameter_status` 必须仍是 `PROVISIONAL_E3_PARAM`。政策里任一预算为 `null`，整单失败关闭，不套隐式默认值。

本刀不修改 E1 的 `DEFAULT_RISK_BUDGET_PCT`，也不修改 E2 的 `OVERLAY_SIGNAL_SIZE_PCT`、ADX 或均线。

---

## 3. 输出

```text
RiskRuntimeRecord {
  risk_plan_key
  based_on_decision_key
  input_versions { decision, account, position, protection, quote, policy }
  risk_state          PASS | REDUCED | BLOCK_NEW_RISK | DEFENSIVE_ONLY | UNKNOWN
  reasons[]
  blockers[]

  requested_target
  risk_adjusted_target
  requested_delta
  risk_adjusted_delta

  new_risk_allowed                 bool
  defensive_intent_preserved       bool
  defensive_quantity               UNAVAILABLE | 来自权威持仓的缩减量

  identity_fence {
    btc_overlay_plan               ADJUDICATED | BLOCKED
    eth_overlay_execution          DENIED
    event_increment_execution      DENIED
  }

  submit_allowed                   false
  order_intent                     ABSENT
  execution_eligibility            DENIED
}

CallReceipt {
  record_present                   所引用的完整裁决记录是否已存在
  wrote_now                        本次调用是否新写入了该记录
  idempotent                       本次是否命中已有记录且未改其字节
}
```

`RiskRuntimeRecord` 是落盘后不再修改的裁决记录。`CallReceipt` 不写入该记录。两者的分工见 §11.3。

语义：

- `PASS`：新增风险请求未被削减，且真相足够形成计划。
- `REDUCED`：允许值严格低于请求值。
- `BLOCK_NEW_RISK`：账户、持仓、保护、报价、净值、回撤、政策或 kill 使新增风险不能成立。
- `DEFENSIVE_ONLY`：新增风险被拒绝，防守意图保留。
- `UNKNOWN`：只表示输入版本或内容无法固定。政策不完整、数值非法、身份冲突和日志失败不叫 `UNKNOWN`，按 §11.5 失败关闭。

`PASS` 仍然不是订单。`identity_fence` 里 ETH overlay 与事件增量的执行资格固定为 `DENIED`，即使合同层算出了非零 `allowed`。未经验证的配置只能出现在请求对照里，不能出现在可执行资格里。BTC overlay 也只是 `ADJUDICATED` 计划，执行资格同样是 `DENIED`。

持仓未知时，防守路径的数量字段必须是 `UNAVAILABLE`。禁止用请求目标反推平仓数量。

---

## 4. 风险单调性

沿用 R3.0 的 `assert_risk_monotonicity()`。运行时在写入计划日志之前再查一次。

```text
allowed_new_risk <= requested_new_risk
```

覆盖：现货再配置增量、BTC overlay、ETH overlay、cluster、事件增量、总暴露、损失预算。

若检查失败：不写计划。回执 `wrote_now=false`、`record_present=false`，`new_risk_allowed=false`，`risk_state` 不是 `PASS`，理由为 `RISK_MONOTONICITY_VIOLATION`。禁止改请求值来迁就一个更大的允许值。

同身份重放的裁决记录必须与已存字节一致。是否重放只出现在回执。另一次输入的允许值不必小于这一次。见 §11.3。

---

## 5. 未知与过期

| 条件 | 新增风险 | 减仓 / 防守 |
|---|---|---|
| 账户未知或过期 | 拒绝 | 不猜数量 |
| 持仓未知 | 拒绝 | 意图可保留，数量 `UNAVAILABLE` |
| 拟新增仓位的保护尚未满足 | 形成条件性计划；`new_risk_allowed=false`；执行资格仍是 `DENIED` | 已有仓位的保护状态另记；防守意图不因此取消 |
| 报价过期或未知 | 拒绝 | 不把成本当 0，也不因此禁止「意图保留」 |
| BTC NAV 未知 | 拒绝 | 同上 |
| kill / incident 活跃 | 拒绝 | 意图可保留，仍无执行权 |

减仓路径在本刀只验证到「意图保留且数量不可用」。它不验证真实平仓。离线里的防守记录不能写成交易所已确认。

---

## 6. 旧链隔离方案

旧写路径今天仍在树里，而且必须继续不能写：

```text
trading_cycle.py
  → PortfolioBrainV2
  → RiskGate
ops_t3_extended.py          T3_EXECUTE_AUTHORIZED = False
ops_controlled_requal.py    EXECUTE_AUTHORIZED = False
production_main.py          只读 broker 拒 create_order
execution_engine.py / execution_engine_v2.py / execution_truth.py
kernel/binance_exchange.py
```

隔离不等于删除这些文件。删除或改写 E2 执行身份不在 R3.1。隔离是证明下面四件事同时成立。

### 6.1 依赖方向

`risk_adjudicator.py` 只允许依赖：

```text
risk_contract_harness.evaluate_risk
decision candidate 的纯数据结构
仅本地追加的计划日志，无交易写入
```

禁止 import：

```text
portfolio_brain_v2
risk_gate
risk_kernel
trading_cycle
ops_t3_extended
ops_controlled_requal
production_main
execution_engine
execution_engine_v2
execution_truth
binance_exchange
armed_runtime
```

### 6.2 输出到不了写入口

`RiskRuntimeRecord` 不含 `order_id`、`client_order_id`、`exchange_qty`、`submit`、`execute`。

`trading_cycle`、`production_main`、`ops_t3_extended`、`ops_controlled_requal` 在本刀不得新增对 `adjudicate_runtime` 的调用。旧路径继续被各自的 `EXECUTE_AUTHORIZED=false` 挡住。R3.1 不把旧路径改成消费新计划的下单器。

### 6.3 运行时旁路探针

验收进程内安装调用探针。一次 `adjudicate_runtime` 期间：

```text
futures_create_order     调用次数 = 0
create_order             调用次数 = 0
RiskGate 方法            调用次数 = 0
PortfolioBrainV2.decide  调用次数 = 0
socket / HTTP 发送       调用次数 = 0
```

### 6.4 反向探针

从 `PortfolioBrainV2` 出发的现有调用栈，静态扫描不得出现 `adjudicate_runtime`。这样旧脑不能在风险门之后读取新计划并把仓位抬回去。

「风控减完后又抬回去」仍然只是待验证风险。R3.1 不把它写成既定事故。本刀只保证新运行时自己做不到抬升，并且旧入口接不到新计划。

---

## 7. 持久化与重启

计划日志是仅本地追加的计划日志，无交易写入。实现为独立 SQLite，路径由测试注入到临时目录。不写入 `state/kernel_ledger.db`，不迁移真实账本。

身份分两层，规则在 §11.1：版本声明身份绑定内容哈希；评估内容身份才是 `risk_plan_key`。二者不能互相代替。

重启恢复规则：

1. 进程退出后重新打开同一日志。
2. 相同评估内容身份再次调用：裁决记录逐字节不变。回执 `idempotent=true`、`wrote_now=false`。不覆盖。
3. 同一来源、对象与版本声明下内容不同，或政策哈希与政策正文不一致：`INPUT_IDENTITY_CONFLICT`。旧绑定不改，不得当成新裁决或幂等命中。
4. 合法新版本，或版本声明的内容绑定仍成立时的新 `evaluation_at`：独立裁决。不要求允许值低于另一条输入。
5. 旧行不可 `UPDATE`。失效是追加事件，或在读取时派生。
6. 写入中途失败：事务回滚。没有新行，或只有完整行。回执 `wrote_now=false`；这次尝试的 `record_present=false`，`new_risk_allowed=false`，且 `risk_state` 不是 `PASS`。

---

## 8. 验收清单

必须是运行时测试，不能只复跑 `tests/test_risk_contract_r3.py`。合同测试保持为 R3.0 回归，不代替下面各项。

| ID | 场景 | 必须结果 |
|---|---|---|
| R31-1 | 进程内调用 `adjudicate_runtime` | 返回记录；`submit_allowed=false`；无订单字段 |
| R31-2 | 同一输入调用两次 | 两次裁决记录逐字节相同；回执分别标出首次 `wrote_now` 与重放 `idempotent` |
| R31-3 | 请求 10，政策只够 6 | `risk_state=REDUCED`；允许值 ≤ 6 |
| R31-4 | 构造一个允许值大于请求值的假输出 | 运行时拒绝持久化 |
| R31-5 | `btc_nav=null` | `BLOCK_NEW_RISK`；不用 0 |
| R31-6 | 账户或报价 `STALE` / `unknown` | 拒绝新增风险 |
| R31-7 | 持仓未知，同时候选含防守动作 | 意图保留；数量 `UNAVAILABLE` |
| R31-8 | 空仓且拟新增保护未满足；已有未保护仓位；纯防守 | 三者分开。前两者 `new_risk_allowed=false`；空仓只让现有仓位保护为 `NOT_APPLICABLE`。纯防守保留意图，执行资格仍是 `DENIED` |
| R31-9 | 候选含 ETH overlay 与事件增量 | 两者 `execution_eligibility=DENIED`；计划文本可以保留请求对照 |
| R31-10 | kill 活跃 | 新增风险拒绝；防守意图可保留；写探针仍为 0 |
| R31-11 | 重启后跨进程重放 | 裁决字节与首次完全相同；回执 `idempotent=true`、`wrote_now=false` |
| R31-12 | 写入中途注入异常 | 无半截计划；重试后结果与成功路径一致 |
| R31-13 | 运行期间探针 | 交易所写、旧 `RiskGate`、旧 `PortfolioBrainV2` 调用均为 0 |
| R31-14 | 静态 import 扫描 | 裁决器与旧写路径互不引用 |
| R31-15 | E2/E1 文件哈希 | 与开工时记录的哈希一致 |
| R31-16 | 正常哈希下同版本异内容；另给合法新版本；伪造政策哈希 | 同声明异内容冲突且旧绑定不改；合法新版本独立成功。不能只伪造哈希碰撞 |
| R31-17 | SLA 边界、未来时间戳、跨快照错时；改墙钟后重放同一历史输入 | 历史结果不随墙钟变；超界拒绝新增风险 |
| R31-18 | 夹具注入 `KNOWN`；空仓＋拟新增保护未满足；已有未保护仓位；纯防守 | `KNOWN` 不升格为权威。三种情况分开断言，空仓不免掉拟新增仓位的保护 |
| R31-19 | 失效之后再写一条不同内容的新评估 | 旧行字节不变；新裁决不要求允许值更小 |
| R31-20 | NaN、Infinity、非法范围、合法零、多条阻断同时成立、日志不可写 | 零不是未知；状态按 §11.5 唯一；不可写时回执 `wrote_now=false`、`record_present=false`，且不是 `PASS` |
| R31-21 | 两个独立进程重放；两个独立连接并发同一版本声明 | 一致内容恰一条，裁决字节相同，回执区分首次与重放。并发的异内容绑定不被覆盖 |

R31-1 至 R31-15 的编号保留。R31-2 与 R31-11 的比较对象是裁决记录，不是带 `idempotent` 的回执。R31-19 仍不要求不同输入之间允许值下降。

R31-15 用开工提交里记下的 `strategy_v2.py` 与 `risk_semantics.py` 哈希。验收失败条件包括这两个文件被改动。

通过 R31-1 至 R31-21 只允许写成：

```text
P3-R3.1 RISK ADJUDICATOR = RUNTIME-PASS / READ-ONLY
EXECUTION ELIGIBILITY    = DENIED
```

禁止写成 `P3 COMPLETE`、`TRADING GO`、`LIVE GO`。

---

## 9. 明确不做

- 不接 `trading_cycle` 下单，不打开 `EXECUTE_AUTHORIZED`
- 不把新计划送进旧 `RiskGate`
- 不修改 E2/E1
- 不给 ETH overlay、事件增量执行资格
- 不实现 R3.2 界面，不实现 P3-R4 执行适配器
- 不制作权威 BTC NAV，不接 funding 消费方
- 不解除 kill，不签发测试网许可
- 不把 S3 费用投影的进度算进本验收

---

## 10. 交易资格路线（登记，不是本刀范围）

第 2–4 项可以在各自开工令出现后并行准备。任何一项通过，都不能代替另一项。测试网与主网必须分开裁定。

| 阶段 | 必须拿出的证据 | 完成后仍不代表 |
|---|---|---|
| 1. R3.1 与旧链隔离 | 单一只读裁决链、风险单调性、未知拒绝、无写旁路 | 允许下单。本阶段也不建立账户权威或执行权威 |
| 2. 权威账户真相 | 账户身份、余额／负债、持仓、费用与 funding 对账；BTC NAV 可追溯、可重放 | 保护可靠 |
| 3. 保护与退出恢复 | ACK 与 `ACTIVE_CONFIRMED` 分开；断网、超时、重启、部分成交、孤儿订单有确定处置 | 交易所已经验过。离线通过不能冒充 |
| 4. 部署与事故治理 | CI 必跑、版本固定、秘密隔离、告警、回滚；事故根因与遗留风险关闭 | 自动解除 kill |
| 5. 受控测试网资格窗 | 独立账户、显式许可、单次会话、限定数量和时限；真实成交、保护、退出、对账 | 主网 GO。数量须单独裁定 |
| 6. 主网资格评审 | 测试网证据、运行观察、风险接受与人工应急；另签限额许可 | 收益能力已证实 |

操作者侧的测试网账户、密钥轮换和事故资料在受控环境准备。密钥不进入聊天、不进入仓库。准备账户不等于授权用它下单。

---

## 11. 评审闭合（R31-P1～P5）

本节只补上次裁定点名的缺口。§0、§1、§6 与 §10 的其余句子保持原样。本节与上文冲突时，以本节为准。

### 11.1 R31-P1 内容身份

四份输入各自做规范化序列化，再组成身份。规范化规则：

- UTF-8 JSON；对象键按码点排序；无多余空白。
- 数字只以十进制文本出现，不经过二进制浮点。
- `null`、`true`、`false` 保持原样。缺键与 `null` 都不是 `0`。
- 数组保持调用方给出的顺序。

两套身份分开。内容哈希自己生成新键，不能代替版本声明上的冲突检查。

```text
content_hash = hash(
  canonical(decision),
  canonical(account),
  canonical(market),
  canonical(policy_body)
)
declaration_key = hash(source, object, version_claim)   # 四份输入各一条
risk_plan_key   = hash(四份 content_hash, evaluation_at, sla_rule_id)
```

`policy_body` 不含调用方自带的 `policy_hash`。运行时重算政策哈希。与自报值不一致，就是 `INPUT_IDENTITY_CONFLICT`。

每个 `declaration_key` 第一次出现时，绑定当时的 `content_hash`。同一来源、同一对象、同一版本声明再次出现而内容哈希不同：拒绝。不新增裁决，不覆盖旧绑定。合法的新版本是版本声明本身变了，并与其内容首次绑定，于是另有一条裁决。

只更换 `evaluation_at`、且该版本声明的内容绑定仍然成立：这是另一次评估，独立裁决。同一版本声明下内容已经不同，不能靠改 `evaluation_at` 变成新裁决。

日志保存四份规范化输入、声明绑定和裁决记录全文。评估内容身份相同的重放，比较的是裁决记录字节；回执见 §11.3。

### 11.2 R31-P2 评估时点与来源

`evaluation_at` 由调用方显式传入，进入评估内容身份。历史重放使用记录里的 `evaluation_at`，不读墙钟。现在重新评估必须传入新的 `evaluation_at`。只有对应版本声明的内容绑定未被打破时，这才是另一次裁决；旧的 `PASS` 不是当前资格。同声明异内容仍按 §11.1 拒绝。

时间比较只相对于这次 `evaluation_at`：

- 任一份快照的 `as_of` 晚于 `evaluation_at`：未来时间戳，拒绝新增风险。
- `evaluation_at - as_of` 超过该输入在政策里声明的 SLA：拒绝新增风险。
- 决策、账户、行情的 `as_of` 彼此之差超过政策里声明的错时上限：拒绝新增风险。
- SLA 或错时上限在政策中为 `null`：政策不完整，按 §11.5 失败关闭。不发明默认时限。

账户与行情各带 `source`：`SYNTHETIC`、`UNVERIFIED`、`AUTHORITATIVE`。缺 `source` 视同不能证明权威。夹具只能标 `SYNTHETIC`。把 `status` 写成 `KNOWN` 或把 `freshness` 写成 `ok`，都不能把 `source` 升成 `AUTHORITATIVE`。

本阶段不核对真实账本或交易所，因此即使调用方填写 `AUTHORITATIVE`，记录上的账户权威仍是 `NOT_ESTABLISHED`。`SYNTHETIC` 可以产生供测试阅读的计划，但不能被读成当前实盘资格。

### 11.3 R31-P3 只追加

计划行写完后不可 `UPDATE`。不得把旧行改成 `STALE`。

失效用追加的失效事件表达；读取方也可以用内容身份和 `evaluation_at` 派生某条旧记录已不是当前评估。两种做法都不改旧行。

落盘的是裁决记录，不是调用回执。记录里没有 `idempotent`、`wrote_now`、`record_present`。同评估内容身份重放时，记录字节保持不变，包括允许值。

回执每次调用单独产生，不写回记录：

- `record_present`：所引用的完整裁决记录是否已经存在。
- `wrote_now`：本次调用是否新写入了该记录。首次成功为 true，重放为 false。
- `idempotent`：本次命中已有记录且没有改它的字节。重放为 true，首次成功为 false。

因此首次与重放可以逐字节相同，同时回执仍能区分两次调用。`record_present` 不表示「这次新写成功」；`wrote_now` 不表示「旧记录还在不在」。

冲突时旧记录保持 `record_present=true`，本次 `wrote_now=false`。写失败时这次尝试没有记录：`record_present=false`，`wrote_now=false`。两种回执都不是一条新的有效 `PASS`。

合法新版本或新的评估时点，在 §11.1 允许独立裁决时，按它自己的请求和政策裁决。它的允许值可以高于另一次输入的允许值。同一次裁决内部仍须 `allowed_new_risk <= requested_new_risk`。

### 11.4 R31-P4 保护不循环

分开两件事：

- 现有仓位的保护状态。
- 拟新增仓位所要求的保护。

没有可验证的现有仓位时，不得为了让首次计划存在而假装现有保护已经 `ACTIVE_CONFIRMED`。现有仓位不存在，只使现有仓位保护为 `NOT_APPLICABLE`，不能免除拟新增仓位的保护要求。

拟新增仓位的保护未满足时，包括首次开仓，可以形成条件性计划：请求对照仍在，`new_risk_allowed=false`，`execution_eligibility=DENIED`。不得标成允许新增风险，也不得因此进入 `PASS`。

持仓未知、或仓位存在但保护不是 `ACTIVE_CONFIRMED`，都不能把现有仓位保护标成 `NOT_APPLICABLE`。已有未保护仓位拒绝新增风险。纯防守没有拟新增仓位，不借用这条保护要求取消防守意图；执行资格仍然是 `DENIED`。防守数量在持仓未知时仍是 `UNAVAILABLE`。

### 11.5 R31-P5 状态、数值、写失败

一条输入只取表中最先命中的状态。其余命中的原因全部列入 `blockers`，但不改这一个状态。

| 顺序 | 条件 | `risk_state` | `new_risk_allowed` | 本次 `wrote_now` |
|---|---|---|---|---|
| 1 | 版本声明冲突，或计划日志写不进去 | `BLOCK_NEW_RISK` | false | false。冲突不覆盖旧绑定 |
| 2 | NaN、Infinity、单位不符、符号不符、超出声明范围 | `BLOCK_NEW_RISK` | false | false |
| 3 | 政策不完整，或 `parameter_status` 不是 `PROVISIONAL_E3_PARAM` | `BLOCK_NEW_RISK` | false | false |
| 4 | 单调性检查失败 | `BLOCK_NEW_RISK` | false | false |
| 5 | kill 或 incident 活跃 | `BLOCK_NEW_RISK`；若同时有防守意图，则为 `DEFENSIVE_ONLY` | false | 仅当整行写完 |
| 6 | 账户、行情、净值未知，或 §11.2 的时间规则失败 | `BLOCK_NEW_RISK` | false | 仅当整行写完 |
| 7 | 持仓未知 | `BLOCK_NEW_RISK`；防守数量为 `UNAVAILABLE` | false | 仅当整行写完 |
| 8 | 请求含新增风险，且拟新增仓位的保护未满足。可验证无现有仓位不能跳过本行 | `BLOCK_NEW_RISK`，计划标明 `PROTECTION_UNMET` | false | 仅当整行写完 |
| 9 | 其余，由 `evaluate_risk` 给出。纯防守不在本行变成 `PASS` | `PASS` 或 `REDUCED`；纯防守为 `DEFENSIVE_ONLY` | 仅 `PASS` / `REDUCED` 按合同；纯防守为 false | 仅当整行写完 |

出现在字段里的合法 `0` 是已知零，不是未知，也不是缺失。未知只来自 `null`、空串或然缺键。

上述任何一行的 `risk_state` 都不是一条可执行资格。`submit_allowed`、`order_intent`、`execution_eligibility` 的固定值不变。
