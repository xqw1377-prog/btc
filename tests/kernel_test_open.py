"""Test-only helper: existing kernel suites assume FakeExchange price=100.

This is an explicit test SL/TP, not a production sentinel. G0-4B tests that
need missing/invalid SL must call Orchestrator.open_position without this wrap.
"""


def bind_explicit_protect_prices(orch, stop_price=99.0, take_profit_price=101.0):
    real = orch.open_position

    def wrapped(
        side,
        quantity,
        intent_id=None,
        reason="manual",
        stop_price=stop_price,
        take_profit_price=take_profit_price,
    ):
        return real(
            side,
            quantity,
            intent_id=intent_id,
            reason=reason,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    orch.open_position = wrapped
    return orch
