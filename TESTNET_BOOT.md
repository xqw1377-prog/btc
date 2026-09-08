# AURORA TESTNET 操作合同

> 本文件当前 **不是启动清单**。  
> 状态 = **INCIDENT_LOCKED**。  
> 只读检查说明 = YES。自动启动指南 = NO。恢复交易指南 = NO。

运行事实真源：**kernel ledger**。`state/p0_safety.json` 不得单独宣称 MATCHED / healthy，也不得靠删除或改写该文件恢复运行。

事故档案：[docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md](docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md)  
处置裁定：[docs/incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md](docs/incidents/2026-09-06-testnet-sl-fail/DISPOSITION.md)  
手工平仓步骤（网页，非 AURORA）：[OPERATOR_CLOSE_CHECKLIST.md](docs/incidents/2026-09-06-testnet-sl-fail/OPERATOR_CLOSE_CHECKLIST.md)

LIVE = **NO-GO**。不要设 `TRADING_MODE=LIVE`，不要设 `AURORA_ARM_LIVE`。

---

```text
AURORA TESTNET STATUS
=====================

State:
INCIDENT_LOCKED

Incident:
2026-09-06 TESTNET protection failure
intent AURORA-0650a39f56e3

Authoritative runtime truth:
kernel ledger

Incident position (read-only 2026-09-08T02:38:29Z):
BTCUSDT LONG/SHORT     KNOWN_FLAT 0.0000 / 0.0000
open orders            = 0
AURORA BTCUSDT Algo    = 0
EXIT_MECHANISM         UNKNOWN
MANUAL_CLOSE_FILL      NOT_FOUND
MANUAL_CLOSE_ORDER     NOT_FOUND
INCIDENT_POSITION      RECOVERED
INCIDENT_EVIDENCE      OPEN_RESIDUAL (EXIT-PROVENANCE-01)
HISTORICAL_EVIDENCE_GAP ACCEPTED
INCIDENT_REQUALIFICATION_ELIGIBLE  YES
KILL                   ACTIVE
p0_safety              STALE

Current restrictions:
- production_main: DENIED
- --boot-only: DENIED
- AURORA_ENABLE_TRADING=true: DENIED
- automatic trading: DENIED
- kill clear/reset: DENIED
- ledger reset/edit of old facts: DENIED
- account-wide position-mode mutation: DENIED
- uncommitted G0-4B/4C code against exchange: DENIED

Allowed:
- offline config inspection (safety_check)
- read-only incident reconciliation
- manual TESTNET incident archive / read-only recon
- offline development/tests（含 G0-4A fake transport）

Exit criteria (all required):
1. incident position reconciled/closed (exchange FLAT + 人工干预事实)
2. G0-4A / G0-4B / G0-4C protocol qualification
3. G0-5 config-source qualification
4. dedicated TESTNET requalification (G0-4D read-only; not “watch one HOLD cycle”)
5. explicit resume approval

LIVE:
NO-GO
```

---

## TESTNET OPERATING STATE

```text
INCIDENT_LOCKED
    ↓
事故人工收口（仓位 FLAT + 只读复核 + 追加人工干预事实；kill 仍 ACTIVE）
    ↓
PROTOCOL_VALIDATION
    ↓
G0-4A / 4B / 4C + G0-5 通过
    ↓
INCIDENT DISPOSITION（证据缺口 ACCEPTED；只读复核资格 YES；lock/kill 仍 ACTIVE）
    ↓
TESTNET_REQUALIFICATION（G0-4D CLOSED-READONLY；恢复证据 PARTIAL）
    ↓
CONTROLLED TESTNET REQUALIFICATION（HARNESS-READY / EXECUTE DENIED）
    ↓
明确审批
    ↓
TESTNET_READY   ← 下文「资格门之后」的启动 SOP 才开放
```

当前停在 **INCIDENT_LOCKED**。仓位风险已收口为交易所 KNOWN_FLAT；证据残留 EXIT-PROVENANCE-01 仍 OPEN。G0-4D **CLOSED-READONLY**。受控写入边界已冻，**执行未授权**。见 [CONTROLLED_TESTNET_REQUAL.md](docs/product/CONTROLLED_TESTNET_REQUAL.md)。**系统事故在 kill 解除审批前不算结束。**

