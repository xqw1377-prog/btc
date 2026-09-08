"""事故运行状态的只读权威门。

事故账本不存在、不可读、schema 不完整或状态非法时，一律是 UNKNOWN。
本模块绝不创建、迁移或修改账本。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from typing import Any, Dict, Optional

from aurora import p0_boundary
from aurora.p0_boundary import SafetyViolation


def incident_ledger_path() -> str:
    return os.path.join(p0_boundary.state_root(), "kernel_ledger.db")


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_incident_state(path: Optional[str] = None) -> Dict[str, Any]:
    """只读事故 kill；任何不确定性都显式返回 UNKNOWN。"""
    target = os.path.abspath(path or incident_ledger_path())
    if not os.path.isfile(target):
        return {
            "status": "UNKNOWN",
            "reason": "authoritative incident ledger absent",
            "path": target,
            "digest": None,
            "written": False,
        }
    try:
        digest = _digest(target)
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT engaged FROM kill_switch WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "reason": f"authoritative incident ledger unreadable: "
                      f"{type(exc).__name__}",
            "path": target,
            "digest": None,
            "written": False,
        }
    if row is None or row[0] not in (0, 1):
        return {
            "status": "UNKNOWN",
            "reason": "authoritative incident kill row missing or invalid",
            "path": target,
            "digest": digest,
            "written": False,
        }
    engaged = int(row[0])
    return {
        "status": "ACTIVE" if engaged else "CLEAR",
        "engaged": engaged,
        "path": target,
        "digest": digest,
        "written": False,
    }


def assert_incident_clear(path: Optional[str] = None) -> Dict[str, Any]:
    """生产执行入口只接受权威且明确的 CLEAR。"""
    state = read_incident_state(path)
    if state["status"] == "UNKNOWN":
        raise SafetyViolation(
            f"[P0] INCIDENT_STATE_UNKNOWN: {state.get('reason')}; boot denied."
        )
    if state["status"] != "CLEAR":
        raise SafetyViolation(
            "[P0] INCIDENT_LOCK ACTIVE; production execution boot denied."
        )
    return state
