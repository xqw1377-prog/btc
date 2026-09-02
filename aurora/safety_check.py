"""Config self-check: python -m aurora.safety_check

Does not start a trading loop. LIVE can only be validated as dual-auth
complete, then reported as NO-GO.
"""
import argparse
import sys

from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    assert_live_dual_auth,
    resolve_mode,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="unused; probes belong to production_main")
    args = ap.parse_args()

    try:
        mode = resolve_mode()
        if mode == RunMode.LIVE:
            assert_live_dual_auth()
    except SafetyViolation as e:
        print(e)
        sys.exit(1)

    print(f"[P0] TRADING_MODE={mode.value} config accepted.")
    if mode == RunMode.PAPER:
        print("[P0] PAPER: no exchange connection.")
    if mode == RunMode.LIVE:
        print("[P0] LIVE dual-auth present, but LIVE remains NO-GO.")
        sys.exit(0)
    if args.probe:
        print("[P0] --probe ignored; use python -m aurora.production_main --boot-only")
    sys.exit(0)


if __name__ == "__main__":
    main()
