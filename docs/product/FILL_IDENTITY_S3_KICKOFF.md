# FILL IDENTITY S3 开工令草案（DRAFT / 待签发）

> 状态：**未签发**。本文件仅为裁定材料——S3 依裁定需单独开工令，
> 不因 S1/S2 关闭连续放行。签发前不写任何 S3 代码/测试。
> 依据：FILL_IDENTITY_IMPL_PLAN.md 第三段（已接受含执行条件）；
> S2 关闭登记见 CAPABILITY_STATUS.md（85b25da / 29498c3 / 09d0844）。

## 一、范围（照抄已接受计划，无新增）

- 新 `aurora/kernel/fee_projection.py`：
  - `fill_fee_supplements` / `fill_fee_projection` 表与判定表（设计 §3.2 七行）
  - 四规则边界（§F5′：冲突≠修正授权；跨资产按资产双蹄同事务）
  - deduct-once 证明链：stable_event_id UNIQUE / projection_version /
    effect_key UNIQUE / 三步单事务
  - delta 重算（同资产）与按资产双蹄（跨资产）
  - 精确运算（§3.5 + 第 0 节确定化：prec 公式、一次翻倍重试、
    上限 10000、异常映射）
- `aurora/kernel/ledger.py`：**仅新增表 DDL 与访问器**；不改身份校验器
  （S2 已关闭资产冻结）。
- 依赖（均已就位）：S1 的 fee_raw/fee_asset 列；S2 的统一校验器费用
  字段比较与引用消解。

## 二、测试目录（14 项，全部红→绿）

T-F2e, T-F4, T-F4R, T-FP1, T-FP2, T-FP3, T-FP4（含"已授权修正事件"
前提）, T-FP5, T-FP6, T-FP7, T-FP8, T-FP9, T-F6a, T-F6b

验收：14 项全绿 + 双树绿；deduct-once 四层证明链逐层可证
（T-FP1/FP5/FP6）；冲突零自动差额（T-FP7/FP8）；跨资产无双蹄
不合事务（T-FP9）；长尾无损（T-F6a）；边界拒收与一次重试上限
（T-F6b）。

## 三、明确不碰（本开工令不授权）

- funding_income 接入（另行授权；E0/D2 待办维持）
- 投影结果消费方接线（会计/风险层读取接口之外的任何接入）
- 交易入口授权逻辑 / 部署 / 任何交易行为——S3 完成不改变现有
  交易行为（离线内核资产，投影仅供读取接口）
- 真实账本迁移（NOT AUTHORIZED 不变；事故副本演练仍
  DEVELOPER-VERIFIED / 未独立验证）
- LIVE = NO-GO 不变；kill switch 不清除

## 四、执行纪律（延续历轮）

- 红→绿→全套回归→克隆验证→证据包（detached worktree 制作红证据）
- 每轮评审 CHANGES-REQUIRED 逐项关闭，不重开已通过段
- S3 代码仅离线内核隔离实现，不接入默认 Ledger 初始化/生产入口

---

**签发格式**（任选其一）：
- 「批准 S3 开工」→ 按本草案执行
- 「S3 开工，改动：<...>」→ 按修订范围执行
- 或指定其他工作项（funding 接线 E0/D2 / user-stream 恢复）
