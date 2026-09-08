"""Read-only TESTNET/SHADOW observation feed for aurora-dashboard.

身份：EXCHANGE_OBSERVATION —— 交易所只读观察快照，不是账本投影。
不交易、不取账户锁、不接入 ArmedRuntime；LIVE/PAPER 拒绝；消息入口
不解析、不转发——任何客户端消息都无法触发 SDK 写调用。

数据纪律：
- 每个数据段（market/account/risk/trades）独立记录 status 与
  last_success_at；重广播旧数据不会刷新"最后成功采集时间"。
- 查询失败的段标记 stale（有旧快照）或 unknown（从未成功），绝不把
  失败显示成 FLAT/零仓位/全部正常。
- 本观察面不核验保护单状态：protectionStatus 恒为 NOT_VERIFIED。
- 输出为手工白名单字段；异常文本经 _redact 脱敏后才进日志/状态。

监听边界：默认仅回环 127.0.0.1；WebSocket Origin 白名单默认放行
Vite 开发源（http://localhost:5173 / http://127.0.0.1:5173），可用
AURORA_DASHBOARD_ORIGINS 覆盖。Origin 检查不是非浏览器客户端的身份认证。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from aurora.feature_engine import FeatureEngine
from aurora.market_state_engine_v2 import MarketStateEngineV2
from aurora.p0_boundary import RunMode, SafetyViolation, resolve_mode
from aurora.safety import read_only_client

# 只读能力白名单：后端能力限制，不依赖"页面上没有按钮"。
READ_METHODS = frozenset({
    "futures_ticker",
    "futures_klines",
    "futures_account",
    "futures_account_trades",
})

_SECRET_KEY_MARKS = (
    "BINANCE_API", "SECRET", "TELEGRAM", "AURORA_LIVE",
    "AURORA_ARM", "TOKEN", "PASSWORD",
)


def _secret_values(environ: Optional[Dict[str, str]] = None) -> List[str]:
    src = environ if environ is not None else os.environ
    return [
        v for k, v in src.items()
        if v and len(v) >= 4 and any(m in k.upper() for m in _SECRET_KEY_MARKS)
    ]


def redact(text: Any, environ: Optional[Dict[str, str]] = None) -> str:
    out = str(text)
    for value in _secret_values(environ):
        out = out.replace(value, "***REDACTED***")
    return out


def default_env_file() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )


def allowed_origins(environ: Optional[Dict[str, str]] = None) -> List[str]:
    src = environ if environ is not None else os.environ
    raw = (src.get("AURORA_DASHBOARD_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


class ReadOnlyClient:
    """把已构造的 SDK 客户端收窄成只读视图。

    白名单外属性访问直接拒绝；不存在动态转发入口。客户端构造本身复用
    safety.build_client 的 C2.1 边界（构造前目标校验 + 出站守卫 +
    禁跳转），本模块不另建构造路径。
    """

    def __init__(self, client: Any):
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name not in READ_METHODS:
            raise SafetyViolation(
                f"[P0] dashboard read-only client has no method: {name}"
            )
        return getattr(self._client, name)


def _section_meta() -> Dict[str, Any]:
    return {"status": "unknown", "updated_at": None, "last_error": None}


class DashboardFeed:
    SECTIONS = ("market", "account", "risk", "trades")

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        client: Any = None,
        mode: Optional[RunMode] = None,
        environ: Optional[Dict[str, str]] = None,
    ):
        self.host = host
        self.port = port
        self.mode = mode or resolve_mode(environ if environ is not None else None)
        if self.mode not in (RunMode.TESTNET, RunMode.SHADOW):
            raise SafetyViolation(
                f"[P0] dashboard feed only allowed in TESTNET/SHADOW, got {self.mode.value}."
            )
        self.clients: Set[Any] = set()
        base = client if client is not None else read_only_client(environ=environ)
        self.client = ReadOnlyClient(base)
        self.feature_engine = FeatureEngine()
        self.state_engine = MarketStateEngineV2()
        self.meta: Dict[str, Dict[str, Any]] = {
            name: _section_meta() for name in self.SECTIONS
        }
        self.market_data: Dict[str, Any] = {
            "price": 0,
            "priceChange": 0,
            "priceChangePercent": 0,
            "regime": "TRANSITION",
            "confidence": 0,
            "ema20": 0,
            "ema60": 0,
            "atr": 0,
            "adx": 0,
            "volatility": 0,
            "volume": 0,
            "klines": [],
        }
        self.account_data: Dict[str, Any] = {
            "balance": 0,
            "equity": 0,
            "unrealizedPnl": 0,
            "positions": [],
            "positionsState": "UNKNOWN",
            "mode": self.mode.value,
            "killSwitch": False,
        }
        self.risk_data: Dict[str, Any] = {
            "currentDrawdown": 0,
            "maxDrawdown": 0,
            "dailyPnl": 0,
            "weeklyPnl": 0,
            "totalPnl": 0,
            "status": "UNKNOWN",
        }
        self.pnl_data: list = []
        self.trade_data: list = []

    # ---- 元数据与输出包封 ----

    def _meta_block(self, section: str) -> Dict[str, Any]:
        m = self.meta[section]
        return {
            "source": "EXCHANGE_READONLY",
            "mode": self.mode.value,
            "status": m["status"],
            "updatedAt": m["updated_at"],
            "lastError": m["last_error"],
            "ledgerReconciled": False,
            "protectionStatus": "NOT_VERIFIED",
        }

    def _envelope(self, msg_type: str, section: str, payload: Any) -> str:
        if isinstance(payload, dict):
            payload = {**payload, "meta": self._meta_block(section)}
        return json.dumps({"type": msg_type, "payload": payload})

    async def register(self, websocket):
        self.clients.add(websocket)
        await self.send_initial_data(websocket)

    async def unregister(self, websocket):
        self.clients.discard(websocket)

    async def send_initial_data(self, websocket):
        for msg in (
            self._envelope("market", "market", self.market_data),
            self._envelope("system", "account", self._system_payload()),
            self._envelope("risk", "risk", self.risk_data),
            json.dumps({"type": "pnl", "payload": self.pnl_data}),
            json.dumps({"type": "score", "payload": 0}),
            self._envelope("trades", "trades", self.trade_data),
        ):
            await websocket.send(msg)

    def _system_payload(self) -> Dict[str, Any]:
        # channel 名沿用前端现有 'system'；内容明确标注观察身份。
        return {**self.account_data, "observation": True}

    async def broadcast(self, message: str):
        if not self.clients:
            return
        await asyncio.gather(
            *[client.send(message) for client in self.clients],
            return_exceptions=True,
        )

    # ---- 采集：各段独立成败，失败不伪装 ----

    def _run_fetch(self, section: str, fn) -> bool:
        try:
            fn()
        except Exception as exc:
            meta = self.meta[section]
            meta["status"] = "stale" if meta["updated_at"] else "unknown"
            meta["last_error"] = redact(
                f"{type(exc).__name__}: {exc}"
            )[:200]
            return False
        meta = self.meta[section]
        meta["status"] = "ok"
        meta["updated_at"] = datetime.now().isoformat()
        meta["last_error"] = None
        return True

    def fetch_market_data(self):
        ticker = self.client.futures_ticker(symbol="BTCUSDT")
        self.market_data["price"] = float(ticker["lastPrice"])
        self.market_data["priceChange"] = float(ticker["priceChange"])
        self.market_data["priceChangePercent"] = float(ticker["priceChangePercent"])

        import pandas as pd

        klines = self.client.futures_klines(symbol="BTCUSDT", interval="1m", limit=100)
        df = pd.DataFrame(
            klines,
            columns=[
                "time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore",
            ],
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        self.market_data["klines"] = [
            {
                "time": int(row["time"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for _, row in df.tail(50).iterrows()
        ]
        features = self.feature_engine.get_latest_features(df, exclude_forming=True)
        self.market_data["ema20"] = features.get("ema20", 0)
        self.market_data["ema60"] = features.get("ema60", 0)
        self.market_data["atr"] = features.get("atr", 0)
        self.market_data["adx"] = features.get("adx", 0)
        self.market_data["volatility"] = features.get("volatility", 0)
        self.market_data["volume"] = features.get("volume", 0)
        market_state = self.state_engine.identify_regime(features)
        self.market_data["regime"] = market_state.get("regime", "TRANSITION")
        self.market_data["confidence"] = market_state.get("confidence", 0)

    def fetch_account_data(self):
        account = self.client.futures_account()
        balance = 0.0
        equity = 0.0
        for asset in account.get("assets") or []:
            if asset.get("asset") == "USDT":
                balance = float(asset.get("availableBalance") or 0)
                equity = float(asset.get("walletBalance") or 0)
                break
        self.account_data["balance"] = balance
        self.account_data["equity"] = equity
        positions = []
        total_unrealized = 0.0
        for pos in account.get("positions") or []:
            amt = float(pos.get("positionAmt") or 0)
            if amt == 0:
                continue
            unrealized = float(pos.get("unrealizedProfit") or 0)
            total_unrealized += unrealized
            positions.append({
                "symbol": pos.get("symbol"),
                "side": "LONG" if amt > 0 else "SHORT",
                "size": abs(amt),
                "entryPrice": float(pos.get("entryPrice") or 0),
                "markPrice": float(pos.get("markPrice") or 0),
                "unrealizedPnl": unrealized,
                "leverage": int(pos.get("leverage") or 3),
            })
        self.account_data["positions"] = positions
        self.account_data["positionsState"] = (
            "FLAT" if not positions else "OPEN"
        )
        self.account_data["unrealizedPnl"] = total_unrealized

    def fetch_risk_data(self):
        account = self.client.futures_account()
        total_balance = float(account.get("totalWalletBalance") or 0)
        total_unrealized = float(account.get("totalUnrealizedProfit") or 0)
        self.risk_data["dailyPnl"] = total_unrealized
        self.risk_data["totalPnl"] = total_unrealized
        if total_balance > 0:
            drawdown_pct = abs(min(0, total_unrealized)) / total_balance * 100
            self.risk_data["currentDrawdown"] = drawdown_pct
            self.risk_data["maxDrawdown"] = max(
                self.risk_data["maxDrawdown"], drawdown_pct
            )
        if self.risk_data["currentDrawdown"] > 5:
            self.risk_data["status"] = "DANGER"
        elif self.risk_data["currentDrawdown"] > 2:
            self.risk_data["status"] = "WARNING"
        else:
            self.risk_data["status"] = "SAFE"

    def update_pnl_history(self):
        # 账户段未成功采集时，不写入由旧值拼出的假净值点。
        if self.meta["account"]["status"] != "ok":
            return
        self.pnl_data.append({
            "time": datetime.now().isoformat(),
            "pnl": round(self.account_data.get("unrealizedPnl") or 0, 2),
        })
        if len(self.pnl_data) > 100:
            self.pnl_data = self.pnl_data[-100:]

    def fetch_trades(self):
        trades = self.client.futures_account_trades(symbol="BTCUSDT", limit=20)
        self.trade_data = []
        for t in trades:
            self.trade_data.append({
                "id": str(t.get("id", "")),
                "timestamp": datetime.fromtimestamp(t["time"] / 1000).isoformat(),
                "side": t.get("side", ""),
                "entryPrice": float(t.get("price") or 0),
                "quantity": float(t.get("qty") or 0),
                "pnl": float(t.get("realizedPnl") or 0),
            })

    # ---- WS 服务：入站消息一律忽略，绝不转发到 SDK ----

    async def handler(self, websocket, path=None):
        await self.register(websocket)
        try:
            async for _message in websocket:
                pass  # 只读面不解析入站消息；无动态方法转发入口。
        except Exception:
            pass
        finally:
            await self.unregister(websocket)

    async def update_loop(self):
        while True:
            self._run_fetch("market", self.fetch_market_data)
            self._run_fetch("account", self.fetch_account_data)
            self._run_fetch("risk", self.fetch_risk_data)
            self._run_fetch("trades", self.fetch_trades)
            self.update_pnl_history()
            try:
                await self.broadcast(self._envelope("market", "market", self.market_data))
                await self.broadcast(self._envelope("system", "account", self._system_payload()))
                await self.broadcast(self._envelope("risk", "risk", self.risk_data))
                await self.broadcast(json.dumps({"type": "pnl", "payload": self.pnl_data}))
                await self.broadcast(self._envelope("trades", "trades", self.trade_data))
                score = int((self.market_data.get("confidence") or 0) * 100)
                await self.broadcast(json.dumps({"type": "score", "payload": score}))
                print(
                    f"[feed] price={self.market_data['price']} "
                    f"balance={self.account_data['balance']} "
                    f"pos={self.account_data['positionsState']} "
                    f"regime={self.market_data['regime']} "
                    f"status={ {s: self.meta[s]['status'] for s in self.SECTIONS} }",
                    flush=True,
                )
            except Exception as exc:
                print(f"[feed] broadcast failed: {redact(exc)}", flush=True)
            await asyncio.sleep(5)

    async def start(self, origins: Optional[Iterable[str]] = None):
        import websockets

        origins = list(origins) if origins is not None else allowed_origins()
        print(
            f"[feed] read-only ws://{self.host}:{self.port} origins={origins}",
            flush=True,
        )
        async with websockets.serve(self.handler, self.host, self.port, origins=origins):
            await self.update_loop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--env-file",
        default=default_env_file(),
        help="explicit dotenv path; no parent-directory search",
    )
    args = ap.parse_args(argv)

    from aurora.config_source import ConfigSource

    # G0-5A：与 production_main / safety_check / ops 共用同一 ConfigSource，
    # 不再各自加载环境文件，也不改写 os.environ。
    source = ConfigSource.load(env_file=os.path.abspath(args.env_file))
    if not source.loaded_from_disk:
        print(f"[feed] config source: {source.env_file} NOT FOUND; process env only",
              flush=True)

    try:
        feed = DashboardFeed(environ=source.as_environ())
        asyncio.run(feed.start())
    except SafetyViolation as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
