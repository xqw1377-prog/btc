"""Binance USDS-M adapter for the kernel ExchangePort.

The client is injected by the safety layer. This module never constructs
a venue SDK client and never chooses mainnet vs testnet.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
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
# 明确业务拒绝：参数/模式不兼容 → fail closed，不得改写参数重试。
_REJECT_MARKS = (
    "-1100", "-1102", "-2021", "-4120", "-4164", "min_notional",
    "stop_order_switch_algo", "illegal parameter", "mandatory parameter",
)
# 限频/系统过载：可重试，但绝不盲目重提交（先查询再收敛）。
_THROTTLE_MARKS = (
    "-1003", "-1008", "-1015", "418", "429", "503",
    "too many requests", "service unavailable", "system overload",
)

# G0-4A：USDⓈ-M 条件单已迁移 Algo 服务；旧 /fapi/v1/order 对
# STOP_MARKET 等条件单返回 -4120。保护腿唯一路径 = Algo API。
ALGO_ORDER_PATH = "algoOrder"
# 冻结产品默认：quantity-based 保护（不传 closePosition）、MARK_PRICE。
ALGO_WORKING_TYPE = "MARK_PRICE"
_ALGO_LEG_ID = re.compile(r"-(?:SL|TP)(?:$|\d+$|-(?:TOPUP|R)\d*$)")


@dataclass(frozen=True)
class AlgoOrderFact:
    algo_id: str
    client_algo_id: str
    symbol: str
    side: str
    position_side: str
    order_type: str
    trigger_price: float
    qty: float
    close_position: bool
    working_type: str
    status: str
    actual_order_id: Optional[str]
    observed_at: float


def _is_algo_leg(client_order_id: str) -> bool:
    return bool(_ALGO_LEG_ID.search(client_order_id))


def _required(raw: dict, field: str):
    if field not in raw or raw[field] is None:
        raise RuntimeError(f"algo response missing {field}")
    return raw[field]


def _bool_field(raw: dict, field: str) -> bool:
    value = _required(raw, field)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise RuntimeError(f"algo response invalid {field}")


def _algo_fact(raw: dict) -> AlgoOrderFact:
    if not isinstance(raw, dict):
        raise RuntimeError("algo response is not an object")
    return AlgoOrderFact(
        algo_id=str(_required(raw, "algoId")),
        client_algo_id=str(_required(raw, "clientAlgoId")),
        symbol=str(_required(raw, "symbol")),
        side=str(_required(raw, "side")).upper(),
        position_side=str(_required(raw, "positionSide")).upper(),
        order_type=str(_required(raw, "type")).upper(),
        trigger_price=float(_required(raw, "triggerPrice")),
        qty=float(_required(raw, "quantity")),
        close_position=_bool_field(raw, "closePosition"),
        working_type=str(_required(raw, "workingType")).upper(),
        status=_algo_status(raw),
        actual_order_id=(str(raw["actualOrderId"])
                         if raw.get("actualOrderId") not in (None, "") else None),
        observed_at=time.time(),
    )


def _algo_status(raw: dict) -> str:
    """algoStatus → 内核订单词汇；TRIGGERED/FINISHED 不等于成交/平仓。"""
    status = str(raw.get("algoStatus") or "").upper()
    if status == "NEW":
        return "NEW"
    if status in ("CANCELED", "CANCELLED"):
        return "CANCELLED"
    if status in ("EXPIRED", "EXPIRED_IN_MATCH"):
        return "EXPIRED"
    if status in ("TRIGGERED", "FINISHED", "REJECTED"):
        return status
    return "UNKNOWN"


def validate_algo_protection_contract(
    *, close_position: bool = False, quantity=None, reduce_only: bool = False,
) -> None:
    """官方互斥合同：closePosition=true 不得与 quantity/reduceOnly 同传。"""
    if close_position and quantity is not None:
        raise OrderRejectedError(
            "closePosition=true must not carry quantity")
    if close_position and reduce_only:
        raise OrderRejectedError(
            "closePosition=true must not carry reduceOnly")


def _is_rejected(exc: BaseException) -> bool:
    return any(m in _message(exc) for m in _REJECT_MARKS)


def _is_throttle(exc: BaseException) -> bool:
    return any(m in _message(exc) for m in _THROTTLE_MARKS)


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
    status = str(raw.get("status") or "").upper()
    if status in ("CANCELED", "CANCELLED", "EXPIRED"):
        return "CANCELLED"
    if status in ("NEW", "PARTIALLY_FILLED", "FILLED", "REJECTED"):
        return status
    return "UNKNOWN"


class BinanceExchange(ExchangePort):
    def __init__(self, client: Any, symbol: str = "BTCUSDT",
                 allow_mutate: bool = True, position_mode: Optional[str] = None):
        if client is None:
            raise SafetyViolation("[P0] armed exchange requires an injected client.")
        if position_mode not in (None, "ONE_WAY", "HEDGE"):
            raise SafetyViolation(f"[P0] unknown position_mode: {position_mode}")
        self._client = client
        self.symbol = symbol
        self.allow_mutate = allow_mutate
        self.position_mode = position_mode

    def position_mode_read(self) -> Optional[str]:
        """读取账户实际持仓模式（外部事实，查询失败/字段异常=UNKNOWN）。"""
        try:
            data = self._client.futures_get_position_mode()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        dual = data.get("dualSidePosition")
        if isinstance(dual, str) and dual.lower() in ("true", "false"):
            dual = dual.lower() == "true"
        if not isinstance(dual, bool):
            return None
        return "HEDGE" if dual else "ONE_WAY"

    def verify_position_mode(self, expected: str) -> str:
        if expected not in ("ONE_WAY", "HEDGE"):
            raise SafetyViolation(f"[P0] invalid approved position mode: {expected}")
        actual = self.position_mode_read()
        if actual is None:
            raise SafetyViolation("[P0] position mode UNKNOWN; refuse execution attach.")
        if actual != expected:
            raise SafetyViolation(
                f"[P0] position mode {actual} != approved {expected}; refuse attach.")
        self.position_mode = actual
        return actual

    def _refuse_mutate(self, action: str) -> None:
        if not self.allow_mutate:
            raise SafetyViolation(f"[P0] read-only exchange refuses {action}.")

    def submit_order(self, req: OrderRequest) -> OrderAck:
        self._refuse_mutate("submit")
        if req.order_kind in (OrderKind.STOP_LOSS, OrderKind.TAKE_PROFIT):
            # 条件保护腿唯一路径：Algo API。旧 futures_create_order(STOP_MARKET)
            # 自 2025-12-09 起会被 -4120 拒绝，本适配器不保留旧路径 fallback。
            return self._submit_algo(req)
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

    # ---- Algo 条件保护腿（G0-4A，冻结 quantity-based 合同）----

    def _algo_params(self, req: OrderRequest) -> dict:
        if self.position_mode is None:
            raise SafetyViolation(
                "[P0] position mode not verified; refuse Algo protection submit.")
        validate_algo_protection_contract(
            close_position=False, quantity=req.quantity,
            reduce_only=req.reduce_only)
        if req.position_side not in ("LONG", "SHORT"):
            raise OrderRejectedError("protection positionSide must be LONG or SHORT")
        expected_side = "SELL" if req.position_side == "LONG" else "BUY"
        if req.side != expected_side:
            raise OrderRejectedError(
                f"protection side {req.side} invalid for {req.position_side}")
        params = {
            "algoType": "CONDITIONAL",
            "symbol": req.symbol,
            "side": req.side,
            "positionSide": ("BOTH" if self.position_mode == "ONE_WAY"
                             else req.position_side),
            "type": ("STOP_MARKET" if req.order_kind == OrderKind.STOP_LOSS
                     else "TAKE_PROFIT_MARKET"),
            "triggerPrice": req.stop_price,
            "quantity": req.quantity,
            "workingType": ALGO_WORKING_TYPE,
            "clientAlgoId": req.client_order_id,
        }
        if self.position_mode == "ONE_WAY":
            params["reduceOnly"] = True
        return params

    def _algo_request(self, method: str, path: str, **kwargs):
        return self._client._request_futures_api(method, path, True, **kwargs)

    def _submit_algo(self, req: OrderRequest) -> OrderAck:
        params = self._algo_params(req)  # 本地合同错误发生在传输前，保持明确拒绝
        try:
            raw = self._algo_request("post", ALGO_ORDER_PATH, data=params)
        except Exception as exc:
            if _is_timeout(exc) or _is_throttle(exc):
                raise SubmitUnknownError(str(exc)) from exc
            if _is_duplicate(exc):
                raise DuplicateClientOrderIdError(req.client_order_id) from exc
            if _is_rejected(exc):
                raise OrderRejectedError(str(exc)) from exc
            raise SubmitUnknownError(str(exc)) from exc
        try:
            fact = _algo_fact(raw)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise SubmitUnknownError(f"algo submit response incomplete: {exc}") from exc
        expected = self._algo_params(req)
        if (
            fact.client_algo_id != req.client_order_id
            or fact.symbol != expected["symbol"]
            or fact.side != expected["side"]
            or fact.position_side != expected["positionSide"]
            or fact.order_type != expected["type"]
            or fact.trigger_price != float(expected["triggerPrice"])
            or fact.qty != float(expected["quantity"])
            or fact.close_position
            or fact.working_type != expected["workingType"]
        ):
            raise SubmitUnknownError("algo submit contract mismatch")
        if fact.status in ("REJECTED", "CANCELLED", "EXPIRED"):
            raise OrderRejectedError(
                f"algo protection rejected with status {fact.status}")
        if fact.status != "NEW":
            raise SubmitUnknownError(
                f"algo submit returned non-active status {fact.status}")
        return OrderAck(
            client_order_id=req.client_order_id,
            exchange_order_id=fact.algo_id,
            status=fact.status,
            filled_qty=0.0,
            avg_price=0.0,
        )

    def query_algo_order(self, client_order_id: str) -> Optional[AlgoOrderFact]:
        try:
            raw = self._algo_request(
                "get", ALGO_ORDER_PATH,
                data={"clientAlgoId": client_order_id})
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        fact = _algo_fact(raw)
        if fact.client_algo_id != client_order_id or fact.symbol != self.symbol:
            raise RuntimeError("algo query identity mismatch")
        if fact.working_type != ALGO_WORKING_TYPE:
            raise RuntimeError("algo query workingType mismatch")
        return fact

    def _query_algo(self, client_order_id: str) -> OrderFact:
        fact = self.query_algo_order(client_order_id)
        if fact is None:
            return OrderFact(client_order_id, "NOT_FOUND", 0.0, 0.0)
        return OrderFact(client_order_id, fact.status, 0.0, 0.0)

    def _cancel_algo(self, client_order_id: str) -> bool:
        try:
            raw = self._algo_request(
                "delete", ALGO_ORDER_PATH,
                data={"clientAlgoId": client_order_id})
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise CancelUnknownError(str(exc)) from exc
        return isinstance(raw, dict)

    def query_order(self, client_order_id: str) -> OrderFact:
        if _is_algo_leg(client_order_id):
            return self._query_algo(client_order_id)
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
        if _is_algo_leg(client_order_id):
            return self._cancel_algo(client_order_id)
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
        if _is_algo_leg(client_order_id):
            # Algo 腿：TRIGGERED 后由 actualOrderId 链接真实订单；
            # algoStatus 本身不是成交事实，缺 actualOrderId 不得编造 fill。
            try:
                raw = self._algo_request(
                    "get", ALGO_ORDER_PATH,
                    data={"clientAlgoId": client_order_id})
            except Exception:
                return []
            if not isinstance(raw, dict):
                return []
            order_id = raw.get("actualOrderId")
            if order_id is None or str(order_id) == "":
                return []
        else:
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
            if order_id is not None and str(trade.get("orderId")) != str(order_id):
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
        elif req.order_kind in (OrderKind.STOP_LOSS, OrderKind.TAKE_PROFIT):
            # RETIRED：条件保护腿不再走 /fapi/v1/order（-4120）。无 fallback。
            raise OrderRejectedError(
                "conditional orders retired on /fapi/v1/order; use Algo path")
        else:
            raise OrderRejectedError(f"unsupported order kind {req.order_kind}")
        if req.reduce_only:
            params["reduceOnly"] = True
        return params
