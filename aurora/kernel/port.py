"""ExchangePort 抽象接口（P0-B1）。

真实 Binance 适配器属 P0-B2+；P0-B1 仅允许 FakeExchange 实现。
关键语义：
- submit_order 超时/中断抛 SubmitUnknownError —— 结果未知，禁止自动重提；
- query_order 是 SUBMIT_UNKNOWN 的唯一合法出路（事实查询）；
- position 返回 None 表示交易所事实不可知（UNKNOWN），不得解释为空仓。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class OrderKind(str, Enum):
    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    CLOSE = "CLOSE"


class SubmitUnknownError(Exception):
    """下单结果未知（超时/断连）。禁止自动重提，必须先 query_order。"""


class OrderRejectedError(Exception):
    """交易所明确拒单。"""


class DuplicateClientOrderIdError(Exception):
    """client_order_id 已存在 —— 交易所侧幂等护栏。"""


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    order_kind: OrderKind
    side: str                 # BUY / SELL
    position_side: str        # LONG / SHORT
    quantity: float
    stop_price: Optional[float] = None
    reduce_only: bool = False


@dataclass(frozen=True)
class OrderAck:
    client_order_id: str
    exchange_order_id: str
    status: str               # NEW / PARTIALLY_FILLED / FILLED
    filled_qty: float
    avg_price: float


@dataclass(frozen=True)
class OrderFact:
    client_order_id: str
    status: str               # NOT_FOUND / NEW / PARTIALLY_FILLED / FILLED / CANCELLED
    filled_qty: float
    avg_price: float


@dataclass(frozen=True)
class Fill:
    fill_id: str
    client_order_id: str
    qty: float
    price: float
    fee: float
    side: str
    filled_at: str


@dataclass(frozen=True)
class ExchangePosition:
    symbol: str
    signed_qty: float         # >0 LONG, <0 SHORT
    entry_price: float


class ExchangePort(ABC):
    @abstractmethod
    def submit_order(self, req: OrderRequest) -> OrderAck:
        ...

    @abstractmethod
    def query_order(self, client_order_id: str) -> OrderFact:
        ...

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> bool:
        ...

    @abstractmethod
    def position(self, symbol: str) -> Optional[ExchangePosition]:
        ...

    @abstractmethod
    def fills(self, client_order_id: str) -> List[Fill]:
        ...
