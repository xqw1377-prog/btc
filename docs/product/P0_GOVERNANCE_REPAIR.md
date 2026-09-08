# P0 GOVERNANCE REPAIR

Status: `CLOSED f0efb2b`  
Date: `2026-09-08`  
Scope: execution governance only; no exchange write, no permit issuance,
no incident-kill clear.

## Repaired contracts

### P0-EXEC-1 — Controlled qualification hard gate

Before any write-client construction:

```text
EXECUTE_AUTHORIZED == TRUE
AND valid Start Order
AND exact-session single-use permit
AND explicit operator CLI flag
AND no terminal session record
```

`EXECUTE_AUTHORIZED == FALSE` is terminal denial. It is not a legacy
indicator and cannot be bypassed by an otherwise valid execution window.

### P0-EXEC-2 — Production entry governance

`production_main` may not consume a controlled qualification permit.
While the authoritative incident state is `ACTIVE` or `UNKNOWN`, TESTNET/LIVE
production boot is denied before Binance client construction. `SHADOW` remains
the networked read-only path.

`AURORA_ENABLE_TRADING=true` through `production_main` remains denied even if
the incident state is later `CLEAR`; AUTO TESTNET needs a separate future
qualification and code review.

### P0-EXEC-3 — Incident state cannot default to CLEAR

The authoritative source is the read-only incident ledger
`state/kernel_ledger.db`, table `kill_switch`, row `id=1`.

Missing file, unreadable database, missing row, invalid `engaged`, or invalid
namespaced migration target is `INCIDENT_STATE_UNKNOWN` and denies boot.
Creating a new ledger with its schema default `kill=0` cannot establish
incident clearance.

## Verification

```text
Targeted governance regression: 85 passed
Full offline regression:         455 passed
Exchange writes:                 0
production_main runs:            0
Permits issued:                   0
Incident kill mutations:         0
```

Key tests:

- `tests/test_controlled_requal.py`
- `tests/test_incident_governance.py`
- `tests/test_g05_identity_isolation.py`
- `tests/test_production_entry_integrity.py`
- `tests/test_armed_live_capability.py`

## Qualification impact

```text
P0-GOVERNANCE-REPAIR     PASS
E0 ACCOUNTING TRUTH      HOLD
E1 RISK SEMANTICS        HOLD
E2 STRATEGY V2           HOLD
E3 BACKTEST              HOLD
AUTO TESTNET             DENIED
LIVE                     NO-GO
```

PASS-1 evidence completeness and CTR-03 authorization provenance remain
separate P1/governance findings. This repair does not upgrade their
qualification credit.
