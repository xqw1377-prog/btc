from typing import Dict, Any, List, Tuple
from datetime import datetime
import json
import os

class OnlineLearner:
    def __init__(self, data_file: str = "brain_learning.json"):
        self.data_file = data_file

        self.regime_stats = {
            "TREND": {"trades": 0, "wins": 0, "total_pnl": 0.0, "avg_rr": 0.0},
            "RANGE": {"trades": 0, "wins": 0, "total_pnl": 0.0, "avg_rr": 0.0},
            "TRANSITION": {"trades": 0, "wins": 0, "total_pnl": 0.0, "avg_rr": 0.0},
        }

        self.signal_stats = {
            "trend": {"correct": 0, "total": 0, "weight": 1.0},
            "breakout": {"correct": 0, "total": 0, "weight": 1.0},
            "momentum": {"correct": 0, "total": 0, "weight": 1.0},
            "mr": {"correct": 0, "total": 0, "weight": 1.0},
        }

        self.trade_history: List[Dict[str, Any]] = []
        self.learning_rate = 0.05
        self.min_weight = 0.3
        self.max_weight = 2.0

        self._load()

    def record_trade(self, regime: str, signals: List[Dict[str, Any]],
                     entry_price: float, exit_price: float, side: str, pnl: float):
        pnl_pct = (exit_price - entry_price) / entry_price if side == "LONG" else (entry_price - exit_price) / entry_price
        is_win = pnl > 0

        record = {
            'timestamp': datetime.now().isoformat(),
            'regime': regime,
            'side': side,
            'entry': entry_price,
            'exit': exit_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'signals': [{'source': s.get('source', ''), 'direction': s.get('direction', ''), 'confidence': s.get('confidence', 0)} for s in signals],
        }
        self.trade_history.append(record)
        if len(self.trade_history) > 500:
            self.trade_history = self.trade_history[-500:]

        if regime in self.regime_stats:
            stats = self.regime_stats[regime]
            stats['trades'] += 1
            if is_win:
                stats['wins'] += 1
            stats['total_pnl'] += pnl
            if stats['trades'] > 0:
                wins = stats['wins']
                losses = stats['trades'] - wins
                avg_win = stats['total_pnl'] / wins if wins > 0 else 0
                avg_loss = abs(stats['total_pnl']) / losses if losses > 0 else 1
                stats['avg_rr'] = avg_win / avg_loss if avg_loss > 0 else 0

        for sig in signals:
            source = sig.get('source', '')
            if source in self.signal_stats:
                sig_stat = self.signal_stats[source]
                sig_stat['total'] += 1

                sig_dir = sig.get('direction', 'NEUTRAL')
                if sig_dir != 'NEUTRAL':
                    if (sig_dir == 'LONG' and is_win) or (sig_dir == 'SHORT' and is_win):
                        sig_stat['correct'] += 1

                if sig_stat['total'] >= 10:
                    accuracy = sig_stat['correct'] / sig_stat['total']
                    target_weight = 0.5 + accuracy * 1.5
                    sig_stat['weight'] += (target_weight - sig_stat['weight']) * self.learning_rate
                    sig_stat['weight'] = max(self.min_weight, min(self.max_weight, sig_stat['weight']))

        if len(self.trade_history) % 20 == 0:
            self._save()

    def get_regime_stats(self) -> Dict[str, Any]:
        result = {}
        for regime, stats in self.regime_stats.items():
            if stats['trades'] > 0:
                result[regime] = {
                    'win_rate': stats['wins'] / stats['trades'],
                    'avg_rr': stats['avg_rr'],
                    'total_pnl': stats['total_pnl'],
                    'trades': stats['trades'],
                }
            else:
                result[regime] = {'win_rate': 0.5, 'avg_rr': 1.0, 'total_pnl': 0, 'trades': 0}
        return result

    def get_signal_weights(self) -> Dict[str, float]:
        return {k: v['weight'] for k, v in self.signal_stats.items()}

    def get_best_regime(self) -> str:
        best = "TRANSITION"
        best_score = -float('inf')
        for regime, stats in self.regime_stats.items():
            if stats['trades'] < 5:
                continue
            win_rate = stats['wins'] / stats['trades']
            score = win_rate * stats['avg_rr']
            if score > best_score:
                best_score = score
                best = regime
        return best

    def should_trade_regime(self, regime: str) -> bool:
        stats = self.regime_stats.get(regime, {})
        if stats.get('trades', 0) < 5:
            return True
        win_rate = stats.get('wins', 0) / stats['trades']
        return win_rate > 0.35

    def _save(self):
        try:
            data = {
                'regime_stats': self.regime_stats,
                'signal_stats': self.signal_stats,
                'trade_history': self.trade_history[-200:],
                'updated': datetime.now().isoformat(),
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.regime_stats = data.get('regime_stats', self.regime_stats)
                    self.signal_stats = data.get('signal_stats', self.signal_stats)
                    self.trade_history = data.get('trade_history', [])
        except Exception:
            pass