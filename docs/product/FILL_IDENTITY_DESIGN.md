# FILL IDENTITY & ECONOMIC COMPLETENESS — 设计 v3（仅评审稿，未实现）

> 状态：**DESIGN-REVISED / 待评审**（v2 收到 CHANGES-REQUIRED；本版
> 仅补三份材料，不实现、不迁移真实账本、不接 funding、不动权限。
> R1–R4 既有通过结论不变。）
> v2→v3 变更摘要：A) 具体 SQLite DDL + 迁移事务与失败回滚（§1.2
> 重写）；B) 类型化引用映射表，定位历史行≠确认身份（§1.3 重写）；
> C) 费用有效投影判定表：幂等/冲突/只扣一次/精度边界（§2.3 扩成
> §3）；D) 测试目录增补 NULL 唯一性/引用串型/投影/迁移回滚/
> FK+CHECK 两类。

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

### 1.2 存储方案：具体 SQLite DDL 与迁移事务

现行 `fill_id TEXT PRIMARY KEY` 无法容纳跨 symbol 同 ID。迁移为
**表重建**（SQLite 无法改主键）。

**新表 DDL（fills_v2，原子改名前的临时名）**：

```sql
CREATE TABLE fills_v2 (
    fill_id          TEXT    NOT NULL,
    symbol           TEXT,              -- NULL=历史身份未解析（仅迁移行；
                                       --   新事件 NOT NULL 由入口层保证+T-I4）
    client_order_id  TEXT    NOT NULL
                     REFERENCES orders(client_order_id),
    qty              REAL    NOT NULL,
    price            REAL    NOT NULL,
    fee              REAL,              -- 兼容列；有效性判定见 §3（fee_raw）
    fee_raw          TEXT,              -- 交易所原始费用串；新事件必填
    fee_asset        TEXT,              -- NULL=UNKNOWN（历史）；新事件必填
    realized_pnl     REAL    NOT NULL DEFAULT 0,
    derivation_ctx   TEXT,              -- JSON；历史 NULL ≡ LEGACY_V0
    side             TEXT    NOT NULL,
    filled_at        TEXT    NOT NULL,
    synthetic        INTEGER NOT NULL DEFAULT 0,
    replaces_synthetic_fill_id TEXT,
    covered_by_fact_id        TEXT,
    quantity_effect_applied   INTEGER NOT NULL DEFAULT 1,
    economic_effect_applied   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (symbol, fill_id)
);
-- NULL symbol 的唯一性钉子：SQLite PK 对 NULL 不去重，
-- 用部分唯一索引保证同一 trade_id 至多一行未解析历史行。
CREATE UNIQUE INDEX ux_fills_null_symbol
    ON fills_v2 (fill_id) WHERE symbol IS NULL;
```

要点：
- **不加 `UNIQUE(fill_id)` 单列约束**——那会重新禁止跨 symbol 同 ID
  （违背 T-I1）；跨 symbol 存储由复合 PK 承载，NULL 历史行的防重
  由部分唯一索引承载。
- 历史行 `fee=0.0`（旧默认值）**无法区分真零与未知** → 迁移不回填
  fee_raw，历史费用一律按 §3 判 UNKNOWN（fail-closed 方向）。

**迁移事务（单事务，失败整体回滚）**：

```sql
PRAGMA foreign_keys=OFF;            -- 表交换期间暂停 FK
BEGIN IMMEDIATE;
  CREATE TABLE fills_v2 (...);      -- 上述 DDL
  INSERT INTO fills_v2 (逐列清单)
      SELECT 逐列清单 FROM fills;   -- 历史行零改写（symbol/fee_raw/
                                   --   fee_asset/derivation_ctx 置 NULL）
  -- 事务内校验：行数一致 + 逐行内容抽样校验和一致，不符→ROLLBACK
  DROP TABLE fills;                 -- 无表 FK 指向 fills（已核实：
                                    --   reconciliation_facts 为 JSON 载荷）
  ALTER TABLE fills_v2 RENAME TO fills;
  CREATE UNIQUE INDEX ux_fills_null_symbol
      ON fills (fill_id) WHERE symbol IS NULL;
  INSERT OR REPLACE INTO schema_meta (key, value)
      VALUES ('fills_identity_version', '3');   -- 标记与数据同事务
COMMIT;
PRAGMA foreign_keys=ON;
```

