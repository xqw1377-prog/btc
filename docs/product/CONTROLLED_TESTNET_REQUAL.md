# CONTROLLED TESTNET REQUALIFICATION

> 状态：**HARNESS-READY / EXECUTE DENIED**  
> 冻结日：2026-09-08  
> 前置：G0-4D `b0b1ef1` CLOSED-READONLY；Incident Disposition `c612c8d`  
> **本文件只冻结写入边界。未授权执行。未清事故 kill。未启动交易。**

```text
CONTROLLED TESTNET REQUALIFICATION    HARNESS-READY
EXECUTE                               DENIED
production_main                       DENIED
AURORA_ENABLE_TRADING                 DENIED
AUTO TESTNET                          DENIED
INCIDENT KILL CLEAR                   DENIED
LIVE                                  NO-GO
SYSTEM EXECUTION                      NOT QUALIFIED
```

「授权启动交易」不是本包。本包若将来执行，也只是一次受控、有上限、可强制停机的 TESTNET 资格试验。

---

## 为什么现在还不能交易

事故 kill 仍在 `state/kernel_ledger.db`。G0-4D 只证明能读。  
历史退出来源仍是 PARTIAL。共享账户 `ACCOUNT_EXCLUSIVITY=FALSE`。  
因此不得把 `production_main` 或策略循环重新打开。

---

## 写入边界（冻结）

### 范围

```text
SYMBOL                         BTCUSDT only
SIDE                           LONG only（单腿）
ACCOUNT                        3fbc5d4f1f9ddc7d TESTNET
POSITION MODE                  HEDGE（只读核对；不得改账户）
ACCOUNT_EXCLUSIVITY            FALSE
FOREIGN ALGO (V5S_*)           DO NOT TOUCH
ENTRY POINT                    专用受控命令；禁止 production_main
                               禁止 TradingCycle / 自动策略
```

### 规模

```text
MAX_QTY                        0.001          （交易所最小步长；< 事故 0.007）
MAX_NOTIONAL_USDT              120            （现价越界则拒开）
INTENTS                        1
CLIENT ID                      单次唯一；禁止复用事故 AURORA-0650a39f56e3
TP                             NOT_CONFIGURED 允许
```

### 保护合同（事故复盘硬条件）

```text
1. 必须先确认 ENTRY fill，再按 fills 聚合数量 sizing 保护
2. ACK executedQty 不是保护数量真源
3. SL 必须 ACTIVE_CONFIRMED，否则立即 fail-closed
4. protected_qty == confirmed_position_qty
5. 部分覆盖不得 VERIFIED；超额覆盖不得当作更安全
6. SUBMIT_UNKNOWN 不盲重提；任意 UNKNOWN 立即停止
```

### 重启与 UNKNOWN

```text
SESSION START                  先只读：FLAT、无 BTC 普通挂单、无 AURORA BTC Algo
MID-SESSION RESTART            recover() 必须通过，否则停止并进入收口
UNKNOWN POSITION / ORDER / ALGO
                               立即停止 → 尝试只减 BTC 仓 → SESSION KILL
```

### 账本与 kill（两套事实，禁止混写）

```text
INCIDENT LEDGER                state/kernel_ledger.db
INCIDENT KILL                  ACTIVE，只读，本包不得解除、不得改旧行

SESSION LEDGER                 显式新路径
                               state/testnet/3fbc5d4f1f9ddc7d/controlled_requal.db
                               禁止 ensure_ledger_migrated 从事故账本接管
SESSION KILL                   会话内自管：UNKNOWN/失败立即 engage
                               收口成功后也必须 engage
```

事故 kill 保持 ACTIVE，是历史事实。受控试验用隔离账本，不是「把事故 kill 清掉再跑生产循环」。

### 收口（强制）

试验结束或任何失败，必须做到：

```text
BTCUSDT                        KNOWN_FLAT
AURORA BTCUSDT ordinary        0
AURORA BTCUSDT Algo            0
V5S_*                          未触碰
SESSION KILL                   ENGAGED
INCIDENT KILL                  仍为 ACTIVE
```

收口失败 → 保持 fail-closed，人工只读复核，不得再开第二笔。

### 永久禁止

```text
LIVE / AURORA_ARM_LIVE
改 position mode / leverage / margin
POST 到非本包白名单路径
第二笔 intent
复用事故 client id
自动策略循环
为了开跑而改事故 ledger / 清事故 kill
```

---

## 将来若单独授权执行

必须另发开工令，且只能是上述边界内的一次性试验。  
通过后的最大结果：

```text
CONTROLLED TESTNET REQUALIFICATION    CLOSED-LIMITED
AUTO TESTNET                          仍 DENIED
SYSTEM EXECUTION                      仍 NOT QUALIFIED
LIVE                                  仍 NO-GO
INCIDENT KILL                         仍 ACTIVE
```

一次受控试验 PASS ≠ 恢复系统交易。

执行边界的正式冻结见 [EXECUTION_WORK_PACKAGE.md](EXECUTION_WORK_PACKAGE.md)。REQUIRED AMENDMENTS 已并入。该文件仍是 **NOT AUTHORIZED TO EXECUTE**。

---

## 已落地（仍不可执行）

```text
命令                 python3 -m aurora.ops_controlled_requal
默认                 PLAN only
--i-execute-...      仍 DENIED（旗标本身不开写）
离线会话             开仓前 FLAT/UNKNOWN 门禁 + SL 必须低于 mark
                     保护失败 → 会话 kill
EXECUTE_AUTHORIZED   false（硬开关；execute_live 恒拒且不构造客户端）
```
