# TESTNET 事故事实表（P0-0 / P0-1）

> 意图：`AURORA-0650a39f56e3`  
> 冻结：2026-09-08T02:16:14Z（P0-0）  
> 交易所只读核对：2026-09-08T02:18:51Z（P0-1）  
> 账户指纹：`3fbc5d4f1f9ddc7d`（TESTNET）  
> **未下单、未撤单、未清 kill、未改 `state/kernel_ledger.db`。**

运行真源：`kernel_ledger` > `p0_safety.json`。后者在本事故中为 STALE，不得单独宣称 MATCHED / healthy。

处置裁定：[DISPOSITION.md](DISPOSITION.md)（2026-09-08）。本表不因 disposition 改写任何 `NOT_FOUND`。

原始快照：`FREEZE.txt`、`HEAD`、`worktree.diff`、`kernel_ledger.dump.json`、`exchange_readonly.json`、`raw/`。

---

## 正式状态（现行，仓位风险收口后）

```text
POSITION_RISK_RECOVERED        YES
FINAL_POSITION                 KNOWN_FLAT

EXIT_MECHANISM                 UNKNOWN
MANUAL_CLOSE_FILL              NOT_FOUND
MANUAL_CLOSE_ORDER             NOT_FOUND

INCIDENT_POSITION_STATE        RECOVERED
INCIDENT_EVIDENCE_STATE        OPEN_RESIDUAL
EXIT-PROVENANCE-01             OPEN / APPEND-ONLY

SYSTEM_EXECUTION_QUALIFIED     NO
KILL                           ACTIVE
AUTO_TESTNET                   DENIED
LIVE                           NO-GO
G0-4A                          CLOSED-OFFLINE
G0-4B                          CLOSED-OFFLINE
G0-4B_COMMIT                   1bb1ecf
G0-4C                          CLOSED-OFFLINE
G0-4C_COMMIT                   5bfa311
G0-4D                          HOLD
G0-5                           CLOSED-OFFLINE
G0-5_COMMIT                    d0863ee

HISTORICAL_EVIDENCE_GAP        ACCEPTED
INCIDENT_REQUALIFICATION_ELIGIBLE  YES
INCIDENT_LOCK                  ACTIVE
```

事故调查 **不是 CLOSED-CLEAN**。仓位风险可关；证据残留保持 OPEN。
未来若 Testnet API / 账户历史给出新解释，**只能追加，不得覆盖** 本日 `NOT_FOUND`。

2026-09-08 disposition 已封：`HISTORICAL_EVIDENCE_GAP=ACCEPTED`，`INCIDENT_REQUALIFICATION_ELIGIBLE=YES`。  
这只批准进入 G0-4D 只读资格复核。`INCIDENT_LOCK` / kill / AUTO TESTNET / SYSTEM EXECUTION 均未解除。

P0-1 当时（2026-09-08T02:18Z）交易所仍持有 LONG 0.007。该快照保留在「六问」；现行仓位以文末「人工平仓复核」为准。

```text
G0-4A_COMMIT                  7a10302
G0-4B_COMMIT                  1bb1ecf
WORKTREE                      禁止对交易所运行
P0-1_POSITION_SNAPSHOT        LONG 0.007 UNPROTECTED（历史）
CURRENT_POSITION              KNOWN_FLAT
PROTECTION                    NONE
EMERGENCY_CLOSE               REJECTED / NOT EXECUTED
KILL                          ACTIVE（ledger）；原因文本为假成功语义
P0_SAFETY_STATUS              STALE / NOT AUTHORITATIVE
```

---

## 六问

