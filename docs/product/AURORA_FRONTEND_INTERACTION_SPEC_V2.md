# AURORA FRONTEND PRODUCT INTERACTION SPEC V2

Status: `DESIGN-FROZEN`  
Date: `2026-09-09`  
Parent: [AURORA_NORTH_STAR.md](./AURORA_NORTH_STAR.md)（P0 APPROVED）  
Supersedes: [AURORA_ONE_SCREEN_CAPITAL_COCKPIT_V1.md](./AURORA_ONE_SCREEN_CAPITAL_COCKPIT_V1.md)

```text
AURORA PRODUCT NORTH STAR V2     APPROVED
OBSERVATORY INTERACTION V2       DESIGN-FROZEN
OBSERVATORY INTERACTION V1       SUPERSEDED
D0.2 IA SHELL                    ALIGN TO V2（夹具；零 feed）
D0.3 FIXTURE INTERACTION         HOLD
D1+                              HOLD
```

**不是开工令以外的执行授权。**

---

## 1. 产品目标

AURORA 首页 = **资本决策总控舱**。16:9 宽屏、桌面全屏优先、**主流程不纵向滚动、不分页**。

用户 5 秒内读懂（见 North Star §阅读顺序）。若还需用户自己拼指标，产品失败。

---

## 2. 单屏信息架构：10 / 20 / 80

| 区域 | 占比 | 职责 | 必须回答 |
|---|---|---|---|
| TOP | ~10% | 我的钱现在怎么样 | BTC NAV、vs HODL、配置、风险、治理 |
| LEFT | ~20% | AI 今天怎么判断 | 三引擎结论 + Decision Brain 输出 |
| RIGHT | ~80% | 为什么 + 钱在哪 | 六区事实与证据 |

### 禁止重新长成页面系统

- LEFT **不是导航**；点击只高亮/联动 RIGHT，不切页  
- 六区 RIGHT **同一屏常驻**  
- 核心任务不依赖 Modal/全屏二级页；局部展开仅限证据明细  
- 1920×1080 默认无纵向滚动；1366×768 仍须可读核心结论  
- 1m **不进入**主分析区  

---

## 3. TOP 10% — 我的钱现在怎么样

只回答最高层结果，**不塞策略细节**。

```text
BTC NAV          12.48 BTC
vs HODL          +0.37 BTC
BTC / ETH / USDT 65 / 25 / 10
TOTAL RISK       NORMAL
SYSTEM           WRITE DENIED · KILL ACTIVE · LIVE NO-GO
```

规则：

| 字段 | 规则 |
|---|---|
| BTC NAV | 单位必须 BTC；D2 未接入 → UNKNOWN/未接入，不得伪造 |
| vs HODL | Excess BTC；E3 前标明 ≠ 已证明 strategy edge |
| Mix | Spot 配置占比；Perp 放次级 |
| TOTAL RISK | 来自 RiskGate 真源 |
| SYSTEM | 治理只读；无清 kill / 授权 / 启动按钮 |

允许且只允许 **一行** STATIC SNAPSHOT：`captured_at + source_commit`。各对象自报 `as_of / stale`。

---

## 4. LEFT 20% — AI 今天怎么判断

五块常驻结论（**不是菜单**）：

```text
┌─ 趋势量化 ─────────────┐
│ BTC  L4/5              │
│ ETH  L3/5              │
│ BTC > ETH              │
├─ ETH/BTC ──────────────┤
│ LOW ZONE               │
│ WATCH ETH              │
├─ 重大事件 ─────────────┤
│ NO BOOST               │
├─ 最终决策 ─────────────┤
│ BTC 65 · ETH 25        │
│ PERP +10 · BOOST 0     │
└────────────────────────┘
```

| 块 | 来源引擎 | 主句 |
|---|---|---|
| 趋势量化 | Trend Quant | BTC/ETH Level + Preferred Asset |
| ETH/BTC | Relative Value | 区间位置 + Allocation Signal |
| 重大事件 | Event Intelligence | Boost State + 最高优先事件摘要 |
| 最终决策 | Decision Brain | Spot / Overlay / Boost / Total Risk |

交互：点击块 → RIGHT 对应区高亮 2–3s；Esc 取消。不改变策略状态。

---

## 5. RIGHT 80% — 六区事实层

```text
┌──────── BTC 趋势 ────────┬──────── ETH 趋势 ────────┬──── ETH/BTC ────┐
│ K 线 · Volume            │ K 线 · Volume            │ 长周期曲线       │
│ 趋势等级证据              │ 趋势等级证据              │ High/Low/Avg     │
│ 1D/4H/1H 原位切换         │ 1D/4H/1H 原位切换         │ Progress/分位    │
├─────────────────────────┼─────────────────────────┼───────────────────┤
│ Event Intelligence      │ Capital / Wallet        │ BTC Performance   │
│ 政治/宏观/监管/舆情      │ BTC ETH USDT            │ vs HODL           │
│ 可信/方向/定价/Boost      │ 仓位/杠杆/Risk Budget    │ DD/Fee/Funding    │
└─────────────────────────┴─────────────────────────┴───────────────────┘
```

