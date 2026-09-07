# AURORA 恢复路线图（事故后重建）

> 本文件是当前唯一权威路线图。README.md / STRATEGY.md / DEPLOYMENT.md 为事故前历史文档，不再代表现状。

## G-1 基线封存（2026-09-07，C6）

```text
G-1_BASELINE   SEALED — 代码基点 0bdde2a，详见 docs/baseline/G1_BASELINE.md
                （封存的是准确可追溯基线，不是"G0 已修完"）
当前能力真源    docs/product/CAPABILITY_STATUS.md
G0 开放项       BOOT-DRIFT(G0-1) / G0-4 协议 / G0-5 配置一致性 —— OPEN
LIVE            NO-GO
```

## 状态（2026-09-02，B2.2 后）

```text
分支:   safety/p0a-mainnet-isolation
P0-A    = PASS-REGRESSED → 已修复待独立重定级
          （回归三件：LIVE 先建主网 Client 再拒绝 / 只读 broker 带真实
            cancel / production_main 依赖未跟踪冻结线模块。
            B2.2 已全部修复并以测试钉死；重定级权在 reviewer）
P0-B1   = PASS  (cda0f83  kernel 基线)
P0-B2.0 = PASS-WITH-FIXES (5c095a7)
P0-B2.1 = PASS-WITH-FIXES (76a6d54)
P0-B2.2 = 本提交：COVERED_BY_FACT 证据门控、OCO 撤单竞态、
          终态逃逸边证据化、P0-A 回归修复、测试数对账
execution_truth.py = FROZEN / NOT-BASELINE（原地冻结）
P0-B3（含离线 Adapter 开发）= HOLD
TESTNET = NOT-RUN
LIVE    = NO-GO（无论配置；production_main 在任何 Client 构造之前拒绝 LIVE）
```

### 测试数对账（144 → 106 的解释）

- 76a6d54 提交树真实用例数 = **106**（干净 worktree unittest discovery 实测）；
- 未跟踪并行线（test_execution_truth*.py 五个文件）= **38**；
- reviewer 观测的 144 = 106 + 38（全量 discovery 含未跟踪文件）；
- 此前误报的 121 = 106 + 15（三个后出现的外部文件未被 --ignore 覆盖，
  被 pytest 静默收集且恰好全过）——报告污染，已纠正；
- B2.2 后提交树 = **119**（106 + 13 项新增）。

### B2.2 关键修正

1. **COVERED_BY_FACT 证据门控**：累计数量"容得下"不再构成证据。仅接受
   （a）reconciliation fact 明确列出该 venue trade ID，或（b）与未匹配
   合成调整的确定性替换（SYNTHETIC_REPLACED：撤销合成经济影响、写入
   真实价格/费用/PnL、仓位数量不重复变化）。fills 表新增
   synthetic / replaces_synthetic_fill_id / covered_by_fact_id /
   economic_effect_applied 证据列 + reconciliation_facts 表。
2. **OCO 撤单竞态**：修复流程改为 撤单→等待每腿明确终态→拉 fills→
   拉仓位→（已平仓→对账收敛；仍持仓→先确认强制 SL→再可选 TP，
   仅 TP 失败= safe_but_incomplete 不触发紧急平仓）。
   FakeExchange 支持 cancel_fires_first（撤单窗口内腿按 reduceOnly
   上限成交，不得超射反向开仓）。
3. **终态逃逸边证据化**：RECONCILED/REJECTED/CLOSED → RECOVERY_REQUIRED
   必须携带 exchange_fact=(fact_id, venue_fill_id) 且 reason 以
   EXCHANGE_FACT_CORRECTION 开头，否则状态机拒绝。
4. **P0-A 回归修复**：LIVE 在任何 Client 构造之前拒绝（含双重授权齐全的
   情形）；只读 broker 的 cancel_order 物理拒绝；
   tests/test_production_entry_integrity.py 钉死 production_main 不得引用
   冻结线/未跟踪模块。
5. **并行写入违规处置（2026-09-02 09:10-09:28）**：写入者再次违反冻结，
   改写 7 个已跟踪文件（含 p0_boundary.boot()）并引入具备真实下单能力的
   binance_port.py/shadow_adapter.py/reconciler.py。全部证据已隔离至
   ../AURORA-quarantine-20260902/，被改文件已恢复至 76a6d54。

### B2.1 关键口径（reviewer 裁定，实现于 aurora/kernel/coverage.py）

- `sl_coverage / tp_coverage`：按角色对**去重后活动订单**的剩余数量求和；
- 禁止 SL+TP 相加、禁止全订单取 max（分片场景 0.003+0.003 覆盖 0.006）；
- 强制保护 = `sl_coverage >= exchange_position_qty`；SL 足额而 TP 不足 =
  safe_but_incomplete（单独表达，不并入"已保护"）；
- 迟到 Fill 三分类：DUPLICATE（无经济影响）/ COVERED_BY_FACT（仅关联审计）/
  LATE_NEW_FILL（修正订单累计成交、费用、已实现 PnL，拉取仓位，重算保护，
  终态意图经唯一逃逸边进入 RECOVERY_REQUIRED 并熔断）；
