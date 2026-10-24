const ZH_LABELS = {
  UNKNOWN: "未知",
  STALE: "已过期",
  FLAT: "空仓",
  OPEN: "持仓中",
  LONG: "做多",
  SHORT: "做空",
  BUY: "买入",
  SELL: "卖出",
  TREND: "趋势",
  RANGE: "震荡",
  TRANSITION: "过渡",
};

export function zhLabel(value) {
  if (value === null || value === undefined || value === "") return value;
  const normalized = String(value).toUpperCase().replaceAll(" ", "_");
  return ZH_LABELS[normalized] || value;
}

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

export function isObservable(meta) {
  const status = meta?.status;
  return status === "ok" || status === "stale";
}

export function KnownValue({ value, meta, format = (v) => v, suffix = "", className = "" }) {
  if (!isObservable(meta) || value === null || value === undefined || !Number.isFinite(Number(value))) {
    return <span className={`val-unknown ${className}`}>未知</span>;
  }
  return <span className={className}>{format(Number(value))}{suffix}</span>;
}

/** L0 — 能不能写？ */
export function GovernanceBand({ policy, connected }) {
  const gates = [
    `LOCK ${policy.incidentLock === "INCIDENT_LOCKED" ? "ACTIVE" : policy.incidentLock}`,
    `KILL ${policy.kill}`,
    `EXECUTE ${policy.executeAuthorized ? "AUTHORIZED" : "DENIED"}`,
    `LIVE ${policy.live.replace("_", "-")}`,
  ].join(" · ");

  return (
    <header className="gov-band" aria-labelledby="observatory-title">
      <h1 id="observatory-title" className="obs-title">
        AURORA · BTC NUMERAIRE OBSERVATORY
      </h1>
      <p className="gov-gates">{gates}</p>
      <p className="gov-meta">
        STATIC SNAPSHOT · {formatStamp(policy.capturedAt)} · {policy.sourceCommit}
        {" · "}
        <span className={connected ? "ws-up" : "ws-down"}>
          WS {connected ? "CONNECTED" : "DISCONNECTED"} · LINK ONLY
        </span>
      </p>
    </header>
  );
}

/** L1 — 策略在做什么？ */
export function StrategyBand({ policy, overlay }) {
  const identity = policy.identity;
  const action = overlay?.action || "UNKNOWN";
  const fixture = overlay?.sourceKind === "PROTOTYPE FIXTURE";
  const htfKnown = fixture && action !== "UNKNOWN";
  const asOf = overlay?.asOf ? formatStamp(overlay.asOf) : "—";
  const dash = "—";

  let footnote = `HTF unavailable · no 1m fallback · ${identity.sourceCommit}`;
  if (fixture) footnote = `PROTOTYPE FIXTURE · 禁止当成实盘指令 · ${identity.sourceCommit}`;
  else if (htfKnown) footnote = `CLOSED 1D BAR · ${identity.sourceCommit}`;

  return (
    <section className="strategy-band" aria-labelledby="strategy-title">
      <h2 id="strategy-title" className="visually-hidden">策略身份</h2>
      <div className="strategy-trio">
        <div className="strategy-cell">
          <span>CORE</span>
          <strong>{identity.core}</strong>
        </div>
        <div className={`strategy-cell strategy-hero overlay-${action.toLowerCase()} ${fixture ? "is-fixture" : ""}`}>
          <span>OVERLAY</span>
          <strong>{action}</strong>
          {fixture ? <em className="fixture-mark">PROTOTYPE FIXTURE</em> : null}
        </div>
        <div className="strategy-cell">
          <span>AS OF</span>
          <strong className={overlay?.asOf ? "" : "val-unknown"}>{asOf}</strong>
        </div>
      </div>
      <p className="strategy-metrics">
        close {htfKnown ? overlay.close.toLocaleString("en-US") : dash}
        {" · "}
        ema20 {htfKnown ? overlay.ema20.toLocaleString("en-US") : dash}
        {" · "}
        ema60 {htfKnown ? overlay.ema60.toLocaleString("en-US") : dash}
        {" · "}
        ADX {htfKnown ? overlay.adx.toFixed(1) : dash}
      </p>
      <p className="strategy-foot">{footnote}</p>
    </section>
  );
}

function walletLine(assets, stale) {
  if (!assets.length) return stale ? "未知 · STALE" : "未知";
  const primary = assets.find((a) => a.asset === "USDT") || assets[0];
  const bal = Number(primary.walletBalance).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const suffix = stale ? " · STALE" : "";
  return `${bal} ${primary.asset}${suffix}`;
}

