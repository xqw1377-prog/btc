# S3 固定代码候选复验（等待独立裁定）

- 代码候选：`502ac70239f4d79c38ff635d8dbd636445eced90`
- 登记：**固定代码候选 / 克隆复验日志已附**。不是独立复验通过，不签 PASS。
- 本包不改 `CAPABILITY_STATUS.md`，不含 `P3_R3_1_RISK_ADJUDICATOR_PLAN.md`。
- 原始日志：`clone_run.txt`（该提交的全新 `git clone`，工作区干净）。

## 与先前工作区自测的区别

`/tmp/aurora-s3-clean` 是当时工作区的无 Git 副本，不是提交克隆。
那里的 935 passed / 0 skipped **不能**绑定到可复验提交：工作区里有
`state/kernel_ledger.db`，事故副本演练因此会执行并通过。全新克隆没有
这份账本，同一项跳过。

| 运行 | 对象 | passed | failed | errors | skipped |
|---|---|---:|---:|---:|---:|
| 专项 unittest | `502ac70` 克隆 | 22 | 0 | 0 | 0 |
| 全套 pytest | `502ac70` 克隆 | 934 | 0 | 0 | 1 |

跳过项：`tests/test_fill_migration_s1.py:93` `incident ledger absent`。
pytest 退出码 0。unittest 输出 `OK`，无 skipped 行。

## 命令与环境

```text
git clone /Users/xinquanwang/AURORA /tmp/aurora-s3-502ac70
cd /tmp/aurora-s3-502ac70
python3 -m unittest tests.test_fill_fee_projection_s3
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q --tb=no -ra
```

Darwin 25.3.0 arm64；Python 3.9.6
`/Library/Developer/CommandLineTools/usr/bin/python3`。

## 交付里必须分开的两点

一致补充的零增量，不是免掉已知基线的首次记账。`T-FP7` 证明：

- 补充前成交行已有 `fee_raw=0.5`、`economic_effect_applied=1`，且 `fee>0`；
- 补充后这三项不变，`accounting_aggregate().total_fees` 不变；
- `fee_effect_ledger` 没有新的 APPLY（不第二次扣同一笔）；
- 再来一条一致补充仍然不加效果。
- 若已知基线没有这条既有记账，或 `fee_raw` 对不上，补充路径拒绝，
  不用“零增量”把首次记账免掉。

10000 是精度资源上限，不得突破：

- 显著位数超过 10000：比较抛 `ComparisonRefused`（同一串也不当相等）；
  加减在构造 Decimal 之前抛 `PrecisionRefused`。
- 空值仍是 UNKNOWN（`None`）。无法比较的结果不当 UNKNOWN、不当相等。
- 翻倍重试夹在上限上：6000 → 6000 与 10000；已是 10000 则不再加；
  10001 直接拒绝。

## 14 项合同 ID → 22 项测试

| 合同 ID | 测试 |
|---|---|
| T-F2e | `T_F2e_EntrySemantics.test_known_declaration_requires_finite_raw_and_asset`；`test_schema_check_enforces_pairing` |
| T-F4 | `T_F4_NumericEquality.test_numeric_equality_representation_independent` |
| T-F4R | `T_F4R_LegacyFloatExcluded.test_legacy_float_fee_never_produces_conflict` |
| T-FP1 | `T_FP1_FirstDeterminationOnce.test_unknown_single_supplement_projects_v1_once`；`test_same_stable_id_different_content_conflicts` |
| T-FP2 | `T_FP2_DoubleUnknownIncomplete.test_double_unknown_stays_incomplete` |
| T-FP3 | `T_FP3_ConflictRetainsBaseline.test_known_baseline_conflicting_supplement` |
| T-FP4 | `T_FP4_OnlyExplicitCorrectionRecomputes.test_supplement_never_recomputes_correction_does_delta` |
| T-FP5 | `T_FP5_EffectKeyIdempotency.test_effect_key_replay_rejected_and_old_key_dead` |
| T-FP6 | `T_FP6_ThreeStepAtomic.test_effect_failure_rolls_back_supplement`；`test_projection_step_failure_rolls_back_supplement`；`test_caller_open_transaction_refused_before_write` |
| T-FP7 | `T_FP7_ConsistentSupplementZeroImpact.test_consistent_supplement_zero_impact` |
| T-FP8 | `T_FP8_ConflictedIsolatedNoAutoDelta.test_conflicting_supplements_isolated_then_correction`；`test_correction_requires_credential` |
| T-FP9 | `T_FP9_CrossAssetDoubleLeg.test_cross_asset_correction_double_leg_atomic`；`test_leg_evidence_insufficient_neither_applied` |
| T-F6a | `T_F6a_LongTailLossless.test_long_tail_subtraction_lossless` |
| T-F6b | `T_F6b_InputBoundsRefusal.test_entry_bounds_rejected`；`test_inexact_after_retry_refused`；`test_correction_with_inexact_refused_nothing_applied` |

## 未授权、未改变

消费方不接线。funding 不接线。真实账本不迁移。
`LIVE=NO-GO`。交易权限不变。
`P3-R3.1` 仍是 CHANGES-REQUIRED，实现未授权。本轮未审代码闭合。
