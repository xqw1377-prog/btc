/** P2-B.3 — Map observatory eth_btc payload → product language (display only, no FSM). */

const ZONE_LABEL = {
  DEEP_CHEAP_ETH: "DEEP CHEAP ETH",
  CHEAP_ETH: "CHEAP ETH",
  FAIR: "FAIR",
  EXPENSIVE_ETH: "EXPENSIVE ETH",
  EXTREME_EXPENSIVE_ETH: "EXTREME EXPENSIVE ETH",
  UNKNOWN: "VALUE TRUTH UNKNOWN",
};

const SIGNAL_LABEL = {
  HOLD_BTC: "HOLD BTC",
  WATCH_ETH: "WATCH ETH",
  INCREASE_ETH_ELIGIBLE: "INCREASE ETH ELIGIBLE",
  HOLD_ETH: "HOLD ETH",
  REDUCE_ETH_ELIGIBLE: "REDUCE ETH ELIGIBLE",
  RETURN_BTC_ELIGIBLE: "RETURN BTC ELIGIBLE",
  NO_REALLOCATION: "NO REALLOCATION",
};

const STATE_LABEL = {
  BTC_DEFAULT: "BTC DEFAULT",
  ETH_CANDIDATE: "ETH CANDIDATE",
  ETH_CONFIRMED: "ETH CONFIRMED",
  ETH_HOLD: "ETH HOLD",
  ETH_WEAKENING: "ETH WEAKENING",
  BTC_RETURN: "BTC RETURN",
};

