# E2 STRATEGY V2

Status: `CLOSED-OFFLINE`  
Date: `2026-09-08`  
Scope: redefine why AURORA exists; no backtest, no exchange writes, no TESTNET.

**E2 冻结策略身份，不证明 excess BTC。**  
`ACCOUNTING TRUTH` / `RISK SEMANTICS` / `STRATEGY EDGE` 仍须分开表述。

## 凭什么长期增加 BTC

```text
NUMERAIRE     = BTC
CORE          = HOLD BTC          ← 默认仓；E3 的 BTC HODL 基准就是它
OVERLAY       = BTCUSDT PERP LONG ← 仅当日线趋势支持「可能比 HODL 多积累 BTC」
FORBIDDEN     = 净空、1m 信号裁定、以 USDT 盈亏当目标
```

机制（合同，不是成绩）：

1. 默认什么都不做，只保持 BTC 身份。不靠 1 分钟 RSI/VWAP 刷单。
2. 只有日线 `close > ema20 > ema60` 且斜率向上、ADX≥20 时，才允许
   **可选**永续多头增强；仓位由 E1 RiskGate risk-budget 裁定。
3. 日线结构破坏 → 平掉 overlay，回到 CORE。不得改成空头「对冲」。
4. 资金费/点差否决沿用 E1：吃 funding 的多头不是在积累 BTC。

V2-R0 执行诚实性：武装内核仍然只写 BTCUSDT 永续。CORE HODL 是经济身份
与 E3 基准，**不是**新的现货执行器。

## Authority

| 决策 | 真源 | 明确不是 |
|---|---|---|
| 要不要 overlay | `strategy_v2.decide_overlay`（日线 HTF） | 1m trend/breakout/momentum/mr |
| 方向 | LONG only | SHORT |
| size / SL/TP | E1 RiskGate | Brain 后处理、1m 百分比 |
| 风险减仓 | SL/TP 与 HTF EXIT | 1m 反向票权 |
| 是否赚钱 | E3 BTC HODL OOS | 本包任何回测暗示 |

HTF 不完整 → overlay OPEN DENIED；已有 overlay 不因缺数据被强制平仓；
SL/TP 减仓始终允许。

## Implementation

| Component | Role |
|---|---|
| `aurora/strategy_v2.py` | 论点、日线快照、overlay 指令 |
| `aurora/portfolio_brain_v2.py` | 只执行 directive；1m 信号降为诊断 |
| `aurora/trading_cycle.py` | 只读拉 `1d` K 线 |

## Verification

```text
tests/test_strategy_v2.py
E1 tests remain green
Exchange writes: 0
```

## Explicit non-goals

- Spot BTC 执行器
- ETH 配置、配对、净空
- LIVE / AUTO TESTNET
- 因 E3 数字回写本包参数

E3 已 CLOSED-OFFLINE。第一原则已遵守：看到 OOS 后未改本包常数。
Walk-forward 数字见 `docs/product/E3_WALKFORWARD_OOS.md`。
E4 已把生产 HTF 看回接到同一已收盘日线口径（见
`docs/product/E4_RUNTIME_PARITY.md`）；ADX / overlay size / risk-budget
仍是本包冻结值。
