"""AURORA P0 Safety Boundary.

This module is the only trading-adjacent control plane allowed after the
audit freeze. It does not implement strategy. It answers: what mode are we
in, which account, is anyone else trading it, what orders exist, is the
position protected, and what is the real loss state.

LIVE trading requires dual-auth plus an explicit arm token. Dual-auth alone
does not construct a mainnet client or start the execution kernel.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlparse


class SafetyViolation(SystemExit):
    """Refuse to start or continue. Never trade while this is raised."""


class RunMode(str, Enum):
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class HaltState(str, Enum):
    NONE = "NONE"
    HALTED = "HALTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ReconcileStatus(str, Enum):
    MATCHED = "MATCHED"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class PositionQueryKind(str, Enum):
    FLAT = "FLAT"
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


class PositionMode(str, Enum):
    HEDGE = "HEDGE"
    ONE_WAY = "ONE_WAY"


MAINNET_MARK = "fapi.binance.com"
TESTNET_MARK = "testnet"
ALLOWED_LIVE_HOSTS = frozenset({"fapi.binance.com"})
# P1-GOV-3 live-endpoint-v1：构造期需经现货 ping 主机；只在完整
# LIVE 授权事实下由 live_endpoint_contract 激活（默认集不变）。
LIVE_CONSTRUCTION_HOSTS = frozenset(
    {"api.binance.com", "fapi.binance.com"})
ALLOWED_TESTNET_HOSTS = frozenset({
    "testnet.binancefuture.com",
    "testnet.binance.vision",
})
LEGACY_TESTNET_TRUTHY = frozenset({"true", "1", "yes", "on"})
LEGACY_TESTNET_FALSY = frozenset({"false", "0", "no", "off"})
LIVE_ARM_TOKEN = "I_ARM_LIVE_EXECUTION"
VALID_MODES = tuple(m.value for m in RunMode)
RECONCILE_TRIGGERS = (
    "boot",
    "before_open",
    "order_unknown",
    "after_open",
    "after_close",
    "after_cancel",
    "exchange_event",
    "ws_reconnect",
    "timer",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def resolve_mode(environ: Optional[Dict[str, str]] = None) -> RunMode:
    get = (environ or os.environ).get
    raw = (get("TRADING_MODE") or "").strip().upper()
    if raw == "":
        return RunMode.PAPER
    if raw not in VALID_MODES:
        raise SafetyViolation(
            f"[P0] unknown TRADING_MODE={raw!r}; allowed={VALID_MODES}. refuse start."
        )
    legacy = (get("TESTNET") or "").strip().lower()
    if legacy:
        if legacy not in LEGACY_TESTNET_TRUTHY | LEGACY_TESTNET_FALSY:
            raise SafetyViolation(
                f"[P0] unknown TESTNET={legacy!r}; "
                "allowed=true/1/yes/on/false/0/no/off. refuse start."
            )
        if raw != RunMode.PAPER.value:
            expect_truthy = raw in (RunMode.TESTNET.value, RunMode.SHADOW.value)
            is_truthy = legacy in LEGACY_TESTNET_TRUTHY
            if is_truthy != expect_truthy:
                raise SafetyViolation(
                    f"[P0] config conflict: TRADING_MODE={raw} vs TESTNET={legacy}. refuse start."
                )
    return RunMode(raw)


def assert_live_dual_auth(environ: Optional[Dict[str, str]] = None) -> None:
    """P0-03: a single env var must never enable live."""
    src = environ or os.environ
    mode = resolve_mode(src if environ is not None else None)
    if mode != RunMode.LIVE:
        raise SafetyViolation("[P0] live gates only apply to TRADING_MODE=LIVE.")
    allow = (src.get("ALLOW_LIVE_TRADING") or "").strip().lower()
    confirm = (src.get("AURORA_LIVE_CONFIRM") or "").strip()
    if allow != "true":
        raise SafetyViolation("[P0] LIVE requires ALLOW_LIVE_TRADING=true.")
    if confirm != "I_UNDERSTAND_LIVE_RISK":
        raise SafetyViolation("[P0] LIVE requires AURORA_LIVE_CONFIRM=I_UNDERSTAND_LIVE_RISK.")


def live_execution_armed(environ: Optional[Dict[str, str]] = None) -> bool:
    src = environ if environ is not None else os.environ
    return (src.get("AURORA_ARM_LIVE") or "").strip() == LIVE_ARM_TOKEN


def assert_not_live_trading(mode: RunMode, environ: Optional[Dict[str, str]] = None) -> None:
    """Refuse LIVE unless dual-auth already passed *and* the arm token is set.

    Dual-auth alone is not enough: that only proves the gates work.
    """
    if mode != RunMode.LIVE:
        return
    if not live_execution_armed(environ):
        raise SafetyViolation(
            "[P0] LIVE remains NO-GO until AURORA_ARM_LIVE=I_ARM_LIVE_EXECUTION. "
            "Dual-auth does not start trading."
        )


def _endpoint_host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower()


def assert_endpoint(url: str, mode: RunMode) -> None:
    if mode == RunMode.PAPER:
        raise SafetyViolation("[P0] PAPER must not attach any exchange endpoint.")
    host = _endpoint_host(url)
    if not host:
        raise SafetyViolation(f"[P0] {mode.value} endpoint missing hostname: {url}")
    if mode in (RunMode.TESTNET, RunMode.SHADOW):
        if host not in ALLOWED_TESTNET_HOSTS:
            raise SafetyViolation(f"[P0] {mode.value} endpoint is not testnet: {url}")
        return
    if mode == RunMode.LIVE:
        if host not in ALLOWED_LIVE_HOSTS:
            raise SafetyViolation(f"[P0] LIVE endpoint is not mainnet: {url}")
        return


def effective_futures_url(client: Any) -> str:
    """USDS-M URL python-binance will actually request.

    Client.FUTURES_URL stays on fapi.binance.com even when testnet=True;
    futures calls then switch to FUTURES_TESTNET_URL.
    """
    if getattr(client, "testnet", False) is True:
        return str(getattr(client, "FUTURES_TESTNET_URL", "") or "")
    return str(getattr(client, "FUTURES_URL", "") or "")


def assert_client_endpoint(client: Any, mode: RunMode) -> None:
    flagged = getattr(client, "testnet", False) is True
    if mode == RunMode.LIVE and flagged:
        raise SafetyViolation("[P0] LIVE client is flagged testnet.")
    if mode in (RunMode.TESTNET, RunMode.SHADOW) and not flagged:
        raise SafetyViolation(f"[P0] {mode.value} client is not flagged testnet.")
    assert_endpoint(effective_futures_url(client), mode)


def assert_strict_url_allowed(url: str, allowed: frozenset, mode: RunMode) -> None:
    """对解析完成的 URL 做严格出站校验，不只是 hostname 子串匹配。

    要求：https scheme、精确 hostname 命中允许列表、无 URL 用户信息、
    端口为缺省或 443。任一不满足即在出站/构造前拒绝。
    """
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise SafetyViolation(f"[P0] {mode.value} endpoint is not https: {raw[:80]}")
    if parsed.username is not None or parsed.password is not None:
        raise SafetyViolation(f"[P0] {mode.value} endpoint carries userinfo: {raw[:80]}")
    try:
        port = parsed.port
    except ValueError:
        raise SafetyViolation(f"[P0] {mode.value} endpoint port invalid: {raw[:80]}")
    if port not in (None, 443):
        raise SafetyViolation(f"[P0] {mode.value} endpoint port not allowed: {raw[:80]}")
    host = (parsed.hostname or "").lower()
    if host not in allowed:
        raise SafetyViolation(
            f"[P0] {mode.value} endpoint host not in allowlist: {host or 'no-host'}"
        )


def assert_client_construction_targets(client_cls: Any, mode: RunMode) -> None:
    """在实例化 SDK Client 之前校验其构造期与后续请求的出站目标。

    python-binance 1.0.19 的 Client.__init__ 会立即 ping spot API（testnet
    时目标为 API_TESTNET_URL），期货请求另走 FUTURES_TESTNET_URL；因此只
    在构造后检查 futures URL 不足以覆盖构造期网络行为。校验使用与真实
    构造参数一致解析完成的 URL（tld='com'、base_endpoint 取类默认值），
    而非仅检查类常量模板。

    LIVE：构造期 spot ping 目标按正向白名单校验；ALLOWED_LIVE_HOSTS 未包含
    主网 spot 主机，因此当前策略下 LIVE 即使授权齐全也在构造前拒绝——
    这是策略不满足的明确报告点，不是授权语义的变更。
    """
    if mode in (RunMode.TESTNET, RunMode.SHADOW):
        urls = (
            str(getattr(client_cls, "API_TESTNET_URL", "") or ""),
            str(getattr(client_cls, "FUTURES_TESTNET_URL", "") or ""),
        )
        allowed = ALLOWED_TESTNET_HOSTS
    elif mode == RunMode.LIVE:
        tld = "com"
        base = str(getattr(client_cls, "BASE_ENDPOINT_DEFAULT", "") or "")
        urls = (
            str(getattr(client_cls, "API_URL", "") or "").format(base, tld),
            str(getattr(client_cls, "FUTURES_URL", "") or "").format(tld),
        )
        allowed = ALLOWED_LIVE_HOSTS
    else:
        raise SafetyViolation(f"[P0] {mode.value} must not construct an exchange client.")
    for url in urls:
        assert_strict_url_allowed(url, allowed, mode)


def install_outbound_guard(client: Any, mode: RunMode) -> None:
    """在会话出站入口（session.send）强制模式允许列表并禁止重定向。

    requests 的每一次会话发送都经过 Session.send，任何跳转也只会以一次新的
    send 出现；目标 host 不在允许列表时在出站前抛 SafetyViolation，而不是
    先发出再报错。重定向是强制规则：调用方显式 allow_redirects=True 直接
    拒绝，缺省（Session.send 默认 True）统一强制为 False——因为 SDK 的
    per-request requests_params 可以在全局参数之后覆盖它。

    本守卫仅针对锁定的 SDK/Requests 版本验证过；升级或更换传输路径必须
    重新通过契约测试。此处不引入对 requests 的依赖，仅包装实例方法。
    """
    allowed = (
        ALLOWED_TESTNET_HOSTS
        if mode in (RunMode.TESTNET, RunMode.SHADOW)
        else ALLOWED_LIVE_HOSTS
    )
    session = getattr(client, "session", None)
    if session is None:
        raise SafetyViolation("[P0] exchange client has no transport session to guard.")
    if getattr(session, "_aurora_guarded", False) is True:
        return
    raw_send = session.send

    def _guarded_send(request: Any, **kwargs: Any) -> Any:
        host = _endpoint_host(getattr(request, "url", "") or "")
        if host not in allowed:
            raise SafetyViolation(
                f"[P0] {mode.value} outbound blocked before send: {host or 'no-host'}"
            )
        if kwargs.get("allow_redirects") is True:
            raise SafetyViolation(
                f"[P0] {mode.value} caller re-enabled redirects; refused before send."
            )
        kwargs["allow_redirects"] = False
        return raw_send(request, **kwargs)

    session.send = _guarded_send
    session._aurora_guarded = True


def resolve_account_fingerprint(mode: RunMode, api_key: str, environ: Optional[Dict[str, str]] = None) -> str:
    src = environ or os.environ
    if mode == RunMode.PAPER:
        return "paper-local"
    if not api_key:
        raise SafetyViolation("[P0] missing BINANCE_API_KEY; refuse start.")
    fp = key_fingerprint(api_key)
    expected = (src.get("AURORA_ACCOUNT_FINGERPRINT") or "").strip().lower()
    if not expected:
        raise SafetyViolation("[P0] missing AURORA_ACCOUNT_FINGERPRINT; refuse start.")
    if fp != expected:
        raise SafetyViolation("[P0] account fingerprint mismatch; refuse start.")
    if mode == RunMode.LIVE:
        live_fp = (src.get("AURORA_LIVE_KEY_SHA256") or "").strip().lower()
        if not live_fp:
            raise SafetyViolation("[P0] LIVE missing AURORA_LIVE_KEY_SHA256.")
        if live_fp != fp:
            raise SafetyViolation("[P0] LIVE key fingerprint mismatch.")
    return fp


@dataclass
class PositionSnapshot:
    kind: PositionQueryKind
    side: str = "FLAT"
    size: float = 0.0
    entry_price: float = 0.0
    protect_sl_id: Optional[str] = None
    protect_tp_id: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.kind == PositionQueryKind.OPEN and self.size > 0


@dataclass
class BrainPosition:
    is_open: bool = False
    side: str = "FLAT"
    size: float = 0.0
    entry_price: float = 0.0


# G0-5D：OrderRecord / SafeExecutor 已迁往 aurora/legacy_safe_executor.py
# （OFFLINE_REFERENCE_ONLY）。生产执行路径不得引用；禁入守卫见
# tests/test_g05_identity_isolation.py。


@dataclass
class SafetyStore:
    halt: HaltState = HaltState.NONE
    halt_reason: str = ""
    kill_switch: bool = False
    kill_reason: str = ""
    daily_pnl: float = 0.0
    drawdown: float = 0.0
    pending_orders: List[Dict[str, Any]] = field(default_factory=list)
    close_failed: bool = False
    account_fingerprint: str = ""
    brain: BrainPosition = field(default_factory=BrainPosition)
    last_reconcile: str = ReconcileStatus.UNKNOWN.value
    account_identity: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["halt"] = self.halt.value
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafetyStore":
        brain = data.get("brain") or {}
        return cls(
            halt=HaltState(data.get("halt", HaltState.NONE.value)),
            halt_reason=data.get("halt_reason", ""),
            kill_switch=bool(data.get("kill_switch", False)),
            kill_reason=data.get("kill_reason", ""),
            daily_pnl=float(data.get("daily_pnl", 0.0)),
            drawdown=float(data.get("drawdown", 0.0)),
            pending_orders=list(data.get("pending_orders") or []),
            close_failed=bool(data.get("close_failed", False)),
            account_fingerprint=data.get("account_fingerprint", ""),
            brain=BrainPosition(
                is_open=bool(brain.get("is_open", False)),
                side=brain.get("side", "FLAT"),
                size=float(brain.get("size", 0.0)),
                entry_price=float(brain.get("entry_price", 0.0)),
            ),
            last_reconcile=data.get("last_reconcile", ReconcileStatus.UNKNOWN.value),
            account_identity=dict(data.get("account_identity") or {}),
            updated_at=data.get("updated_at", utc_now()),
        )


class Persistence:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> SafetyStore:
        if not os.path.exists(self.path):
            return SafetyStore()
        try:
            with open(self.path, "r") as fh:
                return SafetyStore.from_dict(json.load(fh))
        except Exception as exc:
            raise SafetyViolation(f"[P0] safety state unreadable ({exc}); refuse start.")

    def save(self, store: SafetyStore) -> None:
        store.updated_at = utc_now()
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(store.to_dict(), fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception as exc:
            raise SafetyViolation(f"[P0] safety state persist failed ({exc}); refuse continue.")


class AccountLock:
    """Account-fingerprint lock. Two processes cannot control the same account."""

    def __init__(self, lock_dir: str, fingerprint: str):
        self.lock_dir = lock_dir
        self.fingerprint = fingerprint
        self.path = os.path.join(lock_dir, f"{fingerprint}.lock")
        self._fh = None

    def acquire(self) -> None:
        os.makedirs(self.lock_dir, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SafetyViolation(
                f"[P0] account lock held for fingerprint={self.fingerprint}; refuse start."
            ) from exc
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "fingerprint": self.fingerprint,
            "acquired_at": utc_now(),
        }))
        self._fh.flush()

    def release(self) -> None:
        if self._fh:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
            except Exception:
                pass
            self._fh = None


class BrokerError(Exception):
    pass


class Broker(Protocol):
    futures_url: str

    def account(self) -> Dict[str, Any]: ...
    def get_position_mode(self) -> PositionMode: ...
    def get_position(self, symbol: str) -> PositionSnapshot: ...
    def create_order(self, **params: Any) -> Dict[str, Any]: ...
    def get_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]: ...
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]: ...
    def open_orders(self, symbol: str) -> List[Dict[str, Any]]: ...


@dataclass
class ReconcileResult:
    status: ReconcileStatus
    trigger: str
    reason: str
    exchange: PositionSnapshot
    brain: BrainPosition


def reconcile(store: SafetyStore, exchange: PositionSnapshot, trigger: str) -> ReconcileResult:
    if trigger not in RECONCILE_TRIGGERS:
        raise SafetyViolation(f"[P0] unknown reconcile trigger: {trigger}")
    if store.halt == HaltState.RECOVERY_REQUIRED:
        result = ReconcileResult(
            ReconcileStatus.RECOVERY_REQUIRED, trigger, store.halt_reason, exchange, store.brain
        )
        store.last_reconcile = result.status.value
        return result
    if exchange.kind == PositionQueryKind.UNKNOWN:
        result = ReconcileResult(
            ReconcileStatus.UNKNOWN, trigger, "position query failed", exchange, store.brain
        )
        store.last_reconcile = result.status.value
        return result

    if exchange.kind == PositionQueryKind.FLAT:
        if store.brain.is_open:
            store.brain = BrainPosition()
            reason = "exchange flat; cleared brain ghost (SL/TP or external close)"
        else:
            reason = "both flat"
        result = ReconcileResult(ReconcileStatus.MATCHED, trigger, reason, exchange, store.brain)
        store.last_reconcile = result.status.value
        return result

    if not store.brain.is_open:
        result = ReconcileResult(
            ReconcileStatus.DRIFT_DETECTED,
            trigger,
            "exchange open, brain flat; will not auto-open",
            exchange,
            store.brain,
        )
        store.last_reconcile = result.status.value
        return result

    same_side = store.brain.side == exchange.side
    same_size = abs(store.brain.size - exchange.size) <= 0.001
    if same_side and same_size:
        result = ReconcileResult(ReconcileStatus.MATCHED, trigger, "positions match", exchange, store.brain)
        store.last_reconcile = result.status.value
        return result
    result = ReconcileResult(
        ReconcileStatus.DRIFT_DETECTED, trigger, "side or size mismatch", exchange, store.brain
    )
    store.last_reconcile = result.status.value
    return result


def query_position(broker: Broker, symbol: str) -> PositionSnapshot:
    try:
        snap = broker.get_position(symbol)
    except Exception:
        return PositionSnapshot(kind=PositionQueryKind.UNKNOWN)
    if snap is None or getattr(snap, "kind", None) is None:
        return PositionSnapshot(kind=PositionQueryKind.UNKNOWN)
    return snap


def can_open(store: SafetyStore, rec: ReconcileResult) -> bool:
    if store.halt != HaltState.NONE:
        return False
    if store.kill_switch:
        return False
    if store.close_failed:
        return False
    return rec.status == ReconcileStatus.MATCHED


# G0-5D：SafeExecutor 迁往 aurora/legacy_safe_executor.py（OFFLINE_REFERENCE_ONLY）。
# 生产执行路径不得实例化；第二套保护语义就此失去成为生产路径的机会。

def verify_position_mode(broker: Broker, expected: PositionMode) -> PositionMode:
    try:
        actual = broker.get_position_mode()
    except Exception as exc:
        raise SafetyViolation(f"[P0] position mode read failed ({exc}); refuse start.")
    if actual != expected:
        raise SafetyViolation(
            f"[P0] position mode {actual.value} != declared {expected.value}. "
            "process will not change account mode; use aurora.ops_position_mode."
        )
    return actual


def restore_or_refuse(persist: Persistence) -> SafetyStore:
    store = persist.load()
    if store.halt in (HaltState.HALTED, HaltState.RECOVERY_REQUIRED):
        raise SafetyViolation(
            f"[P0] persisted {store.halt.value}: {store.halt_reason}. restart cannot clear this."
        )
    if store.kill_switch:
        raise SafetyViolation(f"[P0] persisted kill switch: {store.kill_reason}. refuse start.")
    return store


@dataclass
class BootContext:
    mode: RunMode
    fingerprint: str
    store: SafetyStore
    persist: Persistence
    lock: AccountLock
    broker: Optional[Broker]
    executor: Optional[Any] = None  # G0-5D：恒为 None；旧 SafeExecutor 已退休
    status: str = "SAFE_IDLE"


def expected_position_mode(environ: Optional[Dict[str, str]] = None) -> PositionMode:
    raw = ((environ or os.environ).get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE").strip().upper()
    if raw not in ("HEDGE", "ONE_WAY"):
        raise SafetyViolation(f"[P0] invalid AURORA_EXPECTED_POSITION_MODE={raw}")
    return PositionMode(raw)


def boot(
    persist_path: str,
    lock_dir: str,
    broker: Optional[Broker] = None,
    environ: Optional[Dict[str, str]] = None,
    symbol: str = "BTCUSDT",
) -> BootContext:
    """Safe production boot. Any step fails => no trading loop."""
    src = environ or os.environ
    mode = resolve_mode(src if environ is not None else None)
    api_key = (src.get("BINANCE_API_KEY") or "").strip()

    if mode == RunMode.LIVE:
        assert_live_dual_auth(src)
        resolve_account_fingerprint(mode, api_key, src)
        if broker is not None:
            assert_endpoint(broker.futures_url, mode)
        assert_not_live_trading(mode, src)

    if mode != RunMode.PAPER and broker is None:
        raise SafetyViolation(f"[P0] {mode.value} boot requires an injected or live broker.")
    if mode == RunMode.PAPER and broker is not None:
        raise SafetyViolation("[P0] PAPER must not receive an exchange broker.")

    fp = resolve_account_fingerprint(mode, api_key, src)
    lock = AccountLock(lock_dir, fp)
    lock.acquire()

    persist = Persistence(persist_path)
    store = restore_or_refuse(persist)
    if store.account_fingerprint and store.account_fingerprint != fp:
        raise SafetyViolation("[P0] persisted fingerprint does not match this account.")
    store.account_fingerprint = fp

    # G0-5C：账户身份绑定与漂移 fail-closed。任何环境/指纹/持仓模式/
    # 交易所主机/独占性变化都必须被显式处置，不能静默沿用旧身份。
    identity = build_account_identity(
        mode=mode,
        fingerprint=fp,
        position_mode=expected_position_mode(src),
        exchange_host=_endpoint_host(broker.futures_url) if broker is not None else "",
        account_exclusivity=(src.get("AURORA_ACCOUNT_EXCLUSIVITY") or "false")
        .strip().lower() in ("true", "1", "yes", "on"),
    )
    check_account_identity_drift(store, identity)
    store.account_identity = identity
    persist.save(store)

    if broker is not None:
        assert_endpoint(broker.futures_url, mode)
        try:
            broker.account()
        except Exception as exc:
            raise SafetyViolation(f"[P0] account probe failed: {exc}")
        verify_position_mode(broker, expected_position_mode(src))
        exchange = query_position(broker, symbol)
        rec = reconcile(store, exchange, "boot")
        if rec.status not in (ReconcileStatus.MATCHED, ReconcileStatus.DRIFT_DETECTED):
            raise SafetyViolation(f"[P0] boot reconcile {rec.status.value}: {rec.reason}")
        if rec.status == ReconcileStatus.DRIFT_DETECTED:
            store.halt = HaltState.RECOVERY_REQUIRED
            store.halt_reason = f"boot drift: {rec.reason}"
            persist.save(store)
            raise SafetyViolation(f"[P0] boot drift requires recovery: {rec.reason}")

    return BootContext(
        mode=mode,
        fingerprint=fp,
        store=store,
        persist=persist,
        lock=lock,
        broker=broker,
        executor=None,
        status="SAFE_IDLE",
    )


def build_account_identity(
    mode: RunMode,
    fingerprint: str,
    position_mode: PositionMode,
    exchange_host: str,
    account_exclusivity: bool,
) -> Dict[str, Any]:
    """G0-5C：账户身份五要素 + 独占性声明 + 稳定哈希。

    ACCOUNT_EXCLUSIVITY 当前冻结为 FALSE（共享测试网账户是已登记事实）：
    账户级状态不得自动解释为 AURORA 独占事实。
    """
    identity = {
        "mode": mode.value,
        "account_fingerprint": fingerprint,
        "position_mode": position_mode.value,
        "exchange_host": exchange_host,
        "account_exclusivity": bool(account_exclusivity),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    identity["identity_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return identity


def check_account_identity_drift(store: SafetyStore, identity: Dict[str, Any]) -> None:
    """持久化身份存在且不一致 → ACCOUNT_IDENTITY_DRIFT，拒启。"""
    stored = store.account_identity or {}
    if not stored:
        return  # 首次引导：写入身份（旧状态文件无身份块不算漂移）
    if stored.get("identity_hash") != identity.get("identity_hash"):
        changed = [
            k for k in identity
            if k != "identity_hash" and stored.get(k) != identity.get(k)
        ]
        raise SafetyViolation(
            "[P0] ACCOUNT_IDENTITY_DRIFT: stored="
            f"{stored.get('identity_hash')} current={identity.get('identity_hash')}"
            f" changed={changed}; explicit disposition required."
        )


def state_root() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state")


def namespaced_state_dir(mode: RunMode, fingerprint: str) -> str:
    """G0-5B：state/<mode>/<fingerprint>/ 物理状态命名空间。

    PAPER ≠ TESTNET ≠ LIVE 不仅逻辑不同，状态文件物理隔离。
    """
    if not fingerprint:
        raise SafetyViolation("[P0] state namespace requires account fingerprint.")
    return os.path.join(state_root(), mode.value.lower(), fingerprint)


def namespaced_state_path(mode: RunMode, fingerprint: str) -> str:
    return os.path.join(namespaced_state_dir(mode, fingerprint), "p0_safety.json")


def namespaced_lock_dir(mode: RunMode, fingerprint: str) -> str:
    return os.path.join(namespaced_state_dir(mode, fingerprint), "locks")


def default_state_path() -> str:
    """遗留（事故封存）路径：state/p0_safety.json。新引导一律走
    namespaced_state_path()；本函数仅保留给归档工具与旧测试。"""
    return os.path.join(state_root(), "p0_safety.json")


def default_lock_dir() -> str:
    return os.path.join(state_root(), "locks")
