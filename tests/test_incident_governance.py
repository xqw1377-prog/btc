"""P0 governance：事故状态必须在任何生产写客户端构造前权威确定。"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora import incident_governance, production_main  # noqa: E402
from aurora.config_source import ConfigSource  # noqa: E402
from aurora.p0_boundary import RunMode, SafetyViolation  # noqa: E402


def _incident_db(path: str, engaged: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE kill_switch "
        "(id INTEGER PRIMARY KEY, engaged INTEGER, reason TEXT)"
    )
    conn.execute(
        "INSERT INTO kill_switch VALUES (1, ?, 'governance test')",
        (engaged,),
    )
    conn.commit()
    conn.close()


def _source(mode: str = "TESTNET", enable: bool = False) -> ConfigSource:
    return ConfigSource(
        env_file="<test>",
        values={
            "TRADING_MODE": mode,
            "TESTNET": "true" if mode != "LIVE" else "false",
            "AURORA_ENABLE_TRADING": "true" if enable else "false",
            "BINANCE_API_KEY": "k",
            "BINANCE_API_SECRET": "s",
            "AURORA_ACCOUNT_FINGERPRINT": "x",
        },
    )


class IncidentStateTests(unittest.TestCase):
    def test_absent_or_invalid_state_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "absent.db")
            self.assertEqual(
                incident_governance.read_incident_state(absent)["status"],
                "UNKNOWN",
            )
            invalid = os.path.join(tmp, "invalid.db")
            sqlite3.connect(invalid).close()
            self.assertEqual(
                incident_governance.read_incident_state(invalid)["status"],
                "UNKNOWN",
            )

    def test_only_exact_kill_values_are_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = os.path.join(tmp, "active.db")
            clear = os.path.join(tmp, "clear.db")
            invalid = os.path.join(tmp, "invalid.db")
            _incident_db(active, 1)
            _incident_db(clear, 0)
            _incident_db(invalid, 2)
            self.assertEqual(
                incident_governance.read_incident_state(active)["status"],
                "ACTIVE",
            )
            self.assertEqual(
                incident_governance.read_incident_state(clear)["status"],
                "CLEAR",
            )
            self.assertEqual(
                incident_governance.read_incident_state(invalid)["status"],
                "UNKNOWN",
            )


class ProductionGovernanceTests(unittest.TestCase):
    def _run_boot_before_client(self, source, incident_path):
        with mock.patch.object(
            production_main.ConfigSource, "load", return_value=source
        ), mock.patch.object(
            incident_governance,
            "incident_ledger_path",
            return_value=incident_path,
        ), mock.patch.object(
            production_main,
            "_build_network_broker",
            side_effect=AssertionError("client construction must not occur"),
        ) as built:
            with self.assertRaises(SafetyViolation) as ctx:
                production_main.run_boot()
        built.assert_not_called()
        return str(ctx.exception)

    def test_active_incident_denies_before_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kernel_ledger.db")
            _incident_db(path, 1)
            reason = self._run_boot_before_client(_source(), path)
        self.assertIn("INCIDENT_LOCK ACTIVE", reason)

    def test_missing_incident_denies_before_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            reason = self._run_boot_before_client(
                _source(), os.path.join(tmp, "missing.db")
            )
        self.assertIn("INCIDENT_STATE_UNKNOWN", reason)

    def test_auto_testnet_denied_even_after_incident_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kernel_ledger.db")
            _incident_db(path, 0)
            reason = self._run_boot_before_client(
                _source(enable=True), path
            )
        self.assertIn("AUTO TESTNET DENIED", reason)

    def test_shadow_remains_read_only_governance_path(self):
        source = _source(mode="SHADOW")
        with mock.patch.object(
            incident_governance,
            "assert_incident_clear",
            side_effect=AssertionError("SHADOW must not consume execution gate"),
        ):
            production_main.assert_production_execution_governance(source)
        self.assertEqual(source.mode(), RunMode.SHADOW)


if __name__ == "__main__":
    unittest.main()
