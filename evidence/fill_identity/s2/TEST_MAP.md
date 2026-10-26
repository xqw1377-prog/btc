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

## 尚未覆盖（入口层接线——**已属 S2 范围，待修正复验后执行**）
T-I4 入口半 / T-I5 / T-DB1 / T-DB2 / T-C1 / T-C2 / T-X1 / T-X2 / T-D3
——这些需要修改 Ledger.insert_fill 与 orchestrator.apply_fill_event
调用本模块（触及生产入口路径），是否在本开工令范围内待评审指示。
