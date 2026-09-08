# INCIDENT DISPOSITION

> 意图：`AURORA-0650a39f56e3`  
> 裁定日：2026-09-08  
> 账户指纹：`3fbc5d4f1f9ddc7d`（TESTNET）  
> 事实真源：[FACTS.md](FACTS.md)  
> **本文件只裁定，不改写事实。未连交易所。未清 kill。未改 `state/kernel_ledger.db`。**

```text
NETWORK CALLS                 0
KILL CLEAR                    DENIED
PROBE                         HOLD until this document is sealed
PRODUCTION_MAIN               DENIED
LIVE                          NO-GO
```

---

## 裁定目的

把两件不能互相替代的事拆开：

```text
历史证据缺口
≠
未来是否允许重新资格验证
```

本裁定回答的是后者中的**最小一步**：是否允许进入只读 TESTNET 资格复核（G0-4D）。  
本裁定不回答系统现在能不能交易。

---

## 正式裁定

```text
INCIDENT_POSITION             RECOVERED
FINAL_POSITION                KNOWN_FLAT

EXIT_MECHANISM                UNKNOWN
MANUAL_CLOSE_FILL             NOT_FOUND
MANUAL_CLOSE_ORDER            NOT_FOUND
EXIT-PROVENANCE-01            OPEN / APPEND-ONLY
HISTORICAL_EVIDENCE_GAP       ACCEPTED

SYSTEM_EXECUTION_QUALIFIED    NO
KILL                          ACTIVE
INCIDENT_LOCK                 ACTIVE
AUTO_TESTNET                  DENIED
LIVE                          NO-GO

INCIDENT_REQUALIFICATION_ELIGIBLE   YES
```

`INCIDENT_REQUALIFICATION_ELIGIBLE = YES` 只表示：

> 可以进入下一阶段的 **只读 TESTNET 资格复核（G0-4D）**。

它绝不表示：

```text
INCIDENT_LOCK                 CLEARED
KILL                          CLEARED
AUTO TESTNET                  APPROVED
SYSTEM EXECUTION              QUALIFIED
G0-4D                         PASS
```

这些继续是 NO / ACTIVE / HOLD。

---

## 必须钉死的三件事

### 1. 证据缺口可以永久 OPEN

`EXIT-PROVENANCE-01` 记录的是：BTCUSDT 0.007 在 2026-09-08T02:34:36Z–02:38:29Z 变为 0，而 `userTrades` / `allOrders` 没有对应 SELL。

```text
EXIT-PROVENANCE-01            OPEN / APPEND-ONLY
HISTORICAL_EVIDENCE_GAP       ACCEPTED
```

允许永久保持 OPEN。若未来 Testnet API 或账户历史给出新解释，**只能追加，不得覆盖** 本日 `NOT_FOUND`。

禁止为了恢复运行或让账本平衡而补造：

```text
synthetic SELL
synthetic fee / realized pnl
synthetic manual order id
假 RECONCILED / CLOSED-CLEAN
```

旧 ENTRY 订单行 `PARTIALLY_FILLED / filled_qty=0` **保持原样**。

### 2. 仓位已 KNOWN_FLAT，缺口不永久阻断新周期

```text
KNOWN_FLAT ≠ exit provenance known
incident recovered ≠ system execution qualified
HISTORICAL_EVIDENCE_GAP ACCEPTED ≠ INCIDENT_LOCK CLEARED
```

当前账户仓位风险已收口为交易所 `KNOWN_FLAT`。  
因此：历史证据缺口 **不得** 被解释成「这个账户永远不能再进入 qualification cycle」。

但新周期的第一扇门只能是只读复核，不是自动交易，也不是清 kill。

### 3. 下一阶段任何身份/账户漂移立即失败

G0-4D 若发现以下任一情况，重新资格 **立即失败**，不得继续扩大范围：

```text
account identity drift
position-mode 与声明不一致
BTCUSDT 再出现未解释仓位
AURORA BTCUSDT Algo 残留
ordinary open orders 残留
endpoint / schema 与离线合同冲突
```

账户上已登记的非 BTC `V5S_*` Algo 证明账户 **不是** AURORA 独占。  
这是既有事实，不是新的平仓证据，也不是改 position mode 的许可。

---

## 本裁定明确不批准

```text
清 kill / 重置 ledger / 改旧订单行
启动 production_main / --boot-only
AURORA_ENABLE_TRADING=true
POST / DELETE / 下单 / 撤单
改账户 position mode
LIVE
自动 TESTNET
宣称 SYSTEM EXECUTION QUALIFIED
```

`MANUAL_RECOVERY_ACTION.json` 仍是处置记录，不是成交事实。

---

## 下一阶段（尚未开始）

本文件封点之后，才允许单独授权：

```text
G0-4D = READ-ONLY TESTNET REQUALIFICATION
```

只允许真实读取：

```text
position mode
account identity / config
positions
ordinary open orders
Algo open orders
userTrades
rate limits
endpoint / schema behavior
```

G0-4D 全部通过之前，不得设计受控 TESTNET qualification，更不得讨论 kill clearance。
