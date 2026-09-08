"""CONTROLLED TESTNET REQUAL 实施包离线验收（合并版）。

覆盖：permit 签发/校验/生命周期、身份门无条件化（F）、规模与方向上限、
P0 基线、P1 WIRE ACK 三方验证、P3 ACTIVE_CONFIRMED、六阶段会话
成功与各停止条件、execute_live 硬拒、事故账本字节不变。
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.config_source import ConfigSource  # noqa: E402
from aurora.kernel.fake_exchange import FakeExchange  # noqa: E402
from aurora.kernel.ledger import Ledger  # noqa: E402
from aurora.kernel.orchestrator import Orchestrator  # noqa: E402
from aurora.ops_controlled_requal import (  # noqa: E402
    check_execution_conditions,
    EXECUTE_AUTHORIZED,
    issue_execution_window,
    read_session_final,
    write_session_final,
    FORBIDDEN_INTENT_MARK,
    INCIDENT_INTENT,
    MAX_NOTIONAL_USDT,
    MAX_QTY,
    WireTee,
    assert_intent_allowed,
    assert_qty_exact,
    assert_scale,
    assert_session_ledger_isolated,
    assert_session_start,
    assert_stop_price,
    assert_write_gates,
    baseline_from_probe,
    bind_permit,
    confirm_protection_active,
    execute_live,
    incident_ledger_path,
    issue_permit,
    leg_client_id,
    load_permit,
    main,
    plan,
    run_session,
    session_intent_id,
    session_ledger_path,
    verify_algo_ack,
    verify_entry_ack,
)
from aurora.p0_boundary import SafetyViolation  # noqa: E402


KEY = "ctr-test-key"


def _key_fp(key):
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()[:16]


FP = _key_fp(KEY)


def _source(**extra):
    values = {
        "TRADING_MODE": "TESTNET",
        "TESTNET": "true",
        "BINANCE_API_KEY": KEY,
        "BINANCE_API_SECRET": "s",
        "AURORA_ACCOUNT_FINGERPRINT": FP,
    }
    values.update(extra)
    return ConfigSource(env_file="<test>", values=values)


def _incident_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE kill_switch (id INTEGER PRIMARY KEY, engaged INTEGER, reason TEXT)")
    conn.execute("INSERT INTO kill_switch VALUES (1, 1, 'incident')")
    conn.commit()
    conn.close()


REAL_ALGO_ACK = {
    "algoId": 1000000192798918, "algoStatus": "NEW",
    "algoType": "CONDITIONAL", "clientAlgoId": "AURORA-CTR-test",
    "closePosition": False, "orderType": "STOP_MARKET",
    "positionSide": "LONG", "quantity": "0.001", "reduceOnly": True,
    "side": "SELL", "symbol": "BTCUSDT", "triggerPrice": "99.0",
    "workingType": "MARK_PRICE", "actualOrderId": "",
}


class CtrTestBase(unittest.TestCase):
    """公共夹具：tmp 事故账本 + permit 路径重定向 + 预签发许可。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.incident = os.path.join(self._tmp.name, "kernel_ledger.db")
        _incident_db(self.incident)
        self.before = open(self.incident, "rb").read()
        self.permit_file = os.path.join(self._tmp.name,
                                        "qualification_permit.json")
        import aurora.ops_controlled_requal as ocr
        self.ocr = ocr
        self._patches = [
            mock.patch.object(ocr, "qualification_permit_path",
                              lambda *a, **k: self.permit_file),
            mock.patch.object(ocr, "start_order_path",
                              lambda *a, **k: os.path.join(
                                  self._tmp.name,
                                  "execution_start_order.json")),
            mock.patch.object(ocr, "session_final_path",
                              lambda sid, *a, **k: os.path.join(
                                  self._tmp.name, "sessions",
                                  f"{sid}.final.json")),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        window = issue_execution_window(
            session_id="CTR-TEST-001", issued_by="operator", fingerprint=FP)
        self.order = window["order"]
        self.permit = window["permit"]

    def _orch(self, exchange=None, ledger_name=None):
        if ledger_name is None:
            path = os.path.join(
                self._tmp.name, "qualification", "CTR-TEST-001", "ledger.db")
        else:
            path = os.path.join(self._tmp.name, ledger_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ledger = Ledger(path)
        orch = Orchestrator(ledger, exchange or FakeExchange(price=100.0),
                            instance_id="ctr")
        def _close():
            try:
                ledger.close()
            except Exception:
                pass
        self.addCleanup(_close)
        orch.recover()
        return orch


class PlanGateTests(CtrTestBase):
    def test_plan_defaults_are_frozen_limits(self):
        report = plan(_source(), qty=MAX_QTY, account_fingerprint=FP)
        self.assertEqual(report["execute"], "DENIED")
        self.assertEqual(report["qty"], 0.001)
        self.assertEqual(report["side"], "LONG")
        self.assertEqual(report["productionMain"], "DENIED")
        self.assertIn(os.path.join("qualification", report["sessionId"],
                                   "ledger.db"), report["sessionLedger"])
        self.assertNotEqual(report["sessionLedger"], report["incidentLedger"])
        self.assertEqual(report["entryClientId"],
                         leg_client_id(report["sessionId"], "ENTRY"))
        self.assertEqual(report["incidentKill"]["status"], "ACTIVE")

    def test_identity_gate_is_unconditional(self):
        # F：source 必填，指纹/模式漂移一律拒绝
        with self.assertRaises(SafetyViolation):
            plan(_source(BINANCE_API_KEY="other",
                         AURORA_ACCOUNT_FINGERPRINT=_key_fp("other")),
                 qty=MAX_QTY)
        with self.assertRaises(SafetyViolation):
            plan(_source(TRADING_MODE="LIVE", TESTNET="false",
                         ALLOW_LIVE_TRADING="true",
                         AURORA_LIVE_CONFIRM="I_UNDERSTAND_LIVE_RISK"),
                 qty=MAX_QTY)
        with self.assertRaises(SafetyViolation):
            plan(_source(AURORA_ACCOUNT_FINGERPRINT="deadbeefdeadbeef"),
                 qty=MAX_QTY)

    def test_qty_and_notional_caps(self):
        with self.assertRaises(SafetyViolation):
            assert_scale(0.002, 100.0)
        with self.assertRaises(SafetyViolation):
            assert_scale(MAX_QTY, (MAX_NOTIONAL_USDT / MAX_QTY) + 1)
        with self.assertRaises(SafetyViolation):
            assert_qty_exact(0.0005)
        with self.assertRaises(SafetyViolation):
            assert_scale(0.0005, 100.0)
        assert_scale(MAX_QTY, 100.0)

    def test_incident_intent_and_namespace_forbidden(self):
        with self.assertRaises(SafetyViolation):
            assert_intent_allowed(INCIDENT_INTENT)
        with self.assertRaises(SafetyViolation):
            assert_intent_allowed(f"AURORA-{FORBIDDEN_INTENT_MARK}-X")
        with self.assertRaises(SafetyViolation):
            assert_intent_allowed("OTHER-NAMESPACE-1")
        assert_intent_allowed("AURORA-CTR-abc123")

    def test_session_path_cannot_be_incident(self):
        with self.assertRaises(SafetyViolation):
            assert_session_ledger_isolated(incident_ledger_path())
        path = session_ledger_path(FP, "CTR-TEST-001")
        assert_session_ledger_isolated(path, "CTR-TEST-001")
        with self.assertRaises(SafetyViolation):
            assert_session_ledger_isolated(
                os.path.join(self._tmp.name, "controlled_requal.db"))

    def test_source_has_no_production_or_write_paths(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "aurora", "ops_controlled_requal.py")).read()
        import re
        for banned in ("import aurora.production_main",
                       "from aurora.production_main",
                       "from aurora.trading_cycle",
                       "ensure_ledger_migrated",
                       "futures_change_position_mode"):
            self.assertNotIn(banned, src, banned)
        # 下单调用必须带 symbol 参数；WireTee 的纯委托(**params)不匹配
        self.assertIsNone(re.search(
            r"futures_create_order\(\s*(symbol|newOrderSymbol)", src))

    def test_main_execute_flag_still_denied(self):
        with mock.patch("aurora.safety.build_client") as built:
            self.assertEqual(main(["--i-execute-controlled-requal",
                                   "--qty", "0.001"]), 3)
        built.assert_not_called()

    def test_execute_live_hard_denied(self):
        # R2：常量是 legacy dead-man 指示；裸调用缺 source/stop → 拒绝
        self.assertFalse(EXECUTE_AUTHORIZED)
        with self.assertRaises(SafetyViolation) as hc:
            execute_live()
        self.assertIn("valid execution window", str(hc.exception))

    def test_write_gates_refuse_before_client(self):
        # R2 四条件门：无 START ORDER/permit 的密封环境 → DENY
        # （EXECUTE_AUTHORIZED 常量仅为 legacy dead-man 指示）
        self.assertFalse(EXECUTE_AUTHORIZED)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                    __import__("aurora.ops_controlled_requal", fromlist=["x"]),
                    "start_order_path",
                    lambda *a, **k: os.path.join(
                        tmp, "execution_start_order.json")), \
                mock.patch.object(
                    __import__("aurora.ops_controlled_requal", fromlist=["x"]),
                    "qualification_permit_path",
                    lambda *a, **k: os.path.join(
                        tmp, "qualification_permit.json")), \
                mock.patch.object(
                    __import__("aurora.ops_controlled_requal", fromlist=["x"]),
                    "session_final_path",
                    lambda sid, *a, **k: os.path.join(
                        tmp, "sessions", f"{sid}.final.json")):
                with self.assertRaises(SafetyViolation) as hc:
                    assert_write_gates(fingerprint=FP,
                                       session_id="CTR-TEST-001")
        self.assertIn("EXECUTION START ORDER", str(hc.exception))

    def test_long_stop_must_be_below_mark(self):
        with self.assertRaises(SafetyViolation):
            assert_stop_price(100.0, 100.0)
        assert_stop_price(99.0, 100.0)


