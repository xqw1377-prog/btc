# P4 七项语义反例

固定方案：`ab2e872417e43b4665cd16b7a4873f826974f5fc`  
原模块缺失红证据：`87a956f`，见 `../red_run.txt`，本目录不改写它。  
语义红：`c2a026c033b16667db7da9ba786a62b9db47f689`  
语义修复：`b6494188eedf02c65654a70604c9053f25ef576d`

这是开发方克隆复跑。P4 RUNTIME 仍是 CHANGES-REQUIRED，待独立复审，不是 RUNTIME-PASS。

| 项 | 测试 | 红（c2a026c） | 绿（b649418） |
|---|---|---|---|
| P4-01 | `test_p4_01_quantity_not_pnl_decides_flat` | AssertionError：`FLAT != KNOWN` | 通过 |
| P4-02 | `test_p4_02_liabilities_and_scope_are_validated` | AssertionError：仍发布净值 | 通过 |
| P4-03 | `test_p4_03_complete_window_validates_events_and_totals` | AssertionError：`COMPLETE == COMPLETE` | 通过 |
| P4-04 | `test_p4_04_time_and_quote_rules_keep_full_precision` | AssertionError：仍通过 | 通过 |
| P4-05 | `test_p4_05_policy_body_enters_binding_identity` | AssertionError：`REPLAY != CONFLICT` | 通过 |
| P4-06 | `test_p4_06_missing_lineage_is_not_a_match` | AssertionError：`MATCH == MATCH` | 通过 |
| P4-07 | `test_p4_07_limits_apply_before_parse` | AssertionError：没有 `RESOURCE_LIMIT` | 通过 |

原有 43 项在红克隆上仍然通过。绿克隆专项 unittest `Ran 50 tests` OK；全套 `1020 passed / 1 skipped`。skip 仍是 S1 `incident ledger absent`。

```text
P4 PLAN               = PASS / CLOSED
P4 RUNTIME            = CHANGES-REQUIRED
P3-R3.1               = CLOSED / RUNTIME-PASS / READ-ONLY
S1 / S2 / S3          = CLOSED / OFFLINE PASS
真实账户／接线／迁移 = NOT AUTHORIZED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
