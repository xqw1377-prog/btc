import { ObservedRisk } from './ObservatoryPanels';

export default function RiskPanel({ risk = {} }) {
  return <ObservedRisk risk={risk} />;
}
