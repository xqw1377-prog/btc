import { TradeObservations } from './ObservatoryPanels';

export default function TradeList({ trades = [], meta = { status: 'unknown' } }) {
  return <TradeObservations trades={Array.isArray(trades) ? trades : []} meta={meta} />;
}
