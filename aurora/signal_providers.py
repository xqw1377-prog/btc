from typing import Dict, Any
from .kernel_types import Signal, Intent

class TrendSignalProvider:
    TIMEFRAME = "5m"

    def generate(self, features: Dict[str, Any], regime: str) -> Signal:
        ema20 = features.get('ema20', 0)
        ema60 = features.get('ema60', 0)
        adx = features.get('adx', 0)
        ema_slope = features.get('ema_slope', 0)

        if adx < 20:
            return Signal(source="trend", direction=Intent.FLAT, confidence=0.2, timeframe=self.TIMEFRAME, reason="ADX too low")

        if ema20 > ema60 and ema_slope > 0:
            conf = min(0.5 + (adx - 20) / 60, 0.95)
            return Signal(source="trend", direction=Intent.LONG, confidence=conf, timeframe=self.TIMEFRAME, reason=f"EMA bullish ADX={adx:.0f}")

        if ema20 < ema60 and ema_slope < 0:
            conf = min(0.5 + (adx - 20) / 60, 0.95)
            return Signal(source="trend", direction=Intent.SHORT, confidence=conf, timeframe=self.TIMEFRAME, reason=f"EMA bearish ADX={adx:.0f}")

        return Signal(source="trend", direction=Intent.FLAT, confidence=0.3, timeframe=self.TIMEFRAME, reason="No clear trend")


class BreakoutSignalProvider:
    TIMEFRAME = "15m"

    def generate(self, features: Dict[str, Any], df=None) -> Signal:
        momentum = features.get('momentum', 0)
        momentum_pct = features.get('momentum_pct', 0)
        atr = features.get('atr', 0)
        close = features.get('close', 0)

        if df is not None and len(df) >= 30:
            high_30 = df['high'].tail(30).max()
            low_30 = df['low'].tail(30).min()

            if close > high_30 * 0.999 and abs(momentum_pct) > 0.003:
                conf = min(0.6 + abs(momentum_pct) * 20, 0.95)
                return Signal(source="breakout", direction=Intent.LONG, confidence=conf, timeframe=self.TIMEFRAME, reason=f"Breakout above {high_30:.0f}")

            if close < low_30 * 1.001 and abs(momentum_pct) > 0.003:
                conf = min(0.6 + abs(momentum_pct) * 20, 0.95)
                return Signal(source="breakout", direction=Intent.SHORT, confidence=conf, timeframe=self.TIMEFRAME, reason=f"Breakdown below {low_30:.0f}")

        if abs(momentum_pct) > 0.005:
            direction = Intent.LONG if momentum > 0 else Intent.SHORT
            conf = min(0.4 + abs(momentum_pct) * 10, 0.8)
            return Signal(source="breakout", direction=direction, confidence=conf, timeframe=self.TIMEFRAME, reason=f"Momentum {momentum_pct:.3%}")

        return Signal(source="breakout", direction=Intent.FLAT, confidence=0.2, timeframe=self.TIMEFRAME, reason="No breakout")


class MomentumSignalProvider:
    TIMEFRAME = "5m"

    def generate(self, features: Dict[str, Any]) -> Signal:
        rsi = features.get('rsi', 50)
        momentum_pct = features.get('momentum_pct', 0)

        if rsi > 70 and momentum_pct > 0.003:
            conf = min(0.5 + (rsi - 70) / 60, 0.9)
            return Signal(source="momentum", direction=Intent.LONG, confidence=conf, timeframe=self.TIMEFRAME, reason=f"RSI={rsi:.0f} strong")

        if rsi < 30 and momentum_pct < -0.003:
            conf = min(0.5 + (30 - rsi) / 60, 0.9)
            return Signal(source="momentum", direction=Intent.SHORT, confidence=conf, timeframe=self.TIMEFRAME, reason=f"RSI={rsi:.0f} weak")

        if 40 < rsi < 60:
            return Signal(source="momentum", direction=Intent.FLAT, confidence=0.2, timeframe=self.TIMEFRAME, reason=f"RSI neutral={rsi:.0f}")

        if rsi > 60:
            return Signal(source="momentum", direction=Intent.LONG, confidence=0.4, timeframe=self.TIMEFRAME, reason=f"RSI={rsi:.0f}")
        else:
            return Signal(source="momentum", direction=Intent.SHORT, confidence=0.4, timeframe=self.TIMEFRAME, reason=f"RSI={rsi:.0f}")


class MeanReversionSignalProvider:
    TIMEFRAME = "1m"

    def generate(self, features: Dict[str, Any]) -> Signal:
        close = features.get('close', 0)
        vwap = features.get('vwap', 0)
        rsi = features.get('rsi', 50)

        if vwap <= 0:
            return Signal(source="mr", direction=Intent.FLAT, confidence=0.2, timeframe=self.TIMEFRAME, reason="No VWAP")

        deviation = (close - vwap) / vwap

        if deviation < -0.003 and rsi < 35:
            conf = min(0.5 + abs(deviation) * 50, 0.9)
            return Signal(source="mr", direction=Intent.LONG, confidence=conf, timeframe=self.TIMEFRAME, reason=f"Below VWAP {deviation:.3%} RSI={rsi:.0f}")

        if deviation > 0.003 and rsi > 65:
            conf = min(0.5 + abs(deviation) * 50, 0.9)
            return Signal(source="mr", direction=Intent.SHORT, confidence=conf, timeframe=self.TIMEFRAME, reason=f"Above VWAP {deviation:.3%} RSI={rsi:.0f}")

        return Signal(source="mr", direction=Intent.FLAT, confidence=0.2, timeframe=self.TIMEFRAME, reason=f"Deviation {deviation:.3%} too small")