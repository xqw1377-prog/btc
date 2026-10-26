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


_REQUIRED_COLS = {"fill_id", "symbol", "origin", "client_order_id", "qty",
                  "qty_raw", "price", "price_raw", "fee", "fee_raw",
                  "fee_asset", "realized_pnl", "derivation_ctx",
                  "replaced_by", "side", "filled_at", "synthetic",
                  "replaces_synthetic_fill_id", "covered_by_fact_id",
                  "quantity_effect_applied", "economic_effect_applied"}
_NOTNULL_REQUIRED = {"fill_id", "origin", "client_order_id", "qty",
                     "price", "side", "filled_at"}

_EV_INS = ("INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
           " qty, qty_raw, price, price_raw, side, filled_at)"
           " VALUES (?, ?, 'EVENT', ?, ?, ?, ?, ?, ?, 't')")
_LG_INS = ("INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
           " qty, price, side, filled_at)"
           " VALUES (?, NULL, 'LEGACY', ?, ?, ?, 'BUY', 't')")


def verify_structure(conn) -> None:
    """结构验证（S1-04 v2）：元数据核验 + 回滚式约束探针。

    评审反例（OR 1=1 索引伪造、删除 side CHECK）证明 SQL 子串匹配
    不可靠——约束语义改由【行为探针】证明：探针在 SAVEPOINT 内
    注入应被拒绝/应被放行的输入，观察真实结果后整体回滚，不留痕。
    元数据部分只使用精确结构信息（table_info/foreign_key_list），
    不解析 SQL 文本。
    """
    if _marker_value(conn) != SCHEMA_VERSION:
        raise MigrationError("schema marker missing or wrong version")
    info = list(conn.execute("PRAGMA table_info(fills)"))
    cols = {r[1] for r in info}
    missing = _REQUIRED_COLS - cols
    if missing:
        raise MigrationError(f"fills missing columns: {sorted(missing)}")
    for r in info:
        if r[1] in _NOTNULL_REQUIRED and not r[3]:
            raise MigrationError(f"column {r[1]} must be NOT NULL")
    pk = [r[1] for r in sorted(
        (r for r in info if r[5] > 0), key=lambda r: r[5])]
    if pk != ["symbol", "fill_id"]:
        raise MigrationError(f"fills PK is {pk}, expected [symbol, fill_id]")
    fks = list(conn.execute("PRAGMA foreign_key_list(fills)"))
    if not any(r[2] == "orders" and r[3] == "client_order_id" for r in fks):
        raise MigrationError("FK client_order_id→orders missing")
    _probe_constraints(conn)