class PermitTests(CtrTestBase):
    def test_issue_load_and_expiry(self):
        permit = issue_permit(issued_by="operator", session_id="CTR-TEST-001",
                              ttl_hours=1.0,
                              fingerprint=FP,
                              now=datetime(2026, 9, 8, tzinfo=timezone.utc))
        self.assertEqual(permit["scope"]["symbol"], "BTCUSDT")
        self.assertEqual(permit["scope"]["qty"], 0.001)
        self.assertTrue(permit["single_use"])
        loaded = load_permit(fingerprint=FP,
                             now=datetime(2026, 9, 8, 0, 30,
                                          tzinfo=timezone.utc))
        self.assertEqual(loaded["issued_by"], "operator")
        with self.assertRaises(SafetyViolation):
            load_permit(fingerprint=FP,
                        now=datetime(2026, 9, 9, 2, tzinfo=timezone.utc))

    def test_no_permit_means_denied(self):
        os.remove(self.permit_file)
        with self.assertRaises(SafetyViolation):
            load_permit(fingerprint=FP)

    def test_lifecycle_binding_and_exhaustion(self):
        intent = "AURORA-CTR-abc123"
        bind_permit(self.permit, intent_id=intent, qty=MAX_QTY,
                    mark_price=100.0)
        with self.assertRaises(SafetyViolation):
            bind_permit(self.permit, intent_id="AURORA-CTR-other",
                        qty=MAX_QTY, mark_price=100.0)


