"""P0-A 绕过路径静态扫描：确认不存在绕过安全层的账户访问路径。

扫描范围：仓库内全部 .py（排除 tests 自身、__pycache__、state/）。
规则：
- 任何文件不得出现 AsyncClient / UMFutures / CMFutures / ccxt / dapi / stream.binance / requests / httpx；
- fapi.binance.com 仅允许出现在 aurora/p0_boundary.py（endpoint 断言常量）；
- binance Client 构造仅允许出现在 aurora/safety.py 与 aurora/production_main.py；
- binance.client 导入仅允许出现在安全层与两个执行引擎（仅类型标注，无构造）。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXCLUDED_DIRS = {"tests", "__pycache__", "state", ".git", "node_modules", "dist", "btc"}
ALLOWED_FAPI = {"aurora/p0_boundary.py"}
ALLOWED_CLIENT_CONSTRUCTION = {"aurora/safety.py", "aurora/production_main.py"}
ALLOWED_BINANCE_IMPORT = {
    "aurora/safety.py",
    "aurora/production_main.py",
    "aurora/execution_engine.py",
    "aurora/execution_engine_v2.py",
}

FORBIDDEN_ANYWHERE = (
    "AsyncClient",
    "UMFutures",
    "CMFutures",
    "ccxt",
    "dapi.binance.com",
    "stream.binance",
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
)


def _iter_py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, ROOT).replace(os.sep, "/")


class NoBypassScanTests(unittest.TestCase):
    def test_no_forbidden_libraries_or_hosts(self):
        violations = []
        for rel in _iter_py_files():
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                content = fh.read()
            for pattern in FORBIDDEN_ANYWHERE:
                if pattern in content:
                    violations.append(f"{rel}: {pattern}")
        self.assertEqual(violations, [])

    def test_mainnet_host_only_in_boundary(self):
        for rel in _iter_py_files():
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                if "fapi.binance.com" in fh.read() and rel not in ALLOWED_FAPI:
                    self.fail(f"fapi.binance.com 出现在非白名单文件: {rel}")

    def test_client_construction_only_in_safety_layer(self):
        pattern = re.compile(r"\bClient\s*\(")
        for rel in _iter_py_files():
            if rel in ALLOWED_CLIENT_CONSTRUCTION:
                continue
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                if pattern.search(fh.read()):
                    self.fail(f"binance Client 构造出现在非安全层文件: {rel}")

    def test_binance_import_surface_limited(self):
        for rel in _iter_py_files():
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                if "binance.client" in fh.read() and rel not in ALLOWED_BINANCE_IMPORT:
                    self.fail(f"binance.client 导入超出白名单: {rel}")


if __name__ == "__main__":
    unittest.main()
