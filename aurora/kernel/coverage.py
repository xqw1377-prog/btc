"""保护覆盖量计算（P0-B2.1 修正口径）。

正确口径（不得简化）：
- 按 protection_role（SL/TP）分组，对**去重后活动订单**的剩余数量求和；
- SL 与 TP 是同一仓位的两个退出路径，**禁止相加**成"安全覆盖"；
- **禁止**对所有保护订单取 max——两个 SL 分片各 0.003 合计覆盖 0.006 仓位，
  取 max 会错误得到 0.003；
- 强制保护标准：sl_coverage >= exchange_position_qty（SL 为强制腿，TP 不足
  是"安全但不完整"，必须与完整状态分开表达）；
- 交易所仓位是唯一数量真源；不可知时 position_known=False，一切覆盖判断
  一律视为不满足。
"""
import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

EPS = 1e-9

ACTIVE_ORDER_STATES = ("SUBMITTING", "ACTIVE", "PROTECTION_SUBMITTING")


@dataclass(frozen=True)
class ProtectionStatus:
    sl_coverage: float          # 活动 SL 分片剩余数量之和
    tp_coverage: float          # 活动 TP 分片剩余数量之和
    exchange_qty: float         # 交易所实际持仓数量（不可知时为 nan）
    position_known: bool
    mandatory_ok: bool          # sl_coverage >= exchange_qty（强制腿）
    tp_ok: bool                 # tp_coverage >= exchange_qty（可选腿）

    @property
    def safe_but_incomplete(self) -> bool:
        """SL 足额但 TP 不足：安全（有强制止损）但不是完整保护，单独表达。"""
        return self.mandatory_ok and not self.tp_ok

    @property
    def protected_full(self) -> bool:
        return self.position_known and self.mandatory_ok and self.tp_ok


def compute_protection_status(
    orders: Iterable[Dict],
    exchange_qty: Optional[float],
) -> ProtectionStatus:
    """orders 为账本订单行；只统计活动保护单的剩余数量（quantity - filled_qty）。

    fired（已成交保护腿）不再计入覆盖——它们已经平掉了对应数量。
    """
    coverage: Dict[str, float] = {"STOP_LOSS": 0.0, "TAKE_PROFIT": 0.0}
    seen: set = set()
    for order in orders:
        cid = order.get("client_order_id")
        if cid in seen:            # 去重：同一订单只计一次
            continue
        seen.add(cid)
        role = order.get("order_kind")
        if role not in coverage:
            continue
        if order.get("state") not in ACTIVE_ORDER_STATES:
            continue
        remaining = float(order.get("quantity", 0.0)) - float(order.get("filled_qty", 0.0))
        if remaining > 0:
            coverage[role] += remaining

    known = exchange_qty is not None and not math.isnan(float(exchange_qty))
    qty = float(exchange_qty) if known else float("nan")
    return ProtectionStatus(
        sl_coverage=round(coverage["STOP_LOSS"], 10),
        tp_coverage=round(coverage["TAKE_PROFIT"], 10),
        exchange_qty=qty,
        position_known=known,
        mandatory_ok=known and coverage["STOP_LOSS"] >= qty - EPS,
        tp_ok=known and coverage["TAKE_PROFIT"] >= qty - EPS,
    )
