# EXECUTION WORK PACKAGE

> 状态：**BOUNDARY-FROZEN / NOT AUTHORIZED TO EXECUTE**  
> 封点提交：`6b2cc7c`（用户已接受为正式边界封点）  
> 冻结日：2026-09-08  
> 修订：REQUIRED AMENDMENTS 1–5 已并入  
> 前置：Harness CLOSED-OFFLINE；`EXECUTE_AUTHORIZED=false`  
> **本合同只把「若将来写那一笔 0.001」的边界一次性写死。不是开工令。**  
> HEAD 实现偏差以本封点为准，不得反向改解释。

```text
EXECUTION WORK PACKAGE                BOUNDARY-FROZEN   6b2cc7c
REQUIRED AMENDMENTS                   INCORPORATED
RESTART RECOVERY                      REQUIRED
QUALIFICATION CLOSE                   FROZEN
CLIENT ID NAMESPACE                   FROZEN
QUALIFICATION LEDGER                  ISOLATED
SCOPED SINGLE-USE PERMIT              REQUIRED

EXECUTE_AUTHORIZED                    FALSE
EXECUTION AUTHORIZATION               NOT ISSUED
SCOPED PERMIT                         NOT ISSUED
0.001 BTC WRITE                       NOT AUTHORIZED
REAL TESTNET WRITE                    DENIED
production_main                       DENIED
AURORA_ENABLE_TRADING                 DENIED
INCIDENT KILL                         ACTIVE
INCIDENT LEDGER                       IMMUTABLE
INCIDENT KILL CLEAR                   DENIED
AUTO TESTNET                          DENIED
LIVE                                  NO-GO
SYSTEM EXECUTION                      NOT QUALIFIED
```

「上线交易 / 启动交易」不是本包。本包若将来被单独授权执行，也只是一笔受控 TESTNET LONG 0.001。

裸 `EXECUTE_AUTHORIZED=true` **不够**。将来写那一笔必须在构造任何写客户端之前同时满足：

```text
EXECUTE_AUTHORIZED = true
+
permit.session_id == execution session_id
permit.single_use == true
permit.scope == exact BTCUSDT/LONG/0.001
permit.expiry valid
```

缺一即 DENY BEFORE CLIENT WRITE。当前两者都未满足。

---

## 一次性写死的边界

```text
SYMBOL                         BTCUSDT only
SIDE                           LONG only
QTY                            0.001 exactly（不是上限内任选）
MAX_NOTIONAL_USDT              120
                               只读 mark 计价；越界拒开
ACCOUNT                        3fbc5d4f1f9ddc7d TESTNET
POSITION MODE                  HEDGE（只读核对，不得改）
ACCOUNT_EXCLUSIVITY            FALSE
FOREIGN ALGO (V5S_*)           DO NOT TOUCH
ENTRY POINT                    qualification harness only
                               （aurora.ops_controlled_requal 恢复入口）
                               禁止 production_main / TradingCycle
```

### 入场前

```text
PERMIT                         必须验证（见下）
POSITION                       必须 KNOWN_FLAT
UNKNOWN POSITION               DENY
BTC ordinary open orders       必须 0
AURORA BTCUSDT Algo            必须 0
IDENTITY / HOST / MODE         必须与冻结身份一致，否则 DENY
```

### 成交与保护

```text
ENTRY FILL                     必须权威确认（fills 聚合）
                               ACK executedQty 不是真源
SL                             随后必须 ACTIVE_CONFIRMED
                               LONG SL 必须严格低于 mark
                               workingType == MARK_PRICE
PROTECTED QTY                  必须等于实际仓位
PARTIAL / OVER COVERAGE        不得 VERIFIED
TP                             NOT_CONFIGURED 允许
```

### 失败与 UNKNOWN

```text
ANY UNKNOWN                    立即停止
TIMEOUT with uncertain submit  立即停止
REMEDIATION INTENT             FORBIDDEN
                               不允许第二笔补救开仓
STOP 之后只允许                BTC 减仓收口（QUALIFICATION CLOSE）
收口失败                       fail-closed + 人工只读复核
```

### 永久禁止

```text
LIVE / AURORA_ARM_LIVE
自动 TESTNET / 策略循环
改 leverage / margin / position mode
第二笔 intent
为开跑而改事故 ledger / 事故 intent
用任何布尔常量获得无限期写能力
```

---

## Amendment 1 — RESTART RECOVERY（必须）

这笔真实 TESTNET qualification **不能**只验证 `entry → fill → SL ACTIVE → close`。  
G0-4C 的核心是：崩溃后不会忘记保护。持仓且保护已确认后，必须做一次受控重启恢复。

```text
ENTRY FILLED 0.001
→ SL ACTIVE_CONFIRMED 0.001
→ 停止 qualification runtime
→ 重新启动 qualification recovery
→ 不重复 entry
→ 不重复 SL
→ position = 0.001
→ existing SL 被重新识别
→ coverage = FULL
```

任一即 FAIL：

```text
duplicate submit
UNKNOWN
coverage mismatch
ownership ambiguity
```

恢复入口只能是 qualification harness。**禁止启动 `production_main`。**

---

## Amendment 2 — QUALIFICATION CLOSE

STOP 之后只允许这一条主动收口。禁止把「发了平仓请求」写成「emergency close executed」。

```text
QUALIFICATION CLOSE

symbol          BTCUSDT
side            SELL
positionSide    LONG
qty             actual confirmed position qty
                最大 0.001

HEDGE:
reduceOnly      不发送
closePosition   false / 不发送
```

```text
close ACK
≠ close confirmed

必须：
authoritative fill
或权威 position → KNOWN_FLAT
```

收口验收：

