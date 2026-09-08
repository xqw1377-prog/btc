# CTR-20260908-01 — QUALIFICATION FAIL

```text
session_id     CTR-20260908-01
contract       6b2cc7c
operator       确认按此单执行
outcome        FAIL / STOP AT P2
exchange write 0
BTC position   KNOWN_FLAT（事后只读确认）
ordinary BTC   0
AURORA BTC Algo 0
V5S_*          未触碰
incident kill  ACTIVE
EXECUTE        restored FALSE
NO SECOND ENTRY
```

## 经过

1. 签发窗口 + scoped permit（`CTR-20260908-01`，6 小时）。
2. 只读 P0：指纹匹配、HEDGE、FLAT、无 BTC 挂单、无 AURORA BTC Algo。
3. 单独提交 `f0126f5` 翻转 `EXECUTE_AUTHORIZED=true`。
4. 真实写入口启动后，**未调用 `recover()` 就 `open_position`**。
5. 账本仓位事实仍是 UNKNOWN → OPEN DENIED。**没有向交易所 POST。**
6. 收口误把「无仓」当成必须平仓，`SafetyViolation(SystemExit)` 冲出 `except Exception`。
7. 事后只读：open legs = 0，BTC 挂单 = 0，BTC Algo = 0。

## 裁定

```text
QUALIFICATION = FAIL
NO SECOND ENTRY under this session
ONLY RISK-REDUCTION / HUMAN RECOVERY
PASS-1 = NOT ACHIEVED
AUTO TESTNET = DENIED
SYSTEM EXECUTION = NOT QUALIFIED
LIVE = NO-GO
```

下一笔必须另发引用 `6b2cc7c` 的新 session 开工令。本单不得重开。
