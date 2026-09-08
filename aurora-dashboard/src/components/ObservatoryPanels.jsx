// 状态徽章：底层值保持后端英文枚举（逻辑判断不受影响），显示层映射中文。
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

const ZH_LABELS = {
  PASS: '通过',
  VERIFIED: '已验证',
  OK: '正常',
  ACTIVE: '已生效',
  INCIDENT_LOCKED: '事故锁定',
  NO_GO: '禁止',
  DENIED: '已拒绝',
  DRIFT: '漂移',
  UNKNOWN: '未知',
  STALE: '已过期',
  NOT_VERIFIED: '未核验',
  NOT_AVAILABLE: '不可用',
  NOT_OBSERVED: '未观测',
  FLAT: '空仓',
  OPEN: '持仓中',
  QUALIFIED: '合格',
  NOT_QUALIFIED: '不合格',
  SAFE: '安全',
  WARNING: '警告',
  DANGER: '危险',
  LONG: '做多',
  SHORT: '做空',
  EXCHANGE: '交易所',
  EXCHANGE_READONLY: '交易所只读',
  SOURCE_UNKNOWN: '来源未知',
  'NOT CONNECTED': '未连接',
  NOT_CONNECTED: '未连接',
  'NO TIMESTAMP': '无时间戳',
  NO_TIMESTAMP: '无时间戳',
  TRANSITION: '过渡',
  TREND: '趋势',
  RANGE: '震荡',
  DRAWDOWN_LE2: '回撤 ≤ 2%',
  DRAWDOWN_2_5: '回撤 2–5%',
  DRAWDOWN_GT5: '回撤 > 5%',
};

export function zhLabel(value) {
  if (value === null || value === undefined || value === '') return value;
  const normalized = String(value).toUpperCase().replaceAll(' ', '_');
  return ZH_LABELS[normalized] || value;
}

export function StatusBadge({ value = 'UNKNOWN', tone, compact = false }) {
  const normalized = String(value || 'UNKNOWN').toUpperCase().replaceAll(' ', '_');
  const display = zhLabel(normalized);
  return (
    <span className={`status-badge status-${tone || STATUS_MAP[normalized] || 'neutral'} ${compact ? 'status-compact' : ''}`}>
      <span className="status-mark" aria-hidden="true" />
      {display}
    </span>
  );
}

export function SourceMeta({ meta, fallbackSource = '未观测' }) {
  const status = (meta?.status || 'unknown').toUpperCase();
  return (
    <div className="source-meta">
      <span>{zhLabel(meta?.source) || fallbackSource}</span>
      <span aria-hidden="true">·</span>
      <StatusBadge value={status} compact />
      <span aria-hidden="true">·</span>
      <time>{meta?.updatedAt ? new Date(meta.updatedAt).toLocaleTimeString('zh-CN', { hour12: false }) : '无时间戳'}</time>
    </div>
  );
}