| # | 问题 | 交易所只读结果 |
|---|---|---|
| 1 | BTCUSDT positionAmt / positionSide | LONG `0.0070` @ entry 79680.2；SHORT `0.0000`。未实现约 −2.77 USDT（核对时刻 mark≈79284） |
| 2 | 账户 position mode | `dualSidePosition=true` → **HEDGE** |
| 3 | 普通 open orders | **空**（BTCUSDT） |
| 4 | open Algo orders | 3 笔，均非 AURORA、均非 BTCUSDT：`V5S_XRP_*` / `V5S_ENA_*` / `V5S_DOGE_*`，状态 NEW |
| 5 | 本 intent 三笔动作终态 | Entry **FILLED** 0.007 @ 79680.2（orderId 28574233916，tradeId 535229485）。SL 普通单 **-2013 不存在**；Algo 按 clientAlgoId 查询无有效合同（SDK `KeyError: data`）。紧急平仓普通单 **-2013 不存在** |
| 6 | 事故后仓位是否被别人动过 | BTCUSDT 仅此 1 笔成交；仓位 `updateTime` 等于成交时间 `1788711270591`。**BTC 腿从事故到核对未再成交。** 同账户上有其他程序的非 BTC Algo，账户**不是** AURORA 独占 |

---

## 账本 vs 交易所

| 项目 | Kernel ledger | Exchange | 裁定 |
|---|---|---|---|
| Entry | 订单行 `PARTIALLY_FILLED`，`filled_qty=0.0`；fills 表 0.007 @ 79680.2 | 订单 **FILLED** executedQty=0.007 avg=79680.2；成交 535229485 | **DRIFT（订单行） / MATCH（成交）** |
| Position（P0-1） | `KNOWN_OPEN` LONG 0.007 | LONG 0.007 仍在 | 当时 **MATCH / UNPROTECTED**。复核后交易所 **KNOWN_FLAT**，账本旧行未改 |
| Position（复核后） | 旧行未改（仍可能写 OPEN） | LONG/SHORT `0.0000` | **POSITION_RISK_RECOVERED**；**CLOSE_PROVENANCE_UNKNOWN** |
| SL | `REJECTED`，qty 记为 0.0，无 exchange_order_id；原因 `-1106 reduceonly` | 普通单不存在；BTCUSDT 无对应 Algo | **MATCH：从未被交易所接受** → 保护 **NONE** |
| Emergency close | 订单 `REJECTED` `-1106`；intent `RECOVERY_REQUIRED`；kill 原因写 *emergency close executed* | 普通单不存在；仓位仍在 | **MATCH：平仓未执行**。Kill 原因是 **假成功语义**（attempted ≠ executed） |
| Algo protection | 本 intent 无 algoId | BTCUSDT 无 AURORA Algo | **NONE** |
| Mode | 启动声明 HEDGE；事故时可变适配器未注入观测模式 | 账户 **HEDGE** | 本笔入场用了 `positionSide=LONG` 且成交。G0-4A 现已冻结 ObservedPositionMode 注入，禁止默认 ONE_WAY |
| Kill | `engaged=1` | 交易所无此概念 | **ACTIVE（仅账本）**。不得因 p0_safety.kill=false 而视为已解除 |
| p0_safety | `MATCHED` / `kill_switch=false` / 更新于 2026-09-06T16:04:46Z（事故前约 10 分钟） | — | **STALE**。无资格宣称健康 |

---

## 对下一步的含义

仓位风险层已经收口为交易所 FLAT。证据层仍是：

```text
KNOWN_FLAT + CLOSE_PROVENANCE_UNKNOWN
```

不是 CLOSED-CLEAN，不是「已找到 SELL」。不得为账本平衡补造 synthetic SELL / fee / pnl / manual order id。

账本订单行把 FILLED 记成 PARTIALLY_FILLED / filled_qty=0，保护提交时还用了 `filled qty=0.0`。G0-4B 已在离线内核钉死「fills 聚合才是保护数量真源、ACK 只是早期观察」；**不得**用自动代码改写本 intent 的旧订单行。

Kill 原因必须改成描述事实的词（后续代码冻结，不在本收口改 live ledger）：

```text
EMERGENCY_CLOSE_REJECTED  (实际发生)
不是 EMERGENCY_CLOSE_CONFIRMED
```

`production_main` 在 kill 解除审批前 = **DO NOT START**。

---

## 人工平仓复核（2026-09-08）

