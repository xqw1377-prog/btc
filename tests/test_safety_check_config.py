"""C4：safety_check 配置加载与离线自检边界。

合同：显式 --env-file 单一来源、进程环境优先、import 无副作用、
自检永不构造 Client / 不发网络请求 / 不接入运行时、输出不泄漏密钥原值。
子进程测试用最小隔离 env；进程内测试保存并整体恢复 os.environ。
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAFETY_KEYS = (
    "TRADING_MODE",
    "TESTNET",
    "ALLOW_LIVE_TRADING",
    "AURORA_LIVE_CONFIRM",
    "AURORA_LIVE_ARM_TOKEN",
    "AURORA_LIVE_KEY_SHA256",
    "AURORA_ACCOUNT_FINGERPRINT",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
)

FAKE_MARKER = "FAKEKEY-MARKER-7f3a2b"


def _clean_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in SAFETY_KEYS}
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    if extra:
        env.update(extra)
    return env


def _run(args, cwd, env=None, code=None):
    cmd = [sys.executable]
    if code is not None:
        cmd += ["-c", code]
    else:
        cmd += ["-m", "aurora.safety_check"] + list(args)
    return subprocess.run(
        cmd, cwd=cwd, env=env or _clean_env(),
        capture_output=True, text=True, timeout=60,
    )


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class ImportSideEffectTests(unittest.TestCase):
    def test_import_only_reads_nothing_and_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".env"), "TRADING_MODE=LIVE\n")
            proc = _run(
                [], cwd=tmp,
                code=(
                    "import os, aurora.safety_check; "
                    "print('POLLUTED' if os.environ.get('TRADING_MODE') else 'CLEAN')"
                ),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            self.assertIn("CLEAN", proc.stdout)


class ExplicitSourceTests(unittest.TestCase):
    def test_env_file_arg_ignores_cwd_dotenv(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as cfg:
            _write(os.path.join(cwd, ".env"), "TRADING_MODE=LIVE\n")  # 诱饵
            envf = _write(os.path.join(cfg, "check.env"), "TRADING_MODE=TESTNET\n")
            proc = _run(["--env-file", envf], cwd=cwd)
            self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
            self.assertIn("requested mode=TESTNET", proc.stdout)
            self.assertIn(envf, proc.stdout)

    def test_missing_file_reported_no_fallback_search(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write(os.path.join(cwd, ".env"), "TRADING_MODE=LIVE\n")  # 诱饵不得被读
            missing = os.path.join(cwd, "nope.env")
            proc = _run(["--env-file", missing], cwd=cwd)
            self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
            self.assertIn("NOT FOUND", proc.stdout)
            self.assertIn("requested mode=PAPER", proc.stdout)  # 仅进程环境


class PrecedenceAndConflictTests(unittest.TestCase):
    def test_process_env_wins_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            envf = _write(os.path.join(tmp, "c.env"), "TRADING_MODE=TESTNET\n")
            proc = _run(["--env-file", envf], cwd=tmp,
                        env=_clean_env({"TRADING_MODE": "PAPER"}))
            self.assertIn("requested mode=PAPER", proc.stdout)

    def test_conflicting_mode_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            envf = _write(
                os.path.join(tmp, "c.env"),
                "TRADING_MODE=TESTNET\nTESTNET=false\n",
            )
            proc = _run(["--env-file", envf], cwd=tmp)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("REJECTED", proc.stdout)
            self.assertIn("conflict", proc.stdout)


class NoExecutionCapabilityTests(unittest.TestCase):
    LIVE_ENV = (
        "TRADING_MODE=LIVE\n"
        "ALLOW_LIVE_TRADING=true\n"
        "AURORA_LIVE_CONFIRM=I_UNDERSTAND_LIVE_RISK\n"
        "AURORA_ARM_LIVE=I_ARM_LIVE_EXECUTION\n"
        "AURORA_LIVE_KEY_SHA256=x\n"
        f"BINANCE_API_KEY={FAKE_MARKER}\n"
        "BINANCE_API_SECRET=fake-secret\n"
        "AURORA_ACCOUNT_FINGERPRINT=x\n"
    )

    def test_full_live_fields_still_zero_client_zero_network(self):
        snapshot = dict(os.environ)
        try:
            for k in SAFETY_KEYS:
                os.environ.pop(k, None)
            with tempfile.TemporaryDirectory() as tmp:
                envf = _write(os.path.join(tmp, "live.env"), self.LIVE_ENV)
                import aurora.safety_check as sc
                from requests.adapters import HTTPAdapter

                out = io.StringIO()
                with contextlib.redirect_stdout(out), mock.patch(
                    "binance.client.Client"
                ) as ctor, mock.patch.object(
                    HTTPAdapter, "send", side_effect=AssertionError("network!")
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        sc.main(["--env-file", envf])
                    self.assertEqual(ctx.exception.code, 0)
                    self.assertEqual(ctor.call_count, 0)
                text = out.getvalue()
                self.assertIn("requested mode=LIVE", text)
                self.assertIn("self-check only", text)
                self.assertNotIn(FAKE_MARKER, text)
                self.assertNotIn("fake-secret", text)
        finally:
            os.environ.clear()
            os.environ.update(snapshot)

    def test_secret_values_never_appear_in_cli_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            envf = _write(os.path.join(tmp, "c.env"), self.LIVE_ENV)
            proc = _run(["--env-file", envf], cwd=tmp)
            self.assertNotIn(FAKE_MARKER, proc.stdout + proc.stderr)
            self.assertNotIn("fake-secret", proc.stdout + proc.stderr)

    def test_sequential_runs_do_not_share_loaded_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = _write(os.path.join(tmp, "a.env"), "TRADING_MODE=TESTNET\n")
            f2 = _write(os.path.join(tmp, "b.env"), "TRADING_MODE=PAPER\n")
            r1 = _run(["--env-file", f1], cwd=tmp)
            r2 = _run(["--env-file", f2], cwd=tmp)
            self.assertIn("requested mode=TESTNET", r1.stdout)
            self.assertIn("requested mode=PAPER", r2.stdout)


if __name__ == "__main__":
    unittest.main()
