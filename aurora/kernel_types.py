from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime

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

@dataclass
class PositionState:
    side: PositionSide = PositionSide.NONE
    size: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    entry_time: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.side != PositionSide.NONE and self.size > 0

class PositionManager:
    def __init__(self):
        self._position = PositionState()
        self._history: List[Dict[str, Any]] = []

    @property
    def position(self) -> PositionState:
        return self._position

    def open(self, side: Intent, size: float, price: float, stop_loss: float, take_profit: float, reason: str):
        pos_side = PositionSide.LONG if side == Intent.LONG else PositionSide.SHORT
        self._position = PositionState(
            side=pos_side,
            size=size,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now()
        )
        self._history.append({
            'action': 'OPEN', 'side': side.value, 'size': size,
            'price': price, 'reason': reason, 'time': datetime.now().isoformat()
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
        if not self._position.is_open:
            return False
        if self._position.side == PositionSide.LONG:
            return price <= self._position.stop_loss
        return price >= self._position.stop_loss

    def should_take_profit(self, price: float) -> bool:
        if not self._position.is_open:
            return False
        if self._position.side == PositionSide.LONG:
            return price >= self._position.take_profit
        return price <= self._position.take_profit

    def get_history(self) -> List[Dict[str, Any]]:
        return self._history