# P4 账户真相证据

固定方案：`ab2e872417e43b4665cd16b7a4873f826974f5fc`  
红测试：`87a956f3fb89ed38232e524f25a346dd5169a839`  
实现：`9a312ad009f3ddb4662cf377fd6b310c017a1cce`

这是开发方克隆复跑，不是独立复验，也不是 RUNTIME-PASS。

七项语义反例的红／绿证据在 `fix1/`，不改写上面的模块缺失记录。

| 运行 | 载体 | 结果 |
|---|---|---|
| 红 | 全新克隆，detached `87a956f`，模块不存在 | 1 passed，42 failed。`AssertionError` 0。`ModuleNotFoundError` 41。`FileNotFoundError` 1（静态扫描） |
| 专项 | 全新克隆，detached 实现提交，账本不在 | unittest `Ran 43 tests` OK；pytest 43 passed |
| 全套 | 同一克隆，`state/kernel_ledger.db` 不在 | 1013 passed，1 skipped（S1 incident ledger absent） |

E2 / E1 相对方案 `ab2e872` 的 diff 为 0 字节。全套计数不与账本在场的工作树计数合并。

通过夹具仍保持 `reality_authority=NOT_ESTABLISHED`、`account_authority=NOT_ESTABLISHED`、`new_risk_usable=false`。

| ID | 测试 |
|---|---|
| 正向计价 | `test_at_positive_full_valuation` |
| BTC 恒等 | `test_at_btc_amount_is_identity` |
| 负债只扣一次 | `test_at_spot_gross_liability_deducted_once` |
| AT-1 | `test_at_01_missing_account_ref` |
| AT-2 | `test_at_02_same_version_conflict_does_not_replace_hash` |
| AT-3 | `test_at_03_new_version_appends_and_keeps_existing_set` |
| AT-4 | `test_at_04_missing_btc_row_is_not_zero` |
| AT-5 | `test_at_05_explicit_zero_stays_known_while_other_gaps_block` |
| AT-6 | `test_at_06_negative_wallet_balance` |
| AT-7 | `test_at_07_positions_missing` |
| AT-8 | `test_at_08_positions_garbage_is_not_flat` |
| AT-9 | `test_at_09_explicit_zero_qty_is_flat` |
| AT-10 | `test_at_10_hedge_legs_without_mode` |
| AT-11 | `test_at_11_fee_manifest_missing_is_not_zero` |
| AT-12 | `test_at_12_fee_page_not_finished` |
| AT-13 | `test_at_13_funding_missing_does_not_read_e0_zero` |
| AT-14 | `test_at_14_truncation_and_partial_late_stay_partial` |
| AT-15 | `test_at_15_quote_direction` |
| AT-16 | `test_at_16_unpinned_price_rejected` |
| AT-17 | `test_at_17_non_finite_is_not_washed_to_null` |
| AT-18 | `test_at_18_legal_null_quote_stays_null` |
| AT-19 | `test_at_19_bad_timestamps` |
| AT-20 | `test_at_20_future_timestamp` |
| AT-21 | `test_at_21_sla_and_skew` |
| AT-22 | `test_at_22_null_sla_is_incomplete_policy` |
| AT-23 | `test_at_23_one_face_unknown` |
| AT-24 | `test_at_24_mismatch_does_not_write_back` |
| AT-25 | `test_at_25_synthetic_cannot_become_authority` |
| AT-26 | `test_at_26_same_input_same_policy_same_bytes` |
| AT-27 | `test_at_27_static_scan` |
| AT-28 | `test_at_28_wallet_once_and_quote_orientations` |
| AT-29 | `test_at_29_settled_flows_are_not_applied_again` |
| AT-30 | `test_at_30_mixed_wallets_and_one_sided_transfer` |
| AT-31 | `test_at_31_set_proof_and_duplicates` |
| AT-32 | `test_at_32_self_reported_authority_is_not_established` |
| AT-33 | `test_at_33_window_states` |
| AT-34 | `test_at_34_event_identity_and_late_version` |
| AT-35 | `test_at_35_evaluation_time_does_not_hide_conflict` |
| AT-36 | `test_at_36_independence_and_mark_move_without_cash` |
| AT-37 | `test_at_37_tolerance_and_scope` |
| AT-38 | `test_at_38_numeric_limits_and_policy_identity` |
| AT-39 | `test_at_39_negative_pnl_negative_nav_and_bad_quote` |
