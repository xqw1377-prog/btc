# FILL IDENTITY 实施拆分清单（仅评审；未获任何实现授权）

> 依据：FILL IDENTITY DESIGN v6 = PASS WITH NONBLOCKING NOTES，设计
> CLOSED（无 v7）。本文只拆分实施；**设计通过 ≠ 开发或真实迁移获准**。
> 每段完成后单独验收；第一段本身仍需单独授权才能开工。
> 全程纪律沿用：IMPLEMENTATION=HOLD（直至逐段授权）、真实账本不
> 迁移（副本演练除外）、funding 不接线、权限不变、R1–R4 不变。

## 0. 三条实施说明的确定化（先行冻结，三段通用）

| 说明 | 确定化规则（可执行） |
|---|---|
| raw 权威仅适用于 EVENT | LEGACY 行永不产生/补造 raw；其 REAL 即事实（LEGACY_APPROXIMATE）。一切比较/投影取值函数：`origin=='EVENT' → Decimal(*_raw)`；`origin=='LEGACY' → REAL 值 + LEGACY_APPROXIMATE 标注`。不存在第三分支。 |
| Decimal→float 溢出/下溢显式处理 | REAL 展示值派生规则：`f = float(raw)`；若 `not isfinite(f)`（含溢出为 ±inf）或 `raw>0 而 f==0.0`（下溢归零）→ **拒绝该 EVENT 入账**（判定依据：交易所真实值必然在 float 可表示域内；域外输入按垃圾拒收）。亚正规（subnormal）非零值允许。派生失败是入口校验的一部分，不是事后补救。 |
| 精度/资源上限/重试/异常确定化 | ① 动态精度：`prec = max(28, max(操作数有效位数, 指数跨度+1) + 4)`，硬上限 **10000**（超限输入直接拒收）；② 重试：运算触发 Inexact/Rounded → prec 翻倍**重试一次**，仍触发 → 拒绝入账+告警（无第三次）；③ 迁移：单事务、无自动重试（失败=ROLLBACK+人工重跑）；校验器无循环重试；④ 异常映射：`FillIdentityConflict`/`FeeConflict`（可捕获、转 kill+告警）≠ `SafetyViolation`（治理拒启）≠ `ValueError`（入口非法输入拒收）。 |

## 第一段：迁移与历史兼容（MIGRATION & LEGACY）

**文件范围**
- `aurora/kernel/ledger.py`：fills 表重建迁移函数（§1.2 DDL：复合
  PK、origin/qty_raw/price_raw/fee_raw/fee_asset/derivation_ctx/
  replaced_by 列、typeof-CHECK、ux_fills_null_symbol）；`schema_meta`
  版本标记与重开结构验证；`fills_aggregate` 精度分级（EVENT=Decimal
  精确，含 LEGACY=照常计入+MIXED_APPROXIMATE 标注）。
- 新 `aurora/kernel/fill_migration.py`（或并入 ledger，开工时定）：
  迁移事务、全列双向 EXCEPT 等价核验、FK 恢复 try/finally、提交前
  `foreign_key_check`。
- **不碰**：orchestrator 事件入口逻辑、funding_income、真实
  `state/kernel_ledger.db`（仅测试/副本）。

**测试 ID**：T-M1、T-M2、T-M3（副本演练）、T-M4、T-M5、T-Q2、
T-Q3、T-Q4（聚合侧）、T-N1、T-DB4、T-DB5、T-I1（跨 symbol 存储）、
T-I4（schema 半）、T-I7。

**依赖**：无前置段。仅依赖现有 ledger/orchestrator 行为基线
（迁移不得改变现行单 symbol 账本的聚合结果——T-Q2 即此断言）。

**验收条件**
1. 上述 15 个 T-ID 全部红→绿；全树与干净树双绿；
2. 迁移函数在临时库与事故账本**副本**上通过 T-M1–M5（真实账本
   字节不变，测试内断言）；
3. 现网等价性：迁移前后 fills_aggregate / 持仓重建 / 既有经济
   效果逐项一致（T-Q2），任何历史数量值零变化；
4. 重开验证：版本标记+结构断言（PK/索引/CHECK）不符即拒开；
5. 第一段**不包含**任何入口行为变更（validator/replacement 逻辑
   均在第二段）。

## 第二段：统一身份校验（UNIFIED IDENTITY VALIDATOR）

**文件范围**
- `aurora/kernel/ledger.py`：`fill_content_mismatch()` 唯一校验器
  （字段集=交易所事实六元组+symbol；算子=§2.3/§3.4/§3.5 冻结口径
  +第 0 节确定化规则）；`insert_fill` IntegrityError 分支区分
  UNIQUE vs FK/CHECK（T-DB1/DB2）；
