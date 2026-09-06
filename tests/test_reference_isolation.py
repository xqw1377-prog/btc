"""C3 / ADR-013：reference 离线身份与生产导入隔离。

证明两件事：
1. 生产代码路径（aurora/ 下除 execution_truth.py 以外的源文件、
   aurora/kernel/ 全部）不导入 aurora.execution_truth。
2. 在干净子进程里 import aurora.production_main 不会加载 reference 模块。
3. reference 模块自身不含真实券商/网络/密钥 token（离线性静态检查）。

本文件不导入 aurora.execution_truth。
"""
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REFERENCE_MODULE = "aurora.execution_truth"
REFERENCE_FILE = os.path.join(ROOT, "aurora", "execution_truth.py")

_IMPORT_RE = re.compile(
    r"(?:from\s+aurora\.execution_truth\s+import|import\s+aurora\.execution_truth)"
)


def _production_py_files():
    for base, _dirs, files in os.walk(os.path.join(ROOT, "aurora")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            if os.path.abspath(path) == os.path.abspath(REFERENCE_FILE):
                continue
            yield path


class ProductionImportIsolationTests(unittest.TestCase):
    def test_no_production_source_imports_reference(self):
        offenders = []
        for path in _production_py_files():
            with open(path, encoding="utf-8") as fh:
                if _IMPORT_RE.search(fh.read()):
                    offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual(offenders, [])

    def test_fresh_import_of_production_entry_excludes_reference(self):
        code = (
            "import sys; import aurora.production_main; "
            "print('LOADED' if 'aurora.execution_truth' in sys.modules else 'CLEAN')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("CLEAN", proc.stdout)

    def test_reference_module_has_no_broker_network_or_secret_surface(self):
        with open(REFERENCE_FILE, encoding="utf-8") as fh:
            src = fh.read()
        for token in ("binance.client", "ccxt", "import requests", "BINANCE_API"):
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
