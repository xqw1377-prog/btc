# AURORA PRODUCT NORTH STAR

Status: `APPROVED`（PRODUCT NORTH STAR V2）  
Date: `2026-09-09`  
Baseline: HEAD `b1079f4`（E4 CLOSED-OFFLINE）

```text
AURORA PRODUCT NORTH STAR V2     APPROVED
P0  PRODUCT NORTH STAR            THIS DOCUMENT
P1  OBSERVATORY V2 产品设计       DESIGN-FROZEN（见 INTERACTION_SPEC_V2）
P2  三引擎分别工程化             HOLD（见 TRADING_STRATEGY V1.1）
P3  DECISION BRAIN               HOLD（§6 · T1–T8 验收）
P4  BTC NAV / ACCOUNT TRUTH      HOLD
P5  E3 / OOS 证明                 CLOSED-OFFLINE（E3 已裁决；不等于 LIVE）
```

**不是开工令以外的执行授权。** 不授权 AUTO TESTNET、不清 kill、不发 permit、不宣称未实现能力已存在。

---

## 一句话定义

> **AURORA 是 BTC 本位的 BTC/ETH 智能资本管理与量化交易系统。**

BTC 本位 ≠ 只交易 BTC。

| 维度 | 范围 |
|---|---|
| 交易资产 | BTC、ETH |
| 资本资产 | BTC、ETH、USDT / Margin |
| 收益计量锚 | BTC |
| 最终 Benchmark | BTC HODL |

North Star：**长期 BTC 本位净资产是否优于 BTC HODL**。  
不是交易次数、不是 USDT PnL、不是单次胜率。

---

## 系统形状

```text
TREND QUANT ENGINE          ─┐
ETH/BTC RELATIVE VALUE      ├→ AURORA DECISION BRAIN → RISK GATE → EXECUTION
EVENT INTELLIGENCE ENGINE ─┘
                              ↑
                    统一账户真相层（BTC NAV / 持仓 / 对账）
```

三个引擎**不能分别控制订单**。Decision Brain 只输出**一份资本状态**。

示例输出：

```text
BTC SPOT       65%
ETH SPOT       25%
USDT           10%

BTC OVERLAY    +20%
ETH OVERLAY     0%

EVENT BOOST     0%

TOTAL RISK     1.2%
```

首页最重要的不是 `BUY BTC` / `SELL ETH`，而是：

> **当前资本应该处于什么状态？**

---

## 三 Alpha 引擎

### ① Trend Quant Engine（BTC + ETH 双资产趋势量化）

**不是**单独的 `BTC TREND ENGINE`。

```text
TREND QUANT ENGINE

BTC TREND     BULL · L4/5
ETH TREND     BULL · L3/5

RELATIVE STRENGTH
BTC > ETH
```

回答：

```text
BTC 值不值得做？
ETH 值不值得做？
当前哪个资产的趋势机会更强？
```

输入（非穷尽）：K 线、价格、成交量、EMA/MA 结构、ADX、ATR/波动率、OI、Funding、趋势持续时间、1D/4H/1H 结构。

**禁止指标墙。** 产品语言示例：

```text
BTC
BULL · L4/5 · STRONG
允许增加风险

ETH
BULL · L3/5 · NORMAL
维持持仓

PREFERRED TREND ASSET
BTC
```

趋势等级（冻结）：

```text
L0  无趋势 / UNKNOWN
L1  弱趋势
L2  初步趋势
L3  确认趋势
L4  强趋势
L5  极强趋势 / 极端趋势
```

与 E2 关系：E2 `CORE=HOLD BTC` + 日线 HTF overlay 是 Trend Quant 的**身份子集**，不是完整 Trend Quant Engine。

---

### ② ETH/BTC Relative Value Engine

低频**资产配置引擎**，不是交易机器人。

核心坐标：

```text
ETH/BTC Current
历史最低 / 最高 / 平均
本周期最低 / 最高
历史分位 / 周期分位 / 周期进度
距离低点 / 距离高点 / 偏离均值
4 年周期位置 / 上一周期对应位置
```

进度比：

```text
Progress = (Current - Cycle Low) / (Cycle High - Cycle Low)
```

输出：

```text
RELATIVE VALUE
ETH CHEAP / FAIR / EXPENSIVE

ALLOCATION SIGNAL
HOLD BTC / WATCH ETH / INCREASE ETH / REDUCE ETH
```

---

### ③ Event Intelligence Engine

回答：有没有**平时不应承担、但现在值得短时间承担**的额外风险？

事件源（分类）：政治、宏观金融、央行、监管、ETF/资金流、战争/地缘、交易所事件、链上重大事故、市场极端舆情。

每个事件必须经过：

```text
真实性 → 可信等级 → BTC 方向 → ETH 方向 → 冲击强度
→ 市场定价程度 → 持续窗口 → 趋势一致性 → Risk Gate
```

Boost 状态：

```text
OFF / WATCH / ELIGIBLE / ACTIVE
```

`ACTIVE` 必须极少出现。ELIGIBLE ≠ 已下单 ≠ 杠杆已开。

---

## 用户 5 秒阅读顺序

打开系统后 5 秒内应读懂：

```text
1. 我现在有多少 BTC 本位资产？
2. BTC 和 ETH 哪个趋势更好？
3. ETH/BTC 现在贵还是便宜？
4. 有没有重大事件值得放大？
5. 系统现在怎么配置我的钱？
6. 最终有没有跑赢 BTC HODL？
```

若仍需用户自行拼指标判断，AURORA 未完成其产品工作。

---

## 能力现状（严格口径）

文档批准 **不等于** 能力已实现。

```text
PRODUCT NORTH STAR           APPROVED（本文）

BTC TREND IDENTITY           PARTIAL / E2 FOUNDATION
ETH TREND                    PROPOSED
ETH/BTC ENGINE               PROPOSED
EVENT ENGINE                 PROPOSED
DECISION BRAIN               PROPOSED
BTC NAV                      NOT YET AUTHORITATIVE
STRATEGY EDGE                OFFLINE-OOS-ONLY（E3 已裁决；≠ LIVE）

D1                           HOLD
D2                           HOLD
AUTO TESTNET                 DENIED
LIVE                         NO-GO
EXECUTE_AUTHORIZED           FALSE
```

---

## 产品冻结清单

```text
BTC NUMERAIRE
BTC + ETH TRADABLE
THREE-ENGINE ARCHITECTURE
ONE DECISION BRAIN
BTC HODL BENCHMARK
ONE-SCREEN OBSERVATORY
```

---

## 实施路线图（产品层）

```text
P0  PRODUCT NORTH STAR           APPROVED ← 本文
P1  OBSERVATORY V2 单屏产品设计   DESIGN-FROZEN
P2  三引擎分别工程化             HOLD ← TRADING_STRATEGY V1.1
P3  DECISION BRAIN               HOLD
P4  BTC NAV / ACCOUNT TRUTH      HOLD
P5  E3 / OOS 证明                 E3 CLOSED-OFFLINE；不等于产品 LIVE
```

前端 D0.2 IA Shell 是 P1 实施前的探索性壳层；以 `AURORA_FRONTEND_INTERACTION_SPEC_V2.md` 为准对齐。
