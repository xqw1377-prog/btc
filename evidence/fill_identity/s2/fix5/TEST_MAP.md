# S2-WIRE-FIX5 证据包（d46abb8 复审四项阻断）

- commit：ed1fbf0 `fill-identity S2-WIRE-FIX5: d46abb8 复审四项阻断关闭`
- 基线：d46abb8（fix4 关闭轮 + 证据包）

## 文件

| 文件 | 内容 |
|---|---|
| `red_run.txt` | d46abb8 源码（detached git worktree）+ 新测试 `tests/test_fill_wire_fix5.py` → 12 用例 **9 red**（3 例为修复后行为在旧代码已正确的锚定：`test_reverse_insertion_order_same_outcome` / `test_cross_symbol_same_fill_id_recomputation_distinct` / `test_same_order_coverage_still_works`） |
| `green_run.txt` | ed1fbf0 本仓全套：Ran 898，898 通过（0 skip） |
| `clone_run.txt` | ed1fbf0 新克隆全套：Ran 898，**897 通过 + 1 skip**；skip 溯源 = `tests/test_fill_migration_s1.py::T_M3_IncidentCopyDrill ... skipped 'incident ledger absent'` |
| `stash_object_hashes.txt` | quarantine stash 对象哈希对照（误操作事件说明 + 时点哈希，此后每轮更新） |

## 阻断 → 用例映射（评审独立复现场景逐条关闭）

| 阻断（d46abb8 复审） | 用例 |
|---|---|
| R1 legacy-shadow 依赖裸 ID 第一行 | `R1_ShadowProbeOrderIndependentTests`：`test_get_legacy_fill_returns_null_row_regardless_of_order`（显式 NULL 行查询）；`test_eth_event_not_adopted_shadow_still_found`（BTC EVENT 先写 + NULL 后写 + ETH 同 ID 事件 → 不收养、无第三行）；`test_reverse_insertion_order_same_outcome`（顺序无关） |
| R2 对账覆盖未用完整身份 | `R2_CoverageOrderScopedTests`：`test_cross_order_same_trade_id_not_covered`（BTC fact 不覆盖 ETH 订单同 trade ID 成交，economic_effect=1 不漏记）；`test_evidence_without_order_scope_fails_closed`（无订单归属=无证据）；`test_same_order_coverage_still_works`（同订单覆盖仍有效） |
| R3 相同依据变化重放重复追加 | `R3_RecomputeIdentityTests`：`test_identical_replay_appends_nothing`（两次相同重放 → 1 条记录；真正新依据才第 2 条）；`test_recompute_table_keeps_full_fill_reference`（symbol 列保留完整成交引用）；`test_cross_symbol_same_fill_id_recomputation_distinct`（同 fill_id 跨 symbol = 独立记录） |
| R4 机器引用附加文字绕过解析 | `R4_MachineRefNoTextBypassTests`：`test_order_ref_with_explanation_rejected`（评审原话复现：`order:NO_SUCH_ORDER plus explanation` 拒绝且未解除；正确写法 = 可解析引用 + detail）；`test_resolvable_ref_with_trailing_text_also_rejected`（含裸前缀 `order:`）；`test_basis_ref_text_bypass_rejected_on_append`（basis_ref 同规则） |

另：`tests/test_fill_wire_fix2.py::test_T_D3_*` 增补幂等断言（相同身份重放返回既有 id、计数不变）；`tests/test_fill_wire_fix4.py::B4` 更新为 R4 严格口径（复合注记 `order:C1 fill:X` 从"人工接受"翻转为拒绝——说明走 detail）。

## 本轮固化口径

- **shadow 探测**：仅 `Ledger.get_legacy_fill`（显式 `WHERE symbol IS NULL`）；
  裸 `get_fill(fill_id)` 在多行同 ID 时命中任意一行，文档已标注不得用于探测。
- **覆盖证据**：fact 与成交必须同属一个 client_order_id（归属核验）；
  未提供归属 = fail-closed 无证据。
- **重算事件身份**：(COALESCE(symbol,''), fill_id, old_ctx, new_ctx,
  basis_ref) 唯一索引 + 前置查重；一致重放返回既有 id 零追加。
- **机器引用**：首 token 命中机器前缀（含裸前缀）即按机器引用整串严格解析；
  附加文字拒绝，说明走独立 `detail` 参数。无机器前缀的自由文本 = 人工处置。

## 计数更正（相对 fix4 证据包）

- `clone_run.txt` 的 `Ran 885 … skipped=1` = **884 通过 + 1 skip**（此前误登
  "885 通过另加 1 skip"）。skip 归属更正为 S1 `incident ledger absent`
  （T_M3_IncidentCopyDrill），非 G0-4D 探针。

## 安全边界（不变）

- LIVE=NO-GO；kill switch 不清除；真实账本未触碰；密钥不出现。
- 红证据使用 detached git worktree；不再使用 stash/pop/reset 制作证据。
