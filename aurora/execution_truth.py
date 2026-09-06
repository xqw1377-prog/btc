"""P0-B1 Durable Execution Truth.

ADR-013 status: OFFLINE REFERENCE IMPLEMENTATION ONLY. Tracked for its
Decimal accounting and execution invariants. It is NOT a production execution
engine (aurora/kernel/ is the only production execution kernel), must never be
imported by production runtime, and its tests must not be cited as proof of
production safety or execution correctness. `reconcile()`/`boot()` depend on a
Reconciler that was never built — that path is explicitly NOT-BUILT; see
docs/baseline/reference_tests/DISPOSITION.md.

This module is the first executable layer of the AURORA post-audit recovery.
It does not implement strategy. It implements the guarantee that no order,
fill, kill switch, or position state can be lost across restarts, timeouts,
partial fills, or exchange query failures.

Design principles
-----------------
1. The exchange is the external source of market fact.
2. The SQLite WAL ledger is the internal source of intent, order life-cycle,
   fill, fee, funding and kill-switch history.
3. The local PositionTruth is a projection rebuilt from the ledger and
   cross-checked against the exchange at every critical step.
4. When the two cannot be reconciled, the system enters UNKNOWN and halts.
5. No real Binance order is placed unless an `ExchangePort` is explicitly
   wired. `FakeExchange` is the default for offline P0-B1 tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

D_QTY = Decimal("0.000001")
D_PRICE = Decimal("0.01")
D_PNL = Decimal("0.0001")

_Q = lambda x: Decimal(str(x)).quantize(D_QTY)
_P = lambda x: Decimal(str(x)).quantize(D_PRICE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cid(intent_id: str, attempt: int, suffix: str = "") -> str:
    base = f"AURORA_{intent_id}_{attempt:03d}"
    if suffix:
        base = f"{base}_{suffix}"
    return base


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class IntentType(Enum):
    OPEN = "OPEN"
    FLAT = "FLAT"
    PROTECT = "PROTECT"
    CANCEL = "CANCEL"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"
    QUERY_UNKNOWN = "QUERY_UNKNOWN"


class PositionState(Enum):
    KNOWN_FLAT = "KNOWN_FLAT"
    KNOWN_OPEN = "KNOWN_OPEN"
    UNKNOWN = "UNKNOWN"


class IntentState(Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class FillRecord:
    client_order_id: str
    exchange_fill_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    side: str
    timestamp: str


@dataclass
class OrderRecord:
    client_order_id: str
    intent_id: str
    exchange_order_id: Optional[str]
    side: str
    position_side: str
    order_type: str
    quantity: Decimal
    reduce_only: bool
    status: OrderStatus
    avg_price: Optional[Decimal]
    filled_qty: Decimal
    remaining_qty: Decimal
    fee: Decimal
    stop_price: Optional[Decimal]
    submit_attempt: int
    created_at: str
    updated_at: str
    error: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        )


@dataclass
class IntentRecord:
    intent_id: str
    intent_type: IntentType
    symbol: str
    side: Side
    quantity: Decimal
    price: Optional[Decimal]
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    state: IntentState
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PositionRecord:
    state: PositionState
    side: Side
    size: Decimal
    cost_basis: Decimal
    avg_entry: Decimal
    realized_pnl: Decimal
    fees: Decimal
    last_intent_id: Optional[str]
    last_order_id: Optional[str]
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    updated_at: str = field(default_factory=_now)


@dataclass
class PnLRecord:
    session_id: str
    realized_pnl: Decimal
    fees: Decimal
    funding: Decimal
    opened_at: str
    closed_at: str


class StateTransitionError(Exception):
    pass


class OrderStateMachine:
    """Valid order status transitions for the P0-B1 durable execution truth."""

    TERMINAL = {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
    }

    ALLOWED = {
        OrderStatus.PENDING: {
            OrderStatus.SUBMITTED,
            OrderStatus.ACKED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.SUBMIT_UNKNOWN,
            OrderStatus.QUERY_UNKNOWN,
        },
        OrderStatus.SUBMITTED: {
            OrderStatus.ACKED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.QUERY_UNKNOWN,
        },
        OrderStatus.ACKED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.QUERY_UNKNOWN,
        },
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.QUERY_UNKNOWN,
        },
        OrderStatus.FILLED: {OrderStatus.FILLED, OrderStatus.QUERY_UNKNOWN},
        OrderStatus.CANCELLED: {OrderStatus.CANCELLED, OrderStatus.QUERY_UNKNOWN},
        OrderStatus.REJECTED: {OrderStatus.REJECTED, OrderStatus.QUERY_UNKNOWN},
        OrderStatus.FAILED: {OrderStatus.FAILED, OrderStatus.QUERY_UNKNOWN},
        OrderStatus.SUBMIT_UNKNOWN: {
            OrderStatus.ACKED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.QUERY_UNKNOWN,
        },
        OrderStatus.QUERY_UNKNOWN: {
            OrderStatus.ACKED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.QUERY_UNKNOWN,
        },
    }

    @classmethod
    def is_valid(cls, old: OrderStatus, new: OrderStatus) -> bool:
        return old == new or new in cls.ALLOWED.get(old, set())


class Ledger:
    """SQLite WAL-backed durable ledger for all execution truth.

    All mutating operations are written to the event log first, then applied to
    state tables.  The ledger is the internal audit source of truth and is
    rebuilt on open if requested.
    """

    def __init__(self, path: Optional[str] = None, now_fn: Optional[Callable[[], str]] = None):
        self._now = now_fn or _now
        if path is None:
            root = Path(__file__).resolve().parent.parent
            path = os.getenv("AURORA_EXECUTION_TRUTH_DB") or str(root / "state" / "execution_truth.db")
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            self._local.conn = sqlite3.connect(
                self.path,
                timeout=10.0,
                isolation_level=None,
                check_same_thread=False,
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn()
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

                CREATE TABLE IF NOT EXISTS intents (
                    intent_id TEXT PRIMARY KEY,
                    intent_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT,
                    stop_loss TEXT,
                    take_profit TEXT,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL REFERENCES intents(intent_id),
                    exchange_order_id TEXT,
                    side TEXT NOT NULL,
                    position_side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    reduce_only INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    avg_price TEXT,
                    filled_qty TEXT NOT NULL,
                    remaining_qty TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    stop_price TEXT,
                    submit_attempt INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
                    exchange_fill_id TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    side TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_unique
                    ON fills(client_order_id, exchange_fill_id);

                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size TEXT NOT NULL,
                    cost_basis TEXT NOT NULL,
                    avg_entry TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL,
                    fees TEXT NOT NULL,
                    last_intent_id TEXT,
                    last_order_id TEXT,
                    sl_order_id TEXT,
                    tp_order_id TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pnl_sessions (
                    session_id TEXT PRIMARY KEY,
                    realized_pnl TEXT NOT NULL,
                    fees TEXT NOT NULL,
                    funding TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kill_switch (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL,
                    reason TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ledger_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
        # Migrate older P0-B1 databases to include protection columns
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
        for col in ("sl_order_id", "tp_order_id"):
            if col not in existing:
                conn.execute(f"ALTER TABLE positions ADD COLUMN {col} TEXT")

    def _log(self, event_type: str, payload: Dict[str, Any]) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT INTO events (event_type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(payload, default=str), self._now()),
            )

    def save_meta(self, key: str, value: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO ledger_meta (key, value) VALUES (?, ?)",
                (key, value),
            )

    def load_meta(self, key: str, default: str = "") -> str:
        row = self._conn().execute(
            "SELECT value FROM ledger_meta WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default

    def create_intent(
        self,
        intent_type: IntentType,
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> IntentRecord:
        intent_id = uuid.uuid4().hex[:16]
        record = IntentRecord(
            intent_id=intent_id,
            intent_type=intent_type,
            symbol=symbol,
            side=side,
            quantity=_Q(quantity),
            price=_P(price) if price is not None else None,
            stop_loss=_P(stop_loss) if stop_loss is not None else None,
            take_profit=_P(take_profit) if take_profit is not None else None,
            state=IntentState.PROPOSED,
            created_at=self._now(),
        )
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO intents (intent_id, intent_type, symbol, side, quantity,
                price, stop_loss, take_profit, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.intent_id,
                    record.intent_type.value,
                    record.symbol,
                    record.side.value,
                    str(record.quantity),
                    str(record.price) if record.price is not None else None,
                    str(record.stop_loss) if record.stop_loss is not None else None,
                    str(record.take_profit) if record.take_profit is not None else None,
                    record.state.value,
                    record.created_at,
                ),
            )
        self._log("INTENT_CREATE", {"intent_id": intent_id, "type": intent_type.value})
        return record

    def approve_intent(self, intent_id: str) -> Optional[IntentRecord]:
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "UPDATE intents SET state=? WHERE intent_id=? AND state=?",
                (IntentState.APPROVED.value, intent_id, IntentState.PROPOSED.value),
            )
        if cur.rowcount == 0:
            return None
        self._log("INTENT_APPROVE", {"intent_id": intent_id})
        return self.get_intent(intent_id)

    def cancel_intent(self, intent_id: str, reason: str = "") -> Optional[IntentRecord]:
        existing = self.get_intent(intent_id)
        if not existing or existing.state in (IntentState.COMPLETED, IntentState.FAILED):
            return existing
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE intents SET state=?, completed_at=?, error=? WHERE intent_id=?",
                (IntentState.CANCELLED.value, self._now(), reason, intent_id),
            )
        self._log("INTENT_CANCEL", {"intent_id": intent_id, "reason": reason})
        return self.get_intent(intent_id)

    def complete_intent(self, intent_id: str, error: Optional[str] = None) -> Optional[IntentRecord]:
        existing = self.get_intent(intent_id)
        if not existing:
            return None
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE intents SET state=?, completed_at=?, error=? WHERE intent_id=?",
                (
                    IntentState.FAILED.value if error else IntentState.COMPLETED.value,
                    self._now(),
                    error,
                    intent_id,
                ),
            )
        self._log(
            "INTENT_COMPLETE",
            {"intent_id": intent_id, "success": error is None, "error": error},
        )
        return self.get_intent(intent_id)

    def get_intent(self, intent_id: str) -> Optional[IntentRecord]:
        row = self._conn().execute(
            "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def _row_to_intent(self, row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            intent_id=row["intent_id"],
            intent_type=IntentType(row["intent_type"]),
            symbol=row["symbol"],
            side=Side(row["side"]),
            quantity=_Q(row["quantity"]),
            price=_P(row["price"]) if row["price"] else None,
            stop_loss=_P(row["stop_loss"]) if row["stop_loss"] else None,
            take_profit=_P(row["take_profit"]) if row["take_profit"] else None,
            state=IntentState(row["state"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

    def create_order(self, intent_id: str, attempt: int, **params: Any) -> OrderRecord:
        client_order_id = _cid(intent_id, attempt, params.get("suffix", ""))
        record = OrderRecord(
            client_order_id=client_order_id,
            intent_id=intent_id,
            exchange_order_id=None,
            side=params["side"],
            position_side=params.get("position_side", params["side"]),
            order_type=params["type"],
            quantity=_Q(params["quantity"]),
            reduce_only=bool(params.get("reduce_only", False)),
            status=OrderStatus.PENDING,
            avg_price=None,
            filled_qty=Decimal("0"),
            remaining_qty=_Q(params["quantity"]),
            fee=Decimal("0"),
            stop_price=_P(params["stop_price"]) if params.get("stop_price") is not None else None,
            submit_attempt=attempt,
            created_at=self._now(),
            updated_at=self._now(),
        )
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO orders (client_order_id, intent_id, exchange_order_id, side,
                position_side, order_type, quantity, reduce_only, status, filled_qty,
                remaining_qty, fee, stop_price, submit_attempt, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.client_order_id,
                    record.intent_id,
                    record.exchange_order_id,
                    record.side,
                    record.position_side,
                    record.order_type,
                    str(record.quantity),
                    int(record.reduce_only),
                    record.status.value,
                    str(record.filled_qty),
                    str(record.remaining_qty),
                    str(record.fee),
                    str(record.stop_price) if record.stop_price is not None else None,
                    record.submit_attempt,
                    record.created_at,
                    record.updated_at,
                ),
            )
        self._log("ORDER_CREATE", {"client_order_id": client_order_id, "intent_id": intent_id})
        return record

    def update_order_status(self, record: OrderRecord) -> OrderRecord:
        old = self.get_order(record.client_order_id)
        if old is not None:
            if not OrderStateMachine.is_valid(old.status, record.status):
                raise StateTransitionError(
                    f"invalid order transition: {old.status.value} -> {record.status.value} for {record.client_order_id}"
                )
        record.updated_at = self._now()
        conn = self._conn()
        with conn:
            conn.execute(
                """
                UPDATE orders SET exchange_order_id=?, status=?, avg_price=?, filled_qty=?,
                remaining_qty=?, fee=?, updated_at=?, error=? WHERE client_order_id=?
                """,
                (
                    record.exchange_order_id,
                    record.status.value,
                    str(record.avg_price) if record.avg_price is not None else None,
                    str(record.filled_qty),
                    str(record.remaining_qty),
                    str(record.fee),
                    record.updated_at,
                    record.error,
                    record.client_order_id,
                ),
            )
        self._log("ORDER_UPDATE", {"client_order_id": record.client_order_id, "status": record.status.value})
        return record

    def get_order(self, client_order_id: str) -> Optional[OrderRecord]:
        row = self._conn().execute(
            "SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_order(row)

    def _row_to_order(self, row: sqlite3.Row) -> OrderRecord:
        return OrderRecord(
            client_order_id=row["client_order_id"],
            intent_id=row["intent_id"],
            exchange_order_id=row["exchange_order_id"],
            side=row["side"],
            position_side=row["position_side"],
            order_type=row["order_type"],
            quantity=_Q(row["quantity"]),
            reduce_only=bool(row["reduce_only"]),
            status=OrderStatus(row["status"]),
            avg_price=_P(row["avg_price"]) if row["avg_price"] else None,
            filled_qty=_Q(row["filled_qty"]),
            remaining_qty=_Q(row["remaining_qty"]),
            fee=_P(row["fee"]) if row["fee"] else Decimal("0"),
            stop_price=_P(row["stop_price"]) if row["stop_price"] else None,
            submit_attempt=row["submit_attempt"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error=row["error"],
        )

    def orders_for_intent(self, intent_id: str) -> List[OrderRecord]:
        rows = self._conn().execute(
            "SELECT * FROM orders WHERE intent_id=? ORDER BY created_at", (intent_id,)
        ).fetchall()
        return [self._row_to_order(r) for r in rows]

    def insert_fill(self, record: FillRecord) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO fills
                (client_order_id, exchange_fill_id, price, quantity, fee, side, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.client_order_id,
                    record.exchange_fill_id,
                    str(_P(record.price)),
                    str(_Q(record.quantity)),
                    str(_P(record.fee)),
                    record.side,
                    record.timestamp,
                ),
            )
        self._log(
            "FILL",
            {
                "client_order_id": record.client_order_id,
                "fill_id": record.exchange_fill_id,
                "price": str(record.price),
                "quantity": str(record.quantity),
                "fee": str(record.fee),
            },
        )

    def fills_for(self, client_order_id: str) -> List[FillRecord]:
        rows = self._conn().execute(
            "SELECT * FROM fills WHERE client_order_id=? ORDER BY timestamp", (client_order_id,)
        ).fetchall()
        return [
            FillRecord(
                client_order_id=r["client_order_id"],
                exchange_fill_id=r["exchange_fill_id"],
                price=_P(r["price"]),
                quantity=_Q(r["quantity"]),
                fee=_P(r["fee"]),
                side=r["side"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    def save_position(self, record: PositionRecord, symbol: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO positions
                (symbol, state, side, size, cost_basis, avg_entry, realized_pnl, fees,
                last_intent_id, last_order_id, sl_order_id, tp_order_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    record.state.value,
                    record.side.value,
                    str(record.size),
                    str(record.cost_basis),
                    str(record.avg_entry),
                    str(record.realized_pnl),
                    str(record.fees),
                    record.last_intent_id,
                    record.last_order_id,
                    record.sl_order_id,
                    record.tp_order_id,
                    record.updated_at,
                ),
            )
        self._log("POSITION", {"symbol": symbol, "state": record.state.value, "side": record.side.value, "size": str(record.size)})

    def get_position(self, symbol: str) -> Optional[PositionRecord]:
        row = self._conn().execute(
            "SELECT * FROM positions WHERE symbol=?", (symbol,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_position(row)

    def _row_to_position(self, row: sqlite3.Row) -> PositionRecord:
        return PositionRecord(
            state=PositionState(row["state"]),
            side=Side(row["side"]),
            size=_Q(row["size"]),
            cost_basis=_P(row["cost_basis"]),
            avg_entry=_P(row["avg_entry"]),
            realized_pnl=_P(row["realized_pnl"]),
            fees=_P(row["fees"]),
            last_intent_id=row["last_intent_id"],
            last_order_id=row["last_order_id"],
            sl_order_id=row["sl_order_id"],
            tp_order_id=row["tp_order_id"],
            updated_at=row["updated_at"],
        )

    def set_kill_switch(self, active: bool, reason: str = "") -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO kill_switch (key, value, reason, updated_at) VALUES (?, ?, ?, ?)",
                ("global", int(active), reason, self._now()),
            )
        self._log("KILL_SWITCH", {"active": active, "reason": reason})

    def get_kill_switch(self) -> Tuple[bool, str]:
        row = self._conn().execute(
            "SELECT value, reason FROM kill_switch WHERE key=?", ("global",)
        ).fetchone()
        if not row:
            return False, ""
        return bool(row[0]), str(row["reason"] or "")

    def checkpoint(self, symbol: str) -> Dict[str, Any]:
        pos = self.get_position(symbol)
        k, r = self.get_kill_switch()
        pending = self._conn().execute(
            "SELECT client_order_id FROM orders WHERE status NOT IN (?, ?, ?, ?)",
            (
                OrderStatus.FILLED.value,
                OrderStatus.CANCELLED.value,
                OrderStatus.REJECTED.value,
                OrderStatus.FAILED.value,
            ),
        ).fetchall()
        return {
            "position": pos,
            "kill_switch": k,
            "kill_reason": r,
            "pending_orders": [r[0] for r in pending],
            "event_count": self._conn().execute("SELECT COUNT(*) FROM events").fetchone()[0],
        }


class ExchangePort(Protocol):
    """Abstraction over any exchange or simulated exchange."""

    symbol: str

    def submit(self, client_order_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def query(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        ...

    def cancel(self, client_order_id: str) -> Dict[str, Any]:
        ...

    def position(self) -> Dict[str, Any]:
        ...

    def is_up(self) -> bool:
        ...


class FakeExchange:
    """Deterministic, fault-injectable exchange for offline P0-B1 tests."""

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        fee_rate: Decimal = Decimal("0.0005"),
        default_price: Decimal = Decimal("100000.00"),
    ):
        self.symbol = symbol
        self.fee_rate = fee_rate
        self.default_price = default_price
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.fills: Dict[str, List[Dict[str, Any]]] = {}
        self._position: Dict[str, Any] = {"side": "FLAT", "size": Decimal("0"), "entry_price": Decimal("0")}
        self.fail_submits: set = set()
        self.fail_queries: set = set()
        self.fail_cancels: set = set()
        self.submit_unknown_once: set = set()
        self.partial_fills: Dict[str, Decimal] = {}
        self.fail_next_n_submits: int = 0
        self.submit_unknown_next_n: int = 0
        self.query_unknown_next_n: int = 0
        self.cancel_fail_next_n: int = 0
        self.partial_fill_next: Optional[Decimal] = None
        self.submit_unknown_types: set = set()
        self.fail_types: set = set()
        self.cancel_calls: List[str] = []
        self.latency_ms: int = 0
        self._seq = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _sleep(self) -> None:
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)

    def set_latency(self, ms: int) -> None:
        self.latency_ms = ms

    def fail_submit_for(self, cid: str) -> None:
        self.fail_submits.add(cid)

    def fail_query_for(self, cid: str) -> None:
        self.fail_queries.add(cid)

    def fail_cancel_for(self, cid: str) -> None:
        self.fail_cancels.add(cid)

    def submit_unknown_for(self, cid: str) -> None:
        """Simulate a timeout where we do not know if the order was accepted."""
        self.submit_unknown_once.add(cid)

    def set_partial_fill(self, cid: str, fill_ratio: Decimal) -> None:
        self.partial_fills[cid] = fill_ratio

    def fail_type_once(self, otype: str) -> None:
        self.fail_types.add(otype)

    def submit_unknown_type_once(self, otype: str) -> None:
        self.submit_unknown_types.add(otype)

    def _make_fill(self, cid: str, qty: Decimal, price: Decimal, side: str) -> Dict[str, Any]:
        fee = (qty * price * self.fee_rate).quantize(D_PRICE)
        fill = {
            "id": f"fill_{self._next_id()}",
            "qty": qty,
            "price": price,
            "fee": fee,
            "side": side,
            "time": _now(),
        }
        self.fills.setdefault(cid, []).append(fill)
        return fill

    def submit(self, client_order_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._sleep()
        if self.submit_unknown_next_n:
            self.submit_unknown_next_n -= 1
            raise SubmitUnknownError("exchange did not respond; result unknown")
        if self.fail_next_n_submits:
            self.fail_next_n_submits -= 1
            raise ExchangeError("submit rejected")
        if client_order_id in self.submit_unknown_once:
            self.submit_unknown_once.discard(client_order_id)
            raise SubmitUnknownError("exchange did not respond; result unknown")
        if client_order_id in self.fail_submits:
            raise ExchangeError("submit rejected")

        existing = self.orders.get(client_order_id)
        if existing:
            return existing

        side = params["side"]
        position_side = params.get("position_side", side)
        qty = _Q(params["quantity"])
        otype = params.get("type", "MARKET")
        reduce_only = bool(params.get("reduce_only", False))

        if otype in self.submit_unknown_types:
            self.submit_unknown_types.discard(otype)
            raise SubmitUnknownError("exchange did not respond; result unknown")
        if otype in self.fail_types:
            self.fail_types.discard(otype)
            raise ExchangeError("submit rejected")

        record = {
            "client_order_id": client_order_id,
            "orderId": str(self._next_id()),
            "symbol": self.symbol,
            "side": side,
            "positionSide": position_side,
            "type": otype,
            "quantity": qty,
            "reduceOnly": reduce_only,
            "status": "NEW",
            "executedQty": Decimal("0"),
            "avgPrice": Decimal("0"),
            "cummulativeQuoteQty": Decimal("0"),
            "stopPrice": _P(params["stop_price"]) if params.get("stop_price") is not None else None,
        }

        if otype == "MARKET":
            fill_qty = qty
            partial = self.partial_fill_next
            if partial is None:
                partial = self.partial_fills.get(client_order_id)
            if partial is not None:
                self.partial_fill_next = None
                fill_qty = (qty * partial).quantize(D_QTY, rounding=ROUND_HALF_UP)
                record["status"] = "PARTIALLY_FILLED"
                record["executedQty"] = fill_qty
                record["avgPrice"] = self.default_price
                self._make_fill(client_order_id, fill_qty, self.default_price, side)
                self._update_position(position_side, fill_qty, self.default_price, reduce_only)
            else:
                record["status"] = "FILLED"
                record["executedQty"] = qty
                record["avgPrice"] = self.default_price
                self._make_fill(client_order_id, qty, self.default_price, side)
                self._update_position(position_side, qty, self.default_price, reduce_only)

            record["fills"] = [dict(f) for f in self.fills.get(client_order_id, [])]

        self.orders[client_order_id] = record
        return record

    def _update_position(self, position_side: str, qty: Decimal, price: Decimal, reduce_only: bool) -> None:
        if reduce_only:
            if self._position["side"] == "FLAT" or self._position["side"] != position_side:
                return
            self._position["size"] -= qty
            if self._position["size"] <= 0:
                self._position = {"side": "FLAT", "size": Decimal("0"), "entry_price": Decimal("0")}
        else:
            if self._position["side"] == "FLAT":
                self._position = {"side": position_side, "size": qty, "entry_price": price}
            elif self._position["side"] == position_side:
                total = self._position["size"] + qty
                avg = (self._position["size"] * self._position["entry_price"] + qty * price) / total
                self._position = {"side": position_side, "size": total, "entry_price": avg.quantize(D_PRICE)}
            else:
                net = self._position["size"] - qty
                if net <= 0:
                    self._position = {"side": "FLAT", "size": Decimal("0"), "entry_price": Decimal("0")}
                else:
                    self._position = {"side": self._position["side"], "size": net, "entry_price": self._position["entry_price"]}

    def query(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        self._sleep()
        if self.query_unknown_next_n:
            self.query_unknown_next_n -= 1
            raise ExchangeError("query failed")
        if client_order_id in self.fail_queries:
            raise ExchangeError("query failed")
        return self.orders.get(client_order_id)

    def cancel(self, client_order_id: str) -> Dict[str, Any]:
        self._sleep()
        self.cancel_calls.append(client_order_id)
        if self.cancel_fail_next_n:
            self.cancel_fail_next_n -= 1
            raise ExchangeError("cancel failed")
        if client_order_id in self.fail_cancels:
            raise ExchangeError("cancel failed")
        rec = self.orders.get(client_order_id)
        if not rec:
            return {"status": "CANCELED", "client_order_id": client_order_id}
        if rec["status"] in ("FILLED", "CANCELED"):
            return rec
        rec["status"] = "CANCELED"
        return rec

    def position(self) -> Dict[str, Any]:
        return dict(self._position)

    def is_up(self) -> bool:
        return True

    def set_position_state(self, side: str, size: Decimal, entry_price: Decimal) -> None:
        self._position = {"side": side, "size": _Q(size), "entry_price": _P(entry_price)}

    def _fill_remaining(self, client_order_id: str) -> None:
        rec = self.orders.get(client_order_id)
        if not rec or rec["status"] == "FILLED":
            return
        remaining = rec["quantity"] - rec["executedQty"]
        if remaining > 0:
            self._make_fill(client_order_id, remaining, self.default_price, rec["side"])
            self._update_position(rec["positionSide"], remaining, self.default_price, rec["reduceOnly"])
            rec["executedQty"] = rec["quantity"]
            rec["avgPrice"] = self.default_price
        rec["status"] = "FILLED"


class ExchangeError(Exception):
    pass


class SubmitUnknownError(Exception):
    """Raised when the exchange did not acknowledge a submission."""
    pass


class QueryUnknownError(Exception):
    """Raised when the exchange did not respond to a query."""
    pass


class PositionTruth:
    """Reconstructs position and realized PnL from ledger fills."""

    def __init__(self, symbol: str, ledger: Ledger):
        self.symbol = symbol
        self.ledger = ledger

    def rebuild(self) -> PositionRecord:
        """Replay every fill in chronological order to reconstruct truth."""
        rows = self.ledger._conn().execute(
            """
            SELECT o.client_order_id, o.reduce_only, o.quantity
            FROM orders o
            JOIN intents i ON o.intent_id = i.intent_id
            WHERE i.symbol=? AND o.status IN (?, ?)
            ORDER BY o.created_at
            """,
            (
                self.symbol,
                OrderStatus.FILLED.value,
                OrderStatus.PARTIALLY_FILLED.value,
            ),
        ).fetchall()

        position = PositionRecord(
            state=PositionState.KNOWN_FLAT,
            side=Side.FLAT,
            size=Decimal("0"),
            cost_basis=Decimal("0"),
            avg_entry=Decimal("0"),
            realized_pnl=Decimal("0"),
            fees=Decimal("0"),
            last_intent_id=None,
            last_order_id=None,
            sl_order_id=None,
            tp_order_id=None,
            updated_at=self.ledger._now(),
        )

        for row in rows:
            for fill in self.ledger.fills_for(row["client_order_id"]):
                position = self.apply_fill(position, fill, bool(row["reduce_only"]), _Q(row["quantity"]))

        position.updated_at = self.ledger._now()
        return position

    def apply_fill(self, position: PositionRecord, fill: FillRecord, reduce_only: bool, order_qty: Decimal) -> PositionRecord:
        new = position
        total_fees = new.fees + fill.fee
        realized = new.realized_pnl

        if not reduce_only:
            if new.state == PositionState.KNOWN_FLAT:
                side = Side.LONG if fill.side in ("BUY", "LONG") else Side.SHORT
                size = fill.quantity
                cost = fill.quantity * fill.price
                return PositionRecord(
                    state=PositionState.KNOWN_OPEN,
                    side=side,
                    size=_Q(size),
                    cost_basis=_P(cost),
                    avg_entry=_P(cost / size) if size > 0 else Decimal("0"),
                    realized_pnl=realized,
                    fees=_P(total_fees),
                    last_intent_id=position.last_intent_id,
                    last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                    updated_at=self.ledger._now(),
                )
            elif new.state == PositionState.KNOWN_OPEN:
                side = new.side
                if (fill.side in ("BUY", "LONG") and side == Side.LONG) or (fill.side in ("SELL", "SHORT") and side == Side.SHORT):
                    total = new.size + fill.quantity
                    cost = new.cost_basis + fill.quantity * fill.price
                    return PositionRecord(
                        state=PositionState.KNOWN_OPEN,
                        side=side,
                        size=_Q(total),
                        cost_basis=_P(cost),
                        avg_entry=_P(cost / total),
                        realized_pnl=realized,
                        fees=_P(total_fees),
                        last_intent_id=position.last_intent_id,
                        last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                        updated_at=self.ledger._now(),
                    )
                else:
                    # reducing / flipping
                    realized += new.size * (fill.price - new.avg_entry) if side == Side.LONG else new.size * (new.avg_entry - fill.price)
                    net = new.size - fill.quantity
                    if net <= 0:
                        return PositionRecord(
                            state=PositionState.KNOWN_FLAT,
                            side=Side.FLAT,
                            size=Decimal("0"),
                            cost_basis=Decimal("0"),
                            avg_entry=Decimal("0"),
                            realized_pnl=realized.quantize(D_PNL),
                            fees=_P(total_fees),
                            last_intent_id=position.last_intent_id,
                            last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                            updated_at=self.ledger._now(),
                        )
                    else:
                        cost = net * new.avg_entry
                        return PositionRecord(
                            state=PositionState.KNOWN_OPEN,
                            side=side,
                            size=_Q(net),
                            cost_basis=_P(cost),
                            avg_entry=new.avg_entry,
                            realized_pnl=realized.quantize(D_PNL),
                            fees=_P(total_fees),
                            last_intent_id=position.last_intent_id,
                            last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                            updated_at=self.ledger._now(),
                        )
        else:
            # reduce-only fill
            if new.state == PositionState.KNOWN_OPEN:
                if (fill.side in ("BUY", "LONG") and new.side == Side.SHORT) or (fill.side in ("SELL", "SHORT") and new.side == Side.LONG):
                    realized += fill.quantity * (new.avg_entry - fill.price) if new.side == Side.SHORT else fill.quantity * (fill.price - new.avg_entry)
                net = new.size - fill.quantity
                if net <= 0:
                    return PositionRecord(
                        state=PositionState.KNOWN_FLAT,
                        side=Side.FLAT,
                        size=Decimal("0"),
                        cost_basis=Decimal("0"),
                        avg_entry=Decimal("0"),
                        realized_pnl=realized.quantize(D_PNL),
                        fees=_P(total_fees),
                        last_intent_id=position.last_intent_id,
                        last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                        updated_at=self.ledger._now(),
                    )
                else:
                    return PositionRecord(
                        state=PositionState.KNOWN_OPEN,
                        side=new.side,
                        size=_Q(net),
                        cost_basis=_P(net * new.avg_entry),
                        avg_entry=new.avg_entry,
                        realized_pnl=realized.quantize(D_PNL),
                        fees=_P(total_fees),
                        last_intent_id=position.last_intent_id,
                        last_order_id=position.last_order_id,
            sl_order_id=position.sl_order_id,
            tp_order_id=position.tp_order_id,
                        updated_at=self.ledger._now(),
                    )
            return new


class DurableExecutor:
    """P0-B1 durable executor.  No strategy.  Only truth."""

    def __init__(
        self,
        symbol: str,
        ledger: Ledger,
        port: ExchangePort,
        max_retries: int = 2,
        poll_interval_ms: int = 100,
        poll_timeout_ms: int = 5000,
    ):
        self.symbol = symbol
        self.ledger = ledger
        self.port = port
        self.max_retries = max_retries
        self.poll_interval_ms = poll_interval_ms
        self.poll_timeout_ms = poll_timeout_ms
        self.truth = PositionTruth(symbol, ledger)

    def _kill_switch(self) -> Tuple[bool, str]:
        return self.ledger.get_kill_switch()

    def _raise_if_killed(self) -> None:
        active, reason = self._kill_switch()
        if active:
            raise ExecutionHalted(f"kill switch active: {reason}")

    def _sleep(self) -> None:
        if self.poll_interval_ms:
            time.sleep(self.poll_interval_ms / 1000.0)

    def _submit_and_query(self, record: OrderRecord, params: Dict[str, Any]) -> OrderRecord:
        """Submit with idempotency and bounded retries.

        Before each submit attempt we query the exchange for the current
        client_order_id.  If it does not exist and the submit fails with an
        explicit ExchangeError, we advance to a new client_order_id and retry.
        A SubmitUnknownError (timeout/ambiguous) is not retried, because doing
        so could create a duplicate order.
        """
        current = record
        for attempt in range(record.submit_attempt, record.submit_attempt + self.max_retries):
            existing = self.port.query(current.client_order_id)
            if existing is not None:
                return self._ingest_exchange_order(current, existing)

            try:
                raw = self.port.submit(current.client_order_id, params)
            except SubmitUnknownError as exc:
                current.status = OrderStatus.SUBMIT_UNKNOWN
                current.error = str(exc)
                return self.ledger.update_order_status(current)
            except ExchangeError as exc:
                if attempt == record.submit_attempt + self.max_retries - 1:
                    current.status = OrderStatus.FAILED
                    current.error = str(exc)
                    return self.ledger.update_order_status(current)
                current = self.ledger.create_order(
                    current.intent_id,
                    attempt + 1,
                    side=params["side"],
                    position_side=params["position_side"],
                    type=params["type"],
                    quantity=params["quantity"],
                    reduce_only=params["reduce_only"],
                    stop_price=params.get("stop_price"),
                )
                continue

            return self._ingest_exchange_order(current, raw)

        current.status = OrderStatus.FAILED
        current.error = "max submit attempts exceeded"
        return self.ledger.update_order_status(current)

    def _ingest_exchange_order(self, record: OrderRecord, raw: Dict[str, Any]) -> OrderRecord:
        record.exchange_order_id = str(raw.get("orderId", ""))
        status = raw.get("status", "NEW")
        record.avg_price = _P(raw.get("avgPrice", 0)) if raw.get("avgPrice") is not None else None
        record.filled_qty = _Q(raw.get("executedQty", 0))
        record.remaining_qty = record.quantity - record.filled_qty

        if status == "FILLED":
            record.status = OrderStatus.FILLED
        elif status == "PARTIALLY_FILLED":
            record.status = OrderStatus.PARTIALLY_FILLED
        elif status == "NEW":
            record.status = OrderStatus.ACKED
        elif status == "CANCELED":
            record.status = OrderStatus.CANCELLED
        elif status == "REJECTED":
            record.status = OrderStatus.REJECTED
        else:
            record.status = OrderStatus.ACKED

        record = self.ledger.update_order_status(record)
        self._ingest_fills(record, raw)
        return record

    def _ingest_fills(self, record: OrderRecord, raw: Dict[str, Any]) -> None:
        # For FakeExchange and Binance fills come separately; this is a compatibility layer
        fills = raw.get("fills") or []
        for f in fills:
            fr = FillRecord(
                client_order_id=record.client_order_id,
                exchange_fill_id=str(f.get("id") or f.get("tradeId") or uuid.uuid4().hex[:8]),
                price=_P(f.get("price", 0)),
                quantity=_Q(f.get("qty", 0)),
                fee=_P(f.get("fee", 0)),
                side=record.side,
                timestamp=f.get("time") or self.ledger._now(),
            )
            self.ledger.insert_fill(fr)

    def _poll_until_terminal(self, record: OrderRecord, timeout_ms: Optional[int] = None) -> OrderRecord:
        """Poll an ACKED/PARTIALLY_FILLED order until terminal or timeout."""
        timeout_ms = timeout_ms if timeout_ms is not None else self.poll_timeout_ms
        start = time.monotonic()
        while not record.is_terminal():
            if record.status in (OrderStatus.QUERY_UNKNOWN, OrderStatus.SUBMIT_UNKNOWN):
                break
            if (time.monotonic() - start) * 1000 > timeout_ms:
                break
            self._sleep()
            try:
                raw = self.port.query(record.client_order_id)
            except ExchangeError:
                record.status = OrderStatus.QUERY_UNKNOWN
                record.error = "query failed during poll"
                return self.ledger.update_order_status(record)
            if raw is None:
                record.status = OrderStatus.QUERY_UNKNOWN
                record.error = "order disappeared"
                return self.ledger.update_order_status(record)
            record = self._ingest_exchange_order(record, raw)

            # FakeExchange specific: if partial, the caller may need to force fill for tests
            if record.status == OrderStatus.PARTIALLY_FILLED and hasattr(self.port, "_fill_remaining"):
                # only used in controlled tests
                pass

        return record

    def _place_protection(
        self,
        intent_id: str,
        side: Side,
        size: Decimal,
        stop_price: Decimal,
        otype: str,
        suffix: str,
    ) -> OrderRecord:
        close_side = "SELL" if side == Side.LONG else "BUY"
        params = {
            "side": close_side,
            "position_side": side.value,
            "type": otype,
            "quantity": size,
            "reduce_only": True,
            "stop_price": stop_price,
            "suffix": suffix,
        }
        record = self.ledger.create_order(intent_id, 1, **params)
        existing = self.port.query(record.client_order_id)
        if existing is not None:
            return self._ingest_exchange_order(record, existing)

        try:
            raw = self.port.submit(record.client_order_id, params)
        except SubmitUnknownError as exc:
            record.status = OrderStatus.SUBMIT_UNKNOWN
            record.error = str(exc)
            return self.ledger.update_order_status(record)
        except ExchangeError as exc:
            record.status = OrderStatus.FAILED
            record.error = str(exc)
            return self.ledger.update_order_status(record)

        return self._ingest_exchange_order(record, raw)

    def _place_protections(
        self,
        intent_id: str,
        side: Side,
        size: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Tuple[Optional[OrderRecord], Optional[OrderRecord]]:
        sl = None
        tp = None
        if stop_loss is not None:
            sl = self._place_protection(intent_id, side, size, stop_loss, "STOP_MARKET", "SL")
        if take_profit is not None:
            tp = self._place_protection(intent_id, side, size, take_profit, "TAKE_PROFIT_MARKET", "TP")
        return sl, tp

    def _cancel_protection(self, client_order_id: Optional[str]) -> None:
        if not client_order_id:
            return
        try:
            self.port.cancel(client_order_id)
        except ExchangeError:
            pass

    def open_position(
        self,
        side: Side,
        quantity: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        self._raise_if_killed()
        if side == Side.FLAT:
            return {"success": False, "reason": "cannot open FLAT"}

        position = self.ledger.get_position(self.symbol) or self.truth.rebuild()
        if position.state != PositionState.KNOWN_FLAT:
            return {
                "success": False,
                "reason": f"already {position.state.value}; close before opening",
            }

        intent = self.ledger.create_intent(
            IntentType.OPEN, self.symbol, side, quantity, stop_loss=stop_loss, take_profit=take_profit
        )
        intent = self.ledger.approve_intent(intent.intent_id)
        if not intent:
            return {"success": False, "reason": "intent approval failed"}

        order_side = "BUY" if side == Side.LONG else "SELL"
        params = {
            "side": order_side,
            "position_side": side.value,
            "type": "MARKET",
            "quantity": quantity,
            "reduce_only": False,
        }

        record = self.ledger.create_order(intent.intent_id, 1, **params)
        result = self._submit_and_query(record, params)

        if result.status == OrderStatus.SUBMIT_UNKNOWN:
            position = self.truth.rebuild()
            position.state = PositionState.UNKNOWN
            position.last_intent_id = intent.intent_id
            position.last_order_id = result.client_order_id
            self.ledger.save_position(position, self.symbol)
            self.ledger.complete_intent(intent.intent_id, error=result.error)
            return {"success": False, "reason": "SUBMIT_UNKNOWN", "client_order_id": result.client_order_id, "halt": True}

        if result.status in (OrderStatus.FAILED, OrderStatus.REJECTED):
            self.ledger.complete_intent(intent.intent_id, error=result.error)
            return {"success": False, "reason": result.error or "open rejected"}

        result = self._poll_until_terminal(result)

        if result.status == OrderStatus.PARTIALLY_FILLED:
            # open must fully fill to be considered complete; cancel remainder and mark UNKNOWN
            try:
                self.port.cancel(result.client_order_id)
            except ExchangeError:
                pass
            position = self.truth.rebuild()
            position.state = PositionState.UNKNOWN
            position.last_intent_id = intent.intent_id
            position.last_order_id = result.client_order_id
            self.ledger.save_position(position, self.symbol)
            self.ledger.complete_intent(intent.intent_id, error="open partially filled")
            return {"success": False, "reason": "open partially filled", "client_order_id": result.client_order_id, "halt": True}

        if result.status == OrderStatus.FILLED:
            position = self.truth.rebuild()
            position.last_intent_id = intent.intent_id
            position.last_order_id = result.client_order_id

            sl, tp = self._place_protections(
                intent.intent_id, position.side, position.size, stop_loss, take_profit
            )
            sl_ok = sl is None or sl.status == OrderStatus.ACKED
            tp_ok = tp is None or tp.status == OrderStatus.ACKED

            if sl is not None:
                position.sl_order_id = sl.client_order_id
            if tp is not None:
                position.tp_order_id = tp.client_order_id

            if not (sl_ok and tp_ok):
                # protection handshake failed: save known order ids, emergency flatten
                self.ledger.save_position(position, self.symbol)
                self.close_position()
                self.ledger.complete_intent(intent.intent_id, error="protection handshake failed")
                return {"success": False, "reason": "protection handshake failed", "client_order_id": result.client_order_id, "halt": True}

            position.sl_order_id = sl.client_order_id if sl else None
            position.tp_order_id = tp.client_order_id if tp else None
            self.ledger.save_position(position, self.symbol)
            self.ledger.complete_intent(intent.intent_id)
            return {"success": True, "client_order_id": result.client_order_id, "position": position}

        self.ledger.complete_intent(intent.intent_id, error=result.error or "open unresolved")
        return {"success": False, "reason": result.error or "open unresolved", "client_order_id": result.client_order_id}

    def close_position(self) -> Dict[str, Any]:
        self._raise_if_killed()
        position = self.ledger.get_position(self.symbol) or self.truth.rebuild()
        if position.state == PositionState.KNOWN_FLAT:
            return {"success": True, "reason": "already flat"}
        if position.state != PositionState.KNOWN_OPEN:
            return {"success": False, "reason": f"cannot close in state {position.state.value}", "halt": True}

        intent = self.ledger.create_intent(
            IntentType.FLAT, self.symbol, position.side, position.size
        )
        intent = self.ledger.approve_intent(intent.intent_id)

        # Cancel open protection orders before closing.  Unknown/cancel-failure is not
        # fatal at this point; the close order is the authoritative flatten action.
        self._cancel_protection(position.sl_order_id)
        self._cancel_protection(position.tp_order_id)

        close_side = "SELL" if position.side == Side.LONG else "BUY"
        params = {
            "side": close_side,
            "position_side": position.side.value,
            "type": "MARKET",
            "quantity": position.size,
            "reduce_only": True,
        }

        record = self.ledger.create_order(intent.intent_id, 1, **params)
        result = self._submit_and_query(record, params)

        if result.status == OrderStatus.SUBMIT_UNKNOWN:
            position.state = PositionState.UNKNOWN
            position.last_intent_id = intent.intent_id
            position.last_order_id = result.client_order_id
            self.ledger.save_position(position, self.symbol)
            self.ledger.complete_intent(intent.intent_id, error=result.error)
            return {"success": False, "reason": "close SUBMIT_UNKNOWN", "client_order_id": result.client_order_id, "halt": True}

        if result.status in (OrderStatus.FAILED, OrderStatus.REJECTED):
            self.ledger.complete_intent(intent.intent_id, error=result.error or "close rejected")
            return {"success": False, "reason": result.error or "close rejected"}

        result = self._poll_until_terminal(result)

        if result.status == OrderStatus.FILLED:
            new_position = self.truth.rebuild()
            new_position.last_intent_id = intent.intent_id
            new_position.last_order_id = result.client_order_id
            self.ledger.save_position(new_position, self.symbol)
            self.ledger.complete_intent(intent.intent_id)
            return {"success": True, "client_order_id": result.client_order_id, "realized_pnl": new_position.realized_pnl}

        # PARTIALLY_FILLED close or unresolved: cancel, then mark UNKNOWN
        try:
            self.port.cancel(result.client_order_id)
        except ExchangeError:
            pass
        position.state = PositionState.UNKNOWN
        position.last_intent_id = intent.intent_id
        position.last_order_id = result.client_order_id
        self.ledger.save_position(position, self.symbol)
        self.ledger.complete_intent(intent.intent_id, error=result.error or "close unresolved")
        return {"success": False, "reason": result.error or "close unresolved", "client_order_id": record.client_order_id, "halt": True}

    def set_kill_switch(self, active: bool, reason: str = "") -> None:
        self.ledger.set_kill_switch(active, reason)

    def reconcile(self, trigger: str = "timer") -> Any:
        """Three-way reconcile: exchange, ledger, and fill-derived truth.

        NOT-BUILT: the original `aurora.reconciler.Reconciler` dependency was
        never implemented and is not restored under ADR-013. The contract is
        preserved in docs/baseline/reference_tests/ as a specification.
        """
        raise NotImplementedError(
            "[reference] reconcile is NOT-BUILT: aurora.reconciler never "
            "existed; see docs/baseline/reference_tests/DISPOSITION.md"
        )

    def boot(self) -> Dict[str, Any]:
        """Recover state from ledger and exchange at startup."""
        self._raise_if_killed()
        rec = self.reconcile("boot")
        return {
            "ok": rec.status == "MATCHED",
            "state": rec.ledger.state.value,
            "reason": rec.reason,
        }


def _abs_close(a: Decimal, b: Decimal, tol: Decimal = Decimal("0.001")) -> bool:
    return abs(a - b) <= tol


class ExecutionHalted(Exception):
    pass
