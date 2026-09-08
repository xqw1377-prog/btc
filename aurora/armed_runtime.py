"""Armed execution runtime: kernel Orchestrator over an injected exchange.

Only TESTNET and LIVE (after dual-auth + arm token) may attach.
SHADOW/PAPER cannot submit. This module never constructs a Binance Client.

G0-5B：账本状态按 state/<mode>/<fingerprint>/kernel_ledger.db 物理隔离；
遗留 state/kernel_ledger.db（含事故 ACTIVE kill）经 ensure_ledger_migrated
以 sqlite backup API 只读接管到命名空间路径，原文件永不改写。
G0-5A：期望持仓模式经调用方显式传入（expected_mode），不再默认读
os.environ——配置只能来自 ConfigSource。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Optional

from aurora.kernel.binance_exchange import BinanceExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.p0_boundary import (
    RunMode, SafetyViolation, assert_not_live_trading, expected_position_mode,
    state_root,
)


def legacy_ledger_path() -> str:
    """事故封存账本（state/kernel_ledger.db）：只读源头，永不改写。"""
    return os.path.join(state_root(), "kernel_ledger.db")


def namespaced_ledger_path(mode: RunMode, fingerprint: str) -> str:
    return os.path.join(
        state_root(), mode.value.lower(), fingerprint, "kernel_ledger.db")


def ensure_ledger_migrated(legacy_path: str, target_path: str) -> Optional[str]:
    """把遗留账本只读接管到命名空间路径（G0-5B）。

    - 目标已存在：不做任何事（幂等）。
    - 遗留不存在：不做任何事（全新命名空间）。
    - 两者皆备：sqlite backup API 复制（含 kill_switch 事实），原文件
      以只读方式打开，绝不写回；复制后校验目标可打开且 kill 行存在。
    返回迁移说明（未迁移返回 None）。
    """
    if os.path.exists(target_path) or not os.path.exists(legacy_path):
        return None
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    src = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target_path)
        try:
            src.backup(dst)
            # backup 会连 WAL 头标志一起复制；目标在此刻必须是自包含文件，
            # 否则只读校验/后续只读打开会因缺 -wal 伴生而失败。
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    check = sqlite3.connect(f"file:{target_path}?mode=ro", uri=True)
    try:
        row = check.execute(
            "SELECT engaged FROM kill_switch WHERE id = 1").fetchone()
        if row is None:
            raise SafetyViolation(
                "[P0] ledger migration produced a target without kill_switch row.")
    finally:
        check.close()
    return f"legacy ledger migrated (read-only takeover) -> {target_path}"


class ArmedRuntime:
    def __init__(
        self,
        mode: RunMode,
        orchestrator: Orchestrator,
        ledger: Ledger,
        exchange: BinanceExchange,
        boot_report: Dict[str, Any],
    ):
        self.mode = mode
        self.orchestrator = orchestrator
        self.ledger = ledger
        self.exchange = exchange
        self.boot_report = boot_report

    @classmethod
    def attach(
        cls,
        mode: RunMode,
        client: Any,
        ledger_path: Optional[str] = None,
        symbol: str = "BTCUSDT",
        expected_mode: Optional[str] = None,
    ) -> "ArmedRuntime":
        if mode == RunMode.PAPER:
            raise SafetyViolation("[P0] PAPER cannot arm the execution kernel.")
        if mode == RunMode.SHADOW:
            raise SafetyViolation("[P0] SHADOW is read-only; execution kernel stays unarmed.")
        if mode == RunMode.LIVE:
            assert_not_live_trading(mode)
        if mode not in (RunMode.TESTNET, RunMode.LIVE):
            raise SafetyViolation(f"[P0] cannot arm execution in mode={mode}")
        probe = BinanceExchange(client, symbol=symbol, allow_mutate=False)
        observed = probe.position_mode_read()
        # G0-5A：期望模式必须由 ConfigSource 显式传入；仅当调用方完全
        # 未提供时才回退进程环境（兼容旧测试直连）。
        expected = expected_mode or expected_position_mode().value
        if observed is None:
            raise SafetyViolation(
                "[P0] position mode UNKNOWN; refuse execution attach.")
        if observed != expected:
            raise SafetyViolation(
                f"[P0] position mode {observed} != approved {expected}; refuse attach.")
        exchange = BinanceExchange(
            client, symbol=symbol, allow_mutate=True, position_mode=observed)
        path = ledger_path or namespaced_ledger_path(mode, "unbound")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        ledger = Ledger(path)
        orch = Orchestrator(ledger, exchange, symbol=symbol)
        report = orch.recover()
        return cls(mode, orch, ledger, exchange, report)

    def open_position(
        self, side: str, quantity: float, intent_id: Optional[str] = None,
        reason: str = "manual",
        stop_price: Optional[float] = None, take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self.orchestrator.open_position(
            side, quantity, intent_id=intent_id, reason=reason,
            stop_price=stop_price, take_profit_price=take_profit_price,
        )

    def close_position(self, reason: str = "manual") -> Dict[str, Any]:
        return self.orchestrator.close_position(reason)

    def recover(self) -> Dict[str, Any]:
        return self.orchestrator.recover()

    def close(self) -> None:
        self.ledger.close()
