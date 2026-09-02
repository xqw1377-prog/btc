"""AURORA P0 Safety Boundary.

This module is the only trading-adjacent control plane allowed after the
audit freeze. It does not implement strategy. It answers: what mode are we
in, which account, is anyone else trading it, what orders exist, is the
position protected, and what is the real loss state.

LIVE trading is intentionally impossible here. Passing dual-auth only proves
the gates work; production_main still refuses to enter a live loop.
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


class OrderState(str, Enum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    FILLED = "FILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PositionMode(str, Enum):
    HEDGE = "HEDGE"
    ONE_WAY = "ONE_WAY"


MAINNET_MARK = "fapi.binance.com"
TESTNET_MARK = "testnet"
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
    if legacy in ("true", "false") and raw != RunMode.PAPER.value:
        expected = "true" if raw == RunMode.TESTNET.value else "false"
        if raw == RunMode.SHADOW.value:
            expected = "true"
        if legacy != expected:
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


def assert_not_live_trading(mode: RunMode) -> None:
    if mode == RunMode.LIVE:
        raise SafetyViolation(
            "[P0] LIVE remains NO-GO in the Safety Boundary. Dual-auth does not start trading."
        )


def assert_endpoint(url: str, mode: RunMode) -> None:
    lowered = (url or "").lower()
    if mode in (RunMode.TESTNET, RunMode.SHADOW) and TESTNET_MARK not in lowered:
        raise SafetyViolation(f"[P0] {mode.value} endpoint is not testnet: {url}")
    if mode == RunMode.LIVE and MAINNET_MARK not in lowered:
        raise SafetyViolation(f"[P0] LIVE endpoint is not mainnet: {url}")
    if mode == RunMode.PAPER:
        raise SafetyViolation("[P0] PAPER must not attach any exchange endpoint.")
    if mode != RunMode.LIVE and MAINNET_MARK in lowered and TESTNET_MARK not in lowered:
        raise SafetyViolation(f"[P0] {mode.value} refused mainnet endpoint: {url}")


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


@dataclass
class OrderRecord:
    client_order_id: str
    state: OrderState
    side: str
    quantity: float
    reduce_only: bool = False
    order_type: str = "MARKET"
    exchange_order_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)


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


class SafeExecutor:
    def __init__(self, broker: Broker, store: SafetyStore, persist: Persistence, symbol: str = "BTCUSDT"):
        self.broker = broker
        self.store = store
        self.persist = persist
        self.symbol = symbol
        self.orders: Dict[str, OrderRecord] = {}
        self.cancel_all_calls = 0

    def _cid(self, prefix: str) -> str:
        return f"AURORA_{prefix}_{uuid.uuid4().hex[:8]}"

    def _place(self, client_order_id: str, **params: Any) -> OrderRecord:
        existing = self.orders.get(client_order_id)
        if existing and existing.state == OrderState.FILLED:
            return existing
        record = existing or OrderRecord(
            client_order_id=client_order_id,
            state=OrderState.PENDING,
            side=params.get("side", ""),
            quantity=float(params.get("quantity", 0)),
            reduce_only=bool(params.get("reduceOnly", False)),
            order_type=params.get("type", "MARKET"),
        )
        self.orders[client_order_id] = record
        try:
            raw = self.broker.create_order(symbol=self.symbol, newClientOrderId=client_order_id, **params)
            record.state = OrderState.FILLED
            record.exchange_order_id = str(raw.get("orderId", client_order_id))
        except Exception as exc:
            try:
                seen = self.broker.get_order(self.symbol, client_order_id)
                if seen.get("status") in ("FILLED", "NEW", "PARTIALLY_FILLED"):
                    record.state = OrderState.FILLED if seen.get("status") == "FILLED" else OrderState.ACKED
                    record.exchange_order_id = str(seen.get("orderId", client_order_id))
                    return record
            except Exception:
                record.state = OrderState.UNKNOWN
                record.error = str(exc)
                return record
            record.state = OrderState.FAILED
            record.error = str(exc)
        return record

    def cancel_order(self, order_id: str) -> None:
        if not order_id:
            raise SafetyViolation("[P0] refuse cancel without exact order id.")
        self.broker.cancel_order(self.symbol, order_id)

    def cancel_all_orders(self) -> None:
        self.cancel_all_calls += 1
        raise SafetyViolation("[P0] cancel-all is forbidden; cancel by order id only.")

    def reconcile(self, trigger: str) -> ReconcileResult:
        exchange = query_position(self.broker, self.symbol)
        result = reconcile(self.store, exchange, trigger)
        self.persist.save(self.store)
        return result

    def execute_open(self, side: str, quantity: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        rec = self.reconcile("before_open")
        if not can_open(self.store, rec):
            return {"success": False, "reason": f"open blocked: halt={self.store.halt.value} rec={rec.status.value} close_failed={self.store.close_failed}"}

        open_cid = self._cid("OPEN")
        order_side = "BUY" if side == "LONG" else "SELL"
        opened = self._place(
            open_cid,
            side=order_side,
            positionSide=side,
            type="MARKET",
            quantity=quantity,
            reduceOnly=False,
        )
        if opened.state == OrderState.UNKNOWN:
            self.reconcile("order_unknown")
            return {"success": False, "reason": "open result UNKNOWN", "client_order_id": open_cid}
        if opened.state != OrderState.FILLED:
            return {"success": False, "reason": opened.error or "open failed", "client_order_id": open_cid}

        self.store.brain = BrainPosition(True, side, quantity, 0.0)
        self.store.pending_orders.append({"id": open_cid, "type": "OPEN"})
        self.persist.save(self.store)

        protect = self._confirm_protection(side, quantity, stop_loss, take_profit)
        self.reconcile("after_open")
        return protect

    def _confirm_protection(self, side: str, quantity: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        close_side = "SELL" if side == "LONG" else "BUY"
        sl_cid = self._cid("SL")
        tp_cid = self._cid("TP")
        sl = self._place(
            sl_cid, side=close_side, positionSide=side, type="STOP_MARKET",
            quantity=quantity, stopPrice=stop_loss, reduceOnly=True,
        )
        tp = self._place(
            tp_cid, side=close_side, positionSide=side, type="TAKE_PROFIT_MARKET",
            quantity=quantity, stopPrice=take_profit, reduceOnly=True,
        )
        sl_ok = self._protection_confirmed(sl)
        tp_ok = self._protection_confirmed(tp)
        if sl_ok and tp_ok:
            self.store.pending_orders.extend([
                {"id": sl_cid, "type": "SL"},
                {"id": tp_cid, "type": "TP"},
            ])
            self.persist.save(self.store)
            return {"success": True, "sl": sl_cid, "tp": tp_cid}

        return self._emergency_flatten("protection unconfirmed")

    def _protection_confirmed(self, record: OrderRecord) -> bool:
        if record.state not in (OrderState.FILLED, OrderState.ACKED):
            return False
        try:
            seen = self.broker.get_order(self.symbol, record.client_order_id)
        except Exception:
            return False
        return seen.get("status") in ("NEW", "FILLED", "PARTIALLY_FILLED")

    def _emergency_flatten(self, reason: str) -> Dict[str, Any]:
        pos = query_position(self.broker, self.symbol)
        if pos.kind == PositionQueryKind.UNKNOWN:
            self.store.halt = HaltState.RECOVERY_REQUIRED
            self.store.halt_reason = f"{reason}; flatten position UNKNOWN"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        if pos.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.halt = HaltState.HALTED
            self.store.halt_reason = f"{reason}; already flat"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        flatten_cid = self._cid("FLAT")
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        flat = self._place(
            flatten_cid,
            side=close_side,
            positionSide=pos.side,
            type="MARKET",
            quantity=pos.size,
            reduceOnly=True,
        )
        confirm = query_position(self.broker, self.symbol)
        if confirm.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.halt = HaltState.HALTED
            self.store.halt_reason = f"{reason}; emergency reduceOnly flattened"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        self.store.halt = HaltState.RECOVERY_REQUIRED
        self.store.halt_reason = (
            f"{reason}; flatten state={flat.state.value} confirm={confirm.kind.value}"
        )
        self.persist.save(self.store)
        return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

    def execute_close(self) -> Dict[str, Any]:
        pos = query_position(self.broker, self.symbol)
        if pos.kind == PositionQueryKind.UNKNOWN:
            self.store.close_failed = True
            self.persist.save(self.store)
            return {"success": False, "reason": "close blocked: position UNKNOWN"}
        if pos.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.close_failed = False
            self.persist.save(self.store)
            self.reconcile("after_close")
            return {"success": True, "reason": "already flat"}

        cid = self._cid("CLOSE")
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        closed = self._place(
            cid, side=close_side, positionSide=pos.side, type="MARKET",
            quantity=pos.size, reduceOnly=True,
        )
        confirm = query_position(self.broker, self.symbol)
        if closed.state == OrderState.FILLED and confirm.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.close_failed = False
            self.persist.save(self.store)
            self.reconcile("after_close")
            return {"success": True, "client_order_id": cid}

        self.store.close_failed = True
        self.persist.save(self.store)
        return {"success": False, "reason": "close unconfirmed; reverse open forbidden"}


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
    executor: Optional[SafeExecutor]
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
        assert_not_live_trading(mode)

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
    persist.save(store)

    executor = None
    if broker is not None:
        assert_endpoint(broker.futures_url, mode)
        try:
            broker.account()
        except Exception as exc:
            raise SafetyViolation(f"[P0] account probe failed: {exc}")
        verify_position_mode(broker, expected_position_mode(src))
        executor = SafeExecutor(broker, store, persist, symbol)
        rec = executor.reconcile("boot")
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
        executor=executor,
        status="SAFE_IDLE",
    )


def default_state_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state", "p0_safety.json")


def default_lock_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state", "locks")
