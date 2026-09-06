"""P0-B1: Durable Execution Truth（离线安全执行内核）。

分层真源：交易所=事实，SQLite 账本=持久化事实与意图，上层组合状态仅为投影。
真实 Binance 适配器见 binance_exchange.BinanceExchange（Client 必须由 safety 注入）。
"""
from .state_machine import IntentState, InvalidTransition, assert_transition  # noqa: F401
from .coverage import ProtectionStatus, compute_protection_status  # noqa: F401
from .port import (  # noqa: F401
    ExchangePort,
    ExchangePosition,
    Fill,
    OrderAck,
    OrderFact,
    OrderKind,
    OrderRequest,
    SubmitUnknownError,
    CancelUnknownError,
    OrderRejectedError,
    DuplicateClientOrderIdError,
)
from .fake_exchange import FakeExchange  # noqa: F401
from .binance_exchange import BinanceExchange  # noqa: F401
from .ledger import Ledger, PositionFactState  # noqa: F401
from .orchestrator import Orchestrator  # noqa: F401
