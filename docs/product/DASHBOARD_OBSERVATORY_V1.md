# DASHBOARD OBSERVATORY V1 — 整体设计方案

Status: `DESIGN-FROZEN`  
Date: `2026-09-09`  
Baseline: HEAD `b1079f4`（E4 CLOSED-OFFLINE）

```text
DASHBOARD OBSERVATORY V1   SUPERSEDED
PRODUCT NORTH STAR V2      APPROVED → docs/product/AURORA_NORTH_STAR.md
OBSERVATORY INTERACTION V2 DESIGN-FROZEN → AURORA_FRONTEND_INTERACTION_SPEC_V2.md
D0.2 IA SHELL              ALIGN TO V2
D1 / D2 / D3               HOLD
```

本地点：`aurora-dashboard` 下 `npm run dev`，底栏 1–5 / D 切换。
默认 `#disconnected`。展开诊断：`#disconnected/diag`。L1 OPEN 仅为排版夹具，标 `PROTOTYPE FIXTURE`。

**不是开工令以外的执行授权。** 不授权 AUTO TESTNET、不清 kill、不发 permit。

## D0.1 第一屏 · 三问骨架

决策顺序，不是合同清单：

```text
1. 能不能写？
2. 策略在做什么？
3. 交易所实际看见什么？
```

### L0 — 能不能写？

一条治理句 + 一条快照 + 一条链路。不再拆徽章墙。

```text
LOCK ACTIVE · KILL ACTIVE · EXECUTE DENIED · LIVE NO-GO
STATIC SNAPSHOT · 2026-09-09T07:02Z · b1079f4
WS DISCONNECTED · LINK ONLY
```

### L1 — 策略在做什么？

OVERLAY 是主视觉；指标是解释证据，不是主角。

```text
CORE      HOLD BTC
OVERLAY   UNKNOWN          ← 主视觉
AS OF     —

close — · ema20 — · ema60 — · ADX —
HTF unavailable · no 1m fallback · ba3edfc
```

### L2 — 交易所实际看见什么？

先表达「是否知道」，再表达「是多少」。

```text
UNKNOWN ≠ ZERO
STALE   ≠ UNKNOWN
FLAT    = authoritative fact
```

### 缺口 — 永远一行

```text
缺口 · 账本未知 · BTC NAV 未接 · 保护未核验 · EXIT OPEN
```

### 1m 诊断 — 默认折叠

展开也必须写 `NO OPEN AUTHORITY`。禁止 Trade Score / BUY / SELL / Confidence 类执行建议语言。

## D0.1 删减（相对 D0）

```text
scene-strip             REMOVE
observatory-footer      REMOVE
freshness panel         REMOVE
protection card         REMOVE FROM FIRST SCREEN
asset card              MERGE INTO POSITION
duplicate SourceKind    REMOVE
HTF missing strip       MERGE INTO OVERLAY STATE
1m diagnostics          COLLAPSED
```

## 冻结细则（仍必守）

1. `STATIC SNAPSHOT` 必须同时显示 `captured_at` 与 `source_commit`（L0 唯一一行）。
2. L1 overlay 只展示 E2 `decide_overlay` 口径。D1 未接时 overlay = `UNKNOWN`，**禁止** 1m score / confidence 顶上。
3. HTF missing/stale → overlay UNKNOWN → no 1m fallback。

## D0.1 范围

- 只动前端 IA
- 零 feed、零出网、零执行能力变化
- 五种夹具仍验证三问能否 3 秒内看懂
- **单屏画布**：L1 | L2 并排；缺口 + 诊断入口同一底行；1m 用抽屉覆盖，不顶走主屏

## D1（HOLD）

```text
1d futures_klines → closed_daily_bars → decide_overlay → read-only broadcast
HTF missing/stale → overlay = UNKNOWN → no 1m fallback
```
