# S2-WIRE-FIX6 证据包（43f6fd5 复审 R3 三项残留）

- commit：f176b31 `fill-identity S2-WIRE-FIX6: 43f6fd5 复审 R3 三项残留关闭`
- 基线：43f6fd5（FIX5 关闭轮；R1/R2/R4 已 CLOSED，本轮未触碰）

## 文件

| 文件 | 内容 |
|---|---|
| `red_run.txt` | 43f6fd5 源码（detached git worktree）+ `tests/test_fill_wire_fix6.py` → 8 用例 **6 red**。红运行垫片**仅补缺失异常符号** `RecomputeIdentityConflict`（类定义，零行为改动——不垫则以 ImportError 呈现，无法区分三组反例）。2 例通过 = 旧行为正确锚定（`test_identical_replay_still_idempotent` / `test_other_integrity_errors_propagate`） |
| `green_run.txt` | f176b31 本仓全套：Ran 906，906 通过（0 skip） |
| `clone_run.txt` | f176b31 新克隆全套：Ran 906，**905 通过 + 1 skip**；skip 溯源 = S1 `T_M3_IncidentCopyDrill ... 'incident ledger absent'` |

## R3 残留 → 用例映射（评审三组反例）

| 残留 | 用例 |
|---|---|
| 1 同身份异容被静默忽略 | `R3_1_SameIdentityDifferentAmounts/test_same_identity_different_amounts_conflicts`（old=0,new=1 → id=1；同身份 new=999 → RecomputeIdentityConflict，原记录 id/金额原样保留）；`test_identical_replay_still_idempotent`（一致重放仍幂等，锚定） |
| 2 并发一致重放未收敛 | `R3_2_ConcurrentReplayConvergence/test_concurrent_identical_replay_converges`（两连接 + 竞态窗口模拟：查重未命中 → INSERT 撞唯一索引 → 重读一致 → 收敛同一 id，无双写）；`test_concurrent_different_amounts_conflicts`（异容 → RecomputeIdentityConflict，A 记录保留）；`test_other_integrity_errors_propagate`（非目标索引 IntegrityError 上抛，锚定） |
| 3 既有重复半升级 | `R3_3_AtomicUpgradeBoundary/test_pre_existing_duplicates_block_upgrade_atomically`（历史重复 → SafetyViolation 列明冲突组；symbol 列/唯一索引/版本标记**一并缺席**——无半升级；历史事件不删不合并）；`test_clean_legacy_table_upgrades_atomically`（干净旧表 → 列+索引+标记同在，历史行原貌保留，升级幂等）；`test_upgrade_log_version_marker`（schema_upgrade_log 版本状态可查） |

## 本轮固化口径

- **幂等判据 = 身份 + 内容**：稳定身份 (COALESCE(symbol,''), fill_id,
  old_ctx, new_ctx, basis_ref) 且金额一致才返回既有 id；同身份异容 =
  RecomputeIdentityConflict（append-only 合同：原记录永不改写）。
- **并发收敛**：唯一索引是最后防线；捕获**仅**目标索引（表达式索引的
  SQLite 消息为 `UNIQUE constraint failed: index '<名>'`，已实测）后重读
  比较内容；一致收敛、异容冲突、其余上抛。
- **升级原子性**：补列/索引/版本标记在同一显式事务（BEGIN IMMEDIATE）
  内同生同灭；此前半升级根因是 DDL 走自动提交（SQLite DDL 事务性已在
  证据流程中实测：BEGIN + ALTER + 失败 CREATE INDEX + ROLLBACK → 列回退）。
- **历史重复处置**：升级前预检，存在即阻断并列明冲突组；不自动裁定、
  不删除、不合并——交人工处置。

## 安全边界（不变）

- LIVE=NO-GO；kill switch 不清除；真实账本未触碰；密钥不出现。
- 红证据 detached git worktree（垫片仅补异常符号、零行为改动）。
- stash 哈希对照每轮追加：见 `../fix5/stash_object_hashes.txt`
  （本轮 f176b31 时点与首次固化哈希一致：b3e301f / 3fad75a）。