- **失败回滚**：任何一步失败 → `ROLLBACK` → 原 fills 表与无标记
  状态原样保留，可安全重试；标记写在事务内，杜绝"迁移成功但无
  标记"或"有标记但未迁移"的中间态。
- **幂等重开**：打开时读 `schema_meta.fills_identity_version`，
  `'3'` 即跳过（T-M2）。
- **迁移失败注入测试**（T-M4）：事务中途失败（CHECK 违约注入）→
  原表逐字节语义不变、无标记、可重试成功。
- 事故账本本轮不迁移；真实迁移仅在对副本演练（T-M3）通过且
  评审放行后另行授权。

### 1.3 类型化引用映射表（定位 ≠ 确认身份）

四类引用，载体、形态与消解规则各自定义：

| # | 引用类型 | 载体 | 历史形态 | 新形态 | 消解规则 |
|---|---|---|---|---|---|
| R1 | venue 成交引用 | `reconciliation_facts.covered_fill_ids[]` | 裸 trade_id | **必须** `symbol:trade_id` | 裸 ID：唯一 symbol 命中→可定位；唯一 NULL 行→可定位；多命中→UNRESOLVED 告警（不猜） |
| R2 | 合成替换 | `fills.replaces_synthetic_fill_id` | 裸 trade_id | **必须** `symbol:trade_id` | 同 R1 定位；定位后要求替换行与被替换行 symbol 一致，否则 REPLACEMENT_ANOMALY 隔离 |
| R3 | 证据覆盖 | `fills.covered_by_fact_id` | fact_id（指向 `reconciliation_facts`，**本就不是 fill 引用**） | 不变 | 直查 facts 表；不参与 fill 消解（类型不同） |
| R4 | 费用补充 | `fill_fee_supplements.fill_ref`（新表，§3） | 无（新表） | **必须** `symbol:trade_id`，裸 ID 拒收 | 限定引用直查 |

**定位 ≠ 确认身份（冻结规则）**：

```text
裸 ID 定位到 NULL-symbol 历史行 → 得到一个【审计位置】：
  ✗ 不把该行 symbol 升级为已知
  ✗ 不据此对后续同 trade_id 事件判 DUPLICATE / 收养 / 重复入账
  ✓ 仅允许作为审计链接展示
后续同 trade_id 带 symbol 事件 → 仍走 IDENTITY_UNRESOLVED（T-R2）
历史身份的正式裁决 = 独立操作员处置流程（本轮不设计，登记待办）
```

新引用串型校验：写入侧强制 `^[^:]+:.+$`（symbol 非空 + trade_id
非空）；不合规拒收（T-R1c）。

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
精度边界在 §3.4 单独冻结。

## 3. 费用有效投影判定表（v3 新增独立章节）

### 3.1 概念

- **基线费用**：fills 行自身的费用状态（KNOWN=有 fee_raw；
  UNKNOWN=无 fee_raw——含全部历史行，见 §1.2）。
- **补充事实**：`fill_fee_supplements` 行——后到的费用观察，
  自带稳定事件 ID（venue tranId 优先；无稳定 ID 拒收，与
  funding_income 同纪律）、fee_raw_s、fee_asset_s、observed_at、
  fill_ref（必须 `symbol:trade_id`）。
- **有效费用（effective fee）**：投影判定表的输出——会计与风险
  层唯一允许使用的费用值。

### 3.2 判定表（冻结）

