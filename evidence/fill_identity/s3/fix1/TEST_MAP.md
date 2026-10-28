# S3 CHANGES-REQUIRED 复验提交（802e0b6）

- 固定代码：`802e0b63d733bae422f3eb8eed08fb834b27e4de`
- 上一候选 `502ac70` / 证据 `f50063d` 的五项阻断在本提交关闭。
- 本包不签 PASS。消费方 / funding 仍 HOLD。真实账本不迁移。
- 原始日志：`clone_run.txt`（该提交的 `git clone` 后 detached checkout）。

| 运行 | passed | failed | errors | skipped |
|---|---:|---:|---:|---:|
| 专项 unittest | 29 | 0 | 0 | 0 |
| 全套 pytest | 941 | 0 | 0 | 1 |

跳过项仍是 `tests/test_fill_migration_s1.py:93` `incident ledger absent`。
克隆里没有 `state/kernel_ledger.db`。原有 22 项仍在这 29 项里。

## 五项反例

| 阻断 | 测试 |
|---|---|
| S3-01 UNKNOWN 补充不再把已知基线重记全额 | `S3_01_UnknownSupplementDoesNotRebook.test_unknown_supplement_does_not_rebook_known_baseline` |
| S3-02 无投影行的同资产修正是差额 0.2，不是 APPLY 0.7 | `S3_02_CorrectionSeesBookedBaseline.test_same_asset_correction_is_delta_not_full_apply` |
| S3-02 跨资产同样先认已记账基线，再双蹄 | `S3_02_CorrectionSeesBookedBaseline.test_cross_asset_correction_reverses_booked_baseline` |
| S3-03 解决后旧证据重放保持 KNOWN v2；新冲突仍暴露 | `S3_03_ResolutionStaysInForce.test_resolved_projection_survives_replay_and_matching_supplement` |
| S3-04 锁库上抛并回滚；缺表才是空 | `S3_04_ReadFailureIsNotEmpty.test_locked_supplement_read_rolls_back_whole_write`；`test_absent_table_is_empty_locked_read_is_raised` |
| S3-05 9997 位减零，公式 10001，直接 PrecisionRefused | `T_F6b_InputBoundsRefusal.test_formula_over_cap_refused_without_truncation` |

## 未改变

S1 / S2 未重开。消费方不接线。funding 不接线。真实账本不迁移。
`P3-R3.1` 实现未授权。`LIVE=NO-GO`。交易权限不变。
