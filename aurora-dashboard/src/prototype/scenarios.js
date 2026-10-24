import { POLICY_SNAPSHOT } from "../policySnapshot";

function meta(status, extra = {}) {
  const mode = Object.prototype.hasOwnProperty.call(extra, "mode")
    ? extra.mode
    : "TESTNET";
  return {
    source: extra.source || (status === "unknown" ? "UNKNOWN" : "EXCHANGE_READONLY"),
    status,
    updatedAt: extra.updatedAt ?? null,
    lastError: extra.lastError ?? null,
    mode,
    protectionStatus: "NOT_VERIFIED",
    ledgerReconciled: false,
  };
}

function klines(n = 48, start = 78000) {
  const t0 = Date.parse("2026-09-09T00:00:00Z");
  const rows = [];
  let px = start;
  for (let i = 0; i < n; i += 1) {
    const drift = (i % 7) - 3;
    const open = px;
    const close = px + drift * 12;
    rows.push({
      time: t0 + i * 60_000,
      open,
      high: Math.max(open, close) + 18,
      low: Math.min(open, close) - 14,
      close,
      volume: 40 + (i % 5) * 8,
    });
    px = close;
  }
  return rows;
}

const STALE_AT = "2026-09-09T04:11:00Z";
const OK_AT = "2026-09-09T07:01:00Z";

const emptyOverlay = {
  action: "UNKNOWN",
  sourceKind: "UNKNOWN",
  source: "CLOSED 1D BAR",
  asOf: null,
  close: null,
  ema20: null,
  ema60: null,
  adx: null,
  note: "HTF missing · D1 HOLD · 无 1m 回退",
};

export const SCENARIOS = [
  {
    id: "disconnected",
    label: "断线",
    tone: "danger",
    summary: "链路断开。L0/L1 CORE 仍是封存快照；其余 UNKNOWN。",
    connected: false,
    overlay: emptyOverlay,
    system: {
      positions: [],
      positionsState: "UNKNOWN",
      assets: [],
      meta: meta("unknown", { mode: null, source: "UNKNOWN" }),
    },
    market: {
      price: null,
      regime: null,
      klines: [],
      meta: meta("unknown", { mode: null, source: "UNKNOWN" }),
    },
    risk: {
      currentDrawdown: null,
      totalPnl: null,
      status: "UNKNOWN",
      meta: meta("unknown", { source: "UNKNOWN" }),
    },
    trades: { items: [], meta: meta("unknown", { source: "UNKNOWN" }) },
  },
  {
    id: "unknown",
    label: "UNKNOWN",
    tone: "unknown",
    summary: "链路在，从未采集成功。禁止把空表画成 FLAT。",
    connected: true,
    overlay: emptyOverlay,
    system: {
      positions: [],
      positionsState: "UNKNOWN",
      assets: [],
      meta: meta("unknown", { lastError: "never succeeded" }),
    },
    market: {
      price: null,
      regime: null,
      klines: [],
      meta: meta("unknown", { lastError: "never succeeded" }),
    },
    risk: {
      currentDrawdown: null,
      totalPnl: null,
      status: "UNKNOWN",
      meta: meta("unknown"),
    },
    trades: { items: [], meta: meta("unknown") },
  },
  {
    id: "stale",
    label: "STALE",
    tone: "stale",
    summary: "展示上一份快照，但必须标过期。不得刷新为未知空仓。",
    connected: true,
    overlay: emptyOverlay,
    system: {
      positions: [
        {
          symbol: "BTCUSDT",
          side: "LONG",
          positionSide: "LONG",
          size: 0.001,
          entryPrice: 78425.6,
          leverage: 3,
          unrealizedPnl: -1.24,
        },
      ],
      positionsState: "OPEN",
      assets: [
        { asset: "USDT", walletBalance: 10420.15, availableBalance: 9980.02, unrealizedPnl: -1.24 },
      ],
      meta: meta("stale", { updatedAt: STALE_AT, lastError: "timeout" }),
    },
    market: {
      price: 78610.4,
      regime: "TREND",
      klines: klines(40, 78400),
      meta: meta("stale", { updatedAt: STALE_AT, lastError: "timeout" }),
    },
    risk: {
      currentDrawdown: 0.4,
      totalPnl: -1.24,
      status: "SAFE",
      meta: meta("stale", { updatedAt: STALE_AT }),
    },
    trades: {
      items: [
        {
          id: "stale-1",
          timestamp: STALE_AT,
          side: "BUY",
          quantity: 0.001,
          entryPrice: 78425.6,
          pnl: 0,
        },
      ],
      meta: meta("stale", { updatedAt: STALE_AT }),
    },
  },
  {
    id: "exchange-ok",
    label: "交易所 OK",
    tone: "ok",
    summary: "L2 可观察；L1 overlay 仍 UNKNOWN（D1 未接，无 1m 回退）。",
    connected: true,
    overlay: emptyOverlay,
    system: {
      positions: [],
      positionsState: "FLAT",
      assets: [
        { asset: "USDT", walletBalance: 11204.88, availableBalance: 11204.88, unrealizedPnl: 0 },
      ],
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    market: {
      price: 78788.9,
      regime: "TRANSITION",
      klines: klines(),
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    risk: {
      currentDrawdown: 0,
      totalPnl: 0,
      status: "SAFE",
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    trades: { items: [], meta: meta("ok", { updatedAt: OK_AT }) },
  },
  {
    id: "overlay-open",
    label: "L1 OPEN 夹具",
    tone: "fixture",
    summary: "只验证身份带排版。PROTOTYPE FIXTURE，不是 live decide_overlay。",
    connected: true,
    overlay: {
      action: "OPEN",
      sourceKind: "PROTOTYPE FIXTURE",
      source: "CLOSED 1D BAR",
      asOf: "2026-09-08T00:00:00Z",
      close: 78788.9,
      ema20: 77210.4,
      ema60: 74102.1,
      adx: 28.4,
      note: "夹具 · 禁止当成实盘指令",
    },
    system: {
      positions: [
        {
          symbol: "BTCUSDT",
          side: "LONG",
          positionSide: "LONG",
          size: 0.001,
          entryPrice: 78120,
          leverage: 2,
          unrealizedPnl: 6.68,
        },
      ],
      positionsState: "OPEN",
      assets: [
        { asset: "USDT", walletBalance: 10880.4, availableBalance: 10110.2, unrealizedPnl: 6.68 },
      ],
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    market: {
      price: 78788.9,
      regime: "TREND",
      klines: klines(48, 78100),
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    risk: {
      currentDrawdown: 0,
      totalPnl: 6.68,
      status: "SAFE",
      meta: meta("ok", { updatedAt: OK_AT }),
    },
    trades: {
      items: [
        {
          id: "fx-1",
          timestamp: OK_AT,
          side: "BUY",
          quantity: 0.001,
          entryPrice: 78120,
          pnl: 0,
        },
      ],
      meta: meta("ok", { updatedAt: OK_AT }),
    },
  },
];

export function scenarioById(id) {
  return SCENARIOS.find((s) => s.id === id) || SCENARIOS[0];
}

export { POLICY_SNAPSHOT };
