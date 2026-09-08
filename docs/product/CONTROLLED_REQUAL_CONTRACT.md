# CONTROLLED TESTNET REQUALIFICATION — WRITES BOUNDARY CONTRACT

> 状态：**CONTRACT FROZEN / EXECUTION NOT AUTHORIZED**  
> 冻结日：2026-09-08  
> 前置事实：G0-4D EXECUTION COMPLETE / EVIDENCE SEALED（a1a284c +
> R1 95ece99 + d452b62）；AUTH PASS；READ PROTOCOL PASS；
> RECOVERY EVIDENCE PARTIAL；DISPOSITION SEALED（c612c8d）  
> 本合同是**可执行设计**，不是执行授权。执行需另行发出开工令。

## 〇、总状态冻结（与本合同一致）

```text
G0-4A/B/C      CLOSED-OFFLINE
G0-5           CLOSED-OFFLINE
INCIDENT       DISPOSITION SEALED
G0-4D          EXECUTION COMPLETE / EVIDENCE SEALED
AUTH           PASS      READ PROTOCOL PASS      RECOVERY EVIDENCE PARTIAL
G0-4D GATE     UNBLOCKED
CONTROLLED EXECUTE   DENIED
KILL           ACTIVE    INCIDENT_LOCK ACTIVE    AUTO TESTNET DENIED
SYSTEM EXECUTION     NOT QUALIFIED               LIVE   NO-GO
```

## 一、资格许可（Qualification Permit）——kill 处理设计

**不采用"先清 kill 再测试"。** 采用一次性、范围受限的许可模型：

```text
INCIDENT KILL          保持 ACTIVE（历史事实，永不因测试而清除）
QUALIFICATION PERMIT   一次性对象，字段冻结：
                       scope   = TESTNET
                       symbol  = BTCUSDT
                       side    = LONG
                       lifecycle = 1（一个 intent：entry→protect→
                                 restart-recover→flatten）
                       max_qty = 0.001
                       max_notional_usdt = 120（按只读观察价计）
                       client_id_ns = AURORA-CTR-*
                       session_ledger = state/testnet/3fbc5d4f1f9ddc7d/
                                        controlled_requal.db
                       issued_at / issued_by / expires_at
PERMIT 语义            在 permit 范围内，会话执行器被允许行动；
                       permit 之外的一切仍被事故 kill 拒绝
KILL CLEARED           = 资格验证 PASS 之后的【结果】，由单独裁定授予，
                       不是本包的前置条件或副作用
```

实现要求：permit 持久化为显式文件（state/testnet/<fp>/
qualification_permit.json），由执行器在每阶段开始前校验
（scope/lifecycle/expiry），任何越界即 STOP。

## 二、写入边界（冻结）

```text
SYMBOL                 BTCUSDT only
SIDE                   LONG only（显式 positionSide=LONG）
POSITION MODE          HEDGE（只读核对，不得改账户）
ACCOUNT                3fbc5d4f1f9ddc7d（指纹不符 → IDENTITY_DRIFT 拒绝）
ACCOUNT_EXCLUSIVITY    FALSE：只把 AURORA-CTR-* 的 BTCUSDT 事实解释为
                       AURORA 事实；V5S_* 与账户级状态只观察
FOREIGN ALGO (V5S_*)   DO NOT TOUCH
ENTRY POINT            专用受控命令；禁止 production_main / TradingCycle
MAX_QTY                0.001（且须满足交易所 MIN_NOTIONAL/stepSize）
MAX_NOTIONAL_USDT      120，按【只读观察的权威标记价】计算；
                       操作员手填价格不作为上限依据
INTENTS                1
CLIENT ID              AURORA-CTR-<random>；禁止复用
                       AURORA-0650a39f56e3 或任何非本前缀 id
TP                     NOT_CONFIGURED 允许（TP 可缺省合同不变）
```

## 三、生命周期（六阶段，任一阶段失败即进入收口）

```text
P0  PRE-FLIGHT（只读）
    复用 G0-4D 读取路径：position mode=HEDGE、BTCUSDT FLAT、
    ordinary BTCUSDT 挂单=0、AURORA BTCUSDT Algo=0、身份一致性、
    权威标记价观察。任一不满足 → 拒开。
P1  WIRE ACK VERIFICATION（R1 遗留未知的第一现场）
    首次真实 ENTRY submit 的原始 wire 响应必须落证据
    （evidence/ctr/ack/），并完成三方核对：
      submitted intent ↔ actual wire response ↔ normalized AlgoOrderFact
    关注：SEND 参数名 type 是否被接受；ACK 订单类型字段真实名称
    （type/orderType）；status/字段集合与 GET 侧合同差异。
    核对失败 → STOP；结果记为 SUBMIT_ACK_CONTRACT = OBSERVED/PARTIAL。
P2  ENTRY
    submit once → authoritative fill required（fills 聚合为唯一
    数量真源；ACK executedQty 只是早期观察——G0-4B 合同不变）。
P3  PROTECTION
    SL mandatory：提交后必须按 clientAlgoId 查询回验——
      status=NEW/ACTIVE、workingType==MARK_PRICE、
      triggerPrice/qty 与计划一致（ACTIVE_CONFIRMED 的显式定义）
    protected_qty == confirmed_position_qty
    TP 可缺省（NOT_CONFIGURED）；部分覆盖不得 VERIFIED
P4  RESTART RECOVERY
    进程内模拟或真实重启 → recover() 必须无 unresolved；
    不得重复 entry、不得重复 protection；ledger/exchange 收敛。
P5  FLATTEN & CLOSE-OUT
    reduceOnly 平仓 → BTCUSDT KNOWN_FLAT、ordinary=0、AURORA Algo=0、
    V5S_* 未触碰；SESSION KILL engage（成功也 engage）；
    INCIDENT KILL 全程保持 ACTIVE、事故账本字节不变。
```

