"""Independent ops command to change Binance futures position mode.

The trading process must never call this. Requirements:
  - explicit --i-understand-account-wide
  - account has no open position
  - account has no open orders
  - target mode is HEDGE or ONE_WAY
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from aurora.p0_boundary import PositionQueryKind, RunMode, SafetyViolation, resolve_mode
from aurora.production_main import _build_network_broker


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Change account position mode (ops only).")
    parser.add_argument("--target", required=True, choices=("HEDGE", "ONE_WAY"))
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--i-understand-account-wide", action="store_true")
    args = parser.parse_args(argv)

    if not args.i_understand_account_wide:
        print("[OPS] refuse: pass --i-understand-account-wide after confirming no other bots.")
        return 2

    try:
        mode = resolve_mode()
        if mode == RunMode.PAPER:
            raise SafetyViolation("[OPS] PAPER has no exchange account.")
        if mode == RunMode.LIVE:
            raise SafetyViolation("[OPS] LIVE remains NO-GO; will not mutate a live account.")
        broker = _build_network_broker(mode)
        pos = broker.get_position(args.symbol)
        if pos.kind == PositionQueryKind.UNKNOWN:
            raise SafetyViolation("[OPS] position query UNKNOWN; refuse mode change.")
        if pos.kind == PositionQueryKind.OPEN:
            raise SafetyViolation("[OPS] open position exists; flatten first.")
        opens = broker.open_orders(args.symbol)
        if opens:
            raise SafetyViolation("[OPS] open orders exist; cancel by id first.")
        dual = "true" if args.target == "HEDGE" else "false"
        broker._client.futures_change_position_mode(dualSidePosition=dual)
        print(f"[OPS] position mode set to {args.target}")
        return 0
    except SafetyViolation as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
