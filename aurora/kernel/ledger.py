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

from ..p0_boundary import SafetyViolation
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

-- E0：资本事实表。baseline 是单行不可变事实（一经写入不得改写，
-- 换 baseline = 显式新事实，不允许静默漂移）；income_events 是账户级
-- 资金费/收入事实（有符号金额，交易所事件时间为 cursor 真源）。
CREATE TABLE IF NOT EXISTS capital_baseline (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    symbol      TEXT NOT NULL,
    amount      REAL NOT NULL,
    asset       TEXT NOT NULL DEFAULT 'USDT',
    source      TEXT NOT NULL,        -- wallet_snapshot | backderived | constructor_fallback
    note        TEXT DEFAULT '',
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS income_events (
    income_id   TEXT PRIMARY KEY,     -- f"{tranId}:{time}:{symbol}"
    symbol      TEXT NOT NULL,
    income_type TEXT NOT NULL,        -- E0 只写 FUNDING_FEE
    amount      REAL NOT NULL,        -- 有符号：正=收到，负=支付
    asset       TEXT NOT NULL,
    time_ms     INTEGER NOT NULL,     -- 交易所事件时间（cursor 真源）
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_income_events_time ON income_events(time_ms);
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


class FillIdentityConflict(Exception):
    """同一 fill_id 以不同内容重放——身份冲突，必须告警。"""


class RecomputeIdentityConflict(Exception):
    """同一重算身份（完整成交身份 + ctx 对 + 依据）以不同金额重放。

    一致内容才是幂等；同身份金额不同 = 显式冲突，原记录保留。
    """


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
        *, venue_symbol: Optional[str] = None,
        venue_qty_raw: Optional[str] = None,
        venue_price_raw: Optional[str] = None,
        venue_fee_raw: Optional[str] = None,
        venue_fee_asset: Optional[str] = None,
        venue_derivation_ctx: Optional[str] = None,
    ) -> bool:
        """幂等入账：完整身份 (symbol, fill_id) 已存在且内容一致返回
        False（不重复记账）。

        W43 复审收紧：同一身份以**不同内容**（qty/price/side/
        client_order_id）再次到达 = 身份冲突，抛 FillIdentityConflict
        告警——绝不静默忽略。S2 复审 Fix 1：venue 事实随 INSERT
        一次性写入（不允许先 INSERT 再按裸 fill_id UPDATE）；读写、
        唯一冲突定位全部使用复合身份。
        """
        _s1_cols = {"symbol", "origin", "qty_raw", "price_raw",
                    "fee_raw", "fee_asset", "derivation_ctx"}
        _cols = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(fills)")}
        _has_s1 = _s1_cols.issubset(_cols)
        _has_venue = (venue_symbol is not None
                      or venue_qty_raw is not None
                      or venue_price_raw is not None
                      or venue_fee_raw is not None
                      or venue_fee_asset is not None
                      or venue_derivation_ctx is not None)
        if _has_venue and not _has_s1:
            raise SafetyViolation(
                "venue facts require S1 schema columns"
                f" (missing: {sorted(_s1_cols - _cols)});"
                " run isolated migration first; refusing to"
                " silently drop venue facts")
        try:
            with self._conn:
                if _has_s1:
                    if venue_symbol is not None:
                        # Fix 1: 复合身份一次性 INSERT——symbol/origin/
                        # raw/推导上下文随主写入原子落库；PK
                        # (symbol, fill_id) 由 schema 强制。
                        self._conn.execute(
                            "INSERT INTO fills (fill_id, symbol, origin,"
                            " client_order_id, qty, qty_raw, price,"
                            " price_raw, fee, fee_raw, fee_asset,"
                            " realized_pnl, derivation_ctx, side,"
                            " filled_at, synthetic,"
                            " replaces_synthetic_fill_id,"
                            " covered_by_fact_id,"
                            " quantity_effect_applied,"
                            " economic_effect_applied)"
                            " VALUES (?, ?, 'EVENT',"
                            " ?, ?, ?, ?, ?, ?, ?, ?,"
                            " ?, ?, ?, ?, ?, ?, ?,"
                            " 1, ?)",
                            (fill_id, venue_symbol, client_order_id,
                             qty, venue_qty_raw, price, venue_price_raw,
                             fee, venue_fee_raw, venue_fee_asset,
                             realized_pnl, venue_derivation_ctx, side,
                             filled_at, int(synthetic),
                             replaces_synthetic_fill_id,
                             covered_by_fact_id,
                             int(economic_effect_applied)))
                    else:
                        self._conn.execute(
                            "INSERT INTO fills (fill_id, client_order_id,"
                            " qty, price, fee, realized_pnl, side,"
                            " filled_at, synthetic,"
                            " replaces_synthetic_fill_id,"
                            " covered_by_fact_id, quantity_effect_applied,"
                            " economic_effect_applied, origin)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                            " 1, ?, 'LEGACY')",
                            (fill_id, client_order_id, qty, price, fee,
                             realized_pnl, side, filled_at, int(synthetic),
                             replaces_synthetic_fill_id,
                             covered_by_fact_id,
                             int(economic_effect_applied)))
                else:
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
        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            msg_u = msg.upper()
            if "FOREIGN" in msg_u or "CHECK" in msg_u or "NOT NULL" in msg_u:
                raise  # T-DB1/DB2/W3：FK/CHECK/NOT NULL 不吞成 DUPLICATE
            if "UNIQUE" not in msg_u:
                raise  # 非 UNIQUE 一律上抛
            # Fix 4：解析 UNIQUE 目标——SQLite 消息格式
            # "UNIQUE constraint failed: <table>.<col>[, <table>.<col>...]"
            # 仅当目标恰好是 fills 表的成交身份键（fill_id 或
            # symbol+fill_id 复合）才进入重复比较；其他表/列的
            # UNIQUE（含触发器引起的）一律上抛。
            target = msg.split(":", 1)[-1].strip() if ":" in msg else ""
            target_cols = {c.strip().lower() for c in target.split(",")}
            fills_targets = {
                frozenset({"fills.fill_id"}),
                frozenset({"fills.symbol", "fills.fill_id"}),
            }
            if frozenset(target_cols) not in fills_targets:
                raise  # 非目标 UNIQUE（评审触发器复现路径）
            # Fix 1: 按复合身份定位既有行——venue 插入用 venue_symbol；
            # LEGACY 插入（symbol NULL）只可能命中 partial unique 的
            # NULL-symbol 行。SELECT 列集按实际 schema 取（旧库无 S1 列）。
            _q_symbol = venue_symbol
            if _has_s1:
                existing = self._conn.execute(
                    "SELECT client_order_id, qty, price, side, symbol,"
                    " qty_raw, price_raw, fee_raw, fee_asset, origin,"
                    " realized_pnl, derivation_ctx FROM fills"
                    " WHERE fill_id = ? AND (symbol IS ? OR"
                    "  (? IS NULL AND symbol IS NULL))",
                    (fill_id, _q_symbol, _q_symbol)).fetchone()
            else:
                existing = self._conn.execute(
                    "SELECT client_order_id, qty, price, side FROM fills"
                    " WHERE fill_id = ?", (fill_id,)).fetchone()
            if existing is None:
                raise  # 无法以完整身份定位——上抛
            # Fix 2: 按两侧 origin 分别走 EVENT raw 校验 / HISTORY /
            # 混合模式——不再一律包装为 HISTORY（评审 2 复现关闭）
            from aurora.kernel.fill_identity import (
                compare_as, compare_mixed,
            )
            _stored_origin = (existing["origin"]
                              if "origin" in existing.keys() else None)
            _incoming_is_event = venue_symbol is not None
            if _stored_origin == "EVENT" and _incoming_is_event:
                # 两侧 EVENT：同等级 raw 校验（raw 是权威，REAL 不参与）
                _stored = {
                    "client_order_id": existing["client_order_id"],
                    "symbol": existing["symbol"],
                    "side": existing["side"],
                    "qty_raw": existing["qty_raw"],
                    "price_raw": existing["price_raw"],
                    "fee_raw": existing["fee_raw"],
                    "fee_asset": existing["fee_asset"],
                }
                _incoming = {
                    "client_order_id": client_order_id,
                    "symbol": venue_symbol, "side": side,
                    "qty_raw": venue_qty_raw,
                    "price_raw": venue_price_raw,
                    "fee_raw": venue_fee_raw,
                    "fee_asset": venue_fee_asset,
                }
                report = compare_as("EVENT", _stored, _incoming)
            elif _stored_origin == "EVENT" or _incoming_is_event:
                # 一侧 EVENT 一侧 LEGACY → 混合（跨等级冻结语义：
                # 离散冲突暴露，数值不可证实）
                if _stored_origin == "EVENT":
                    _lg_incoming = {
                        "client_order_id": client_order_id,
                        "symbol": None, "side": side,
                        "qty": qty, "price": price,
                        "fee": None, "fee_asset": None,
                    }
                    _ev_stored = {
                        "origin": "EVENT",
                        "client_order_id": existing["client_order_id"],
                        "symbol": existing["symbol"],
                        "side": existing["side"],
                        "qty_raw": existing["qty_raw"],
                        "price_raw": existing["price_raw"],
                        "fee_raw": existing["fee_raw"],
                        "fee_asset": existing["fee_asset"],
                    }
                    report = compare_mixed(_lg_incoming, _ev_stored)
                else:
                    _legacy = {
                        "client_order_id": existing["client_order_id"],
                        "symbol": existing["symbol"] if _has_s1 else None,
                        "side": existing["side"],
                        "qty": existing["qty"], "price": existing["price"],
                        "fee": None, "fee_asset": None,
                    }
                    _event = {
                        "origin": "EVENT",
                        "client_order_id": client_order_id,
                        "symbol": venue_symbol, "side": side,
                        "qty_raw": venue_qty_raw,
                        "price_raw": venue_price_raw,
                        "fee_raw": venue_fee_raw,
                        "fee_asset": venue_fee_asset,
                    }
                    report = compare_mixed(_legacy, _event)
            else:
                # 两侧 LEGACY → HISTORY（历史近似口径）
                _stored = {
                    "client_order_id": existing["client_order_id"],
                    "symbol": None, "side": existing["side"],
                    "qty": existing["qty"], "price": existing["price"],
                    "fee": None, "fee_asset": None,
                }
                _incoming = {
                    "client_order_id": client_order_id, "symbol": None,
                    "side": side, "qty": qty, "price": price,
                    "fee": None, "fee_asset": None,
                }
                report = compare_as("HISTORY", _stored, _incoming)
            if report["verdict"] == "MISMATCH":
                raise FillIdentityConflict(
                    f"fill {fill_id!r} identity conflict on fields"
                    f" {report['conflict_fields']}: stored_origin="
                    f"{_stored_origin}; composite key"
                    f" ({_q_symbol!r}, {fill_id!r})")
            # MATCH/INCOMPLETE → 幂等
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

    def evidence_covers_fill(
        self, fill_id: str, client_order_id: Optional[str] = None,
    ) -> Optional[str]:
        """返回把该 venue fill_id 明确列为已覆盖的 reconciliation
        fact_id（R2 修正：覆盖证据按订单归属核验）。

        fact 必须属于同一 client_order_id——跨订单/跨 symbol 的同
        trade ID 不得自动套用他方覆盖证据（否则另一订单的成交经济
        影响被静默豁免）。client_order_id 未提供时按无证据处理
        （fail-closed，不再全表裸 ID 匹配）。
        """
        import json as _json
        if client_order_id is None:
            return None
        rows = self._conn.execute(
            "SELECT fact_id, covered_fill_ids FROM reconciliation_facts"
            " WHERE client_order_id = ?", (client_order_id,)).fetchall()
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

    def fill_exists(self, fill_id: str,
                    symbol: Optional[str] = None) -> bool:
        """Fix 1：完整身份查询——提供 symbol 时按复合键 (symbol,
        fill_id) 精确匹配；未提供（旧调用方）在 S1 库等价 NULL-symbol
        历史行匹配（base schema fill_id 即 PK）。base schema 无
        symbol 列 → 退化为 fill_id 查询（venue 行不可能存在）。"""
        if symbol is not None and self._fills_has_symbol():
            row = self._conn.execute(
                "SELECT 1 FROM fills WHERE symbol IS ? AND fill_id = ?",
                (symbol, fill_id,)).fetchone()
            return row is not None
        row = self._conn.execute(
            "SELECT 1 FROM fills WHERE fill_id = ?", (fill_id,)
        ).fetchone()
        return row is not None

    def get_fill(self, fill_id: str,
                 symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fix 1：完整身份读取——语义同 fill_exists（venue 路径必须
        传 symbol；裸 fill_id 仅用于 NULL-symbol 历史行/旧 schema）。
        注意：裸读在多行同 fill_id 时命中任意一行（受插入顺序影
        响）——需要确定性 NULL 历史行请用 get_legacy_fill。"""
        if symbol is not None and self._fills_has_symbol():
            row = self._conn.execute(
                "SELECT * FROM fills WHERE symbol IS ? AND fill_id = ?",
                (symbol, fill_id,)).fetchone()
            return dict(row) if row else None
        row = self._conn.execute(
            "SELECT * FROM fills WHERE fill_id = ?", (fill_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_legacy_fill(self, fill_id: str) -> Optional[Dict[str, Any]]:
        """显式查询同 fill_id 的 NULL-symbol 历史行（R1 修正）。

        裸 ID 探测会受插入顺序影响命中任意一行；legacy-shadow 语义
        必须确定性指向 NULL-symbol 行（resolve_fill_ref 的
        UNRESOLVED_NULL_LEGACY 定位）。base schema（fill_id 即 PK）
        等价于 get_fill。
        """
        if self._fills_has_symbol():
            row = self._conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?"
                " AND symbol IS NULL", (fill_id,)).fetchone()
            return dict(row) if row else None
        return self.get_fill(fill_id)

    def _fills_has_symbol(self) -> bool:
        cols = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(fills)")}
        return "symbol" in cols

    def fills_for_order(self, client_order_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE client_order_id = ? ORDER BY filled_at", (client_order_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_economic_fills_with_context(self) -> List[Dict[str, Any]]:
        """E0：权威经济影响成交，附带 order_kind / intent_id 上下文。"""
        rows = self._conn.execute(
            "SELECT f.*, o.order_kind, o.intent_id"
            " FROM fills f"
            " JOIN orders o ON f.client_order_id = o.client_order_id"
            " WHERE f.economic_effect_applied = 1"
            " AND NOT (f.synthetic = 1 AND f.covered_by_fact_id IS NOT NULL)"
            " ORDER BY f.filled_at, f.fill_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_baseline(
        self,
        symbol: str,
        amount: float,
        asset: str = "USDT",
        source: str = "wallet_snapshot",
        note: str = "",
    ) -> bool:
        """E0：写入资本基线（单行不可变事实）。

        INSERT OR IGNORE：已存在 baseline 时二次写入不覆盖、返回 False。
        换 baseline = 显式新事实（先人工处理旧行），禁止静默漂移。
        """
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO capital_baseline"
                " (id, symbol, amount, asset, source, note, recorded_at)"
                " VALUES (1, ?, ?, ?, ?, ?, ?)",
                (symbol, float(amount), asset, source, note, utc_now()),
            )
        return cur.rowcount > 0

    def get_baseline(self) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM capital_baseline WHERE id = 1"
        ).fetchone()
        return dict(row) if row else None

    def insert_income_event(
        self,
        income_id: str,
        symbol: str,
        income_type: str,
        amount: float,
        time_ms: int,
        asset: str = "USDT",
    ) -> bool:
        """E0：幂等写入 funding / income 事实（有符号 amount）。"""
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO income_events"
                    " (income_id, symbol, income_type, amount, asset, time_ms, recorded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (income_id, symbol, income_type, amount, asset, time_ms, utc_now()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def list_income_events(self, income_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if income_type:
            rows = self._conn.execute(
                "SELECT * FROM income_events WHERE income_type = ? ORDER BY time_ms, income_id",
                (income_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM income_events ORDER BY time_ms, income_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def max_income_time_ms(self, income_type: Optional[str] = None) -> int:
        if income_type:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(time_ms), 0) AS m FROM income_events WHERE income_type = ?",
                (income_type,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(time_ms), 0) AS m FROM income_events"
            ).fetchone()
        return int(row["m"])

    def sum_funding_net(self, income_type: str = "FUNDING_FEE") -> float:
        """Signed funding sum (Binance: negative = paid out)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) AS s FROM income_events WHERE income_type = ?",
            (income_type,),
        ).fetchone()
        return float(row["s"])

    def accounting_aggregate(self) -> Dict[str, Any]:
        """E0/E1：fills + funding income 聚合。"""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) AS gross,"
            " COALESCE(SUM(fee), 0.0) AS fees,"
            " COUNT(*) AS n"
            " FROM fills"
            " WHERE economic_effect_applied = 1"
            " AND NOT (synthetic = 1 AND covered_by_fact_id IS NOT NULL)"
        ).fetchone()
        gross = float(row["gross"])
        fees = float(row["fees"])
        funding_net = self.sum_funding_net()
        return {
            "gross_realized_pnl": gross,
            "total_fees": fees,
            "funding_net": funding_net,
            "funding_paid": -funding_net,
            "net_pnl": gross - fees + funding_net,
            "fill_count": int(row["n"]),
        }

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

    # ---------- 推导重算与 DEVIATION（Fix 5：T-D2/D3） ----------

    _MACHINE_REF_PREFIXES = ("fill:", "order:", "fact:", "recompute:",
                             "recomputation-event:")

    def _validate_resolution_ref(self, ref: str) -> str:
        """Fix 4 / R4：机器引用必须完整解析；说明走独立 detail。

        首 token 命中机器前缀（fill:/order:/fact:/recompute:/
        recomputation-event:）即声明为机器引用——整串必须严格单
        token 并解析到已存在目标；附加文字不得使其降级为人工依据
        （拒绝并指向 detail 参数）。无机器前缀 = 人工处置文本
        （非空即可）。
        """
        import re as _re
        from aurora.kernel.fill_identity import validate_new_ref
        stripped = (ref or "").strip()
        if not stripped:
            raise SafetyViolation(
                "resolution_ref must be non-empty (machine ref must"
                " resolve or operator disposition must be stated)")
        first = stripped.split(None, 1)[0]
        if first.startswith(("fill:", "order:", "fact:", "recompute:",
                             "recomputation-event:")):
            # 机器引用意图已声明：整串必须严格单 token
            strict = _re.fullmatch(
                r"(fill|order|fact|recompute|recomputation-event):[^\s]+",
                stripped)
            if strict is None:
                raise SafetyViolation(
                    f"machine ref carries trailing text: {stripped!r};"
                    " the reference must fully resolve — move the"
                    " explanation to the detail parameter")
            kind, target = stripped.split(":", 1)
            if kind == "fill":
                res = validate_new_ref(self._conn, target)
                if not res["ok"]:
                    raise SafetyViolation(
                        f"machine fill ref does not resolve: {stripped!r}"
                        f" ({res['reason']})")
                return stripped
            if kind == "order":
                row = self._conn.execute(
                    "SELECT 1 FROM orders WHERE client_order_id = ?",
                    (target,)).fetchone()
                if row is None:
                    raise SafetyViolation(
                        f"machine order ref does not resolve: {stripped!r}")
                return stripped
            if kind == "fact":
                row = self._conn.execute(
                    "SELECT 1 FROM reconciliation_facts WHERE fact_id = ?",
                    (target,)).fetchone()
                if row is None:
                    raise SafetyViolation(
                        f"machine fact ref does not resolve: {stripped!r}")
                return stripped
            # recompute / recomputation-event
            try:
                rid = int(target)
            except ValueError:
                raise SafetyViolation(
                    f"machine recomputation ref malformed: {stripped!r}")
            try:
                row = self._conn.execute(
                    "SELECT 1 FROM fill_recomputations WHERE id = ?",
                    (rid,)).fetchone()
            except sqlite3.OperationalError:
                row = None
            if row is None:
                raise SafetyViolation(
                    f"machine recomputation ref does not resolve:"
                    f" {stripped!r}")
            return stripped
        return stripped  # 人工处置文本（无机器前缀）

    def append_resolution_record(self, kind: str, entity_id: str,
                                 resolution_ref: str,
                                 detail: str = "") -> int:
        """Fix 4：解决记录（append-only）——解除任何阻断标志前必须
        先落此记录，形成持久审计链（不是非空字符串检查）。"""
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS resolution_log ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " kind TEXT NOT NULL,"
                " entity_id TEXT NOT NULL,"
                " resolution_ref TEXT NOT NULL,"
                " detail TEXT NOT NULL DEFAULT '',"
                " resolved_at TEXT NOT NULL)")
            cur = self._conn.execute(
                "INSERT INTO resolution_log"
                " (kind, entity_id, resolution_ref, detail, resolved_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (kind, entity_id, resolution_ref, detail, utc_now()))
            return cur.lastrowid

    def resolution_records(self, kind: Optional[str] = None,
                           entity_id: Optional[str] = None) -> list:
        try:
            sql = "SELECT * FROM resolution_log"
            conds, params = [], []
            if kind is not None:
                conds.append("kind = ?")
                params.append(kind)
            if entity_id is not None:
                conds.append("entity_id = ?")
                params.append(entity_id)
            if conds:
                sql += " WHERE " + " AND ".join(conds)
            rows = self._conn.execute(
                sql + " ORDER BY id", params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    _RECOMPUTE_IDENT_INDEX = "ux_fill_recompute_ident"

    def _ensure_recompute_schema(self) -> None:
        """R3-3：重算表 schema 升级的原子边界（调用方事务前置条件）。

        - 事务前置条件：连接存在未提交事务 → 直接拒绝（与 S1 迁移
          口径一致）。不加入调用方事务、不替调用方 commit/rollback、
          不改连接配置——否则升级 DDL 会挂进外层事务（失败半升级）
          或方法自身的事务会把调用方未提交数据一并提交。
        - 升级 = 补 symbol 列 + 唯一索引 + 版本标记（schema_upgrade_log）
          三者同一显式事务，失败整体回滚（无半升级）。
        - 升级前预检历史同身份重复：存在即明确阻断（列明冲突组），
          绝不自动删除/合并历史事件。索引在位 = 升级完成（快速路径，
          同样受事务前置条件约束）。
        """
        if self._conn.in_transaction:
            raise SafetyViolation(
                "_ensure_recompute_schema must own its transaction:"
                " caller connection has an open transaction; refusing"
                " to join it (finish or rollback the outer transaction"
                " first) — DDL joining a caller transaction can leave"
                " a half-upgrade on its commit")
        have_idx = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name = ?", (self._RECOMPUTE_IDENT_INDEX,)).fetchone()
        if have_idx is not None:
            return  # 升级已完成（列+索引+标记同事务原子落成）
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS fill_recomputations ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " fill_id TEXT NOT NULL,"
                " old_value REAL NOT NULL,"
                " new_value REAL NOT NULL,"
                " old_ctx TEXT, new_ctx TEXT,"
                " basis_ref TEXT,"
                " symbol TEXT,"
                " reason TEXT NOT NULL,"
                " recomputed_at TEXT NOT NULL)")
            _rc = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(fill_recomputations)")}
            if "symbol" not in _rc:
                self._conn.execute(
                    "ALTER TABLE fill_recomputations"
                    " ADD COLUMN symbol TEXT")
            dups = self._conn.execute(
                "SELECT COALESCE(symbol, '') s, fill_id,"
                " COALESCE(old_ctx, '') oc, COALESCE(new_ctx, '') nc,"
                " COALESCE(basis_ref, '') bc, COUNT(*) c"
                " FROM fill_recomputations"
                " GROUP BY s, fill_id, oc, nc, bc"
                " HAVING c > 1 LIMIT 5").fetchall()
            if dups:
                raise SafetyViolation(
                    "pre-existing duplicate recomputation identities"
                    " block the identity-index upgrade (no auto"
                    " adjudication — historical events are never"
                    " deleted or merged): "
                    + "; ".join(
                        f"(symbol={r['s']!r}, fill_id={r['fill_id']!r},"
                        f" old_ctx={r['oc']!r}, new_ctx={r['nc']!r},"
                        f" basis_ref={r['bc']!r}, count={r['c']})"
                        for r in dups))
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS"
                f" {self._RECOMPUTE_IDENT_INDEX} ON fill_recomputations ("
                " COALESCE(symbol, ''), fill_id,"
                " COALESCE(old_ctx, ''), COALESCE(new_ctx, ''),"
                " COALESCE(basis_ref, ''))")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_upgrade_log ("
                " component TEXT PRIMARY KEY,"
                " upgraded_at TEXT NOT NULL)")
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_upgrade_log"
                " (component, upgraded_at) VALUES (?, ?)",
                ("fill_recomputations_identity", utc_now()))
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise  # 整体回滚：列/索引/版本标记同生同灭

    def _lookup_recompute_identity(
        self, symbol: Optional[str], fill_id: str,
        old_ctx: Optional[str], new_ctx: Optional[str],
        basis_ref: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """按稳定重算身份查既有记录（id + 金额内容）。"""
        return self._conn.execute(
            "SELECT id, old_value, new_value FROM fill_recomputations WHERE"
            " COALESCE(symbol, '') = COALESCE(?, '')"
            " AND fill_id = ?"
            " AND COALESCE(old_ctx, '') = COALESCE(?, '')"
            " AND COALESCE(new_ctx, '') = COALESCE(?, '')"
            " AND COALESCE(basis_ref, '') = COALESCE(?, '')",
            (symbol, fill_id, old_ctx, new_ctx,
             basis_ref)).fetchone()

    def append_fill_recomputation(
        self, fill_id: str, old_value: float, new_value: float,
        reason: str, *, old_ctx: Optional[str] = None,
        new_ctx: Optional[str] = None, basis_ref: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> int:
        """显式重算事件（append-only，Fix 4 / R3 强化）。

        - fill_id 必须已存在于 fills 表（提供符号时按复合身份验证）；
        - 必须提供冻结依据三元组 old_ctx/new_ctx/basis_ref；
        - basis_ref 是机器引用时必须解析到已存在目标；
        - R3：稳定身份 = 完整成交身份 (symbol, fill_id) + ctx 对 +
          依据。**一致内容才是幂等**：同身份同金额重放返回既有 id
          零追加；同身份金额不同 = RecomputeIdentityConflict（原
          记录保留）。并发窗口由唯一索引兜底：捕获本索引冲突后
          重读并比较内容（一致收敛到同一 id，异容报告冲突）；
        - 事务前置条件（R3-3 收尾）：连接存在未提交事务 → 任何
          写入前拒绝（不接管调用方事务，不替其 commit/rollback）；
        - 记录保留完整成交引用（symbol 列）；
        - 不改历史 fill 行。
        """
        if self._conn.in_transaction:
            raise SafetyViolation(
                "append_fill_recomputation must own its transaction:"
                " caller connection has an open transaction; refusing"
                " before any write (the method's own commit would"
                " otherwise publish the caller's uncommitted changes;"
                " finish or rollback the outer transaction first)")
        for _n, _v in (("old_ctx", old_ctx), ("new_ctx", new_ctx),
                       ("basis_ref", basis_ref)):
            if _v is None or not str(_v).strip():
                raise SafetyViolation(
                    f"recomputation requires frozen basis {_n}"
                    f" for fill {fill_id!r}; refusing to append"
                    " unattributed recomputation")
        self._validate_resolution_ref(str(basis_ref))
        self._ensure_recompute_schema()
        with self._conn:
            if symbol is not None:
                exists = self._conn.execute(
                    "SELECT 1 FROM fills WHERE symbol IS ? AND fill_id = ?",
                    (symbol, fill_id)).fetchone()
            else:
                exists = self._conn.execute(
                    "SELECT 1 FROM fills WHERE fill_id = ?",
                    (fill_id,)).fetchone()
            if exists is None:
                raise SafetyViolation(
                    f"recomputation references nonexistent fill"
                    f" {fill_id!r}; refusing to append")
            dup = self._lookup_recompute_identity(
                symbol, fill_id, old_ctx, new_ctx, basis_ref)
            if dup is not None:
                if (float(dup["old_value"]) == float(old_value)
                        and float(dup["new_value"]) == float(new_value)):
                    return dup["id"]  # 一致重放：幂等零追加
                raise RecomputeIdentityConflict(
                    f"recomputation identity replayed with different"
                    f" amounts (symbol={symbol!r}, fill_id={fill_id!r},"
                    f" old_ctx={old_ctx!r}, new_ctx={new_ctx!r},"
                    f" basis_ref={basis_ref!r}): stored="
                    f"({dup['old_value']}, {dup['new_value']})"
                    f" incoming=({old_value}, {new_value});"
                    " original record preserved")
            try:
                cur = self._conn.execute(
                    "INSERT INTO fill_recomputations"
                    " (fill_id, old_value, new_value, old_ctx, new_ctx,"
                    "  basis_ref, symbol, reason, recomputed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (fill_id, old_value, new_value, old_ctx, new_ctx,
                     basis_ref, symbol, reason, utc_now()))
                return cur.lastrowid
            except sqlite3.IntegrityError as exc:
                if self._RECOMPUTE_IDENT_INDEX not in str(exc):
                    raise  # 非目标索引冲突（其他异常上抛）
                # 并发一致重放竞态：唯一索引已防双写——重读并比较
                row = self._lookup_recompute_identity(
                    symbol, fill_id, old_ctx, new_ctx, basis_ref)
                if (row is not None
                        and float(row["old_value"]) == float(old_value)
                        and float(row["new_value"]) == float(new_value)):
                    return row["id"]  # 并发一致 → 收敛同一 id
                raise RecomputeIdentityConflict(
                    f"concurrent recomputation replay conflict"
                    f" (symbol={symbol!r}, fill_id={fill_id!r}):"
                    f" index={self._RECOMPUTE_IDENT_INDEX},"
                    f" stored={dict(row) if row else None}"
                    f" incoming=({old_value}, {new_value});"
                    " original record preserved")

    def fill_recomputations(self, fill_id: str) -> list:
        try:
            rows = self._conn.execute(
                "SELECT * FROM fill_recomputations WHERE fill_id = ?"
                " ORDER BY id", (fill_id,)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def mark_pnl_unreliable(self, symbol: str, reason: str) -> None:
        """损益不可依赖标志：阻新增风险（open 已查 unresolved +
        此标志）；不阻减仓。"""
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS pnl_reliability ("
                " symbol TEXT PRIMARY KEY,"
                " unreliable INTEGER NOT NULL DEFAULT 1,"
                " reason TEXT NOT NULL,"
                " marked_at TEXT NOT NULL)")
            self._conn.execute(
                "INSERT OR REPLACE INTO pnl_reliability"
                " (symbol, unreliable, reason, marked_at)"
                " VALUES (?, 1, ?, ?)", (symbol, reason, utc_now()))

    def clear_pnl_unreliable(self, symbol: str,
                             resolution_ref: Optional[str] = None,
                             detail: str = "") -> None:
        """解除 UNRELIABLE（Fix 4 / R4）：依据验证 → 先落解决记录 →
        再删标志（同一事务）。机器引用必须完整解析（附加文字拒绝）；
        说明放 detail，不与引用混写。"""
        self._validate_resolution_ref(resolution_ref or "")
        with self._conn:
            try:
                marked = self._conn.execute(
                    "SELECT reason FROM pnl_reliability WHERE symbol = ?",
                    (symbol,)).fetchone()
            except sqlite3.OperationalError:
                marked = None  # 表未创建=从未标记
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS resolution_log ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " kind TEXT NOT NULL,"
                " entity_id TEXT NOT NULL,"
                " resolution_ref TEXT NOT NULL,"
                " detail TEXT NOT NULL DEFAULT '',"
                " resolved_at TEXT NOT NULL)")
            self._conn.execute(
                "INSERT INTO resolution_log"
                " (kind, entity_id, resolution_ref, detail, resolved_at)"
                " VALUES ('pnl_unreliable_cleared', ?, ?, ?, ?)",
                (symbol, resolution_ref,
                 (f"prior mark reason: {marked['reason']}; {detail}"
                  if marked else detail), utc_now()))
            try:
                self._conn.execute(
                    "DELETE FROM pnl_reliability WHERE symbol = ?",
                    (symbol,))
            except sqlite3.OperationalError:
                pass  # 表未创建=无标志可删；解决记录仍保留
            try:
                self._conn.execute(
                    "DELETE FROM pnl_reliability WHERE symbol = ?",
                    (symbol,))
            except sqlite3.OperationalError:
                pass  # 表未创建=无标志可删；解决记录仍保留

    def pnl_unreliable(self, symbol: str) -> bool:
        """读取损益可靠性。表不存在=正常可靠；其他异常→True。"""
        try:
            row = self._conn.execute(
                "SELECT unreliable FROM pnl_reliability WHERE symbol = ?",
                (symbol,)).fetchone()
            return bool(row and row[0])
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return False  # 表从未创建=正常
            return True  # 真实读取异常 → 不可靠
        except sqlite3.Error:
            return True

    # ---------- Unresolved fill 标志（Fix 2：阻新增不阻减仓） ----------

    def mark_fill_unresolved(self, fill_id: str, reason: str) -> None:
        """持久化未解析标志：跨重启保留；阻新增风险、不阻减仓。"""
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS unresolved_fills ("
                " fill_id TEXT PRIMARY KEY, reason TEXT NOT NULL,"
                " marked_at TEXT NOT NULL)")
            self._conn.execute(
                "INSERT OR REPLACE INTO unresolved_fills"
                " (fill_id, reason, marked_at) VALUES (?, ?, ?)",
                (fill_id, reason, utc_now()))

    def clear_fill_unresolved(self, fill_id: str,
                              resolution_ref: Optional[str] = None,
                              detail: str = "") -> None:
        """解除 unresolved（Fix 4 / R4）：依据验证 → 先落解决记录 →
        再删标志（同一事务）。机器引用必须完整解析（附加文字拒绝）；
        说明放 detail，不与引用混写。"""
        self._validate_resolution_ref(resolution_ref or "")
        with self._conn:
            try:
                marked = self._conn.execute(
                    "SELECT reason FROM unresolved_fills WHERE fill_id = ?",
                    (fill_id,)).fetchone()
            except sqlite3.OperationalError:
                marked = None  # 表未创建=从未标记
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS resolution_log ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " kind TEXT NOT NULL,"
                " entity_id TEXT NOT NULL,"
                " resolution_ref TEXT NOT NULL,"
                " detail TEXT NOT NULL DEFAULT '',"
                " resolved_at TEXT NOT NULL)")
            self._conn.execute(
                "INSERT INTO resolution_log"
                " (kind, entity_id, resolution_ref, detail, resolved_at)"
                " VALUES ('unresolved_cleared', ?, ?, ?, ?)",
                (fill_id, resolution_ref,
                 (f"prior mark reason: {marked['reason']}; {detail}"
                  if marked else detail), utc_now()))
            try:
                self._conn.execute(
                    "DELETE FROM unresolved_fills WHERE fill_id = ?",
                    (fill_id,))
            except sqlite3.OperationalError:
                pass  # 表未创建=无标志可删；解决记录仍保留

    def unresolved_fill_ids(self):
        """读取未解析标志。表不存在=空状态（正常）；其他读取异常
        → 哨兵（阻新增方向）。"""
        try:
            rows = self._conn.execute(
                "SELECT fill_id FROM unresolved_fills").fetchall()
            return [r[0] for r in rows]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []  # 表从未创建=正常空状态
            return ["<READ_ERROR>"]  # 真实读取异常 → 哨兵
        except sqlite3.Error:
            return ["<READ_ERROR>"]

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
        # R3-3 收尾：独立调用时必须自持事务（此前裸 execute 留下
        # 未提交的隐式事务，泄漏到后续写入方——append 的事务前置
        # 条件守卫暴露了它）；被外层 with-block 调用时加入外层事务
        # （嵌套 with 会在中途提交外层部分写，禁止）。
        sql = ("INSERT INTO transitions (entity_type, entity_id,"
               " from_state, to_state, at, reason, correlation_id)"
               " VALUES (?, ?, ?, ?, ?, ?, ?)")
        params = (transition.entity_type, transition.entity_id,
                  transition.from_state, transition.to_state,
                  transition.at, transition.reason,
                  transition.correlation_id)
        if self._conn.in_transaction:
            self._conn.execute(sql, params)  # 加入调用方事务
        else:
            with self._conn:
                self._conn.execute(sql, params)

    def transitions_for(self, entity_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM transitions WHERE entity_id = ? ORDER BY id", (entity_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def all_transitions(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM transitions ORDER BY id").fetchall()
        return [dict(r) for r in rows]
