# AURORA 能力台账（现行）

> 本表是当前唯一能力真源。每条只写已核实状态；UNKNOWN / NOT-RUN
> 不因文档封存变成 PASS。
>
> **运行事实真源是 kernel ledger / kernel recovery state。**
> `state/p0_safety.json` 只是派生/历史投影，不得单独宣称 MATCHED / healthy。
>
> 事故现场：[docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md](../incidents/2026-09-06-testnet-sl-fail/FACTS.md)  
> 处置裁定：[docs/incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md](../incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md)

## 〇、当前正式状态（2026-09-10 · P2-A.2 #observe 验收后）

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
EXECUTION AUTHORIZATION       NOT ISSUED
REAL WRITE PATH               DENIED
NEXT STAGE                    P3-R3.1 RISK ADJUDICATOR（HOLD · READ-ONLY · 不接旧 RiskGate）
P2-PRE DECISION HARNESS       CLOSED · PASS（T1–T10 · 见 P2_PRE_DECISION_BRAIN_HARNESS.md）
AURORA PRODUCT NORTH STAR V2  APPROVED
  P0  NORTH STAR DOC          docs/product/AURORA_NORTH_STAR.md
  P1  OBSERVATORY V2 SPEC     DESIGN-FROZEN
  P2  TRADING STRATEGY V1.1  DESIGN-FROZEN（A1–A8 · T1–T8）
      docs/product/AURORA_TRADING_STRATEGY_CONTRACT_V1.md
  P2-A DUAL-ASSET TREND       CLOSED · READ-ONLY-TRUTH-COMPLETE
      HTF TRUTH                 COMPLETE
      BTC / ETH                 COMPLETE
      RELATIVE STRENGTH         COMPLETE
      FUNDING TRUTH             COMPLETE
      OPEN ELIGIBILITY          COMPLETE
      REALTIME UI MIRROR        COMPLETE
      ALPHA EVIDENCE            NO-EVIDENCE（≠ ENGINE COMPLETE / ≠ 赚钱能力）
      evidence/p2-a2/observe-acceptance-full.png
  P2-A.4 OI CONTEXT           OPTIONAL · NON-BLOCKING（OBSERVE/ANNOTATE/CONTEXT only）
  P2-B ETH/BTC VALUE ENGINE   READ-ONLY-DECISION-COMPLETE
      P2-B.1 VALUE TRUTH        CLOSED · READ-ONLY-TRUTH-COMPLETE
      P2-B.2 ALLOCATION FSM     CONTRACT-PASS · READ-ONLY（B1–B9）
      P2-B.3 OBSERVATORY MIRROR PASS（#observe · evidence/p2-b3/）
      ALPHA EVIDENCE            NO-EVIDENCE
      REALLOCATION EXECUTION    NOT IMPLEMENTED
  P2-C EVENT INTELLIGENCE     GO
      P2-C.0 CONTRACT HARNESS   CONTRACT-PASS（C1–C10 · 见 P2_C0_EVENT_CONTRACT_HARNESS.md）
      P2-C.1 EVENT TRUTH        READ-ONLY-TRUTH-COMPLETE（C1-1–C1-10 · 见 P2_C1_EVENT_TRUTH_FOUNDATION.md）
      P2-C.2 ACTION ELIGIBILITY CONTRACT-PASS · READ-ONLY（C2-1–C2-12 · 见 P2_C2_EVENT_ACTION_ELIGIBILITY.md）
      P2-C.3 OBSERVATORY MIRROR PASS（LEFT 04 + RIGHT · 见 P2_C3_OBSERVATORY_MIRROR.md）
      P2-C PIPELINE             READ-ONLY-SEMANTICS-COMPLETE（≠ live ingestion · ≠ Alpha）
      OFFICIAL SOURCE INGESTION NOT CONNECTED / NOT IMPLEMENTED
  P3-G0 ENTRY GATE AUDIT      PASS（G1–G14 · 见 P3_G0_ENTRY_GATE_AUDIT.md）
  P2-PRE DECISION HARNESS     CLOSED · T1–T10 FROZEN · T9/T10 guards PASS
  P3-R1 DECISION BRAIN CORE   CONTRACT-PASS · READ-ONLY（R1–R13 · 见 P3_R1_DECISION_BRAIN_CORE.md）
  P3-R2 FINAL DECISION MIRROR PASS（R2-1–R2-12 · 见 P3_R2_FINAL_DECISION_MIRROR.md）
  P3 READ-ONLY DECISION LOOP  COMPLETE（≠ P3 COMPLETE · RiskGate 仍 HOLD）
  P3-R3.0 RISK CONTRACT       CONTRACT-PASS（R3-1–R3-16 · 见 P3_R3_RISK_CONTRACT_HARNESS.md）
  RISK SEMANTICS              FROZEN（RISK MONOTONICITY · 只减不增）
  P3-R3.1 RISK ADJUDICATOR    HOLD
  P3-R3.2 RISK OBSERVATORY     HOLD
  P3-R3 RISKGATE ADAPTER      HOLD（旧 risk_gate 非 authority）
  P3-R4 EXECUTION ADAPTER     FORBIDDEN / HOLD
      aurora/decision_brain.py = P3-R1 runtime core（NormalizedInput only）
      aurora/decision_brain_entry_gate.py = G0 GATE + normalizers
      tests/test_decision_brain_r1.py = R1–R13 ACCEPTANCE AUTHORITY
      tests/test_decision_brain_entry_gate_g0.py = G1–G14 ACCEPTANCE AUTHORITY
      tests/test_decision_brain_contract_v1_1.py = T1–T10 ACCEPTANCE AUTHORITY
      portfolio_brain_v2        LEGACY · NOT P3（禁止升级接入）
  P3 → RISK / EXECUTION       HOLD
  P4  BTC NAV / ACCOUNT       HOLD
  P5  E3 OOS                  CLOSED-OFFLINE（≠ LIVE）
