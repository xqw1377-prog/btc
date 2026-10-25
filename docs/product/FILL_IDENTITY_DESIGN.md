# FILL IDENTITY & ECONOMIC COMPLETENESS — 设计 v4（仅评审稿，未实现）

> 状态：**DESIGN-REVISED / 待评审**（v3 收到 CHANGES-REQUIRED F1–F6；
> 本版逐条闭合，不实现、不迁移真实账本、不接 funding、不动权限。
> R1–R4 既有通过结论不变。）
> v3→v4 摘要：F1 索引只建一次+失败恢复 FK+提交前 foreign_key_check；
> F2 补真实 CHECK 约束与 origin 列（LEGACY/EVENT 区分入 DDL）；
> F3 covered_by_fact_id 现行实际写读映射成表（含 replaced-by: 标记）
> +引用目标存在性/类型校验；F4 费用规则统一为"可入账 INCOMPLETE、
> 仅 KNOWN 声明强制 raw+asset"，双 UNKNOWN 口径同步修正；F5 只扣
> 一次证明链（补充稳定 ID 唯一键/投影版本/记账效果幂等键/单事务
> 边界/delta 重算语义）；F6 精度统一为原始串有限 Decimal 数值相等
> （去 normalize，历史近似不比不投影）；另：迁移全量等价核验+
> 重开结构验证；测试目录唯一编号（含补录 T-R1c），取消手算总数。

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

### 1.2 存储方案：具体 SQLite DDL 与迁移事务（F1/F2 修正）

现行 `fill_id TEXT PRIMARY KEY` 无法容纳跨 symbol 同 ID。迁移为
**表重建**（SQLite 无法改主键）。

**最终表 DDL（索引只在迁移事务内建一次，见 F1）**：

```sql
CREATE TABLE fills (
    fill_id          TEXT    NOT NULL,
    symbol           TEXT,
    origin           TEXT    NOT NULL DEFAULT 'LEGACY'
                     CHECK (origin IN ('LEGACY','EVENT')),
    client_order_id  TEXT    NOT NULL
                     REFERENCES orders(client_order_id),
    qty              REAL    NOT NULL CHECK (qty > 0),
    price            REAL    NOT NULL CHECK (price > 0),
    fee              REAL,
    fee_raw          TEXT,
    fee_asset        TEXT,
    realized_pnl     REAL    NOT NULL DEFAULT 0,
    derivation_ctx   TEXT,
    replaced_by      TEXT,              -- R2 新写入口（§1.3）；历史为 NULL
    side             TEXT    NOT NULL CHECK (side IN ('BUY','SELL')),
    filled_at        TEXT    NOT NULL,
    synthetic        INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0,1)),
    replaces_synthetic_fill_id TEXT,
    covered_by_fact_id        TEXT,
    quantity_effect_applied   INTEGER NOT NULL DEFAULT 1
                              CHECK (quantity_effect_applied IN (0,1)),
    economic_effect_applied   INTEGER NOT NULL DEFAULT 1
                              CHECK (economic_effect_applied IN (0,1)),
    PRIMARY KEY (symbol, fill_id),
    -- F2：约束把"新事件 vs 历史行"写进 schema，不靠入口注释：
    CHECK (origin = 'LEGACY' OR symbol IS NOT NULL),          -- 新事件必带 symbol
    CHECK (fee_raw IS NULL OR (fee_raw != '' AND fee_asset IS NOT NULL
                               AND fee_asset != ''))           -- 声明 KNOWN 费用
                                                                -- 必须有合法非空串+资产
);
-- 唯一索引：只在迁移事务内创建一次（F1：不再出现在建表 DDL 中）
-- CREATE UNIQUE INDEX ux_fills_null_symbol
--     ON fills (fill_id) WHERE symbol IS NULL;
```

**CHECK 约束与对应错误场景（T-DB2/T-M4 的注入面）**：

