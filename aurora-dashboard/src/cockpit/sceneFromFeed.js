import { POLICY_SNAPSHOT } from "../policySnapshot";
import { CAP } from "./capability";
import { ethBtcEvidenceFromObservatory, ethBtcLeftFromObservatory } from "./ethBtcMirror";
import { decisionEvidenceFromObservatory, decisionLeftFromObservatory } from "./decisionMirror";
import { eventEvidenceFromObservatory, eventLeftFromObservatory } from "./eventMirror";

const LEFT_INDEX = {
  btcTrend: "01",
  ethTrend: "02",
  ethBtc: "03",
  event: "04",
  finalDecision: "05",
};

function dirToDot(dir) {
  if (dir === "BULL") return "bull";
  if (dir === "BEAR") return "bear";
  if (dir === "TRANSITION") return "partial";
  return "unknown";
}

function trendHeadline(dir, level, strength) {
  const direction = dir || "UNKNOWN";
  const lvl = level || "L0/5";
  if (direction === "UNKNOWN") return `方向不明确 · ${lvl}`;
  const tag = strength && strength !== "UNKNOWN" ? ` · ${strength}` : "";
  return `${direction} · ${lvl}${tag}`;
}

function riskFromExchange(exchange) {
  const rs = exchange?.risk_status;
  if (rs) {
    return { risk: { label: rs.label, value: rs.value, note: rs.note }, riskPct: null };
  }
  return { risk: "UNKNOWN", riskPct: null };
}

function governanceFromBundle(gov) {
  if (!gov) return POLICY_SNAPSHOT;
  return {
    kind: CAP.PARTIAL,
    capturedAt: gov.as_of || POLICY_SNAPSHOT.capturedAt,
    sourceCommit: gov.source_commit || POLICY_SNAPSHOT.sourceCommit,
    source: "dashboard_feed · observatory-v1",
    incidentLock: gov.incident_lock || POLICY_SNAPSHOT.incidentLock,
    kill: gov.kill || POLICY_SNAPSHOT.kill,
    executeAuthorized: Boolean(gov.execute_authorized),
    executionQualified: Boolean(gov.execution_qualified),
    autoTestnet: gov.auto_testnet || "DENIED",
    live: gov.live || "NO_GO",
    identity: POLICY_SNAPSHOT.identity,
  };
}

const ELIGIBILITY_LABEL = {
  ELIGIBLE: "LONG ELIGIBLE",
  WATCH: "WATCH",
  HOLD: "HOLD",
  BLOCK_NEW_RISK: "BLOCK NEW RISK",
  LONG_ELIGIBLE: "LONG ELIGIBLE",
  BLOCKED: "BLOCK NEW RISK",
};

function trendMirrorFromSnapshot(snapshot, rs, asset) {
  const relative = asset === "BTC" ? rs?.btc_vs_eth : rs?.eth_vs_btc;
  const rate = snapshot?.funding_rate;
  return {
    structures: [
      { label: "1D", value: snapshot?.daily_structure || "—" },
      { label: "4H", value: snapshot?.h4_structure || "—" },
      { label: "1H", value: snapshot?.h1_structure || "—" },
    ],
    relative: relative || "—",
    relativeLabel: asset === "BTC" ? "Relative" : "vs BTC",
    funding: snapshot?.funding_state || "UNKNOWN",
    fundingRate: rate == null ? null : rate,
    fundingFreshness: snapshot?.funding_freshness || "unknown",
    eligibility: ELIGIBILITY_LABEL[snapshot?.action_eligibility] || snapshot?.action_eligibility || "—",
    trendLevel: snapshot?.trend_level,
    trendStrength: snapshot?.trend_strength,
    blockers: snapshot?.blockers || [],
  };
}

function leftTrendCard(snapshot, rs, asset, capDefault) {
  const dir = snapshot?.trend_direction || snapshot?.dir;
  const level = snapshot?.trend_level || snapshot?.level;
  const mirror = trendMirrorFromSnapshot(snapshot, rs, asset);
  return {
    index: asset === "BTC" ? LEFT_INDEX.btcTrend : LEFT_INDEX.ethTrend,
    title: asset === "BTC" ? "BTC TREND" : "ETH TREND",
    subtitle: asset === "BTC" ? "BTC 趋势" : "ETH 趋势",
    cap: snapshot?.capability || capDefault,
    statusDot: dirToDot(dir),
    headline: trendHeadline(dir, level, snapshot?.trend_strength),
    level: level || "L0/5",
    trendMirror: mirror,
    meta: [mirror.eligibility],
    evidence:
      mirror.blockers.length > 0
        ? mirror.blockers.join(" · ")
        : snapshot?.evidence || "—",
  };
}