class WireAckTests(unittest.TestCase):
    def test_entry_ack_ok_and_overflow(self):
        ok = verify_entry_ack(
            {"side": "BUY", "executedQty": "0.001", "status": "FILLED"},
            side="LONG", qty=0.001)
        self.assertEqual(ok["problems"], [])
        bad = verify_entry_ack(
            {"side": "BUY", "executedQty": "0.5", "status": "FILLED"},
            side="LONG", qty=0.001)
        self.assertTrue(any("executedQty" in p for p in bad["problems"]))

    def test_algo_ack_three_way(self):
        ok = verify_algo_ack(dict(REAL_ALGO_ACK), trigger=99.0,
                             qty=0.001, position_side="LONG")
        self.assertEqual(ok["problems"], [])
        self.assertEqual(ok["orderType"], "STOP_MARKET")

    def test_algo_ack_conflict_fails_closed(self):
        raw = dict(REAL_ALGO_ACK)
        raw["type"] = "TAKE_PROFIT_MARKET"
        result = verify_algo_ack(raw, trigger=99.0, qty=0.001,
                                 position_side="LONG")
        self.assertTrue(any("conflict" in p for p in result["problems"]))

    def test_algo_ack_both_absent_fails_closed(self):
        raw = {k: v for k, v in REAL_ALGO_ACK.items()
               if k not in ("orderType", "type")}
        result = verify_algo_ack(raw, trigger=99.0, qty=0.001,
                                 position_side="LONG")
        self.assertTrue(any("missing orderType" in p
                            for p in result["problems"]))


