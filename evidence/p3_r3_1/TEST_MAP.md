# P3-R3.1 开发者复跑（9214729）

固定方案：`745e4e0a7737ba2945bc50243be449264759e1b3`  
固定实现：`921472921eb287b1d04cb4d1ff396e6673f7c697`  
红测试：`801d86cc70d217ba85f8b84d82f1807ade74d950`（21 项，20 项导入失败，R31-15 通过）  
开工哈希：`evidence/p3_r3_1/BASELINE.md`

本包是开发者在全新克隆上的复跑，不是独立复验，不签 `RUNTIME-PASS`。  
克隆方式：`git clone` 后 `git checkout --detach 9214729`。克隆里没有 `state/kernel_ledger.db`。  
原始日志：`clone_run.txt`。

环境：macOS 26.3 arm64，Python 3.9.6。

| 运行 | passed | failed | errors | skipped |
|---|---:|---:|---:|---:|
| 专项 unittest | 21 | 0 | 0 | 0 |
| 全套 pytest | 962 | 0 | 0 | 1 |

跳过项是 `tests/test_fill_migration_s1.py:93` `incident ledger absent`。  
同一工作树另有一次全套 `963 passed / 0 skipped`，因为工作树里事故账本文件在，那一项被执行了。不要把 963 和 962/1 加在一起，也不要把它当成克隆结果。

## 验收项

| ID | 测试 |
|---|---|
| R31-1 | `test_r31_1_in_process_record_has_no_order` |
| R31-2 | `test_r31_2_same_input_record_bytes_receipt_differs` |
| R31-3 | `test_r31_3_request_10_policy_6_reduced` |
| R31-4 | `test_r31_4_inflated_output_is_not_persisted` |
| R31-5 | `test_r31_5_null_nav_blocks_without_zero_fill` |
| R31-6 | `test_r31_6_stale_account_or_quote_blocks_new_risk` |
| R31-7 | `test_r31_7_unknown_position_defensive_quantity_unavailable` |
| R31-8 | `test_r31_8_protection_cases_stay_separate` |
| R31-9 | `test_r31_9_eth_and_event_execution_stay_denied` |
| R31-10 | `test_r31_10_kill_blocks_new_risk_and_probes_stay_zero` |
| R31-11 | `test_r31_11_cross_process_replay_bytes` |
| R31-12 | `test_r31_12_mid_write_failure_rolls_back_and_retry_matches` |
| R31-13 | `test_r31_13_runtime_probes_stay_zero` |
| R31-14 | `test_r31_14_static_import_scan` |
| R31-15 | `test_r31_15_e2_e1_hashes_match_baseline` |
| R31-16 | `test_r31_16_declaration_conflict_and_legal_new_version` |
| R31-17 | `test_r31_17_time_rules_ignore_wall_clock` |
| R31-18 | `test_r31_18_known_does_not_become_authority` |
| R31-19 | `test_r31_19_invalidation_appends_and_new_version_may_allow_more` |
| R31-20 | `test_r31_20_numbers_priority_and_unwritable_log` |
| R31-21 | `test_r31_21_process_replay_and_concurrent_bindings` |

R31-17 的墙钟探针改的是合同层 `_now_iso`。这台 Python 3.9 不允许替换内置 `datetime.now`。裁决器源码不得出现 `datetime.now` 或 `time.time`，由 R31-14 扫描。

## 未改变

不接 `trading_cycle` / `production_main` / 旧 RiskGate。不改 E2/E1。不实现 R3.2 / P3-R4。不接费用消费方或 funding。不迁移真实账本。不解除 kill。不发测试网订单。

```text
P3-R3.1 PLAN           = PASS / CLOSED
P3-R3.1 IMPLEMENTATION = AUTHORIZED / READ-ONLY
P3-R3.1 RUNTIME       = NOT YET VERIFIED
S1 / S2 / S3          = CLOSED / OFFLINE PASS
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
