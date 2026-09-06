"""Config self-check: python -m aurora.safety_check

Reads configuration from ONE explicit source (--env-file, defaulting to the
repo-root .env), applies existing mode/conflict rules, and reports. It never
constructs an exchange client, never touches the network, and never attaches
the runtime. A complete set of LIVE authorization fields is reported as
"fields present" — it is NOT a live-trading approval.

Importing this module has no side effects: no .env read, no env mutation,
no client construction.
"""
import argparse
import os
import sys

from aurora.p0_boundary import (
    RunMode,
    SafetyViolation,
    assert_live_dual_auth,
    live_execution_armed,
    resolve_mode,
)


def default_env_file() -> str:
    """The single sanctioned config source for self-check: <repo>/.env."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--env-file",
        default=default_env_file(),
        help="explicit dotenv path; no parent-directory search is performed",
    )
    ap.add_argument("--probe", action="store_true", help="unused; probes belong to production_main")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv

    env_file = os.path.abspath(args.env_file)
    if os.path.isfile(env_file):
        # 进程环境优先于文件同名键；不覆盖既有环境变量。
        load_dotenv(dotenv_path=env_file, override=False)
        print(f"[P0] config source: {env_file} (loaded; process env takes precedence)")
    else:
        print(f"[P0] config source: {env_file} NOT FOUND; using process environment only")

    try:
        mode = resolve_mode()
        if mode == RunMode.LIVE:
            assert_live_dual_auth()
    except SafetyViolation as e:
        print(f"[P0] config consistency: REJECTED — {e}")
        sys.exit(1)

    print(f"[P0] config consistency: accepted; requested mode={mode.value}")
    print(
        "[P0] execution restriction: self-check only — no client construction,"
        " no network request, no runtime attach."
    )
    if mode == RunMode.PAPER:
        print("[P0] PAPER: no exchange connection.")
    if mode == RunMode.LIVE:
        if live_execution_armed():
            print(
                "[P0] LIVE dual-auth + arm token fields present. This is a"
                " config finding only, NOT live approval: LIVE remains NO-GO"
                " under the production boundary and endpoint policy."
            )
        else:
            print("[P0] LIVE dual-auth present, but LIVE remains NO-GO without AURORA_ARM_LIVE.")
        sys.exit(0)
    if args.probe:
        print("[P0] --probe ignored; use python -m aurora.production_main --boot-only")
    sys.exit(0)


if __name__ == "__main__":
    main()
