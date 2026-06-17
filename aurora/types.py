from typing import Literal, Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

Regime = Literal["TREND", "RANGE", "TRANSITION"]
Direction = Literal["LONG", "SHORT", "NONE"]

@dataclass
class MarketData:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    oi: float
    funding_rate: float

@dataclass
class MarketState:
    regime: Regime
    direction: Direction
    confidence: float
    adx: float
    atr: float
    volatility: float
    structure: str

@dataclass
class Signal:
    type: Literal["ENTER", "EXIT", "ADD", "NONE"]
    direction: Direction
    confidence: float
    reason: str

@dataclass
class Position:
    symbol: str
    direction: Direction
    size: float
    entry_price: float
    open_time: datetime
    pnl: float
    status: Literal["OPEN", "CLOSED"]

@dataclass
class Order:
    id: str
    symbol: str
    type: Literal["LIMIT", "MARKET"]
    side: Direction
    size: float
    price: Optional[float]
    status: Literal["PENDING", "PARTIAL", "FILLED", "REJECTED", "CANCELLED"]
    filled_size: float
    filled_price: float
    created_at: datetime
    updated_at: datetime

@dataclass
class RiskMetrics:
    daily_pnl: float
    max_drawdown: float
    current_exposure: float
    leverage: float
    consecutive_losses: int

@dataclass
class SentimentData:
    fear_greed: float
    funding_crowding: float
    sentiment_score: float
    risk_multiplier: float