function positionLine(system, stale) {
  const meta = system.meta || {};
  const observable = isObservable(meta);
  if (!observable) return "UNKNOWN";
  const state = system.positionsState || "UNKNOWN";
  const positions = Array.isArray(system.positions) ? system.positions : [];
  if (state === "FLAT") return "FLAT";
  if (positions.length === 0) return stale ? `${state} · STALE` : state;
  const leg = positions[0];
  const side = (leg.positionSide || leg.side || "LONG").toUpperCase();
  const size = Number.isFinite(Number(leg.size)) ? leg.size : "?";
  return `${side} ${size}${stale ? " · STALE" : ""}`;
}

/** L2 — 交易所实际看见什么？ */
export function ExchangeObservation({ system, connected }) {
  const meta = system.meta || {};
  const observable = isObservable(meta);
  const stale = meta.status === "stale";
  const assets = observable && Array.isArray(system.assets) ? system.assets : [];
  const stateKind = !observable ? "unknown" : stale ? "stale" : system.positionsState === "FLAT" ? "flat" : "ok";

  let headline;
  let subline;
  if (!observable) {
    headline = connected ? "交易所观察不可用" : "交易所观察不可用";
    subline = "不能解释为空仓";
  } else if (stale) {
    headline = `仓位 ${positionLine(system, true)}`;
    subline = "过期快照 · 数字不是当前事实 · 不得刷新为空仓";
  } else if (system.positionsState === "FLAT") {
    headline = "交易所报告空仓";
    subline = "FLAT = 权威事实 · 非账本对账";
  } else {
    headline = `仓位 ${positionLine(system, false)}`;
    subline = null;
  }

  const source = observable
    ? (meta.source === "EXCHANGE_READONLY" ? "EXCHANGE OBSERVATION" : meta.source || "EXCHANGE OBSERVATION")
    : "UNKNOWN";

  return (
    <section className={`exchange-band state-${stateKind}`} aria-labelledby="exchange-title">
      <h2 id="exchange-title" className="exchange-headline">{headline}</h2>
      {subline ? <p className="exchange-subline">{subline}</p> : null}
      <dl className="exchange-facts">
        <div><dt>Wallet</dt><dd className={!observable ? "val-unknown" : stale ? "val-stale" : ""}>{observable ? walletLine(assets, stale) : "UNKNOWN"}</dd></div>
        <div><dt>Position</dt><dd className={!observable ? "val-unknown" : stale ? "val-stale" : stateKind === "flat" ? "val-flat" : ""}>{observable ? positionLine(system, stale) : "UNKNOWN"}</dd></div>
        <div><dt>Source</dt><dd>{source}</dd></div>
      </dl>
    </section>
  );
}

/** 缺口 — 永远一行 */
export function GapLine() {
  return (
    <p className="gap-line" aria-label="未接入缺口">
      缺口 · 账本未知 · BTC NAV 未接 · 保护未核验 · EXIT OPEN
    </p>
  );
}

export function diagnosticHint(scene) {
  if (!scene.connected) return "链路断开 · 无开仓权";
  const status = scene.market?.meta?.status;
  if (status === "stale") return "已过期 · 无开仓权";
  if (status === "ok") return "可观察 · 无开仓权";
  return "未知 · 无开仓权";
}

export function DiagnosticAuthority() {
  return (
    <p className="diag-authority" role="note">
      NO OPEN AUTHORITY · 无开仓权 · 1m 不能生成 overlay · 不能回退 HTF UNKNOWN
    </p>
  );
}

export function DiagnosticRegime({ market }) {
  const meta = market.meta || {};
  const known = isObservable(meta);
  return (
    <div className="diag-block">
      <span className="diag-label">1m regime</span>
      <strong className={known ? "" : "val-unknown"}>
        {known ? zhLabel(market.regime || "UNKNOWN") : "未知"}
      </strong>
    </div>
  );
}

export function DiagnosticMicro({ market, risk }) {
  const meta = market.meta || {};
  const riskMeta = risk.meta || {};
  return (
    <div className="diag-block">
      <span className="diag-label">micro / exposure</span>
      <span>
        价格{" "}
        <KnownValue
          value={market.price}
          meta={meta}
          format={(v) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
        />
        {" · "}
        未实现{" "}
        <KnownValue value={risk.totalPnl} meta={riskMeta} format={(v) => `${v.toFixed(2)} USDT`} />
      </span>
    </div>
  );
}

export function DiagnosticFills({ trades, meta }) {
  const observable = isObservable(meta);
  const items = observable && Array.isArray(trades) ? trades : [];
  return (
    <div className="diag-block diag-fills">
      <span className="diag-label">recent fills</span>
      {!observable ? (
        <span className="val-unknown">成交观察不可用</span>
      ) : items.length === 0 ? (
        <span className="val-muted">交易所未返回近期成交</span>
      ) : (
        <ul>
          {items.slice(0, 5).map((t) => (
            <li key={t.id || `${t.timestamp}-${t.side}`}>
              {formatStamp(t.timestamp)} · {zhLabel(t.side)} · {t.quantity} BTC @ ${Number(t.entryPrice).toLocaleString()}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
