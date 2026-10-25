# FILL IDENTITY & ECONOMIC COMPLETENESS — 设计 v2（仅评审稿，未实现）

> 状态：**DESIGN-REVISED / 待评审**（v1 收到 CHANGES-REQUIRED；本版仅
> 修订设计，不实现、不迁移、不接 funding、不动权限）。
> v1→v2 变更摘要：① 跨 symbol 规则反转 + 复合身份的存储/引用/迁移
> 方案成文；② 三分类补三条约束（推导上下文冻结、DEVIATION 处置、
> 已知/未知比较表 + Decimal 规范化比较，撤回 1e-9 容差）；
> ③ 测试目录按评审表重写；元测试改口径。

## 0. 术语修正

- `account_fingerprint` 在本设计中仅为**凭证命名空间代理**
  （credential-namespace proxy）——它把账本物理隔离到
  `state/<mode>/<fingerprint>/`，但**不是稳定账户身份**。密钥轮换后
  的账本连续性另案设计，本设计不依赖指纹的跨密钥稳定性。

## 1. 身份作用域（v2 修正：跨 symbol 规则反转）

### 1.1 完整身份键与判定规则（冻结提案）

```text
完整身份键 = 命名空间（mode + 凭证命名空间代理，结构性）
           + symbol
           + exchange_trade_id

判定：
  同完整身份键 + 事实内容不同        → IDENTITY_CONFLICT
  不同完整身份键（如跨 symbol 同ID） → 独立事件；随后做订单归属检查
  事件 symbol 与所属订单 symbol 不符 → ATTRIBUTION_ANOMALY：隔离
                                       （不入账）+ 熔断 + 告警
```

v1 的矛盾已修正：symbol 既然入键，`BTCUSDT/trade=123` 与
`ETHUSDT/trade=123` 就是两个不同身份，可各自独立存储；"错绑订单"
才是隔离熔断的触发条件，而非 trade ID 撞号。

### 1.2 存储方案：复合主键（不能"仅加两列"）

现行 `fill_id TEXT PRIMARY KEY` 无法容纳跨 symbol 同 ID。迁移为
**表重建**而非加列：

```text
fills_v2:
  PRIMARY KEY (symbol, fill_id)
  新列：symbol TEXT（历史行 NULL，不回填）
        fee_asset TEXT（同上）
        fee_raw TEXT（新事件的交易所原始费用串；见 §2.3）
        derivation_ctx TEXT（JSON，见 §2.1）
  其余列原样复制；历史行零改写
迁移步骤：建 v2 表 → 复制 → 原子改名 → schema 版本标记
幂等性：标记存在则二次打开为 no-op（迁移完整性测试覆盖）
事故账本本轮不迁移（设计冻结前不动任何真实账本）
```

### 1.3 内部引用的消解规则

既有引用（`reconciliation_facts.covered_fill_ids`、
`replaces_synthetic_fill_id`、`covered_by_fact_id`）是裸 fill_id：

```text
裸 ID 消解：目标 symbol 唯一或历史 NULL 行 → 可解析
           多 symbol 命中 → 引用未解析 → 告警（不猜）
新写入引用：一律限定形式 "symbol:fill_id"
```

## 2. 三分类（接受 + 三条约束）

| 类别 | 字段 | 语义 |
|---|---|---|
| 交易所事实 | symbol, side, qty, price, fee, fee_asset | 同完整身份下已知值冲突 → IDENTITY_CONFLICT |
| 本地推导 | realized_pnl | 同推导上下文不一致 → DERIVATION_DEVIATION（非身份冲突） |
| 记账属性 | synthetic / covered_by_fact_id / economic_effect | 不参与身份比较，仍受账本不变量约束 |

### 2.1 推导上下文冻结（约束1）

**禁止用"当前入场均价"重算历史 PnL。** 每条推导记录其上下文：

```text
derivation_ctx = { derivation_version,      # 计算公式版本
                   entry_order_id,           # 入场成本依据（订单ID）
                   entry_basis_snapshot }    # 依据当时的均价快照
```

- 校验一致性 = 在**同一 ctx** 下重算并比对；
- 入场依据事后变化（如迟到成交修正均价）→ **显式重算事件**
  （append-only `fill_recomputations`，引用旧值，不覆盖历史行），
  语义是"依据演进"，不是"非确定性缺陷"；
- 不同 derivation_version 的结果差异同样走显式重算，不判 DEVIATION。

### 2.2 DEVIATION 处置（约束2）

```text
DERIVATION_DEVIATION 发生时：
  保留原值；不重复入账；不改写历史
  受影响的已实现损益标记为 UNRELIABLE
  下游后果：依赖该损益的风险预算视为 UNKNOWN → 阻断新增风险
  边界：不把真实持仓标 UNKNOWN；不阻断减仓/平仓（CLOSE 永不被
  OPEN 侧条件反向阻断的既有纪律同样适用）
```

### 2.3 已知/未知比较表 + Decimal（约束3）

费用的 UNKNOWN **既非冲突也非完整重复**。字段状态机：

