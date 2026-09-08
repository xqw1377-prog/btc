"""G0-5 Runtime Identity & Config Isolation 验收（离线，零出网）。

A: ONE_CONFIG_SOURCE / NO_PARENT_DOTENV_SEARCH / NO_IMPORT_SIDE_EFFECT_CONFIG
B: PAPER / TESTNET / LIVE state 物理隔离；事故账本 kill 只读接管保留
C: ACCOUNT_IDENTITY_REQUIRED / ACCOUNT_IDENTITY_DRIFT_FAIL_CLOSED / EXCLUSIVITY=FALSE
D: SAFEEXECUTOR_PRODUCTION_UNREACHABLE
"""
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora import config_source as config_source_module  # noqa: E402
from aurora.config_source import ConfigSource, repo_default_env_file  # noqa: E402
from aurora.legacy_safe_executor import SafeExecutor as LegacySafeExecutor  # noqa: E402
from aurora.p0_boundary import (  # noqa: E402
    Persistence,
    PositionMode,
    PositionQueryKind,
    PositionSnapshot,
    RunMode,
    SafetyStore,
    SafetyViolation,
    boot,
    build_account_identity,
    namespaced_lock_dir,
    namespaced_state_dir,
    namespaced_state_path,
)
from aurora.armed_runtime import namespaced_ledger_path  # noqa: E402


class _FakeBroker:
    def __init__(self, url="https://testnet.binancefuture.com", mode="HEDGE"):
        self.futures_url = url
        self._mode = mode
        self.position = PositionSnapshot(kind=PositionQueryKind.FLAT)

    def account(self):
        return {"assets": []}

    def get_position_mode(self):
        return PositionMode(self._mode)

    def get_position(self, symbol):
        return self.position


def _legacy_close(ctx):
    ctx.persist.save(ctx.store)
    ctx.lock.release()


def _fp(key):
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _boot_testnet(tmp, key="k", **env_over):
    persist = os.path.join(tmp, "p0.json")
    locks = os.path.join(tmp, "locks")
    env = {
        "TRADING_MODE": "TESTNET",
        "TESTNET": "true",
        "BINANCE_API_KEY": key,
        "BINANCE_API_SECRET": "s",
        "AURORA_ACCOUNT_FINGERPRINT": _fp(key),
    }
    env.update(env_over)
    ctx = boot(persist, locks, broker=_FakeBroker(), environ=env)
    return ctx, persist, env


class ConfigSourceContractTests(unittest.TestCase):
    ENTRIES = (
        "aurora/production_main.py",
        "aurora/safety_check.py",
        "aurora/dashboard_feed.py",
        "aurora/ops_position_mode.py",
    )

    def test_ONE_CONFIG_SOURCE(self):
        for rel in self.ENTRIES:
            src = Path(rel).read_text()
            self.assertNotIn("load_dotenv", src, rel)
            self.assertIn("ConfigSource", src, rel)

    def test_NO_PARENT_DOTENV_SEARCH(self):
        src = Path("aurora/config_source.py").read_text()
        self.assertNotIn("find_dotenv", src)
        self.assertNotIn("load_dotenv(", src)
        # 行为：CWD 在深层嵌套目录时，默认配置仍是仓库根 .env，绝不就近搜索
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "a", "b")
            os.makedirs(nested)
            # 金丝雀键：只写进"可能被父级搜索到"的文件，绝不属于仓库根配置
            with open(os.path.join(nested, ".env"), "w") as fh:
                fh.write("G05_PARENT_SEARCH_CANARY=1\n")
            os.chdir(nested)
            try:
                source = ConfigSource.load()  # 无参数：必须落在仓库根
                self.assertEqual(source.env_file, os.path.abspath(repo_default_env_file()))
                self.assertNotIn("G05_PARENT_SEARCH_CANARY", source.values)
            finally:
                os.chdir(old)

    def test_NO_IMPORT_SIDE_EFFECT_CONFIG(self):
        code = (
            "import os, json\n"
            "before = json.dumps(dict(os.environ), sort_keys=True)\n"
            "import aurora.config_source\n"
            "import aurora.production_main\n"
            "import aurora.safety_check\n"
            "import aurora.safety\n"
            "after = json.dumps(dict(os.environ), sort_keys=True)\n"
            "assert before == after, 'env mutated at import'\n"
            "print('ok')\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ok", out.stdout)


