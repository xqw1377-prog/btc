# E0 — EXECUTION ACCOUNTING TRUTH（完成与修复计划）

## Context

E0 发令已授权：把「真实成交事实 → 真实盈亏 → 风险状态 → 资本曲线」收成一条以 execution ledger 为权威源的链。当前 HEAD `fc3e521`（"E0: close accounting truth on authoritative execution fills"，465 测试绿）已迈出第一步（CLOSE 路径不再记 bar-price PnL、fees 入净 PnL、brain 资本改由 ledger 重放），但经审计**不满足冻结的 8 条验收标准**，且存在一个数据级 bug：

- **[数据 bug]** 手动/受控平仓的 `fills.realized_pnl` 恒为 0：[orchestrator.py:434](file:///Users/xinquanwang/AURORA/aurora/kernel/orchestrator.py#L434) 每次平仓新建独立 intent `AURORA-CLOSE-{uuid}`，而 `_realized_pnl()`（L1586-1595）只查 `{order['intent_id']}-ENTRY` → 查不到 → entry_avg=0 → realized=0。真实 CTR-03 账本实证：ENTRY 0.001@78368.6 / CLOSE 0.001@78351.0，真值 −0.0176 列为 0.0。SL/TP 保护腿挂在原 entry intent 下，不受影响。
- `accounting_truth.py` 的 `_net_fill()`（L61）**信任该列** → 手动平仓的亏损对 equity/risk 仍然隐身（验收 1、2 未达成）。
- funding 完全未实现（`funding_paid` 字段不存在恒为 0）→ 验收 4 未达成。
- `_sync_accounting(full_replay=cached is None)`：重启带缓存 → 增量重放到全新内存 kernel → daily/weekly/连亏清零 → **验收 5 未达成**。
- baseline = 每次启动的 `availableBalance`，不持久化 → 重启 equity 跳变。
- 无日历窗口（验收 6）、无 reconciliation（验收 8）、`_parse_ts` 解析不了 Binance epoch-ms 串（→ timestamp=None → min_trade_interval 仍是死代码）。
- **[ops 隐患]** `state/testnet/3fbc5d4f1f9ddc7d/kernel_ledger.db` 为 0 字节空文件（9/8 21:39 产生）。下次 attach 时 `ensure_ledger_migrated` 见 target 存在即跳过迁移 → **事故 kill（ACTIVE）无法从遗留账本接管**。

## 冻结的会计政策

1. **记账单位 = round-trip（回合）**：持仓 0→非0→0 为一个回合，可跨多个 order/intent（部分 SL + 手动补平 = 1 回合）。win/loss、consecutive_losses、returns_history 全以回合净 PnL 计。
2. **回合净 PnL = Σ回合内 exit fills 重算的 realized − Σ回合内 entry+exit fills 的 fees**。realized 由重放计算（direction × (exit_price − 加权 avg_entry) × qty），**不信任 `fills.realized_pnl` 列**（该列降级为被校验投影）。
3. **资金费 = 账户级 fact**（income_events 表，有符号金额），不摊入回合，只进 equity 与日/周窗口。
4. **equity = baseline + Σrealized_gross − Σfees + Σfunding**（纯已实现口径；未实现浮盈亏不标记，属 E1+，文档声明局限）。
5. **日/周窗口 = 窗口内 equity 时间线增量**（日 = UTC 日历日，周 = ISO 周一 00:00 UTC；与 Binance 资金费结算时区一致）。比"窗口内平仓 PnL 之和"更正确：entry fee 与 funding 的时间归属自然准确，且与验收 8 的 capital-delta 同口径。
6. **重放永远全量**（fills 为 O(百级)，成本可忽略）；watermark/JSON 快照降级为诊断缓存，绝不承载状态。
7. **funding 拉取失败 → `funding_incomplete=True` → 仅阻止新开仓**（OPEN 分支 HOLD），不 engage kill（会计不完整 ≠ 持仓危险，不能因此挡平仓/恢复）。
8. **baseline**：ledger 单行不可变表；首启取 `walletBalance` 快照（非 availableBalance）；已有 fills 的账本一次性回推 `wallet − net_so_far`；均不可得回退构造参数。共享 testnet 失真写进模块 docstring（他方资金流使 baseline 偏大；wallet-delta 对账在共享账户只作 warning）。
9. **冻结 CTR 账本只读**：不回填、不改写。回填工具做成 opt-in（供将来接管有历史的账本用）；对 CTR-02/03 只生成 reconciliation 差异报告作为 bug 证据。

## 实施步骤（commit 划分）

### C1 — ledger 事实表
**文件**：[ledger.py](file:///Users/xinquanwang/AURORA/aurora/kernel/ledger.py)
- schema 追加（`CREATE TABLE IF NOT EXISTS`，安全迁移）：`capital_baseline`（单行 `id=1 CHECK`：symbol/amount/asset/source/note/recorded_at）+ `income_events`（`income_id TEXT PK`=`{tranId}:{time}:{symbol}`/symbol/income_type/amount 有符号/asset/`time_ms INTEGER`+索引/recorded_at）
- 幂等方法：`set_baseline`（INSERT OR IGNORE，写后不可变）、`get_baseline`、`insert_income_event`、`max_income_time_ms`（cursor 真源）、`list_income_events`
**测试**：test_kernel_ledger.py 追加——建表幂等、baseline 二次写不覆盖、income 幂等、cursor 查询。

### C2 — 重写 accounting_truth 核心（持仓感知重放）
**文件**：[accounting_truth.py](file:///Users/xinquanwang/AURORA/aurora/accounting_truth.py)（保留模块名与 wiring 形状，核心重写）
- `ClosedTrade`（entry_intent_id/closing_fill_id/direction/qty/entry_avg/exit_avg/realized_gross/fees/net_pnl/opened_at_ms/closed_at_ms）
- `CapitalFacts` 扩展快照：baseline(+source)/equity/realized_gross/fees_total/funding_net/**daily_pnl/weekly_pnl(+窗口标签)**/**consecutive_losses**/high_water/drawdown/returns_history（回合净pnl÷回合前equity）/equity_curve/pnl_history/closed_trades/**last_exit_epoch**/trades_today/trades_week/**accounting_gap**/**funding_incomplete**
- 重放算法：输入 `list_economic_fills_with_context()` + `list_income_events()`；`_parse_ts` 统一处理 ISO / epoch-ms / 纯数字串，排序键 `(parsed_ts, fill_id)`；维护 signed_qty/加权 avg_entry/当前回合 fees 与 exit fills；qty 归零 → ClosedTrade；孤 exit / 超射 / flat 但重放残差非零 → `accounting_gap=True`（equity 仍按记录效果累加）
- `ensure_baseline(wallet_balance=None, fallback_amount=None)`：C5 政策 8 的三档来源
- `reconcile(ledger)`：Σ列值 realized vs Σ重放值 vs per-intent 重构，输出差异行清单（验收 8）
- 删除 `sync_brain_from_snapshot` 的增量 replay 语义
**测试**：test_accounting_truth.py 改写——空账本；单回合净 PnL 含费；多腿退出=1 回合；funding 汇总；UTC 日/周窗口（注入 now_ms 跨午夜边界）；孤 exit → accounting_gap；epoch-ms/ISO 双格式；hypothesis property：任意 fill/income 序列 → equity == baseline+Σrealized−Σfees+Σfunding。

### C3 — 交易所适配器（funding/wallet）
**文件**：[port.py](file:///Users/xinquanwang/AURORA/aurora/kernel/port.py)、[binance_exchange.py](file:///Users/xinquanwang/AURORA/aurora/kernel/binance_exchange.py)、[fake_exchange.py](file:///Users/xinquanwang/AURORA/aurora/kernel/fake_exchange.py)
- port 新增 `IncomeEvent` dataclass + 两个**非抽象**具体方法（默认 raise 不破坏实现者）：`funding_income(symbol, start_time_ms) -> List[IncomeEvent]`、`wallet_balance(asset) -> Optional[float]`
- BinanceExchange：`funding_income` 用 `futures_income_history(incomeType="FUNDING_FEE", startTime=..., limit=1000)` 分页拉至空页（python-binance 1.0.19 已确认有该方法）；`wallet_balance` 用 `futures_account` 的 assets.walletBalance
- FakeExchange：`emit_funding(symbol, amount, time_ms=None)` 旋钮 + 两方法（wallet 可配置默认 None → fallback）
**测试**：test_binance_exchange.py 追加 mock 分页（2 页+空页终止+有符号映射）；fake 旋钮测试。

### C4 — 修复 close-intent realized_pnl 链接
**文件**：[orchestrator.py](file:///Users/xinquanwang/AURORA/aurora/kernel/orchestrator.py)
- `_realized_pnl`：`{intent_id}-ENTRY` 查不到时 fallback 查"当前持仓归属 intent"的 ENTRY order（intents 处于非终态且 ENTRY 有成交；单仓系统应唯一，不唯一即 raise fail-closed）→ 此后新写入的 close fill 列值正确，与重放口径一致
- opt-in 回填工具 `backfill_realized_pnl(ledger)`（重放值 UPDATE 不一致历史行 + transitions 审计行 `entity_type="fills_backfill"`）；**不对冻结 CTR 账本执行**
**测试**：open@100 → `close_position()` → close fill realized = (exit−entry)×qty ≠ 0（把本次 bug 固化为回归）；fallback 多候选 raise；backfill 对 CTR-03 同构 fixture 产出 −0.0176 并写审计行。

### C5 — risk kernel / objective 吃 facts
**文件**：[risk_kernel.py](file:///Users/xinquanwang/AURORA/aurora/risk_kernel.py)、[risk_gate.py](file:///Users/xinquanwang/AURORA/aurora/risk_gate.py)、[capital_objective.py](file:////Users/xinquanwang/AURORA/aurora/capital_objective.py)
- `InstitutionalRiskKernel.apply_facts(facts)`：覆盖 total/peak/daily/weekly/consecutive_losses/returns_history/pnl_history/equity_curve/last_trade_ts/trade_count_*；随后 `_check_all_breakers(0.0)` 从 facts 重 derive 熔断（重启即恢复 kill，验收 5 本意；reset_kill 保持人工）
- `RiskGate.apply_facts` 委托；`capital_objective.sync_from_facts(facts)` 整体覆盖内部序列；`record_trade/record/update_capital` 保留仅供旧单测，生产路径不再调用
**测试**：apply_facts 全字段覆盖；facts.consecutive ≥ max → kill 激活（重启语义）；sync_from_facts 后 multiplier/should_trade 正确。

### C6 — trading_cycle 单一会计路径接线
**文件**：[trading_cycle.py](file:///Users/xinquanwang/AURORA/aurora/trading_cycle.py)、[portfolio_brain_v2.py](file:///Users/xinquanwang/AURORA/aurora/portfolio_brain_v2.py)
- step 新序：`recover → kill check → ensure_baseline（幂等）→ funding 拉取（cursor=max_income_time_ms；失败→funding_incomplete=True 告警）→ facts=refresh(now) → brain.risk_gate.apply_facts + brain.capital_objective.sync_from_facts + brain.capital=equity → sync_brain_from_exchange（flat 时用 ClosedTrade.exit_avg 做 bookkeeping 历史，无 exit fill 则 close_without_pnl）→ decide → execute`
- `_sync_accounting` 重写为**永远全量重放**（watermark 删除/降级为诊断）；`initial_capital` 改由 `ensure_baseline` 提供
- execute()：OPEN 分支在 enable 检查同层加 `funding_incomplete / accounting_gap → HOLD`（不拦 CLOSE）；CLOSE 成功后立即 refresh+apply（`_submit_close` L761 已同步 `_apply_fills`，时序已验证）
- 保留 fc3e521 的 `close_position_from_accounting`/`close_without_pnl` 形状
**测试（冻结验收回归，新建 tests/test_e0_incident_regression.py）**：
- (a) **必做事故回归**：FakeExchange+Orchestrator open 0.01@100 → `fire_protection(SL, price=95)` → recover → refresh → apply：断言回合净 PnL = −0.050975 < 0、consecutive_losses == 1、drawdown > 0、daily_pnl < 0、equity 精确
- (b) 手动 `close_position` 同路径同断言（Δcapital == −(entry_fee+exit_fee)，与 bar 价格无关）
- (c) **重启等价**：新 accountant+新 kernel 从同一 ledger 重建 == 原进程状态（daily/weekly/consecutive/high_water 不清零）
- (d) reconciliation：Σ列值（C4 修复后）== Σ重放 == capital delta（差异仅列明 fee/funding timing）
- (e) funding 拉取失败 → OPEN HOLD、CLOSE 放行
- 全量 465+ 回归绿

### C7 — 证据 commit（与实现分离）
- `docs/product/E0_ACCOUNTING_TRUTH.md` 更新为完成态（会计政策、UTC 窗口定义、共享 testnet baseline 失真声明、未实现口径局限、reset_kill 人工 runbook）
- `evidence/e0/`：全量测试输出；对 CTR-02/03 冻结账本的**只读**重放 reconciliation 差异报告（证明列值 bug 与新口径重构值）；生产命名空间 baseline 首启快照流程记录
- **ops 处置**：删除 0 字节 `state/testnet/3fbc5d4f1f9ddc7d/kernel_ledger.db`，使下次 attach 时 `ensure_ledger_migrated` 从遗留账本只读接管（保留事故 kill ACTIVE）；处置记录入证据

**顺序**：C1 → C2 → (C3, C4, C5 可并行) → C6 → C7。C6 前必须落 C4（否则回归 (a)(b)(d) 不可能全绿）。

## 验证

1. 每 commit 全量测试：`cd /Users/xinquanwang/AURORA && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q --tb=no`
2. C6 后跑冻结回归套件 + hypothesis property
3. 只读启动验证（不发单、零写出）：`python3 -m aurora.production_main --boot-only`（TESTNET 配置）
4. 禁令自查：不触碰 signal_providers/策略参数/阈值；不动 LIVE 门禁与 `assert_production_execution_governance`；不恢复 AUTO TESTNET；任何真实 testnet 复跑须走 ops scoped permit（不在 E0 范围）

## 明确不做（E0 边界）

volatility 单位、funding_rate/spread 风控参数接线（assess 的死代码参数）、Risk Gate 仓位最终裁定权、交易所过滤器量化、timeframe 语义 —— 全部 E1。Strategy V2 / 回测 / LIVE —— HOLD。
