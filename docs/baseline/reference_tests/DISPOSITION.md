# ADR-013 / C3 — Reference 测试归属与处置清单

日期：C3 批次。身份裁定沿用 ADR-013：
`aurora/kernel/` 为唯一生产执行内核；`aurora/execution_truth.py` 为
**离线参考实现**（TRACKED / OFFLINE_REFERENCE_ONLY）；生产代码禁止导入；
quarantine 模块不恢复；reference 测试不构成生产安全性证明。

## 一、原件溯源（首次进入 Git 前的现场记录）

以下文件此前均为**未跟踪文件**，C3 是它们首次进入 Git 历史。
采集时点：C3 批次执行时；SHA-256 与字节数如下。

| 文件 | sha256 | bytes | 处置 |
|---|---|---|---|
| aurora/execution_truth.py | 3f7c3e38f7822d89eed1c7ffccedf4f7908747a71a0ffd6444a50a721ebb1f50 | 62148 | 跟踪入库（头部加 OFFLINE_REFERENCE_ONLY 标注；reconcile() 依赖解耦为显式 NOT-BUILT） |
| tests/test_execution_truth.py | d61b3ef456b35e7d39412034d95bae20ebcdbd70757066b78177454b70550961 | 8422 | 跟踪入库；4 条 boot/reconcile 相关断言按下表处置 |
| tests/test_execution_truth_p0b2.py | bf729f8f1d5e0e1cff1142631626360e6d6a33731666efad9b98edafa55d9383 | 4157 | 跟踪入库，保持可运行 |
| tests/test_execution_truth_review.py | a014e9c37cf9e018433b915cb790172d976e570ffa2659c2bdd86e1f025422a8 | 7214 | 跟踪入库，保持可运行 |
| tests/test_execution_truth_p0b3.py | f12df5048ab037e7995512506bb1f039a350f4669c296c060e6704071bb31ca6 | 4837 | 原件归档 → 本目录 `.py.txt` |
| tests/test_execution_truth_p0c.py | 6d52e6703327c94cf844027c77f911f560a9ff21a4c3fc24ae018defb49e308c | 3699 | 原件归档 → 本目录 `.py.txt` |

归档件均为 `.txt`，pytest 不收集；不得改回 `.py` 重新混入测试树。

## 二、test_execution_truth.py 四条失败逐断言处置

四条失败的公共根因：`DurableExecutor.boot()/reconcile()` 依赖
`aurora.reconciler.Reconciler` —— 该模块**从未实现**（无 Git 历史、无
quarantine 副本）。reference 侧已把 `reconcile()` 改为显式
`NotImplementedError(NOT-BUILT)`，避免悬挂 import 被误认为可恢复缺口。

| 原测试 nodeid | 原验证合同 | 原依赖 | 处置 | 当前对应 | 结果 |
|---|---|---|---|---|---|
| `test_submit_unknown_results_in_unknown_state` | 提交未知 → 仓位 UNKNOWN + halt；重启后仍 UNKNOWN 且拒绝 | `aurora.reconciler`（仅尾部 boot） | 拆分：前半保留并运行；boot 尾部归档至 `test_execution_truth_boot_reconcile.spec.txt`，改写为 `open_position` 等价拒绝 | kernel `test_g6_unknown_position_forbids_new_open` 同合同 | PASS（可执行部分） |
| `test_boot_reconcile_detects_drift` | 启动时 exchange 有仓位而 ledger flat → 必须识别漂移、进入 UNKNOWN，不得静默当 flat | `aurora.reconciler` | 原件归档（spec.txt） | **REQUIRED_UNCOVERED**：kernel `recover()` 只遍历持久化 intent，无 intent 时不检查仓位漂移。登记缺口 **BOOT-DRIFT**，关联 G0 后续工作包 | 未实施 |
| `test_boot_matches_when_both_flat` | 双侧 flat 时启动对账通过 | `aurora.reconciler` | 原件归档（spec.txt） | 部分对应 kernel 启动恢复族（`test_g8_pending_order_recovered_on_startup` 等只覆盖 pending intent 恢复，非启动仓位判定） | 未实施（spec） |
| `test_ledger_rebuilds_position_across_restart` | 重启后账本重建仓位；boot 通过 | 重建部分无外部依赖；boot 尾部依赖 `aurora.reconciler` | 拆分：重建断言保留运行；boot-ok 断言归档；新增重启后 `open_position` 拒绝断言 | kernel `test_g7_kill_switch_survives_restart`/`test_g8_*` 为同族恢复合同 | PASS（可执行部分） |