| 约束 | 违约场景（测试注入） | 期望 |
|---|---|---|
| `qty>0` / `price>0` | 0、负数、NaN/Inf 串 | IntegrityError(CHECK) 上抛，不吞 DUPLICATE |
| `side IN ('BUY','SELL')` | 'buy'/'LONG'/空 | 同上 |
| `origin IN (...)` | 未知 origin | 同上 |
| `origin='EVENT'→symbol NOT NULL` | 新事件缺 symbol | CHECK 拒绝（schema 级，先于入口层） |
| `fee_raw→非空+fee_asset 非空` | 有 raw 无 asset / 空串 | 同上（F4：fee_raw=NULL 合法=INCOMPLETE） |
| FK `client_order_id→orders` | 引用不存在订单 | IntegrityError(FK) 上抛且与 CHECK 可区分 |
| `ux_fills_null_symbol` | 同 trade_id 二行 NULL | IntegrityError(UNIQUE) 走身份比较路径 |

**迁移事务（F1：索引单次创建；失败恢复 FK；提交前 FK 完整性检查；
核验=全量等价而非抽样）**：

```text
01  old_fk = PRAGMA foreign_keys          -- 记录进入前状态
02  PRAGMA foreign_keys=OFF
03  BEGIN IMMEDIATE
04      CREATE TABLE fills_new (...上述 DDL...)
05      INSERT INTO fills_new (旧列全列, origin='LEGACY',
              symbol=NULL, fee_raw=NULL, fee_asset=NULL,
              derivation_ctx=NULL, replaced_by=NULL)
          SELECT 旧列全列 FROM fills
06      -- F 材料修正：全量等价核验（非抽样）——旧列集上双向 EXCEPT
07      -- 必须为空；不为空 → 显式 ROLLBACK
08      CREATE UNIQUE INDEX ux_fills_null_symbol
            ON fills_new (fill_id) WHERE symbol IS NULL   -- 只建这一次
09      DROP TABLE fills
10      ALTER TABLE fills_new RENAME TO fills
11      INSERT OR REPLACE INTO schema_meta(key,value)
            VALUES ('fills_identity_version','4')
12      -- F1：提交前 FK 完整性检查（事务内）
13      IF EXISTS (PRAGMA foreign_key_check) → ROLLBACK
14  COMMIT
15  PRAGMA foreign_keys=ON                 -- 无条件恢复
16  IF old_fk == 1: 断言 PRAGMA foreign_keys 现为 1（恢复验证）
17  重开验证：schema_meta=4 且结构断言（PK 列序、索引存在、
      CHECK 存在）符合版本，否则拒绝打开（SafetyViolation）
```

- **失败回滚**：任何一步失败 → ROLLBACK → 原表、无索引残留（索引
  在事务内创建，随回滚消失）、无标记；**foreign_keys=ON 的恢复放
  在 try/finally 语义层**（伪代码 15–16 行），即使 ROLLBACK 抛错
  也执行并验证。
- **幂等重开**：读标记=4 → 跳过迁移；但**仍执行结构验证**（17 行），
  标记与结构不符 = 拒绝打开。
- 历史 `fee=0.0` 无法辨真零 → 迁移不回填 fee_raw，历史费用一律按
  §3 判 UNKNOWN。
- 事故账本本轮不迁移；真实迁移仅在对副本演练通过且评审放行后
  另行授权。

### 1.3 类型化引用映射表（F3：以现行代码实际写读为准）

**现行代码取证**（ledger.py / orchestrator.py）——`covered_by_fact_id`
存在**三种实际值形态**，不能断言它只指向 facts 表：

| 现行写入点 | 值形态 | 含义 |
|---|---|---|
| `insert_fill(covered_by_fact_id=fact_id)`（orchestrator COVERED_BY_FACT 路径） | 真实 fact_id | 证据覆盖链接（R3） |
| `mark_synthetic_replaced()` | `'replaced-by:' + 真实fill_id` | 合成替换标记（**借用了本列**，非 fact 引用） |
| 其余 | NULL | 无 |

**类型化引用映射表 v4**：

