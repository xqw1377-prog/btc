"""FILL IDENTITY S1：迁移与历史兼容（隔离实现——显式调用专用）。

边界（开工裁定 2026-10，见 FILL_IDENTITY_IMPL_PLAN.md §S1 执行边界）：
- 本模块【不】接入 Ledger.__init__ / 生产入口 / 默认启动路径；
  只被显式的测试与演练代码调用。
- 作用对象：临时库、合成旧库、经批准的事故账本副本；原件只读。
- 等价性结论只允许表述为"副本/离线恢复等价性"。
- 新 schema 写入走独立构造器 FillsV2Writer，不吸收 S2 校验逻辑
  （写入校验仅为 raw 合法性与 REAL 派生，非身份内容比较）。
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

SCHEMA_VERSION = "4"
SCHEMA_MARKER_KEY = "fills_identity_version"

OLD_COLS = (
    "fill_id, client_order_id, qty, price, fee, realized_pnl,"
    " side, filled_at, synthetic, replaces_synthetic_fill_id,"
    " covered_by_fact_id, quantity_effect_applied,"
    " economic_effect_applied")

_NEW_DDL = """
CREATE TABLE {name} (
    fill_id          TEXT    NOT NULL,
    symbol           TEXT,
    origin           TEXT    NOT NULL
                     CHECK (origin IN ('LEGACY','EVENT')),
    client_order_id  TEXT    NOT NULL
                     REFERENCES orders(client_order_id),
    qty              REAL    NOT NULL,
    qty_raw          TEXT,
    price            REAL    NOT NULL,
    price_raw        TEXT,
    fee              REAL,
    fee_raw          TEXT,
    fee_asset        TEXT,
    realized_pnl     REAL    NOT NULL DEFAULT 0,
    derivation_ctx   TEXT,
    replaced_by      TEXT,
    side             TEXT    NOT NULL CHECK (side IN ('BUY','SELL')),
    filled_at        TEXT    NOT NULL,
    synthetic        INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0,1)),
    replaces_synthetic_fill_id TEXT,
    covered_by_fact_id        TEXT,
    quantity_effect_applied   INTEGER NOT NULL DEFAULT 1
                              CHECK (quantity_effect_applied IN (0,1)),
    economic_effect_applied   INTEGER NOT NULL DEFAULT 1
                              CHECK (economic_effect_applied IN (0,1)),
    PRIMARY KEY (symbol, fill_id),
    CHECK (typeof(qty)   IN ('real','integer') AND qty   > 0),
    CHECK (typeof(price) IN ('real','integer') AND price > 0),
    CHECK (origin = 'LEGACY' OR symbol IS NOT NULL),
    CHECK (origin = 'LEGACY' OR (qty_raw IS NOT NULL AND qty_raw != ''
                                 AND price_raw IS NOT NULL AND price_raw != '')),
    CHECK (fee_raw IS NULL OR (fee_raw != '' AND fee_asset IS NOT NULL
                               AND fee_asset != ''))
)
"""


class MigrationError(Exception):
    """迁移事务失败（已回滚；原库保持迁移前状态）。"""


def _marker_value(conn) -> Optional[str]:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (SCHEMA_MARKER_KEY,)).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def verify_structure(conn) -> None:
    """结构验证：版本标记 + 复合 PK（symbol,fill_id）+ 唯一索引 + origin 列。"""
    if _marker_value(conn) != SCHEMA_VERSION:
        raise MigrationError("schema marker missing or wrong version")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(fills)")}
    if "origin" not in cols or "qty_raw" not in cols:
        raise MigrationError("fills schema missing S1 columns")
    pk = [r[1] for r in sorted(
        (r for r in conn.execute("PRAGMA table_info(fills)") if r[5] > 0),
        key=lambda r: r[5])]
    if pk != ["symbol", "fill_id"]:
        raise MigrationError(f"fills PK is {pk}, expected [symbol, fill_id]")
    idx = {r[1] for r in conn.execute("PRAGMA index_list(fills)")}
    if "ux_fills_null_symbol" not in idx:
        raise MigrationError("ux_fills_null_symbol index missing")


def reopen_isolated(path: str) -> sqlite3.Connection:
    """隔离重开：版本标记 + 结构验证（PK/索引/origin 列）。"""
    conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        verify_structure(conn)
    except Exception:
        conn.close()
        raise
    return conn


def migrate_fills_identity(path: str, *, _fail_after: Optional[str] = None
                           ) -> Dict[str, Any]:
    """在【显式指定的库】上执行 §1.2 单事务表重建迁移（隔离专用）。

    - 全列双向 EXCEPT 等价核验（非抽样）；
    - 唯一索引只在本事务创建一次；
    - 提交前 PRAGMA foreign_key_check 非空 → ROLLBACK；
    - foreign_keys 状态在 finally 中恢复并验证；
    - 幂等：标记存在 → no-op（但仍验证结构）。
    _fail_after 仅为测试注入失败点。
    """
    conn = sqlite3.connect(path)
    try:
        if _marker_value(conn) == SCHEMA_VERSION:
            verify_structure(conn)
            return {"migrated": False, "reason": "already at version 4"}
        old_fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_NEW_DDL.format(name="fills_new"))
            if _fail_after == "ddl":
                raise RuntimeError("injected:ddl")
            conn.execute(
                f"INSERT INTO fills_new ({OLD_COLS}, origin, symbol,"
                " qty_raw, price_raw, fee_raw, fee_asset, derivation_ctx,"
                " replaced_by) "
                f"SELECT {OLD_COLS}, 'LEGACY', NULL, NULL, NULL, NULL,"
                " NULL, NULL, NULL FROM fills")
            if _fail_after == "copy":
                raise RuntimeError("injected:copy")
            # 全量等价核验：旧列集双向 EXCEPT 均为空
            a = conn.execute(
                f"SELECT {OLD_COLS} FROM fills EXCEPT"
                f" SELECT {OLD_COLS} FROM fills_new").fetchone()
            b = conn.execute(
                f"SELECT {OLD_COLS} FROM fills_new EXCEPT"
                f" SELECT {OLD_COLS} FROM fills").fetchone()
            if a is not None or b is not None:
                raise MigrationError("full-column equivalence violated")
            conn.execute(
                "CREATE UNIQUE INDEX ux_fills_null_symbol ON fills_new"
                " (fill_id) WHERE symbol IS NULL")
            if _fail_after == "index":
                raise RuntimeError("injected:index")
            conn.execute("DROP TABLE fills")
            if _fail_after == "drop":
                raise RuntimeError("injected:drop")
            conn.execute("ALTER TABLE fills_new RENAME TO fills")
            if _fail_after == "rename":
                raise RuntimeError("injected:rename")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta"
                " (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value)"
                " VALUES (?, ?)", (SCHEMA_MARKER_KEY, SCHEMA_VERSION))
            dangling = conn.execute("PRAGMA foreign_key_check").fetchall()
            if dangling:
                raise MigrationError(
                    f"foreign_key_check non-empty: {len(dangling)} rows")
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise MigrationError(f"migration rolled back: {exc}") from exc
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
            if old_fk:
                restored = conn.execute(
                    "PRAGMA foreign_keys").fetchone()[0]
                if not restored:
                    raise MigrationError(
                        "foreign_keys pragma not restored after migration")
    finally:
        conn.close()
    conn = reopen_isolated(path)  # 迁移后重开即结构验证
    conn.close()
    return {"migrated": True, "version": SCHEMA_VERSION}


def _rollback(path, conn):
    try:
        conn.rollback()
    except Exception:
        pass
    return MigrationError("migration rolled back")


def aggregate_qty_v2(conn, client_order_id: str) -> Dict[str, Any]:
    """精度分级聚合（§1.4）：EVENT=Decimal 精确；LEGACY 照常计入。"""
    rows = conn.execute(
        "SELECT origin, qty_raw, qty FROM fills WHERE client_order_id = ?",
        (client_order_id,)).fetchall()
    if not rows:
        return {"qty": Decimal(0), "fills": 0, "precision": "EMPTY"}
    total = Decimal(0)
    has_legacy = has_event = False
    for r in rows:
        if r["origin"] == "EVENT":
            has_event = True
            total += Decimal(r["qty_raw"])
        else:
            has_legacy = True
            total += Decimal(str(r["qty"]))  # LEGACY_APPROXIMATE 通道
    tier = ("MIXED_APPROXIMATE" if has_legacy and has_event
            else "LEGACY_APPROXIMATE" if has_legacy else "EXACT")
    return {"qty": total, "fills": len(rows), "precision": tier}


def cross_tier_compare(event_qty_raw: str, legacy_qty_real: float
                       ) -> Dict[str, Any]:
    """跨等级比较（§1.4）：永不判冲突也永不判确认匹配。"""
    return {"result": "COMPARISON_INCOMPLETE",
            "restrict_new_risk": True,
            "block_reduce": False,
            "note": "EVENT raw vs LEGACY REAL：等对账；减仓不受限"}


def _parse_positive_raw(raw: str, field: str) -> Decimal:
    try:
        d = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field}_raw not a Decimal: {raw!r}")
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{field}_raw not finite positive: {raw!r}")
    return d


def _derive_real(d: Decimal, field: str) -> float:
    """REAL 展示派生：超本实现 float 支持范围 → 拒收（计划 §0）。"""
    f = float(d)
    if not (f > 0) or f in (float("inf"),):
        raise ValueError(
            f"{field} beyond float support range: {d}")
    return f


class FillsV2Writer:
    """新 schema 测试写入的独立构造器（origin='EVENT'）。

    校验=写入合法性（raw 有限/严格>0/REAL 派生/费用规则），不吸收
    S2 的身份内容比较。
    """

    def __init__(self, conn):
        self._conn = conn

    def write_event_fill(self, *, fill_id, symbol, client_order_id,
                         qty_raw, price_raw, side, filled_at,
                         fee_raw=None, fee_asset=None, **_ignored):
        if not symbol or ":" in symbol:
            raise ValueError("EVENT fill requires clean symbol")
        q = _parse_positive_raw(qty_raw, "qty")
        p = _parse_positive_raw(price_raw, "price")
        if fee_raw is not None and (not fee_raw or not fee_asset):
            raise ValueError("KNOWN fee requires fee_raw and fee_asset")
        with self._conn:
            self._conn.execute(
                "INSERT INTO fills (fill_id, symbol, origin,"
                " client_order_id, qty, qty_raw, price, price_raw,"
                " fee_raw, fee_asset, side, filled_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (fill_id, symbol, "EVENT", client_order_id,
                 _derive_real(q, "qty"), qty_raw,
                 _derive_real(p, "price"), price_raw,
                 fee_raw, fee_asset, side, filled_at))
