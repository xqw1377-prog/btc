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

from aurora.config_source import ConfigSource
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
    namespaced_lock_dir,
    namespaced_state_path,
    resolve_account_fingerprint,
    resolve_mode,
)


FORBIDDEN_IMPORTS = ("aurora_hf_kernel", "aurora_final")
SYMBOL = "BTCUSDT"
ENABLE_TOKEN = "true"


def _trading_requested(source: ConfigSource) -> bool:
    return (
        source.get("AURORA_ENABLE_TRADING") or ""
    ).strip().lower() == ENABLE_TOKEN


def assert_production_execution_governance(source: ConfigSource) -> None:
    """事故期生产入口不得获得写能力；UNKNOWN 也不得默认放行。

    Controlled Start Order / permit 只属于 ops_controlled_requal 的单次
    lifecycle，不能授权无限循环的 production_main。
    """
    mode = source.mode()
    if mode not in (RunMode.TESTNET, RunMode.LIVE):
        return
    from aurora.incident_governance import assert_incident_clear

    assert_incident_clear()
    if mode == RunMode.TESTNET and _trading_requested(source):
        raise SafetyViolation(
            "[P0] AUTO TESTNET DENIED; production_main cannot consume a "
            "controlled qualification permit. Use ops_controlled_requal only."
        )


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


def _build_network_broker(mode: RunMode, source: Optional[ConfigSource] = None) -> BinanceBroker:
    # LIVE 未武装时必须在任何 Client 构造之前拒绝（构造主网 Client 即出网）。
    values = source.as_environ() if source is not None else os.environ
    if mode == RunMode.LIVE:
        # 门禁必须读同一份 ConfigSource，禁止再偷偷回落一份未审计的进程环境。
        assert_not_live_trading(mode, values)
        assert_live_dual_auth(values)
    from binance.client import Client
    api_key = (values.get("BINANCE_API_KEY") or "").strip()
    api_secret = (values.get("BINANCE_API_SECRET") or "").strip()
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


def run_boot(env_file: Optional[str] = None) -> BootContext:
    """G0-5A/B/C：单一 ConfigSource → 命名空间状态 → 账户身份绑定。"""
    source = ConfigSource.load(env_file=env_file)
    mode = source.mode()
    broker = None
    if mode == RunMode.LIVE:
        # 未武装：双重授权可校验，但绝不能构造主网客户端
        assert_live_dual_auth(source.as_environ())
        assert_not_live_trading(mode, source.as_environ())
    # 必须先于任何 Binance Client 构造：ACTIVE / UNKNOWN 都不能让生产
    # 入口获得可写客户端。SHADOW 是事故期唯一联网只读入口。
    assert_production_execution_governance(source)
    if mode in (RunMode.TESTNET, RunMode.SHADOW, RunMode.LIVE):
        broker = _build_network_broker(mode, source)
    # 指纹必须先于状态路径解析（命名空间含指纹）；缺密钥/指纹在此拒启。
    fingerprint = resolve_account_fingerprint(
        mode, source.get("BINANCE_API_KEY"), source.as_environ())
    return boot(
        persist_path=(
            source.get("AURORA_P0_STATE")
            or namespaced_state_path(mode, fingerprint)
        ),
        lock_dir=(
            source.get("AURORA_P0_LOCK_DIR")
            or namespaced_lock_dir(mode, fingerprint)
        ),
        broker=broker,
        environ=source.as_environ(),
    )


def _arm_runtime(ctx: BootContext, source: Optional[ConfigSource] = None):
    if ctx.mode not in (RunMode.TESTNET, RunMode.LIVE):
        return None
    if ctx.broker is None:
        raise SafetyViolation(f"[P0] {ctx.mode.value} arm requires a broker client.")
    from aurora.armed_runtime import ArmedRuntime, ensure_ledger_migrated
    from aurora.p0_boundary import state_root

    ledger_override = source.get("AURORA_LEDGER_PATH") if source is not None else (
        os.getenv("AURORA_LEDGER_PATH") or "")
    if ledger_override:
        # 显式路径 = 隔离用途（测试/工具）：绝不继承事故遗留状态。
        ledger_path = ledger_override
    else:
        ledger_path = os.path.join(
            state_root(), ctx.mode.value.lower(), ctx.fingerprint, "kernel_ledger.db")
        # G0-5B：命名空间账本首次启用时，从事故遗留账本安全接管（kill 保留）。
        ensure_ledger_migrated(
            os.path.join(state_root(), "kernel_ledger.db"), ledger_path)
    return ArmedRuntime.attach(
        ctx.mode,
        ctx.broker.client,
        ledger_path=ledger_path,
        expected_mode=(
            source.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE"
        ) if source is not None else None,
    )


def _idle(ctx: BootContext, runtime=None, once: bool = False,
          source: Optional[ConfigSource] = None) -> int:
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
    enabled = trading_enabled(environ=source.as_environ()) if source is not None \
        else trading_enabled()
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
        elif ctx.broker is not None:
            # G0-5D：SHADOW 只读心跳（旧执行封装已退休）；
            # 这里只有 query+reconcile+persist，没有任何执行能力。
            from aurora.p0_boundary import query_position, reconcile

            exchange = query_position(ctx.broker, SYMBOL)
            rec = reconcile(ctx.store, exchange, "timer")
            ctx.persist.save(ctx.store)
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
    argv = list(argv if argv is not None else sys.argv[1:])
    env_file: Optional[str] = None
    if "--env-file" in argv:
        idx = argv.index("--env-file")
        try:
            env_file = argv[idx + 1]
        except IndexError:
            print("[P0] --env-file requires a path")
            return 2
        del argv[idx:idx + 2]
    runtime = None
    try:
        ctx = run_boot(env_file=env_file)
        runtime = _arm_runtime(ctx, source=ConfigSource.load(env_file=env_file))
    except SafetyViolation as exc:
        print(exc)
        return 1
    except Exception as exc:
        print(f"[P0] boot crashed; refuse trading loop: {exc}")
        return 1
    if "--boot-only" in argv:
        if runtime is not None:
            runtime.close()
        ctx.lock.release()
        print("[P0] --boot-only: exiting after successful safety boot.")
        return 0
    return _idle(
        ctx, runtime, once="--once" in argv,
        source=ConfigSource.load(env_file=env_file))


if __name__ == "__main__":
    sys.exit(main())