OBSERVATORY / TRANSPORT（严格 — 观察 ≠ 策略能力）
  OBSERVATORY-V1 TRANSPORT    CONNECTED（只读 WS · observatory-v1）
  REALTIME FEED               READ ONLY · EXECUTION DENIED
  LIVE TRADING                NO-GO
PRODUCT CAPABILITY（严格 — 策略引擎 ≠ 能显示）
  TREND QUANT ENGINE          READ-ONLY-TRUTH-COMPLETE（P2-A · 非 Alpha 证据）
  BTC TREND                   READ-ONLY-TRUTH-COMPLETE
  ETH TREND                   READ-ONLY-TRUTH-COMPLETE
  FUNDING TRUTH               READ-ONLY-TRUTH-COMPLETE（只读 · OPEN veto · 不改 L0–L5）
  OI TRUTH                    HOLD（P2-A.4 · 非 P2-A 完成门 · 待 E3 独立增量证明）
  ETH/BTC VALUE TRUTH         READ-ONLY-TRUTH-COMPLETE（P2-B.1）
  ETH/BTC ALLOCATION FSM      CONTRACT-PASS · READ-ONLY（P2-B.2）
  ETH/BTC OBSERVATORY MIRROR  PASS（P2-B.3 · LEFT 03 + RIGHT 证据区）
  ETH/BTC ENGINE ALPHA          NO-EVIDENCE · REALLOCATION EXECUTION NOT IMPLEMENTED
  EVENT INTELLIGENCE          P2-C.0 CONTRACT-PASS · READ-ONLY（无 live feed · 无 LLM 权威）
  EVENT TRUTH / SOURCE        READ-ONLY-TRUTH-COMPLETE（P2-C.1 · append-only · as-of replay）
  EVENT IMPACT ASSESSMENT     CONTRACT-PASS · READ-ONLY（P2-C.2 C2-A）
  EVENT PRICED-IN             CONTRACT-PASS · READ-ONLY（P2-C.2 C2-B · PROVISIONAL_E3_PARAM）
  EVENT BOOST ELIGIBILITY     ELIGIBILITY ONLY（P2-C.2 C2-C · ACTIVE UNREACHABLE）
  EVENT OBSERVATORY MIRROR    PASS（P2-C.3 · backend projection · no frontend recompute）
  OFFICIAL EVENT INGESTION    NOT CONNECTED（live feed 默认 · 不得显示「无事件」）
  EVENT EXECUTION             NOT IMPLEMENTED
  EVENT ENGINE ALPHA          NO-EVIDENCE
  DECISION BRAIN SEMANTICS    CONTRACT-FROZEN（T1–T10 · fixture hash pinned）
  P3-G0 ENTRY GATE            PASS（G1–G14）
  P3-R1 DECISION BRAIN CORE   CONTRACT-PASS · READ-ONLY（RUNTIME-IMPLEMENTED）
  P3-R2 FINAL DECISION MIRROR PASS（LEFT 05 + RIGHT · decisionMirror.js）
  P3 READ-ONLY DECISION LOOP  COMPLETE
  P3-R3.0 RISK CONTRACT       CONTRACT-PASS（evaluate_risk · R3-16 monotonicity）
  RISK SEMANTICS              FROZEN
  DECISION BRAIN COMPLETE     NO（R3.1 Adjudicator · R3.2 Observatory · R4 Execution pending）
  DECISION BRAIN LIVE         NOT LIVE · EXECUTION DENIED
  BTC NAV AUTHORITATIVE       NO（P4 HOLD · Brain fail-closed on account UNKNOWN）
  EXCHANGE OBSERVATION        PARTIAL
  BTC NAV                     NOT AUTHORITATIVE / D2 HOLD
  EXECUTION                   DENIED · KILL ACTIVE