| # | 引用类型 | 载体（现行→目标） | 历史形态与兼容 | 新形态 | 消解与校验 |
|---|---|---|---|---|---|
| R1 | venue 成交引用 | `reconciliation_facts.covered_fill_ids[]` | 裸 trade_id | `symbol:trade_id` | 裸 ID 三分支（唯一命中/唯一NULL行/多命中告警）；**新写入校验目标存在**（按限定键查 fills），不存在→拒收，非仅正则 |
| R2 | 合成替换 | 现行：`replaces_synthetic_fill_id`（裸）+ `covered_by_fact_id='replaced-by:X'`（借用） | 借用标记**只读兼容**：解析器识别 `replaced-by:` 前缀→按 R2 语义处理，不迁移不改写 | 新写入口统一走新列 `replaced_by`（`symbol:trade_id`） | 定位后 symbol 一致性校验；不一致=REPLACEMENT_ANOMALY |
| R3 | 证据覆盖 | `covered_by_fact_id` | **混合列**：真实 fact_id 与 `replaced-by:` 标记并存 → 消解器先按前缀分流（标记→R2；其余→R3） | 新写入**禁止**再写 `replaced-by:` 形态到本列（入口层强制），R3 仅写真实 fact_id | R3 消解=直查 reconciliation_facts 且 fact 存在；缺失→悬空引用告警 |
| R4 | 费用补充 | `fill_fee_supplements.fill_ref`（新表 §3） | 无 | `symbol:trade_id`，裸 ID 拒收 | 目标存在性校验同 R1 |

**引用通用校验（超出正则）**：写入前按引用类型查询目标表确认
存在且类型正确；读取消解同样回查——**格式合规但目标不存在 =
悬空引用**，新写入拒收、历史悬空告警不猜。

**定位 ≠ 确认身份（v3 冻结规则不变）**：

```text
裸 ID 定位到 NULL-symbol 历史行 → 审计位置：
  ✗ 不升级 symbol  ✗ 不判 DUPLICATE/收养/重复入账  ✓ 仅审计链接
后续同 trade_id 带 symbol 事件 → 仍 IDENTITY_UNRESOLVED（T-R2）
历史身份正式裁决 = 独立操作员处置流程（登记待办）
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
比较(a, b)（F4 口径修正）：
  KNOWN  vs KNOWN    → 有限 Decimal 数值相等（§3.4）；不等=冲突
  KNOWN  vs UNKNOWN  → INCOMPLETE（任何方向：未知不覆盖已知；
                       也不据此宣告完整 DUPLICATE）
  UNKNOWN vs UNKNOWN → INCOMPLETE（该字段【不可证实】——不算"匹配"，
                       不计入确认相等；整体永不因此字段判 DUPLICATE）

INCOMPLETE 时：原行不动；后到的已知值以【追加补充事实】入账
（fill_fee_supplements，引用成交，不修改历史行）

费用入账规则（F4 冻结，取代 §3.4 旧句"缺 fee_raw 拒收"）：
  成交事实允许在费用 INCOMPLETE（fee_raw=NULL）状态下入账；
  只有【声明 KNOWN】（提供了 fee_raw）才强制要求合法有限 Decimal
  原始串 + 非空 fee_asset（schema CHECK 已同口径）。
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
| UNKNOWN | UNKNOWN | **INCOMPLETE** | 仍未知——非 0、非完整重复、非冲突、亦非"字段匹配"（§2.3 F4） |

### 3.3 只扣一次（deduct-once）：证明链（F5 重写）

单行主键只证明"一行"，不证明"扣费动作恰一次"。补全四层证明链：

```text
(1) 补充事实幂等：fill_fee_supplements.stable_event_id UNIQUE
    （venue tranId 优先，无稳定 ID 拒收）；同 ID 不同内容 →
    FEE_CONFLICT（funding 同纪律）。重放=零行新增。

(2) 投影版本：fill_fee_projection(fill_ref PRIMARY KEY,
    projection_version INTEGER NOT NULL, effective_raw TEXT,
    applied_effect_key TEXT UNIQUE, ...)

(3) 记账效果幂等键：会计/风险层应用费用时写
    effect_key = fill_ref + ':FEE:v' + projection_version
    于收入/调整事实表并 UNIQUE——同一投影版本的完整金额
    【物理上只能应用一次】；重放被键拒绝。

(4) 事务边界（单事务三步）：
    BEGIN IMMEDIATE
      a. INSERT 补充事实（stable_event_id 唯一）
      b. 投影更新（PENDING/旧版本 → 新版本，写 applied_effect_key）
      c. 记账效果写入（effect_key 唯一，金额=本次 delta 或首次全额）
    COMMIT   —— 任一步失败整体回滚，不存在"补充已入而投影未更"
              或"投影已更而费用未扣/重复扣"的中间态
