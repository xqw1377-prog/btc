import os
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.env = os.getenv('AURORA_ENV', 'development')
        
        self.binance = {
            'api_key': os.getenv('BINANCE_API_KEY', ''),
            'api_secret': os.getenv('BINANCE_API_SECRET', ''),
            'testnet': os.getenv('TESTNET', 'true').lower() == 'true',
            'symbol': 'BTCUSDT',
            'leverage': 3
        }
        
        self.redis = {
            'host': os.getenv('REDIS_HOST', 'localhost'),
            'port': int(os.getenv('REDIS_PORT', 6379)),
            'db': int(os.getenv('REDIS_DB', 0)),
            'url': os.getenv('REDIS_URL', 'redis://localhost:6379')
        }
        
        self.postgres = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'user': os.getenv('POSTGRES_USER', 'aurora'),
            'password': os.getenv('POSTGRES_PASSWORD', 'aurora'),
            'database': os.getenv('POSTGRES_DB', 'aurora')
        }
        
        self.telegram = {
            'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
            'chat_id': os.getenv('TELEGRAM_CHAT_ID', '')
        }
        
        self.risk = {
            'max_daily_loss_pct': 0.03,
            'max_drawdown_pct': 0.10,
            'max_consecutive_losses': 5,
            'max_leverage': 3.0,
            'max_exposure_pct': 0.30,
            'max_single_position_pct': 0.10,
            'min_trade_interval_sec': 300,
            'kill_switch_drawdown': 0.05,
            'kill_switch_daily_loss': 0.02
        }
        
        self.strategy = {
            'state_confirmation_count': 3,
            'trend_weight': 1.0,
            'exec_weight': 1.0,
            'base_risk_pct': 0.01
        }
        
        self.monitoring = {
            'log_dir': 'logs',
            'metrics_interval_sec': 60,
            'alert_cooldown_sec': 300
        }
    
    def is_production(self) -> bool:
        return self.env == 'production'
    
    def is_testnet(self) -> bool:
        return self.binance['testnet']
    
    def get_binance_config(self) -> Dict[str, Any]:
        return self.binance
    
    def get_redis_url(self) -> str:
        return self.redis['url']
    
    def get_postgres_url(self) -> str:
        return f"postgresql://{self.postgres['user']}:{self.postgres['password']}@{self.postgres['host']}:{self.postgres['port']}/{self.postgres['database']}"
    
    def validate(self) -> List[str]:
        errors = []
        
        if not self.binance['api_key']:
            errors.append("BINANCE_API_KEY not set")
        if not self.binance['api_secret']:
            errors.append("BINANCE_API_SECRET not set")
        if not self.telegram['bot_token'] and self.is_production():
            errors.append("TELEGRAM_BOT_TOKEN not set for production")
        
        return errors

config = Config()