## 四、停止条件（任一出现 → 立即 STOP，资格失败）

```text
ANY UNKNOWN（position/order/algo/submit/close）
ANY IDENTITY_DRIFT（指纹/host/mode/exclusivity）
ANY COVERAGE_MISMATCH（部分覆盖、超额覆盖、protected_qty≠仓位）
ANY ORPHAN_ALGO（AURORA 前缀出现在非本会话，或会话遗留）
ANY UNEXPLAINED POSITION（账本无法解释的交易所仓位）
WIRE ACK 三方核对失败
P0 基线任一不满足
incident ledger 摘要变化
```

STOP 后：只允许 BTC 减仓方向的收口动作；收口失败保持 fail-closed、
人工只读复核；不得开第二笔。

## 五、验收矩阵（执行包必须逐条给出证据）

```text
PERMIT_SCOPE_ENFORCED                PASS 才可执行
P0_BASELINE_ALL_GREEN                PASS
SUBMIT_ACK_WIRE_RECORDED             PASS（原始响应落证据）
SUBMIT_ACK_CONTRACT                  OBSERVED / PARTIAL
ENTRY_SINGLE_INTENT                  PASS（交易所侧仅 1 个新 BTCUSDT 订单链）
PROTECTION_ACTIVE_CONFIRMED          PASS（查询回验 + workingType=MARK_PRICE）
PROTECTED_QTY_EQ_POSITION            PASS
RESTART_NO_DUPLICATES                PASS
CLOSEOUT_FLAT_ZERO_ZERO              PASS
SESSION_KILL_ENGAGED                 PASS
INCIDENT_LEDGER_UNCHANGED            PASS（字节级）
FULL_TEST_EXECUTION                  PASS
REAL_WRITES_BOUNDED                  entry=1, sl=1, tp=0/1, close=1
```

## 六、执行后最大结果（预冻结）

```text
CONTROLLED TESTNET REQUALIFICATION   CLOSED-LIMITED（若 PASS）
KILL CLEARED                         仅可作为 PASS 后的单独裁定结果
AUTO TESTNET                         仍 DENIED
SYSTEM EXECUTION                     仍 NOT QUALIFIED（多次 PASS 才可复议）
LIVE                                 仍 NO-GO
```

## 七、与本审查的关系

实施本合同 = 按 DESIGN REVIEW 的 A–F 修复预构建文件并补齐 P0/P1
两阶段，单独提交；随后由用户单独发出第一次受控写入开工令
（含 permit 签发）。本合同本身不构成执行授权。

---

## 附录：运行时范围授权（R2 草案，**已作废对 EXECUTE_AUTHORIZED 的降级**）

> 2026-09-08 用户裁定：`EXECUTE_AUTHORIZED` **仍是写盘前门**，不是 legacy dead-man。  
> 本附录不得反向解释 `6b2cc7c`。真实写路径必须在构造写客户端之前同时满足布尔前门 + scoped permit + Start Order。

真实写路径的条件（`assert_write_gates` / `check_execution_conditions`）：

```text
C1  EXECUTION START ORDER      state/testnet/<fp>/execution_start_order.json
                               schema=ctr-start-order-v1，status=OPEN，
                               未过期，含 session_id/scope/上限
C2  RUNTIME SCOPED PERMIT      qualification_permit.json，
                               session_id 必须等于 C1 的 session_id，
                               未作废、未过期；bind 即预占并持久化
C3  OPERATOR FLAG              同一次调用显式给出
                               --i-execute-controlled-requal
```

签发通道唯一：`--issue-execution-window --session-id <id> --issued-by
<操作员> --valid-hours <N>` —— 同一窗口写 START ORDER + scoped permit，
不存在独立于开工令的 permit。

会话终态（一票终结）：`sessions/<session_id>.final.json` ——
COMPLETE 与 STOP 均写入；存在终态的 session 永久拒绝再次执行；
STOP 同时作废 permit（P1 WIRE ACK 不一致 → 无第二次 entry）。
端到端 AURORA 形态 Algo 单查（workingType=MARK_PRICE 的完整
query_algo_order PASS）在受控会话 P3 现场核验，R1 的解析层合同不变。
