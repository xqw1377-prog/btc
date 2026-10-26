# S2 测试映射（v2：25 方法 → 合同 ID；含评审四阻断反例）

## 评审反例（红→绿）
| S2-01 cid 入身份 | S2ReviewRepros::test_S2_01_cid_is_identity_fact |
| S2-02 非数值双 UNKNOWN | test_S2_02_nonnumeric_double_unknown_is_incomplete |
| S2-03 EVENT 认 raw/跨等级/非法拒收 | test_S2_03_event_reads_raw_not_real_and_detects_diff / test_S2_03_cross_tier_cannot_confirm_match / test_S2_03_negative_qty_is_invalid_not_matchable |
| S2-04 推导上下文比较 | test_S2_04_derivation_ctx_comparison（同ctx偏离+异ctx显式重算） |


| 合同 ID | 测试方法 |
|---|---|
| T-I3 | ValidatorMismatchTests::test_field_mutation_matrix / test_symbol_mutation_is_mismatch |
| T-I6 | ValidatorMatchIncompleteTests::test_full_match / test_known_vs_unknown_incomplete_either_direction / test_double_unknown_is_incomplete_not_match / test_null_rows_do_not_crash |
| T-F1 | ValidatorMismatchTests::test_field_mutation_matrix（fee 变异子项） |
| T-F3/F3R | RawPrecisionTests::test_illegal_raws_are_unknown_not_crash |
| T-F4 | RawPrecisionTests::test_representation_independent_equality |
| T-Q1d | RawPrecisionTests::test_support_range_cap |
| T-D1 | DerivationTests::test_same_ctx_consistent |
| T-D2 | DerivationTests::test_same_ctx_deviation_not_identity（DEVIATION 分类；风险边界断言在入口层接线时补） |
| T-D4 | DerivationTests::test_legacy_no_ctx_not_checked（path=NO_CTX）+ S2ReviewRepros 异 ctx→EXPLICIT_RECOMPUTE |
| T-R1a | RefResolutionTests::test_new_ref_validation_rejects_bare_and_dangling（裸 ID 拒收） |
| T-R1b | test_qualified_ref_resolves / test_bare_id_unique_symbol_resolves / test_bare_id_multi_symbol_ambiguous |
| T-R1c | test_new_ref_validation_rejects_bare_and_dangling（悬空拒收） |
| T-R2 | test_null_legacy_location_is_not_identity（定位≠身份） |
| T-R3/I4e/I2 | test_attribution_anomaly（ATTRIBUTION_ANOMALY + ORDER_NOT_FOUND） |

## S2-03 残留修正（v3 反例）
| 历史 fee float 不参与比较 | S2_03_ResidualRepros::test_legacy_fee_float_not_in_comparison |
| 跨等级不掩盖已知 cid 冲突 | test_cross_tier_does_not_mask_known_cid_conflict |
| 未知 origin 拒收 | test_unknown_origin_rejected |

## 入口接线（已执行）

| 合同 ID | 测试方法（S2_EntryWiringTests） |
|---|---|
| T-DB1 | test_T_DB1_fk_violation_not_swallowed（FK 上抛不吞 DUPLICATE） |
| T-DB2 | test_T_DB2_fk_and_check_distinguishable（FOREIGN KEY vs FillIdentityConflict 可区分） |
| T-C1 | test_T_C1_concurrent_same_identity_exactly_once（独立连接并发，恰一条） |
| T-C2 | test_T_C2_concurrent_conflict_not_lost（并发冲突可见） |
| T-X1 | test_T_X1_both_entries_same_report（两入口同一校验器同一冲突字段） |
| T-X2 | test_T_X2_legacy_w43_tests_unchanged（W43 冲突断言不改+签名一致） |
| T-I4e | test_T_I4e_entry_layer_rejects_event_without_symbol（同内容重放=DUPLICATE 幂等） |
| T-I5 | test_T_I5_identity_unresolved_not_adopted（冲突不收养、不写新行） |
| T-D3 | test_T_D3_explicit_recompute_does_not_overwrite（EXPLICIT_RECOMPUTE 分类；完整重算事件归 S3） |

接线说明：旧 schema 账本行与 Fill 事件同为 REAL 近似通道——
两侧行均以 HISTORY 模式（调用路径声明）比较，离散冲突与数值
差异都能暴露；跨等级（raw EVENT vs 无 raw 历史）场景保留
compare_mixed，模式仍由调用路径决定。compare_mixed 未成为第
二套校验器——它只增加跨等级分层，字段集与裁决词表同源。
