import { MarketEvidence } from './ObservatoryPanels';

export default function MarketPanel({ market = {} }) {
  const score = market.meta?.status === 'ok' && Number.isFinite(Number(market.confidence))
    ? Math.round(Number(market.confidence) * 100)
    : null;
  return <MarketEvidence market={market} score={score} />;
}