class StateIsolationTests(unittest.TestCase):
    def test_namespaced_paths_differ_by_mode(self):
        paper = namespaced_state_path(RunMode.PAPER, "fp1")
        testnet = namespaced_state_path(RunMode.TESTNET, "fp1")
        live = namespaced_state_path(RunMode.LIVE, "fp1")
        self.assertNotEqual(paper, testnet)
        self.assertNotEqual(testnet, live)
        self.assertIn(os.path.join("state", "paper", "fp1"), paper)
        self.assertIn(os.path.join("state", "testnet", "fp1"), testnet)
        self.assertIn(os.path.join("state", "live", "fp1"), live)
        self.assertNotEqual(
            namespaced_ledger_path(RunMode.LIVE, "fp1"),
            namespaced_ledger_path(RunMode.TESTNET, "fp1"))
        self.assertNotEqual(
            namespaced_lock_dir(RunMode.TESTNET, "fp1"),
            namespaced_lock_dir(RunMode.PAPER, "fp1"))

    def test_PAPER_STATE_ISOLATED(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        legacy = os.path.join(root, "state", "p0_safety.json")
        repo_paper = os.path.join(root, "state", "paper", "paper-local", "p0_safety.json")
        before = open(legacy, "rb").read() if os.path.exists(legacy) else None
        repo_paper_mtime = os.path.getmtime(repo_paper) if os.path.exists(repo_paper) else None
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = os.path.join(tmp, "state")
            os.makedirs(fake_root)
            with mock.patch("aurora.p0_boundary.state_root", return_value=fake_root):
                with mock.patch.dict(os.environ, {"TRADING_MODE": "PAPER"}, clear=True):
                    from aurora import production_main
                    ctx = production_main.run_boot()
                    try:
                        paper_path = namespaced_state_path(RunMode.PAPER, "paper-local")
                        self.assertTrue(os.path.exists(paper_path))
                        self.assertTrue(paper_path.startswith(fake_root))
                        self.assertFalse(os.path.exists(os.path.join(fake_root, "p0_safety.json")))
                        self.assertFalse(os.path.exists(os.path.join(fake_root, "testnet")))
                        self.assertFalse(os.path.exists(os.path.join(fake_root, "live")))
                    finally:
                        ctx.lock.release()
        after = open(legacy, "rb").read() if os.path.exists(legacy) else None
        self.assertEqual(before, after)  # PAPER 绝不修改遗留/TESTNET 状态
        repo_paper_after = os.path.getmtime(repo_paper) if os.path.exists(repo_paper) else None
        self.assertEqual(repo_paper_mtime, repo_paper_after)

    def test_LIVE_STATE_ISOLATED(self):
        live = namespaced_state_dir(RunMode.LIVE, "fp-live")
        testnet = namespaced_state_dir(RunMode.TESTNET, "fp-live")
        paper = namespaced_state_dir(RunMode.PAPER, "fp-live")
        self.assertNotEqual(live, testnet)
        self.assertNotEqual(live, paper)
        self.assertIn(os.path.join("state", "live", "fp-live"), live)
        self.assertNotEqual(
            namespaced_ledger_path(RunMode.LIVE, "fp-live"),
            namespaced_ledger_path(RunMode.TESTNET, "fp-live"))
        with tempfile.TemporaryDirectory() as tmp:
            ctx, persist, _env = _boot_testnet(tmp)
            _legacy_close(ctx)
            self.assertTrue(os.path.exists(persist))
            self.assertNotIn(os.path.sep + "live" + os.path.sep, persist)
            self.assertFalse(os.path.exists(os.path.join(tmp, "live")))

    def test_TESTNET_STATE_ISOLATED_cross_fingerprint_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, persist, env = _boot_testnet(tmp, key="keyA")
            _legacy_close(ctx)
            other = dict(env)
            other["BINANCE_API_KEY"] = "keyB"
            other["AURORA_ACCOUNT_FINGERPRINT"] = _fp("keyB")
            with self.assertRaises(SafetyViolation):
                boot(persist, os.path.join(tmp, "locks"),
                     broker=_FakeBroker(), environ=other)

    def test_ledger_migration_preserves_kill_and_leaves_legacy_untouched(self):
        from aurora.armed_runtime import ensure_ledger_migrated
        from aurora.kernel.ledger import Ledger
        with tempfile.TemporaryDirectory() as tmp:
            legacy = os.path.join(tmp, "kernel_ledger.db")
            led = Ledger(legacy)
            led.engage_kill("incident lock")
            led.close()
            before = open(legacy, "rb").read()
            target = os.path.join(tmp, "testnet", "fp", "kernel_ledger.db")
            note = ensure_ledger_migrated(legacy, target)
            self.assertIsNotNone(note)
            after = open(legacy, "rb").read()
            self.assertEqual(before, after)  # 原文件字节不变
            migrated = Ledger(target)
            self.assertEqual(migrated.kill_state()["engaged"], 1)  # kill 保留
            migrated.close()
            self.assertIsNone(ensure_ledger_migrated(legacy, target))  # 幂等


class AccountIdentityTests(unittest.TestCase):
    def test_ACCOUNT_IDENTITY_REQUIRED(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, persist, env = _boot_testnet(tmp)
            _legacy_close(ctx)
            store = Persistence(persist).load()
            identity = store.account_identity
            self.assertTrue(identity)
            for field in ("mode", "account_fingerprint", "position_mode",
                          "exchange_host", "account_exclusivity", "identity_hash"):
                self.assertIn(field, identity)
            self.assertEqual(identity["mode"], "TESTNET")
            self.assertEqual(identity["exchange_host"], "testnet.binancefuture.com")
            # 身份缺失不可：指纹键缺失 → 拒启
            with tempfile.TemporaryDirectory() as tmp2:
                with self.assertRaises(SafetyViolation):
                    boot(
                        os.path.join(tmp2, "p0.json"),
                        os.path.join(tmp2, "locks"),
                        broker=_FakeBroker(),
                        environ={
                            "TRADING_MODE": "TESTNET",
                            "TESTNET": "true",
                            "BINANCE_API_KEY": "k2",
                            "BINANCE_API_SECRET": "s",
                            # AURORA_ACCOUNT_FINGERPRINT 缺失
                        },
                    )

    def test_ACCOUNT_IDENTITY_DRIFT_FAIL_CLOSED(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, persist, env = _boot_testnet(tmp)
            _legacy_close(ctx)
            # 持仓模式漂移
            with self.assertRaises(SafetyViolation) as hc:
                _boot_testnet(tmp, AURORA_EXPECTED_POSITION_MODE="ONE_WAY")
            self.assertIn("ACCOUNT_IDENTITY_DRIFT", str(hc.exception))
            # 交易所主机漂移（同模式、同指纹、不同合法主机）
            with self.assertRaises(SafetyViolation) as hh:
                ctx2 = boot(
                    persist, os.path.join(tmp, "locks"),
                    broker=_FakeBroker(url="https://testnet.binance.vision"),
                    environ=env)
                _legacy_close(ctx2)
            self.assertIn("ACCOUNT_IDENTITY_DRIFT", str(hh.exception))
            # 独占性漂移
            with self.assertRaises(SafetyViolation) as he:
                _boot_testnet(tmp, AURORA_ACCOUNT_EXCLUSIVITY="true")
            self.assertIn("ACCOUNT_IDENTITY_DRIFT", str(he.exception))

    def test_exclusivity_defaults_false(self):
        identity = build_account_identity(
            mode=RunMode.TESTNET, fingerprint="fp",
            position_mode=PositionMode.HEDGE,
            exchange_host="testnet.binancefuture.com",
            account_exclusivity=False)
        self.assertIs(identity["account_exclusivity"], False)
        # ConfigSource 默认口径：未显式声明独占 = false（共享账户是登记事实）
        source = ConfigSource.load(environ={})
        self.assertEqual(source.get("AURORA_ACCOUNT_EXCLUSIVITY") or "false", "false")


class SafeExecutorRetirementTests(unittest.TestCase):
    PRODUCTION_FILES = (
        "aurora/production_main.py",
        "aurora/safety.py",
        "aurora/armed_runtime.py",
        "aurora/kernel/orchestrator.py",
        "aurora/kernel/ledger.py",
        "aurora/kernel/binance_exchange.py",
    )

    def test_SAFEEXECUTOR_PRODUCTION_UNREACHABLE(self):
        for rel in self.PRODUCTION_FILES:
            src = Path(rel).read_text()
            self.assertNotIn("SafeExecutor", src, rel)
            self.assertNotIn("legacy_safe_executor", src, rel)
        boundary = Path("aurora/p0_boundary.py").read_text()
        self.assertNotIn("class SafeExecutor", boundary)
        self.assertNotIn("class OrderRecord", boundary)
        self.assertNotIn("Optional[SafeExecutor]", boundary)
        # 导入层面：生产模块命名空间中没有执行器残留
        import aurora.production_main as pm
        import aurora.kernel.orchestrator as orch
        self.assertFalse(hasattr(pm, "SafeExecutor"))
        self.assertFalse(hasattr(orch, "SafeExecutor"))

    def test_boot_context_executor_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = os.path.join(tmp, "state")
            os.makedirs(fake_root)
            with mock.patch("aurora.p0_boundary.state_root", return_value=fake_root):
                with mock.patch.dict(os.environ, {"TRADING_MODE": "PAPER"}, clear=True):
                    from aurora import production_main
                    ctx = production_main.run_boot()
                    try:
                        self.assertIsNone(ctx.executor)
                    finally:
                        ctx.lock.release()

    def test_legacy_reference_still_importable(self):
        self.assertTrue(callable(LegacySafeExecutor.execute_open))

    def test_attach_refuses_unbound_ledger(self):
        from aurora.armed_runtime import ArmedRuntime

        with self.assertRaises(SafetyViolation) as ctx:
            ArmedRuntime.attach(RunMode.TESTNET, object(), ledger_path=None)
        self.assertIn("explicit namespaced ledger_path", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