```

**重算语义（delta，非全额重扣）**：

```text
重算事件（append-only）记录：old_effective_raw / new_effective_raw /
  delta_raw = new − old（Decimal 精确差）
记账效果只应用 delta；绝不再扣完整金额。
首次投影（PENDING→v1）= 全额；此后每次重算 = 差额。
projection_version 严格递增；effect_key 携带版本 → 旧版本键
  永不复活，重放历史版本被唯一键拒绝。
```

投影状态机与风险边界（§2.2 同界）：CONFLICTED → 拒绝投影，费用
按 UNKNOWN 阻断新增风险；不设持仓 UNKNOWN；不阻减仓。

### 3.4 精度边界（F6 修正：去 normalize，统一无损语义）

```text
比较算子：Decimal(raw_a) == Decimal(raw_b)
  —— Decimal 数值相等与表示无关：Decimal("-0.400")==Decimal("-0.4")
    为 True，无需 normalize；无舍入、无 epsilon、无损。
  —— 合法性：Decimal(raw).is_finite() 必须成立（NaN/Infinity 拒收）。

基线 KNOWN 的唯一条件 = fee_raw IS NOT NULL（schema CHECK 同口径）：
  历史行（迁移置 NULL）→ 基线一律 UNKNOWN
  历史近似值（float 列 fee）：【保留作展示，永不参与比较、求和、
  投影】——不冒充原始精度（F6：删除 v3"float 串化伪差以冲突暴露"
  的矛盾条款；既然历史 float 从不进入比较，就不存在伪差冲突路径）

