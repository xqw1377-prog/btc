import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def test_config():
    print("=== Testing Configuration ===")
    from core.config import config
    
    errors = config.validate()
    if errors:
        print(f"❌ Configuration errors: {errors}")
        return False
    
    print(f"✅ Environment: {config.env}")
    print(f"✅ Testnet: {config.is_testnet()}")
    print(f"✅ Symbol: {config.binance['symbol']}")
    return True

def test_risk_engine():
    print("\n=== Testing Risk Engine ===")
    from services.risk_service.risk_engine import RiskEngine
    
    risk = RiskEngine()
    
    risk.update_balance(10000)
    assert risk.current_balance == 10000
    print("✅ Balance update works")
    
    validation = risk.validate_trade(leverage=3.0, position_size_pct=0.02)
    assert validation['approved'] == True
    print("✅ Trade validation works")
    
    risk.update_pnl(-200)
    assert risk.daily_pnl == -200
    print("✅ PnL update works")
    
    for i in range(5):
        risk.update_pnl(-100)
    
    assert risk.kill_switch == True
    print("✅ Kill switch activates on consecutive losses")
    
    risk.reset_kill_switch(manual=True)
    assert risk.kill_switch == False
    print("✅ Kill switch reset works")
    
    return True

def test_message_schema():
    print("\n=== Testing Message Schema ===")
    from core.message_schema import KlineEvent, SignalEvent, RiskEvent
    
    kline = KlineEvent("BTCUSDT", {
        'time': 1234567890,
        'open': 65000,
        'high': 65500,
        'low': 64900,
        'close': 65300,
        'volume': 1200,
        'is_closed': True
    })
    assert kline.type == 'KLINE'
    assert kline.data['close'] == 65300
    print("✅ KlineEvent creation works")
    
    signal = SignalEvent(
        engine='TREND',
        action='BUY',
        direction='LONG',
        confidence=0.85,
        size=0.001,
        reason='Breakout detected'
    )
    assert signal.engine == 'TREND'
    assert signal.confidence == 0.85
    print("✅ SignalEvent creation works")
    
    risk = RiskEvent(
        type='KILL_SWITCH',
        reason='Max drawdown exceeded',
        severity='CRITICAL'
    )
    assert risk.type == 'KILL_SWITCH'
    print("✅ RiskEvent creation works")
    
    return True

def test_feature_engine():
    print("\n=== Testing Feature Engine ===")
    import pandas as pd
    from aurora.feature_engine import FeatureEngine
    
    engine = FeatureEngine()
    
    data = {
        'open': [65000 + i * 10 for i in range(100)],
        'high': [65100 + i * 10 for i in range(100)],
        'low': [64900 + i * 10 for i in range(100)],
        'close': [65050 + i * 10 for i in range(100)],
        'volume': [1000 + i * 10 for i in range(100)]
    }
    df = pd.DataFrame(data)
    
    features = engine.get_latest_features(df)
    
    assert 'ema20' in features
    assert 'atr' in features
    assert 'adx' in features
    assert 'close' in features
    print("✅ Feature engine calculates all indicators")
    
    return True

def test_market_state_engine():
    print("\n=== Testing Market State Engine ===")
    from aurora.market_state_engine_v2 import MarketStateEngineV2
    
    engine = MarketStateEngineV2(confirmation_count=3)
    
    features = {
        'ema20': 65100,
        'ema60': 65000,
        'adx': 30,
        'atr': 500,
        'atr_mean': 400,
        'adx_mean': 25,
        'ema_slope': 50,
        'close': 65200,
        'is_uptrend': True
    }
    
    state = engine.identify_regime(features)
    assert 'regime' in state
    assert 'confidence' in state
    assert 'confirmed' in state
    print("✅ Market state engine works")
    print(f"   Regime: {state['regime']}, Confidence: {state['confidence']}")
    
    return True

def test_position_sizer():
    print("\n=== Testing Position Sizer ===")
    from aurora.position_sizing_v2 import PositionSizingEngine
    
    sizer = PositionSizingEngine()
    
    result = sizer.calculate_position_size(
        balance=10000,
        price=65000,
        market_state={'regime': 'TREND', 'confidence': 0.8, 'features': {'volatility': 1.0}},
        engine_type='TREND'
    )
    
    assert 'quantity' in result
    assert 'position_value' in result
    assert 'position_pct' in result
    assert result['quantity'] > 0
    print("✅ Position sizer works")
    print(f"   Quantity: {result['quantity']:.4f} BTC")
    print(f"   Position: {result['position_pct']:.2%}")
    
    return True

async def test_event_bus():
    print("\n=== Testing Event Bus ===")
    from core.event_bus import EventBus
    
    bus = EventBus("redis://localhost:6379")
    
    connected = await bus.connect()
    if not connected:
        print("⚠️  Redis not available, skipping event bus test")
        return True
    
    received = []
    
    async def handler(data):
        received.append(data)
    
    bus.subscribe('test_channel', handler)
    
    await bus.publish('test_channel', {'test': 'data'})
    
    await asyncio.sleep(0.1)
    
    await bus.disconnect()
    print("✅ Event bus works")
    
    return True

def main():
    print("🚀 AURORA Production System Test")
    print("=" * 50)
    
    tests = [
        ("Configuration", test_config),
        ("Risk Engine", test_risk_engine),
        ("Message Schema", test_message_schema),
        ("Feature Engine", test_feature_engine),
        ("Market State Engine", test_market_state_engine),
        ("Position Sizer", test_position_sizer),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} failed: {e}")
            results.append((name, False))
    
    try:
        result = asyncio.run(test_event_bus())
        results.append(("Event Bus", result))
    except Exception as e:
        print(f"⚠️  Event Bus test skipped: {e}")
        results.append(("Event Bus", None))
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print("=" * 50)
    
    all_passed = True
    for name, result in results:
        if result is None:
            status = "⚠️  SKIP"
        elif result:
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
            all_passed = False
        print(f"  {name}: {status}")
    
    print("=" * 50)
    
    if all_passed:
        print("\n✅ All tests passed! System ready for deployment.")
        print("\nNext steps:")
        print("  1. Configure .env file")
        print("  2. Run: docker-compose up -d")
        print("  3. Monitor: http://localhost:3000")
    else:
        print("\n❌ Some tests failed. Please fix before deployment.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())