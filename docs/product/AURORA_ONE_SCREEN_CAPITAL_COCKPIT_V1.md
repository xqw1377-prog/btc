# AURORA ONE-SCREEN CAPITAL COCKPIT V1

Status: `SUPERSEDED`  
Date: `2026-09-09`  
Superseded by: [AURORA_FRONTEND_INTERACTION_SPEC_V2.md](./AURORA_FRONTEND_INTERACTION_SPEC_V2.md)  
Parent: [AURORA_NORTH_STAR.md](./AURORA_NORTH_STAR.md)

```text
AURORA ONE-SCREEN CAPITAL COCKPIT V1   SUPERSEDED BY V2
D0.1 THREE-QUESTION IA                 SUPERSEDED BY D0.2 SHELL
D0.2 IA SHELL                          IN PROGRESS
D0.3 FIXTURE INTERACTION               HOLD
D1 READ-ONLY MARKET                    HOLD
D1.5 RELATIVE VALUE                    HOLD
D1.6 EVENT READ-ONLY                   HOLD
D2 CAPITAL & ACCOUNTING                HOLD
```

**不是开工令以外的执行授权。** 不授权 AUTO TESTNET、不清 kill、不发 permit。

## 产品定义

AURORA 不是单一 BTC 看盘或下单工具，而是以 **BTC 为本位**、同时管理 BTC 与 ETH 的智能资本与趋势量化系统。

核心策略：

1. BTC/ETH 趋势量化  
2. ETH/BTC 相对价值兑换  
3. 重大事件 / 政治 / 金融 / 舆情机会放大  

North Star：**长期 BTC 本位净资产是否优于 BTC HODL**。

## 单屏信息架构：10 / 20 / 80

| 区域 | 占比 | 职责 |
|---|---|---|
| 顶部全局条 | ~10% | North Star、组合、风险、执行治理 |
| 左侧决策脑 | ~20% | 四个策略结论（不是导航） |
| 右侧主工作区 | ~80% | 行情、价值、事件、资本、收益事实 |

### 禁止重新长成页面系统

- 左侧不得变成导航栏；点击只高亮/联动右侧，不切页  
- BTC、ETH、ETH/BTC、事件、资本、收益同一主界面常驻  
- 核心任务不依赖弹窗/抽屉/二级页；弹层仅补充证据  
- 1920×1080 默认无纵向滚动；图表可局部交互  

## 左侧 20%：四个决策结论

| 模块 | 主句 | 状态集合 |
|---|---|---|
| BTC 趋势 | BULL · L4/5 | L0–L5 |
| ETH 趋势 | BULL · L3/5 | L0–L5 + vs BTC |
| ETH/BTC | 0.0368 · WATCH ETH | HOLD/WATCH/ALLOCATE/REDUCE/UNKNOWN |
| 重大事件 | BOOST OFF | NONE/WATCH/CONFIRMED/ELIGIBLE/ACTIVE/UNKNOWN |

## 右侧 80%

**上 58%**：BTC 趋势图 · ETH 趋势图 · ETH/BTC 历史相对价值  
**下 42%**：事件情报 · 资本/钱包/仓位 · BTC 本位收益  

1m 不进入主分析区。趋势等级不由前端计算。

## 全局状态语义

| 状态 | 显示 | 绝不能解释为 |
|---|---|---|
| KNOWN | 权威值 + as_of | — |
| STALE | 旧值 + STALE + 时间 | UNKNOWN 或最新 |
| UNKNOWN | 明确不可用 | 0、FLAT、健康 |
| NOT CONNECTED | 未接入 | 数据已存在 |
| PROTOTYPE FIXTURE | 显著标明 | 真实策略/收益 |

## 实施顺序

| 阶段 | 内容 | 边界 |
|---|---|---|
| D0.2 | 10/20/80 布局、视觉层级、空态 | 只动前端；零 feed |
| D0.3 | 周期切换、左栏联动、局部展开 | PROTOTYPE FIXTURE |
| D1 | HTF 只读行情与趋势快照 | 不改策略、不执行 |
| D1.5 | ETH/BTC 历史/周期 | 冻结口径后接 |
| D1.6 | 事件只读快照 | 无自动执行 |
| D2 | 钱包、仓位、Accounting Truth | 保持 source 语义 |

## D0.2 验收

1. 1920×1080 无纵向滚动可见七个核心区  
2. 顶部 ~10%，左 20% / 右 80%  
3. 左栏为决策结论，非导航菜单  
4. UNKNOWN / STALE / FLAT / 0 语义严格区分  
5. 无写盘按钮、无清 Kill、无 Permit  
6. 夹具不得展示为真实 strategy edge  

完整交互细则见用户提交的 `FRONTEND PRODUCT INTERACTION SPEC V1.0`（本文件为仓库冻结摘要）。
