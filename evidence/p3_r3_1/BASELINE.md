# P3-R3.1 开工基线

固定方案：`745e4e0a7737ba2945bc50243be449264759e1b3`

记录时点是该提交的工作树。此时还没有 `aurora/risk_adjudicator.py`。下面两个文件的字节即 R31-15 的验收哈希。

| 文件 | SHA-256 |
|---|---|
| `aurora/strategy_v2.py` | `27f36b3de9b01f89e8dd5d360d7f219345c00bf086652af2a50241ff8440ef84` |
| `aurora/risk_semantics.py` | `c0f7a700da1e483d6af3621abf1b057eea8177275428dafd7155e85ab68bcdf3` |

规范化算法与哈希算法在实现里固定为 `aurora-canonical-json-v1` / `sha256`。本文件不是运行时验收。

```text
P3-R3.1 PLAN           = PASS / CLOSED
P3-R3.1 IMPLEMENTATION = AUTHORIZED / READ-ONLY
P3-R3.1 RUNTIME       = NOT YET VERIFIED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