上排 ~58%，下排 ~42%。

### 5.1 BTC / ETH 趋势区

- 默认 **1D**；原位切换 4H / 1H  
- 主结论：`Price + Trend Level`（引擎给出，前端不重算）  
- 指标带：EMA20/60、ADX、Volume、Funding、Vol/OI（按空间）  
- 动作资格：`LONG ELIGIBLE / HOLD / BLOCKED` ≠ 写盘授权  

### 5.2 ETH/BTC 区

- Current、Historical Low/High、Average、Percentile、Cycle Progress、Cycle Low/High、Relative Trend、Signal  
- 尺度：All History / Current 4Y / 365D（只改展示，不改策略参数）  
- Signal 仅配置建议，禁止 BUY/SELL 命令式文案  

### 5.3 事件区

- 最高优先 1 条 + 类别入口；不是新闻瀑布流  
- Trust A/B/C、BTC/ETH Impact -5~+5、Priced-in、Window、Boost State  
- ELIGIBLE ≠ 已下单  

### 5.4 资本区

- Spot Allocation vs Wallet 余额分开  
- Perp Exposure、Open Positions、Risk Budget  
- UNKNOWN ≠ 0；断线 ≠ FLAT；STALE 保留旧值 + 标 STALE  

### 5.5 收益区

- AURORA BTC NAV、HODL Baseline、Excess BTC（主视觉）  
- 7D/30D/90D/YTD 均 BTC 本位  
- Fee Drag / Funding Drag 必须可见  
- USDT PnL 不得作为 North Star  

---

## 6. 全局状态语义

| 状态 | 显示 | 绝不能解释为 |
|---|---|---|
| KNOWN | 权威值 + as_of | — |
| STALE | 旧值 + STALE + 时间 | UNKNOWN 或最新 |
| UNKNOWN | 明确不可用 | 0、FLAT、健康 |
| NOT CONNECTED | 未接入 | 数据已存在 |
| PROTOTYPE FIXTURE | 显著标明 | 真实策略/收益 |

---

## 7. 前端数据合同（摘要）

| 区域 | 期望对象 | 权威性 |
|---|---|---|
| Trend Quant | `trend_quant_snapshot` | 等级/方向/Preferred 由引擎给出 |
| ETH/BTC | `eth_btc_value_snapshot` | 分位/进度/Signal 服务端确定口径 |
| Event | `event_intelligence_snapshot` | Boost/Impact 来自事件引擎 |
| Decision | `capital_allocation_snapshot` | Decision Brain 唯一输出 |
| Wallet/Position | `exchange_observation` | 只读交易所事实 |
| Performance | `accounting_truth_snapshot` | E0 链；BTC NAV 需 D2 |
| Governance | `governance_snapshot` | fail-closed |

前端禁止自行合成趋势分数、收益、交易资格。

---

## 8. 实施顺序

| 阶段 | 内容 | 边界 |
|---|---|---|
| **P1 设计** | 本文 V2 | 已冻结 |
| D0.2 | 10/20/80 壳层对齐 V2（含 LEFT 第五块「最终决策」） | 零 feed |
| D0.3 | 周期切换、左栏联动、局部展开 | PROTOTYPE FIXTURE |
| D1 | HTF 只读 + Trend Quant 快照 | 不执行 |
| D1.5 | ETH/BTC 历史/周期 | 口径冻结后接 |
| D1.6 | Event 只读 | 无自动执行 |
| D2 | Wallet + Accounting Truth + BTC NAV | 保持语义 |

P2 三引擎工程化、P3 Decision Brain、P4 Account Truth：**HOLD**，需单独开工令。

---

## 9. V2 相对 V1 的关键修正

1. **Trend Quant** 覆盖 BTC + ETH 双资产 + Relative Strength，不是单独 BTC TREND  
2. LEFT 增加 **最终决策** 块（Decision Brain 输出），与三引擎结论并列  
3. TOP 只答「钱怎么样」，策略细节全部在 LEFT/RIGHT  
4. 六区 RIGHT 与 5 秒阅读顺序一一对应  
5. 所有未实现能力保持 PROPOSED / UNKNOWN，不因 UI 夹具伪装为 LIVE  

---

## 10. 验收（P1 设计完成标准）

- [x] North Star 父文档 APPROVED  
- [x] 10/20/80 职责冻结  
- [x] LEFT 五块 / RIGHT 六区定义  
- [x] 状态语义与数据合同摘要  
- [x] 与 E 线 / D 线 HOLD 边界一致  

前端实现验收见 D0.2/D0.3 清单（实施阶段）。
