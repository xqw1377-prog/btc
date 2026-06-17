import asyncio
import aiohttp
from typing import Dict, Any, Optional
from datetime import datetime
from collections import deque

class TelegramAlert:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.alert_cooldown = 300
        self.last_alerts: Dict[str, float] = {}
        self.alert_queue: deque = deque(maxlen=100)
    
    def _should_send(self, alert_type: str) -> bool:
        now = datetime.now().timestamp()
        last_sent = self.last_alerts.get(alert_type, 0)
        return (now - last_sent) > self.alert_cooldown
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.bot_token or not self.chat_id:
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': parse_mode
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        return True
                    else:
                        print(f"Telegram API error: {response.status}")
                        return False
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False
    
    async def alert_kill_switch(self, reason: str):
        if not self._should_send('kill_switch'):
            return
        
        message = f"""
🚨 <b>KILL SWITCH ACTIVATED</b>

<b>Reason:</b> {reason}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ All trading has been stopped.
"""
        await self.send_message(message)
        self.last_alerts['kill_switch'] = datetime.now().timestamp()
    
    async def alert_trade(self, trade_data: Dict[str, Any]):
        if not self._should_send('trade'):
            return
        
        message = f"""
📊 <b>Trade Executed</b>

<b>Engine:</b> {trade_data.get('engine', 'N/A')}
<b>Direction:</b> {trade_data.get('direction', 'N/A')}
<b>Price:</b> ${trade_data.get('price', 0):,.2f}
<b>Size:</b> {trade_data.get('quantity', 0):.4f} BTC
<b>PnL:</b> ${trade_data.get('pnl', 0):,.2f}
"""
        await self.send_message(message)
    
    async def alert_drawdown(self, drawdown: float):
        if not self._should_send('drawdown'):
            return
        
        message = f"""
⚠️ <b>Drawdown Alert</b>

<b>Current Drawdown:</b> {drawdown:.2%}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Monitor closely.
"""
        await self.send_message(message)
        self.last_alerts['drawdown'] = datetime.now().timestamp()
    
    async def alert_api_error(self, error: str):
        if not self._should_send('api_error'):
            return
        
        message = f"""
❌ <b>API Error</b>

<b>Error:</b> {error}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await self.send_message(message)
        self.last_alerts['api_error'] = datetime.now().timestamp()
    
    async def alert_daily_summary(self, summary: Dict[str, Any]):
        message = f"""
📈 <b>Daily Summary</b>

<b>PnL:</b> ${summary.get('daily_pnl', 0):,.2f}
<b>Trades:</b> {summary.get('trade_count', 0)}
<b>Win Rate:</b> {summary.get('win_rate', 0):.1%}
<b>Drawdown:</b> {summary.get('drawdown', 0):.2%}
<b>Balance:</b> ${summary.get('balance', 0):,.2f}
"""
        await self.send_message(message)
    
    async def alert_connection_loss(self):
        if not self._should_send('connection_loss'):
            return
        
        message = f"""
🔌 <b>Connection Lost</b>

WebSocket connection dropped.
Attempting to reconnect...
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await self.send_message(message)
        self.last_alerts['connection_loss'] = datetime.now().timestamp()

class AlertManager:
    def __init__(self, telegram: Optional[TelegramAlert] = None):
        self.telegram = telegram
        self.alert_history: deque = deque(maxlen=1000)
    
    async def send_alert(self, alert_type: str, data: Dict[str, Any]):
        self.alert_history.append({
            'type': alert_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
        
        if not self.telegram:
            return
        
        if alert_type == 'kill_switch':
            await self.telegram.alert_kill_switch(data.get('reason', 'Unknown'))
        elif alert_type == 'trade':
            await self.telegram.alert_trade(data)
        elif alert_type == 'drawdown':
            await self.telegram.alert_drawdown(data.get('drawdown', 0))
        elif alert_type == 'api_error':
            await self.telegram.alert_api_error(data.get('error', 'Unknown'))
        elif alert_type == 'connection_loss':
            await self.telegram.alert_connection_loss()
        elif alert_type == 'daily_summary':
            await self.telegram.alert_daily_summary(data)
    
    def get_recent_alerts(self, limit: int = 50) -> list:
        return list(self.alert_history)[-limit:]