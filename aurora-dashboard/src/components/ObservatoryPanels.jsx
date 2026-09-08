const STATUS_MAP = {
  PASS: 'verified',
  VERIFIED: 'verified',
  OK: 'verified',
  ACTIVE: 'danger',
  INCIDENT_LOCKED: 'danger',
  NO_GO: 'danger',
  DENIED: 'danger',
  DRIFT: 'danger',
  UNKNOWN: 'unknown',
  STALE: 'unknown',
  NOT_VERIFIED: 'unknown',
  NOT_AVAILABLE: 'neutral',
  NOT_OBSERVED: 'unknown',
};

export function StatusBadge({ value = 'UNKNOWN', tone, compact = false }) {
  const normalized = String(value || 'UNKNOWN').toUpperCase().replaceAll(' ', '_');
  return (
    <span className={`status-badge status-${tone || STATUS_MAP[normalized] || 'neutral'} ${compact ? 'status-compact' : ''}`}>
      <span className="status-mark" aria-hidden="true" />
      {normalized.replaceAll('_', ' ')}
    </span>
  );
}

export function SourceMeta({ meta, fallbackSource = 'NOT OBSERVED' }) {
  const status = (meta?.status || 'unknown').toUpperCase();
  return (
    <div className="source-meta">
      <span>{meta?.source || fallbackSource}</span>
      <span aria-hidden="true">·</span>
      <StatusBadge value={status} compact />
      <span aria-hidden="true">·</span>
      <time>{meta?.updatedAt ? new Date(meta.updatedAt).toLocaleTimeString('zh-CN', { hour12: false }) : 'NO TIMESTAMP'}</time>
    </div>
  );
}

export function KnownValue({ value, meta, format = (v) => v, suffix = '', className = '' }) {
  const known = meta?.status === 'ok' && value !== null && value !== undefined && Number.isFinite(Number(value));
  if (!known) return <span className={`unknown-value ${className}`}>UNKNOWN</span>;
  return <span className={className}>{format(Number(value))}{suffix}</span>;
}

