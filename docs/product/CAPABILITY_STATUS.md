# AURORA 能力台账（现行）

> 本表是当前唯一能力真源。每条只写已核实状态；UNKNOWN / NOT-RUN
> 不因文档封存变成 PASS。
>
> **运行事实真源是 kernel ledger / kernel recovery state。**
> `state/p0_safety.json` 只是派生/历史投影，不得单独宣称 MATCHED / healthy。
>
> 事故现场：[docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md](../incidents/2026-09-06-testnet-sl-fail/FACTS.md)

## 〇、当前正式状态（2026-09-08 仓位风险收口后）

```text
G0-4A_COMMIT                  7a10302
G0-4B_COMMIT                  1bb1ecf
HEAD                          cd93850
WORKTREE                      禁止对交易所运行；ops_testnet_probe 保持未提交

G0-1A                         CLOSED
G0-1B                         CLOSED
G0-2                          CLOSED
G0-3                          CLOSED

TESTNET_STATE                 INCIDENT_LOCKED
INCIDENT_POSITION_STATE       RECOVERED
INCIDENT_EVIDENCE_STATE       OPEN_RESIDUAL
EXIT-PROVENANCE-01            OPEN / APPEND-ONLY

POSITION_RISK_RECOVERED       YES
FINAL_POSITION                KNOWN_FLAT
EXIT_MECHANISM                UNKNOWN
MANUAL_CLOSE_FILL             NOT_FOUND
MANUAL_CLOSE_ORDER            NOT_FOUND

G0-4A                         CLOSED-OFFLINE
G0-4B                         CLOSED-OFFLINE
G0-4C                         HOLD
G0-5                          OPEN
KILL                          ACTIVE
INCIDENT_LOCK                 ACTIVE
AUTO_TESTNET                  DENIED
LIVE                          NO-GO
SYSTEM_EXECUTION_QUALIFIED    NO
P0_SAFETY_STATUS              STALE / NOT AUTHORITATIVE
STRATEGY / V2                 HOLD
```

证据残留可以永久 OPEN；事故运行锁须单独 incident disposition 才能解除。当前未批准解除。`CLOSE_PROVENANCE_UNKNOWN` ≠ 永久禁止账户未来任何交易。

## 一、运行与授权

| 项 | 状态 | 证据 |
|---|---|---|
| PAPER 模式 | ACTIVE — 无交易所客户端、无出网 | tests/test_p0_safety.py, test_network_boundary.py |
| SHADOW 模式 | READ-ONLY TESTNET — 只读镜像，生产循环禁止实例化 | p0_boundary, test_production_entry_integrity |
| TESTNET 模式 | INCIDENT_LOCKED — KNOWN_FLAT；EXIT_MECHANISM UNKNOWN；kill ACTIVE | docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md |
| LIVE 代码路径 | EXISTS（未被本批删除或改写） | production_main, safety.build_client |
| LIVE 授权条件 | 既有条件未修改：双重授权 + AURORA_ARM_LIVE | p0_boundary.assert_live_dual_auth / assert_not_live_trading |
| 当前 SDK+端点策略下的 armed-LIVE | BLOCKED_BEFORE_CLIENT — 构造期 spot ping 目标 api.binance.com 不在 ALLOWED_LIVE_HOSTS，授权齐全也构造前拒绝 | C2.1（04b2c0e），tests/test_network_boundary.py |
| 产品 LIVE 放行 | NOT-GRANTED | 本台账 |

**拒绝在 UNKNOWN 下开仓 ≠ 能够完成启动对账。**前者证明不继续增加
风险，后者证明能发现未知风险；两者不能互相替代。

## 二、执行内核与参考实现

