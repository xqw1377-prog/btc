from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime
import math

class Intent(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"

class RiskLevel(Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"

class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

@dataclass
class Signal:
    source: str
    direction: Intent
    confidence: float
    timeframe: str
    reason: str
    timestamp: float = 0

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = datetime.now().timestamp()

@dataclass
class TradeIntent:
    action: str  # OPEN / CLOSE / HOLD
    side: Intent
    size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    confidence: float
    risk_level: RiskLevel
    reason: str
    signals: List[Signal] = field(default_factory=list)

class ThresholdState(Enum):
    """保护阈值三态：不知道 / 明确未配置 / 有效。0.0 不再是合法哨兵。"""
    UNKNOWN = "UNKNOWN"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    VALID = "VALID"


def valid_threshold(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


@dataclass
class PositionState:
    side: PositionSide = PositionSide.NONE
    size: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss_state: ThresholdState = ThresholdState.UNKNOWN
    take_profit_state: ThresholdState = ThresholdState.UNKNOWN
    # 本地阈值来源：仅 STRATEGY 来源的 VALID SL 可被 trailing 更新；
    # 恢复同步的阈值不得被本地 trailing 升级成"已确认保护"。
    stop_loss_source: str = ""
    protection_note: str = ""
    entry_time: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.side != PositionSide.NONE and self.size > 0

    @property
    def protection_unknown(self) -> bool:
        """任一腿状态为 UNKNOWN → 保护存在未确认缺口。"""
        return self.is_open and (
            self.stop_loss_state == ThresholdState.UNKNOWN
            or self.take_profit_state == ThresholdState.UNKNOWN
        )

class PositionManager:
    def __init__(self):
        self._position = PositionState()
        self._history: List[Dict[str, Any]] = []

    @property
    def position(self) -> PositionState:
        return self._position

    def open(
        self, side: Intent, size: float, price: float,
        stop_loss: Optional[float], take_profit: Optional[float],
        reason: str,
        stop_loss_state: Optional[ThresholdState] = None,
        take_profit_state: Optional[ThresholdState] = None,
        stop_loss_source: str = "",
        protection_note: str = "",
    ):
        pos_side = PositionSide.LONG if side == Intent.LONG else PositionSide.SHORT

        def _resolve(value, explicit: Optional[ThresholdState]) -> ThresholdState:
            if valid_threshold(value):
                return ThresholdState.VALID
            if explicit == ThresholdState.NOT_CONFIGURED:
                return ThresholdState.NOT_CONFIGURED
            return ThresholdState.UNKNOWN

        self._position = PositionState(
            side=pos_side,
            size=size,
            entry_price=price,
            stop_loss=stop_loss if valid_threshold(stop_loss) else None,
            take_profit=take_profit if valid_threshold(take_profit) else None,
            stop_loss_state=_resolve(stop_loss, stop_loss_state),
            take_profit_state=_resolve(take_profit, take_profit_state),
            stop_loss_source=stop_loss_source,
            protection_note=protection_note,
            entry_time=datetime.now()
        )
        self._history.append({
            'action': 'OPEN', 'side': side.value, 'size': size,
            'price': price, 'reason': reason,
            'sl_state': self._position.stop_loss_state.value,
            'tp_state': self._position.take_profit_state.value,
            'protection_note': protection_note,
            'time': datetime.now().isoformat()
        })

    def close(self, price: float, reason: str) -> float:
        if not self._position.is_open:
            return 0.0

        if self._position.side == PositionSide.LONG:
            pnl = (price - self._position.entry_price) * self._position.size
        else:
            pnl = (self._position.entry_price - price) * self._position.size

        self._history.append({
            'action': 'CLOSE', 'side': self._position.side.value,
            'size': self._position.size, 'entry': self._position.entry_price,
            'exit': price, 'pnl': pnl, 'reason': reason,
            'time': datetime.now().isoformat()
        })

        self._position = PositionState()
        return pnl

    def update_price(self, price: float):
        if not self._position.is_open:
            return
        if self._position.side == PositionSide.LONG:
            self._position.unrealized_pnl = (price - self._position.entry_price) * self._position.size
        else:
            self._position.unrealized_pnl = (self._position.entry_price - price) * self._position.size

    def should_stop_loss(self, price: float) -> bool:
        # 先判状态与数值合法性，再比较价格；未知/未配置/无效阈值不触发。
        p = self._position
        if not p.is_open:
            return False
        if p.stop_loss_state != ThresholdState.VALID or not valid_threshold(p.stop_loss):
            return False
        if p.side == PositionSide.LONG:
            return price <= p.stop_loss
        return price >= p.stop_loss

    def should_take_profit(self, price: float) -> bool:
        p = self._position
        if not p.is_open:
            return False
        if p.take_profit_state != ThresholdState.VALID or not valid_threshold(p.take_profit):
            return False
        if p.side == PositionSide.LONG:
            return price >= p.take_profit
        return price <= p.take_profit

    def get_history(self) -> List[Dict[str, Any]]:
        return self._history