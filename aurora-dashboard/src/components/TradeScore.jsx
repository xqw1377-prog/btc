import { MarketEvidence } from './ObservatoryPanels';

export default function TradeScore({ score = null, market = {} }) {
  return <MarketEvidence market={market} score={score} />;
}
