"""Binance USDS-M adapter for the kernel ExchangePort.

The client is injected by the safety layer. This module never constructs
a venue SDK client and never chooses mainnet vs testnet.
"""
from __future__ import annotations

from typing import Any, List, Optional

from aurora.p0_boundary import SafetyViolation

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

_TIMEOUT_MARKS = ("timeout", "timed out", "timedout", "connection reset", "connection aborted")
_NOT_FOUND_MARKS = ("-2013", "order does not exist", "unknown order")
_DUPLICATE_MARKS = ("duplicate", "-4087", "clientorderid")


def _message(exc: BaseException) -> str:
    return str(exc).lower()


def _is_timeout(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if "timeout" in name or name in {"connectionerror", "connectionabortederror"}:
        return True
    msg = _message(exc)
    return any(mark in msg for mark in _TIMEOUT_MARKS)


def _is_not_found(exc: BaseException) -> bool:
    msg = _message(exc)
    return any(mark in msg for mark in _NOT_FOUND_MARKS)


def _is_duplicate(exc: BaseException) -> bool:
    msg = _message(exc)
    return any(mark in msg for mark in _DUPLICATE_MARKS)


def _status(raw: dict) -> str:
    status = str(raw.get("status") or "NEW").upper()
    if status in ("CANCELED", "CANCELLED", "EXPIRED"):
        return "CANCELLED"
    if status in ("NEW", "PARTIALLY_FILLED", "FILLED"):
        return status
    return "NEW"


class BinanceExchange(ExchangePort):
    def __init__(self, client: Any, symbol: str = "BTCUSDT", allow_mutate: bool = True):
        if client is None:
            raise SafetyViolation("[P0] armed exchange requires an injected client.")
        self._client = client
        self.symbol = symbol
        self.allow_mutate = allow_mutate

    def _refuse_mutate(self, action: str) -> None:
        if not self.allow_mutate:
            raise SafetyViolation(f"[P0] read-only exchange refuses {action}.")

    def submit_order(self, req: OrderRequest) -> OrderAck:
        self._refuse_mutate("submit")
        params = self._params(req)
        try:
            raw = self._client.futures_create_order(**params)
        except Exception as exc:
            if _is_timeout(exc):
                raise SubmitUnknownError(str(exc)) from exc
            if _is_duplicate(exc):
                raise DuplicateClientOrderIdError(req.client_order_id) from exc
            raise OrderRejectedError(str(exc)) from exc
        if not isinstance(raw, dict):
            raise SubmitUnknownError("submit returned non-dict")
        return OrderAck(
            client_order_id=req.client_order_id,
            exchange_order_id=str(raw.get("orderId") or req.client_order_id),
            status=_status(raw),
            filled_qty=float(raw.get("executedQty") or 0),
            avg_price=float(raw.get("avgPrice") or 0),
        )

    def query_order(self, client_order_id: str) -> OrderFact:
        try:
            raw = self._client.futures_get_order(
                symbol=self.symbol, origClientOrderId=client_order_id)
        except Exception as exc:
            if _is_not_found(exc):
                return OrderFact(client_order_id, "NOT_FOUND", 0.0, 0.0)
            raise
        if not isinstance(raw, dict):
            raise RuntimeError("order query returned non-dict")
        return OrderFact(
            client_order_id,
            _status(raw),
            float(raw.get("executedQty") or 0),
            float(raw.get("avgPrice") or 0),
        )

    def cancel_order(self, client_order_id: str) -> bool:
        self._refuse_mutate("cancel")
        try:
            raw = self._client.futures_cancel_order(
                symbol=self.symbol, origClientOrderId=client_order_id)
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise CancelUnknownError(str(exc)) from exc
        return isinstance(raw, dict)

    def position(self, symbol: str) -> Optional[ExchangePosition]:
        try:
            rows = self._client.futures_position_information(symbol=symbol)
        except Exception:
            return None
        if rows is None:
            return None
        open_legs = []
        for row in rows:
            amt = float(row.get("positionAmt") or 0)
            if amt != 0:
                open_legs.append((amt, row))
        if len(open_legs) > 1:
            return None
        if not open_legs:
            return ExchangePosition(symbol, 0.0, 0.0)
        amt, row = open_legs[0]
        return ExchangePosition(symbol, amt, float(row.get("entryPrice") or 0))

    def fills(self, client_order_id: str) -> List[Fill]:
        try:
            raw = self._client.futures_get_order(
                symbol=self.symbol, origClientOrderId=client_order_id)
        except Exception:
            return []
        if not isinstance(raw, dict):
            return []
        order_id = raw.get("orderId")
        try:
            trades = self._client.futures_account_trades(symbol=self.symbol) or []
        except Exception:
            return []
        out: List[Fill] = []
        for trade in trades:
            if order_id is not None and trade.get("orderId") != order_id:
                continue
            if order_id is None and str(trade.get("clientOrderId") or "") != client_order_id:
                continue
            out.append(Fill(
                fill_id=str(trade.get("id") or trade.get("tradeId") or f"{client_order_id}-T"),
                client_order_id=client_order_id,
                qty=float(trade.get("qty") or 0),
                price=float(trade.get("price") or 0),
                fee=float(trade.get("commission") or 0),
                side=str(trade.get("side") or "BUY"),
                filled_at=str(trade.get("time") or ""),
            ))
        return out

    @staticmethod
    def _params(req: OrderRequest) -> dict:
        params = {
            "symbol": req.symbol,
            "side": req.side,
            "positionSide": req.position_side,
            "quantity": req.quantity,
            "newClientOrderId": req.client_order_id,
        }
        if req.order_kind == OrderKind.ENTRY:
            params["type"] = "MARKET"
        elif req.order_kind == OrderKind.CLOSE:
            params["type"] = "MARKET"
            params["reduceOnly"] = True
        elif req.order_kind == OrderKind.STOP_LOSS:
            params["type"] = "STOP_MARKET"
            params["stopPrice"] = req.stop_price
            params["reduceOnly"] = True
        elif req.order_kind == OrderKind.TAKE_PROFIT:
            params["type"] = "TAKE_PROFIT_MARKET"
            params["stopPrice"] = req.stop_price
            params["reduceOnly"] = True
        else:
            raise OrderRejectedError(f"unsupported order kind {req.order_kind}")
        if req.reduce_only:
            params["reduceOnly"] = True
        return params
