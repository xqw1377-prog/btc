# P3-R3.1 六项修正的开发者复跑（27f125b）

固定方案：`745e4e0a7737ba2945bc50243be449264759e1b3`  
被复验实现：`921472921eb287b1d04cb4d1ff396e6673f7c697`  
语义红测试：`ef3e9ca99316b725bd11cad4e6e0c9ec766675ab`  
红日志：`red_run.txt`（detached worktree，账本不在）  
修正：`27f125b81f715fce2e2e644008d1572cda1e6efa`  
绿日志：`green_run.txt`（detached worktree，账本不在）

这是开发者复跑，不是独立复验，不签 `RUNTIME-PASS`。  
原先 20 项导入失败只说明模块当时不存在，不代替这次语义反例。  
相对方案基线，`aurora/strategy_v2.py` 与 `aurora/risk_semantics.py` 的 diff 为 0 字节。

环境：macOS 26.3 arm64，Python 3.9.6。

| 运行 | 对象 | passed | failed | errors | skipped |
|---|---|---:|---:|---:|---:|
| 红 unittest | ef3e9ca | 21 | 9 | 8 | 0 |
| 绿 unittest | 27f125b | 27 | 0 | 0 | 0 |
| 绿 pytest | 27f125b | 968 | 0 | 0 | 1 |

红跑的 9 个失败和 8 个错误都在 R31-01～06 的子例上。原先 R31-1～21 在同一进程里通过。  
绿跑跳过项是 `tests/test_fill_migration_s1.py:93` `incident ledger absent`。  
含事故账本的主工作树曾得到 `969 passed / 0 skipped`。那是另一份证书，不与 `968/1` 合并。

## 本轮反例

| ID | 测试 | 修正 |
|---|---|---|
| R31-01 | `test_r31_01_bad_timestamps_do_not_pass` | 缺失、非法、无时区时间戳给出 `TIMESTAMP_INVALID`，不跳过 SLA，也不抛比较异常 |
| R31-02 | `test_r31_02_unknown_governance_and_bad_positions` | 缺失或 `UNKNOWN` 治理不再变成 `CLEAR`；畸形持仓为 `POSITION_MALFORMED` |
| R31-03 | `test_r31_03_submit_flag_and_policy_hash_are_required` | `submit_allowed is False` 才继续；缺 `policy_hash` 为 `POLICY_INCOMPLETE` |
| R31-04 | `test_r31_04_block_does_not_keep_requested_increase` | 阻断时调整后目标与增量为 `UNAVAILABLE`，请求对照保留 |
| R31-05 | `test_r31_05_evaluate_decision_boundary` | `evaluate_decision()` 经 `adapt_decision_candidate()` 进入裁决，浮点不冒充精确事实 |
| R31-06 | `test_r31_06_probes_bind_real_entries_and_block_send` | 探针绑在真实写入口上，命中即失败；发送探针在调用前阻断 |

## 未改变

不重开 S1/S2/S3。不接 `trading_cycle` / `production_main` / 旧 RiskGate。不改 E2/E1。不实现 R3.2 / P3-R4。不接费用消费方或 funding。不迁移真实账本。不解除 kill。不发测试网订单。

```text
P3-R3.1 PLAN           = PASS / CLOSED
P3-R3.1 RUNTIME        = CHANGES-REQUIRED
FIX SUBMITTED          = 27f125b / READ-ONLY / 待独立复验
S1 / S2 / S3          = CLOSED / OFFLINE PASS
消费方 / funding      = HOLD
真实账本迁移          = NOT AUTHORIZED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