def _probe_constraints(conn) -> None:
    """回滚式约束探针（S1-04 v2）：证明语义而非子串。

    每个探针注入一个必须被拒绝（或必须放行）的输入；观察数据库
    的真实裁决。全部在 SAVEPOINT 内，最终回滚——零残留。
    """
    import uuid as _uuid

    tag = _uuid.uuid4().hex[:8]
    prev_iso = conn.isolation_level
    conn.isolation_level = None  # 手动事务模式，SAVEPOINT 显式控制
    conn.execute("SAVEPOINT s1_verify")
    try:
        row = conn.execute(
            "SELECT client_order_id FROM orders LIMIT 1").fetchone()
        if row is not None:
            cid = row[0]
        else:
            conn.execute(
                "INSERT INTO intents (intent_id, symbol, side, quantity,"
                " state, reason, created_at, updated_at)"
                " VALUES ('__probe_i_" + tag + "','BTCUSDT','LONG',1,"
                " 'REJECTED','structure probe','t','t')")
            cid = "__probe_o_" + tag
            conn.execute(
                "INSERT INTO orders (client_order_id, intent_id,"
                " order_kind, side, position_side, quantity, reduce_only,"
                " state, filled_qty, avg_price, created_at, updated_at)"
                f" VALUES ('{cid}','__probe_i_{tag}','ENTRY','BUY','LONG',"
                "1,0,'FILLED',1,1,'t','t')")

        def expect_reject(sql, params=(), what=""):
            try:
                conn.execute(sql, params)
            except sqlite3.IntegrityError:
                return
            raise MigrationError(
                f"constraint probe NOT enforced{what}: {sql}")

        def expect_ok(sql, params=(), what=""):
            try:
                conn.execute(sql, params)
            except sqlite3.IntegrityError as exc:
                raise MigrationError(
                    f"probe wrongly rejected{what}: {exc}")

        def ev(fid, symbol="BTCUSDT", qty=1, qty_raw="1",
               price=1, price_raw="1", side="BUY", fee_raw=None,
               fee_asset=None, cid_override=None):
            return (_EV_INS, (f"__p_{tag}_{fid}", symbol,
                              cid_override or cid, qty, qty_raw,
                              price, price_raw, side), fee_raw, fee_asset)

        # --- 部分唯一索引语义（钉死 OR 1=1 伪造） ---
        # P1: 两个 NULL-symbol 同 trade ID → 必须拒绝
        lg_sql = _LG_INS
        expect_ok(lg_sql, (f"__p_{tag}_A", cid, 1, 1))
        expect_reject(lg_sql, (f"__p_{tag}_A", cid, 1, 1),
                      what=" [partial-unique on NULL symbol]")
        # P2: 同 trade ID 跨 symbol → 必须放行（OR 1=1 伪造会拒绝）
        s, p, fr, fa = ev("B", symbol="BTCUSDT")
        expect_ok(s, p)
        s2, p2, _, _ = ev("B", symbol="ETHUSDT")
        expect_ok(s2, p2, what=" [cross-symbol same trade ID]")
        # P3: NULL + symbol 同 trade ID 共存 → 放行
        expect_ok(lg_sql, (f"__p_{tag}_C", cid, 1, 1))
        s3, p3, _, _ = ev("C", symbol="BTCUSDT")
        expect_ok(s3, p3, what=" [NULL+symbol coexist]")
        # PK: 同 (symbol, trade ID) 重复 → 拒绝
        s4, p4, _, _ = ev("D")
        expect_ok(s4, p4)
        expect_reject(s4, p4, what=" [composite PK]")

        # --- CHECK 语义（钉死删除/弱化 CHECK 的伪造） ---
        expect_reject(_EV_INS, (f"__p_{tag}_G", "BTCUSDT", cid,
                                "garbage", "1", 1, "1", "BUY"),
                      what=" [typeof(qty) text]")
        expect_reject(_EV_INS, (f"__p_{tag}_N", "BTCUSDT", cid,
                                -1, "-1", 1, "1", "BUY"),
                      what=" [qty>0]")
        expect_reject(_EV_INS, (f"__p_{tag}_Z", "BTCUSDT", cid,
                                0, "0", 1, "1", "BUY"),
                      what=" [qty>0 zero]")
        expect_reject(_EV_INS, (f"__p_{tag}_P", "BTCUSDT", cid,
                                1, "1", -1, "-1", "BUY"),
                      what=" [price>0]")
        expect_reject(_EV_INS, (f"__p_{tag}_S", "BTCUSDT", cid,
                                1, "1", 1, "1", "LONG"),
                      what=" [side enum]")
        expect_reject(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, side, filled_at)"
            " VALUES (?, 'BTCUSDT', 'BOGUS', ?, 1, '1', 1, '1', 'BUY', 't')",
            (f"__p_{tag}_O", cid), what=" [origin enum]")
        expect_reject(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, side, filled_at)"
            " VALUES (?, NULL, 'EVENT', ?, 1, '1', 1, '1', 'BUY', 't')",
            (f"__p_{tag}_M", cid), what=" [EVENT requires symbol]")
        expect_reject(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, side, filled_at)"
            " VALUES (?, 'BTCUSDT', 'EVENT', ?, 1, NULL, 1, '1', 'BUY', 't')",
            (f"__p_{tag}_R", cid), what=" [EVENT requires raws]")
        expect_reject(
            "INSERT INTO fills (fill_id, symbol, origin, client_order_id,"
            " qty, qty_raw, price, price_raw, fee_raw, fee_asset,"
            " side, filled_at)"
            " VALUES (?, 'BTCUSDT', 'EVENT', ?, 1, '1', 1, '1', '0.1',"
            " NULL, 'BUY', 't')",
            (f"__p_{tag}_F", cid), what=" [fee KNOWN requires asset]")
        # NOT NULL（origin 无默认、必填）
        expect_reject(
            "INSERT INTO fills (fill_id, symbol, client_order_id, qty,"
            " price, side, filled_at)"
            " VALUES (?, 'BTCUSDT', ?, 1, 1, 'BUY', 't')",
            (f"__p_{tag}_NN", cid), what=" [origin NOT NULL]")
        # FK：引用不存在订单 → 拒绝（连接级 FK 已由 reopen 强制）
        s5, p5, _, _ = ev("K", cid_override="__no_such_order__")
        expect_reject(s5, p5, what=" [FK to orders]")
    finally:
        conn.execute("ROLLBACK TO s1_verify")
        conn.execute("RELEASE s1_verify")
        conn.isolation_level = prev_iso


