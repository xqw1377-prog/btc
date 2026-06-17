import pandas as pd
import numpy as np
from typing import Dict, Any

class FeatureEngine:
    def __init__(self):
        self.ema_span_short = 20
        self.ema_span_long = 60
        self.atr_period = 14
        self.adx_period = 14
    
    def compute_ema(self, series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()
    
    def compute_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def compute_adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=high.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=high.index)
        
        tr = self.compute_atr(high, low, close, period)
        
        plus_di = 100 * (plus_dm.rolling(period).mean() / tr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / tr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(period).mean()
        
        return adx
    
    def compute_vwap(self, df: pd.DataFrame) -> pd.Series:
        cum_vol = df['volume'].cumsum()
        cum_vol_price = (df['close'] * df['volume']).cumsum()
        return cum_vol_price / cum_vol
    
    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        df['ema20'] = self.compute_ema(df['close'], self.ema_span_short)
        df['ema60'] = self.compute_ema(df['close'], self.ema_span_long)
        
        df['ret'] = df['close'].pct_change()
        df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
        
        df['atr'] = self.compute_atr(df['high'], df['low'], df['close'], self.atr_period)
        
        df['adx'] = self.compute_adx(df['high'], df['low'], df['close'], self.adx_period)
        
        df['momentum'] = df['close'] - df['close'].shift(5)
        df['momentum_pct'] = df['momentum'] / df['close'].shift(5)
        
        df['volatility'] = df['log_ret'].rolling(20).std() * np.sqrt(24 * 365)
        
        df['vwap'] = self.compute_vwap(df)
        
        df['ema_slope'] = df['ema20'] - df['ema20'].shift(5)
        
        return df
    
    def get_latest_features(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) == 0:
            return {}
        
        df = self.compute_all(df)
        latest = df.iloc[-1]
        
        return {
            'close': float(latest['close']),
            'ema20': float(latest['ema20']),
            'ema60': float(latest['ema60']),
            'atr': float(latest['atr']),
            'adx': float(latest['adx']),
            'momentum': float(latest['momentum']),
            'momentum_pct': float(latest['momentum_pct']),
            'volatility': float(latest['volatility']),
            'vwap': float(latest['vwap']),
            'ema_slope': float(latest['ema_slope']),
            'atr_mean': float(df['atr'].mean()),
            'adx_mean': float(df['adx'].mean()),
            'volume': float(latest['volume']),
            'is_uptrend': bool(latest['ema20'] > latest['ema60']),
            'is_momentum_positive': bool(latest['momentum'] > 0)
        }
