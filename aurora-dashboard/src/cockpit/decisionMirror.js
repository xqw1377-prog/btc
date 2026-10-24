/** P3-R2 — Map observatory.decision → LEFT 05 + RIGHT Portfolio Decision (display only). */

function rowsFromBackend(leftCard) {
  return (leftCard?.mirror_rows || []).map(({ label, value }) => ({
    label,
    value: value ?? "—",
    unknown:
      value == null ||
      value === "UNKNOWN" ||
      value === "UNAVAILABLE" ||
      String(value).includes("UNKNOWN"),
  }));
}

/** LEFT 05 — backend left_card is source of truth; no P0–P5 recompute. */
export function decisionLeftFromObservatory(decisionBundle) {
  const lc = decisionBundle?.left_card || {};
  const headlines = lc.headlines || [lc.headline_action || "PORTFOLIO DECISION"];
  const headlineAction = lc.headline_action || headlines[0] || "—";

  let statusDot = "partial";
  if (lc.tone === "defensive") statusDot = "bear";
  else if (lc.target_status === "UNKNOWN") statusDot = "unknown";
  else if (lc.delta_status === "AVAILABLE") statusDot = "bull";

  const lines = [...headlines];
  if (headlineAction && !lines.includes(headlineAction)) {
    lines.push(headlineAction);
  }

  return {
    index: lc.index || "05",
    title: lc.title || "PORTFOLIO DECISION",
    subtitle: lc.subtitle || "统一资本判断",
    cap: decisionBundle?.capability || "READ-ONLY-DECISION",
    statusDot,
    headline: headlines[0],
    headlines: lines,
    headlineAction,
    targetStatus: lc.target_status || decisionBundle?.target_status || "UNKNOWN",
    deltaStatus: lc.delta_status || decisionBundle?.delta_status || "UNAVAILABLE",
    decisionState: lc.decision_state || headlineAction,
    mirror: {
      rows: rowsFromBackend(lc),
      whyNot: lc.why_not || lc.evidence || null,
    },
    meta: lc.meta || ["READ ONLY", "TARGET ≠ ORDER", "RISK NOT APPLIED"],
    evidence: lc.evidence || lc.why_not || "—",
    disclaimer: lc.disclaimer || decisionBundle?.disclaimer || "DELTA ≠ EXECUTION · RISKGATE NOT APPLIED",
    decisionKey: decisionBundle?.decision_key || null,
    submitAllowed: Boolean(decisionBundle?.submit_allowed),
    live: false,
  };
}

function fmtMix(btc, eth, usdt) {
  if (btc == null && eth == null && usdt == null) return "UNKNOWN";
  return `BTC ${btc ?? "—"} · ETH ${eth ?? "—"} · USDT ${usdt ?? "—"}`;
}

function fmtDeltaLayer(layer) {
  if (!layer || layer.status === "UNAVAILABLE" || layer.status === "UNKNOWN") {
    return layer?.status || "UNAVAILABLE";
  }
  const parts = [];
  if (layer.btc != null && layer.btc !== 0) {
    parts.push(layer.btc < 0 ? `REDUCE BTC EXPOSURE ${Math.abs(layer.btc)}` : `INCREASE BTC EXPOSURE ${layer.btc}`);
  }
  if (layer.eth != null && layer.eth !== 0) {
    parts.push(layer.eth < 0 ? `REDUCE ETH EXPOSURE ${Math.abs(layer.eth)}` : `INCREASE ETH EXPOSURE ${layer.eth}`);
  }
  if (layer.usdt != null && layer.usdt !== 0) {
    parts.push(`USDT ${layer.usdt > 0 ? "+" : ""}${layer.usdt}`);
  }
  return parts.length ? parts.join(" · ") : "NO CHANGE";
}

/** RIGHT Portfolio Decision — six layers from backend candidate projection. */
export function decisionEvidenceFromObservatory(decisionBundle) {
  const right = decisionBundle?.right_evidence || {};
  const finalView = right.final_view || {};
  const current = right.current || {};
  const target = right.target_candidate || {};
  const delta = right.delta_proposal || {};
  const why = right.why || {};
  const authority = right.authority || {};
  const cluster = why.crypto_beta_cluster || {};
  const eventInc = why.event_increment || {};

  return {
    capability: decisionBundle?.capability || "READ-ONLY-DECISION",
    title: right.title || "PORTFOLIO DECISION",
    finalView: {
      decisionState: finalView.decision_state || decisionBundle?.candidate?.runtime_kind,
      targetStatus: finalView.target_status || target.status,
      deltaStatus: finalView.delta_status || delta.status,
      primaryBlocker: finalView.primary_blocker,
      decisionKey: finalView.decision_key || decisionBundle?.decision_key,
      asOf: finalView.as_of || decisionBundle?.as_of,
      idempotent: Boolean(finalView.idempotent),
    },
    current: {
      mix: fmtMix(current.btc, current.eth, current.usdt),
      btcOverlay: current.btc_overlay,
      ethOverlay: current.eth_overlay,
      truthStatus: current.truth_status || "UNKNOWN",
      accountVersion: current.account_version,
    },
    targetCandidate: {
      mix: fmtMix(target.btc, target.eth, target.usdt),
      btcOverlay: target.btc_overlay,
      ethOverlay: target.eth_overlay,
      eventIncrement: target.event_increment,
      status: target.status,
    },
    deltaProposal: {
      summary: fmtDeltaLayer(delta),
      btc: delta.btc,
      eth: delta.eth,
      usdt: delta.usdt,
      btcOverlay: delta.btc_overlay,
      ethOverlay: delta.eth_overlay,
      eventIncrement: delta.event_increment,
      status: delta.status,
    },
    why: {
      decisionTrace: why.decision_trace || decisionBundle?.decision_trace?.stages || [],
      traceWinner: why.trace_winner || decisionBundle?.decision_trace?.winner,
      cryptoBetaCluster: {
        btcRequest: cluster.btc_overlay_request,
        ethRequest: cluster.eth_overlay_request,
        combinedState: cluster.combined_state || "NONE",
        independentFullBudgets: cluster.independent_full_budgets || "NOT ALLOWED",
        clusterCap: cluster.cluster_cap,
      },
      eventIncrement: {
        baseTrendRisk: eventInc.base_trend_risk || "NONE",
        incrementRequest: eventInc.event_increment_request || "NONE",
        finalRiskAmount: eventInc.final_risk_amount || "NOT DECIDED",
      },
      reasons: why.reasons || decisionBundle?.candidate?.reasons || [],
      blockers: why.blockers || decisionBundle?.candidate?.blockers || [],
    },
    authority: {
      riskgate: authority.riskgate || "NOT APPLIED",
      execution: authority.execution || "DENIED",
      submitAllowed: Boolean(authority.submit_allowed),
      targetNotOrder: authority.target_not_order !== false,
      deltaNotExecution: authority.delta_not_execution !== false,
    },
  };
}