DASHBOARD OBSERVATORY
  V1 / COCKPIT V1             SUPERSEDED BY INTERACTION V2
  D0.2 IA SHELL               FIXTURE MODE（synthetic allowed · 可见 FIXTURE）
  D1 REALTIME MODE            #observe · synthetic forbidden
  D1.5 / D1.6 / D2            HOLD
STRATEGY V2 / BACKTEST        V2 / E3 / E4 CLOSED-OFFLINE

INDEPENDENT REVIEW = BLOCKED / REPOSITORY ACCESS（远端 origin 未含
  本分支；载体已改为本地 bundle ZIP：aurora-w43-review.zip，
  sha256 0590e7f4…731353，含全分支历史+复验材料+验证说明，零秘密）
FILL IDENTITY DESIGN = SUBMITTED FOR REVIEW（docs/product/FILL_IDENTITY_
  DESIGN.md：身份作用域四元组 fp/env/symbol/tradeID；经济字段三分类
  事实/推导/记账；统一校验器消除两套比较；16 项测试清单——
  仅设计，未实现；不接 funding、不动权限）
W43 REVIEW FIXES   = R1-R4 LANDED（ace1ad9/3a8ddec/650a429/fd35923）
  独立复验裁定：PASS WITH NONBLOCKING NOTES（752+68 subtests/0 fail）
  更正两处表述：
  a) R4 封闭性测试的执行分支实际先被 EXECUTE_AUTHORIZED=false 硬门
     拒绝（exit 3），会话终态仅是次级防线——非"由会话终态阻断"
  b) 此前"红→绿"为开发方过程记录；独立评审确认的是最终实现与
     回归通过（过程证据保留于各提交，不作为验收口径）
CLEAN-TREE TESTS   = PASS@fd35923（735+4→752+0；此前 FAIL 记录保留
  于 raw_run_*；封闭性
  缺口登记，不以复制 .env/跳过测试消除；主树数字不作独立证据）
W43 OFFLINE ABSORPTION = SELF-VERIFIED / REVIEW-PENDING（复验收紧已并入：
  成交身份冲突告警同ID不同内容 raise；A1 跨真实进程重启 submit=1 已证；
  funding Decimal/原始串/分资产/窗口完整性 PARTIAL_LATE 语义；-1125
  分类限定订单操作域；假件 diff 存证 evidence/w43/）
USER-STREAM RECOVERY   = NOT IMPLEMENTED（A2 仅为 REST 替代性约束）
FUNDING INGESTION      = MODULE IMPLEMENTED / NOT INTEGRATED（E0/D2 待办）
HEDGE DUAL-LEG         = FAIL-CLOSED / NOT FULLY SUPPORTED
TRADING AUTHORITY      = UNCHANGED
HYPOTHESIS             = PINNED 6.141.1（requirements-dev 锁定；
  镜像不可达 6.170.8；不涉及该回归场景；0 skipped ≠ 生成空间充分）