## 三、test_execution_truth_p0b3.py（原件归档）

缺失依赖：`aurora.binance_port`（已退役的 BinancePort 组装层）、
`aurora.reconciler`。

| 原测试 nodeid | 原验证合同 | 处置 | 当前对应 | 结果 |
|---|---|---|---|---|
| `P0B3BinancePortTests::test_submit_query_cancel_mapping` | raw 下单/查询/撤单载荷 → 端口类型化结果，含 fills/fee、client_order_id→newClientOrderId 映射 | **已迁移** | `tests/test_kernel_binance_exchange_mapping.py::test_submit_query_cancel_mapping` + `test_fills_mapping_includes_fee`（BinanceExchange） | PASS |
| `P0B3BinancePortTests::test_position_mapping` | positionAmt/entryPrice → 仓位对象（LONG/数量/入场价） | **已迁移** | `test_position_mapping_long`（signed_qty>0 即 LONG 语义） | PASS |
| `P0B3BinancePortTests::test_position_flat` | 零仓位 → FLAT | **已迁移** | `test_position_flat` | PASS |
| `P0B3ReconcilerTests::test_reconcile_match_after_open` | 开仓后三方对账 MATCHED | 归档（spec） | kernel per-intent 恢复族部分对应；仓位级三方对账 **REQUIRED_UNCOVERED** | 未实施 |
| `P0B3ReconcilerTests::test_reconcile_drift_size_mismatch` | 数量不一致 → DRIFT + UNKNOWN | 归档（spec） | **REQUIRED_UNCOVERED**（BOOT-DRIFT 同族） | 未实施 |
| `P0B3ReconcilerTests::test_reconcile_exchange_open_ledger_flat` | exchange 开 / ledger flat → DRIFT | 归档（spec） | **REQUIRED_UNCOVERED**（BOOT-DRIFT） | 未实施 |

注意：迁移用例只覆盖 raw→typed 映射；**未迁移** G0-4 的协议级合同
（`workingType`/`closePosition`/`timeInForce`/`price`、条件单类型、
HEDGE vs ONE_WAY 账户模式核对、错误码/限频/重试语义、真实 testnet
协议验证）。旧文件中 `positionSide: LONG` 的请求形状不视为已验证的
真实交易所合同。

## 四、test_execution_truth_p0c.py（原件归档）

缺失依赖：`aurora.shadow_adapter`、`aurora.reconciler`（间接）。
`aurora.capital_controller` 仍存在但 ShadowAdapter 已退役。

| 原测试 nodeid | 原验证合同 | 处置 | 当前对应 | 结果 |
|---|---|---|---|---|
| `test_shadow_open_long` | SHADOW 决策→只读镜像执行，含 SL/TP 记录 | 历史规格归档 | Legacy ShadowAdapter **RETIRED**；V2 ShadowRunner **NOT-BUILT / NOT-COVERED** | 未实施 |
| `test_shadow_open_short` | 同上 SHORT 方向 | 同上 | 同上 | 未实施 |
| `test_shadow_flat` | 决策 FLAT → 镜像回到 KNOWN_FLAT | 同上 | 同上 | 未实施 |
| `test_shadow_flat_when_no_position` | 无仓位时 FLAT 决策 agree | 同上 | 同上 | 未实施 |

仍适用于未来 ShadowRunner 的要求（决策→镜像一致性、风险态传播）
关联后续 ShadowRunner 验收工作包，不在本批实现。

## 五、生产导入隔离

- 静态扫描：`aurora/` 下除 `execution_truth.py` 外无任何源文件导入
  `aurora.execution_truth`（`tests/test_reference_isolation.py`）。
- 干净子进程 `import aurora.production_main` 后
  `aurora.execution_truth` 不在 `sys.modules`。
- reference 源文件不含 `binance.client`/`ccxt`/`import requests`/
  `BINANCE_API` token。

## 六、剩余缺口登记（不消失）

- **BOOT-DRIFT / REQUIRED_UNCOVERED**：启动期仓位级三方对账（exchange
  open & ledger flat → 不得静默 flat；数量不一致 → UNKNOWN）。关联 G0
  后续工作包。
- **G0-4**：Binance 适配器协议级合同（见第三节）。
- **ShadowRunner**：NOT-BUILT / NOT-COVERED，历史规格保留。
- **reference Decimal 语义**：保留参考价值；不等于已迁入生产账本
  （生产 ledger 迁移属 C4，不在本批）。
