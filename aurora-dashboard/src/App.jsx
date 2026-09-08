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
  AccountAssets,
  zhLabel,
} from './components/ObservatoryPanels';
import useWS from './hooks/useWS';

const POLICY_SNAPSHOT = Object.freeze({
  incidentLock: 'INCIDENT_LOCKED',
  kill: 'ACTIVE',
  executionQualified: false,
  autoTestnet: 'DENIED',
  live: 'NO_GO',
  authority: '内部权威 · 静态快照',
  source: '能力台账',
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
    { name: '交易所账户', meta: accountMeta },
    { name: '行情K线', meta: marketMeta },
    { name: '风险观察', meta: riskMeta },
    { name: '用户成交', meta: tradesMeta },
    { name: '内核账本', meta: { status: 'unknown', source: 'NOT CONNECTED', updatedAt: null } },
  ];

  return (
    <div className="observatory-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <GlobalSafety policy={POLICY_SNAPSHOT} system={system} connected={connected} />

      <main id="main-content" className="observatory-main">
        <div className="section-intro">
          <div>
            <div className="eyebrow">运行真相优先</div>
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
          <AccountAssets account={system} />
          <DataFreshness sections={freshnessSections} connected={connected} />
        </div>

        <div className="section-intro secondary-intro">
          <div>
            <div className="eyebrow">观察 · 无执行权限</div>
            <h2>市场与账户观察</h2>
          </div>
          <p>以下数据不生成交易许可；查询失败时保持未知，不以零值或空列表替代。</p>
        </div>

        <div className="dashboard-grid evidence-grid">
          <section className="panel chart-panel">
            <header className="panel-header">
              <div>
                <div className="eyebrow">L2 · 交易所行情观察</div>
                <h2>BTCUSDT · 1 分钟</h2>
              </div>
              <span className="read-only-label">只读</span>
            </header>
            <div className="source-meta">
              <span>{zhLabel(marketMeta.source) || '来源未知'}</span>
              <span>·</span>
              <span>{zhLabel((marketMeta.status || 'UNKNOWN').toUpperCase())}</span>
              <span>·</span>
              <span>{marketMeta.updatedAt ? new Date(marketMeta.updatedAt).toLocaleTimeString('zh-CN', { hour12: false }) : '无时间戳'}</span>
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
          <div className="disclaimer-index">边界</div>
          <div>
            <strong>交易所观察 ≠ 账本对账 ≠ 执行资格</strong>
            <p>
              当前前台未接入内核投影。PnL 历史仅是当前会话中、账户快照成功时采集的未实现盈亏观察，
              共 {Array.isArray(pnlData) ? pnlData.length : 0} 个数据点，不构成资本绩效证明。
            </p>
          </div>
        </section>
      </main>

      <footer className="observatory-footer">
        <span>AURORA · 资本与安全观察台</span>
        <span>只读观察面</span>
        <span>实盘 · 禁止</span>
      </footer>
    </div>
  );
}

export default App;