class BaselineTests(unittest.TestCase):
    def test_baseline_violations_detected(self):
        ok = baseline_from_probe({
            "positionMode": {"status": "PASS", "value": "HEDGE"},
            "positions": {"btcusdtPositionState": "FLAT"},
            "openOrders": {"status": "EMPTY"},
            "openAlgoOrders": {"status": "EMPTY"},
            "identity": {"positionModeMatchesExpected": True},
        })
        self.assertTrue(ok["ok"])
        bad = baseline_from_probe({
            "positionMode": {"status": "PASS", "value": "ONE_WAY"},
            "positions": {"btcusdtPositionState": "OPEN"},
            "openOrders": {"status": "PASS", "count": 2},
            "openAlgoOrders": {"status": "PASS", "count": 1},
            "identity": {"positionModeMatchesExpected": False},
        })
        self.assertFalse(bad["ok"])
        self.assertIn("POSITION_NOT_FLAT", bad["violations"])
        self.assertIn("IDENTITY_DRIFT", bad["violations"])


class OfflineSessionTests(CtrTestBase):
    def test_full_session_success_with_kill_and_incident_intact(self):
        orch = self._orch()
        out = run_session(
            orch, permit=self.permit, qty=MAX_QTY, mark_price=100.0,
            stop_price=99.0, session_id="CTR-TEST-001",
            incident_path=self.incident)
        self.assertTrue(out["success"], out)
        self.assertEqual(out["phase"], "COMPLETE")
        self.assertEqual(out["opened"]["state"], "PROTECTED")
        self.assertAlmostEqual(out["opened"]["protected_qty"], MAX_QTY,
                               places=10)
        self.assertEqual(out["protectionConfirmed"]["status"], "NEW")
        self.assertEqual(out["wireAck"]["submitAckContract"],
                         "NOT_OBSERVED_OFFLINE")
        self.assertEqual(out["restartRecover"], "PASS")
        self.assertEqual(out["restartInstanceId"], "ctr-restart")
        self.assertEqual(out["entryClientId"],
                         leg_client_id("CTR-TEST-001", "ENTRY"))
        self.assertEqual(out["closeClientId"],
                         leg_client_id("CTR-TEST-001", "CLOSE"))
        self.assertEqual(out["closed"]["plan"]["side"], "SELL")
        self.assertEqual(out["closed"]["plan"]["positionSide"], "LONG")
        self.assertNotEqual(out["closed"]["authoritative"], "ack")
        self.assertEqual(out["sessionKill"]["engaged"], 1)
        self.assertEqual(open(self.incident, "rb").read(), self.before)
        pos = orch.exchange.position("BTCUSDT")
        self.assertEqual(pos.signed_qty, 0.0)
        self.assertIn(session_intent_id("CTR-TEST-001"),
                      self.permit["lifecycle"]["used"])
        self.assertFalse(any(
            req.client_order_id.startswith("AURORA-CLOSE-")
            for req in orch.exchange.submit_log))

    def test_oversize_refused_before_open(self):
        orch = self._orch()
        with self.assertRaises(SafetyViolation):
            run_session(orch, permit=self.permit, qty=0.007,
                        mark_price=100.0, stop_price=99.0,
                        session_id="CTR-TEST-001")
        self.assertEqual(len(orch.exchange.submit_log), 0)

    def test_start_not_flat_refuses_and_kills_session(self):
        exchange = FakeExchange(price=100.0)
        orch = self._orch(exchange=exchange)
        exchange.seed_external_position(0.002, 100.0)
        with self.assertRaises(SafetyViolation):
            run_session(orch, permit=self.permit, qty=MAX_QTY,
                        mark_price=100.0, stop_price=99.0,
                        session_id="CTR-TEST-001")
        self.assertEqual(orch.ledger.kill_state()["engaged"], 1)

    def test_unknown_position_refuses_start(self):
        exchange = FakeExchange()
        exchange.set_position_query_ambiguous(True)
        with self.assertRaises(SafetyViolation):
            assert_session_start(exchange)

    def test_protection_reject_stops_and_kills_session(self):
        exchange = FakeExchange(price=100.0, protection_behavior="reject")
        orch = self._orch(exchange=exchange, ledger_name="slfail.db")
        out = run_session(orch, permit=self.permit, qty=MAX_QTY,
                          mark_price=100.0, stop_price=99.0,
                          session_id="CTR-TEST-001")
        self.assertFalse(out["success"])
        self.assertEqual(out["phase"], "P2")  # SL 拒绝发生在开仓链路内
        self.assertEqual(orch.ledger.kill_state()["engaged"], 1)

    def test_wire_ack_conflict_stops_at_p1(self):
        orch = self._orch()
        tee = WireTee(None)
        bad_ack = dict(REAL_ALGO_ACK)
        bad_ack["type"] = "TAKE_PROFIT_MARKET"
        tee.algo_acks.append({"params": {}, "raw": bad_ack})
        out = run_session(orch, permit=self.permit, qty=MAX_QTY,
                          mark_price=100.0, stop_price=99.0,
                          session_id="CTR-TEST-001", wire_log=tee)
        self.assertFalse(out["success"])
        self.assertEqual(out["phase"], "P1")
        self.assertEqual(orch.ledger.kill_state()["engaged"], 1)

    def test_baseline_violation_stops_before_entry(self):
        orch = self._orch()
        out = run_session(
            orch, permit=self.permit, qty=MAX_QTY, mark_price=100.0,
            stop_price=99.0, session_id="CTR-TEST-001",
            baseline={"ok": False,
                      "violations": ["ORDINARY_OPEN_ORDERS_PRESENT"]})
        self.assertFalse(out["success"])
        self.assertEqual(out["phase"], "P0")
        self.assertEqual(len(orch.exchange.submit_log), 0)

    def test_protection_confirm_trigger_echo_mismatch_stops(self):
        orch = self._orch()
        opened = orch.open_position(
            "LONG", MAX_QTY, intent_id=session_intent_id("CTR-TEST-001"),
            stop_price=99.0)
        self.assertTrue(opened.get("success"), opened)
        with self.assertRaises(SafetyViolation):
            confirm_protection_active(
                orch, intent_id=session_intent_id("CTR-TEST-001"),
                planned_trigger=98.0, planned_qty=MAX_QTY)

    def test_expired_permit_denies_session(self):
        expired = issue_permit(issued_by="op", session_id="CTR-TEST-001",
                               fingerprint=FP,
                               now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        orch = self._orch()
        with self.assertRaises(SafetyViolation):
            run_session(orch, permit=expired, qty=MAX_QTY,
                        mark_price=100.0, stop_price=99.0,
                        session_id="CTR-TEST-001")

    def test_conditions_require_start_order(self):
        os.remove(self.ocr.start_order_path(FP))
        with self.assertRaises(SafetyViolation):
            check_execution_conditions(fingerprint=FP,
                                       session_id="CTR-TEST-001")

    def test_conditions_refuse_permit_session_mismatch(self):
        with open(self.permit_file) as fh:
            permit = json.load(fh)
        permit["session_id"] = "CTR-TAMPERED"
        with open(self.permit_file, "w") as fh:
            json.dump(permit, fh)
        with self.assertRaises(SafetyViolation) as hc:
            check_execution_conditions(fingerprint=FP,
                                       session_id="CTR-TEST-001")
        self.assertIn("PERMIT_SESSION_MISMATCH", str(hc.exception))

    def test_session_final_blocks_second_run(self):
        write_session_final("CTR-TEST-001",
                            {"outcome": "COMPLETE"}, fingerprint=FP)
        with self.assertRaises(SafetyViolation):
            check_execution_conditions(fingerprint=FP,
                                       session_id="CTR-TEST-001")

    def test_issue_execution_window_cli(self):
        env_file = os.path.join(self._tmp.name, "ctr.env")
        with open(env_file, "w") as fh:
            fh.write(f"TRADING_MODE=TESTNET\nTESTNET=true\n"
                     f"BINANCE_API_KEY={KEY}\nBINANCE_API_SECRET=s\n"
                     f"AURORA_ACCOUNT_FINGERPRINT={FP}\n")
        code = main(["--env-file", env_file,
                     "--issue-execution-window",
                     "--session-id", "CTR-CLI-001",
                     "--issued-by", "operator", "--valid-hours", "1"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.ocr.start_order_path(FP)))


class MainAndSourceTests(CtrTestBase):
    def test_main_plan_only_zero(self):
        self.assertEqual(main([]), 0)

    def test_main_execute_flag_still_denied(self):
        self.assertEqual(main(["--i-execute-controlled-requal"]), 3)

    def test_missing_env_blocks(self):
        code = main(["--env-file",
                     os.path.join(self._tmp.name, "missing.env")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()


class FinalityContractTests(unittest.TestCase):
    """R1 finality 合同：撤腿状态的有界轮询。"""

    def _wait(self, statuses, max_attempts=3, interval=0.01):
        from aurora.ops_controlled_requal import wait_leg_finality
        seq = list(statuses)
        calls = {"n": 0}

        def query(cid):
            calls["n"] += 1
            return SimpleNamespace(status=seq[min(calls["n"] - 1, len(seq) - 1)])
        return wait_leg_finality(query, "X-SL", max_attempts=max_attempts,
                                 interval=interval), calls

    def test_terminal_immediately(self):
        result, _ = self._wait(["CANCELLED"])
        self.assertEqual(result["status"], "CANCELLED")

    def test_lagging_status_bounded_then_terminal(self):
        result, calls = self._wait(["NEW", "NEW", "CANCELLED"],
                                   max_attempts=5)
        self.assertEqual(result["status"], "CANCELLED")
        self.assertLessEqual(calls["n"], 5)

    def test_exhausted_window_returns_unknown(self):
        result, _ = self._wait(["NEW", "NEW", "NEW"], max_attempts=3)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["lastObserved"], "NEW")

    def test_unknown_is_fail_safe_not_success(self):
        result, _ = self._wait(["NEW"], max_attempts=1)
        self.assertNotIn(result["status"], ("CANCELLED", "FILLED"))


if __name__ == "__main__":
    unittest.main()
