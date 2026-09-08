"""Legacy SafeExecutor — OFFLINE_REFERENCE_ONLY（G0-5D 退休）。

这是 2026-09 事故前后的第一代执行封装，保留其测试与语义作为研究参照。
生产执行路径唯一归属 aurora/kernel/（ADR-013）：
- production_main / safety / armed_runtime / kernel 不得引用本模块；
- 其"TP 失败即紧急平仓"的旧保护合同与内核"SL 强制 / TP 可缺"不一致，
  不得再获得成为第二生产执行器的机会（守卫：
  tests/test_g05_identity_isolation.py::SafeExecutorRetirementTests）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from aurora.p0_boundary import (
    BrainPosition,
    Broker,
    BrokerError,
    HaltState,
    Persistence,
    PositionQueryKind,
    ReconcileResult,
    SafetyStore,
    SafetyViolation,
    can_open,
    query_position,
    reconcile,
    utc_now,
)


class OrderState(str, Enum):
    """legacy 枚举（与 p0_boundary 旧版一致，仅本模块使用）。"""

    PENDING = "PENDING"
    ACKED = "ACKED"
    FILLED = "FILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class OrderRecord:
    client_order_id: str
    state: OrderState
    side: str
    quantity: float
    reduce_only: bool = False
    order_type: str = "MARKET"
    exchange_order_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)


class SafeExecutor:
    def __init__(self, broker: Broker, store: SafetyStore, persist: Persistence, symbol: str = "BTCUSDT"):
        self.broker = broker
        self.store = store
        self.persist = persist
        self.symbol = symbol
        self.orders: Dict[str, OrderRecord] = {}
        self.cancel_all_calls = 0

    def _cid(self, prefix: str) -> str:
        return f"AURORA_{prefix}_{uuid.uuid4().hex[:8]}"

    def _place(self, client_order_id: str, **params: Any) -> OrderRecord:
        existing = self.orders.get(client_order_id)
        if existing and existing.state == OrderState.FILLED:
            return existing
        record = existing or OrderRecord(
            client_order_id=client_order_id,
            state=OrderState.PENDING,
            side=params.get("side", ""),
            quantity=float(params.get("quantity", 0)),
            reduce_only=bool(params.get("reduceOnly", False)),
            order_type=params.get("type", "MARKET"),
        )
        self.orders[client_order_id] = record
        try:
            raw = self.broker.create_order(symbol=self.symbol, newClientOrderId=client_order_id, **params)
            record.state = OrderState.FILLED
            record.exchange_order_id = str(raw.get("orderId", client_order_id))
        except Exception as exc:
            try:
                seen = self.broker.get_order(self.symbol, client_order_id)
                if seen.get("status") in ("FILLED", "NEW", "PARTIALLY_FILLED"):
                    record.state = OrderState.FILLED if seen.get("status") == "FILLED" else OrderState.ACKED
                    record.exchange_order_id = str(seen.get("orderId", client_order_id))
                    return record
            except Exception:
                record.state = OrderState.UNKNOWN
                record.error = str(exc)
                return record
            record.state = OrderState.FAILED
            record.error = str(exc)
        return record

    def cancel_order(self, order_id: str) -> None:
        if not order_id:
            raise SafetyViolation("[P0] refuse cancel without exact order id.")
        self.broker.cancel_order(self.symbol, order_id)

    def cancel_all_orders(self) -> None:
        self.cancel_all_calls += 1
        raise SafetyViolation("[P0] cancel-all is forbidden; cancel by order id only.")

    def reconcile(self, trigger: str) -> ReconcileResult:
        exchange = query_position(self.broker, self.symbol)
        result = reconcile(self.store, exchange, trigger)
        self.persist.save(self.store)
        return result

    def execute_open(self, side: str, quantity: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        rec = self.reconcile("before_open")
        if not can_open(self.store, rec):
            return {"success": False, "reason": f"open blocked: halt={self.store.halt.value} rec={rec.status.value} close_failed={self.store.close_failed}"}

        open_cid = self._cid("OPEN")
        order_side = "BUY" if side == "LONG" else "SELL"
        opened = self._place(
            open_cid,
            side=order_side,
            positionSide=side,
            type="MARKET",
            quantity=quantity,
            reduceOnly=False,
        )
        if opened.state == OrderState.UNKNOWN:
            self.reconcile("order_unknown")
            return {"success": False, "reason": "open result UNKNOWN", "client_order_id": open_cid}
        if opened.state != OrderState.FILLED:
            return {"success": False, "reason": opened.error or "open failed", "client_order_id": open_cid}

        self.store.brain = BrainPosition(True, side, quantity, 0.0)
        self.store.pending_orders.append({"id": open_cid, "type": "OPEN"})
        self.persist.save(self.store)

        protect = self._confirm_protection(side, quantity, stop_loss, take_profit)
        self.reconcile("after_open")
        return protect

    def _confirm_protection(self, side: str, quantity: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        close_side = "SELL" if side == "LONG" else "BUY"
        sl_cid = self._cid("SL")
        tp_cid = self._cid("TP")
        sl = self._place(
            sl_cid, side=close_side, positionSide=side, type="STOP_MARKET",
            quantity=quantity, stopPrice=stop_loss, reduceOnly=True,
        )
        tp = self._place(
            tp_cid, side=close_side, positionSide=side, type="TAKE_PROFIT_MARKET",
            quantity=quantity, stopPrice=take_profit, reduceOnly=True,
        )
        sl_ok = self._protection_confirmed(sl)
        tp_ok = self._protection_confirmed(tp)
        if sl_ok and tp_ok:
            self.store.pending_orders.extend([
                {"id": sl_cid, "type": "SL"},
                {"id": tp_cid, "type": "TP"},
            ])
            self.persist.save(self.store)
            return {"success": True, "sl": sl_cid, "tp": tp_cid}

        return self._emergency_flatten("protection unconfirmed")

    def _protection_confirmed(self, record: OrderRecord) -> bool:
        if record.state not in (OrderState.FILLED, OrderState.ACKED):
            return False
        try:
            seen = self.broker.get_order(self.symbol, record.client_order_id)
        except Exception:
            return False
        return seen.get("status") in ("NEW", "FILLED", "PARTIALLY_FILLED")

    def _emergency_flatten(self, reason: str) -> Dict[str, Any]:
        pos = query_position(self.broker, self.symbol)
        if pos.kind == PositionQueryKind.UNKNOWN:
            self.store.halt = HaltState.RECOVERY_REQUIRED
            self.store.halt_reason = f"{reason}; flatten position UNKNOWN"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        if pos.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.halt = HaltState.HALTED
            self.store.halt_reason = f"{reason}; already flat"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        flatten_cid = self._cid("FLAT")
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        flat = self._place(
            flatten_cid,
            side=close_side,
            positionSide=pos.side,
            type="MARKET",
            quantity=pos.size,
            reduceOnly=True,
        )
        confirm = query_position(self.broker, self.symbol)
        if confirm.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.halt = HaltState.HALTED
            self.store.halt_reason = f"{reason}; emergency reduceOnly flattened"
            self.persist.save(self.store)
            return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

        self.store.halt = HaltState.RECOVERY_REQUIRED
        self.store.halt_reason = (
            f"{reason}; flatten state={flat.state.value} confirm={confirm.kind.value}"
        )
        self.persist.save(self.store)
        return {"success": False, "halt": self.store.halt.value, "reason": self.store.halt_reason}

    def execute_close(self) -> Dict[str, Any]:
        pos = query_position(self.broker, self.symbol)
        if pos.kind == PositionQueryKind.UNKNOWN:
            self.store.close_failed = True
            self.persist.save(self.store)
            return {"success": False, "reason": "close blocked: position UNKNOWN"}
        if pos.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.close_failed = False
            self.persist.save(self.store)
            self.reconcile("after_close")
            return {"success": True, "reason": "already flat"}

        cid = self._cid("CLOSE")
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        closed = self._place(
            cid, side=close_side, positionSide=pos.side, type="MARKET",
            quantity=pos.size, reduceOnly=True,
        )
        confirm = query_position(self.broker, self.symbol)
        if closed.state == OrderState.FILLED and confirm.kind == PositionQueryKind.FLAT:
            self.store.brain = BrainPosition()
            self.store.close_failed = False
            self.persist.save(self.store)
            self.reconcile("after_close")
            return {"success": True, "client_order_id": cid}

        self.store.close_failed = True
        self.persist.save(self.store)
        return {"success": False, "reason": "close unconfirmed; reverse open forbidden"}


