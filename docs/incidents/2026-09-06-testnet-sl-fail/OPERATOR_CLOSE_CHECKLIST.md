# 操作员手工平仓清单（AURORA 不执行）

```text
AUTO CLOSE          DENIED
AUTO PROTECTION     DENIED
MANUAL TESTNET EXIT APPROVED
source              OPERATOR_BINANCE_TESTNET_UI
```

核对时刻（只读，2026-09-08T02:23 左右）：BTCUSDT **LONG 0.007 仍在**。  
本清单只指导网页操作。AURORA 进程不要开，工作区 Algo 不要对交易所提交。

## 平什么、不平什么

| 做 | 不做 |
|---|---|
| 只平 **BTCUSDT / LONG / 0.007** | 不要平 SHORT（本来就是 0） |
| 从持仓面板对该腿点平仓 | 不要开反向空单当“对冲” |
| 数量必须是 **0.007**（或 Close All 该 LONG 腿） | 不要动 XRP/ENA/DOGE 上的 `V5S_*` Algo |
| 平完后告诉我，再只读复核 | 不要清 kill、不要改 ledger 旧订单行 |

## 建议路径（Binance USDS-M 期货测试网）

1. 打开 [https://testnet.binancefuture.com/](https://testnet.binancefuture.com/) ，登录**同一把**测试网密钥对应的账户（指纹 `3fbc5d4f1f9ddc7d`）。
2. 确认是 **USDⓢ-M**，合约 **BTCUSDT**，持仓模式 **Hedge**。
3. 打开 **Positions**。应看到 LONG `0.007`，入场约 `79680.2`。
4. 在该 LONG 行用 **Close / 平仓**（市价、该腿数量 0.007）。不要用会新开 SHORT 的下单板，除非明确是 Reduce-only + `positionSide=LONG` + `SELL`。
5. 确认 Positions 里 BTCUSDT LONG 与 SHORT 都是 0；Open Orders 为空。
6. 记下：**成交时间、成交价、成交 ID / orderId**（成交记录里那一笔 SELL）。

平完后在对话里说一声「已平」，并把成交价、成交 ID 贴过来（没有也行，我会只读拉 user trades）。

我才会：

- 只读复核 `positionAmt=0`、BTCUSDT 普通单=0、AURORA BTC Algo=0
- **追加** `MANUAL_RECOVERY_ACTION` 事实（不改旧 ENTRY 行，不清 kill）
