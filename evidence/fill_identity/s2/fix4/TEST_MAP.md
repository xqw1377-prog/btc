# S2-WIRE-FIX4 证据包（ca031f1 复审四项阻断）

- commit：9289ae0 `fill-identity S2-WIRE-FIX4: ca031f1 复审四项阻断关闭`
- 基线：ca031f1（fix3 关闭轮）

## 文件

| 文件 | 内容 |
|---|---|
| `red_run.txt` | ca031f1 源码（detached worktree）+ 新测试 `tests/test_fill_wire_fix4.py` → 13 用例 12 red（1 例 `test_venue_replay_of_legacy_row_not_adopted_as_new` 在旧代码碰巧因 bare get_fill 命中而通过——其针对的回归在旧代码中不存在，属防御锚定） |
| `green_run.txt` | 9289ae0 本仓全套：Ran 885，885 通过（0 skip） |
| `clone_run.txt` | 9289ae0 新克隆全套：Ran 885，**884 通过 + 1 skip**。skip 溯源：`tests/test_fill_migration_s1.py::T_M3_IncidentCopyDrill ... skipped 'incident ledger absent'`（S1 事故库副本演练，环境缺事故账本；先前登记为"G0-4D 探针"系计数归属错误，本轮更正——G0-4D 探针输出 BLOCKED 状态行，不计入 unittest skip 口径） |

## 阻断 → 用例映射

| 阻断（ca031f1 复审） | 用例 |
|---|---|
| 1 复合身份贯穿读写 | `B1_CompositeIdentityTests/test_one_shot_insert_no_post_update`（一次性 INSERT 含 ctx）；`test_null_legacy_and_event_rows_coexist_by_identity`（复合键分派读取）；`test_conflict_localized_by_composite_key`（冲突定位）；`test_venue_replay_of_legacy_row_not_adopted_as_new`（NULL-symbol 历史行 = 审计定位，不收养） |
| 2 两侧 EVENT 走 raw | `B2_EventVsEventRawTests/test_raw_diff_behind_equal_reals_exposed`（REAL 相同 raw 不同 → 冲突暴露，HISTORY 包装会吞）；`test_equal_raws_with_display_noise_not_spurious_conflict`（raw 相同 REAL 尾差 → 幂等，HISTORY 包装会伪冲突）；`test_exact_replay_idempotent_false` |
| 3 PnL 冻结推导上下文 | `B3_FrozenDerivationCtxTests/test_ctx_helper_is_frozen_entry_basis`（基准=entry 腿快照；无订单=无 ctx 不伪造）；`test_venue_row_carries_ctx_at_write`（随写持久）；另见 `tests/test_fill_wire_fix3.py::Fix3_3`：`test_replay_with_different_pnl_triggers_deviation`（同 ctx 数值不等=DEVIATION）/ `test_replay_missing_ctx_is_unverifiable_not_fabricated`（缺 ctx=PNL_UNVERIFIABLE）/ `test_replay_basis_change_routes_explicit_recompute`（基准变化=EXPLICIT_RECOMPUTE 追加事件、历史行不变） |
| 4 解析引用审计链 | `B4_ResolutionAuditTrailTests/test_recomputation_requires_frozen_basis_triple`（三元组强制）；`test_clear_unresolved_logs_resolution_then_deletes`（先落 resolution_log 再删，跨重启）；`test_machine_refs_must_resolve`（悬空机器引用拒绝）；`test_basis_ref_machine_dangling_rejected_on_append` |

## 语义裁定（实现中固化的口径）

- **复合身份下的历史行重放**：venue 事件按 (symbol, fill_id) 未命中时，探测同
  fill_id 的 NULL-symbol 历史行——这是迁移前同一笔交易的审计定位
  （resolve_fill_ref 的 UNRESOLVED_NULL_LEGACY 语义）→ 跨等级比较 →
  INCOMPLETE → IDENTITY_UNRESOLVED。绝不作为新身份收养（否则重放=二次记账）。
  回归证明：`tests/test_protection_semantics.py::T7`（全套内）。
- **机器引用 vs 人工依据**：单 token 结构化引用（`fill:SYM:FID`、`order:CID`、
  `fact:FID`、`recompute:ID`、`recomputation-event:ID`）必须解析到已存在目标；
  含空格复合注记与操作员处置文本视为人工依据（非空即可）。
- **EXPLICIT_RECOMPUTE 不改历史行**：基准变化只追加 fill_recomputations 记录
  （old_ctx/new_ctx/basis_ref 完备），fills 行值不动（append-only 合同）。
- **resolution_log**：`unresolved_cleared` / `pnl_unreliable_cleared` 两类，
  记录 entity、resolution_ref、原标记原因 detail；与标志 DELETE 同事务。

## 安全边界（不变）

- LIVE=NO-GO；kill switch 不清除；真实账本未触碰；密钥不出现。
- 本轮零真实状态修改：仅隔离测试库 + detached worktree 红证据。