```text
FINAL POSITION                 必须回到 KNOWN_FLAT
AURORA BTC ordinary            必须 0
AURORA BTC Algo                必须 0
V5S_*                          未触碰
SESSION KILL                   成功或失败都必须 ENGAGED
INCIDENT KILL                  全程 ACTIVE，不得解除
INCIDENT LEDGER                字节不得改变
```

---

## Amendment 3 — 分腿 client ID

```text
AURORA-CTR-<session>-ENTRY
AURORA-CTR-<session>-SL
AURORA-CTR-<session>-CLOSE
```

```text
session id                     单次唯一
client id                      永不复用
                               禁止复用 AURORA-0650a39f56e3
一个 session 最多：
  1 ENTRY identity
  1 mandatory SL identity
  1 CLOSE identity
```

SL 若因恢复需要 query / repair，必须复用已冻结的保护身份逻辑。  
禁止因重启生成第二套无关联 client ID 后盲挂。

---

## Amendment 4 — Qualification ledger 与事故 ledger 分开

```text
INCIDENT LEDGER                immutable evidence
                               字节不得改变
                               禁止接着修改事故 intent

QUALIFICATION SESSION LEDGER   new execution evidence
                               独立 namespaced ledger

路径语义：
state/testnet/<fingerprint>/qualification/<session-id>/
```

离线 harness（`3aa4d8d`）曾用 `state/testnet/<fp>/controlled_requal.db`。  
**未来真实写入必须改走本条 namespaced 路径**；不得为了方便继续写事故账本，也不得把 qualification 事实回写事故 intent。

---

## Amendment 5 — Scoped single-use permit

```text
PERMIT:
environment      TESTNET
account          3fbc5d4f1f9ddc7d
symbol           BTCUSDT
side             LONG
qty              exactly 0.001
max_notional     120 USDT
session_id       exact
entry_count      <= 1
expires_at       required
single_use       true
```

任一字段不一致：

```text
PERMIT_SCOPE_VIOLATION
→ DENY BEFORE CLIENT WRITE
```

```text
INCIDENT KILL                  保持 ACTIVE（历史事实）
QUALIFICATION PERMIT           只覆盖本包一笔
                               不是清事故 kill
                               过期或越界立即 STOP
KILL CLEAR                     不是本包前置，也不是本包副作用
```

Permit 不得因任何布尔常量获得无限期写能力（one-lifecycle，终态即作废）。

---

## 完整成功序列（PASS 必须走完）

```text
P0  verify permit
P1  verify identity / host / HEDGE
P2  verify BTC KNOWN_FLAT
P3  verify ordinary BTC orders = 0
P4  verify AURORA BTC Algo = 0
P5  read mark; 0.001 notional <= 120

P6  submit exactly ONE LONG entry
P7  obtain authoritative fill
P8  verify actual position = LONG 0.001

P9  submit mandatory SL
P10 query until ACTIVE_CONFIRMED
P11 verify protected qty == 0.001
P12 verify workingType == MARK_PRICE

P13 controlled runtime restart
P14 recover existing position/protection
P15 prove no duplicate entry / SL

P16 controlled close SELL+LONG 0.001
P17 authoritative close evidence
P18 verify KNOWN_FLAT
P19 verify ordinary BTC orders = 0
P20 verify AURORA BTC Algo = 0
P21 verify V5S_* untouched
P22 engage/end session kill
```

任一阶段出现即 FAIL：

```text
UNKNOWN
TIMEOUT with uncertain submission
IDENTITY_DRIFT
POSITION_DRIFT
COVERAGE != FULL
ORPHAN_ALGO
foreign-order mutation
```

```text
QUALIFICATION = FAIL
NO SECOND ENTRY
ONLY RISK-REDUCTION / HUMAN RECOVERY
```

---

## 将来若单独授权执行

必须另发开工令，明确引用 `6b2cc7c`。  
开工令必须同时打开 `EXECUTE_AUTHORIZED` **并**签发本包 scoped permit。单独改布尔值无效。实现偏差见 [PRE_EXECUTION_CONFORMANCE.md](PRE_EXECUTION_CONFORMANCE.md)，以本合同为准。

即使 P0–P22 全 PASS，最大结果也只是：

```text
CONTROLLED TESTNET LIFECYCLE     PASS-1
PROTOCOL WRITE PATH              OBSERVED-PASS
PROTECTION LIFECYCLE             OBSERVED-PASS
RESTART RECOVERY                 OBSERVED-PASS

EXECUTION WORK PACKAGE           CLOSED-LIMITED
AUTO TESTNET                     DENIED
SYSTEM EXECUTION                 NOT QUALIFIED
LIVE                             NO-GO
INCIDENT KILL                    ACTIVE
```

一笔 0.001 PASS 只证明：

> 这个冻结版本在这一账户、这一时点、这一条极小生命周期上完成了真实协议闭环。

它不能证明持续自动交易资格。  
`SYSTEM EXECUTION QUALIFIED = YES` **不是**本包副作用。  
是否需要第二轮 forward qualification、以及什么证据才足以解除事故运行锁，必须另裁。

---

## P1-GOV-3（登记，未实施）：LIVE endpoint contract

当前 `ALLOWED_LIVE_HOSTS` 只含 `fapi.binance.com`；SDK 构造期 spot
ping（api.binance.com）不在白名单 → armed-LIVE 即便授权齐全也在
构造前拒绝（BLOCKED_BEFORE_CLIENT，G0-4D 探测已确认该行为）。
这是策略性正确行为，但 LIVE 端点合同从未正式定义。LIVE 解冻评审
前必须冻结：构造期/交易期各自允许的主机集合、出网守卫口径、
以及"策略不满足即构造前拒绝"的正式表达。状态：PLANNED / NOT-STARTED。
