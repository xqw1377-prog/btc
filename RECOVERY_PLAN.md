# AURORA 恢复路线图（事故后重建）

> 本文件是当前唯一权威路线图。README.md / STRATEGY.md / DEPLOYMENT.md 为事故前历史文档，不再代表现状。

## 状态（2026-09-02）

```text
分支:   safety/p0a-mainnet-isolation
P0-A   = PASS  (b037e8e  fail-closed 主网隔离, 44 tests)
P0-B1  = PASS  (cda0f83  durable execution truth, 47 tests)
P0-B2  = 部分完成（离线语义加固: OCO/OUO/迟到成交 + Hypothesis 性质测试）
BINANCE ADAPTER = NOT-CONNECTED
TESTNET = NOT-RUN
LIVE    = NO-GO（无论配置；production_main 拒绝实盘循环）
```

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

1. **B1 归属裁决**：`aurora/kernel/`（已提交，106 项测试全绿）vs `aurora/execution_truth.py`（未提交，其评审套件 3 项失败：并发审批互斥失效/订单状态可回滚/仓位重建错误）。建议 kernel/ 为基线，仅移植其 Decimal 与费用设计。
2. **密钥轮换 + 人工对账**（走代理核对持仓/孤儿挂单）完成前，P0-B3 不启动。
3. **并行写入冻结**：多会话同时写本仓库已两次产生同任务双实现，裁决前请暂停其他写入者。

## 运行

```bash
pip3 install --user -r requirements-dev.txt   # hypothesis（测试用）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q
python3 -m aurora.safety_check                # 配置自检
python3 -m aurora.production_main --boot-only # 安全启动自检（唯一入口）
```