- `aurora/kernel/orchestrator.py`：`apply_fill_event` 改调统一校验
  器（含 IDENTITY_UNRESOLVED/ATTRIBUTION_ANOMALY/COMPARISON_
  INCOMPLETE 分类）；引用写入走限定形式+目标存在性回查；
  `replaced_by` 新写入口与 `replaced-by:` 前缀只读分流。
- **不碰**：费用补充/投影表（第三段）、迁移函数（第一段成果仅引用）。

**测试 ID**：T-I2、T-I3、T-I4（入口半）、T-I5、T-I6、T-D1、
T-D2、T-D3、T-D4（推导上下文/DEVIATION 分类/显式重算属校验器的
推导类语义）、T-R1a、T-R1b、T-R1c、T-R2、T-R3、T-DB1、T-DB2、
T-C1、T-C2、T-F1、T-F3、T-F3R、T-RW1、T-Q1（派生半）、T-X1、
T-X2。

**依赖**：**第一段**（schema：origin/symbol/raws 列与 NULL 唯一
索引是校验器取值与 UNIQUE 分流的前提）。

**验收条件**
1. 上述 25 个 T-ID 全部红→绿；双树绿；
2. 元测试 T-X1 证明两入口同输入同 MatchReport，且 orchestrator
   重放路径静态断言调用 `fill_content_mismatch`（调用关系而非算术
   禁令）；
3. 既有 W43 冲突测试（R1 遗产）不改断言全绿（T-X2）；
4. FK/CHECK/UNIQUE 三类 IntegrityError 可区分且均不吞成 DUPLICATE；
5. 并发：同身份一致重放恰一次、冲突路径不静默丢失（T-C1/C2）。

## 第三段：费用补充与投影（FEE SUPPLEMENTS & PROJECTION）

**文件范围**
- 新 `aurora/kernel/fee_projection.py`：`fill_fee_supplements` /
  `fill_fee_projection` 表与判定表（§3.2 七行）、四规则边界
  （§F5′：冲突≠修正授权；跨资产双蹄同事务）、deduct-once 证明链
  （stable_event_id UNIQUE / projection_version / effect_key
  UNIQUE / 三步单事务）、delta 重算（同资产）与按资产双蹄
  （跨资产）、精确运算（§3.5 + 第 0 节确定化：prec 公式、一次
  翻倍重试、异常映射）。
- `aurora/kernel/ledger.py`：仅新增表 DDL 与访问器；**不改**身份
  校验器。
- **不碰**：funding_income（其接入另行授权）；交易入口授权逻辑。

**测试 ID**：T-F2（入口语义半）、T-F4、T-F4R、T-FP1、T-FP2、
T-FP3、T-FP4（含"已授权修正事件"前提）、T-FP5、T-FP6、T-FP7、
T-FP8、T-FP9、T-F6a、T-F6b。

**依赖**：**第一段**（fee_raw/fee_asset 列）；**第二段**（FEE_
CONFLICT 判定复用统一校验器的费用字段比较；补充事实的 fill_ref
解析复用引用消解）。

**验收条件**
1. 上述 14 个 T-ID 全部红→绿；双树绿；
2. deduct-once 四层证明链逐层可证（T-FP1/FP5/FP6）；冲突零自动
   差额（T-FP7/FP8）；跨资产无双蹄不合事务（T-FP9）；
3. 精确运算：长尾无损（T-F6a）、边界拒收与一次重试上限（T-F6b）；
4. 本段完成**不改变**任何现有交易行为（未接线：投影结果仅供
   会计/风险层读取接口，消费方接入另行授权）。

## 汇总映射（52 项全覆盖、零残留）

```text
S1=15  T-M1-5, T-Q2-4, T-N1, T-DB4, T-DB5, T-I1, T-I4s, T-I7
S2=25  T-I2-6, T-I4e, T-D1-4, T-R1a-c, T-R2, T-R3, T-DB1, T-DB2,
       T-C1, T-C2, T-F1, T-F3, T-F3R, T-RW1, T-Q1d, T-X1, T-X2
S3=14  T-F2e, T-F4, T-F4R, T-FP1-9, T-F6a, T-F6b
拆半归属：T-I4(s=schema/e=入口)、T-Q1(d=派生)、T-F2(e=入口语义)
```

## 全局门槛（三段共同）

- 每段开工前：该段 T-ID 先写红（提交一次），后实现转绿（独立提交）；
- kernel 单写纪律沿用；每段完成推送远端并双树验证；
- 真实账本迁移、funding 接线、任何交易权限变化：**均不在三段范围**，
  各自单独授权。
