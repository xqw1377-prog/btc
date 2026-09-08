"""Armed execution runtime: kernel Orchestrator over an injected exchange.

Only TESTNET and LIVE (after dual-auth + arm token) may attach.
SHADOW/PAPER cannot submit. This module never constructs a Binance Client.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from aurora.kernel.binance_exchange import BinanceExchange
from aurora.kernel.ledger import Ledger
from aurora.kernel.orchestrator import Orchestrator
from aurora.p0_boundary import (
    RunMode, SafetyViolation, assert_not_live_trading, expected_position_mode,
)


def default_ledger_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "state", "kernel_ledger.db")


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
        expected = expected_position_mode().value
        if observed is None:
            raise SafetyViolation(
                "[P0] position mode UNKNOWN; refuse execution attach.")
        if observed != expected:
            raise SafetyViolation(
                f"[P0] position mode {observed} != approved {expected}; refuse attach.")
        exchange = BinanceExchange(
            client, symbol=symbol, allow_mutate=True, position_mode=observed)
        path = ledger_path or os.getenv("AURORA_LEDGER_PATH") or default_ledger_path()
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
