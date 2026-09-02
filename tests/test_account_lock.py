"""P0-A 账户锁测试：同账户互斥、释放后可重取、不同账户互不影响。

补充 tests/test_p0_safety.py::test_p0_10 之外的锁语义。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora.p0_boundary import AccountLock, SafetyViolation  # noqa: E402
from aurora.safety import acquire_instance_lock  # noqa: E402


class AccountLockTests(unittest.TestCase):
    def test_same_fingerprint_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = AccountLock(tmp, "fp1")
            b = AccountLock(tmp, "fp1")
            a.acquire()
            with self.assertRaises(SafetyViolation):
                b.acquire()
            a.release()

    def test_release_then_reacquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = AccountLock(tmp, "fp1")
            a.acquire()
            a.release()
            b = AccountLock(tmp, "fp1")
            b.acquire()
            b.release()

    def test_different_fingerprints_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = AccountLock(tmp, "fp1")
            b = AccountLock(tmp, "fp2")
            a.acquire()
            b.acquire()
            a.release()
            b.release()

    def test_lock_survives_until_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = AccountLock(tmp, "fp1")
            a.acquire()
            b = AccountLock(tmp, "fp1")
            for _ in range(3):
                with self.assertRaises(SafetyViolation):
                    b.acquire()
            a.release()


class RetiredFacadeTests(unittest.TestCase):
    def test_process_lock_facade_retired(self):
        """旧进程级锁已由账户指纹锁取代；facade 必须拒绝。"""

        with self.assertRaises(SafetyViolation):
            acquire_instance_lock()


if __name__ == "__main__":
    unittest.main()
