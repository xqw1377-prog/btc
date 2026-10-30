# P4 账户真相开工基线

固定方案：`ab2e872417e43b4665cd16b7a4873f826974f5fc`

记录时点是该提交的工作树。此时还没有 `aurora/account_truth.py`。下面两个文件的字节即冻结哈希。

| 文件 | SHA-256 |
|---|---|
| `aurora/strategy_v2.py` | `27f36b3de9b01f89e8dd5d360d7f219345c00bf086652af2a50241ff8440ef84` |
| `aurora/risk_semantics.py` | `c0f7a700da1e483d6af3621abf1b057eea8177275428dafd7155e85ab68bcdf3` |

规范化算法与哈希算法沿用 `aurora-canonical-json-v1` / `sha256`。本文件不是运行时验收。

实现口径：

- BTC 金额换算为 BTC 是单位恒等，不要求额外 BTC/BTC 报价。
- 现货分项使用尚未扣除单列负债的资产余额。负债只在最终负债项扣一次。

```text
P4 PLAN               = PASS / CLOSED
P4 IMPLEMENTATION     = AUTHORIZED / OFFLINE PURE FUNCTION
P4 RUNTIME            = NOT YET VERIFIED
真实账户／接线／迁移 = NOT AUTHORIZED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
