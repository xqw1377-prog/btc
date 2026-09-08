# EXECUTION WORK PACKAGE

> 状态：**BOUNDARY-FROZEN / NOT AUTHORIZED TO EXECUTE**  
> 冻结日：2026-09-08  
> 前置：Harness `3aa4d8d` CLOSED-OFFLINE；`EXECUTE_AUTHORIZED=false`  
> **本合同只把「若将来写那一笔 0.001」的边界一次性写死。不是开工令。**

```text
EXECUTION WORK PACKAGE                BOUNDARY-FROZEN
EXECUTE_AUTHORIZED                    FALSE
CONTROLLED TESTNET EXECUTE            DENIED
production_main                       DENIED
AURORA_ENABLE_TRADING                 DENIED
INCIDENT KILL CLEAR                   DENIED
LIVE                                  NO-GO
SYSTEM EXECUTION                      NOT QUALIFIED
```

「上线交易 / 启动交易」不是本包。本包若将来被单独授权执行，也只是一笔受控 TESTNET LONG 0.001。

---

## 一次性写死的边界

```text
SYMBOL                         BTCUSDT only
SIDE                           LONG only
QTY                            0.001 exactly（不是上限内任选）
MAX_NOTIONAL_USDT              120
                               只读 mark 计价；越界拒开
CLIENT ID NAMESPACE            AURORA-CTR-*
                               禁止复用 AURORA-0650a39f56e3
ACCOUNT                        3fbc5d4f1f9ddc7d TESTNET
POSITION MODE                  HEDGE（只读核对，不得改）
ACCOUNT_EXCLUSIVITY            FALSE
FOREIGN ALGO (V5S_*)           DO NOT TOUCH
ENTRY POINT                    aurora.ops_controlled_requal only
                               禁止 production_main / TradingCycle
```

### 入场前

```text
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
PROTECTED QTY                  必须等于实际仓位
PARTIAL / OVER COVERAGE        不得 VERIFIED
TP                             NOT_CONFIGURED 允许
```

### 失败与 UNKNOWN

```text
ANY UNKNOWN                    立即停止
REMEDIATION INTENT             FORBIDDEN
                               不允许第二笔补救开仓
STOP 之后只允许                BTC 减仓收口
收口失败                       fail-closed + 人工只读复核
```

### 收口

```text
FINAL POSITION                 必须回到 KNOWN_FLAT
AURORA BTC ordinary            必须 0
AURORA BTC Algo                必须 0
V5S_*                          未触碰
SESSION KILL                   成功或失败都必须 ENGAGED
INCIDENT KILL                  全程 ACTIVE，不得解除
INCIDENT LEDGER                字节不得改变
```

### kill / permit

```text
INCIDENT KILL                  保持 ACTIVE（历史事实）
QUALIFICATION PERMIT           若将来签发，只覆盖本包一笔
                               不是清事故 kill
                               过期或越界立即 STOP
KILL CLEAR                     不是本包前置，也不是本包副作用
```

### 永久禁止

```text
LIVE / AURORA_ARM_LIVE
自动 TESTNET / 策略循环
改 leverage / margin / position mode
第二笔 intent
为开跑而改事故 ledger
```

---

## 将来若单独授权执行

必须另发开工令，明确引用本文件，并保持 `EXECUTE_AUTHORIZED` 在代码里被打开之前先有书面令。  
通过后的最大结果：

```text
EXECUTION WORK PACKAGE                CLOSED-LIMITED
AUTO TESTNET                          仍 DENIED
SYSTEM EXECUTION                      仍 NOT QUALIFIED
LIVE                                  仍 NO-GO
INCIDENT KILL                         仍 ACTIVE
```

一笔 0.001 PASS ≠ 上线交易。
