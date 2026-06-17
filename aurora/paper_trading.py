from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class OrderSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"

class Order:
    def __init__(self, order_id: str, symbol: str, side: str, order_type: str, size: float, price: float = 0.0):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.size = size
        self.price = price
        self.filled_size = 0.0
        self.filled_price = 0.0
        self.status = OrderStatus.PENDING.value
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def fill(self, fill_price: float, fill_size: Optional[float] = None):
        if fill_size is None:
            fill_size = self.size
        
        self.filled_size = fill_size
        self.filled_price = fill_price
        self.status = OrderStatus.FILLED.value if fill_size >= self.size else OrderStatus.PARTIAL.value
        self.updated_at = datetime.now()
    
    def cancel(self):
        self.status = OrderStatus.CANCELLED.value
        self.updated_at = datetime.now()

class Position:
    def __init__(self, symbol: str, side: str, size: float, entry_price: float):
        self.symbol = symbol
        self.side = side
        self.size = size
        self.entry_price = entry_price
        self.open_time = datetime.now()
        self.status = "OPEN"
        self.pnl = 0.0
    
    def update_pnl(self, current_price: float):
        if self.side == "LONG":
            self.pnl = (current_price - self.entry_price) * self.size
        else:
            self.pnl = (self.entry_price - current_price) * self.size
    
    def close(self, close_price: float):
        self.update_pnl(close_price)
        self.status = "CLOSED"

class PaperTradingAccount:
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.order_id_counter = 0
        self.trade_history = []
        self.last_price = 0.0
    
    def generate_order_id(self) -> str:
        self.order_id_counter += 1
        return f"ORD-{self.order_id_counter}-{datetime.now().timestamp()}"
    
    def place_order(self, symbol: str, side: str, order_type: str, size: float, price: float = 0.0) -> Dict[str, Any]:
        order_id = self.generate_order_id()
        
        if order_type == OrderType.MARKET.value:
            fill_price = self.last_price if self.last_price > 0 else price
            order = Order(order_id, symbol, side, order_type, size, fill_price)
            order.fill(fill_price, size)
            
            if side == OrderSide.LONG.value:
                if size * fill_price > self.balance:
                    return {"success": False, "message": "Insufficient balance"}
                self.balance -= size * fill_price
                self.positions[symbol] = Position(symbol, side, size, fill_price)
            else:
                self.positions[symbol] = Position(symbol, side, size, fill_price)
            
            self.trade_history.append({
                "order_id": order_id,
                "type": order_type,
                "side": side,
                "size": size,
                "price": fill_price,
                "timestamp": datetime.now()
            })
            
            return {"success": True, "order_id": order_id, "fill_price": fill_price}
        
        else:
            order = Order(order_id, symbol, side, order_type, size, price)
            self.orders[order_id] = order
            return {"success": True, "order_id": order_id}
    
    def close_position(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.positions:
            return {"success": False, "message": "No open position"}
        
        position = self.positions[symbol]
        close_price = self.last_price if self.last_price > 0 else position.entry_price
        
        position.close(close_price)
        
        if position.side == OrderSide.LONG.value:
            self.balance += position.size * close_price
        
        self.trade_history.append({
            "action": "CLOSE",
            "symbol": symbol,
            "side": position.side,
            "size": position.size,
            "entry_price": position.entry_price,
            "close_price": close_price,
            "pnl": position.pnl,
            "timestamp": datetime.now()
        })
        
        del self.positions[symbol]
        
        return {"success": True, "pnl": position.pnl, "close_price": close_price}
    
    def update(self, current_price: float):
        self.last_price = current_price
        
        for symbol, position in self.positions.items():
            position.update_pnl(current_price)
        
        position_value = sum(pos.size * current_price for pos in self.positions.values())
        self.equity = self.balance + position_value
    
    def get_account_summary(self) -> Dict[str, Any]:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "positions": {sym: {
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "pnl": round(pos.pnl, 2),
                "status": pos.status
            } for sym, pos in self.positions.items()},
            "open_orders": len(self.orders),
            "total_trades": len(self.trade_history)
        }
    
    def get_pnl(self) -> float:
        return sum(pos.pnl for pos in self.positions.values())
