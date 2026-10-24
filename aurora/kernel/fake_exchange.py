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
    CancelUnknownError,
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
        self.cancel_behavior = "ok"      # "ok" | "unknown"（撤单结果未知）
        self.cancel_fires_first = False  # 撤单竞态：撤单到达前腿已成交
        self.tp_reject_only = False      # 仅 TP 腿拒单（SL 正常，测 safe_but_incomplete）
        self.price = price
        # G0-4B：ACK.executedQty 只是早期观察。设为 0 可模拟事故：ACK=0 但 fills/仓位已有量。
        self.ack_executed_qty = None

        self.submit_log: List[OrderRequest] = []
        self._orders: Dict[str, dict] = {}
        self._fills: Dict[str, List[Fill]] = {}
        self._fill_seq = 0
        self._fail_position = False
        self._fail_order_query = False
        # BOOT-DRIFT 测试辅助：账本/本 fake 订单系统之外的外部持仓。
        self._external: List[tuple] = []       # (signed_qty, entry_price)
        self._ambiguous_position = False        # 如 HEDGE 双腿：查询不完整 → None
        self._force_flat = False                # 仓位变 0 但无对应 fill（EXIT-PROVENANCE）
        self.position_delta_on_cancel = 0.0     # 撤单窗口内仓位变化（G0-4C repair）
        self.flatten_on_cancel = False          # 撤单后仓位归零且无 fill

    # ---- 内部 ----

    def _behavior_for(self, kind: OrderKind) -> str:
        if self.tp_reject_only and kind == OrderKind.TAKE_PROFIT:
            return "reject"
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
            return OrderAck(
                req.client_order_id, req.client_order_id, "PARTIALLY_FILLED",
                self._ack_qty(req, order["filled_qty"]),
                self._ack_avg(req, order["avg_price"]))

        self._orders[req.client_order_id] = {
            "req": req, "status": "FILLED", "filled_qty": 0.0, "avg_price": 0.0,
        }
        self._emit_fill(req, req.quantity)
        order = self._orders[req.client_order_id]
        return OrderAck(
            req.client_order_id, req.client_order_id, "FILLED",
            self._ack_qty(req, order["filled_qty"]),
            self._ack_avg(req, order["avg_price"]))

    def _ack_qty(self, req: OrderRequest, actual: float) -> float:
        if req.order_kind == OrderKind.ENTRY and self.ack_executed_qty is not None:
            return float(self.ack_executed_qty)
        return actual

    def _ack_avg(self, req: OrderRequest, actual: float) -> float:
        if (
            req.order_kind == OrderKind.ENTRY
            and self.ack_executed_qty is not None
            and float(self.ack_executed_qty) <= 1e-12
        ):
            return 0.0
        return actual

    def query_order(self, client_order_id: str) -> OrderFact:
        if self._fail_order_query:
            raise RuntimeError(f"order query failed: {client_order_id}")
        order = self._orders.get(client_order_id)
        if order is None:
            return OrderFact(client_order_id, "NOT_FOUND", 0.0, 0.0)
        return OrderFact(client_order_id, order["status"], order["filled_qty"], order["avg_price"])

    def _current_signed_qty(self, symbol: str) -> float:
        signed = 0.0
        for order in self._orders.values():
            req = order["req"]
            if req.symbol == symbol and order["filled_qty"] > 0:
                signed += (1.0 if req.side == "BUY" else -1.0) * order["filled_qty"]
        return signed

    def _cap_reduce_only(self, req: OrderRequest, want: float) -> float:
        """reduceOnly 成交上限 = 当前仓位绝对值（不得超射反向开仓）。"""
        if not req.reduce_only:
            return want
        return max(0.0, min(want, abs(self._current_signed_qty(req.symbol))))

    def cancel_order(self, client_order_id: str) -> bool:
        if self.cancel_behavior == "unknown":
            raise CancelUnknownError(f"cancel result unknown: {client_order_id}")
        order = self._orders.get(client_order_id)
        if order is None or order["status"] != "NEW":
            return False
        if self.cancel_fires_first:
            # 竞态：撤单请求到达前，腿已按 reduceOnly 上限成交
            fire_qty = self._cap_reduce_only(
                order["req"], order["req"].quantity - order["filled_qty"])
            if fire_qty > 0:
                self._emit_fill(order["req"], fire_qty)
                order["status"] = "FILLED"
                return False  # 撤单失败：订单已成交
        order["status"] = "CANCELLED"
        if self.flatten_on_cancel:
            self.flatten_without_fill()
        elif abs(self.position_delta_on_cancel) > 1e-12:
            # 修复窗口内仓位变化：表达为多头腿的外部增减（减仓场景），
            # 而不是开一条对侧空头腿（HEDGE 保真，W43-A3）。
            self.seed_external_position(
                self.position_delta_on_cancel, self.price, leg="LONG")
        return True

    def seed_external_position(self, signed_qty: float, entry_price: float,
                               leg: str = None) -> None:
        """注入账本之外的持仓。leg 缺省按符号推断（正→LONG、负→SHORT）。

        HEDGE 保真（W43-A3）：leg="LONG" 且负值 = 外部减多头腿（减仓）；
        负值且 leg 缺省 = 真实空头腿（与多头腿并存 → 双腿 UNKNOWN）。
        """
        if leg is None:
            leg = "LONG" if signed_qty >= 0 else "SHORT"
        if leg not in ("LONG", "SHORT"):
            raise ValueError(f"unknown leg {leg!r}")
        self._external.append((signed_qty, entry_price, leg))

    def set_position_query_ambiguous(self, flag: bool = True) -> None:
        """模拟多腿/覆盖不足的仓位查询：返回 None（UNKNOWN），绝不净额成 FLAT。"""
        self._ambiguous_position = flag

    def flatten_without_fill(self) -> None:
        """交易所仓位归零，但不产生任何 order/fill。禁止测试据此补造 SELL。"""
        self._force_flat = True
        self._external = []

    def position(self, symbol: str) -> Optional[ExchangePosition]:
        if self._fail_position or self._ambiguous_position:
            return None  # 交易所事实不可知 = UNKNOWN，绝不能解释为空仓
        if self._force_flat:
            return ExchangePosition(symbol, 0.0, 0.0)
        signed = 0.0
        entry_price = 0.0
        long_leg = 0.0
        short_leg = 0.0
        for qty, px, leg in self._external:
            signed += qty
            if qty:
                entry_price = px
                if leg == "SHORT":
                    short_leg += -qty
                else:
                    long_leg += qty
        for order in self._orders.values():
            req = order["req"]
            if req.symbol != symbol or order["filled_qty"] <= 0:
                continue
            sign = 1.0 if req.side == "BUY" else -1.0
            signed += sign * order["filled_qty"]
            # HEDGE 语义：成交归属其 positionSide 腿——SELL(positionSide=
            # LONG) 是减多头腿，不是开空头腿。ONE-WAY（BOTH）并入多头腿
            # 净额（单向模式本无双腿）。
            leg = getattr(req, "position_side", "LONG") or "LONG"
            if leg == "SHORT":
                short_leg += sign * order["filled_qty"]
            else:
                long_leg += sign * order["filled_qty"]
            if req.order_kind == OrderKind.ENTRY:
                entry_price = order["avg_price"]
        # W43-A3（NautilusTrader #5416 吸收）：多空两腿同时非零 = 持仓快照
        # 不明确。与真实 Binance 适配器一致：返回 None（UNKNOWN），
        # 绝不净额成单腿、绝不把对侧腿当作本腿覆盖证据。
        if long_leg > 1e-12 and short_leg > 1e-12:
            return None
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

    def mark_algo_triggered(self, client_order_id: str) -> None:
        """G0-4C C5：模拟 Algo 终态 TRIGGERED 且无 actualOrderId/权威成交。

        TRIGGERED ≠ FILLED：查询侧只见终态名，不得收敛，不得编造 fill。
        随后若测试再注入 fills()（fire_protection），即代表 actualOrderId
        关联的权威成交到达。
        """
        order = self._orders.get(client_order_id)
        if order is None:
            raise KeyError(client_order_id)
        order["status"] = "TRIGGERED"

    def fire_protection(
        self, client_order_id: str, price: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> None:
        """模拟交易所侧 SL/TP 触发；qty 省略为整腿成交（部分触发可指定 qty）。

        reduceOnly 保护腿成交上限为当前仓位（不得超射反向开仓）。
        """
        order = self._orders[client_order_id]
        if order["status"] == "FILLED":
            return
        want = order["req"].quantity if qty is None else qty
        fire_qty = self._cap_reduce_only(order["req"], want)
        if fire_qty <= 0:
            return
        if price is not None:
            self._emit_fill_at(order["req"], fire_qty, price)
        else:
            self._emit_fill(order["req"], fire_qty)
        if order["filled_qty"] >= order["req"].quantity - 1e-12:
            order["status"] = "FILLED"
        else:
            order["status"] = "PARTIALLY_FILLED"

    def _emit_fill_at(self, req: OrderRequest, qty: float, price: float) -> None:
        saved = self.price
        self.price = price
        try:
            self._emit_fill(req, qty)
        finally:
            self.price = saved

    def fail_position_queries(self, fail: bool) -> None:
        self._fail_position = fail

    def fail_order_queries(self, fail: bool) -> None:
        self._fail_order_query = fail