投影金额以原始串形态存 effective_raw；一切投影/重算运算在
Decimal 域完成；结果序列化为字符串，不写回 float 列。
```

## 4. 错误处理边界（新增，源自评审测试表）

- **DB 约束错误不得吞成 DUPLICATE**：`IntegrityError` 分支必须区分
  "唯一键冲突"（走身份比较）与 "FK/CHECK 违约"（向上抛出，绝不
  静默 False）。v1 实现路径存在此隐患，已列入测试 T-DB1。
- **并发写入**：同身份并发一致重放恰好入账一次（复合主键 +
  事务）；冲突路径必须抛出/熔断，不得静默丢失。

## 5. 测试目录 v4（唯一编号清单；实现前冻结）

> 计数以本清单为准（机器可数），不再手算汇总。v3 提到未列出的
> T-R1c 已补录；v4 新增 T-M5/T-DB3/T-FP5/T-FP6/T-R3/T-F4R。

**身份与归属**
- T-I1 同 trade ID 跨 symbol：两身份独立存储、各自入账成功
- T-I2 跨 symbol 同 ID + 错绑订单（事件 symbol ≠ 订单 symbol）→
       ATTRIBUTION_ANOMALY：隔离不入账 + 熔断
- T-I3 同完整身份逐字段变异矩阵（cid/side/qty/price/fee/fee_asset
       六维）→ 两入口 MatchReport 逐项一致
- T-I4 新事件缺 symbol → 拒收（入口层 + schema CHECK origin='EVENT'
       双层）
- T-I5 历史行 symbol=NULL + 同 trade ID 重放 → IDENTITY_UNRESOLVED：
       不判 DUPLICATE、不收养、不重复入账 → 隔离告警
- T-I6 历史行参与比较不崩溃；NULL 字段本身不构成冲突源
- T-I7 跨命名空间同 (symbol, trade ID)：结构性互不可见（回归钉）

**推导**
- T-D1 同 derivation_ctx 重算一致 → DUPLICATE 正常
- T-D2 同 ctx 不一致 → DERIVATION_DEVIATION：原值保留、损益
       UNRELIABLE、阻断新增风险、不设持仓 UNKNOWN、不阻减仓
- T-D3 entry 依据变化 → 显式重算事件追加，历史行与旧值不覆盖
- T-D4 不同 derivation_version → 显式重算路径，不判 DEVIATION

**费用与非法输入**
- T-F1 fee/fee_asset 变异 → 冲突（T-I3 子项，独立可读）
- T-F2 费用 UNKNOWN 入账合法（INCOMPLETE）；声明 KNOWN 才强制
       raw+asset（F4 口径；schema CHECK 同验）
- T-F3 qty/price/fee 的 NaN/Infinity/非法串 → 拒收（两入口）
- T-F4 原始串 Decimal 数值相等：`-0.400 ≡ -0.4`；`0.40 ≠ 0.4+1e-300`
- T-F4R（v4 改）历史 float 不参与比较：构造历史近似行 + 新 raw
       事件 → 走 INCOMPLETE/UNRESOLVED 路径，永不产生"float 伪差
       冲突"（F6 语义钉）

**数据库与并发**
- T-DB1 FK 违约（引用不存在订单）→ 异常上抛，不吞成 DUPLICATE
- T-DB2 CHECK 与 FK 两类 IntegrityError 分别上抛且可区分
       （错误码/信息分类器；注入面=§1.2 CHECK 表全行）
- T-C1 并发同身份一致重放：恰好一条入账（复合主键 + 事务）
- T-C2 并发冲突路径：抛出/熔断可见，无静默丢失

**迁移**
- T-M1 表重建迁移：历史行旧列【全列】逐字段不变（双向 EXCEPT 空）
- T-M2 重复打开幂等：标记=4 跳过 + 结构验证（PK/索引/CHECK），
       标记与结构不符 → 拒绝打开
- T-M3 事故账本【副本】演练迁移：kill=1、引用、数量、损益不变
- T-M4 迁移中途失败（CHECK/FK 注入）→ ROLLBACK：原表原样、
       无索引残留、无标记、foreign_keys 状态恢复并验证（F1）
- T-M5（v4）提交前 PRAGMA foreign_key_check 非空 → ROLLBACK；
       事务内索引随回滚消失（F1 单次创建证明）

**NULL 唯一性与引用**
- T-N1 同 trade_id 两行 NULL symbol 被 ux_fills_null_symbol 阻止；
       NULL+非NULL 共存允许
- T-R1a 新写入 R1/R2/R4 引用必须 `symbol:trade_id`（裸 ID 拒收）
- T-R1b 裸 ID 消解三分支（唯一命中/唯一 NULL 行/多命中告警）
- T-R1c 新写入引用目标存在性校验：格式合规但目标不存在 → 拒收
       （补录；v3 提及未列）
- T-R2  定位≠身份：裸 ID 定位 NULL 行后，同 trade_id 带 symbol
       事件仍 IDENTITY_UNRESOLVED
- T-R3 （v4）covered_by_fact_id 历史混合值：`replaced-by:X` 前缀
       分流 R2 语义、真实 fact_id 走 R3、新写入禁用标记形态借列；
       悬空引用（目标不存在）新写拒收/历史告警

**费用投影**
- T-FP1 UNKNOWN+单补充→投影 v1 全额一次；补充重放（同稳定 ID）
       零行新增（F5-1）
- T-FP2 双 UNKNOWN→INCOMPLETE：不投影、不写 0、不判重复
- T-FP3 KNOWN vs 冲突补充→FEE_CONFLICT：原值保留不覆盖
- T-FP4 投影后补充到达→delta 重算事件：只应用差额，绝不二次
       全额（F5 重算语义）
- T-FP5（v4）记账效果幂等键：同 effect_key 重放被 UNIQUE 拒绝；
       旧版本键在重算后不可复活（F5-3）
- T-FP6（v4）三步单事务边界：b 步注入失败 → a 步补充亦回滚
       （无"已补充未投影"中间态）（F5-4）

**元与回归**
- T-X1 元测试：两入口调用同一校验器且同输入同 MatchReport
- T-X2 既有 W43 冲突测试在统一校验器下不改断言全绿

## 6. NON-GOALS（不变 + 重申）

不实现（本轮只交设计）；不迁移任何真实账本；不接 funding；不做
密钥轮换连续性（指纹=凭证命名空间代理，另案）；不做崩溃注入；
不动 TRADING AUTHORITY。

## 7. 评审请求

① §1.1 判定规则三分支与 §1.2/1.3 存储引用方案；② §2 三条约束的
落地语义（尤其 T-D2 的风险边界与 T-F2 的补充事实不回改）；③ §5 测试目录 v4 唯一编号清单（T-I 7/T-D 4/T-F 4+1R/T-DB 2/
T-C 2/T-M 5/T-N 1/T-R 6/T-FP 6/T-X 2，共 39 项——以清单为准）
是否充分。
