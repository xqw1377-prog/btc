# S2-WIRE-FIX7 证据包（c623cd3 复审 R3-3 收尾：调用方事务边界）

- commit：85b25da `fill-identity S2-WIRE-FIX7: c623cd3 复审 R3-3 收尾——不接管调用方事务`
- 基线：c623cd3（FIX6 关闭轮；R1/R2/R4、R3-1/R3-2 保持关闭，未触碰）

## 文件

| 文件 | 内容 |
|---|---|
| `red_run.txt` | c623cd3 源码（detached git worktree）+ `tests/test_fill_wire_fix7.py` → 7 用例 **4 red**（四个调用方事务拒绝场景全部失败于旧代码）；3 例通过 = 无外层事务时的行为锚定（幂等/冲突、干净旧表升级、orchestrator EXPLICIT_RECOMPUTE 路径） |
| `green_run.txt` | 85b25da 本仓全套：Ran 913，913 通过（0 skip） |
| `clone_run.txt` | 85b25da 新克隆全套：Ran 913，**912 通过 + 1 skip**（S1 `T_M3_IncidentCopyDrill ... 'incident ledger absent'`，附溯源行） |

## 阻断 → 用例映射（评审两项独立复现 + 裁定补测）

| 项 | 用例 |
|---|---|
| 复现 1：未提交修改 + 失败升级 → 半升级 | `CallerTransactionTests/test_open_txn_duplicate_upgrade_refused_then_rollback_clean`（历史重复 + BEGIN + UPDATE 未提交 → append 拒绝；rollback 后 avg≠123、symbol 列/索引缺席、重复原样 2 条）；`test_open_txn_direct_schema_call_refused`（升级入口直调同样拒绝） |
| 复现 2：未提交 avg=123 被方法提交 | `CallerCommitIsolationTests/test_success_path_never_commits_caller_txn`（拒绝 → rollback → 123 消失；无重算记录；外层结束后正常路径可用） |
| 快速路径不得绕过 | `CallerTransactionTests/test_open_txn_fast_path_also_refused`（索引已在位时 append 与 _ensure 双入口均拒绝） |
| 无外层事务回归锚定 | `NoOuterTxnRegressionTests/`（幂等+异容冲突不变；干净旧表升级不变；orchestrator EXPLICIT_RECOMPUTE 生产路径不变） |

## 本轮固化口径

- **事务前置条件**：`append_fill_recomputation` 与 `_ensure_recompute_schema`
  在任何写入前检查 `conn.in_transaction`——True 即 SafetyViolation 拒绝；
  不加入调用方事务、不替其 commit/rollback、不改连接配置（与 S1 迁移
  的拒绝方案同口径）。
- **守卫暴露的既有缺陷（同轮修复）**：`_log_transition` 裸 execute 留下
  未提交隐式事务——apply_fill_event 的 EXPLICIT_RECOMPUTE 转移写后泄漏
  至后续写入方（fix5 双重放场景在守卫下立即可见）。修复：独立调用时
  自持事务；被外层 with-block 调用时加入外层事务（嵌套 with 会在中途
  提交外层部分写，禁止）。全套 913 通过含该场景回归。

## 安全边界（不变）

- LIVE=NO-GO；kill switch 不清除；真实账本未触碰；密钥不出现。
- 红证据 detached git worktree（本轮无需任何垫片）。
- stash 哈希对照每轮追加：`../fix5/stash_object_hashes.txt`
  （85b25da 时点与首次固化一致：b3e301f / 3fad75a）。