function chartFromTrendSnapshot(snapshot, chartBundle) {
  const tfs = chartBundle?.timeframes || snapshot?.timeframes || {};
  const klinesByTf = { ...tfs };
  const slot3m = tfs["3m"] || chartBundle || {};
  return {
    status: slot3m.status || snapshot?.freshness || "unknown",
    level: snapshot?.trend_level || snapshot?.level || "L0/5",
    timeframe: "3m",
    capability: snapshot?.capability || CAP.PARTIAL,
    price: slot3m.price,
    klines: slot3m.klines || [],
    klinesByTf,
    fixture: false,
    metrics: slot3m.metrics || {},
    warning:
      snapshot?.blockers?.length > 0
        ? snapshot.blockers.join(" · ")
        : snapshot?.evidence || null,
  };
}

function emptyObserveScene(connected) {
  return {
    id: "observe",
    label: "REALTIME",
    realtimeMode: true,
    connected,
    governance: POLICY_SNAPSHOT,
    global: {
      btcNav: null,
      vsHodl: null,
      mix: { btc: null, eth: null, usdt: null },
      risk: "UNKNOWN",
      riskPct: 0,
    },
    decisions: {
      btcTrend: {
        index: LEFT_INDEX.btcTrend,
        title: "BTC TREND",
        subtitle: "BTC 趋势",
        cap: CAP.UNKNOWN,
        statusDot: "unknown",
        headline: "等待 observatory feed…",
        level: "L0/5",
        meta: connected ? ["WS connected"] : ["WS 已断开"],
        evidence: connected ? "observatory pending" : "WebSocket disconnected",
      },
      ethTrend: {
        index: LEFT_INDEX.ethTrend,
        title: "ETH TREND",
        subtitle: "ETH 趋势",
        cap: CAP.UNKNOWN,
        statusDot: "unknown",
        headline: "等待 observatory feed…",
        level: "L0/5",
        meta: connected ? ["WS connected"] : ["WS 已断开"],
        evidence: connected ? "observatory pending" : "WebSocket disconnected",
      },
      ethBtc: ethBtcLeftFromObservatory(
        { ratio: null, value_zone: "UNKNOWN", blockers: ["VALUE_TRUTH_UNKNOWN"] },
        {},
      ),
      event: eventLeftFromObservatory({
        capability: CAP.READ_ONLY_SEMANTICS,
        observation_state: "SOURCE_NOT_CONNECTED",
        event_state: "UNKNOWN",
        official_source_ingestion: "NOT_CONNECTED",
        left_card: {
          headlines: ["等待 observatory feed…"],
          headline_action: "—",
          meta: connected ? ["WS connected"] : ["WS 已断开"],
        },
      }),
      finalDecision: decisionLeftFromObservatory({
        capability: "READ-ONLY-DECISION",
        left_card: {
          index: "05",
          title: "PORTFOLIO DECISION",
          subtitle: "统一资本判断",
          headlines: ["等待 observatory feed…"],
          delta_status: "UNAVAILABLE",
          target_status: "UNKNOWN",
          meta: connected ? ["WS connected"] : ["WS 已断开"],
        },
      }),
    },
    btcChart: {
      status: "unknown",
      level: "L0/5",
      timeframe: "3m",
      capability: CAP.UNKNOWN,
      klinesByTf: {},
      metrics: {},
      warning: connected ? "等待 observatory 数据" : "WebSocket 已断开",
    },
    ethChart: {
      status: "unknown",
      level: "L0/5",
      timeframe: "3m",
      capability: CAP.UNKNOWN,
      klinesByTf: {},
      metrics: {},
      warning: connected ? "等待 observatory 数据" : "WebSocket 已断开",
    },
    ethBtcChart: ethBtcEvidenceFromObservatory({
      ratio: null,
      value_zone: "UNKNOWN",
      blockers: ["VALUE_TRUTH_UNKNOWN"],
    }),
    eventDetail: eventEvidenceFromObservatory({
      capability: CAP.READ_ONLY_SEMANTICS,
      observation_state: "SOURCE_NOT_CONNECTED",
      status: "unknown",
    }),
    decisionDetail: null,
    capital: {
      status: "unknown",
      capability: CAP.UNKNOWN,
      wallet: { usdt: "—", btc: "—", eth: "—" },
      positions: "UNKNOWN",
      warning: "交易所观察不可用",
    },
    performance: {
      status: "unknown",
      capability: CAP.D2_HOLD,
      nav: null,
      hodl: null,
      note: "D2 HOLD · BTC NAV not authoritative",
    },
  };
}

