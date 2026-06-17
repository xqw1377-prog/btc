import asyncio
import sys
sys.path.insert(0, '.')

def test_emergency_controller():
    print("\n=== Testing Emergency Controller ===")
    from aurora.emergency_controller import EmergencyController, EmergencyMode
    
    controller = EmergencyController()
    
    assert controller.current_mode == EmergencyMode.NORMAL
    print("✅ Initial mode is NORMAL")
    
    trigger = controller.check_triggers(drawdown=0.06)
    assert trigger is not None
    print(f"✅ Trigger detected: {trigger}")
    
    trigger = controller.check_triggers(drawdown=0.01)
    assert trigger is None
    print("✅ No trigger for low drawdown")
    
    return True

def test_health_monitor():
    print("\n=== Testing Health Monitor ===")
    from aurora.health_monitor import HealthMonitor, HealthStatus
    
    monitor = HealthMonitor()
    
    monitor.update_metric('ws_connected', True)
    monitor.update_metric('ws_last_update', asyncio.get_event_loop().time())
    monitor.update_metric('api_error_count', 0)
    monitor.update_metric('api_success_count', 100)
    
    assert monitor.metrics['ws_connected'] == True
    print("✅ Metrics update works")
    
    status = monitor.get_status()
    assert 'overall_status' in status
    assert 'checks' in status
    assert 'metrics' in status
    print("✅ Status retrieval works")
    
    return True

def test_self_healing():
    print("\n=== Testing Self-Healing System ===")
    from aurora.self_healing import SelfHealingSystem
    
    healing = SelfHealingSystem()
    
    assert 'reconnect_websocket' in healing.recovery_actions
    assert 'reconcile_orders' in healing.recovery_actions
    assert 'resync_state' in healing.recovery_actions
    print("✅ Recovery actions registered")
    
    status = healing.get_status()
    assert 'is_recovering' in status
    assert 'state' in status
    print("✅ Status retrieval works")
    
    return True

def test_operator_panel():
    print("\n=== Testing Operator Panel ===")
    from aurora.operator_panel import OperatorPanel, OperatorCommand, TradingMode
    
    panel = OperatorPanel()
    
    assert panel.trading_mode == TradingMode.AUTO
    assert panel.is_paused == False
    print("✅ Initial state correct")
    
    result = asyncio.run(panel.execute_command(OperatorCommand.PAUSE, {'reason': 'Test'}))
    assert result['success'] == True
    assert panel.is_paused == True
    print("✅ Pause command works")
    
    result = asyncio.run(panel.execute_command(OperatorCommand.RESUME))
    assert result['success'] == True
    assert panel.is_paused == False
    print("✅ Resume command works")
    
    result = asyncio.run(panel.execute_command(OperatorCommand.SWITCH_MODE, {'mode': 'MANUAL'}))
    assert result['success'] == True
    assert panel.trading_mode == TradingMode.MANUAL
    print("✅ Mode switch works")
    
    return True

def test_disaster_recovery():
    print("\n=== Testing Disaster Recovery ===")
    from aurora.disaster_recovery import DisasterRecovery, DRState, DRPhase
    
    dr = DisasterRecovery()
    
    assert dr.state == DRState.NORMAL
    assert dr.current_phase is None
    print("✅ Initial state correct")
    
    dr.create_checkpoint('test', {'balance': 10000})
    checkpoint = dr.get_checkpoint('test')
    assert checkpoint is not None
    assert checkpoint['data']['balance'] == 10000
    print("✅ Checkpoint creation works")
    
    assert DRPhase.DETECTION in dr.recovery_plan
    assert DRPhase.CONTAINMENT in dr.recovery_plan
    assert DRPhase.RECOVERY in dr.recovery_plan
    print("✅ Recovery plan defined")
    
    return True

async def test_integration():
    print("\n=== Testing Integration ===")
    from aurora.emergency_controller import EmergencyController, EmergencyMode
    from aurora.health_monitor import HealthMonitor, HealthStatus
    from aurora.self_healing import SelfHealingSystem
    from aurora.operator_panel import OperatorPanel, OperatorCommand, TradingMode
    from aurora.disaster_recovery import DisasterRecovery, DRState
    
    emergency = EmergencyController()
    health = HealthMonitor()
    healing = SelfHealingSystem()
    operator = OperatorPanel()
    dr = DisasterRecovery()
    
    print("✅ All components initialized")
    
    health.update_metric('ws_connected', True)
    health.update_metric('api_error_count', 5)
    health.update_metric('api_success_count', 95)
    
    trigger = emergency.check_triggers(
        drawdown=0.02,
        api_error_rate=0.05,
        ws_connected=True
    )
    
    if trigger:
        print(f"   Trigger: {trigger}")
    
    await operator.execute_command(OperatorCommand.PAUSE, {'reason': 'Integration test'})
    assert operator.is_paused == True
    print("✅ Operator pause works")
    
    await operator.execute_command(OperatorCommand.RESUME)
    assert operator.is_paused == False
    print("✅ Operator resume works")
    
    incident_id = await dr.start_incident_response('test_incident', {'type': 'test'})
    assert dr.state != DRState.NORMAL
    print(f"✅ DR incident started: {incident_id}")
    
    status = {
        'emergency': emergency.get_status(),
        'health': health.get_status(),
        'healing': healing.get_status(),
        'operator': operator.get_status(),
        'dr': dr.get_status()
    }
    
    print("✅ All status retrieved")
    
    return True

def main():
    print("🚀 AURORA DR System Test")
    print("=" * 50)
    
    tests = [
        ("Emergency Controller", test_emergency_controller),
        ("Health Monitor", test_health_monitor),
        ("Self-Healing System", test_self_healing),
        ("Operator Panel", test_operator_panel),
        ("Disaster Recovery", test_disaster_recovery),
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
    
    try:
        result = asyncio.run(test_integration())
        results.append(("Integration", result))
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Integration", False))
    
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
        print("\n✅ All DR system tests passed!")
    else:
        print("\n❌ Some tests failed.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())