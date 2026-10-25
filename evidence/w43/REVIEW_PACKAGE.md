# W43 独立复验材料包（c318bc8 → ee412a7）

> 性质：复验材料交付。本轮零功能变更、零授权变化。
> 状态：W43 OFFLINE ABSORPTION = SELF-VERIFIED / REVIEW-PENDING。

## 1. 提交与分支

```text
branch   safety/p0a-mainnet-isolation
c318bc8  c318bc8d9ce29671dd4b3f2beb12830ab431ac6a
ee412a7  ee412a7ab13f415d2e6aa24981a8ca2ebdf54a32
中间提交 7ab8e1a（e3 ablation，研究报表，非本复验对象）
```

## 2. 测试数量差异（回执更正）

我此前回执写"+8 项"是**算术错误**：把 FillIdentityConflictTests 的
4 个断言变体误计为 4 个测试。精确差异（--collect-only 双提交对比，
已核）：

```text
c318bc8  739 collected
ee412a7  745 collected
净增      +6，删除 0

ADDED（全部 6 项，文件 tests/test_external_digest_w43.py）:
  A1CrossProcessRestartTests::test_submit_once_holds_across_real_process_restart
  A4FundingIncomeTests::test_decimal_precision_and_multi_asset_no_cross_sum
  A4FundingIncomeTests::test_same_id_different_content_raises_conflict
  A4FundingIncomeTests::test_window_completeness_semantics
  FillIdentityConflictTests::test_identical_replay_ignored
  FillIdentityConflictTests::test_same_id_different_content_raises
```

## 3. 实际测试命令与原始结果

```text
命令   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q
ee412a7（主工作树）：745 passed, 1 warning（raw_run_ee412a7_worktree.txt）
c318bc8（干净 worktree）：735 passed, 4 FAILED（raw_run_c318bc8_worktree.txt）
```

**新发现（如实登记，本轮不修）**：测试套件不封闭。干净 worktree 中
`test_controlled_requal.py::MainAndSourceTests` 的 4 项失败源于对
仓库根 `.env` 与 `state/` 运行时文件的依赖（均被 gitignore）——同
一提交在主工作树为 739 passed。复验应在两种环境各跑一次并注明。

## 4. 跨进程测试入口与故障注入点

```text
入口   tests/test_external_digest_w43.py::
       A1CrossProcessRestartTests::test_submit_once_holds_across_real_process_restart
故障点 FakeExchange(entry_behavior="timeout_then_filled")：
       submit 抛 SubmitUnknownError，而交易所侧订单已存在且已成交
       ——即"交易所已接受、客户端未收到响应"窗口
阶段一 子进程：开仓遇 SUBMIT_UNKNOWN → 账本落盘 + pickle 交易所
       状态 → 进程正常退出（受控退出）
阶段二 另一子进程：加载 → recover() → 断言 ENTRY 提交数=1、
       原 ID 归属、fills 聚合 0.01
```

**证据边界（与复审第 3 点一致，不冒充）**：这是**受控退出后的恢复**
证明，不是任意崩溃点证明。未覆盖的微窗口：交易所接受与账本
SUBMITTING 写入之间被硬杀（ledger-first 设计上 SUBMITTING 在提交前
落盘、且 SUBMITTING 属 PENDING_ORDER_STATES 会被恢复查询——设计
覆盖，但**未在进程边界上测试**）。不登记为 crash-consistency 完整验证。

## 5. 账本 schema/迁移差异

```text
DDL 变更     0（git diff c318bc8..ee412a7 无 CREATE/ALTER）
代码路径变更 insert_fill 的 IntegrityError 分支增加内容比对→冲突告警
旧账本兼容   事故账本副本打开验证：OK，kill=1、intents 可读
             （原件未触碰；副本测试）
迁移需求     无
```

## 6. 复审四疑点的登记裁定（真缺陷 vs 回执表述不足）

| # | 复审疑点 | 裁定 |
|---|---|---|
| 1 | 测试数量不一致 | **回执表述错误**（本包更正：净增 6） |
| 2a | 密钥轮换后账本连续性 | **真缺口**：未设计/未测（指纹变更=新命名空间目录，旧账本归属与续接规则未冻结） |
| 2b | fill_id 是否需 symbol 等作用域 | **真缺口**：当前作用域=账本物理命名空间；交易所侧 ID 全局唯一性未按 symbol 核验登记 |
| 2c | fee/费资产/realized_pnl 变化是否触发冲突 | **真缺口**：当前冲突键仅 cid/qty/price/side；经济字段不一致仍被静默忽略 |
| 3 | 崩溃一致性边界 | **真缺口**（受控退出证明 ≠ 任意崩溃点；SUBMITTING 窗口设计覆盖、边界未测） |
| 4 | COMPLETE 的来源证据 | **真缺口**：declare_window 为调用方布尔断言；无分页游标/范围/来源存证；迟到降级无历史记录 |

以上 2a–4 均登记为 REVIEW-PENDING 下的已知未覆盖项，**待独立复验
后再决定修复优先级**；本轮不修。

## 7. 状态（不变）

```text
W43 OFFLINE ABSORPTION = REVIEW-PENDING
FUNDING INGESTION      = NOT INTEGRATED
TRADING AUTHORITY      = UNCHANGED
```
