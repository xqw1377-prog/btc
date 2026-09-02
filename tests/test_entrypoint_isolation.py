"""P0-A 入口隔离测试：四个真实入口在 PAPER 下无法构造客户端；Docker 只指向安全入口。

以子进程方式执行真实入口脚本，覆盖 dotenv 加载、模块导入到 __init__ 的完整路径。
"""
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENTRYPOINTS = [
    "aurora_final.py",
    "aurora_hf_kernel.py",
    "ws_server.py",
    "check_status.py",
]

CHILD_ENV_KEYS = (
    "TRADING_MODE",
    "TESTNET",
    "ALLOW_LIVE_TRADING",
    "AURORA_LIVE_CONFIRM",
    "AURORA_LIVE_KEY_SHA256",
    "AURORA_ACCOUNT_FINGERPRINT",
)


def _run_entrypoint(script, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_KEYS}
    env["PYTHONWARNINGS"] = "ignore"
    env["TRADING_MODE"] = "PAPER"
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, script)],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
        cwd=ROOT,
    )


class EntrypointIsolationTests(unittest.TestCase):
    def test_all_entrypoints_refuse_under_paper(self):
        for script in ENTRYPOINTS:
            with self.subTest(script=script):
                proc = _run_entrypoint(script)
                self.assertEqual(proc.returncode, 1, f"{script} stderr={proc.stderr}")
                self.assertIn("[P0]", proc.stderr + proc.stdout)

    def test_default_mode_also_refuses(self):
        env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_KEYS}
        env.pop("TRADING_MODE", None)
        env["PYTHONWARNINGS"] = "ignore"
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "aurora_final.py")],
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[P0]", proc.stderr + proc.stdout)

    def test_read_only_entry_reports_paper_specific_reason(self):
        proc = _run_entrypoint("ws_server.py")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PAPER forbids exchange connections", proc.stderr + proc.stdout)


class DockerSafetyTests(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(ROOT, name)) as fh:
            return fh.read()

    def test_dockerfile_only_runs_safety_entry(self):
        dockerfile = self._read("Dockerfile")
        cmd = re.findall(r'^CMD\s+(\[.*\])\s*$', dockerfile, re.M)
        self.assertEqual(len(cmd), 1)
        self.assertEqual(cmd[0], '["python", "-m", "aurora.production_main"]')
        for banned in ("aurora_final", "aurora_hf_kernel", "ws_server"):
            self.assertNotIn(banned, dockerfile)

    def test_compose_no_auto_restart_no_bogus_mount(self):
        compose = self._read("docker-compose.yml")
        self.assertIn('restart: "no"', compose)
        self.assertNotIn("regime_stats.json", compose)

    def test_production_main_cannot_place_orders(self):
        source = self._read(os.path.join("aurora", "production_main.py"))
        self.assertIn("will not place orders", source)
        self.assertIn("aurora_hf_kernel", source)
        self.assertIn("aurora_final", source)

    def test_entrypoints_have_no_direct_binance_import(self):
        for script in ENTRYPOINTS:
            with self.subTest(script=script):
                source = self._read(script)
                self.assertNotIn("from binance.client import", source)
                self.assertNotIn("binance.client", source)


if __name__ == "__main__":
    unittest.main()
