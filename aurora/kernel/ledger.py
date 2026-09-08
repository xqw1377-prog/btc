"""SQLite WAL 持久化账本（P0-B1）。

持久化：意图与状态机、订单、成交、持仓事实（KNOWN_FLAT/KNOWN_OPEN/UNKNOWN）、
Kill Switch、全部状态转移审计（时间/原因/关联 ID）。

不变量：
- 账本先于交易所写入：订单必须先落 SUBMITTING 才允许提交（ledger-first）；
- fill_id 主键去重：重复 Fill 事件不会重复记账；
- claim 用 BEGIN IMMEDIATE 原子抢占：两个执行器不能同时消费同一 Intent。
"""
import sqlite3
from enum import Enum
from typing import Any, Dict, List, Optional

from .state_machine import IntentState, assert_transition, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
    intent_id       TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    state           TEXT NOT NULL,
    claimed_by      TEXT,
    claimed_at      TEXT,
    reason          TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    stop_price      REAL,
    take_profit_price REAL
);

CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    intent_id       TEXT NOT NULL REFERENCES intents(intent_id),
    order_kind      TEXT NOT NULL,
    side            TEXT NOT NULL,
    position_side   TEXT NOT NULL,
    quantity        REAL NOT NULL,
    stop_price      REAL,
    reduce_only     INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL,
    exchange_order_id TEXT,
    filled_qty      REAL NOT NULL DEFAULT 0,
    avg_price       REAL NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id         TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
    qty             REAL NOT NULL,
    price           REAL NOT NULL,
    fee             REAL NOT NULL DEFAULT 0,
    realized_pnl    REAL NOT NULL DEFAULT 0,
    side            TEXT NOT NULL,
    filled_at       TEXT NOT NULL,
    synthetic                 INTEGER NOT NULL DEFAULT 0,
    replaces_synthetic_fill_id TEXT,
    covered_by_fact_id         TEXT,
    quantity_effect_applied    INTEGER NOT NULL DEFAULT 1,
    economic_effect_applied    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS reconciliation_facts (
    fact_id                TEXT PRIMARY KEY,
    client_order_id        TEXT NOT NULL,
    covered_fill_ids       TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    exchange_executed_qty  REAL NOT NULL DEFAULT 0,
    captured_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switch (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    engaged     INTEGER NOT NULL DEFAULT 0,
    reason      TEXT DEFAULT '',
    engaged_at  TEXT
);

CREATE TABLE IF NOT EXISTS position_facts (
    symbol      TEXT PRIMARY KEY,
    state       TEXT NOT NULL,
    qty         REAL NOT NULL DEFAULT 0,
    side        TEXT NOT NULL DEFAULT 'FLAT',
    source      TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    at              TEXT NOT NULL,
    reason          TEXT NOT NULL,
    correlation_id  TEXT NOT NULL
);
"""


class PositionFactState(Enum):
    KNOWN_FLAT = "KNOWN_FLAT"
    KNOWN_OPEN = "KNOWN_OPEN"
    UNKNOWN = "UNKNOWN"


# 交易所已确认空仓，但没有可引用的平仓 order/fill。
# 不得为了账本平衡补造 SELL / fee / pnl。
# 这是证据残留，不是永久交易禁令；运行锁由 kill / incident disposition 单独决定。
CLOSE_PROVENANCE_UNKNOWN = "CLOSE_PROVENANCE_UNKNOWN"


PENDING_ORDER_STATES = (
    "SUBMITTING",
    "SUBMIT_UNKNOWN",
    "PROTECTION_SUBMITTING",
    "CLOSING",
    "CLOSE_UNKNOWN",
)


class Ledger:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._ensure_intent_protect_columns()
        self._conn.execute(
            "INSERT OR IGNORE INTO kill_switch (id, engaged, reason) VALUES (1, 0, '')"
        )
        self._conn.commit()

    def _ensure_intent_protect_columns(self) -> None:
        """G0-4B：保护价必须能在重启后从账本读回，禁止用 99/101 哨兵回填。"""
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(intents)")
        }
        with self._conn:
            if "stop_price" not in cols:
                self._conn.execute("ALTER TABLE intents ADD COLUMN stop_price REAL")
            if "take_profit_price" not in cols:
                self._conn.execute(
                    "ALTER TABLE intents ADD COLUMN take_profit_price REAL")

    def close(self) -> None:
        self._conn.close()

    # ---------- 意图 ----------

    def create_intent(self, intent_id: str, symbol: str, side: str, quantity: float) -> bool:
        now = utc_now()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO intents (intent_id, symbol, side, quantity, state,"
                    " reason, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (intent_id, symbol, side, quantity, IntentState.INTENT_CREATED.value,
                     "intent created", now, now),
                )
        except sqlite3.IntegrityError:
            return False  # 重放：意图已存在
        return True

    def set_intent_protect_prices(
        self,
        intent_id: str,
        stop_price: Optional[float],
        take_profit_price: Optional[float] = None,
    ) -> None:
        """把强制 SL / 可选 TP 作为意图合同持久化（不是哨兵默认值）。"""
        with self._conn:
            self._conn.execute(
                "UPDATE intents SET stop_price = ?, take_profit_price = ?,"
                " updated_at = ? WHERE intent_id = ?",
                (stop_price, take_profit_price, utc_now(), intent_id),
            )

    def get_intent(self, intent_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_intents(self, states: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if states:
            marks = ",".join("?" for _ in states)
            rows = self._conn.execute(
                f"SELECT * FROM intents WHERE state IN ({marks}) ORDER BY created_at", states
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM intents ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def claim_intent(self, intent_id: str, instance_id: str) -> bool:
        """原子抢占：仅 INTENT_CREATED 且未被他人认领的意图可被认领一次。"""
        try:
            with self._conn:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "UPDATE intents SET claimed_by = ?, claimed_at = ?"
                    " WHERE intent_id = ? AND state = ?"
                    " AND (claimed_by IS NULL OR claimed_by = ?)",
                    (instance_id, utc_now(), intent_id,
                     IntentState.INTENT_CREATED.value, instance_id),
                )
                return cur.rowcount == 1
        except sqlite3.Error:
            return False

    def transition_intent(
        self, intent_id: str, to_state: IntentState, reason: str,
        correlation_id: Optional[str] = None,
        exchange_fact: Optional[tuple] = None,
    ) -> bool:
        current = self.get_intent(intent_id)
        if current is None:
            return False
        from_state = IntentState(current["state"])
        transition = assert_transition(
            "intent", intent_id, from_state, to_state, reason,
            correlation_id, exchange_fact=exchange_fact,
        )
        with self._conn:
            cur = self._conn.execute(
                "UPDATE intents SET state = ?, reason = ?, updated_at = ? WHERE intent_id = ?",
                (to_state.value, reason, transition.at, intent_id),
            )
            if cur.rowcount != 1:
                return False
            self._log_transition(transition)
        return True

    # ---------- 订单 ----------

    def record_order_submitting(
        self,
        client_order_id: str,
        intent_id: str,
        order_kind: str,
        side: str,
        position_side: str,
        quantity: float,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> None:
        """ledger-first：订单必须先落 SUBMITTING，之后才允许向交易所提交。"""
        now = utc_now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO orders (client_order_id, intent_id, order_kind, side,"
                " position_side, quantity, stop_price, reduce_only, state,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTING', ?, ?)",
                (client_order_id, intent_id, order_kind, side, position_side,
                 quantity, stop_price, int(reduce_only), now, now),
            )

    def update_order(
        self,
        client_order_id: str,
        state: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        filled_qty: Optional[float] = None,
        avg_price: Optional[float] = None,
    ) -> None:
        sets, params = ["updated_at = ?"], [utc_now()]
        if state is not None:
            sets.append("state = ?")
            params.append(state)
        if exchange_order_id is not None:
            sets.append("exchange_order_id = ?")
            params.append(exchange_order_id)
        if filled_qty is not None:
            sets.append("filled_qty = ?")
            params.append(filled_qty)
        if avg_price is not None:
            sets.append("avg_price = ?")
            params.append(avg_price)
        params.append(client_order_id)
        with self._conn:
            self._conn.execute(
                f"UPDATE orders SET {', '.join(sets)} WHERE client_order_id = ?", params
            )

    def get_order(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
        ).fetchone()
        return dict(row) if row else None

    def orders_for_intent(self, intent_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE intent_id = ? ORDER BY created_at", (intent_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def pending_orders(self) -> List[Dict[str, Any]]:
        marks = ",".join("?" for _ in PENDING_ORDER_STATES)
        rows = self._conn.execute(
            f"SELECT * FROM orders WHERE state IN ({marks}) ORDER BY created_at",
            PENDING_ORDER_STATES,
        ).fetchall()
        return [dict(r) for r in rows]

    def orders_in_states(
        self, states: List[str], kinds: Optional[tuple] = None,
    ) -> List[Dict[str, Any]]:
        """按状态（可选按角色）列出订单行——保护残留审计（G0-4C C6）用。"""
        marks = ",".join("?" for _ in states)
        sql = f"SELECT * FROM orders WHERE state IN ({marks})"
        params: List[Any] = list(states)
        if kinds:
            sql += f" AND order_kind IN ({','.join('?' for _ in kinds)})"
            params.extend(kinds)
        rows = self._conn.execute(sql + " ORDER BY created_at", params).fetchall()
        return [dict(r) for r in rows]

    # ---------- 成交 ----------

    def insert_fill(
        self, fill_id: str, client_order_id: str, qty: float, price: float,
        fee: float, side: str, filled_at: str, realized_pnl: float = 0.0,
        synthetic: bool = False, replaces_synthetic_fill_id: Optional[str] = None,
        covered_by_fact_id: Optional[str] = None, economic_effect_applied: bool = True,
    ) -> bool:
        """幂等入账：fill_id 已存在返回 False，不重复记账。"""
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO fills (fill_id, client_order_id, qty, price, fee,"
                    " realized_pnl, side, filled_at, synthetic,"
                    " replaces_synthetic_fill_id, covered_by_fact_id,"
                    " quantity_effect_applied, economic_effect_applied)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (fill_id, client_order_id, qty, price, fee, realized_pnl,
                     side, filled_at, int(synthetic), replaces_synthetic_fill_id,
                     covered_by_fact_id, int(economic_effect_applied)),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def record_reconciliation_fact(
        self, fact_id: str, client_order_id: str,
        covered_fill_ids: list, exchange_executed_qty: float,
    ) -> None:
        """记录对账事实证据：明确列出本次已覆盖的 venue trade IDs。"""
        import json as _json
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO reconciliation_facts"
                " (fact_id, client_order_id, covered_fill_ids,"
                "  exchange_executed_qty, captured_at) VALUES (?, ?, ?, ?, ?)",
                (fact_id, client_order_id, _json.dumps(sorted(covered_fill_ids)),
                 exchange_executed_qty, utc_now()),
            )

    def evidence_covers_fill(self, fill_id: str) -> Optional[str]:
        """返回把该 venue fill_id 明确列为已覆盖的 reconciliation fact_id。"""
        import json as _json
        rows = self._conn.execute(
            "SELECT fact_id, covered_fill_ids FROM reconciliation_facts"
        ).fetchall()
        for row in rows:
            try:
                if fill_id in _json.loads(row["covered_fill_ids"]):
                    return row["fact_id"]
            except Exception:
                continue
        return None

    def open_synthetic_fills(self, client_order_id: str) -> list:
        """尚未被真实 Fill 替换的合成调整（用于替换定位）。"""
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE client_order_id = ? AND synthetic = 1"
            " AND covered_by_fact_id IS NULL ORDER BY filled_at",
            (client_order_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_synthetic_replaced(self, synthetic_fill_id: str, by_real_fill_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE fills SET covered_by_fact_id = ? WHERE fill_id = ?",
                (f"replaced-by:{by_real_fill_id}", synthetic_fill_id),
            )

    def fill_exists(self, fill_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM fills WHERE fill_id = ?", (fill_id,)
        ).fetchone()
        return row is not None

    def get_fill(self, fill_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM fills WHERE fill_id = ?", (fill_id,)
        ).fetchone()
        return dict(row) if row else None

    def fills_for_order(self, client_order_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE client_order_id = ? ORDER BY filled_at", (client_order_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def fills_aggregate(self, client_order_id: str) -> Dict[str, Any]:
        """权威成交聚合（G0-4B B1）。

        fills 是执行事实；orders.filled_qty 只是可重建投影。聚合口径：
        - quantity_effect_applied = 1 才计入数量；
        - economic_effect_applied = 0 的证据行（COVERED_BY_FACT，其数量已由
          reconciliation fact 表达）不计入；
        - 已被真实成交替换的合成调整（synthetic=1 且 covered_by_fact_id 非空）
          不计入，替换它的真实成交按自身口径计入。
        """
        row = self._conn.execute(
            "SELECT COALESCE(SUM(qty), 0.0) AS qty,"
            " COALESCE(SUM(qty * price), 0.0) AS notional,"
            " COUNT(*) AS n FROM fills"
            " WHERE client_order_id = ? AND quantity_effect_applied = 1"
            " AND economic_effect_applied = 1"
            " AND NOT (synthetic = 1 AND covered_by_fact_id IS NOT NULL)",
            (client_order_id,),
        ).fetchone()
        qty = float(row["qty"])
        notional = float(row["notional"])
        return {
            "qty": qty,
            "notional": notional,
            "avg_price": (notional / qty) if qty > 1e-12 else 0.0,
            "fills": int(row["n"]),
        }

    def sync_order_projection_from_fills(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """把 orders.filled_qty 收敛为权威聚合（G0-4B B1）。

        投影单调不减：聚合小于现值（如 fills 尚未拉全）时不回退旧值。
        状态只随事实推进（凑满全量 → FILLED），绝不改写
        REJECTED/CANCELLED/SUBMIT_UNKNOWN 等提交结果语义。
        """
        order = self.get_order(client_order_id)
        if order is None:
            return None
        agg = self.fills_aggregate(client_order_id)
        current = float(order["filled_qty"] or 0.0)
        merged = max(current, agg["qty"])
        if merged > current + 1e-12:
            self.update_order(client_order_id, filled_qty=merged)
        state = order["state"]
        if (
            agg["qty"] > 1e-12
            and agg["qty"] + 1e-12 >= float(order["quantity"])
            and state in ("SUBMITTING", "NEW", "ACTIVE", "PARTIALLY_FILLED")
        ):
            self.update_order(client_order_id, state="FILLED")
        elif agg["qty"] > 1e-12 and state == "SUBMITTING":
            self.update_order(client_order_id, state="PARTIALLY_FILLED")
        return {"filled_qty": merged, "aggregate": agg["qty"], "fills": agg["fills"]}

    # ---------- Kill Switch ----------

    def engage_kill(self, reason: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE kill_switch SET engaged = 1, reason = ?, engaged_at = ? WHERE id = 1",
                (reason, utc_now()),
            )

    def kill_state(self) -> Dict[str, Any]:
        row = self._conn.execute("SELECT * FROM kill_switch WHERE id = 1").fetchone()
        return dict(row) if row else {"engaged": 0, "reason": ""}

    def clear_kill(self, reason: str = "manual") -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE kill_switch SET engaged = 0, reason = ?, engaged_at = ? WHERE id = 1",
                (f"cleared: {reason}", utc_now()),
            )

    # ---------- 持仓事实 ----------

    def set_position_fact(
        self, symbol: str, state: PositionFactState, qty: float = 0.0,
        side: str = "FLAT", source: str = "", note: str = "",
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO position_facts (symbol, state, qty, side, source, note, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(symbol) DO UPDATE SET state=excluded.state, qty=excluded.qty,"
                " side=excluded.side, source=excluded.source, note=excluded.note,"
                " updated_at=excluded.updated_at",
                (symbol, state.value, qty, side, source, note, utc_now()),
            )

    def get_position_fact(self, symbol: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM position_facts WHERE symbol = ?", (symbol,)
        ).fetchone()
        return dict(row) if row else None

    # ---------- 审计 ----------

    def _log_transition(self, transition) -> None:
        self._conn.execute(
            "INSERT INTO transitions (entity_type, entity_id, from_state, to_state,"
            " at, reason, correlation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (transition.entity_type, transition.entity_id, transition.from_state,
             transition.to_state, transition.at, transition.reason, transition.correlation_id),
        )

    def transitions_for(self, entity_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM transitions WHERE entity_id = ? ORDER BY id", (entity_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def all_transitions(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM transitions ORDER BY id").fetchall()
        return [dict(r) for r in rows]
