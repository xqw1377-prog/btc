import { useMemo, useState } from "react";
import { CAP_HINT } from "./capability";
import {
  CandlestickChart,
  ChartUnavailable,
  DEFAULT_TF,
  genCandles,
  genLine,
  genPerf,
  LineChart,
  normalizeKlines,
  PerfChart,
} from "./charts";

function isValidNumber(v) { return typeof v === "number" && Number.isFinite(v); }
function fmtNumber(v, digits = 6) { return isValidNumber(v) ? v.toFixed(digits) : "—"; }
function fmtPercent(v, digits = 1) { return isValidNumber(v) ? `${(v * 100).toFixed(digits)}%` : "—"; }

export function formatStamp(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const h = String(d.getUTCHours()).padStart(2, "0");
  const min = String(d.getUTCMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${h}:${min}Z`;
}

export function CapBadge({ cap, title }) {
  if (!cap) return null;
  const slug = cap.toLowerCase().replace(/\s+/g, "-");
  const hint = title || CAP_HINT[cap] || cap;
  return (
    <span className={`cap-badge cap-${slug}`} title={hint}>
      {cap}
    </span>
  );
}

function MetaChip({ label }) {
  return <span className="meta-chip">{label}</span>;
}

function StatusDot({ kind }) {
  return <span className={`status-dot dot-${kind || "unknown"}`} aria-hidden="true" />;
}

function ExecBadge({ label, tone = "solid" }) {
  return <span className={`exec-badge exec-${tone}`}>{label}</span>;
}

export function GlobalBar({ scene }) {
  const g = scene.global;
  const gov = scene.governance;
  const actualValues = g.actualMix?.values ?? g.mix;
  const actualMixKnown = actualValues?.btc != null && actualValues?.eth != null && actualValues?.usdt != null;
  const targetMix = g.targetMix;
  const navObj = g.btcNav;
  const hodlObj = g.vsHodl;
  const riskProxy = typeof g.risk === "object" ? g.risk : null;

  return (
    <header className="global-bar">
      <div className="global-bar-row">
        <div className="global-bar-brand">
          <strong className="brand-logo">AURORA</strong>
          <span className="brand-ver">v0.1</span>
          <span className="brand-sep">|</span>
          <span className={`fixture-tag ${scene.realtimeMode ? "is-realtime" : ""}`}>
            COCKPIT · {scene.realtimeMode ? "REALTIME" : "FIXTURE"}
          </span>
        </div>
        <span className="brand-tagline">AI-DRIVEN CRYPTO ALLOCATION</span>
      </div>

      <div className="global-bar-metrics-row">
        <div className="global-metric-block nav-block">
          <span className="metric-label">BTC NAV</span>
          <div className="nav-combo">
            {navObj?.value != null ? (
              <>
                <strong className="nav-value">{navObj.value} BTC</strong>
                {navObj.cap ? <CapBadge cap={navObj.cap} /> : null}
              </>
            ) : (
              <strong className="val-unknown">BTC NAV UNKNOWN</strong>
            )}
            {hodlObj?.value != null ? (
              <span className={`hodl-chip ${hodlObj.positive ? "is-up" : ""}`}>
                ▲ {hodlObj.value} vs HODL
              </span>
            ) : (
              <span className="val-unknown">vs HODL NOT AVAILABLE</span>
            )}
          </div>
        </div>

        <div className="global-metric-block">
          <span className="metric-label">ACTUAL ASSET MIX</span>
          {actualMixKnown ? (
            <strong className="mix-value">
              BTC {actualValues.btc} <span className="mix-sep">/</span> ETH {actualValues.eth}{" "}
              <span className="mix-sep">/</span> USDT {actualValues.usdt}
            </strong>
          ) : (
            <strong className="val-unknown">UNKNOWN</strong>
          )}
        </div>

        <div className="global-metric-block">
          <span className="metric-label">TARGET ALLOCATION</span>
          {targetMix?.percent != null ? (
            <strong className="mix-value">
              BTC {targetMix.percent.btc}% <span className="mix-sep">/</span> ETH {targetMix.percent.eth}%{" "}
              <span className="mix-sep">/</span> USDT {targetMix.percent.usdt}%
            </strong>
          ) : (
            <strong className="val-unknown">UNKNOWN · P3 HOLD</strong>
          )}
        </div>

        <div className="global-metric-block">
          <span className="metric-label">风险状态</span>
          <div className="risk-row">
            <strong>
              {riskProxy ? `${riskProxy.label} · ${riskProxy.value}` : "TOTAL RISK UNKNOWN"}
            </strong>
            {isValidNumber(g.riskPct) ? (
              <span className="risk-bar" aria-hidden="true">
                <span className="risk-bar-fill" style={{ width: `${g.riskPct}%` }} />
              </span>
            ) : null}
          </div>
        </div>

        <div className="global-metric-block exec-block">
          <span className="metric-label">执行状态</span>
          <div className="exec-badges">
            <ExecBadge label={`LOCK ${gov.incidentLock === "INCIDENT_LOCKED" ? "ACTIVE" : "OFF"}`} tone="outline" />
            <ExecBadge label={`KILL ${gov.kill}`} tone="outline" />
            <ExecBadge label={`EXECUTE ${gov.executeAuthorized ? "ON" : "DENIED"}`} tone="solid" />
            <ExecBadge label={`TRADING ${gov.live.replace("_", "-")}`} tone="solid" />
          </div>
        </div>
      </div>

      <p className="global-bar-meta">
        <span className="meta-tag">{scene.realtimeMode ? "OBSERVATORY" : "STATIC SNAPSHOT"}</span>
        {formatStamp(scene.asOf || gov.capturedAt)} · {gov.sourceCommit}
        <span className="meta-sep">·</span>
        <span className={scene.connected ? "ws-up" : "ws-down"}>
          WS {scene.connected ? "CONNECTED" : "已断开"}
        </span>
        <span className="meta-sep">·</span>
        {scene.realtimeMode ? "REALTIME FEED · READ ONLY · EXECUTION DENIED · TRADING NO-GO" : "ZERO FEED"}
      </p>
    </header>
  );
}

function EventMirror({ mirror }) {
  if (!mirror?.rows?.length) return null;
  return (
    <dl className="trend-mirror event-mirror">
      {mirror.rows.map(({ label, value, unknown }) => (
        <div key={label} className="trend-mirror-row">
          <dt>{label}</dt>
          <dd className={unknown ? "val-unknown" : ""}>{value}</dd>
        </div>
      ))}
      {mirror.whyNot ? (
        <div className="eth-btc-why-not">
          <span className="why-not-label">为什么</span>
          <span className="why-not-value val-unknown">{mirror.whyNot}</span>
        </div>
      ) : null}
    </dl>
  );
}

function DecisionMirror({ mirror }) {
  if (!mirror?.rows?.length) return null;
  return (
    <dl className="trend-mirror decision-mirror">
      {mirror.rows.map(({ label, value, unknown }) => (
        <div key={label} className="trend-mirror-row">
          <dt>{label}</dt>
          <dd className={unknown ? "val-unknown" : ""}>{value}</dd>
        </div>
      ))}
      {mirror.whyNot ? (
        <div className="eth-btc-why-not">
          <span className="why-not-label">为什么不能执行</span>
          <span className="why-not-value val-unknown">{mirror.whyNot}</span>
        </div>
      ) : null}
    </dl>
  );
}

function PortfolioDecisionPanel({ detail }) {
  if (!detail?.finalView) {
    return (
      <ChartUnavailable label="DECISION PENDING" detail="REALTIME · waiting for observatory decision bundle" />
    );
  }

  const trace = detail.why?.decisionTrace || [];
  const cluster = detail.why?.cryptoBetaCluster || {};
  const eventInc = detail.why?.eventIncrement || {};
  const auth = detail.authority || {};

  return (
    <div className="event-evidence portfolio-decision-evidence">
      <h4 className="event-evidence-title">{detail.title || "PORTFOLIO DECISION"}</h4>

      <section className="evidence-block">
        <h5>① FINAL VIEW</h5>
        <dl className="evidence-dl">
          <div><dt>Decision State</dt><dd>{detail.finalView.decisionState || "—"}</dd></div>
          <div><dt>Target Status</dt><dd>{detail.finalView.targetStatus || "—"}</dd></div>
          <div><dt>Delta Status</dt><dd className={detail.finalView.deltaStatus === "UNAVAILABLE" ? "val-unknown" : ""}>{detail.finalView.deltaStatus || "—"}</dd></div>
          <div><dt>Primary Blocker</dt><dd className={detail.finalView.primaryBlocker ? "val-unknown" : ""}>{detail.finalView.primaryBlocker || "—"}</dd></div>
          <div><dt>Decision Key</dt><dd>{detail.finalView.decisionKey || "—"}</dd></div>
          <div><dt>As Of</dt><dd>{formatStamp(detail.finalView.asOf)}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>② CURRENT</h5>
        <dl className="evidence-dl">
          <div><dt>Mix</dt><dd className={detail.current?.truthStatus === "UNKNOWN" ? "val-unknown" : ""}>{detail.current?.mix || "UNKNOWN"}</dd></div>
          <div><dt>BTC Overlay</dt><dd>{detail.current?.btcOverlay ?? "—"}</dd></div>
          <div><dt>ETH Overlay</dt><dd>{detail.current?.ethOverlay ?? "—"}</dd></div>
          <div><dt>Truth Status</dt><dd>{detail.current?.truthStatus || "UNKNOWN"}</dd></div>
          <div><dt>Account Version</dt><dd>{detail.current?.accountVersion || "—"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>③ TARGET CANDIDATE</h5>
        <dl className="evidence-dl">
          <div><dt>Mix</dt><dd>{detail.targetCandidate?.mix || "—"}</dd></div>
          <div><dt>BTC Overlay</dt><dd>{detail.targetCandidate?.btcOverlay ?? "—"}</dd></div>
          <div><dt>ETH Overlay</dt><dd>{detail.targetCandidate?.ethOverlay ?? "—"}</dd></div>
          <div><dt>Event Increment</dt><dd>{detail.targetCandidate?.eventIncrement ?? "—"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>④ DELTA PROPOSAL</h5>
        <dl className="evidence-dl">
          <div><dt>Summary</dt><dd>{detail.deltaProposal?.summary || detail.deltaProposal?.status || "UNAVAILABLE"}</dd></div>
          <div><dt>Status</dt><dd className={detail.deltaProposal?.status === "UNAVAILABLE" ? "val-unknown" : ""}>{detail.deltaProposal?.status || "—"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>⑤ WHY · DECISION TRACE</h5>
        {trace.length ? (
          <dl className="evidence-dl decision-trace">
            {trace.map((row) => (
              <div key={row.stage}>
                <dt>{row.stage}</dt>
                <dd>
                  {row.status}
                  {row.detail ? ` · ${row.detail}` : ""}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {detail.why?.traceWinner ? (
          <p className="evidence-note">Precedence winner: P2 DEFENSIVE OVERRIDE &gt; P4 TREND ENHANCEMENT</p>
        ) : null}
        <dl className="evidence-dl">
          <div><dt>CRYPTO BETA CLUSTER</dt><dd>{cluster.combinedState || "NONE"}</dd></div>
          <div><dt>BTC Overlay Request</dt><dd>{cluster.btcRequest ?? "—"}</dd></div>
          <div><dt>ETH Overlay Request</dt><dd>{cluster.ethRequest ?? "—"}</dd></div>
          <div><dt>Independent Full Budgets</dt><dd>{cluster.independentFullBudgets || "NOT ALLOWED"}</dd></div>
        </dl>
        <dl className="evidence-dl">
          <div><dt>Base Trend Risk</dt><dd>{eventInc.baseTrendRisk || "NONE"}</dd></div>
          <div><dt>Event Increment Request</dt><dd>{eventInc.incrementRequest || "NONE"}</dd></div>
          <div><dt>Final Risk Amount</dt><dd>{eventInc.finalRiskAmount || "NOT DECIDED"}</dd></div>
        </dl>
        {detail.why?.blockers?.length ? (
          <p className="evidence-blockers"><strong>Blockers</strong> {detail.why.blockers.join(" · ")}</p>
        ) : null}
        {detail.why?.reasons?.length ? (
          <p className="evidence-reasons"><strong>Reasons</strong> {detail.why.reasons.join(" · ")}</p>
        ) : null}
      </section>

      <section className="evidence-block">
        <h5>⑥ AUTHORITY</h5>
        <dl className="evidence-dl">
          <div><dt>RiskGate</dt><dd>{auth.riskgate || "NOT APPLIED"}</dd></div>
          <div><dt>Execution</dt><dd>{auth.execution || "DENIED"}</dd></div>
          <div><dt>submit_allowed</dt><dd className="val-unknown">{auth.submitAllowed ? "TRUE" : "FALSE"}</dd></div>
        </dl>
      </section>

      <footer className="event-source-footer">
        TARGET ≠ ORDER · DELTA ≠ EXECUTION · READ ONLY · P3-R3 HOLD
      </footer>
    </div>
  );
}

function EthBtcMirror({ mirror }) {
  if (!mirror?.rows?.length) return null;
  return (
    <dl className="trend-mirror eth-btc-mirror">
      {mirror.rows.map(({ label, value, unknown }) => (
        <div key={label} className="trend-mirror-row">
          <dt>{label}</dt>
          <dd className={unknown ? "val-unknown" : ""}>{value}</dd>
        </div>
      ))}
      {mirror.whyNot ? (
        <div className="eth-btc-why-not">
          <span className="why-not-label">为什么还不换</span>
          <span className="why-not-value val-unknown">{mirror.whyNot}</span>
        </div>
      ) : null}
    </dl>
  );
}

function fmtEvidenceNum(n, digits = 6) {
  const v = n == null ? null : Number(n);
  return fmtNumber(isValidNumber(v) ? v : null, digits);
}

function EthBtcEvidencePanel({ rv }) {
  if (!rv?.current) return null;
  const sig = rv.current.allocationSignal || "—";
  const sigLabel = String(sig).replace(/_/g, " ");
  const statusUnknown = rv.unknown;
  const statusStale = rv.stale;

  return (
    <div className="eth-btc-evidence">
      <h4 className="eth-btc-evidence-title">ETH/BTC RELATIVE VALUE</h4>

      <section className="evidence-block">
        <h5>① CURRENT</h5>
        <dl className="evidence-dl">
          <div><dt>Ratio</dt><dd className={statusUnknown ? "val-unknown" : ""}>{fmtEvidenceNum(rv.current.ratio)}</dd></div>
          <div><dt>Value Zone</dt><dd className={statusUnknown ? "val-unknown" : ""}>{rv.current.valueZone?.replace(/_/g, " ") || "UNKNOWN"}</dd></div>
          <div><dt>Allocation State</dt><dd>{rv.current.allocationState?.replace(/_/g, " ") || "—"}</dd></div>
          <div><dt>Allocation Signal</dt><dd className={sig === "NO_REALLOCATION" ? "val-unknown" : ""}>{sigLabel}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>② HISTORICAL COORDINATES</h5>
        <dl className="evidence-dl">
          <div><dt>Historical Low</dt><dd>{fmtEvidenceNum(rv.historical?.low)}</dd></div>
          <div><dt>Historical High</dt><dd>{fmtEvidenceNum(rv.historical?.high)}</dd></div>
          <div><dt>Historical Mean</dt><dd>{fmtEvidenceNum(rv.historical?.mean)}</dd></div>
          <div><dt>Historical Percentile</dt><dd>{fmtPercent(rv.historical?.percentile, 1)}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>③ KNOWN CYCLE</h5>
        <dl className="evidence-dl">
          <div><dt>Known Low</dt><dd>{fmtEvidenceNum(rv.cycle?.low)}</dd></div>
          <div><dt>Known High</dt><dd>{fmtEvidenceNum(rv.cycle?.high)}</dd></div>
          <div><dt>Known-range Position</dt><dd>{fmtPercent(rv.cycle?.knownRange, 0)}</dd></div>
        </dl>
        <p className="evidence-note">Known-range only · no future peak progress</p>
      </section>

      <section className="evidence-block">
        <h5>④ RELATIVE DYNAMICS</h5>
        <dl className="evidence-dl">
          <div><dt>Relative Trend</dt><dd>{rv.dynamics?.relativeTrend || "—"}</dd></div>
          <div><dt>Relative Momentum</dt><dd>{rv.dynamics?.relativeMomentum || "—"}</dd></div>
          <div><dt>BTC vs ETH RS</dt><dd>{rv.dynamics?.relativeStrength || "—"}</dd></div>
        </dl>
        {rv.dynamics?.reasons?.length ? (
          <p className="evidence-reasons"><strong>Reasons</strong> {rv.dynamics.reasons.join(" · ")}</p>
        ) : null}
        {rv.dynamics?.blockers?.length ? (
          <p className="evidence-blockers"><strong>Blockers</strong> {rv.dynamics.blockers.join(" · ")}</p>
        ) : null}
      </section>

      {statusStale ? (
        <p className="val-stale evidence-stale">
          STALE · last as_of {formatStamp(rv.asOf)} · BLOCK NEW REALLOCATION
        </p>
      ) : null}

      <footer className="eth-btc-source-footer">
        SOURCE: {rv.source || "SYNTHETIC_USDT_RATIO"}
        <br />
        RESEARCH / ALLOCATION RATIO · NOT EXECUTABLE ETHBTC PRICE
      </footer>
    </div>
  );
}

function TrendMirror({ mirror }) {
  if (!mirror) return null;
  return (
    <dl className="trend-mirror">
      {mirror.structures?.map(({ label, value }) => (
        <div key={label} className="trend-mirror-row">
          <dt>{label}</dt>
          <dd className={value === "UNKNOWN" || value === "—" ? "val-unknown" : ""}>{value}</dd>
        </div>
      ))}
      <div className="trend-mirror-row">
        <dt>{mirror.relativeLabel || "Relative"}</dt>
        <dd>{mirror.relative}</dd>
      </div>
      <div className="trend-mirror-row">
        <dt>Funding</dt>
        <dd className={mirror.funding === "UNKNOWN" ? "val-unknown" : ""}>
          {mirror.funding}
          {mirror.fundingRate != null ? ` · ${fmtPercent(mirror.fundingRate, 4)}` : ""}
        </dd>
      </div>
      <div className="trend-mirror-row trend-mirror-eligibility">
        <dt>Eligibility</dt>
        <dd className={mirror.eligibility?.includes("BLOCK") ? "val-unknown" : ""}>{mirror.eligibility}</dd>
      </div>
    </dl>
  );
}

function EventEvidencePanel({ ev }) {
  if (ev.disconnected) {
    return (
      <div className="event-evidence">
        <h4 className="event-evidence-title">EVENT INTELLIGENCE</h4>
        <p className="val-unknown event-source-banner">OFFICIAL EVENT SOURCES · NOT CONNECTED</p>
        <p className="evidence-note">Event State UNKNOWN · No action eligibility</p>
        <footer className="event-source-footer">READ ONLY · ELIGIBLE ≠ ACTIVE · EXECUTION DENIED</footer>
      </div>
    );
  }
  if (ev.sourceError) {
    return (
      <div className="event-evidence">
        <h4 className="event-evidence-title">EVENT INTELLIGENCE</h4>
        <p className="val-unknown event-source-banner">SOURCE ERROR · EVENT TRUTH UNKNOWN</p>
        <p className="evidence-note">NO NEW BOOST · fetch failure ≠ calm market</p>
        <footer className="event-source-footer">READ ONLY · EXECUTION DENIED</footer>
      </div>
    );
  }
  if (ev.noEvent || (ev.observationState === "NO_EVENT_OBSERVED" && !ev.primaryEventId)) {
    return (
      <div className="event-evidence">
        <h4 className="event-evidence-title">EVENT INTELLIGENCE</h4>
        <p className="event-source-banner">SOURCE HEALTH OK · NO EVENT OBSERVED</p>
        <p className="evidence-note">DECISION EVENTS NONE</p>
        <footer className="event-source-footer">READ ONLY · OFFICIAL INGESTION CONNECTED</footer>
      </div>
    );
  }

  const grade = ev.evidence?.evidence_grade || "—";
  const fmtImpact = (dir, imp) => {
    if (dir == null && imp == null) return "—";
    if (imp === "UNKNOWN") return "UNKNOWN";
    const sign = typeof imp === "number" && imp >= 0 ? "+" : "";
    return `${dir || "—"} · ${sign}${imp ?? "—"}`;
  };

  return (
    <div className="event-evidence">
      <h4 className="event-evidence-title">EVENT INTELLIGENCE</h4>

      <section className="evidence-block">
        <h5>① WHAT HAPPENED</h5>
        <dl className="evidence-dl">
          <div><dt>Event Class</dt><dd>{ev.whatHappened?.event_class || "—"}</dd></div>
          <div><dt>Factual Claim</dt><dd>{ev.whatHappened?.factual_claim || "—"}</dd></div>
          <div><dt>Policy Stage</dt><dd>{ev.whatHappened?.policy_stage || "—"}</dd></div>
          <div><dt>First Observed</dt><dd>{formatStamp(ev.whatHappened?.first_observed_at)}</dd></div>
          <div><dt>Latest Revision</dt><dd>{ev.whatHappened?.latest_revision ?? "—"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>② EVIDENCE</h5>
        <dl className="evidence-dl">
          <div><dt>Evidence Grade</dt><dd>{grade}</dd></div>
          <div><dt>Primary Source</dt><dd>{ev.evidence?.primary_source || "—"}</dd></div>
          <div><dt>Independent Clusters</dt><dd>{ev.evidence?.independent_clusters ?? "—"}</dd></div>
          <div><dt>Retracted</dt><dd className={ev.evidence?.retracted ? "val-unknown" : ""}>{ev.evidence?.retracted ? "YES" : "NO"}</dd></div>
          <div><dt>Surprise</dt><dd className={ev.evidence?.surprise == null ? "val-unknown" : ""}>{ev.evidence?.surprise ?? "UNKNOWN"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>③ IMPACT</h5>
        <dl className="evidence-dl">
          <div><dt>BTC</dt><dd>{fmtImpact(ev.impact?.btc_direction, ev.impact?.btc_impact)}</dd></div>
          <div><dt>ETH</dt><dd>{fmtImpact(ev.impact?.eth_direction, ev.impact?.eth_impact)}</dd></div>
        </dl>
        {ev.impact?.transmission_path?.length ? (
          <p className="evidence-reasons"><strong>Transmission</strong> {ev.impact.transmission_path.join(" · ")}</p>
        ) : null}
      </section>

      <section className="evidence-block">
        <h5>④ MARKET RESPONSE</h5>
        <dl className="evidence-dl">
          <div><dt>Anchor</dt><dd>{formatStamp(ev.marketResponse?.anchor_time)}</dd></div>
          <div><dt>Priced-in</dt><dd>{ev.marketResponse?.priced_in || "UNKNOWN"}</dd></div>
          <div><dt>Chase Distance</dt><dd>{ev.marketResponse?.chase_distance ?? "—"}</dd></div>
          <div><dt>Trend Alignment</dt><dd>{ev.marketResponse?.trend_alignment || "—"}</dd></div>
        </dl>
      </section>

      <section className="evidence-block">
        <h5>⑤ ACTION ELIGIBILITY</h5>
        <dl className="evidence-dl">
          <div><dt>Action State</dt><dd>{ev.actionEligibility?.action_state || "—"}</dd></div>
          <div><dt>Boost Eligibility</dt><dd>{ev.actionEligibility?.boost_eligibility || "—"}</dd></div>
        </dl>
        {ev.actionEligibility?.blockers?.length ? (
          <p className="evidence-blockers"><strong>Blockers</strong> {ev.actionEligibility.blockers.join(" · ")}</p>
        ) : null}
      </section>

      <footer className="event-source-footer">
        ELIGIBLE ≠ ACTIVE · READ ONLY · P3 HOLD
        {ev.footer?.no_short ? ` · ${ev.footer.no_short}` : ""}
      </footer>
    </div>
  );
}

function LeftCard({
  id,
  index,
  title,
  subtitle,
  cap,
  statusDot,
  lines,
  meta,
  evidence,
  disclaimer,
  trendMirror,
  ethBtcMirror,
  eventMirror,
  decisionMirror,
  active,
  emphasis,
  onSelect,
}) {
  return (
    <button
      type="button"
      className={`left-card ${active ? "is-active" : ""} ${emphasis ? "is-final" : ""}`}
      onClick={() => onSelect?.(id)}
      aria-pressed={active}
    >
      <div className="left-card-head">
        <span className="left-card-index">{index}</span>
        <div className="left-card-titles">
          <span className="left-card-title">{title}</span>
          <span className="left-card-sub">{subtitle}</span>
        </div>
        <CapBadge cap={cap} />
      </div>
      <div className="left-card-body">
        <StatusDot kind={statusDot} />
        <div className="left-card-content">
          {lines.map((line, i) => (
            <strong key={`${line}-${i}`} className={`left-card-line ${i === 0 ? "line-primary" : ""}`}>
              {line}
            </strong>
          ))}
          <TrendMirror mirror={trendMirror} />
          <EthBtcMirror mirror={ethBtcMirror} />
          <EventMirror mirror={eventMirror} />
          <DecisionMirror mirror={decisionMirror} />
          {meta?.length ? (
            <span className="left-card-meta">
              {meta.map((m) => (
                <MetaChip key={m} label={m} />
              ))}
            </span>
          ) : null}
          {evidence ? <span className="left-card-evidence">{evidence}</span> : null}
          {disclaimer ? <span className="left-card-disclaimer">{disclaimer}</span> : null}
        </div>
      </div>
    </button>
  );
}

export function DecisionBrain({ scene, focus, onCardSelect }) {
  const d = scene.decisions;

  const cards = [
    {
      id: "btc",
      ...d.btcTrend,
      lines: [d.btcTrend.headline],
      meta: d.btcTrend.meta,
      evidence: d.btcTrend.evidence,
    },
    {
      id: "eth",
      ...d.ethTrend,
      lines: [d.ethTrend.headline],
      meta: d.ethTrend.meta,
      evidence: d.ethTrend.evidence,
    },
    {
      id: "ethbtc",
      ...d.ethBtc,
      lines: d.ethBtc.headlines || [d.ethBtc.headline],
      ethBtcMirror: d.ethBtc.mirror,
      meta: d.ethBtc.meta,
      evidence: d.ethBtc.evidence,
      disclaimer: d.ethBtc.disclaimer,
    },
    {
      id: "event",
      ...d.event,
      lines: d.event.headlines || [d.event.headline],
      meta: d.event.meta,
      evidence: d.event.evidence,
      disclaimer: d.event.disclaimer,
      eventMirror: d.event.mirror,
    },
    {
      id: "final",
      ...d.finalDecision,
      lines: d.finalDecision.headlines || [d.finalDecision.headline],
      decisionMirror: d.finalDecision.mirror,
      meta: d.finalDecision.meta,
      evidence: d.finalDecision.evidence,
      disclaimer: d.finalDecision.disclaimer,
      emphasis: true,
    },
  ];

  return (
    <aside className="decision-sidebar">
      <header className="sidebar-head">
        <h2>决策总览</h2>
        <span>Decision Overview</span>
      </header>
      <div className="decision-brain">
        {cards.map((c) => (
          <LeftCard key={c.id} {...c} active={focus === c.id} onSelect={onCardSelect} />
        ))}
      </div>
    </aside>
  );
}

function TfPills({ value, onChange }) {
  return (
    <span className="tf-pills" role="group" aria-label="周期">
      {["3m", "1H", "4H", "1D"].map((tf) => (
        <button
          key={tf}
          type="button"
          className={`tf-pill ${value === tf ? "is-active" : ""}`}
          onClick={() => onChange(tf)}
        >
          {tf}
        </button>
      ))}
    </span>
  );
}

function MetricRow({ items }) {
  return (
    <dl className="metric-row">
      {items.map(({ label, value, unknown }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={unknown ? "val-unknown" : ""}>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

function PanelWarning({ text }) {
  if (!text) return null;
  return (
    <p className="panel-warning">
      <span className="warn-icon" aria-hidden="true">
        ⚠
      </span>
      {text}
    </p>
  );
}

function PanelTitle({ title, status, statusUnknown }) {
  return (
    <div className="panel-title-block">
      <h3>{title}</h3>
      {status ? (
        <span className={`panel-status ${statusUnknown ? "val-unknown" : ""}`}>{status}</span>
      ) : null}
    </div>
  );
}

function resolveTrendChart(chart, tf, realtimeMode) {
  if (realtimeMode) {
    const slot = chart.klinesByTf?.[tf];
    if (slot?.connected && slot.klines?.length) {
      return {
        candles: normalizeKlines(slot.klines, tf),
        fixture: false,
        unavailable: false,
      };
    }
    const partial = tf === "1D" && chart.klinesByTf?.["1D"]?.status === "ok";
    return {
      candles: [],
      fixture: false,
      unavailable: true,
      unavailableLabel: partial ? "PARTIAL" : "NOT CONNECTED",
      unavailableDetail: "REALTIME · synthetic forbidden",
    };
  }
  const liveTf = chart.timeframe || DEFAULT_TF;
  if (tf === liveTf && chart.klines?.length) {
    return { candles: normalizeKlines(chart.klines, tf), fixture: false, unavailable: false };
  }
  return {
    candles: genCandles(
      chart.chartSeed || 1,
      chart.chartBase || chart.price || 118500,
      chart.chartVol || 1200,
      tf,
    ),
    fixture: true,
    unavailable: false,
  };
}

export function AnalysisRow({ scene, focus }) {
  const btc = scene.btcChart;
  const eth = scene.ethChart;
  const rv = scene.ethBtcChart;
  const realtimeMode = Boolean(scene.realtimeMode);
  const [btcTf, setBtcTf] = useState(btc.timeframe || DEFAULT_TF);
  const [ethTf, setEthTf] = useState(eth.timeframe || DEFAULT_TF);

  const btcResolved = useMemo(
    () => resolveTrendChart(btc, btcTf, realtimeMode),
    [btc, btcTf, realtimeMode],
  );
  const ethResolved = useMemo(
    () => resolveTrendChart(eth, ethTf, realtimeMode),
    [eth, ethTf, realtimeMode],
  );
  const rvLine = useMemo(
    () => (realtimeMode || rv?.current ? [] : genLine(rv.chartSeed || 3, 48, 0.042)),
    [rv, realtimeMode],
  );
  const rvHasEvidence = Boolean(rv?.current);
  const rvSignal = rv?.current?.allocationSignal || rv?.signal;

  return (
    <div className="analysis-row">
      <section className={`panel trend-panel ${focus === "btc" ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <PanelTitle
            title="BTC 趋势"
            status={btc.status === "unknown" ? `UNKNOWN · ${btc.level}` : btc.level}
            statusUnknown={btc.status === "unknown"}
          />
          <TfPills value={btcTf} onChange={setBtcTf} />
        </header>
        {btcResolved.unavailable ? (
          <ChartUnavailable label={btcResolved.unavailableLabel} detail={btcResolved.unavailableDetail} />
        ) : (
          <CandlestickChart
            data={btcResolved.candles}
            timeframe={btcTf}
            fixture={btcResolved.fixture || btc.status !== "ok" || btc.fixture === true}
          />
        )}
        <MetricRow
          items={[
            { label: "Latest Price", value: btc.metrics?.price, unknown: !btc.metrics?.price || btc.metrics?.price === "—" },
            { label: "EMA20", value: btc.metrics?.ema20, unknown: !btc.metrics?.ema20 || btc.metrics?.ema20 === "—" },
            { label: "EMA60", value: btc.metrics?.ema60, unknown: !btc.metrics?.ema60 || btc.metrics?.ema60 === "—" },
            { label: "ADX", value: btc.metrics?.adx, unknown: !btc.metrics?.adx || btc.metrics?.adx === "—" },
          ]}
        />
        <PanelWarning text={btc.warning || btc.structure} />
      </section>

      <section className={`panel trend-panel ${focus === "eth" ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <PanelTitle
            title="ETH 趋势"
            status={eth.status === "unknown" ? `UNKNOWN · ${eth.level}` : eth.level}
            statusUnknown={eth.status === "unknown"}
          />
          <TfPills value={ethTf} onChange={setEthTf} />
        </header>
        {ethResolved.unavailable ? (
          <ChartUnavailable label={ethResolved.unavailableLabel} detail={ethResolved.unavailableDetail} />
        ) : (
          <CandlestickChart
            data={ethResolved.candles}
            timeframe={ethTf}
            fixture={ethResolved.fixture || eth.status !== "ok" || eth.fixture === true}
          />
        )}
        <MetricRow
          items={[
            { label: "Latest Price", value: eth.metrics?.price, unknown: !eth.metrics?.price || eth.metrics?.price === "—" },
            { label: "EMA20", value: eth.metrics?.ema20, unknown: !eth.metrics?.ema20 || eth.metrics?.ema20 === "—" },
            { label: "EMA60", value: eth.metrics?.ema60, unknown: !eth.metrics?.ema60 || eth.metrics?.ema60 === "—" },
            { label: "ADX", value: eth.metrics?.adx, unknown: !eth.metrics?.adx || eth.metrics?.adx === "—" },
          ]}
        />
        <PanelWarning text={eth.warning} />
      </section>

      <section className={`panel rv-panel eth-btc-panel ${focus === "ethbtc" ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <PanelTitle
            title="ETH/BTC 相对价值"
            status={
              rv.unknown
                ? "VALUE UNKNOWN"
                : rv.stale
                  ? "STALE"
                  : String(rvSignal || "—").replace(/_/g, " ")
            }
            statusUnknown={rv.unknown || rv.stale}
          />
          <CapBadge cap={rv.capability} />
        </header>
        {rvHasEvidence ? (
          <EthBtcEvidencePanel rv={rv} />
        ) : realtimeMode ? (
          <ChartUnavailable label="VALUE TRUTH PENDING" detail="REALTIME · waiting for observatory eth_btc" />
        ) : (
          <>
            <LineChart data={rvLine} muted={rv.status === "unknown"} />
            <MetricRow
              items={[
                { label: "Current", value: rv.metrics?.current, unknown: rv.status === "unknown" },
                { label: "Percentile", value: rv.metrics?.percentile, unknown: rv.status === "unknown" },
                { label: "Velocity", value: rv.metrics?.velocity, unknown: rv.status === "unknown" },
              ]}
            />
          </>
        )}
        {!rvHasEvidence ? <PanelWarning text={rv.warning} /> : null}
      </section>
    </div>
  );
}

export function OperationsRow({ scene, focus }) {
  const ev = scene.eventDetail;
  const decision = scene.decisionDetail;
  const hasEventEvidence = Boolean(
    ev?.whatHappened?.event_class || ev?.disconnected || ev?.sourceError || ev?.message,
  );
  const hasDecisionEvidence = Boolean(decision?.finalView?.decisionState || decision?.finalView?.targetStatus);
  const cap = scene.capital;
  const perf = scene.performance;
  const finalHighlight = focus === "final";
  const realtimeMode = Boolean(scene.realtimeMode);

  const perfData = useMemo(() => genPerf(perf.chartSeed || 99), [perf.chartSeed]);
  const actualValues = cap.actualMix?.values ?? cap.wallet;
  const targetUnknown = cap.targetMix?.percent == null;

  return (
    <div className="operations-row">
      <section className={`panel ops-panel event-panel ${focus === "event" ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <h3>事件情报</h3>
          <CapBadge cap={ev.capability} />
        </header>
        {hasEventEvidence ? (
          <EventEvidencePanel ev={ev} />
        ) : (
          <ChartUnavailable label="EVENT PENDING" detail="REALTIME · waiting for observatory event bundle" />
        )}
      </section>

      <section className={`panel ops-panel capital-panel ${finalHighlight ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <h3>{finalHighlight && hasDecisionEvidence ? "Portfolio Decision" : "资本 / 钱包 / 仓位"}</h3>
          <CapBadge cap={hasDecisionEvidence ? decision.capability : cap.capability} />
        </header>
        {hasDecisionEvidence ? (
          <PortfolioDecisionPanel detail={decision} />
        ) : null}
        <div className="capital-grid">
          <div className="wallet-block">
            <h4 className="section-sub">钱包资产</h4>
            <table className="wallet-table">
              <tbody>
                <tr>
                  <th>USDT</th>
                  <td className={cap.wallet?.usdt === "—" ? "val-unknown" : ""}>{cap.wallet?.usdt ?? "—"}</td>
                </tr>
                <tr>
                  <th>BTC</th>
                  <td className={cap.wallet?.btc === "—" ? "val-unknown" : ""}>{cap.wallet?.btc ?? "—"}</td>
                </tr>
                <tr>
                  <th>ETH</th>
                  <td className={cap.wallet?.eth === "—" ? "val-unknown" : ""}>{cap.wallet?.eth ?? "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="alloc-block">
            <h4 className="section-sub">ACTUAL ASSET MIX</h4>
            <table className="wallet-table">
              <tbody>
                <tr>
                  <th>BTC</th>
                  <td className={actualValues?.btc == null ? "val-unknown" : ""}>{actualValues?.btc ?? "—"}</td>
                </tr>
                <tr>
                  <th>ETH</th>
                  <td className={actualValues?.eth == null ? "val-unknown" : ""}>{actualValues?.eth ?? "—"}</td>
                </tr>
                <tr>
                  <th>USDT</th>
                  <td className={actualValues?.usdt == null ? "val-unknown" : ""}>{actualValues?.usdt ?? "—"}</td>
                </tr>
              </tbody>
            </table>
            <h4 className="section-sub" style={{ marginTop: "1rem" }}>TARGET ALLOCATION</h4>
            {targetUnknown ? (
              <div className="val-unknown">UNKNOWN · P3 HOLD</div>
            ) : (
              <div>
                BTC {cap.targetMix.percent.btc}% · ETH {cap.targetMix.percent.eth}% · USDT {cap.targetMix.percent.usdt}%
              </div>
            )}
          </div>
        </div>
        <dl className="capital-meta">
          <div>
            <dt>杠杆</dt>
            <dd>{cap.perp ?? cap.leverage ?? "—"}</dd>
          </div>
          <div>
            <dt>风险额度</dt>
            <dd>{cap.riskBudget ?? "—"}</dd>
          </div>
          <div>
            <dt>持仓状态</dt>
            <dd className={cap.positions === "UNKNOWN" ? "val-unknown" : cap.positions === "FLAT" ? "val-flat" : ""}>
              {cap.positions ?? "—"}
            </dd>
          </div>
        </dl>
        <PanelWarning text={cap.warning || (cap.status === "stale" ? `STALE · ${formatStamp(cap.asOf)}` : null)} />
      </section>

      <section className={`panel ops-panel perf-panel ${finalHighlight ? "is-highlight" : ""}`}>
        <header className="panel-head">
          <h3>BTC 本位收益</h3>
          <CapBadge cap={perf.capability} />
        </header>
        <dl className="perf-metrics">
          <div>
            <dt>AURORA BTC NAV</dt>
            <dd className={perf.nav ? (perf.fixture ? "val-fixture" : "") : "val-unknown"}>
              {perf.nav ?? "UNKNOWN"}
            </dd>
          </div>
          <div>
            <dt>HODL Baseline</dt>
            <dd className={perf.hodl ? (perf.fixture ? "val-fixture" : "") : "val-unknown"}>{perf.hodl ?? "UNKNOWN"}</dd>
          </div>
          <div>
            <dt>Alpha (Excess BTC)</dt>
            <dd className={perf.excess ? "val-positive" : "val-unknown"}>{perf.excess ?? "—"}</dd>
          </div>
        </dl>
        {realtimeMode ? (
          <div className="chart-frame chart-empty">D2 HOLD · BTC NAV not authoritative</div>
        ) : perf.chartSeed || perf.fixture ? (
          <PerfChart data={perfData} fixture={perf.fixture} />
        ) : (
          <div className="chart-frame chart-empty">D2 HOLD · no chart</div>
        )}
        <PanelWarning text={perf.note} />
      </section>
    </div>
  );
}
