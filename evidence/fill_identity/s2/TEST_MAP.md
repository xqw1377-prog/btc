# S2 测试映射（19 方法 → 合同 ID）

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
| T-D4 | DerivationTests::test_legacy_no_ctx_not_checked |
| T-R1a | RefResolutionTests::test_new_ref_validation_rejects_bare_and_dangling（裸 ID 拒收） |
| T-R1b | test_qualified_ref_resolves / test_bare_id_unique_symbol_resolves / test_bare_id_multi_symbol_ambiguous |
| T-R1c | test_new_ref_validation_rejects_bare_and_dangling（悬空拒收） |
| T-R2 | test_null_legacy_location_is_not_identity（定位≠身份） |
| T-R3/I4e/I2 | test_attribution_anomaly（ATTRIBUTION_ANOMALY + ORDER_NOT_FOUND） |

## 尚未覆盖（入口层接线时——两入口接入是 S2 第二步或评审指示）
T-I4 入口半 / T-I5 / T-DB1 / T-DB2 / T-C1 / T-C2 / T-X1 / T-X2 / T-D3
——这些需要修改 Ledger.insert_fill 与 orchestrator.apply_fill_event
调用本模块（触及生产入口路径），是否在本开工令范围内待评审指示。
