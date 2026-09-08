# AURORA 能力台账（现行）

> 本表是当前唯一能力真源。每条只写已核实状态；UNKNOWN / NOT-RUN
> 不因文档封存变成 PASS。
>
> **运行事实真源是 kernel ledger / kernel recovery state。**
> `state/p0_safety.json` 只是派生/历史投影，不得单独宣称 MATCHED / healthy。
>
> 事故现场：[docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md](../incidents/2026-09-06-testnet-sl-fail/FACTS.md)  
> 处置裁定：[docs/incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md](../incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md)

## 〇、当前正式状态（2026-09-08 仓位风险收口后）

```text
G0-4A_COMMIT                  7a10302
G0-4B_COMMIT                  1bb1ecf
G0-4C_COMMIT                  5bfa311
G0-5_COMMIT                   d0863ee
WORKTREE                      禁止对交易所写入
                              sealed-at-the-time：ops_testnet_probe 未提交
                              current head：ops_testnet_probe 已入库存档（G0-4D-R1）

G0-1A                         CLOSED
G0-1B                         CLOSED
G0-2                          CLOSED
G0-3                          CLOSED

TESTNET_STATE                 INCIDENT_LOCKED
INCIDENT_POSITION_STATE       RECOVERED
INCIDENT_EVIDENCE_STATE       OPEN_RESIDUAL
EXIT-PROVENANCE-01            OPEN / APPEND-ONLY
HISTORICAL_EVIDENCE_GAP       ACCEPTED
INCIDENT_REQUALIFICATION_ELIGIBLE  YES

POSITION_RISK_RECOVERED       YES
FINAL_POSITION                KNOWN_FLAT
EXIT_MECHANISM                UNKNOWN
MANUAL_CLOSE_FILL             NOT_FOUND
MANUAL_CLOSE_ORDER            NOT_FOUND

G0-4A                         CLOSED-OFFLINE
G0-4B                         CLOSED-OFFLINE
G0-4C                         CLOSED-OFFLINE
G0-4D EXECUTION               COMPLETE
G0-4D EVIDENCE                SEALED
G0-4D QUALIFICATION GATE      UNBLOCKED（EXECUTE 仍 DENIED）

PRE-EXECUTION CONFORMANCE     PASS   eb0536b
QTY EXACTNESS                 PASS
CLIENT ID CONTRACT            PASS
SESSION LEDGER ISOLATION      PASS
TRUE RESTART RECOVERY         PASS
QUALIFICATION CLOSE           PASS
REAL WRITE AUTHORITY          NOT ISSUED
REAL TESTNET WRITE            DENIED
G0-5                          CLOSED-OFFLINE

CONTROLLED TESTNET IMPLEMENTATION   CLOSED-OFFLINE
CONTROLLED HARNESS            READY
PERMIT TOOLING                READY（签发仅随开工窗口）
P0-P5 LIFECYCLE               IMPLEMENTED
WIRE ACK EVIDENCE             IMPLEMENTED
ACTIVE_CONFIRMED CONTRACT     IMPLEMENTED
MARK_PRICE NOTIONAL GATE      IMPLEMENTED
IDENTITY GATE                 IMPLEMENTED
EXECUTION AUTHORIZATION       RUNTIME-SCOPED / NOT ISSUED
EXECUTION START ORDER         NOT ISSUED
SCOPED PERMIT                 NOT ISSUED
REAL TESTNET WRITE            DENIED
KILL                          ACTIVE
INCIDENT_LOCK                 ACTIVE
AUTO_TESTNET                  DENIED
OFFLINE CONTRACTS             PROVEN
READ-ONLY TESTNET             SEALED
CONTROLLED REQUAL HARNESS     IMPLEMENTED
PRE_EXECUTION_CONFORMANCE     ALIGNED     eb0536b / 6ed46be
EXECUTION BOUNDARY            FROZEN      6b2cc7c
EXECUTE_AUTHORIZED            FALSE
                              仍是写盘前门 ≠ legacy dead-man
CTR-20260908-01               STOP AT P2 / NO EXCHANGE WRITE
EXECUTION AUTHORIZATION       NOT ISSUED
SCOPED PERMIT                 VOIDED（该 session）
REAL WRITE PATH               DENIED
CONTROLLED REQUAL LIFECYCLE   PASS-1（真实 TESTNET，见 evidence/ctr/）
EXECUTION AUTHORIZATION       CONSUMED（CTR-20260908-02，one-lifecycle）
NEXT SESSION                  需新开工令；AUTO TESTNET 仍 DENIED
WRITE GATES                   EXECUTE_AUTHORIZED
                              + scoped permit（session/single_use/exact 0.001/未过期）
                              + Execution Start Order
                              构造写客户端之前同时满足；当前一项都未放行
EXECUTION_WP                  BOUNDARY-FROZEN / NOT AUTHORIZED TO EXECUTE
                              SEALED 6b2cc7c
                              PERMIT NOT ISSUED
LIVE                          NO-GO
SYSTEM_EXECUTION_QUALIFIED    NO
P0_SAFETY_STATUS              STALE / NOT AUTHORITATIVE
STRATEGY / V2                 HOLD
```

