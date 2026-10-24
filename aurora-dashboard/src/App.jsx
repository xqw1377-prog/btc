import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AnalysisRow,
  DecisionBrain,
  GlobalBar,
  OperationsRow,
} from "./cockpit/CockpitPanels";
import { SCENARIOS, scenarioById } from "./cockpit/fixtures";
import { sceneFromFeed } from "./cockpit/sceneFromFeed";
import useWS from "./hooks/useWS";
import PrototypeDock from "./prototype/PrototypeDock";

const OBSERVE_ID = "observe";

function parseHash() {
  const raw = window.location.hash.replace("#", "");
  const [id] = raw.split("/");
  if (id === OBSERVE_ID || id === "live") return { id: OBSERVE_ID, diag: false };
  return {
    id: SCENARIOS.some((s) => s.id === id) ? id : "disconnected",
    diag: false,
  };
}

function useScenario() {
  const [scenarioId, setScenarioId] = useState(() => parseHash().id);
  const writeHash = useCallback((id) => {
    if (window.location.hash.replace("#", "") !== id) {
      window.location.hash = id;
    }
  }, []);
  const setScenario = useCallback(
    (id) => {
      setScenarioId(id);
      writeHash(id);
    },
    [writeHash],
  );
  useEffect(() => {
    const onHash = () => setScenarioId(parseHash().id);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return [scenarioId, setScenario];
}

function App() {
  const [scenarioId, setScenario] = useScenario();
  const [focus, setFocus] = useState(null);
  const isObserve = scenarioId === OBSERVE_ID;
  const { observatory, connected, market, system } = useWS();

  const scene = useMemo(() => {
    if (isObserve) {
      return sceneFromFeed({
        observatory,
        connected,
        marketMeta: market.meta,
        accountMeta: system.meta,
      });
    }
    return scenarioById(scenarioId);
  }, [isObserve, observatory, connected, market.meta, system.meta, scenarioId]);

  const handleCardSelect = useCallback((id) => {
    setFocus((prev) => (prev === id ? null : id));
  }, []);

  useEffect(() => {
    if (!focus) return undefined;
    const timer = window.setTimeout(() => setFocus(null), 2500);
    return () => window.clearTimeout(timer);
  }, [focus]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key >= "1" && event.key <= "5") {
        const next = SCENARIOS[Number(event.key) - 1];
        if (next) setScenario(next.id);
      }
      if (event.key === "6" || event.key === "o" || event.key === "O") {
        setScenario(OBSERVE_ID);
      }
      if (event.key === "Escape") setFocus(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setScenario]);

  return (
    <div className="cockpit-shell">
      <GlobalBar scene={scene} />
      <div className="cockpit-body">
        <DecisionBrain scene={scene} focus={focus} onCardSelect={handleCardSelect} />
        <div className="cockpit-right">
          <AnalysisRow scene={scene} focus={focus} />
          <OperationsRow scene={scene} focus={focus} />
        </div>
      </div>
      <PrototypeDock scenarioId={scenarioId} onScenario={setScenario} diagnosticOpen={false} onDiagnostic={() => {}} hideDiagnostic />
    </div>
  );
}

export default App;
