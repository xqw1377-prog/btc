/** P2-C.3 — Map observatory event payload → product language (display only, no recompute). */

function rowsFromBackend(leftCard) {
  return (leftCard?.mirror_rows || []).map(({ label, value }) => ({
    label,
    value: value ?? "—",
    unknown: value == null || value === "UNKNOWN",
  }));
}

/** LEFT 04 card — backend left_card is source of truth. */
export function eventLeftFromObservatory(eventBundle) {
  const lc = eventBundle?.left_card || {};
  const disconnected = eventBundle?.observation_state === "SOURCE_NOT_CONNECTED";
  const sourceError = eventBundle?.source_health_summary === "SOURCE_ERROR";
  const noEvent = eventBundle?.observation_state === "NO_EVENT_OBSERVED" && !eventBundle?.primary_event_id;

  const headlines = lc.headlines || [lc.title || "MAJOR EVENT"];
  const headlineAction = lc.headline_action || "—";

  let statusDot = "partial";
  if (disconnected || sourceError) statusDot = "unknown";
  else if (lc.tone === "defensive") statusDot = "bear";
  else if (lc.tone === "positive") statusDot = "bull";
  else if (lc.retracted) statusDot = "unknown";

  const lines = [...headlines];
  if (headlineAction && !lines.includes(headlineAction)) {
    lines.push(headlineAction);
  }

  return {
    index: lc.index || "04",
    title: lc.title || "MAJOR EVENT",
    subtitle: lc.subtitle || "重大事件",
    cap: eventBundle?.capability || "READ-ONLY-SEMANTICS",
    statusDot,
    headline: headlines[0],
    headlines: lines,
    headlineAction,
    eventState: lc.event_state || eventBundle?.event_state || "UNKNOWN",
    mirror: {
      rows: rowsFromBackend(lc),
      whyNot: lc.evidence && lc.headline_action === "NO BOOST" ? lc.evidence : lc.why_not || null,
    },
    meta: lc.meta || ["READ ONLY", "ELIGIBLE ≠ ACTIVE"],
    evidence: lc.evidence || eventBundle?.disclaimer || "—",
    disclaimer: lc.disclaimer || eventBundle?.disclaimer || null,
    disconnected,
    sourceError,
    noEvent,
    retracted: Boolean(lc.retracted),
    primaryEventId: eventBundle?.primary_event_id || null,
    ingestion: eventBundle?.official_source_ingestion || "NOT_CONNECTED",
  };
}

/** RIGHT Event evidence — five layers from backend, zero FSM recompute. */
export function eventEvidenceFromObservatory(eventBundle) {
  const right = eventBundle?.right_evidence || {};
  const layers = right.layers || {};
  const disconnected = eventBundle?.observation_state === "SOURCE_NOT_CONNECTED";
  const sourceError = eventBundle?.source_health_summary === "SOURCE_ERROR";

  return {
    status: right.status || eventBundle?.status || "unknown",
    capability: eventBundle?.capability || "READ-ONLY-SEMANTICS",
    title: right.title || "EVENT INTELLIGENCE",
    disconnected,
    sourceError,
    sourceHealth: eventBundle?.source_health_summary || right.source_health || "UNKNOWN",
    eventState: eventBundle?.event_state || "UNKNOWN",
    observationState: eventBundle?.observation_state || "UNKNOWN",
    ingestion: eventBundle?.official_source_ingestion || "NOT_CONNECTED",
    lastObservedAt: right.last_observed_at || eventBundle?.last_observed_at,
    decisionEvents: eventBundle?.decision_events || "NONE",
    primaryEventId: eventBundle?.primary_event_id,
    activeCandidateCount: eventBundle?.active_candidate_count ?? 0,
    itemsSummary: right.items_summary || [],
    whatHappened: layers.what_happened || {},
    evidence: layers.evidence || {},
    impact: layers.impact || {},
    marketResponse: layers.market_response || {},
    actionEligibility: layers.action_eligibility || {},
    footer: right.footer || layers.footer || {},
    message: right.message || null,
    noEvent: eventBundle?.observation_state === "NO_EVENT_OBSERVED" && !eventBundle?.primary_event_id,
  };
}
