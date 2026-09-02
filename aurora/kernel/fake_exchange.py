"""确定性故障注入测试适配器（P0-B1）。

行为旋钮：
- "ok"                 正常全量成交
- "reject"             明确拒单
- "timeout_then_filled"提交超时（结果未知），事后查询发现已成交
- "timeout_then_gone"  提交超时（结果未知），事后查询发现订单不存在
- "partial"            部分成交（60%），其余由 complete_fill() 推进

同一 client_order_id 重复提交抛 DuplicateClientOrderIdError（交易所侧幂等护栏）。
所有请求（无论成败）都记入 submit_log，供测试证明"没有第二单"。
"""
from typing import Dict, List, Optional

from .port import (
    DuplicateClientOrderIdError,
    ExchangePort,
    ExchangePosition,
    Fill,
    OrderAck,
    OrderFact,
    OrderKind,
    OrderRejectedError,
    OrderRequest,
    SubmitUnknownError,
)
from .state_machine import utc_now


class FakeExchange(ExchangePort):
    def __init__(
        self,
        entry_behavior: str = "ok",
        protection_behavior: str = "ok",
        close_behavior: str = "ok",
        price: float = 100.0,
    ):
        for name, value in (
            ("entry", entry_behavior),
            ("protection", protection_behavior),
            ("close", close_behavior),
        ):
            if value not in ("ok", "reject", "timeout_then_filled", "timeout_then_gone", "partial"):
                raise ValueError(f"unknown {name} behavior: {value}")
        self.entry_behavior = entry_behavior
        self.protection_behavior = protection_behavior
        self.close_behavior = close_behavior
        self.price = price

        self.submit_log: List[OrderRequest] = []
        self._orders: Dict[str, dict] = {}
        self._fills: Dict[str, List[Fill]] = {}
        self._fill_seq = 0
        self._fail_position = False

    # ---- 内部 ----

    def _behavior_for(self, kind: OrderKind) -> str:
        if kind == OrderKind.ENTRY:
            return self.entry_behavior
        if kind == OrderKind.CLOSE:
            return self.close_behavior
        return self.protection_behavior

    def _emit_fill(self, req: OrderRequest, qty: float) -> Fill:
        self._fill_seq += 1
        fill = Fill(
            fill_id=f"{req.client_order_id}-F{self._fill_seq}",
            client_order_id=req.client_order_id,
            qty=qty,
            price=self.price,
            fee=round(qty * self.price * 0.0005, 8),
            side=req.side,
            filled_at=utc_now(),
        )
        self._fills.setdefault(req.client_order_id, []).append(fill)
        order = self._orders[req.client_order_id]
        order["filled_qty"] = round(order["filled_qty"] + qty, 10)
        order["avg_price"] = self.price
        return fill

    # ---- ExchangePort ----

    def submit_order(self, req: OrderRequest) -> OrderAck:
        self.submit_log.append(req)
        if req.client_order_id in self._orders:
            raise DuplicateClientOrderIdError(req.client_order_id)

        behavior = self._behavior_for(req.order_kind)
        if behavior == "reject":
            raise OrderRejectedError(f"{req.order_kind.value} rejected")

        if behavior in ("timeout_then_filled", "timeout_then_gone"):
            if behavior == "timeout_then_filled":
                self._orders[req.client_order_id] = {
                    "req": req, "status": "FILLED", "filled_qty": 0.0, "avg_price": 0.0,
                }
                self._emit_fill(req, req.quantity)
            raise SubmitUnknownError(f"{req.order_kind.value} submit timed out")

        if req.order_kind in (OrderKind.STOP_LOSS, OrderKind.TAKE_PROFIT):
            # 保护单挂牌后处于工作状态（NEW），不立即成交、不产生持仓变化；
            # 触发由 fire_protection() 模拟交易所侧 SL/TP 行为
            self._orders[req.client_order_id] = {
                "req": req, "status": "NEW", "filled_qty": 0.0, "avg_price": 0.0,
            }
            return OrderAck(req.client_order_id, req.client_order_id, "NEW", 0.0, 0.0)

        if behavior == "partial" and req.order_kind == OrderKind.ENTRY:
            self._orders[req.client_order_id] = {
                "req": req, "status": "PARTIALLY_FILLED", "filled_qty": 0.0, "avg_price": 0.0,
            }
            self._emit_fill(req, round(req.quantity * 0.6, 10))
            order = self._orders[req.client_order_id]
            return OrderAck(req.client_order_id, req.client_order_id, "PARTIALLY_FILLED",
                            order["filled_qty"], order["avg_price"])

        self._orders[req.client_order_id] = {
            "req": req, "status": "FILLED", "filled_qty": 0.0, "avg_price": 0.0,
        }
        self._emit_fill(req, req.quantity)
        order = self._orders[req.client_order_id]
        return OrderAck(req.client_order_id, req.client_order_id, "FILLED",
                        order["filled_qty"], order["avg_price"])

    def query_order(self, client_order_id: str) -> OrderFact:
        order = self._orders.get(client_order_id)
        if order is None:
            return OrderFact(client_order_id, "NOT_FOUND", 0.0, 0.0)
        return OrderFact(client_order_id, order["status"], order["filled_qty"], order["avg_price"])

    def cancel_order(self, client_order_id: str) -> bool:
        order = self._orders.get(client_order_id)
        if order is None or order["status"] != "NEW":
            return False
        order["status"] = "CANCELLED"
        return True

    def position(self, symbol: str) -> Optional[ExchangePosition]:
        if self._fail_position:
            return None  # 交易所事实不可知 = UNKNOWN，绝不能解释为空仓
        signed = 0.0
        entry_price = 0.0
        for order in self._orders.values():
            req = order["req"]
            if req.symbol != symbol or order["filled_qty"] <= 0:
                continue
            sign = 1.0 if req.side == "BUY" else -1.0
            signed += sign * order["filled_qty"]
            if req.order_kind == OrderKind.ENTRY:
                entry_price = order["avg_price"]
        if abs(signed) < 1e-12:
            return ExchangePosition(symbol, 0.0, 0.0)
        return ExchangePosition(symbol, signed, entry_price)

    def fills(self, client_order_id: str) -> List[Fill]:
        return list(self._fills.get(client_order_id, []))

    # ---- 测试辅助 ----

    def complete_fill(self, client_order_id: str) -> None:
        """把部分成交订单推进到全量成交（模拟后续成交事件）。"""
        order = self._orders[client_order_id]
        remaining = round(order["req"].quantity - order["filled_qty"], 10)
        if remaining > 0:
            self._emit_fill(order["req"], remaining)
        order["status"] = "FILLED"

    def fire_protection(self, client_order_id: str, price: Optional[float] = None) -> None:
        """模拟交易所侧 SL/TP 触发：保护单成交，仓位相应归零/转向。"""
        order = self._orders[client_order_id]
        if order["status"] == "FILLED":
            return
        if price is not None:
            self._emit_fill_at(order["req"], order["req"].quantity, price)
        else:
            self._emit_fill(order["req"], order["req"].quantity)
        order["status"] = "FILLED"

    def _emit_fill_at(self, req: OrderRequest, qty: float, price: float) -> None:
        saved = self.price
        self.price = price
        try:
            self._emit_fill(req, qty)
        finally:
            self.price = saved

    def fail_position_queries(self, fail: bool) -> None:
        self._fail_position = fail
