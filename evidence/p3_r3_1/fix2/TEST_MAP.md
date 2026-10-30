# P3-R3.1 适配边界修正的开发者复跑（90aee87）

固定方案：`745e4e0a7737ba2945bc50243be449264759e1b3`  
上一轮代码：`27f125b81f715fce2e2e644008d1572cda1e6efa`  
语义红测试：`82f675ecb5adf60d47bf30d9642b5196391a12ff`  
红日志：`red_run.txt`（detached worktree，账本不在）  
修正：`90aee876daa928ffaf00111c49ef3f1fd2fcf1e6`  
绿日志：`green_run.txt`（detached worktree，账本不在）

这是开发者复跑，不是独立复验，不签 `RUNTIME-PASS`。  
只动 R31-05a / R31-05b。R31-01～04 与 R31-06 的测试仍在同一套专项里。  
相对方案基线，`aurora/strategy_v2.py` 与 `aurora/risk_semantics.py` 的 diff 为 0 字节。

环境：macOS 26.3 arm64，Python 3.9.6。

| 运行 | 对象 | 结果 |
|---|---|---|
| 红 unittest | 82f675e | Ran 29；failures=9 |
| 绿 unittest | 90aee87 | Ran 29；OK |
| 绿 pytest | 90aee87 | 970 passed；1 skipped |

红跑的 9 个失败都在 R31-05a / R31-05b。  
绿跑跳过项是 `tests/test_fill_migration_s1.py:93` `incident ledger absent`。  
含事故账本的主工作树曾得到 `971 passed / 0 skipped`。那是另一份证书，不与 `970/1` 合并。

## 本轮反例

| ID | 测试 | 修正 |
|---|---|---|
| R31-05a | `test_r31_05a_non_finite_is_not_null_and_cannot_pass` | NaN 与 ±Infinity 保留为 `$aurora_non_finite` 标记并列入 `non_finite_paths`，运行时以 `NON_FINITE` 阻断。合法 null 仍是 null |
| R31-05b | `test_r31_05b_outer_declaration_cannot_bypass_inner_binding` | 外层 key、来源、时间、submit 标志必须与内层一致，否则 `BOUNDARY_DECLARATION_MISMATCH`。边界版本仍在内容身份里。两边一起改版本才是新声明 |

## 未改变

不重开 S1/S2/S3。不接 `trading_cycle` / `production_main` / 旧 RiskGate。不改 E2/E1。不实现 R3.2 / P3-R4。不接费用消费方或 funding。不迁移真实账本。不解除 kill。不发测试网订单。

```text
P3-R3.1 PLAN           = PASS / CLOSED
P3-R3.1 RUNTIME        = CHANGES-REQUIRED（适配边界两项已提交，待独立复验）
FIX SUBMITTED          = 90aee87 / READ-ONLY
S1 / S2 / S3          = CLOSED / OFFLINE PASS
消费方 / funding      = HOLD
真实账本迁移          = NOT AUTHORIZED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
