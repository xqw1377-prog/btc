import json
import os
from typing import Dict, Any, List, Generator
from datetime import datetime

class ReplayEngine:
    def __init__(self, data_dir: str = "replay_data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        
        self.recorded_events: List[Dict[str, Any]] = []
        self.replay_index = 0
        self.is_recording = False
        self.is_replaying = False
    
    def start_recording(self):
        self.is_recording = True
        self.recorded_events = []
        print("Recording started")
    
    def stop_recording(self):
        self.is_recording = False
        print(f"Recording stopped. {len(self.recorded_events)} events captured")
    
    def record_event(self, event_type: str, data: Dict[str, Any]):
        if not self.is_recording:
            return
        
        self.recorded_events.append({
            'timestamp': datetime.now().timestamp(),
            'event_type': event_type,
            'data': data
        })
    
    def save_recording(self, filename: str = None):
        if not self.recorded_events:
            print("No events to save")
            return
        
        if filename is None:
            filename = f"replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = os.path.join(self.data_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump({
                'recorded_at': datetime.now().isoformat(),
                'event_count': len(self.recorded_events),
                'events': self.recorded_events
            }, f, indent=2)
        
        print(f"Recording saved to {filepath}")
        return filepath
    
    def load_recording(self, filename: str) -> bool:
        filepath = os.path.join(self.data_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return False
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                self.recorded_events = data.get('events', [])
                print(f"Loaded {len(self.recorded_events)} events from {filename}")
                return True
        except Exception as e:
            print(f"Error loading recording: {e}")
            return False
    
    def get_events(self) -> Generator[Dict[str, Any], None, None]:
        self.is_replaying = True
        self.replay_index = 0
        
        for event in self.recorded_events:
            self.replay_index += 1
            yield event
        
        self.is_replaying = False
    
    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        return [e for e in self.recorded_events if e.get('event_type') == event_type]
    
    def get_replay_progress(self) -> Dict[str, Any]:
        return {
            'is_replaying': self.is_replaying,
            'current_index': self.replay_index,
            'total_events': len(self.recorded_events),
            'progress': self.replay_index / len(self.recorded_events) if self.recorded_events else 0
        }

class TradeReconstructor:
    def __init__(self):
        self.trades: List[Dict[str, Any]] = []
        self.current_trade = None
    
    def process_event(self, event: Dict[str, Any]):
        event_type = event.get('event_type')
        data = event.get('data', {})
        
        if event_type == 'SIGNAL':
            if data.get('signal') == 'ENTER':
                self.current_trade = {
                    'entry_time': event.get('timestamp'),
                    'entry_price': data.get('price'),
                    'direction': data.get('direction'),
                    'engine': data.get('engine'),
                    'regime': data.get('regime'),
                    'signals': [data]
                }
            elif data.get('signal') == 'EXIT' and self.current_trade:
                self.current_trade['exit_time'] = event.get('timestamp')
                self.current_trade['exit_price'] = data.get('price')
                self.current_trade['signals'].append(data)
                self.trades.append(self.current_trade)
                self.current_trade = None
        
        elif event_type == 'TRADE' and self.current_trade:
            self.current_trade['execution'] = data
    
    def get_reconstructed_trades(self) -> List[Dict[str, Any]]:
        return self.trades
    
    def analyze_trades(self) -> Dict[str, Any]:
        if not self.trades:
            return {}
        
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t.get('exit_price', 0) > t.get('entry_price', 0)])
        
        regime_trades = {}
        engine_trades = {}
        
        for trade in self.trades:
            regime = trade.get('regime', 'UNKNOWN')
            engine = trade.get('engine', 'UNKNOWN')
            
            if regime not in regime_trades:
                regime_trades[regime] = 0
            regime_trades[regime] += 1
            
            if engine not in engine_trades:
                engine_trades[engine] = 0
            engine_trades[engine] += 1
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': winning_trades / total_trades if total_trades > 0 else 0,
            'regime_distribution': regime_trades,
            'engine_distribution': engine_trades
        }

def replay_day(date_str: str, replay_dir: str = "replay_data"):
    filename = f"replay_{date_str}.json"
    filepath = os.path.join(replay_dir, filename)
    
    if not os.path.exists(filepath):
        print(f"No replay data for {date_str}")
        return None
    
    engine = ReplayEngine(replay_dir)
    engine.load_recording(filename)
    
    reconstructor = TradeReconstructor()
    
    for event in engine.get_events():
        reconstructor.process_event(event)
    
    analysis = reconstructor.analyze_trades()
    trades = reconstructor.get_reconstructed_trades()
    
    return {
        'date': date_str,
        'analysis': analysis,
        'trades': trades
    }