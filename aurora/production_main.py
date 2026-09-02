"""AURORA production entry: P0 Safety Boundary boot only.

Boot order (any failure exits, no trading loop):
  resolve+validate mode
  -> account fingerprint
  -> single-instance account lock
  -> restore safety/risk halt state
  -> full exchange reconcile (non-PAPER)
  -> verify position mode (read-only)
  -> verify kill switch
  -> idle / shadow heartbeat

This process never imports aurora_final or aurora_hf_kernel.
LIVE remains NO-GO even when dual-auth is present.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from aurora.p0_boundary import (
    BrokerError,
    BootContext,
    PositionMode,
    PositionQueryKind,
    PositionSnapshot,
    RunMode,
    SafetyViolation,
    boot,
    default_lock_dir,
    default_state_path,
    resolve_mode,
)


FORBIDDEN_IMPORTS = ("aurora_hf_kernel", "aurora_final")


class BinanceBroker:
    def __init__(self, client: Any, mode: RunMode):
        self._client = client
        self.futures_url = getattr(client, "FUTURES_URL", "") or ""
        self._mode = mode

    def account(self) -> Dict[str, Any]:
        try:
            data = self._client.futures_account()
        except Exception as exc:
            raise BrokerError(str(exc)) from exc
        if not isinstance(data, dict):
            raise BrokerError("account probe returned non-dict")
        return data

    def get_position_mode(self) -> PositionMode:
        try:
            data = self._client.futures_get_position_mode()
        except Exception as exc:
            raise BrokerError(str(exc)) from exc
        dual = data.get("dualSidePosition")
        if isinstance(dual, str):
            dual = dual.lower() == "true"
        return PositionMode.HEDGE if dual else PositionMode.ONE_WAY

    def get_position(self, symbol: str) -> PositionSnapshot:
        try:
            rows = self._client.futures_position_information(symbol=symbol)
        except Exception as exc:
            raise BrokerError(str(exc)) from exc
        if rows is None:
            raise BrokerError("position query returned empty")
        for row in rows:
            amt = float(row.get("positionAmt") or 0)
            if amt != 0:
                return PositionSnapshot(
                    kind=PositionQueryKind.OPEN,
                    side="LONG" if amt > 0 else "SHORT",
                    size=abs(amt),
                    entry_price=float(row.get("entryPrice") or 0),
                )
        return PositionSnapshot(kind=PositionQueryKind.FLAT)

    def create_order(self, **params: Any) -> Dict[str, Any]:
        raise SafetyViolation("[P0] production_main will not place orders in this phase.")

    def get_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        try:
            return self._client.futures_get_order(symbol=symbol, origClientOrderId=client_order_id)
        except Exception as exc:
            raise BrokerError(str(exc)) from exc

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        try:
            return self._client.futures_cancel_order(symbol=symbol, orderId=order_id)
        except Exception as exc:
            raise BrokerError(str(exc)) from exc

    def open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            return list(self._client.futures_get_open_orders(symbol=symbol) or [])
        except Exception as exc:
            raise BrokerError(str(exc)) from exc


def _build_network_broker(mode: RunMode) -> BinanceBroker:
    from binance.client import Client

    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise SafetyViolation("[P0] missing BINANCE_API_KEY/SECRET.")
    if mode == RunMode.LIVE:
        client = Client(api_key, api_secret, testnet=False)
    else:
        client = Client(api_key, api_secret, testnet=True)
    return BinanceBroker(client, mode)


def run_boot() -> BootContext:
    load_dotenv()
    mode = resolve_mode()
    broker = None
    if mode in (RunMode.TESTNET, RunMode.SHADOW, RunMode.LIVE):
        broker = _build_network_broker(mode)
    return boot(
        persist_path=os.getenv("AURORA_P0_STATE") or default_state_path(),
        lock_dir=os.getenv("AURORA_P0_LOCK_DIR") or default_lock_dir(),
        broker=broker,
    )


def _idle(ctx: BootContext) -> int:
    running = True

    def _stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(
        f"[P0] boot ok mode={ctx.mode.value} fingerprint={ctx.fingerprint} "
        f"status={ctx.status} LIVE=NO-GO"
    )
    if ctx.mode == RunMode.PAPER:
        print("[P0] PAPER idle: no exchange connection, no orders.")
    elif ctx.mode == RunMode.SHADOW:
        print("[P0] SHADOW idle: read-only reconcile heartbeat, no orders.")
    elif ctx.mode == RunMode.TESTNET:
        print("[P0] TESTNET ready: safety boundary up, order path not armed.")
    while running:
        if ctx.executor is not None:
            rec = ctx.executor.reconcile("timer")
            if rec.status.value != "MATCHED":
                print(f"[P0] timer reconcile {rec.status.value}: {rec.reason}")
        time.sleep(30)
    ctx.lock.release()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for name in FORBIDDEN_IMPORTS:
        if name in sys.modules:
            print(f"[P0] forbidden module already imported: {name}")
            return 2
    try:
        ctx = run_boot()
    except SafetyViolation as exc:
        print(exc)
        return 1
    except Exception as exc:
        print(f"[P0] boot crashed; refuse trading loop: {exc}")
        return 1
    if "--boot-only" in (argv or sys.argv[1:]):
        ctx.lock.release()
        print("[P0] --boot-only: exiting after successful safety boot.")
        return 0
    return _idle(ctx)


if __name__ == "__main__":
    sys.exit(main())
