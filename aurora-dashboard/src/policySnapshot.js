/**
 * Governance / identity static snapshot for D0.
 * Every STATIC SNAPSHOT surface must render capturedAt + sourceCommit.
 * Not a live feed. D1 must not invent overlay from 1m data.
 */
export const POLICY_SNAPSHOT = Object.freeze({
  kind: "STATIC SNAPSHOT",
  capturedAt: "2026-09-09T07:02:00Z",
  sourceCommit: "b1079f4",
  source: "docs/product/CAPABILITY_STATUS.md",
  incidentLock: "INCIDENT_LOCKED",
  kill: "ACTIVE",
  executeAuthorized: false,
  executionQualified: false,
  autoTestnet: "DENIED",
  live: "NO_GO",
  identity: Object.freeze({
    kind: "STATIC SNAPSHOT",
    capturedAt: "2026-09-09T07:02:00Z",
    sourceCommit: "ba3edfc",
    source: "aurora/strategy_v2.py",
    numeraire: "BTC",
    core: "HOLD BTC",
  }),
});