export function KnownValue({ value, meta, format = (v) => v, suffix = '', className = '' }) {
  const known = meta?.status === 'ok' && value !== null && value !== undefined && Number.isFinite(Number(value));
  if (!known) return <span className={`unknown-value ${className}`}>未知</span>;
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
          <div className="eyebrow">BTC 资本与安全观察台</div>
          <h1 id="global-safety-title">AURORA</h1>
        </div>
      </div>
      <div className="global-statuses" aria-label="运行授权状态">
        <div className="global-status-item">
          <span>运行环境</span>
          <StatusBadge value={system.meta?.mode || 'UNKNOWN'} tone="info" />
        </div>
        <div className="global-status-item critical">
          <span>事故锁</span>
          <StatusBadge value={policy.incidentLock} />
        </div>
        <div className="global-status-item critical">
          <span>急停开关</span>
          <StatusBadge value={policy.kill} />
        </div>
        <div className="global-status-item">
          <span>执行资格</span>
          <StatusBadge value={policy.executionQualified ? 'QUALIFIED' : 'NOT QUALIFIED'} tone="danger" />
        </div>
        <div className="global-status-item">
          <span>实盘</span>
          <StatusBadge value={policy.live} />
        </div>
      </div>
      <div className="transport-state">
        <span className={`transport-dot ${connected ? 'connected' : ''}`} aria-hidden="true" />
        <div>
          <strong>WebSocket {connected ? '已连接' : '已断开'}</strong>
          <span>仅表示链路 · 不代表运行健康</span>
        </div>
        <StatusBadge value={(accountMeta.status || 'UNKNOWN').toUpperCase()} />
      </div>
      <div className="policy-source">
        <span>权威：{policy.authority}</span>
        <span>来源：{policy.source}</span>
        <span>基线：{policy.baseline}</span>
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
    <Panel eyebrow="L2 · 交易所事实" title="仓位真相" meta={meta} className="position-panel">
      <div className="truth-grid">
        <div className="truth-item">
          <span>交易所状态</span>
          <StatusBadge value={state} tone={state === 'OPEN' ? 'info' : state === 'FLAT' ? 'neutral' : undefined} />
        </div>
        <div className="truth-item">
          <span>账本状态</span>
          <StatusBadge value="NOT OBSERVED" />
        </div>
        <div className="truth-item">
          <span>仓位归属</span>
          <StatusBadge value="UNKNOWN" />
        </div>
        <div className="truth-item">
          <span>数量核对</span>
          <StatusBadge value="UNKNOWN" />
        </div>
      </div>
      {!observable ? (
        <div className="empty-state warning-state">
          <strong>仓位观察不可用</strong>
          <span>查询失败或尚未成功采集，不能解释为空仓。</span>
        </div>
      ) : positions.length === 0 ? (
        <div className="empty-state">
          <strong>交易所报告无持仓腿</strong>
          <span>这只证明当前交易所快照为空，不证明账本已对账或退出来源已知。</span>
        </div>
      ) : (
        <div className="position-legs">
          {positions.map((position, index) => (
            <article className="position-leg" key={`${position.symbol || 'UNKNOWN'}-${position.positionSide || position.side || 'UNKNOWN'}-${index}`}>
              <div className="position-leg-head">
                <div>
                  <strong>{position.symbol || '未知品种'}</strong>
                  <span>腿 {String(index + 1).padStart(2, '0')}</span>
                </div>
                <StatusBadge value={position.positionSide || position.side || 'UNKNOWN'} tone="info" />
              </div>
              <dl className="metric-list">
                <div><dt>经济方向</dt><dd>{position.side || '未知'}</dd></div>
                <div><dt>持仓方向</dt><dd>{position.positionSide || '未观测'}</dd></div>
                <div><dt>数量</dt><dd>{Number.isFinite(Number(position.size)) ? `${position.size} BTC` : '未知'}</dd></div>
                <div><dt>开仓价</dt><dd>{Number.isFinite(Number(position.entryPrice)) ? `$${Number(position.entryPrice).toLocaleString()}` : '未知'}</dd></div>
                <div><dt>杠杆</dt><dd>{Number.isFinite(Number(position.leverage)) ? `${position.leverage}x · 已观察` : '未知'}</dd></div>
                <div><dt>未实现盈亏</dt><dd>{Number.isFinite(Number(position.unrealizedPnl)) ? `${Number(position.unrealizedPnl).toFixed(2)} USDT` : '未知'}</dd></div>
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
    <Panel eyebrow="L2 + L4 · 不得混同" title="保护证据" className="protection-panel">
      <div className="split-contract">
        <div className="contract-block">
          <div className="contract-label">策略意图</div>
          <div className="contract-title">阈值</div>
          <dl className="metric-list">
            <div><dt>止损阈值</dt><dd className="unknown-value">未知</dd></div>
            <div><dt>止盈阈值</dt><dd className="unknown-value">未知</dd></div>
            <div><dt>来源</dt><dd>未观测</dd></div>
          </dl>
        </div>
        <div className="contract-divider" aria-hidden="true" />
        <div className="contract-block">
          <div className="contract-label">交易所保护</div>
          <div className="contract-title"><StatusBadge value={protection} /></div>
          <dl className="metric-list">
            <div><dt>Algo 状态</dt><dd className="unknown-value">未知</dd></div>
            <div><dt>受保护数量</dt><dd className="unknown-value">未知</dd></div>
            <div><dt>触发基准</dt><dd className="unknown-value">未知</dd></div>
          </dl>
        </div>
      </div>
      <div className="invariant-callout">有效阈值 ≠ 交易所保护已核验</div>
    </Panel>
  );
}

export function RecoveryEvidence({ policy }) {
  const events = [
    { time: '当前', title: '事故锁生效中', detail: 'TESTNET 自动交易维持拒绝。', tone: 'danger', transition: '资格复核 → 阻断' },
    { time: '未决', title: 'EXIT-PROVENANCE-01', detail: '交易所已空仓；退出机制未知。', tone: 'unknown', transition: 'KNOWN_OPEN → KNOWN_FLAT · 来源未知' },
    { time: '已封存', title: 'G0-4A 离线合同', detail: 'Algo 协议合同仅限离线。', tone: 'info', transition: '旧条件单 → Algo 合同' },
  ];
  return (
    <Panel eyebrow="L3 · 恢复 / 审计" title="恢复与证据" className="recovery-panel" action={<StatusBadge value={policy.incidentLock} />}>
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
      <div className="source-meta"><span>权威：能力台账快照</span><span>·</span><span>D2 内核投影未接入</span></div>
    </Panel>
  );
}

export function CapitalObjective() {
  const rows = [
    ['BTC 净值', 'NOT AVAILABLE'],
    ['BTC 相对持有', 'NOT AVAILABLE'],
    ['BTC 本位回撤', 'NOT AVAILABLE'],
  ];
  return (
    <Panel eyebrow="产品北极星" title="BTC 资本目标" className="capital-panel">
      <div className="capital-mark">₿</div>
      <div className="capital-rows">
        {rows.map(([label, value]) => (
          <div key={label}><span>{label}</span><StatusBadge value={value} /></div>
        ))}
      </div>
      <div className="blocked-reasons">
        <strong>记账证据不完整</strong>
        <span>Decimal 账本未迁移</span>
        <span>BTC 基准序列未建立</span>
      </div>
    </Panel>
  );
}

export function DataFreshness({ sections, connected }) {
  return (
    <Panel eyebrow="可观测性" title="数据新鲜度" className="freshness-panel">
      <div className="freshness-list">
        {sections.map(({ name, meta }) => (
          <div className="freshness-row" key={name}>
            <div><strong>{name}</strong><span>{zhLabel(meta?.source) || '来源未知'}</span></div>
            <StatusBadge value={(meta?.status || 'UNKNOWN').toUpperCase()} />
            <time>{meta?.updatedAt ? new Date(meta.updatedAt).toLocaleString('zh-CN', { hour12: false }) : '尚无成功采集'}</time>
          </div>
        ))}
      </div>
      <div className="invariant-callout">WS {connected ? '已连接' : '已断开'} ≠ 数据新鲜 ≠ 账本已对账</div>
    </Panel>
  );
}

export function MarketEvidence({ market, score }) {
  const meta = market.meta || {};
  const known = meta.status === 'ok';
  return (
    <Panel eyebrow="L4 · 策略观察" title="市场证据" meta={meta} className="market-evidence-panel">
      <div className="market-evidence-grid">
        <div className="large-metric">
          <span>观察价格</span>
          <KnownValue value={market.price} meta={meta} format={(v) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`} />
        </div>
        <div className="evidence-metric"><span>候选状态</span><strong>{known ? zhLabel(market.regime || 'UNKNOWN') : '未知'}</strong></div>
        <div className="evidence-metric"><span>已确认状态</span><strong className="unknown-value">未观测</strong></div>
        <div className="evidence-metric"><span>信号置信度</span><strong>{known && score !== null && Number.isFinite(Number(score)) ? `${score}%` : '未知'}</strong></div>
        <div className="evidence-metric"><span>执行权限</span><strong className="danger-text">无</strong></div>
      </div>
      <div className="invariant-callout">信号证据永远不产生交易许可</div>
    </Panel>
  );
}

export function ObservedRisk({ risk }) {
  const meta = risk.meta || {};
  const drawdownBand = meta.status !== 'ok'
    ? 'UNKNOWN'
    : risk.status === 'SAFE' ? 'DRAWDOWN_LE2'
      : risk.status === 'WARNING' ? 'DRAWDOWN_2_5'
        : risk.status === 'DANGER' ? 'DRAWDOWN_GT5' : 'UNKNOWN';
  return (
    <Panel eyebrow="交易所推导 · 有限" title="观察敞口" meta={meta} className="risk-panel">
      <div className="truth-grid">
        <div className="truth-item"><span>推导回撤区间</span><StatusBadge value={drawdownBand} tone={drawdownBand === 'UNKNOWN' ? 'unknown' : 'neutral'} /></div>
        <div className="truth-item"><span>当前回撤</span><KnownValue value={risk.currentDrawdown} meta={meta} format={(v) => v.toFixed(2)} suffix="%" /></div>
        <div className="truth-item"><span>未实现盈亏</span><KnownValue value={risk.totalPnl} meta={meta} format={(v) => v.toFixed(2)} suffix=" USDT" /></div>
        <div className="truth-item"><span>当日已实现盈亏</span><span className="unknown-value">未观测</span></div>
      </div>
      <p className="panel-note">当前 feed 的风险数据来自账户快照，不是 kernel 风险状态，也不证明日盈亏或累计收益。</p>
    </Panel>
  );
}

export function TradeObservations({ trades, meta }) {
  const observable = meta?.status === 'ok';
  return (
    <Panel eyebrow="交易所观察" title="近期成交观察" meta={meta} className="trades-panel">
      {!observable ? (
        <div className="empty-state warning-state"><strong>成交观察不可用</strong><span>未知状态不显示为空列表。</span></div>
      ) : trades.length === 0 ? (
        <div className="empty-state"><strong>交易所未返回近期成交</strong><span>这不是账本成交完整性的证明。</span></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>观察时间</th><th>方向</th><th className="number">数量</th><th className="number">价格</th><th className="number">已实现盈亏</th><th>来源</th></tr></thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id || `${trade.timestamp}-${trade.side}-${trade.quantity}`}>
                  <td>{trade.timestamp ? new Date(trade.timestamp).toLocaleString('zh-CN', { hour12: false }) : '未知'}</td>
                  <td><StatusBadge value={trade.side || 'UNKNOWN'} tone="info" compact /></td>
                  <td className="number">{Number.isFinite(Number(trade.quantity)) ? `${trade.quantity} BTC` : '未知'}</td>
                  <td className="number">{Number.isFinite(Number(trade.entryPrice)) ? `$${Number(trade.entryPrice).toLocaleString()}` : '未知'}</td>
                  <td className="number">{Number.isFinite(Number(trade.pnl)) ? `${Number(trade.pnl).toFixed(2)} USDT` : '未知'}</td>
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

export function AccountAssets({ account }) {
  const meta = account.meta || {};
  const observable = meta.status === 'ok';
  const assets = observable && Array.isArray(account.assets) ? account.assets : [];
  return (
    <Panel eyebrow="L2 · 交易所资金" title="账户资产观察" meta={meta} className="assets-panel">
      {!observable ? (
        <div className="empty-state warning-state">
          <strong>资产观察不可用</strong>
          <span>查询失败不显示为零值。</span>
        </div>
      ) : assets.length === 0 ? (
        <div className="empty-state"><strong>账户无可显示资产</strong></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>币种</th><th className="number">钱包余额</th><th className="number">可用</th><th className="number">未实现盈亏</th></tr></thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.asset}>
                  <td><strong>{asset.asset}</strong></td>
                  <td className="number">{Number(asset.walletBalance).toLocaleString('en-US', { maximumFractionDigits: 8 })}</td>
                  <td className="number">{Number(asset.availableBalance).toLocaleString('en-US', { maximumFractionDigits: 8 })}</td>
                  <td className="number">{Number(asset.unrealizedPnl).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="panel-note">币安期货测试网钱包观察 · 非链上钱包 · 账户非 AURORA 独占（EXCLUSIVITY=FALSE）。</p>
    </Panel>
  );
}