export function Panel({ eyebrow, title, meta, children, className = '', action }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {meta && <SourceMeta meta={meta} />}
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function GlobalSafety({ policy, system, connected }) {
  const accountMeta = system.meta || {};
  return (
    <section className="global-safety" aria-labelledby="global-safety-title">
      <div className="brand-lockup">
        <div className="brand-symbol" aria-hidden="true"><span /></div>
        <div>
          <div className="eyebrow">BTC CAPITAL & SAFETY OBSERVATORY</div>
          <h1 id="global-safety-title">AURORA</h1>
        </div>
      </div>
      <div className="global-statuses" aria-label="运行授权状态">
        <div className="global-status-item">
          <span>Environment</span>
          <StatusBadge value={system.meta?.mode || 'UNKNOWN'} tone="info" />
        </div>
        <div className="global-status-item critical">
          <span>Incident</span>
          <StatusBadge value={policy.incidentLock} />
        </div>
        <div className="global-status-item critical">
          <span>Kill</span>
          <StatusBadge value={policy.kill} />
        </div>
        <div className="global-status-item">
          <span>Execution</span>
          <StatusBadge value={policy.executionQualified ? 'QUALIFIED' : 'NOT QUALIFIED'} tone="danger" />
        </div>
        <div className="global-status-item">
          <span>LIVE</span>
          <StatusBadge value={policy.live} />
        </div>
      </div>
      <div className="transport-state">
        <span className={`transport-dot ${connected ? 'connected' : ''}`} aria-hidden="true" />
        <div>
          <strong>WebSocket {connected ? 'CONNECTED' : 'DISCONNECTED'}</strong>
          <span>Transport only · not health</span>
        </div>
        <StatusBadge value={(accountMeta.status || 'UNKNOWN').toUpperCase()} />
      </div>
      <div className="policy-source">
        <span>Authority: {policy.authority}</span>
        <span>Source: {policy.source}</span>
        <span>Baseline: {policy.baseline}</span>
      </div>
    </section>
  );
}

export function PositionTruth({ system }) {
  const meta = system.meta || {};
  const observable = meta.status === 'ok';
  const positions = observable && Array.isArray(system.positions) ? system.positions : [];
  const state = observable ? (system.positionsState || 'UNKNOWN') : 'UNKNOWN';
  return (
    <Panel eyebrow="L2 · EXCHANGE FACT" title="Position Truth" meta={meta} className="position-panel">
      <div className="truth-grid">
        <div className="truth-item">
          <span>Exchange state</span>
          <StatusBadge value={state} tone={state === 'OPEN' ? 'info' : state === 'FLAT' ? 'neutral' : undefined} />
        </div>
        <div className="truth-item">
          <span>Ledger state</span>
          <StatusBadge value="NOT OBSERVED" />
        </div>
        <div className="truth-item">
          <span>Ownership</span>
          <StatusBadge value="UNKNOWN" />
        </div>
        <div className="truth-item">
          <span>Quantity match</span>
          <StatusBadge value="UNKNOWN" />
        </div>
      </div>
      {!observable ? (
        <div className="empty-state warning-state">
          <strong>Position observation unavailable</strong>
          <span>查询失败或尚未成功采集，不能解释为 FLAT。</span>
        </div>
      ) : positions.length === 0 ? (
        <div className="empty-state">
          <strong>Exchange reports no open legs</strong>
          <span>这只证明当前交易所快照为空，不证明账本已对账或退出来源已知。</span>
        </div>
      ) : (
        <div className="position-legs">
          {positions.map((position, index) => (
            <article className="position-leg" key={`${position.symbol || 'UNKNOWN'}-${position.positionSide || position.side || 'UNKNOWN'}-${index}`}>
              <div className="position-leg-head">
                <div>
                  <strong>{position.symbol || 'UNKNOWN SYMBOL'}</strong>
                  <span>LEG {String(index + 1).padStart(2, '0')}</span>
                </div>
                <StatusBadge value={position.positionSide || position.side || 'POSITION SIDE UNKNOWN'} tone="info" />
              </div>
              <dl className="metric-list">
                <div><dt>Economic side</dt><dd>{position.side || 'UNKNOWN'}</dd></div>
                <div><dt>Position side</dt><dd>{position.positionSide || 'NOT OBSERVED'}</dd></div>
                <div><dt>Quantity</dt><dd>{Number.isFinite(Number(position.size)) ? `${position.size} BTC` : 'UNKNOWN'}</dd></div>
                <div><dt>Entry</dt><dd>{Number.isFinite(Number(position.entryPrice)) ? `$${Number(position.entryPrice).toLocaleString()}` : 'UNKNOWN'}</dd></div>
                <div><dt>Leverage</dt><dd>{Number.isFinite(Number(position.leverage)) ? `${position.leverage}x · observed` : 'UNKNOWN'}</dd></div>
                <div><dt>Unrealized PnL</dt><dd>{Number.isFinite(Number(position.unrealizedPnl)) ? `${Number(position.unrealizedPnl).toFixed(2)} USDT` : 'UNKNOWN'}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function ProtectionTruth({ system }) {
  const protection = system.meta?.protectionStatus || 'NOT_VERIFIED';
  return (
    <Panel eyebrow="L2 + L4 · DO NOT CONFLATE" title="Protection Evidence" className="protection-panel">
      <div className="split-contract">
        <div className="contract-block">
          <div className="contract-label">Strategy intent</div>
          <div className="contract-title">Thresholds</div>
          <dl className="metric-list">
            <div><dt>Stop threshold</dt><dd className="unknown-value">UNKNOWN</dd></div>
            <div><dt>Take profit</dt><dd className="unknown-value">UNKNOWN</dd></div>
            <div><dt>Source</dt><dd>NOT OBSERVED</dd></div>
          </dl>
        </div>
        <div className="contract-divider" aria-hidden="true" />
        <div className="contract-block">
          <div className="contract-label">Exchange protection</div>
          <div className="contract-title"><StatusBadge value={protection} /></div>
          <dl className="metric-list">
            <div><dt>Algo status</dt><dd className="unknown-value">UNKNOWN</dd></div>
            <div><dt>Protected qty</dt><dd className="unknown-value">UNKNOWN</dd></div>
            <div><dt>Working type</dt><dd className="unknown-value">UNKNOWN</dd></div>
          </dl>
        </div>
      </div>
      <div className="invariant-callout">VALID threshold ≠ exchange protection verified</div>
    </Panel>
  );
}

export function RecoveryEvidence({ policy }) {
  const events = [
    { time: 'CURRENT', title: 'INCIDENT LOCK ACTIVE', detail: 'Automatic TESTNET remains denied.', tone: 'danger', transition: 'QUALIFICATION → BLOCKED' },
    { time: 'OPEN', title: 'EXIT-PROVENANCE-01', detail: 'Exchange is flat; exit mechanism remains unknown.', tone: 'unknown', transition: 'KNOWN_OPEN → KNOWN_FLAT · provenance UNKNOWN' },
    { time: 'SEALED', title: 'G0-4A OFFLINE CONTRACT', detail: 'Algo protocol contract is offline-only.', tone: 'info', transition: 'LEGACY CONDITIONAL → ALGO CONTRACT' },
  ];
  return (
    <Panel eyebrow="L3 · RECOVERY / AUDIT" title="Recovery & Evidence" className="recovery-panel" action={<StatusBadge value={policy.incidentLock} />}>
      <div className="timeline">
        {events.map((event) => (
          <div className={`timeline-event timeline-${event.tone}`} key={event.title}>
            <div className="timeline-rail"><span /></div>
            <div className="timeline-time">{event.time}</div>
            <div className="timeline-content">
              <strong>{event.title}</strong>
              <p>{event.detail}</p>
              <code>{event.transition}</code>
            </div>
          </div>
        ))}
      </div>
      <div className="source-meta"><span>Authority: CAPABILITY REGISTRY SNAPSHOT</span><span>·</span><span>D2 kernel projection not connected</span></div>
    </Panel>
  );
}

export function CapitalObjective() {
  const rows = [
    ['BTC NAV', 'NOT AVAILABLE'],
    ['BTC vs HODL', 'NOT AVAILABLE'],
    ['BTC-denominated drawdown', 'NOT AVAILABLE'],
  ];
  return (
    <Panel eyebrow="PRODUCT NORTH STAR" title="BTC Capital Objective" className="capital-panel">
      <div className="capital-mark">₿</div>
      <div className="capital-rows">
        {rows.map(([label, value]) => (
          <div key={label}><span>{label}</span><StatusBadge value={value} /></div>
        ))}
      </div>
      <div className="blocked-reasons">
        <strong>Accounting evidence incomplete</strong>
        <span>Decimal ledger not migrated</span>
        <span>BTC benchmark series not established</span>
      </div>
    </Panel>
  );
}

export function DataFreshness({ sections, connected }) {
  return (
    <Panel eyebrow="OBSERVABILITY" title="Data Freshness" className="freshness-panel">
      <div className="freshness-list">
        {sections.map(({ name, meta }) => (
          <div className="freshness-row" key={name}>
            <div><strong>{name}</strong><span>{meta?.source || 'SOURCE UNKNOWN'}</span></div>
            <StatusBadge value={(meta?.status || 'UNKNOWN').toUpperCase()} />
            <time>{meta?.updatedAt ? new Date(meta.updatedAt).toLocaleString('zh-CN', { hour12: false }) : 'NO SUCCESSFUL OBSERVATION'}</time>
          </div>
        ))}
      </div>
      <div className="invariant-callout">WS {connected ? 'CONNECTED' : 'DISCONNECTED'} ≠ data fresh ≠ ledger reconciled</div>
    </Panel>
  );
}

export function MarketEvidence({ market, score }) {
  const meta = market.meta || {};
  const known = meta.status === 'ok';
  return (
    <Panel eyebrow="L4 · STRATEGY OBSERVATION" title="Market Evidence" meta={meta} className="market-evidence-panel">
      <div className="market-evidence-grid">
        <div className="large-metric">
          <span>Observed price</span>
          <KnownValue value={market.price} meta={meta} format={(v) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`} />
        </div>
        <div className="evidence-metric"><span>Candidate regime</span><strong>{known ? market.regime || 'UNKNOWN' : 'UNKNOWN'}</strong></div>
        <div className="evidence-metric"><span>Confirmed regime</span><strong className="unknown-value">NOT OBSERVED</strong></div>
        <div className="evidence-metric"><span>Signal confidence</span><strong>{known && score !== null && Number.isFinite(Number(score)) ? `${score}%` : 'UNKNOWN'}</strong></div>
        <div className="evidence-metric"><span>Execution authority</span><strong className="danger-text">NONE</strong></div>
      </div>
      <div className="invariant-callout">Signal evidence never produces can_trade</div>
    </Panel>
  );
}

export function ObservedRisk({ risk }) {
  const meta = risk.meta || {};
  const drawdownBand = meta.status !== 'ok'
    ? 'UNKNOWN'
    : risk.status === 'SAFE' ? 'DRAWDOWN ≤ 2%'
      : risk.status === 'WARNING' ? 'DRAWDOWN 2–5%'
        : risk.status === 'DANGER' ? 'DRAWDOWN > 5%' : 'UNKNOWN';
  return (
    <Panel eyebrow="EXCHANGE-DERIVED · LIMITED" title="Observed Exposure" meta={meta} className="risk-panel">
      <div className="truth-grid">
        <div className="truth-item"><span>Derived drawdown band</span><StatusBadge value={drawdownBand} tone={drawdownBand === 'UNKNOWN' ? 'unknown' : 'neutral'} /></div>
        <div className="truth-item"><span>Current drawdown</span><KnownValue value={risk.currentDrawdown} meta={meta} format={(v) => v.toFixed(2)} suffix="%" /></div>
        <div className="truth-item"><span>Unrealized PnL</span><KnownValue value={risk.totalPnl} meta={meta} format={(v) => v.toFixed(2)} suffix=" USDT" /></div>
        <div className="truth-item"><span>Daily realized PnL</span><span className="unknown-value">NOT OBSERVED</span></div>
      </div>
      <p className="panel-note">当前 feed 的风险数据来自账户快照，不是 kernel 风险状态，也不证明日盈亏或累计收益。</p>
    </Panel>
  );
}

export function TradeObservations({ trades, meta }) {
  const observable = meta?.status === 'ok';
  return (
    <Panel eyebrow="EXCHANGE OBSERVATION" title="Recent User Trades" meta={meta} className="trades-panel">
      {!observable ? (
        <div className="empty-state warning-state"><strong>Trade observation unavailable</strong><span>UNKNOWN 不显示为空列表。</span></div>
      ) : trades.length === 0 ? (
        <div className="empty-state"><strong>Exchange returned no recent user trades</strong><span>这不是 ledger fill 完整性证明。</span></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Observed at</th><th>Side</th><th className="number">Quantity</th><th className="number">Price</th><th className="number">Realized PnL</th><th>Authority</th></tr></thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id || `${trade.timestamp}-${trade.side}-${trade.quantity}`}>
                  <td>{trade.timestamp ? new Date(trade.timestamp).toLocaleString('zh-CN', { hour12: false }) : 'UNKNOWN'}</td>
                  <td><StatusBadge value={trade.side || 'UNKNOWN'} tone="info" compact /></td>
                  <td className="number">{Number.isFinite(Number(trade.quantity)) ? `${trade.quantity} BTC` : 'UNKNOWN'}</td>
                  <td className="number">{Number.isFinite(Number(trade.entryPrice)) ? `$${Number(trade.entryPrice).toLocaleString()}` : 'UNKNOWN'}</td>
                  <td className="number">{Number.isFinite(Number(trade.pnl)) ? `${Number(trade.pnl).toFixed(2)} USDT` : 'UNKNOWN'}</td>
                  <td><StatusBadge value="EXCHANGE" tone="neutral" compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