```text
INCIDENT_POSITION_STATE       RECOVERED
INCIDENT_EVIDENCE_STATE       OPEN_RESIDUAL
EXIT-PROVENANCE-01            OPEN / APPEND-ONLY
POSITION_RISK_RECOVERED       YES
FINAL_POSITION                KNOWN_FLAT
EXIT_MECHANISM                UNKNOWN
SYSTEM_EXECUTION_QUALIFIED    NO
KILL                          ACTIVE
G0-4A                         CLOSED-OFFLINE
G0-4B                         CLOSED-OFFLINE
G0-4B_COMMIT                  1bb1ecf
G0-4C                         CLOSED-OFFLINE
G0-4C_COMMIT                  5bfa311
G0-4D                         CLOSED-READONLY
G0-5                          CLOSED-OFFLINE
G0-5_COMMIT                   d0863ee
HISTORICAL_EVIDENCE_GAP       ACCEPTED
INCIDENT_REQUALIFICATION_ELIGIBLE  YES
INCIDENT_LOCK                 ACTIVE
AUTO_TESTNET                  DENIED
CONTROLLED_REQUAL             IMPLEMENTED / EXECUTE DENIED
PRE_EXECUTION_CONFORMANCE     ALIGNED TO 6b2cc7c
EXECUTION_WP                  BOUNDARY-FROZEN / NOT AUTHORIZED TO EXECUTE
                              SEALED 6b2cc7c
                              PERMIT NOT ISSUED
OFFLINE CONTRACTS             PROVEN
READ-ONLY TESTNET             SEALED
REAL WRITE PATH               DENIED
LIVE                          NO-GO
```

证据残留可永久 OPEN。受控写入边界已冻于 `6b2cc7c`，执行未授权、permit 未签发；`INCIDENT_LOCK` / 事故 kill 未解除。

---

## INCIDENT_LOCKED 下允许

| 动作 | 说明 |
|---|---|
| 读 FACTS.md / 本文件顶部合同 | 事故真源与禁令 |
| `python3 -m aurora.safety_check` | **OFFLINE CONFIG CHECK**。不出网探账户 |
| 只读交易所核对 | 专用 incident/ops 只读路径；**不是** `production_main` |
| 查看 `state/kernel_ledger.db` | kill / intent / 订单 / 成交。不要改旧行 |
| 网页手工平掉 BTCUSDT LONG 0.007 | 已执行；成交未找到。`MANUAL_RECOVERY_ACTION.json` 是处置记录，不是 fill 事实 |

`safety_check` ≠ 启动。它只回答「这份配置在离线规则下是否自洽」。

---

## INCIDENT_LOCKED 下禁止

```text
python3 -m aurora.production_main
python3 -m aurora.production_main --boot-only
AURORA_ENABLE_TRADING=true
清 kill / 重置 ledger / 改旧订单行让账本变漂亮
删除或改写 p0_safety.json 以恢复运行
python3 -m aurora.ops_position_mode
工作区未提交 G0-4B/4C 对交易所 submit/cancel
```

### 为什么 `--boot-only` 也禁止

`production_main --boot-only` 是 **ONLINE ACCOUNT BOOT PROBE**：出网、构造客户端、读账户、武装内核恢复。  
不是「安全启动自检」。事故期间用生产入口「为了看一眼」会绕过「不启动 production_main」。

### 为什么不能清 `p0_safety.json`

事故已经证明两套账不一致：kernel 为 RECOVERY_REQUIRED + kill；p0_safety 为 MATCHED + kill=false。

```text
任何 kill / HALTED 均不得通过删除、修改或重置
p0_safety.json 恢复运行。

运行恢复资格只能来自 kernel authoritative state
以及明确的人工恢复审批。
```

### 为什么不能改账户持仓模式

position mode 是**账户级**状态。本测试网账户上还有非 AURORA 的 `V5S_*` Algo（XRP / ENA / DOGE）。

```text
ACCOUNT-WIDE MUTATION = DENIED BY DEFAULT
```

AURORA 只允许：读取 mode、与声明核对、不一致则拒启。  
未来若必须改模式，须先确认整个账户无仓、无普通单、无 Algo、无其他机器人，并经独立人工审批。不得当作排障步骤。

### 为什么「看一轮 submitted=False 再开交易」作废

ENTRY 成功 ≠ 具备安全交易能力。本次事故：入场成交，保护失败，紧急平仓被拒。  
一轮不下单日志不能证明 Algo 保护、紧急减仓、HEDGE 合同、UNKNOWN 生命周期或对账正确。

