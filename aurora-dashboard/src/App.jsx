import KLineChart from './components/KLineChart';
import {
  CapitalObjective,
  DataFreshness,
  GlobalSafety,
  MarketEvidence,
  ObservedRisk,
  PositionTruth,
  ProtectionTruth,
  RecoveryEvidence,
  TradeObservations,
} from './components/ObservatoryPanels';
import useWS from './hooks/useWS';

const POLICY_SNAPSHOT = Object.freeze({
  incidentLock: 'INCIDENT_LOCKED',
  kill: 'ACTIVE',
  executionQualified: false,
  autoTestnet: 'DENIED',
  live: 'NO_GO',
  authority: 'AUTHORITATIVE_INTERNAL · STATIC SNAPSHOT',
  source: 'CAPABILITY_STATUS',
  baseline: '8026c69',
});

function App() {
  const { system, market, risk, score, pnlData, trades, connected } = useWS();
  const accountMeta = system.meta || {};
  const marketMeta = market.meta || {};
  const riskMeta = risk.meta || {};
  const tradesMeta = trades.meta || {};
  const tradeRows = Array.isArray(trades.items) ? trades.items : [];

  const freshnessSections = [
    { name: 'Exchange account', meta: accountMeta },
    { name: 'Market bars', meta: marketMeta },
    { name: 'Risk observation', meta: riskMeta },
    { name: 'User trades', meta: tradesMeta },
    { name: 'Kernel ledger', meta: { status: 'unknown', source: 'NOT CONNECTED', updatedAt: null } },
  ];

  return (
    <div className="observatory-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <GlobalSafety policy={POLICY_SNAPSHOT} system={system} connected={connected} />

      <main id="main-content" className="observatory-main">
        <div className="section-intro">
          <div>
            <div className="eyebrow">OPERATING TRUTH FIRST</div>
            <h2>运行真相总览</h2>
          </div>
          <p>先确认授权、仓位、保护与恢复证据，再观察资本与市场。此界面不提供任何交易写能力。</p>
        </div>

        <div className="dashboard-grid primary-grid">
          <PositionTruth system={system} />
          <ProtectionTruth system={system} />
          <RecoveryEvidence policy={POLICY_SNAPSHOT} />
        </div>

        <div className="dashboard-grid capital-grid">
          <CapitalObjective />
          <DataFreshness sections={freshnessSections} connected={connected} />
        </div>

        <div className="section-intro secondary-intro">
          <div>
            <div className="eyebrow">OBSERVATION · NO EXECUTION AUTHORITY</div>
            <h2>市场与账户观察</h2>
          </div>
          <p>以下数据不生成交易许可；查询失败时保持 UNKNOWN，不以零值或空列表替代。</p>
        </div>

        <div className="dashboard-grid evidence-grid">
          <section className="panel chart-panel">
            <header className="panel-header">
              <div>
                <div className="eyebrow">L2 · EXCHANGE MARKET OBSERVATION</div>
                <h2>BTCUSDT · 1m</h2>
              </div>
              <span className="read-only-label">READ ONLY</span>
            </header>
            <div className="source-meta">
              <span>{marketMeta.source || 'SOURCE UNKNOWN'}</span>
              <span>·</span>
              <span>{(marketMeta.status || 'UNKNOWN').toUpperCase()}</span>
              <span>·</span>
              <span>{marketMeta.updatedAt ? new Date(marketMeta.updatedAt).toLocaleTimeString('zh-CN', { hour12: false }) : 'NO TIMESTAMP'}</span>
            </div>
            <div className="panel-body chart-body">
              <KLineChart marketData={market} />
            </div>
          </section>
          <MarketEvidence market={market} score={score} />
          <ObservedRisk risk={risk} />
        </div>

        <TradeObservations trades={tradeRows} meta={tradesMeta} />

        <section className="evidence-disclaimer" aria-label="观察面限制">
          <div className="disclaimer-index">BOUNDARY</div>
          <div>
            <strong>Exchange observation ≠ ledger reconciliation ≠ execution qualification</strong>
            <p>
              当前前台未接入 kernel projection。PnL 历史仅是当前会话中、账户快照成功时采集的未实现盈亏观察，
              共 {Array.isArray(pnlData) ? pnlData.length : 0} 个数据点，不构成资本绩效证明。
            </p>
          </div>
        </section>
      </main>

      <footer className="observatory-footer">
        <span>AURORA · CAPITAL & SAFETY OBSERVATORY</span>
        <span>READ-ONLY SURFACE</span>
        <span>LIVE · NO-GO</span>
      </footer>
    </div>
  );
}

export default App;
