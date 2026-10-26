"""FILL IDENTITY S2：统一身份校验器（桩——提交 A：红测试专用）。"""
from typing import Any, Dict, List, Optional


class S2Stub(NotImplementedError):
    """目标能力缺失（红测试失败必须来自此处，非导入错误）。"""


def parse_finite(raw):
    raise S2Stub("parse_finite")


def fill_content_mismatch(stored, incoming):
    raise S2Stub("fill_content_mismatch")


def derivation_check(stored_ctx, recomputed_value, stored_value):
    raise S2Stub("derivation_check")


def order_symbol_for(conn, client_order_id):
    raise S2Stub("order_symbol_for")


def check_attribution(conn, fill_symbol, client_order_id):
    raise S2Stub("check_attribution")


def resolve_fill_ref(conn, ref):
    raise S2Stub("resolve_fill_ref")


def validate_new_ref(conn, ref):
    raise S2Stub("validate_new_ref")