| 项 | 状态 |
|---|---|
| aurora/kernel/ | 唯一生产执行内核（ADR-013） |
| aurora/execution_truth.py | TRACKED / OFFLINE_REFERENCE_ONLY；Decimal 记账与执行不变量保留参考价值；**不是**生产引擎、不得被生产导入、不证明生产正确性 |
| reference reconcile()/boot() | NOT-BUILT（本轮检查的当前仓库、可达 Git 历史及所检查的 quarantine 范围内，未找到可复用实现） |
| 生产导入隔离 | PASS — 静态扫描 + 干净子进程 sys.modules 检查 |
| 生产账本 Decimal 迁移 | NOT-DONE（仍 float/REAL；后续工作包） |

## 三、观察面

| 项 | 状态 |
|---|---|
| aurora/dashboard_feed.py | EXCHANGE_OBSERVATION / NOT_LEDGER_PROJECTION；只读白名单、分段时间戳、失败不伪装、回环 + Origin 白名单 |
| 浏览器行为验证 | NOT-RUN（vite build 通过 ≠ 浏览器呈现正确；BUILD_CONFIG_ISOLATION = NOT-EVIDENCED） |
| 保护单核验 | NOT_VERIFIED（本观察面不查条件单；G0-4 未完成前不得宣称已保护） |

## 四、G0 工作包（以提交与事故核对为准）

| 工作包 | 状态 | 说明 |
|---|---|---|
| G0-1A 启动与持仓真相 | **CLOSED**（`5cc1360`） | BOOT-DRIFT：有仓无账不认领 |
| G0-1B SL/TP 三态 | **CLOSED**（`2264755`） | 大脑层消灭 0.0 误平；不证明交易所保护 |
| G0-2 确认计数 | **CLOSED**（`ffbb17f`） | 唯一已收盘 bar |
| G0-3 UNKNOWN | **CLOSED**（`e4af236`） | 性质测试钉死；不重造状态机 |
| G0-4A Algo/HEDGE 协议 | **CLOSED-OFFLINE** | fake transport。ObservedPositionMode 注入、HEDGE 减仓 `side+positionSide+qty`、`-1106` 不改参重试、Algo 终态≠fill、KNOWN_FLAT+CLOSE_PROVENANCE_UNKNOWN。REAL ORDER/ALGO/MODE MUTATION/KILL CLEAR = 0 |
| G0-4B 执行事实真源 | **CLOSED-OFFLINE**（`1bb1ecf`） | B1 保护数量 = fills 权威聚合→仓位事实，ACK executedQty 仅为早期观察；订单投影单调收敛于 fills；`0 < protection_qty ≤ confirmed_position_qty`；保护计划价持久化于 intents（PRAGMA+ALTER 增量迁移，不改历史行）。B2 紧急平仓四态（ATTEMPTED/REJECTED/UNKNOWN/CONFIRMED），kill 理由禁"executed"假成功，仅权威事实可 CONFIRMED。B3 缺/非法 SL 价 → OPEN DENIED；99/101 哨兵废除；TP 可明确 NOT_CONFIGURED。回归：tests/test_g04b_contracts.py + tests/test_g04b_offline_probe.py（socket 绊网零出网）。交易所侧行为未验证（事故锁不变） |
| G0-4C 保护生命周期恢复 | **HOLD** | HEAD 上有后续提交 `cd93850`，本对齐不把它登记为 CLOSED。需单独封点后才能改状态。 |
| G0-5 配置来源 | **OPEN**（执行资格前置） | `production_main` 裸 `load_dotenv()` 必须与 safety_check / dashboard_feed 共用显式 ConfigSource；含 SafeExecutor 退休裁定（M2）：其交易方法在生产入口不可达（production_main 仅调 `executor.reconcile("timer")`，且仅 SHADOW 分支；SHADOW broker 拒写），TP 失败即平仓的旧合同与内核冲突暂为休眠，须在 G0-5 隔离或退休 |

沿用既有登记的 G1/G4/G5 迁移项（启动余额不刷新、死配置、数量精度、
内存移动止损、波动单位）不因未列入上表而消失。
