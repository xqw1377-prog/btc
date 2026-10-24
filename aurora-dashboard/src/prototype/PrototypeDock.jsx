import { SCENARIOS } from "../cockpit/fixtures";

const VIEW_LABELS = ["Overview", "Trend", "Events", "Position", "Decision"];
const OBSERVE_ID = "observe";

export default function PrototypeDock({
  scenarioId,
  onScenario,
  diagnosticOpen,
  onDiagnostic,
  hideDiagnostic = false,
}) {
  return (
    <aside className="prototype-dock" aria-label="观察台原型控制">
      <div className="prototype-dock-label">
        <span>PROTOTYPE</span>
        <em>Internal Evaluation Only · D1 observatory · 6=REALTIME READ ONLY</em>
      </div>
      <div className="prototype-dock-actions" role="tablist" aria-label="状态夹具">
        {SCENARIOS.map((scenario, index) => (
          <button
            key={scenario.id}
            type="button"
            role="tab"
            aria-selected={scenario.id === scenarioId}
            className={scenario.id === scenarioId ? "is-active" : ""}
            onClick={() => onScenario(scenario.id)}
            title={VIEW_LABELS[index] || scenario.label}
          >
            <kbd>{index + 1}</kbd>
            {scenario.label}
          </button>
        ))}
        <button
          type="button"
          role="tab"
          aria-selected={scenarioId === OBSERVE_ID}
          className={scenarioId === OBSERVE_ID ? "is-active is-realtime-tab" : "is-realtime-tab"}
          onClick={() => onScenario(OBSERVE_ID)}
          title="WebSocket observatory · read only · not live trading"
        >
          <kbd>6</kbd>
          REALTIME
        </button>
      </div>
      {!hideDiagnostic ? (
        <button
          type="button"
          className={diagnosticOpen ? "is-active" : ""}
          aria-pressed={diagnosticOpen}
          onClick={() => onDiagnostic((open) => !open)}
        >
          <kbd>D</kbd>
          1m 诊断
        </button>
      ) : null}
      <span className="prototype-dock-hint">1–5 夹具 · 6 REALTIME 只读 · ESC 取消高亮</span>
    </aside>
  );
}
