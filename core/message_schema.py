from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from datetime import datetime
import json

@dataclass
class MarketEvent:
    type: str
    symbol: str
    timestamp: float
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'symbol': self.symbol,
            'ts': self.timestamp,
            'data': self.data
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())

@dataclass
class KlineEvent(MarketEvent):
    def __init__(self, symbol: str, data: Dict[str, Any]):
        super().__init__(
            type='KLINE',
            symbol=symbol,
            timestamp=data.get('time', datetime.now().timestamp()),
            data={
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'close': float(data.get('close', 0)),
                'volume': float(data.get('volume', 0)),
                'is_closed': data.get('is_closed', False)
            }
        )

@dataclass
class SignalEvent:
    engine: str
    action: str
    direction: str
    confidence: float
    size: float
    reason: str
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'engine': self.engine,
            'action': self.action,
            'direction': self.direction,
            'confidence': self.confidence,
            'size': self.size,
            'reason': self.reason,
            'ts': self.timestamp
        }

@dataclass
class RiskEvent:
    type: str
    reason: str
    severity: str
    data: Dict[str, Any] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().timestamp()
        if self.data is None:
            self.data = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'reason': self.reason,
            'severity': self.severity,
            'data': self.data,
            'ts': self.timestamp
        }

@dataclass
class OrderEvent:
    order_id: str
    client_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float
    status: str
    filled_quantity: float = 0.0
    avg_price: float = 0.0
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'client_id': self.client_id,
            'symbol': self.symbol,
            'side': self.side,
            'type': self.order_type,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status,
            'filled_quantity': self.filled_quantity,
            'avg_price': self.avg_price,
            'ts': self.timestamp
        }

@dataclass
class TradeEvent:
    trade_id: str
    engine: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    reason: str
    regime: str
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_id': self.trade_id,
            'engine': self.engine,
            'direction': self.direction,
            'entry': self.entry_price,
            'exit': self.exit_price,
            'quantity': self.quantity,
            'pnl': self.pnl,
            'reason': self.reason,
            'regime': self.regime,
            'ts': self.timestamp
        }

class MessageValidator:
    @staticmethod
    def validate_market_event(data: Dict[str, Any]) -> bool:
        required = ['type', 'symbol', 'ts', 'data']
        return all(k in data for k in required)
    
    @staticmethod
    def validate_signal_event(data: Dict[str, Any]) -> bool:
        required = ['engine', 'action', 'direction', 'confidence']
        return all(k in data for k in required)
    
    @staticmethod
    def validate_risk_event(data: Dict[str, Any]) -> bool:
        required = ['type', 'reason', 'severity']
        return all(k in data for k in required)