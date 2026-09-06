# TESTNET 最小启动清单

唯一入口：`python -m aurora.production_main`  
不要跑 `aurora_hf_kernel.py` / `aurora_final.py` / `ws_server.py`。  
不要设 `TRADING_MODE=LIVE`，不要设 `AURORA_ARM_LIVE`。

TESTNET 会连 **Binance 期货测试网**（真实出网），并用测试网密钥。  
进程武装内核后跑收盘 K 决策循环。**默认不算完不下单**；只有  
`AURORA_ENABLE_TRADING=true` 才会把 OPEN/CLOSE 送到 Orchestrator。

## 0. 准备

- 一把 **Testnet** USDS-M 密钥（不是主网密钥）
- 测试网账户持仓模式与声明一致（默认声明 `HEDGE`）
- 本机已 `pip3 install -r requirements.txt`
- 工作目录是仓库根：`/Users/xinquanwang/AURORA`

## 1. 写 `.env`（最小集合）

```bash
TRADING_MODE=TESTNET
TESTNET=true
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
AURORA_ACCOUNT_FINGERPRINT=
AURORA_EXPECTED_POSITION_MODE=HEDGE
# 先不要开。确认 --boot-only 成功后再设 true。
# AURORA_ENABLE_TRADING=true
```

计算指纹（必须与当前 `BINANCE_API_KEY` 一致）：

```bash
python3 -c "import hashlib,os; from dotenv import load_dotenv; load_dotenv(); print(hashlib.sha256(os.environ['BINANCE_API_KEY'].encode()).hexdigest()[:16])"
```

把输出填进 `AURORA_ACCOUNT_FINGERPRINT`。

禁止出现：

| 变量 | 原因 |
|---|---|
| `TRADING_MODE=LIVE` | 主网路径 |
| `AURORA_ARM_LIVE=...` | 武装主网 |
| `ALLOW_LIVE_TRADING=true` | 主网双重授权 |
| `TESTNET=false` / `0` / `no` / `off` | 与 TESTNET 模式冲突，拒启 |

可选：

```bash
AURORA_P0_STATE=state/p0_safety.json
AURORA_P0_LOCK_DIR=state/locks
AURORA_LEDGER_PATH=state/kernel_ledger.db
```

不填则用上面这三个默认路径。

## 2. 配置自检（不出网探账户）

```bash
python3 -m aurora.safety_check
```

期望：`[P0] TRADING_MODE=TESTNET config accepted.`

## 3. 安全启动自检（出网，武装后立即退出）

```bash
python3 -m aurora.production_main --boot-only
```

成功应看到类似：

```text
[P0] boot ok mode=TESTNET ...
[P0] --boot-only: exiting after successful safety boot.
```

失败常见原因：

| 现象 | 处理 |
|---|---|
| missing BINANCE_API_KEY/SECRET | `.env` 没加载或键名错 |
| account fingerprint mismatch | 用第 1 步命令重算指纹 |
| endpoint is not testnet | 密钥/客户端没走测试网 |
| position mode X != declared Y | 见第 4 步，进程**不会**自动改模式 |
| persisted HALTED / kill switch | 人工确认后才能清 `state/p0_safety.json`，不要当正常启动步骤 |
| account lock held | 已有实例在跑；先停旧进程 |
| boot drift requires recovery | 交易所仓位与本地脑状态不一致，先人工对账 |

## 4. 持仓模式不一致时（独立 ops，不是交易进程）

先确认测试网账户 **无仓、无挂单**，再：

```bash
python3 -m aurora.ops_position_mode --target HEDGE --i-understand-account-wide
```

然后重跑第 3 步。

## 5. 常驻（心跳，不自动开仓）

```bash
python3 -m aurora.production_main
```

期望：

```text
[P0] boot ok mode=TESTNET ... armed=True
[P0] TESTNET armed: kernel recover heartbeat, orders via Orchestrator only.
```

进程每 30 秒：`recover()` → 拉 1m K 线 → 用**已收盘** bar 决策。  
未设 `AURORA_ENABLE_TRADING=true` 时只打印 intent，不下单。  
设为 true 后，OPEN/CLOSE 只走武装内核（真实 SL/TP 价，不是 99/101 测试桩）。

先看一轮 `submitted=False` 的日志，再打开交易开关。

停：`Ctrl-C` 或 `SIGTERM`。

## 6. 启动后看什么

- `state/p0_safety.json`：halt / kill / 上次对账
- `state/kernel_ledger.db`：意图 / 订单 / 成交 / 持仓事实
- 测试网网页或 API：仓位、挂单是否与账本一致
- 日志里若出现 `kernel recover unresolved`：先停，按 client_order_id 查交易所，不要重启碰运气重提

## 7. 明确不要做

- 不要用主网密钥填进 TESTNET
- 不要同时再起一个 `production_main`（账户锁会拒）
- 不要为了“先跑起来”清 kill / HALTED
- 不要把 Docker/`aurora_hf_kernel` 当入口
- 不要在这一步设 LIVE 武装令牌
