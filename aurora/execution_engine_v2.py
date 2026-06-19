import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from binance.client import Client


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderType(Enum):
    MARKET_OPEN = "MARKET_OPEN"
    MARKET_CLOSE = "MARKET_CLOSE"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


@dataclass
class OrderRecord:
    client_order_id: str
    order_type: OrderType
    side: str
    size: float
    status: OrderStatus
    exchange_order_id: Optional[str] = None
    price: Optional[float] = None
    stop_price: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    retry_count: int = 0


@dataclass
class ExecutionResult:
    success: bool
    client_order_id: str
    exchange_order_id: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0


class ExecutionEngineV2:
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 1.0
    
    def __init__(self, client: Client, symbol: str = 'BTCUSDT'):
        self.client = client
        self.symbol = symbol
        self.order_history: Dict[str, OrderRecord] = {}
        self.stats = {
            'orders_placed': 0,
            'orders_failed': 0,
            'orders_retried': 0,
            'total_volume': 0.0,
            'errors': [],
        }
    
    def execute_open(self, side: str, size_btc: float, price: float,
                     stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None) -> ExecutionResult:
        
        if size_btc < 0.001:
            return ExecutionResult(
                success=False,
                client_order_id="",
                error="Size below minimum"
            )
        
        client_id = self._generate_client_id("OPEN")
        order_side = 'BUY' if side == 'LONG' else 'SELL'
        
        result = self._place_order_with_retry(
            client_order_id=client_id,
            order_type=OrderType.MARKET_OPEN,
            side=order_side,
            pos_side=side,
            quantity=round(size_btc, 3),
            price=price
        )
        
        if result.success and stop_loss:
            sl_side = 'SELL' if side == 'LONG' else 'BUY'
            sl_client_id = self._generate_client_id("SL")
            self._place_order_with_retry(
                client_order_id=sl_client_id,
                order_type=OrderType.STOP_LOSS,
                side=sl_side,
                pos_side=side,
                quantity=round(size_btc, 3),
                stop_price=round(stop_loss, 2)
            )
        
        if result.success and take_profit:
            tp_side = 'SELL' if side == 'LONG' else 'BUY'
            tp_client_id = self._generate_client_id("TP")
            self._place_order_with_retry(
                client_order_id=tp_client_id,
                order_type=OrderType.TAKE_PROFIT,
                side=tp_side,
                pos_side=side,
                quantity=round(size_btc, 3),
                stop_price=round(take_profit, 2)
            )
        
        return result
    
    def execute_close(self) -> ExecutionResult:
        position = self._get_exchange_position()
        if not position:
            return ExecutionResult(
                success=False,
                client_order_id="",
                error="No position to close"
            )
        
        amt = float(position['positionAmt'])
        side = 'SELL' if amt > 0 else 'BUY'
        pos_side = 'LONG' if amt > 0 else 'SHORT'
        
        self._cancel_all_orders()
        
        client_id = self._generate_client_id("CLOSE")
        return self._place_order_with_retry(
            client_order_id=client_id,
            order_type=OrderType.MARKET_CLOSE,
            side=side,
            pos_side=pos_side,
            quantity=abs(amt)
        )
    
    def _place_order_with_retry(self, client_order_id: str, order_type: OrderType,
                                 side: str, pos_side: str, quantity: float,
                                 price: Optional[float] = None,
                                 stop_price: Optional[float] = None) -> ExecutionResult:
        
        if client_order_id in self.order_history:
            existing = self.order_history[client_order_id]
            if existing.status == OrderStatus.FILLED:
                return ExecutionResult(
                    success=True,
                    client_order_id=client_order_id,
                    exchange_order_id=existing.exchange_order_id
                )
        
        record = OrderRecord(
            client_order_id=client_order_id,
            order_type=order_type,
            side=side,
            size=quantity,
            status=OrderStatus.PENDING,
            price=price,
            stop_price=stop_price
        )
        self.order_history[client_order_id] = record
        
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                order_params = {
                    'symbol': self.symbol,
                    'side': side,
                    'positionSide': pos_side,
                    'quantity': quantity,
                    'newClientOrderId': client_order_id,
                }
                
                if order_type == OrderType.STOP_LOSS:
                    order_params['type'] = 'STOP_MARKET'
                    order_params['stopPrice'] = stop_price
                elif order_type == OrderType.TAKE_PROFIT:
                    order_params['type'] = 'TAKE_PROFIT_MARKET'
                    order_params['stopPrice'] = stop_price
                else:
                    order_params['type'] = 'MARKET'
                
                order = self.client.futures_create_order(**order_params)
                
                record.status = OrderStatus.FILLED
                record.exchange_order_id = order['orderId']
                record.filled_at = datetime.now()
                
                self.stats['orders_placed'] += 1
                self.stats['total_volume'] += quantity * (price or 0)
                
                return ExecutionResult(
                    success=True,
                    client_order_id=client_order_id,
                    exchange_order_id=order['orderId'],
                    retries=attempt
                )
                
            except Exception as e:
                last_error = str(e)
                record.retry_count = attempt + 1
                self.stats['orders_retried'] += 1
                
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY_BASE * (2 ** attempt)
                    time.sleep(delay)
        
        record.status = OrderStatus.FAILED
        record.error = last_error
        self.stats['orders_failed'] += 1
        self.stats['errors'].append({
            'time': datetime.now().isoformat(),
            'order_id': client_order_id,
            'error': last_error
        })
        
        return ExecutionResult(
            success=False,
            client_order_id=client_order_id,
            error=last_error,
            retries=self.MAX_RETRIES
        )
    
    def _cancel_all_orders(self):
        try:
            self.client.futures_cancel_all_open_orders(symbol=self.symbol)
        except Exception:
            pass
    
    def _get_exchange_position(self) -> Optional[Dict[str, Any]]:
        try:
            positions = self.client.futures_position_information(symbol=self.symbol)
            for pos in positions:
                if float(pos['positionAmt']) != 0:
                    return pos
            return None
        except Exception:
            return None
    
    def _generate_client_id(self, prefix: str) -> str:
        short_uuid = uuid.uuid4().hex[:8]
        return f"AURORA_{prefix}_{short_uuid}"
    
    def reconcile_position(self, brain_position: Dict[str, Any]) -> Dict[str, Any]:
        exch_pos = self._get_exchange_position()
        brain_open = brain_position.get('is_open', False)
        
        if exch_pos and not brain_open:
            amt = float(exch_pos['positionAmt'])
            return {
                'action': 'SYNC_OPEN',
                'side': 'LONG' if amt > 0 else 'SHORT',
                'size': abs(amt),
                'entry_price': float(exch_pos['entryPrice']),
                'reason': 'Position on exchange but not in brain'
            }
        
        if not exch_pos and brain_open:
            return {
                'action': 'SYNC_CLOSE',
                'reason': 'Position in brain but not on exchange'
            }
        
        if exch_pos and brain_open:
            exch_size = abs(float(exch_pos['positionAmt']))
            brain_size = brain_position.get('size', 0)
            
            if abs(exch_size - brain_size) > 0.001:
                return {
                    'action': 'SIZE_MISMATCH',
                    'exchange_size': exch_size,
                    'brain_size': brain_size,
                    'reason': 'Position size mismatch'
                }
        
        return {'action': 'NONE'}
    
    def get_position_info(self) -> Optional[Dict[str, Any]]:
        pos = self._get_exchange_position()
        if not pos:
            return None
        
        return {
            'side': 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT',
            'size': abs(float(pos['positionAmt'])),
            'entry_price': float(pos['entryPrice']),
            'unrealized_pnl': float(pos.get('unRealizedProfit', 0)),
            'leverage': int(pos.get('leverage', 3)),
        }
    
    def get_order_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        orders = sorted(
            self.order_history.values(),
            key=lambda x: x.created_at,
            reverse=True
        )[:limit]
        
        return [
            {
                'client_order_id': o.client_order_id,
                'type': o.order_type.value,
                'side': o.side,
                'size': o.size,
                'status': o.status.value,
                'exchange_order_id': o.exchange_order_id,
                'price': o.price,
                'stop_price': o.stop_price,
                'error': o.error,
                'created_at': o.created_at.isoformat(),
                'filled_at': o.filled_at.isoformat() if o.filled_at else None,
                'retry_count': o.retry_count,
            }
            for o in orders
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            'pending_orders': sum(1 for o in self.order_history.values() if o.status == OrderStatus.PENDING),
            'filled_orders': sum(1 for o in self.order_history.values() if o.status == OrderStatus.FILLED),
            'failed_orders': sum(1 for o in self.order_history.values() if o.status == OrderStatus.FAILED),
        }
    
    def health_check(self) -> Dict[str, Any]:
        try:
            account = self.client.futures_account()
            return {
                'status': 'healthy',
                'connection': True,
                'balance': float(account['availableBalance']),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'connection': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