操作员声明已在测试网网页平掉。AURORA **未**下单。live `kernel_ledger.db` **未**改旧行、**未**清 kill。

`MANUAL_RECOVERY_ACTION.json` **不是人工成交事实**。它只证明操作者恢复动作 / 现场处置记录。交易所证据目前只能证明：**仓位在该时间窗内消失**。

只读窗口：

| 时刻 (UTC) | 结果 |
|---|---|
| 02:34:36 | BTCUSDT LONG 0.007 |
| 02:38:29 | BTCUSDT position = 0 |

```text
userTrades     没有对应 SELL
allOrders      没有对应 close order
AURORA Algo    没有
ordinary order 没有
```

| 核对项 | 结果 |
|---|---|
| BTCUSDT position | **KNOWN_FLAT** — LONG `0.0000`，SHORT `0.0000` |
| BTCUSDT ordinary orders | **0** |
| BTCUSDT AURORA Algo | **0**（账户仍有 3 笔非 BTC `V5S_*` Algo） |
| 持仓模式 | 仍为 HEDGE（`dualSidePosition=true`） |
| EXIT_MECHANISM | **UNKNOWN** |
| MANUAL_CLOSE_FILL | **NOT_FOUND** |
| MANUAL_CLOSE_ORDER | **NOT_FOUND** |

能记进档案的成交字段：

| 字段 | 值 |
|---|---|
| 成交时间 | **未知**（无 SELL userTrade；仓位在 02:34:36–02:38:29Z 之间变为 0） |
| 成交价 | **未知** |
| order id | **未知**（`allOrders` 仍只有入场 `28574233916`） |
| trade/fill id | **未知**（BTCUSDT userTrades 仍只有 `535229485` BUY） |
| 最终 positionAmt | `0.0000` / `0.0000` |
| 最终 positionSide 行 | LONG 与 SHORT 均为空仓 |

```text
ENTRY                         FILLED 0.007 @ 79680.2
                              (trade 535229485 / order 28574233916)
PROTECTION                    NONE
EMERGENCY_CLOSE               REJECTED

POSITION_RISK_RECOVERED       YES
FINAL_POSITION                KNOWN_FLAT
EXIT_MECHANISM                UNKNOWN
MANUAL_CLOSE_FILL             NOT_FOUND
MANUAL_CLOSE_ORDER            NOT_FOUND

INCIDENT_POSITION_STATE       RECOVERED
INCIDENT_EVIDENCE_STATE       OPEN_RESIDUAL

SYSTEM_EXECUTION_QUALIFIED    NO
KILL                          ACTIVE
AUTO_TESTNET                  DENIED
LIVE                          NO-GO
```

### Residual：EXIT-PROVENANCE-01

```text
EXIT-PROVENANCE-01
BTCUSDT 0.007 → 0
between 02:34:36Z and 02:38:29Z
without matching userTrade/allOrder evidence
```

这是给后续恢复系统的真实反例：**仓位状态可以变化，而本系统未必能找到对应 order/fill。**

```text
position truth  ≠  financial provenance truth
```

恢复语义必须能表达 `KNOWN_FLAT + CLOSE_PROVENANCE_UNKNOWN`，禁止：

```text
FLAT → 必然存在本地可解释 SELL fill
synthetic SELL / fee / realized pnl / manual order id
```

没有来源就没有财务事实。旧 ENTRY 订单行 `PARTIALLY_FILLED / filled_qty=0` **保持原样**。

2026-09-08 disposition 已接受历史证据缺口，并批准进入只读 qualification cycle（G0-4D）。  
EXIT provenance 继续 UNKNOWN / OPEN。new risk 仍 DENIED：kill ACTIVE，INCIDENT_LOCK ACTIVE。详见 [DISPOSITION.md](DISPOSITION.md)。

原始探针：`exchange_manual_close_probe.json`（仍开仓）、`exchange_post_manual_close.json`、`exchange_post_manual_close_hunt.json`、`MANUAL_RECOVERY_ACTION.json`（处置记录，非成交事实）。