- 保护腿部分成交 → PROTECTION_DEGRADED：按交易所实际剩余仓位精确撤旧腿
  （撤单未知 → RECOVERY_REQUIRED + Kill）并重建，修复期间禁止新开仓。

## 已确立的架构原则

1. **分层真源**：交易所=事实 → SQLite WAL 账本=持久化意图/订单/成交/Kill → 组合状态仅为投影，重启后由 Reconciler 重建。
2. **fail-closed**：任何配置缺失/冲突/探活失败 → 拒绝启动，绝不静默回落主网。
3. **唯一进程入口**：`python -m aurora.production_main`；旧双栈默认禁止交易。
4. **状态机即法律**：15 态 Intent 状态机，非法转移物理抛错；SUBMIT_UNKNOWN 禁止自动重提；转移必带时间/原因/关联 ID。
5. **UNKNOWN ≠ FLAT**：查不到持仓就是 UNKNOWN，禁止新开仓。

## 开源系统吸收映射（consultant 评估已采纳）

| 来源 | 吸收物 | AURORA 落点 | 状态 |
|---|---|---|---|
| NautilusTrader | bracket 语义：任一保护腿独立拒单不假设交易所保证 | orchestrator 保护握手 + 保护失败紧急平仓 | ✅ B1 |
| NautilusTrader | OCO：一腿成交另一腿须主动撤销 | `_reconcile_protected_intents` 按精确 ID 撤兄弟腿 | ✅ 本轮 |
| NautilusTrader | OUO：部分成交后保护量跟随补足 | `sync_protection()` 差额补挂 | ✅ 本轮 |
| Hummingbot | 迟到成交：终态后 Fill 只入审计账，不改对账事实 | ledger fill_id 幂等 + g6e 测试 | ✅ 本轮 |
| Hummingbot | lost order 查不到≠未成交 | 保持 AURORA 更严规则：SUBMIT_UNKNOWN/RECOVERY_REQUIRED | ✅ B1 |
| Hypothesis | 随机事件序列性质测试（I1 幂等/I2 熔断单调/I3 事实收敛/I4 持仓一致/I5 状态合法） | tests/test_kernel_properties.py（本轮挖出 5 个真实缺陷） | ✅ 本轮 |
| Binance 官方 USDS-M SDK | REST/WS/UserData/Testnet/结构化错误 | P0-B3 唯一 BinanceAdapter；⚠️ 默认 base_path 是主网，必须经 safety.py 构造并显式传 Testnet endpoint；届时核实其对 HMAC/RSA 密钥的支持 | ⏳ B3 |
| Toxiproxy | 网络超时/断线/半连接注入 | P0-B3 Testnet 验证 | ⏳ |
| Freqtrade | 独立回测/未来数据检查/手续费后表现 | P1 外部验证器进程（GPL-3.0，禁止复制源码入仓） | ⏳ P1 |
| LEAN | 撮合语义（跳空/部分成交/bar 内触发顺序） | P1 语义参考 | ⏳ |
| Prometheus client | 安全指标（unprotected_position_seconds / unknown_orders_total / kill_switch_state 等） | P0-C 轻量 /metrics | ⏳ |

## 明确不采用

- CCXT 作为执行核心（掩盖 positionSide/reduceOnly/条件单/UDS 细节）
- 整体迁移 NautilusTrader / Hummingbot / Freqtrade（LGPL/GPL 与重量级风险）
- vectorbt（Commons Clause，且无法表达保护握手）
- Redis / Postgres / MQTT（单账户 BTC 内核 SQLite WAL 足够）

## 里程碑

- **P0-B2（余）**：性能与边界——`execution_truth.py` 与 `aurora/kernel/` 二选一裁决（见下）；杀单（cancel）与 CLOSE 幂等联动；Decimal 数量/价格/费用记账（从 execution_truth.py 设计移植）。
- **P0-B3**：Binance 官方 SDK 只读适配器 → TESTNET 连续运行 ≥48h + Toxiproxy 注入。SDK 构造仅经 `aurora/safety.py`，显式 Testnet endpoint，业务代码禁止直接实例化。python-binance 逐步退出。
- **P0-C**：TESTNET 门禁全绿后进入 Shadow（只读对账心跳），旧 Provider 经适配器接入对比，不实盘。
- **P1**：Freqtrade 独立回测验证策略有效性（修复审计发现的伪多周期/突破含当前K线/MR-动量方向归因错误）；Prometheus 指标；前端仅消费事实账本。

## 未决事项（需用户输入）

1. **B1 归属**：已裁定 kernel/ 为基线，execution_truth.py 冻结。其 Decimal
   精度与费用账本移植须先写迁移测试再动代码。
2. **密钥轮换 + 人工对账**（走代理核对持仓/孤儿挂单）完成前，P0-B3 保持
   HOLD（含离线 Adapter 开发）。
3. 并行写入冻结维持。

## 运行

```bash
pip3 install --user -r requirements-dev.txt   # hypothesis（测试用）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q
python3 -m aurora.safety_check                # 配置自检
python3 -m aurora.production_main --boot-only # 安全启动自检（唯一入口）
```
