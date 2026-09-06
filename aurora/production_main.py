"""AURORA production entry: safety boot then optional armed kernel.

Boot order (any failure exits, no trading loop):
  resolve+validate mode
  -> LIVE dual-auth + arm token (LIVE only)
  -> account fingerprint
  -> single-instance account lock
  -> restore safety/risk halt state
  -> full exchange reconcile (non-PAPER)
  -> verify position mode (read-only)
  -> verify kill switch
  -> TESTNET/LIVE: arm kernel Orchestrator and recover()
  -> idle / shadow heartbeat

This process never imports aurora_final or aurora_hf_kernel.
Read-only BinanceBroker still cannot place or cancel orders.
LIVE without AURORA_ARM_LIVE remains NO-GO before any Client construction.
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
    assert_client_construction_targets,
    assert_client_endpoint,
    assert_live_dual_auth,
    install_outbound_guard,
    effective_futures_url,
    assert_not_live_trading,
    boot,
    default_lock_dir,
    default_state_path,
    resolve_mode,
)


FORBIDDEN_IMPORTS = ("aurora_hf_kernel", "aurora_final")


class BinanceBroker:
    def __init__(self, client: Any, mode: RunMode):
        self._client = client
        self.futures_url = effective_futures_url(client)
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
        open_legs = []
        for row in rows:
            amt = float(row.get("positionAmt") or 0)
            if amt != 0:
                open_legs.append((amt, row))
        if len(open_legs) > 1:
            # HEDGE 双腿同时非零：禁止只取第一条，否则另一腿从账本消失
            return PositionSnapshot(kind=PositionQueryKind.UNKNOWN)
        if len(open_legs) == 1:
            amt, row = open_legs[0]
            return PositionSnapshot(
                kind=PositionQueryKind.OPEN,
                side="LONG" if amt > 0 else "SHORT",
                size=abs(amt),
                entry_price=float(row.get("entryPrice") or 0),
            )
        return PositionSnapshot(kind=PositionQueryKind.FLAT)

    @property
    def client(self) -> Any:
        return self._client

    def create_order(self, **params: Any) -> Dict[str, Any]:
        raise SafetyViolation("[P0] production_main will not place orders in this phase.")

    def get_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        try:
            return self._client.futures_get_order(symbol=symbol, origClientOrderId=client_order_id)
        except Exception as exc:
            raise BrokerError(str(exc)) from exc

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        # 只读 broker 不具备任何账户变更能力；撤单仅允许经武装执行内核
        # 按精确 client_order_id 执行（P0-A 复审修复）
        raise SafetyViolation(
            "[P0] read-only broker refuses cancel; cancel belongs to the"
            " armed execution kernel only."
        )

    def open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            return list(self._client.futures_get_open_orders(symbol=symbol) or [])
        except Exception as exc:
            raise BrokerError(str(exc)) from exc


def _build_network_broker(mode: RunMode) -> BinanceBroker:
    # LIVE 未武装时必须在任何 Client 构造之前拒绝（构造主网 Client 即出网）。
    if mode == RunMode.LIVE:
        # 先查武装令牌：未武装时不得因环境未设 TRADING_MODE=LIVE 而走错门禁。
        assert_not_live_trading(mode)
        assert_live_dual_auth()
    from binance.client import Client

    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise SafetyViolation("[P0] missing BINANCE_API_KEY/SECRET.")
    # 构造期即出网：先校验 SDK 将使用的目标常量，再禁跳转，再挂出站守卫。
    assert_client_construction_targets(Client, mode)
    client = Client(
        api_key,
        api_secret,
        testnet=(mode != RunMode.LIVE),
        requests_params={"allow_redirects": False},
    )
    install_outbound_guard(client, mode)
    assert_client_endpoint(client, mode)
    return BinanceBroker(client, mode)


def run_boot() -> BootContext:
    load_dotenv()
    mode = resolve_mode()
    broker = None
    if mode == RunMode.LIVE:
        # 未武装：双重授权可校验，但绝不能构造主网客户端
        assert_live_dual_auth()
        assert_not_live_trading(mode)
    if mode in (RunMode.TESTNET, RunMode.SHADOW, RunMode.LIVE):
        broker = _build_network_broker(mode)
    return boot(
        persist_path=os.getenv("AURORA_P0_STATE") or default_state_path(),
        lock_dir=os.getenv("AURORA_P0_LOCK_DIR") or default_lock_dir(),
        broker=broker,
    )


def _arm_runtime(ctx: BootContext):
    if ctx.mode not in (RunMode.TESTNET, RunMode.LIVE):
        return None
    if ctx.broker is None:
        raise SafetyViolation(f"[P0] {ctx.mode.value} arm requires a broker client.")
    from aurora.armed_runtime import ArmedRuntime, default_ledger_path

    return ArmedRuntime.attach(
        ctx.mode,
        ctx.broker.client,
        ledger_path=os.getenv("AURORA_LEDGER_PATH") or default_ledger_path(),
    )


def _idle(ctx: BootContext, runtime=None, once: bool = False) -> int:
    running = True

    def _stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    armed = runtime is not None
    print(
        f"[P0] boot ok mode={ctx.mode.value} fingerprint={ctx.fingerprint} "
        f"status={ctx.status} armed={armed}"
    )
    if ctx.mode == RunMode.PAPER:
        print("[P0] PAPER idle: no exchange connection, no orders.")
    elif ctx.mode == RunMode.SHADOW:
        print("[P0] SHADOW idle: read-only reconcile heartbeat, no orders.")
    elif ctx.mode == RunMode.TESTNET:
        print("[P0] TESTNET armed: decision cycle on closed bars; orders require AURORA_ENABLE_TRADING=true.")
    elif ctx.mode == RunMode.LIVE:
        print("[P0] LIVE armed: decision cycle on closed bars; orders require AURORA_ENABLE_TRADING=true.")
    from aurora.trading_cycle import TradingCycle, trading_enabled

    cycle = None
    if runtime is not None and ctx.mode in (RunMode.TESTNET, RunMode.LIVE):
        cycle = TradingCycle(runtime, ctx.broker.client, mode=ctx.mode)
    enabled = trading_enabled()
    if cycle is not None:
        print(f"[P0] trading_cycle attached enable={enabled}")
    while running:
        if cycle is not None:
            out = cycle.step(enable=enabled)
            print(
                f"[P0] cycle action={out.get('action')} submitted={out.get('submitted')} "
                f"reason={out.get('reason') or out.get('decision_reason')}"
            )
        elif runtime is not None:
            report = runtime.recover()
            if report.get("unresolved"):
                print(f"[P0] kernel recover unresolved: {report['unresolved']}")
        elif ctx.executor is not None:
            rec = ctx.executor.reconcile("timer")
            if rec.status.value != "MATCHED":
                print(f"[P0] timer reconcile {rec.status.value}: {rec.reason}")
        if once:
            break
        time.sleep(30)
    if runtime is not None:
        runtime.close()
    ctx.lock.release()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for name in FORBIDDEN_IMPORTS:
        if name in sys.modules:
            print(f"[P0] forbidden module already imported: {name}")
            return 2
    runtime = None
    try:
        ctx = run_boot()
        runtime = _arm_runtime(ctx)
    except SafetyViolation as exc:
        print(exc)
        return 1
    except Exception as exc:
        print(f"[P0] boot crashed; refuse trading loop: {exc}")
        return 1
    argv = argv or sys.argv[1:]
    if "--boot-only" in argv:
        if runtime is not None:
            runtime.close()
        ctx.lock.release()
        print("[P0] --boot-only: exiting after successful safety boot.")
        return 0
    return _idle(ctx, runtime, once="--once" in argv)


if __name__ == "__main__":
    sys.exit(main())
