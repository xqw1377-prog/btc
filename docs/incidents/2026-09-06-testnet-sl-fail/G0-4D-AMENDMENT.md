# G0-4D 修正附录（APPEND-ONLY）

> 本文件是对 [G0-4D.md](G0-4D.md) 的追加更正，不覆盖原文。  
> 依据：独立第二次真实只读探测（2026-09-08），原始输出  
> [evidence/g0-4d/probe_run_20260908.json](../../../evidence/g0-4d/probe_run_20260908.json)  
> 事实明细：[evidence/g0-4d/FACTS.md](../../../evidence/g0-4d/FACTS.md)

## 新事实：单条 Algo 查询 schema 也不匹配（比"列表缺 type"更严重）

第一次探测（G0-4D.md）正确记录了 `openAlgoOrders` 列表行缺 `type`，
并按"列表 schema PARTIAL"处理，读协议整体给了 PASS。

第二次探测把缺口补到了**单条查询**（`GET /fapi/v1/algoOrder` by
clientAlgoId，使用已观察到的既有 id `V5S_XRP_1788567120000_0001`，
绑定其所属品种 XRPUSDT，只读）：

```text
真实单条响应（26 字段）：没有 "type" 字段。
订单类型的真实字段名：orderType（本例 "STOP_MARKET"）。
其余 4A 关注字段全部在位；另见 reduceOnly=true、positionSide=SHORT
（他方系统的 SHORT 止损，观察即可）。
```

4A 生产合同 `kernel/binance_exchange.py::_algo_fact` 强制要求 `type`：

```text
提交回验（_submit_algo echo 校验）读 type → 真实提交必 raise
→ SubmitUnknownError → RECOVERY_REQUIRED + kill
查询路径（query_algo_order）读 type → 真实查询必 raise
→ _safe_query_order=None → 恢复层永远 QUERY_FAILED
```

即：**不只是列表端点字段口径问题，而是生产 Algo 提交与查询两条路径
对真实服务全部不可用（fail-closed 卡死）**。

## 更正后的裁决

```text
AUTHENTICATION CONTRACT          PASS（维持）
READ PROTOCOL CONTRACT           FAIL —— Algo 段 schema 不匹配
                                 （普通读取段全部 PASS）
RECOVERY EVIDENCE COMPLETENESS   PARTIAL（维持：
                                 当前 BTCUSDT=1 成交+1 订单可完整枚举，
                                 无 SELL 再确认；一般化完整性未证明）

G0-4D                            CLOSED-READONLY → HOLD
唯一阻塞：_algo_fact 接受 orderType 别名（离线合同修正）
+ FakeExchange 真实 schema 回归 + 重跑只读探测至 Algo 段 PASS
```

原裁决中维持不变的部分：身份一致（HEDGE=HEDGE、指纹
3fbc5d4f1f9ddc7d）、BTCUSDT KNOWN_FLAT、普通挂单 0、AURORA Algo
残留 0、共享账户现场证实（V5S_DOGE/ENA/XRP，EXCLUSIVITY=FALSE）、
kill / lock / AUTO TESTNET / SYSTEM EXECUTION 全部未解除。

## 正面观察

跨品种单查曾被守卫正确拒绝（symbol 身份不匹配 → RuntimeError），
证明 4A 的 fail-closed 身份检查在真实数据上生效。

## 禁令复核

POST/DELETE = 0；position mode / leverage / margin 未变；
kill / ledger / state 树未触碰（契约测试以 transport 间谍 +
state 树字节不变钉死）。