证据残留可以永久 OPEN。G0-4D 只读复核：认证 PASS、普通读取 PASS、恢复证据 PARTIAL（EXIT-PROVENANCE-01 再确认 NOT_FOUND）；Algo 单查 schema 不匹配（真实字段 orderType）已经 **G0-4D-R1（95ece99）离线修复**：_algo_fact 双别名规范化（冲突 fail-closed）、list/single 分开合同、真实 fixture 回归；R1 后复测列表 PASS + 真实单查解析 PASS + workingType/身份守卫按合同工作 → 读协议升 PASS。修正附录 G0-4D-AMENDMENT.md。`CONTROLLED TESTNET REQUALIFICATION` 仅冻结写入边界，**EXECUTE DENIED**（且在 G0-4D 阻塞修复前不得解封）。`INCIDENT_LOCK` / 事故 kill / AUTO TESTNET / SYSTEM EXECUTION 均未解除。

## 一、运行与授权

| 项 | 状态 | 证据 |
|---|---|---|
| PAPER 模式 | ACTIVE — 无交易所客户端、无出网 | tests/test_p0_safety.py, test_network_boundary.py |
| SHADOW 模式 | READ-ONLY TESTNET — 只读镜像，生产循环禁止实例化 | p0_boundary, test_production_entry_integrity |
| TESTNET 模式 | INCIDENT_LOCKED — KNOWN_FLAT；EXIT_MECHANISM UNKNOWN；kill ACTIVE；G0-4D **CLOSED-READONLY / R1 PASS**（恢复证据仍 PARTIAL） | FACTS.md + G0-4D.md + G0-4D-AMENDMENT.md。sealed-at-the-time 曾写 HOLD（Algo schema 阻塞），现已过时 |
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
| G0-4C 保护生命周期恢复 | **CLOSED-OFFLINE** | `FILLED_UNPROTECTED` / `PROTECTION_SUBMITTING` / `PARTIALLY_FILLED` 重启进入生命周期恢复；`SUBMIT_UNKNOWN` 不重提；部分覆盖不得 VERIFIED；超额覆盖撤旧按实际仓位重建；repair 窗口仓位变化按现场数量；无平仓成交的 FLAT → `CLOSE_PROVENANCE_UNKNOWN`，禁止合成 SELL / 假 RECONCILED；FLAT+ACTIVE 保护 → `ORPHAN_PROTECTION`。回归：tests/test_g04c_contracts.py。交易所生命周期仍归 G0-4D |
| Incident Disposition | **SEALED** | 历史证据缺口 ACCEPTED；`INCIDENT_REQUALIFICATION_ELIGIBLE=YES` 仅批准进入 G0-4D 只读复核。lock / kill / AUTO TESTNET / SYSTEM EXECUTION 未解除。真源：DISPOSITION.md |
| G0-4D 只读 TESTNET 资格复核 | **CLOSED-READONLY** | 认证 PASS；读协议 PASS；恢复证据 PARTIAL（无 SELL，缺口再确认）。fail-closed 未触发。回归：tests/test_g04d_readonly.py。现场：g04d_readonly.json。SYSTEM EXECUTION 仍 NO |
| Controlled TESTNET Requal | **IMPLEMENTED / EXECUTE DENIED** | 边界已冻；`ops_controlled_requal` 默认只出 PLAN；execute 旗标在构造写客户端前硬拒。真源：CONTROLLED_TESTNET_REQUAL.md |
| Pre-Execution Conformance | **ALIGNED TO 6b2cc7c / NOT AUTHORIZED TO EXECUTE** | qty exactly 0.001；分腿 `AURORA-CTR-<session>-ENTRY/SL/CLOSE`；`qualification/<session-id>/ledger.db`；新实例 restart recovery；harness 层 QUALIFICATION CLOSE；写门在构造客户端前双检。回归：tests/test_controlled_requal.py。真源：PRE_EXECUTION_CONFORMANCE.md |
| Execution Work Package | **BOUNDARY-FROZEN / NOT AUTHORIZED TO EXECUTE** | 正式封点 `6b2cc7c`。不得用 HEAD 反向改解释。写盘必须 `EXECUTE_AUTHORIZED` **且** scoped single-use permit。PASS-1 ≠ AUTO TESTNET ≠ SYSTEM EXECUTION。permit 未签发 |
| G0-5 运行身份与配置隔离 | **CLOSED-OFFLINE** | 5A–5D 同前。sealed-at-the-time：370 passed（排除当时未提交 probe）。current head：441 passed（2026-09-08 离线全套）。REAL EXCHANGE CALLS = 0。不授权 probe / 清 kill / TESTNET 真跑 |

沿用既有登记的 G1/G4/G5 迁移项（启动余额不刷新、死配置、数量精度、
内存移动止损、波动单位）不因未列入上表而消失。
