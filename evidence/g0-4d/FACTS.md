# G0-4D READ-ONLY TESTNET 探测事实（2026-09-08）

> 授权：INCIDENT-DISPOSITION（c612c8d）封点之后的只读资格复核。  
> 执行：`python3 -m aurora.ops_testnet_probe --env-file .env`（签名 GET，零写入）+ 两次补充只读观察（单条 Algo schema）。  
> 账户指纹：`3fbc5d4f1f9ddc7d`（与事故账户一致）  
> 原始输出：[probe_run_20260908.json](probe_run_20260908.json)  
> 禁令复核：POST/DELETE = 0；kill/ledger/state 未触碰（transport 间谍测试 + state 树字节不变测试钉死）。

## 三类结论

```text
AUTHENTICATION CONTRACT        PASS
READ PROTOCOL CONTRACT         FAIL（仅 Algo schema 一项；普通读取全部 PASS）
RECOVERY EVIDENCE COMPLETENESS PARTIAL

G0-4D                          HOLD（唯一阻塞：Algo schema 对齐）
```

## 八问回答

| # | 问题 | 现场答案 |
|---|---|---|
| 1 | 实际 position mode | **HEDGE**（与声明一致，identity.positionModeMatchesExpected=true） |
| 2 | BTCUSDT 是否 KNOWN_FLAT | **是**。positions 2 行（LONG/SHORT 均 0），openLegs=0 |
| 3 | ordinary BTCUSDT open order | **0**（openOrders EMPTY） |
| 4 | AURORA BTCUSDT Algo 残留 | **0**（BTCUSDT Algo 列表 EMPTY；无 ORPHAN_ALGO） |
| 5 | 其他系统活动 | **有**：`V5S_DOGE/ENA/XRP` 三笔 Algo（NEW）。ACCOUNT_EXCLUSIVITY=FALSE 现场证实；只有 AURORA- 前缀 id/BTCUSDT/positionSide 才解释为 AURORA 事实 |
| 6 | Algo GET schema 与 4A 合同一致？ | **不一致（本刀核心发现，见下）** |
| 7 | userTrades/allOrders 查询窗口 | 能力在：fromId 锚点 PASS（535229485）、time-window 调用被接受、allOrders orderId 锚点 PASS。当前 BTCUSDT 历史 = 1 笔成交 + 1 笔订单，单页即可完整枚举 |
| 8 | ConfigSource/身份/命名空间一致 | 一致：TESTNET、指纹 3fbc5d4f1f9ddc7d、HEDGE=HEDGE、host 在白名单、显式 env 路径 |

## 核心发现：Algo schema 不匹配（阻塞项）

真实 TESTNET Algo 响应（列表行与单条查询均如此）**没有 `type` 字段**；
订单类型字段的真实名称是 **`orderType`**（本例值 `STOP_MARKET`）。
4A 离线合同 `_algo_fact` 强制要求 `type` → 对真实响应每次都会
`RuntimeError: algo response missing type` → 适配层全部 UNKNOWN。

影响面（离线推导，未对交易所验证）：
- 提交回验（`_submit_algo` 的 echo 校验）同样读 `type` → 真实提交会
  SubmitUnknownError → RECOVERY_REQUIRED + kill。
- 查询路径 `query_algo_order` → RuntimeError → `_safe_query_order`
  返回 None → 恢复层视为 QUERY_FAILED，永远无法收敛。

真实响应字段全集（26 个，见 rawResponseFieldNames）：`orderType` 为
别名；其余 4A 关注字段（algoId/clientAlgoId/symbol/side/positionSide/
triggerPrice/quantity/closePosition/workingType/algoStatus/actualOrderId）
全部在位。另观察到：列表端点行同样缺 `type`（probe 判
CONTRACT_INCOMPLETE，仅缺此一项）。

修复方向（离线工作包，未在本刀执行）：`_algo_fact` 接受 `orderType`
别名（或两者），`_ALGO_FIELDS` 按 list/single 分别定义，FakeExchange
补真实 schema 回归，然后重跑本 probe 至 Algo 段全 PASS。

## 恢复证据核对（与 DISPOSITION 一致）

- userTrades(BTCUSDT) = 1 笔：`535229485`（入场 BUY 0.007 @ 79680.2）。
- allOrders(BTCUSDT) = 1 笔：`28574233916`（同入场）。
- **仍然没有 SELL**：人工平仓的成交缺口再次现场证实。
- `EXIT-PROVENANCE-01` 保持 OPEN / APPEND-ONLY；`NOT_FOUND` 未被改写。

## 完整性裁定的边界

- 对当前 BTCUSDT 状态：证据完整可枚举（1+1，单页内），恢复对账充分。
- 一般化完整性（超大历史的分页/时间窗上界）：能力已演示但未穷尽证明
  → 按冻结口径记 PARTIAL，不伪造 PASS。
