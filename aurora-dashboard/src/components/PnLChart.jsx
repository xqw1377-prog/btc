import { Panel, StatusBadge } from './ObservatoryPanels';

export default function PnLChart({ data = [] }) {
  const observed = Array.isArray(data) && data.length > 0;
  return (
    <Panel eyebrow="SESSION OBSERVATION · NOT ACCOUNTING" title="Unrealized PnL Samples">
      <div className="truth-grid">
        <div className="truth-item"><span>Session samples</span><strong>{observed ? data.length : 'NOT AVAILABLE'}</strong></div>
        <div className="truth-item"><span>BTC performance</span><StatusBadge value="NOT AVAILABLE" /></div>
        <div className="truth-item"><span>Realized PnL</span><StatusBadge value="NOT OBSERVED" /></div>
        <div className="truth-item"><span>Accounting authority</span><StatusBadge value="NONE" tone="danger" /></div>
      </div>
      <div className="invariant-callout">Session unrealized observations ≠ ledger PnL ≠ BTC performance.</div>
    </Panel>
  );
}