```text
比较(a, b)：
  KNOWN  vs KNOWN    → 规范化 Decimal 相等性（见下）；不等=冲突
  KNOWN  vs UNKNOWN  → INCOMPLETE（任何方向：未知不得覆盖已知；
                       也不得据此宣告完整 DUPLICATE）
  UNKNOWN vs UNKNOWN → 该字段匹配，但整体判定仍受其他字段约束

INCOMPLETE 时：原行不动；后到的已知值以【追加补充事实】入账
（fill_fee_supplements，引用成交，不修改历史行）
```

**比较算子**：撤销 v1 的固定 `1e-9`。采用规范化 Decimal 比较——

```text
双方均持交易所原始串（fee_raw）→ Decimal(normalize(raw)) 精确相等
任一方为历史浮点值 → Decimal(str(value)) 精确相等（fail-closed：
   浮点串化伪差会以冲突形式暴露，方向安全）
精度依据：费用精度由交易所按结算资产的小数位以字符串下发，
   因此以字符串→Decimal 为唯一权威表示；不引入人为 epsilon
```

## 3. 统一校验器（不变 + 元测试口径修正）

```text
ledger.fill_content_mismatch(stored, incoming) -> MatchReport
    唯一实现；字段集与比较算子（§2.3）单一来源
两个入口（apply_fill_event / insert_fill）必须调用它
```

元测试口径修正（v1 的"orchestrator 不得出现 abs()"作废）：

```text
元测试 = 断言两入口对同一输入产生同一 MatchReport，
        并静态断言 orchestrator 的成交重放路径调用
        ledger.fill_content_mismatch（调用关系，而非禁用算术）
```

## 4. 错误处理边界（新增，源自评审测试表）

- **DB 约束错误不得吞成 DUPLICATE**：`IntegrityError` 分支必须区分
  "唯一键冲突"（走身份比较）与 "FK/CHECK 违约"（向上抛出，绝不
  静默 False）。v1 实现路径存在此隐患，已列入测试 T-DB1。
- **并发写入**：同身份并发一致重放恰好入账一次（复合主键 +
  事务）；冲突路径必须抛出/熔断，不得静默丢失。

## 5. 测试目录 v2（实现前冻结）

**身份与归属（7）**
- T-I1 同 trade ID 跨 symbol：两身份独立存储、各自入账成功
- T-I2 跨 symbol 同 ID + 错绑订单（事件 symbol ≠ 订单 symbol）→
       ATTRIBUTION_ANOMALY：隔离不入账 + 熔断
- T-I3 同完整身份逐字段变异矩阵（cid/side/qty/price/fee/fee_asset
       六维）→ 两入口结果逐项一致（同一 MatchReport）
- T-I4 新事件缺 symbol → 拒收（两入口）
- T-I5 历史行 symbol=NULL + 同 trade ID 重放 → IDENTITY_UNRESOLVED：
       不判 DUPLICATE、不收养、不重复入账 → 隔离告警
- T-I6 历史行参与比较不崩溃；NULL 字段本身不构成冲突源
- T-I7 跨命名空间同 (symbol, trade ID)：结构性互不可见（回归钉）

**推导（4）**
- T-D1 同 derivation_ctx 重算一致 → DUPLICATE 正常
- T-D2 同 ctx 不一致 → DERIVATION_DEVIATION：原值保留、损益
       UNRELIABLE、阻断新增风险、不设持仓 UNKNOWN、不阻减仓
- T-D3 entry 依据变化（迟到成交改均价）→ 显式重算事件追加，
       历史行与旧值不被覆盖
- T-D4 不同 derivation_version → 显式重算路径，不判 DEVIATION

**费用与非法输入（4）**
- T-F1 fee/fee_asset 变异 → 冲突（T-I3 的子项，独立可读）
- T-F2 fee UNKNOWN：INCOMPLETE 语义——不冲突、不完整重复、原行
       不动；后到已知值走补充事实追加，历史行零修改
- T-F3 qty/price/fee 的 NaN/Infinity/非法串 → 拒收（两入口）
- T-F4 Decimal 规范化：`"-0.400" vs "-0.4"` 相等；浮点串化伪差
       以冲突暴露（fail-closed 方向验证）

**数据库与并发（3）**
- T-DB1 FK 违约（引用不存在订单）→ 异常上抛，不吞成 DUPLICATE
       （v1 隐患的钉子）
- T-C1 并发同身份一致重放：恰好一条入账（复合主键 + 事务）
- T-C2 并发冲突路径：抛出/熔断可见，无静默丢失

**迁移完整性（3）**
- T-M1 表重建迁移：历史行内容逐字段不变（qty/price/pnl/kill 等）
- T-M2 重复打开幂等（schema 标记）；引用消解按 §1.3
- T-M3 事故账本【副本】演练迁移：kill=1、引用、数量、损益不变

**元与回归（2）**
- T-X1 元测试：两入口调用同一校验器且同输入同 MatchReport
- T-X2 既有 W43 冲突测试在统一校验器下不改断言全绿

## 6. NON-GOALS（不变 + 重申）

不实现（本轮只交设计）；不迁移任何真实账本；不接 funding；不做
密钥轮换连续性（指纹=凭证命名空间代理，另案）；不做崩溃注入；
不动 TRADING AUTHORITY。

## 7. 评审请求

① §1.1 判定规则三分支与 §1.2/1.3 存储引用方案；② §2 三条约束的
落地语义（尤其 T-D2 的风险边界与 T-F2 的补充事实不回改）；③ §5
23 项测试目录是否充分。
