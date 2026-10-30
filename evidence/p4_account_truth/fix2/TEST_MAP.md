# P4-03／04／07 残留反例

固定方案：`ab2e872417e43b4665cd16b7a4873f826974f5fc`  
上一轮七项修复：`b6494188eedf02c65654a70604c9053f25ef576d`  
残留红：`9843ca4a47fbfba69aefbc8965a96fd5fce4f871`  
残留修复：`afa441923b8e6c1ff84cd98c22c7f908abf4fc8a`

P4-01、02、05、06 保持关闭。这是开发方克隆复跑。P4 RUNTIME 仍是 CHANGES-REQUIRED，待独立复审。

| 项 | 测试 | 红（9843ca4） | 绿（afa4419） |
|---|---|---|---|
| P4-03 | `test_p4_03b_window_shape_and_event_account` | AssertionError：畸形窗口仍 COMPLETE | 通过 |
| P4-04 | `test_p4_04b_used_quote_requires_time` | AssertionError：缺 `as_of` 仍发布净值 | 通过 |
| P4-07 | `test_p4_07b_limits_before_copy_and_event_sum` | AssertionError：`unhandled _Stop` | 通过 |

原有 50 项在红克隆上仍然通过。绿克隆专项 unittest `Ran 53 tests` OK；全套 `1023 passed / 1 skipped`。skip 仍是 S1 `incident ledger absent`。

```text
P4 PLAN               = PASS / CLOSED
P4 RUNTIME            = CHANGES-REQUIRED
P3-R3.1               = CLOSED / RUNTIME-PASS / READ-ONLY
S1 / S2 / S3          = CLOSED / OFFLINE PASS
真实账户／接线／迁移 = NOT AUTHORIZED
LIVE / TESTNET WRITE  = NO-GO / DENIED
TRADING AUTHORITY     = UNCHANGED
```