---

## 事故仓（截至 2026-09-08T02:38:29Z 只读）

```text
BTCUSDT LONG/SHORT     KNOWN_FLAT 0 / 0
open orders            0
AURORA BTCUSDT Algo    0
EXIT_MECHANISM         UNKNOWN
MANUAL_CLOSE_FILL      NOT_FOUND
MANUAL_CLOSE_ORDER     NOT_FOUND
KILL                   ACTIVE
```

细节与缺口见 [FACTS.md 人工平仓复核](docs/incidents/2026-09-06-testnet-sl-fail/FACTS.md)。

---

## 资格门之后：TESTNET_READY 启动 SOP（当前整章 DENIED）

> 以下步骤 **全部锁定**。在 Exit criteria 未满足且没有书面恢复审批之前，
> 当作历史 SOP 存档，**不要执行**。

### R0. 准备（仅当 TESTNET_READY）

- Testnet USDS-M 密钥（不是主网）
- 账户持仓模式与声明一致（只读核对；不改账户）
- `pip3 install -r requirements.txt`
- 工作目录为仓库根

### R1. `.env` 最小集合（仅当 TESTNET_READY）

```bash
TRADING_MODE=TESTNET
TESTNET=true
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
AURORA_ACCOUNT_FINGERPRINT=
AURORA_EXPECTED_POSITION_MODE=HEDGE
# AURORA_ENABLE_TRADING 默认不要设。恢复交易须单独审批，不是本清单能打开的。
```

指纹必须与当前 `BINANCE_API_KEY` 一致。禁止 `TRADING_MODE=LIVE`、`AURORA_ARM_LIVE`、`ALLOW_LIVE_TRADING=true`、以及与 TESTNET 冲突的 `TESTNET=false/0/no/off`。

可选路径：`AURORA_P0_STATE` / `AURORA_P0_LOCK_DIR` / `AURORA_LEDGER_PATH`。未设则用 `state/` 默认值。**健康状态仍以 kernel ledger 为准。**

### R2. OFFLINE CONFIG CHECK（事故期间唯一仍允许的检查）

```bash
python3 -m aurora.safety_check
```

期望：`[P0] TRADING_MODE=TESTNET config accepted.`  
这不是账户探活，也不是放行交易。

### R3. ONLINE ACCOUNT BOOT PROBE（当前 DENIED）

```bash
# DENIED while INCIDENT_LOCKED
# python3 -m aurora.production_main --boot-only
```

出网、构造客户端、读账户。不是配置自检。恢复后须在独立 TESTNET_REQUALIFICATION 会话中执行，不得当作「先跑起来」。

### R4. 账户级持仓模式变更（当前 DENIED）

```bash
# DENIED BY DEFAULT — 账户非独占
# python3 -m aurora.ops_position_mode --target HEDGE --i-understand-account-wide
```

不一致 → 拒启。不要改账户来迁就进程。

### R5. 常驻进程（当前 DENIED）

```bash
# DENIED while INCIDENT_LOCKED
# python3 -m aurora.production_main
```

### R6. 打开自动下单（当前 DENIED）

```text
# DENIED
# AURORA_ENABLE_TRADING=true
```

将来恢复 TESTNET 自动执行，必须先：

```text
G0-4A offline protocol PASS
G0-4B emergency close contract PASS
G0-4C protection lifecycle PASS
G0-5 config identity PASS
→ dedicated TESTNET validation session
→ incident-free evidence
→ recovery review
→ 才讨论重新 enable trading
```

「先看一轮 `submitted=False`」**不是**恢复条件。

### R7. 观察面（恢复后）

- **真源**：`state/kernel_ledger.db`（intent / 订单 / 成交 / kill / 持仓事实）
- **非真源**：`state/p0_safety.json`（派生投影）
- 测试网网页或只读 API：仓位、普通单、Algo 是否与账本一致
- `kernel recover unresolved`：停。按 client_order_id 查交易所。不要重启碰运气重提

---

## 永久禁止（任何状态）

- 主网密钥填进 TESTNET
- 两个 `production_main` 同时控同一账户
- 旧入口：`aurora_hf_kernel.py` / `aurora_final.py` / `ws_server.py`
- 为了「先跑起来」清 kill / 改 ledger / 删状态文件
- 设 LIVE 武装令牌
