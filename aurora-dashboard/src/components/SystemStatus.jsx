import { Panel, SourceMeta, StatusBadge } from './ObservatoryPanels';

export default function SystemStatus({ state = {} }) {
  const meta = state.meta || { status: 'unknown' };
  return (
    <Panel eyebrow="L2 · EXCHANGE OBSERVATION" title="Observation Status">
      <SourceMeta meta={meta} />
      <div className="truth-grid">
        <div className="truth-item"><span>Transport mode</span><StatusBadge value={meta.mode || 'UNKNOWN'} tone="info" /></div>
        <div className="truth-item"><span>Position observation</span><StatusBadge value={meta.status === 'ok' ? state.positionsState || 'UNKNOWN' : 'UNKNOWN'} /></div>
        <div className="truth-item"><span>Protection</span><StatusBadge value={meta.protectionStatus || 'NOT_VERIFIED'} /></div>
        <div className="truth-item"><span>Ledger reconciliation</span><StatusBadge value="NOT OBSERVED" /></div>
      </div>
      <div className="invariant-callout">Connection state never means system health.</div>
    </Panel>
  );
}
