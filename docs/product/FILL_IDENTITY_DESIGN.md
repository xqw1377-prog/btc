# FILL IDENTITY & ECONOMIC COMPLETENESS — 设计与测试清单（仅评审稿）

> 状态：**DESIGN-FROZEN-CANDIDATE / 待评审**。本文只提交设计与测试
> 清单；不实现、不接线、不恢复任何权限。
> 依据：W43 独立复验 CHANGES-REQUIRED 后续裁定（R1-R4 PASS WITH
> NONBLOCKING NOTES；下一刀=成交身份与经济字段完整性）。
> 范围纪律：**不接 funding、不升级依赖、不动 TRADING AUTHORITY。**

## 0. 问题陈述（现状缺陷，均已确认）

1. **两套校验并存（R1 引入的技术债）**：`orchestrator.apply_fill_event`
   事件入口与 `ledger.insert_fill` 的 IntegrityError 分支各自实现了
   内容一致性比较（字段集与容差是两份代码）——正是评审警告的
   "事件入口与账本两套校验"。
2. **身份作用域不完整**：fill 身份当前= 账本物理命名空间
   （mode+fingerprint，结构性）+ `fill_id`（交易所 trade ID 原文）。
   **symbol 不参与身份**：同 trade ID 不同 symbol 的事件会命中
   content 比较（若 cid 不同→冲突；若 cid 恰同→漏检）。
3. **经济字段缺失**：fills 表无 `fee_asset` 列；`fee` 存在但**不参与**
   重放比较；`realized_pnl` 是本地推导值（非交易所事实），当前既
   不区分性质也不参与任何一致性语义。

## 1. 冻结的身份作用域（提案）

```text
FILL IDENTITY KEY =
  account_fingerprint   （账本物理命名空间，结构性，不加列）
+ environment           （同上：state/<mode>/…）
+ symbol                （新增：进入身份与比较）
+ exchange_trade_id     （现 fill_id）
```

- **schema 迁移**：`fills` 增加 `symbol TEXT`（可空历史行=UNKNOWN，
  迁移不回填不重写）；新事件必须有 symbol，缺失=拒收（fail-closed，
  与 funding 缺 asset 同纪律）。
- **同一 trade ID 跨 symbol 重放** = 身份冲突（即便 cid/qty/price
  全同）。理由：trade ID 的交易所级唯一性作用域未证明跨 symbol
  成立，凡未证明唯一性的组合一律当作身份的一部分。

## 2. 经济字段分类与统一比较（提案）

字段按**事实来源**分三类，比较语义不同：

| 类别 | 字段 | 重放语义 |
|---|---|---|
| 交易所事实 | symbol, side, qty, price, **fee, fee_asset** | 不可变：任何不一致=IDENTITY_CONFLICT |
| 本地推导 | realized_pnl（由 entry avg 计算） | 不参与身份比较；重放时**确定性重算**并要求与已存值一致（浮点容差），不一致=推导非确定性缺陷→告警（DEVIATION，非 IDENTITY） |
| 记账属性 | synthetic/covered_by_fact_id/economic_effect | 不参与身份（记账状态，非市场事实） |

- **schema 迁移**：`fills` 增加 `fee_asset TEXT`（历史行 NULL=UNKNOWN，
  只读保留）；新事件 fee 缺失=UNKNOWN 显式入账（非 0），fee_asset
  缺失=拒收。
- **fee 数值比较容差**：`abs(a-b) <= 1e-9`（与 price 同级）。

## 3. 统一校验器（消除两套比较）

```text
ledger.fill_content_mismatch(fill_id, incoming) -> None | ConflictReport
    唯一实现，唯一容差表，唯一字段集（§1+§2 事实字段）

orchestrator.apply_fill_event:
    existing = ledger.get_fill(fill_id)
    if existing:
        report = ledger.fill_content_mismatch(...)
        if report: → engage_kill + IDENTITY_CONFLICT + 仓位 UNKNOWN
        else:      → DUPLICATE（幂等）

ledger.insert_fill (IntegrityError 分支):
    同一 fill_content_mismatch → 抛 FillIdentityConflict
    （两入口调用同一函数；容差/字段集改动只允许发生在该函数）
```

## 4. 不做什么（NON-GOALS）

- 不接 funding 入交易链（funding_income 保持 MODULE/NOT INTEGRATED）
- 不处理密钥轮换账本连续性（独立议题，另行设计）
- 不实现任意崩溃点注入（独立议题）
- 不改事件入口的分类语义（DUPLICATE/ORPHAN/LATE_NEW_FILL 等仅
  在身份检查点收口，分支逻辑不动）
- 历史行不回填 symbol/fee_asset（迁移=加列+默认 NULL，旧账本
  可打开性由现有迁移测试保障）

## 5. 测试清单（实现前冻结；逐条红→绿）

**身份作用域（6）**
1. 同 trade ID + 不同 symbol + 其余全同 → IDENTITY_CONFLICT（含 kill）
2. 同 trade ID + 不同 symbol + cid 也不同 → IDENTITY_CONFLICT（当前漏检场景）
3. 新事件无 symbol → 拒收（fail-closed，事件入口与 insert_fill 双口）
4. symbol 迁移：旧账本（无 symbol 列）打开→可读→历史行 symbol=UNKNOWN
5. 历史行 symbol=NULL 不与新事件比较崩溃（NULL≠冲突源）
6. 跨账本命名空间同 trade ID：互不可见（结构性作用域回归钉）

**经济字段（5）**
7. 同 ID fee 不一致 → IDENTITY_CONFLICT
8. 同 ID fee_asset 不一致（USDT→BNB）→ IDENTITY_CONFLICT
9. fee 缺失 → 记 UNKNOWN 不记 0；fee_asset 缺失 → 拒收
10. realized_pnl 重放不一致 → DEVIATION 告警（非 IDENTITY_CONFLICT，不熔断身份链）
11. realized_pnl 重放一致（确定性重算）→ DUPLICATE 正常

**统一校验器（3）**
12. 两入口（apply_fill_event / insert_fill）对同一冲突输入产生同一
    ConflictReport 字段集（防再分叉的元测试：抽查字段清单）
13. 容差表单一来源：修改容差只允许在 fill_content_mismatch（静态
    断言：orchestrator 不含独立 abs(...) 比较）
14. 冲突后的持久化告警：kill 理由含冲突字段名；仓位事实=UNKNOWN

**回归（2）**
15. 既有 W43 冲突测试（FillIdentityConflictTests / EventEntryConflictBypassTests）
    在统一校验器下不改断言仍全绿
16. 事故账本副本迁移后打开：schema 含新列、旧行未改写、kill=1

## 6. 评审请求

请裁定：① 身份作用域四元组是否冻结；② 事实/推导/记账三分类语义
（尤其 realized_pnl=DEVIATION 而非 CONFLICT 的定性）；③ 测试清单
16 项是否充分或需增删。批准后实现按本清单逐条红→绿，独立提交。
