import sys
sys.path.insert(0, '.')

def test_capital_allocator():
    print("\n=== Testing Capital Allocator ===")
    from aurora.capital_allocator import CapitalAllocator, CapitalBucket
    
    allocator = CapitalAllocator(100000)
    
    assert allocator.total_capital == 100000
    assert len(allocator.buckets) == 4
    print("✅ Capital allocator initialized")
    
    aggressive = allocator.get_allocation(CapitalBucket.AGGRESSIVE)
    assert aggressive.capital == 20000
    print(f"✅ Aggressive bucket: ${aggressive.capital:,.2f}")
    
    result = allocator.allocate_trade(CapitalBucket.TREND, 5000)
    assert result['success'] == True
    print(f"✅ Allocated $5,000 to TREND")
    
    result = allocator.allocate_trade(CapitalBucket.TREND, 60000)
    assert result['success'] == False
    print("✅ Rejected oversized allocation")
    
    summary = allocator.get_allocation_summary()
    assert 'total_capital' in summary
    assert 'buckets' in summary
    print("✅ Allocation summary works")
    
    return True

def test_risk_budgeting():
    print("\n=== Testing Risk Budgeting ===")
    from aurora.risk_budgeting import RiskBudgetManager, RiskCategory, PortfolioRiskManager
    
    manager = RiskBudgetManager(100000)
    
    assert manager.total_capital == 100000
    assert len(manager.budgets) == 4
    print("✅ Risk budget manager initialized")
    
    check = manager.check_budget(RiskCategory.MARKET, 1000)
    assert check['approved'] == True
    print("✅ Budget check works")
    
    result = manager.allocate_risk(RiskCategory.MARKET, 1000)
    assert result['success'] == True
    print(f"✅ Allocated risk budget")
    
    portfolio = PortfolioRiskManager(100000)
    portfolio.add_position('BTCUSDT', 0.1, 65000, 'LONG')
    portfolio.update_position('BTCUSDT', 66000)
    
    assert portfolio.positions['BTCUSDT']['unrealized_pnl'] == 100
    print("✅ Position tracking works")
    
    stress_results = portfolio.run_stress_test()
    assert 'btc_crash_10' in stress_results
    print(f"✅ Stress test: worst case = ${stress_results['btc_crash_10']['total_loss']:,.2f}")
    
    return True

def test_portfolio_mixer():
    print("\n=== Testing Portfolio Mixer ===")
    from aurora.portfolio_mixer import PortfolioMixer, StrategyType, BTCMultiStrategy
    
    mixer = PortfolioMixer(100000)
    
    assert mixer.total_capital == 100000
    assert len(mixer.strategies) == 4
    print("✅ Portfolio mixer initialized")
    
    mixer.update_performance(StrategyType.TREND, sharpe=1.5, win_rate=0.6, drawdown=0.05)
    mixer.adjust_weights()
    print("✅ Weight adjustment works")
    
    signals = {
        StrategyType.TREND: {'direction': 'LONG', 'confidence': 0.8},
        StrategyType.MEAN_REVERSION: {'direction': 'LONG', 'confidence': 0.6},
        StrategyType.BREAKOUT: {'direction': 'SHORT', 'confidence': 0.4},
        StrategyType.MOMENTUM: {'direction': 'LONG', 'confidence': 0.7}
    }
    
    combined = mixer.get_combined_signal(signals)
    assert 'direction' in combined
    assert 'confidence' in combined
    print(f"✅ Combined signal: {combined['direction']} ({combined['confidence']:.2f})")
    
    btc_strategy = BTCMultiStrategy(100000)
    features = {
        'ema20': 65100,
        'ema60': 65000,
        'adx': 30,
        'close': 65200,
        'vwap': 65000,
        'rsi': 55,
        'momentum': 200,
        'momentum_pct': 0.003
    }
    
    signal = btc_strategy.generate_combined_signal(features)
    print(f"✅ BTC multi-strategy signal: {signal['direction']}")
    
    return True

def test_institutional_risk():
    print("\n=== Testing Institutional Risk ===")
    from aurora.institutional_risk import VARCalculator, StressTestEngine, InstitutionalRiskManager
    
    var_calc = VARCalculator(100000)
    
    returns = [0.01, -0.02, 0.015, -0.01, 0.005, -0.03, 0.02, -0.015, 0.01, -0.005]
    
    var = var_calc.calculate_historical_var(returns, confidence=0.95)
    print(f"✅ Historical VaR (95%): ${var.var_amount:,.2f} ({var.var_pct:.2%})")
    
    var_mc = var_calc.calculate_monte_carlo_var(returns, confidence=0.95)
    print(f"✅ Monte Carlo VaR (95%): ${var_mc.var_amount:,.2f}")
    
    stress_engine = StressTestEngine(100000)
    positions = {
        'BTCUSDT': {'size': 0.1, 'entry_price': 65000, 'direction': 'LONG', 'current_price': 65000}
    }
    
    results = stress_engine.run_all_scenarios(positions)
    print(f"✅ Stress test: all survive = {results['all_survive']}")
    print(f"   Worst case: {results['worst_case']['scenario']} (${results['worst_case']['loss']:,.2f})")
    
    risk_manager = InstitutionalRiskManager(100000)
    risk_manager.add_position('BTCUSDT', 0.1, 65000, 'LONG')
    risk_manager.update_position_price('BTCUSDT', 66000)
    
    for ret in returns:
        risk_manager.add_return(ret)
    
    report = risk_manager.get_risk_report()
    print(f"✅ Risk report generated")
    print(f"   VaR analysis: {len(report['var_analysis']['var_by_confidence'])} confidence levels")
    print(f"   Limit check: compliant = {report['limit_check']['compliant']}")
    
    return True

def main():
    print("🚀 AURORA Hedge Fund Architecture Test")
    print("=" * 50)
    
    tests = [
        ("Capital Allocator", test_capital_allocator),
        ("Risk Budgeting", test_risk_budgeting),
        ("Portfolio Mixer", test_portfolio_mixer),
        ("Institutional Risk", test_institutional_risk),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print("=" * 50)
    
    all_passed = True
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        if not result:
            all_passed = False
        print(f"  {name}: {status}")
    
    print("=" * 50)
    
    if all_passed:
        print("\n✅ All Hedge Fund Architecture tests passed!")
        print("\n🚀 AURORA is now a Hedge Fund-grade system:")
        print("  - Capital Layer (Allocator + Risk Budget)")
        print("  - Portfolio Layer (Multi-Strategy Mixer)")
        print("  - Institutional Risk (VAR + Stress Testing)")
    else:
        print("\n❌ Some tests failed.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())