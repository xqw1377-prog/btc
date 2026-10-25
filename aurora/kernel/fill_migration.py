"""FILL IDENTITY S1：迁移与历史兼容（隔离实现——显式调用专用）。

边界（开工裁定 2026-10，见 FILL_IDENTITY_IMPL_PLAN.md §S1 执行边界）：
- 本模块【不】接入 Ledger.__init__ / 生产入口 / 默认启动路径；
  只被显式的测试与演练代码调用。
- 作用对象：临时库、合成旧库、经批准的事故账本副本；原件只读。
- 等价性结论只允许表述为"副本/离线恢复等价性"。
- 新 schema 写入走独立构造器 FillsV2Writer，不吸收 S2 校验逻辑。

（提交 A 为桩：全部能力 NotImplementedError——红测试的失败必须
来自目标能力缺失，而非导入错误。）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

SCHEMA_VERSION = "4"
SCHEMA_MARKER_KEY = "fills_identity_version"


class MigrationError(Exception):
    """迁移事务失败（已回滚；原库保持迁移前状态）。"""


class FillMigrationStub(NotImplementedError):
    """S1 桩：目标能力缺失（提交 A）。"""


def migrate_fills_identity(path: str, *, _fail_after: Optional[str] = None) -> Dict[str, Any]:
    """在【显式指定的库】上执行 §1.2 单事务表重建迁移。

    _fail_after 仅为测试注入失败点（'copy'/'index'/'rename'）。
    """
    raise FillMigrationStub("migrate_fills_identity")


def reopen_isolated(path: str) -> Any:
    """隔离重开：版本标记 + 结构验证（PK/索引/origin 列）。"""
    raise FillMigrationStub("reopen_isolated")


def aggregate_qty_v2(conn: Any, client_order_id: str) -> Dict[str, Any]:
    """精度分级聚合（§1.4）：EVENT=Decimal 精确；LEGACY 照常计入。"""
    raise FillMigrationStub("aggregate_qty_v2")


def cross_tier_compare(event_qty_raw: str, legacy_qty_real: float) -> Dict[str, Any]:
    """跨等级比较（§1.4）：COMPARISON_INCOMPLETE——限新增风险不阻减仓。"""
    raise FillMigrationStub("cross_tier_compare")


class FillsV2Writer:
    """新 schema 测试写入的独立构造器（origin='EVENT'）。

    校验仅为写入合法性（raw 有限/严格>0/REAL 派生），不是 S2 的
    身份内容比较。
    """

    def __init__(self, conn: Any):
        raise FillMigrationStub("FillsV2Writer.__init__")

    def write_event_fill(self, **kwargs: Any) -> None:
        raise FillMigrationStub("FillsV2Writer.write_event_fill")