/** Map WS observatory bundle → cockpit scene. Realtime data ≠ live trading. */
export function sceneFromFeed({ observatory, connected, marketMeta, accountMeta }) {
  if (!observatory?.schema) {
    return emptyObserveScene(connected);
  }

  const trend = observatory.trend_quant || {};
  const btc = trend.btc || {};
  const eth = trend.eth || {};
  const rs = trend.relative_strength || {};
  const charts = trend.charts || {};
  const ethBtc = observatory.eth_btc || {};
  const event = observatory.event || {};
  const decision = observatory.decision || {};
  const exchange = observatory.exchange_observation || {};
  const accounting = observatory.accounting || {};
  const gov = governanceFromBundle(observatory.governance);

  const accountStatus = accountMeta?.status || exchange.status || "unknown";
  const { risk, riskPct } = riskFromExchange(exchange);

  const actualMix = exchange.actual_mix || { values: null, percent: null, note: "Percentage requires price truth; raw wallet balances only" };
  const targetMix = exchange.target_mix || { percent: null, note: "Target allocation not available until P3" };

  return {
    id: "observe",
    label: "REALTIME",
    realtimeMode: true,
    connected,
    asOf: observatory.as_of,
    governance: gov,
    global: {
      btcNav: accounting.nav_btc
        ? { value: String(accounting.nav_btc), cap: "D2 HOLD" }
        : { value: null, cap: "D2 HOLD", note: "BTC NAV not authoritative" },
      vsHodl: accounting.excess_btc
        ? { value: accounting.excess_btc, cap: "D2 HOLD" }
        : { value: null, cap: "D2 HOLD", note: "vs HODL not available" },
      actualMix,
      targetMix,
      risk,
      riskPct,
    },
    decisions: {
      btcTrend: leftTrendCard(btc, rs, "BTC", CAP.PARTIAL),
      ethTrend: leftTrendCard(eth, rs, "ETH", CAP.PARTIAL),
      ethBtc: ethBtcLeftFromObservatory(ethBtc, eth),
      event: eventLeftFromObservatory(event),
      finalDecision: decisionLeftFromObservatory(decision),
    },
    btcChart: {
      ...chartFromTrendSnapshot(btc, charts.btc),
      asOf: observatory.as_of,
    },
    ethChart: chartFromTrendSnapshot(eth, charts.eth),
    ethBtcChart: ethBtcEvidenceFromObservatory(ethBtc),
    eventDetail: eventEvidenceFromObservatory(event),
    decisionDetail: decisionEvidenceFromObservatory(decision),
    capital: {
      status: accountStatus,
      capability: exchange.capability || CAP.PARTIAL,
      asOf: exchange.as_of,
      wallet: exchange.wallet || { usdt: "—", btc: "—", eth: "—" },
      actualMix,
      targetMix,
      perp: exchange.perp,
      leverage: exchange.leverage,
      positions: exchange.positions || (accountStatus === "unknown" ? "UNKNOWN" : "—"),
      riskBudget: exchange.risk_status?.value || "—",
      warning: exchange.warning,
    },
    performance: {
      status: accounting.status || "unknown",
      capability: accounting.capability || CAP.D2_HOLD,
      nav: accounting.nav_btc,
      hodl: accounting.hodl_btc,
      excess: accounting.excess_btc,
      note: accounting.note || "D2 HOLD · BTC NAV not authoritative",
    },
  };
}
