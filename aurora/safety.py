"""Compatibility facade over the P0 Safety Boundary.

Old kernels must not obtain a trading client. The only allowed process
entry for anything that could trade is `python -m aurora.production_main`.
"""
from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    assert_client_construction_targets,
    assert_client_endpoint,
    assert_live_dual_auth,
    install_outbound_guard,
    assert_not_live_trading,
    key_fingerprint,
    resolve_account_fingerprint,
    resolve_mode,
)


def env_value(name):
    import os
    return (os.getenv(name) or "").strip()


def live_gates():
    from aurora.p0_boundary import assert_live_dual_auth, assert_not_live_trading

    assert_live_dual_auth()
    assert_not_live_trading(RunMode.LIVE)


def probe_account(client):
    try:
        account = client.futures_account()
    except Exception as e:
        raise SafetyViolation(f"[P0] account probe failed: {str(e)[:200]}")
    if not isinstance(account, dict):
        raise SafetyViolation("[P0] account probe returned invalid payload.")
    return account


def build_client(mode, purpose, environ=None):
    from binance.client import Client
    import os

    src = os.environ if environ is None else environ
    if isinstance(mode, RunMode):
        mode_name = mode.value
        mode_enum = mode
    else:
        mode_name = mode
        mode_enum = RunMode(mode)
    if mode_enum == RunMode.PAPER:
        raise SafetyViolation("[P0] PAPER must not open an exchange client.")
    # LIVE：双重授权 + 武装令牌都通过后才允许构造主网 Client。
    if mode_enum == RunMode.LIVE:
        assert_live_dual_auth(environ if environ is not None else None)
        assert_not_live_trading(mode_enum)
    api_key = src.get("BINANCE_API_KEY")
    api_secret = src.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise SafetyViolation("[P0] missing BINANCE_API_KEY/SECRET.")
    # 构造期即出网：先校验 SDK 将使用的目标常量，再禁跳转，再挂出站守卫。
    assert_client_construction_targets(Client, mode_enum)
    try:
        client = Client(
            api_key,
            api_secret,
            testnet=(mode_enum != RunMode.LIVE),
            requests_params={"allow_redirects": False},
        )
    except Exception as e:
        raise SafetyViolation(f"[P0] exchange connect failed ({purpose}): {str(e)[:200]}")
    install_outbound_guard(client, mode_enum)
    assert_client_endpoint(client, mode_enum)
    resolve_account_fingerprint(mode_enum, api_key, environ)
    return client


def acquire_instance_lock():
    raise SafetyViolation(
        "[P0] process-level lock is retired; account-fingerprint lock lives in production_main."
    )


def trading_client():
    raise SafetyViolation(
        "[P0] direct trading entries are retired. "
        "Start only via: python -m aurora.production_main"
    )


def read_only_client(environ=None):
    mode = resolve_mode(environ if environ is not None else None)
    if mode == RunMode.PAPER:
        raise SafetyViolation("[P0] PAPER forbids exchange connections, including read-only.")
    if mode == RunMode.LIVE:
        raise SafetyViolation("[P0] LIVE remains NO-GO, including read-only clients.")
    return build_client(mode, "read-only", environ=environ)
