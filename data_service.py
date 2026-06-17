import asyncio
import json
import os
import redis
from datetime import datetime
from aurora.binance_ws import BinanceWS
from aurora.feature_engine import FeatureEngine
import psycopg2

class DataService:
    def __init__(self):
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis = redis.Redis(host=self.redis_host, port=self.redis_port)
        
        self.pg_host = os.getenv('POSTGRES_HOST', 'localhost')
        self.pg_port = int(os.getenv('POSTGRES_PORT', 5432))
        self.pg_db = os.getenv('POSTGRES_DB', 'aurora')
        self.pg_user = os.getenv('POSTGRES_USER', 'aurora')
        self.pg_password = os.getenv('POSTGRES_PASSWORD', 'aurora123')
        
        self.ws = BinanceWS("btcusdt")
        self.feature_engine = FeatureEngine()
        
        self._init_db()
    
    def _init_db(self):
        try:
            conn = psycopg2.connect(
                host=self.pg_host,
                port=self.pg_port,
                dbname=self.pg_db,
                user=self.pg_user,
                password=self.pg_password
            )
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP,
                    open NUMERIC,
                    high NUMERIC,
                    low NUMERIC,
                    close NUMERIC,
                    volume NUMERIC,
                    vwap NUMERIC,
                    oi NUMERIC,
                    funding_rate NUMERIC
                )
            """)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"DB init error: {e}")
    
    def _save_to_db(self, data):
        try:
            conn = psycopg2.connect(
                host=self.pg_host,
                port=self.pg_port,
                dbname=self.pg_db,
                user=self.pg_user,
                password=self.pg_password
            )
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO market_data (timestamp, open, high, low, close, volume, vwap, oi, funding_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (data['timestamp'], data['open'], data['high'], data['low'], 
                  data['close'], data['volume'], data['vwap'], data['oi'], data['funding_rate']))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"DB save error: {e}")
    
    def _publish_event(self, event_type, data):
        event = {
            'type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        self.redis.xadd('market_events', {'event': json.dumps(event)})
    
    async def run(self):
        print("🚀 Data Service started")
        
        self.ws.start_in_thread()
        await asyncio.sleep(5)
        
        import pandas as pd
        
        while True:
            buffer = self.ws.get_buffer()
            
            if len(buffer) < 100:
                await asyncio.sleep(1)
                continue
            
            df = pd.DataFrame(buffer)
            latest = df.iloc[-1]
            
            features = self.feature_engine.get_latest_features(df)
            
            market_event = {
                'timestamp': latest['time'],
                'open': latest['open'],
                'high': latest['high'],
                'low': latest['low'],
                'close': latest['close'],
                'volume': latest['volume'],
                'vwap': features.get('vwap', latest['close']),
                'oi': features.get('oi', 0),
                'funding_rate': features.get('funding_rate', 0),
                'features': features
            }
            
            self._publish_event('market_update', market_event)
            self._save_to_db(market_event)
            
            await asyncio.sleep(1)

if __name__ == "__main__":
    service = DataService()
    asyncio.run(service.run())
