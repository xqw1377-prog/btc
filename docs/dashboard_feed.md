# aurora-dashboard 只读观察面（C5 收口）

## 身份与边界

- `aurora/dashboard_feed.py`：**EXCHANGE_OBSERVATION**——交易所只读观察
  快照，不是账本投影，不证明对账结果。
- 仅允许 `TRADING_MODE=TESTNET / SHADOW`；PAPER 与 LIVE 在构造前拒绝。
- 客户端构造复用 `aurora.safety.build_client` 的 C2.1 边界（构造前目标
  校验、出站守卫、禁跳转），feed 不另建构造路径。
- 后端能力限制：`ReadOnlyClient` 白名单仅含
  `futures_ticker / futures_klines / futures_account / futures_account_trades`；
  白名单外属性访问即 `SafetyViolation`。入站 WS 消息一律忽略，无动态转发。

## 启动

```bash
python -m aurora.dashboard_feed            # 默认读取 <repo>/.env，监听 127.0.0.1:8000
python -m aurora.dashboard_feed --env-file /path/to/x.env
```

- `--env-file` 显式指定，不向父目录搜索；进程环境优先（override=False）。
- 监听地址默认回环；Origin 白名单默认 `http://localhost:5173` 与
  `http://127.0.0.1:5173`，可用 `AURORA_DASHBOARD_ORIGINS`（逗号分隔）覆盖。
  Origin 检查只是浏览器来源限制，不是身份认证。

## 数据语义

每条广播 payload 携带 `meta`：`source / mode / status / updatedAt /
lastError / ledgerReconciled=false / protectionStatus=NOT_VERIFIED`。

- `status`：`ok` / `stale`（有旧快照但本次失败）/ `unknown`（从未成功）。
- `updatedAt` 只在采集成功时更新；重广播不刷新。
- 账户查询失败时 `positionsState=UNKNOWN`，绝不在失败时显示 FLAT。
- 保护单状态本观察面**不核验**（G0-4 未完成）；`killSwitch` 等字段为
  前端占位，后端不提供写入口。