EXTERNAL DIGEST 2026-W43         ABSORBED（测试+状态机约束；零交易依赖变更）
  A1 NT#5375 未知提交重启归属：原 ID 查询/外部归属成交→ORPHAN 熔断
     /绝不铸造新 ENTRY ID（tests/test_external_digest_w43.py）
  A2 NT#5377 凭证失效类错误：-1022/-2015/-1125 永不匹配限流/超时
     分类；持久查询失败跨重启永不假收敛、永不重提交
  A3 NT#5416 HEDGE 双腿：FakeExchange 保真升级——positionSide 分腿
     净额，双腿非零→UNKNOWN（与真实适配器一致，原为净额单腿）；
     对侧腿迟到成交不得错归属；seed_external_position 增加 leg 参数
  A4 FT#13679 funding 漏记：aurora/funding_income.py 幂等入账
     （tranId 稳定 ID；重放忽略；未取到=UNKNOWN≠0；无稳定 ID 拒收）；
     SL 触发路径自动接线登记为 E0/D2 待办，不静默宣称已接
  Hypothesis 6.170.8：镜像源不可达（最高 6.141.1）；现有性质测试
     仅标量策略，不适用该修复场景；全树 0 skipped


E5 FORWARD EVIDENCE             STARTED（首条 2026-10-20 bar 落账：
                                冻结规则裁决 HOLD_BTC / overlay 不合格；
                                append-only 前瞻账 evidence/forward/；
                                观察期自首条起算）
P1-GOV-3 LIVE ENDPOINT          CONTRACT IMPLEMENTED（live-endpoint-v1：
                                构造集/交易集分离；未满授权保持
                                BLOCKED_BEFORE_CLIENT；armed 且合同版本
                                匹配才放行构造期 spot ping；交易期永禁 spot）
KEY ROTATION TOOLING            READY（aurora/ops_key_rotation：只读核验
                                +手动步骤指引，不代改 .env；等待操作员
                                在币安控制台生成新 key——仍 NOT-DONE）

PASS-2 / THIRD SESSION        HOLD / DENIED
E0 ACCOUNTING TRUTH           CLOSED-OFFLINE
  FILLS → PNL → CAPITAL       PASS
  FEES IN NET PNL             PASS
  FUNDING                     AUTHORITATIVE（income_events → equity）
  EQUITY LABEL                fills+fees+funding authoritative; not full economic NAV
  RESTART WATERMARK           PASS（derivative cache；ledger rebuild 为 oracle）
  BAR-PRICE CLOSE PNL         PROHIBITED
E0 ≠ STRATEGY PROFITABILITY   账可信 ≠ 策略赚钱
E1 RISK SEMANTICS             CLOSED-OFFLINE    89248f7
  VOL UNITS                   vol_atr_pct authoritative
  SL/TP AUTHORITY             RiskGate final
  RISK-BUDGET SIZING          risk_budget/stop_distance
  FUNDING RATE VETO           wired
  FUNDING LEDGER              income_events
  FUNDING INCOMPLETE          OPEN denied / CLOSE allowed
E1 ≠ STRATEGY EDGE            风险语义冻结 ≠ 策略盈利证据
ACCOUNTING TRUTH              ESTABLISHED-OFFLINE
RISK SEMANTICS                ESTABLISHED-OFFLINE
STRATEGY EDGE                 OFFLINE-OOS-ONLY
E2 STRATEGY V2                CLOSED-OFFLINE
  NUMERAIRE                   BTC
  CORE                        HOLD BTC
  OVERLAY                     HTF daily LONG only
  1M SIGNALS                  DIAGNOSTIC / NOT AUTHORITY
  NET SHORT                   FORBIDDEN
  STRATEGY IDENTITY           FROZEN
E2 ≠ STRATEGY EDGE            身份冻结 ≠ excess BTC 证据
E3 WALK-FORWARD/OOS           CLOSED-OFFLINE
  BENCHMARK                   BTC HODL = 1.0
  SAMPLE                      local 1d CSV 2022-08-02 → 2026-09-08（已收盘；形成中 bar 剔除）；n_trades=58
  EXCESS BTC                  +0.0338021862（fee/funding/slip 后）
  YEAR FOLDS                  4/5 正超额（2022 负；正折占比 0.80）
  CONCENTRATION               max_month_share=0.186；max_trade_share=0.083
  VERDICT                     EDGE_PASS_OFFLINE
  NO OOS RETUNE               已遵守：看到数字后未回写 E2 / E1 常数