| 基线 | 补充事实 | 判定 | 有效费用与投影动作 |
|---|---|---|---|
| KNOWN(V0) | 无 | KNOWN | 投影 V0，恰好一次 |
| UNKNOWN | 无 | **INCOMPLETE** | **不投影**；费用视 UNKNOWN（非 0）；相关损益标"费用不可依赖" |
| UNKNOWN | 单条 KNOWN(S1) | KNOWN(S1) | 投影 S1，恰好一次（补充幂等键防重放） |
| UNKNOWN | 多条且规范化一致 | KNOWN(S) | 投影一次 |
| 任意 | 多条互相冲突 | **FEE_CONFLICT** | 不投影；告警；**不取先到/后到/均值** |
| KNOWN(V0) | KNOWN(S1) 且 S1≠V0（规范化后） | **FEE_CONFLICT** | 保留 V0 原值；不覆盖；告警；损益 UNRELIABLE |
| UNKNOWN | UNKNOWN | **INCOMPLETE** | 仍未知——**非 0、非完整重复、非冲突** |

### 3.3 只扣一次（deduct-once）机制

```text
fill_fee_projection 表：
  fill_ref        TEXT PRIMARY KEY     -- symbol:trade_id
  state           TEXT                 -- PROJECTED / CONFLICTED / PENDING
  effective_raw   TEXT                 -- Decimal 原文（投影依据）
  source          TEXT                 -- base 或 supplement 稳定ID
  projected_at    TEXT
  derivation_ctx  TEXT                 -- 与 §2.1 同构的投影上下文

规则：
  每条成交至多一行投影记录（主键保证）
  投影发生后新补充到达 → 不二次扣；触发【显式费用重算事件】
  （append-only，引用旧投影；与 §2.1 推导纪律同构）
  CONFLICTED 状态 → 拒绝投影；依赖费用的风险量按 UNKNOWN 处理
  （阻断新增风险；不设持仓 UNKNOWN；不阻减仓——与 §2.2 同界）
```

### 3.4 精度边界（原始串 vs 历史 float）

```text
比较与投影运算：仅 Decimal(normalize(原始串))；
  "-0.400" ≡ "-0.4"（规范化相等，T-F4）

基线 KNOWN 的唯一条件 = fee_raw IS NOT NULL：
  历史行（迁移置 NULL）→ 基线一律 UNKNOWN
  → 历史浮点 fee 值【永不参与比较或求和】，杜绝
    float 伪差与"0 默认值冒充真零"两类污染（fail-closed 双向）

新事件缺 fee_raw/fee_asset → 拒收（与 T-I4/T-F3 同口）
投影金额以原始串形态存 effective_raw，Decimal 运算，
不再写回任何 float 列
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

**NULL 唯一性与引用串型（3，v3 增）**
- T-N1 同 trade_id 两行 NULL symbol 被 ux_fills_null_symbol 阻止；
       NULL+非NULL 共存允许（跨 symbol 存储不受伤）
- T-R1a 新写入 R1/R2/R4 引用必须 `symbol:trade_id`（裸 ID 拒收）
- T-R1b 裸 ID 消解三分支（唯一命中/唯一 NULL 行/多命中告警）
- T-R2  定位≠身份：裸 ID 定位到 NULL 行后，同 trade_id 带 symbol
       事件仍 IDENTITY_UNRESOLVED——不收养、不判 DUPLICATE

**费用投影（4，v3 增）**
- T-FP1 UNKNOWN+单补充→投影恰好一次；补充重放幂等（稳定 ID）
- T-FP2 双 UNKNOWN→INCOMPLETE：不投影、不写 0、不判重复
- T-FP3 KNOWN vs 冲突补充→FEE_CONFLICT：原值保留不覆盖
- T-FP4 投影后补充到达→显式费用重算事件，绝不二次扣

**迁移回滚与 DB 错误两类（2+1，v3 增）**
- T-M4 迁移中途失败（CHECK 违约注入）→ ROLLBACK：原表原样、
       无版本标记、可重试成功
- T-DB2 FK 违约与 CHECK 违约**分别**上抛且可区分（错误码/类），
       两类均不得吞成 DUPLICATE（T-DB1 的细化）

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
测试目录 v3 = 30 项（v2 23 + v3 增补 7：T-N1/T-R1a/T-R1b/T-R2/
T-FP1-4 中 4 项/T-M4/T-DB2）是否充分。