def reopen_isolated(path: str,
                    _connect=None) -> sqlite3.Connection:
    """隔离重开：版本标记 + 结构深度验证 + 外键强制启用（S1-03）。"""
    connect = _connect or (lambda p: sqlite3.connect(
        f"file:{p}?mode=rw", uri=True))
    conn = connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise MigrationError("foreign_keys enforcement refused to enable")
        verify_structure(conn)
    except Exception:
        conn.close()
        raise
    return conn


def migrate_fills_identity(path: str, *, _fail_after: Optional[str] = None,
                           _connect=None) -> Dict[str, Any]:
    """在【显式指定的库】上执行 §1.2 单事务表重建迁移（隔离专用）。

    - 全列双向 EXCEPT 等价核验（非抽样）；
    - 唯一索引只在本事务创建一次；
    - 提交前 PRAGMA foreign_key_check 非空 → ROLLBACK；
    - foreign_keys 状态在 finally 中恢复并验证；
    - 幂等：标记存在 → no-op（但仍验证结构）。
    _fail_after 仅为测试注入失败点；_connect 为连接工厂（FK 恢复
    可观测性——评审指出：连接级 pragma 可经工厂代理观测）。
    """
    conn = (_connect or sqlite3.connect)(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")  # 探针要求 FK 强制
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
            # 无条件恢复并验证（评审 S1-03 教训：不能只在旧状态为 ON 时
            # 才恢复——迁移连接必须以 FK=ON 收尾，可观测性经 _connect 工厂）
            conn.execute("PRAGMA foreign_keys=ON")
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


_AGG_WHERE = (" WHERE client_order_id = ? AND quantity_effect_applied = 1"
              " AND economic_effect_applied = 1"
              " AND NOT (synthetic = 1 AND covered_by_fact_id IS NOT NULL)")

_PREC_CAP = 10000


def _needed_prec(vals):
    """动态精度（计划 §0）：max(28, 最大有效位数, 指数跨度+1) + 4。"""
    digits = max(len(v.as_tuple().digits) for v in vals)
    min_exp = min(v.as_tuple().exponent for v in vals)
    max_adj = max(v.adjusted() for v in vals)
    span = max_adj - min_exp + 2
    return max(28, digits, span) + 4


def _exact_sum(vals):
    """精确求和：Inexact/Rounded 陷阱 + 一次翻倍重试；上限 10000。

    超上限输入直接拒收（不进入运算）；重试不突破上限（计划 §0）。
    """
    from decimal import localcontext, Inexact, Rounded
    need = _needed_prec(vals)
    if need > _PREC_CAP:
        raise ValueError(
            f"precision requirement {need} beyond support cap {_PREC_CAP}")
    with localcontext() as ctx:
        ctx.prec = need
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        try:
            return sum(vals, Decimal(0))
        except (Inexact, Rounded):
            ctx.prec = min(ctx.prec * 2, _PREC_CAP)
            return sum(vals, Decimal(0))  # 一次重试；仍触发则异常上抛


def aggregate_qty_v2(conn, client_order_id: str) -> Dict[str, Any]:
    """精度分级聚合（§1.4）——S1-01/02 修正。

    数量/经济效果过滤与已替换合成行排除规则与旧 fills_aggregate
    完全一致（S1-01）；求和在陷阱保护的 Decimal 域内进行，EXACT
    标签不再伴随静默舍入（S1-02）。
    """
    rows = conn.execute(
        "SELECT origin, qty_raw, qty FROM fills" + _AGG_WHERE,
        (client_order_id,)).fetchall()
    if not rows:
        return {"qty": Decimal(0), "fills": 0, "precision": "EMPTY"}
    vals = []
    has_legacy = has_event = False
    for r in rows:
        if r["origin"] == "EVENT":
            has_event = True
            vals.append(Decimal(r["qty_raw"]))
        else:
            has_legacy = True
            vals.append(Decimal(str(r["qty"])))  # LEGACY_APPROXIMATE 通道
    tier = ("MIXED_APPROXIMATE" if has_legacy and has_event
            else "LEGACY_APPROXIMATE" if has_legacy else "EXACT")
    return {"qty": _exact_sum(vals), "fills": len(rows), "precision": tier}


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