function fmtPct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(Number(n) * 100).toFixed(0)}%`;
}

function cycleZoneLabel(knownRange) {
  if (knownRange == null) return "—";
  const p = Number(knownRange);
  if (p <= 0.33) return "LOW ZONE";
  if (p <= 0.66) return "MID ZONE";
  return "HIGH ZONE";
}

function rsRecoveryLabel(rs, relTrend) {
  const base = rs || "UNKNOWN";
  if (relTrend === "IMPROVING") return `${base} → RECOVERING`;
  if (relTrend === "WEAKENING") return `${base} → WEAKENING`;
  return base;
}

function whyNotSwitch(alloc, ethTrend) {
  const blockers = alloc?.blockers || [];
  const reasons = alloc?.reasons || [];
  if (blockers.includes("VALUE_TRUTH_UNKNOWN")) return "VALUE TRUTH UNKNOWN";
  if (blockers.includes("BLOCK_NEW_REALLOCATION")) return "VALUE DATA STALE";
  const ethLvl = ethTrend?.trend_level || ethTrend?.level || "";
  const lvlNum = parseInt(String(ethLvl).replace(/\D/g, "") || "0", 10);
  if (alloc?.state === "ETH_CANDIDATE" && lvlNum > 0 && lvlNum < 3) {
    return "ETH TREND NOT CONFIRMED";
  }
  const r = reasons.find((x) => /not confirmed|stale|unknown/i.test(x));
  return r ? r.toUpperCase().replace(/ — .*/, "") : null;
}

function statusDotFromSignal(signal, unknown) {
  if (unknown) return "unknown";
  if (signal === "INCREASE_ETH_ELIGIBLE") return "bull";
  if (signal === "WATCH_ETH") return "partial";
  if (signal?.includes("REDUCE") || signal === "RETURN_BTC_ELIGIBLE") return "bear";
  return "partial";
}

/** LEFT 03 card — product language first. */
export function ethBtcLeftFromObservatory(ethBtc, ethTrend) {
  const alloc = ethBtc?.allocation || {};
  const signal = alloc.allocation_signal || ethBtc?.signal || "NO_REALLOCATION";
  const state = alloc.state || "BTC_DEFAULT";
  const unknown =
    ethBtc?.ratio == null ||
    ethBtc?.value_zone === "UNKNOWN" ||
    (ethBtc?.blockers || []).includes("VALUE_TRUTH_UNKNOWN");
  const stale =
    ethBtc?.freshness === "stale" ||
    ethBtc?.data_quality === "stale" ||
    (alloc.blockers || []).includes("BLOCK_NEW_REALLOCATION");

  const zoneRaw = ethBtc?.value_zone || "UNKNOWN";
  const zoneLabel = ZONE_LABEL[zoneRaw] || zoneRaw.replace(/_/g, " ");
  const signalLabel = SIGNAL_LABEL[signal] || signal.replace(/_/g, " ");
  const stateLabel = STATE_LABEL[state] || state.replace(/_/g, " ");

  let headlines;
  let meta;
  let evidence;
  let disclaimer;

  if (unknown) {
    headlines = ["VALUE TRUTH UNKNOWN", signalLabel];
    meta = ["READ ONLY", "NO REALLOCATION"];
    evidence = whyNotSwitch(alloc, ethTrend) || "VALUE_TRUTH_UNKNOWN";
    disclaimer = null;
  } else if (stale) {
    headlines = [zoneLabel, stateLabel, signalLabel];
    meta = ["STALE · BLOCK NEW REALLOCATION", "READ ONLY"];
    evidence = ethBtc?.ratio != null ? `Last known ratio ${Number(ethBtc.ratio).toFixed(6)}` : "—";
    disclaimer = "STALE — not used as fresh allocation truth";
  } else if (signal === "INCREASE_ETH_ELIGIBLE") {
    headlines = [zoneLabel, stateLabel, signalLabel];
    meta = ["ELIGIBLE ≠ ORDER", "P3 DECISION BRAIN HOLD"];
    evidence = "Value + trend confirmed — eligibility only";
    disclaimer = "READ ONLY · NO EXECUTION";
  } else if (signal === "WATCH_ETH" || state === "ETH_CANDIDATE") {
    headlines = [zoneLabel, stateLabel, signalLabel];
    meta = ["READ ONLY", "NO REALLOCATION"];
    evidence = whyNotSwitch(alloc, ethTrend) ? `Why not yet: ${whyNotSwitch(alloc, ethTrend)}` : null;
    disclaimer = null;
  } else {
    headlines = [zoneLabel, stateLabel, signalLabel];
    meta = ["READ ONLY", signal === "NO_REALLOCATION" ? "NO REALLOCATION" : signalLabel];
    evidence = (alloc.reasons || []).slice(0, 1).join("") || ethBtc?.evidence;
    disclaimer = signal.includes("ELIGIBLE") ? "ELIGIBLE ≠ ORDER" : null;
  }

  const mirror = {
    rows: [
      { label: "历史位置", value: fmtPct(ethBtc?.historical_percentile), unknown: ethBtc?.historical_percentile == null },
      {
        label: "已知周期位置",
        value: cycleZoneLabel(ethBtc?.known_range_position ?? ethBtc?.cycle_percentile),
        unknown: ethBtc?.known_range_position == null && ethBtc?.cycle_percentile == null,
      },
      {
        label: "相对趋势",
        value: ethBtc?.relative_trend || "—",
        unknown: !ethBtc?.relative_trend || ethBtc.relative_trend === "UNKNOWN",
      },
      {
        label: "ETH vs BTC",
        value: rsRecoveryLabel(alloc.relative_strength, ethBtc?.relative_trend),
        unknown: !alloc.relative_strength,
      },
    ],
    whyNot: whyNotSwitch(alloc, ethTrend),
  };

  if (signal === "INCREASE_ETH_ELIGIBLE" && !unknown && !stale) {
    mirror.rows = [
      { label: "价值位置", value: "ATTRACTIVE", unknown: false },
      {
        label: "ETH 趋势",
        value: alloc.eth_trend_level
          ? `${String(alloc.eth_trend_level).split("/")[0]} CONFIRMED`
          : "—",
        unknown: !alloc.eth_trend_level,
      },
      { label: "相对趋势", value: ethBtc?.relative_trend || "—", unknown: !ethBtc?.relative_trend },
      {
        label: "相对强弱",
        value: alloc.relative_strength === "STRONGER" ? "RECOVERING" : alloc.relative_strength || "—",
        unknown: false,
      },
    ];
  }

  return {
    index: "03",
    title: "ETH/BTC RELATIVE VALUE",
    subtitle: "ETH/BTC 相对价值",
    cap: ethBtc?.capability || "PARTIAL",
    statusDot: statusDotFromSignal(signal, unknown),
    headline: headlines[0],
    headlines,
    mirror,
    meta,
    evidence,
    disclaimer,
    signal,
    state,
    unknown,
    stale,
  };
}

/** RIGHT ETH/BTC evidence panel — four layers, no FSM recompute. */
export function ethBtcEvidenceFromObservatory(ethBtc) {
  const alloc = ethBtc?.allocation || {};
  const unknown = ethBtc?.ratio == null || ethBtc?.value_zone === "UNKNOWN";
  const stale = ethBtc?.freshness === "stale" || ethBtc?.data_quality === "stale";

  return {
    status: unknown ? "unknown" : stale ? "stale" : ethBtc?.status || "ok",
    capability: ethBtc?.capability || "PARTIAL",
    unknown,
    stale,
    asOf: ethBtc?.as_of,
    source: ethBtc?.source || "SYNTHETIC_USDT_RATIO",
    ratioSemantics: ethBtc?.ratio_semantics || "research_config_not_tradable_ethbtc",
    current: {
      ratio: ethBtc?.ratio,
      valueZone: ethBtc?.value_zone,
      allocationState: alloc.state,
      allocationSignal: alloc.allocation_signal || ethBtc?.signal,
    },
    historical: {
      low: ethBtc?.historical_low,
      high: ethBtc?.historical_high,
      mean: ethBtc?.historical_mean,
      percentile: ethBtc?.historical_percentile,
    },
    cycle: {
      low: ethBtc?.cycle_low_known,
      high: ethBtc?.cycle_high_known,
      knownRange: ethBtc?.known_range_position ?? ethBtc?.cycle_percentile,
      cycleId: ethBtc?.cycle_id,
    },
    dynamics: {
      relativeTrend: ethBtc?.relative_trend,
      relativeMomentum: ethBtc?.relative_momentum,
      relativeStrength: alloc.relative_strength,
      reasons: alloc.reasons || [],
      blockers: [...(ethBtc?.blockers || []), ...(alloc.blockers || [])],
    },
    freshness: ethBtc?.freshness,
  };
}