E3 ≠ LIVE                     离线 OOS ≠ AUTO TESTNET ≠ 实盘资格
E4 RUNTIME PARITY             CLOSED-OFFLINE
  HTF SOURCE                  closed_daily_bars（时钟剔形成中 bar，不盲丢末根）
  LOOKBACK                    HORIZON_FETCH_LIMIT=1500
  DIRECTIVE                   与 E3 同一已收盘日线前缀 → 同一 overlay action
  1M                          不能单独武装 overlay
  PAPER CYCLE                 仍禁止
  E3 VERDICT                  未改写（excess_btc +0.0338021862 / 58 trades）
E4 ≠ LIVE                     裁决对等 ≠ AUTO TESTNET ≠ 实盘资格
WRITE FRONT DOOR              EXECUTE_AUTHORIZED ≠ legacy dead-man
CTR-20260908-01               STOP AT P2 / NO EXCHANGE WRITE
EXECUTION AUTHORIZATION       NOT ISSUED
SCOPED PERMIT                 VOIDED（该 session）
REAL WRITE PATH               DENIED
PASS-1                        EXISTS
PASS-1 EVIDENCE               RECONSTRUCTED-COMPLETE
PASS-1 ORIGINAL RAW           PARTIAL（原始 run_output.txt 已丢失；
                              禁止生成新文件冒充原始——只允许追加
                              reconstruction provenance/hash/引用来源）
SESSION CTR-20260908-03       FAIL-SAFE / CLEAN RECOVERY
                              （P5_FINALITY_DELAY；后到证据不改写裁决）
AUTHORIZATION PROVENANCE      CTR-03：TIMELINE MECHANICALLY VALID /
                              GOVERNANCE NON-CONFORMANT（永久标记）
P0-GOVERNANCE-REPAIR          CLOSED          f0efb2b
  GATE-1  EXECUTE_AUTHORIZED=FALSE → deny before writable client
  GATE-2  production_main → cannot bypass incident governance
  GATE-3  incident authority missing/unreadable/invalid → UNKNOWN
          → deny boot → never synthesize CLEAR
OFFLINE REGRESSION            516 PASS
REAL EXCHANGE WRITES          0
EXECUTE_AUTHORIZED            FALSE
INCIDENT KILL / LOCK          ACTIVE
AUTO TESTNET                  DENIED
LIVE                          NO-GO
P1-GOV-3 LIVE ENDPOINT        PLANNED / NOT-STARTED
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
STRATEGY / V2                 CLOSED-OFFLINE / EDGE OFFLINE-OOS-ONLY
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
| 浏览器行为验证 | D0.1 三问原型可本地点选状态；正式 D3 仍 HOLD |
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
| G0-5 运行身份与配置隔离 | **CLOSED-OFFLINE** | 5A–5D 同前。sealed-at-the-time：370 passed（排除当时未提交 probe）。pre-governance-repair：445 passed；post-E0 head：465 passed（2026-09-08 离线全套）。REAL EXCHANGE CALLS = 0。不授权 probe / 清 kill / TESTNET 真跑 |

沿用既有登记的 G1/G4/G5 迁移项（启动余额不刷新、死配置、数量精度、
内存移动止损、波动单位）不因未列入上表而消失。

E0 已 CLOSED-OFFLINE（账从 fills 重建；**不等于策略盈利证据**）。
E1 已 CLOSED-OFFLINE（风险语义冻结；**不等于策略 edge 证据**）。
E2 已 CLOSED-OFFLINE（BTC 本位身份冻结；**不等于 excess BTC 证据**）。
E3 已 CLOSED-OFFLINE（冻结 V2 vs BTC HODL；`EDGE_PASS_OFFLINE` /
`STRATEGY EDGE = OFFLINE-OOS-ONLY`；**仍不等于 AUTO TESTNET / LIVE**）。
E4 已 CLOSED-OFFLINE（生产 overlay 裁决与 E3 对同一已收盘日线一致；
**仍不等于 AUTO TESTNET / LIVE**）。
下一阶段：HOLD。未发令不得开新工作包、不得因 OOS 回写 E2。
