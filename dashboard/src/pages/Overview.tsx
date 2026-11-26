import { lazy, Suspense, useState } from "react";
import { useForecasts } from "../services/forecasts";
import { ForecastReport } from "../models/ForecastReport";
import { eastern, session } from "../services/format";
import { MarketQuote } from "../components/MarketQuote";
const Market = lazy(() => import("./Market"));
const Performance = lazy(() => import("./Performance"));
const ForecastBreakdown = lazy(() => import("../components/Forecast").then(module => ({default: module.ForecastBreakdown})));

export default function Overview() {
  const forecasts = useForecasts();
  const [selected, setSelected] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const rows = forecasts.data?.rows ?? [];
  const row = rows.find(record => record.id === selected) ?? rows[0];
  const report = row && new ForecastReport(row);
  return (
    <>
      <MarketQuote />
      <section className="forecast-card" aria-labelledby="forecast-title">
        <header className="research-head">
          <h2 id="forecast-title">Five-session forecast</h2>
          {rows.length > 1 && <label className="record-select">Forecast origin
            <select value={rows.some(record => record.id === selected) ? selected : ""} onChange={e => setSelected(e.target.value)}>
              <option value="">Latest · {rows[0].origin}</option>
              {rows.slice(1).map(record => <option key={record.id} value={record.id}>{record.origin}</option>)}
            </select>
          </label>}
        </header>
        {row && report ? <>
          <p className="window" title={row.target_sessions.map(session).join(", ")}>
            {session(row.target_sessions[0])} – {session(row.target_sessions[4])}, {row.target_sessions[4].slice(0, 4)}
          </p>
          <p className="definition">Expected standard deviation of daily returns across this window.</p>
          <dl className="estimates">
            {report.estimates.map(({method, label, percent}) => (
              <div key={method} className={method}><dt>{label}</dt><dd>{percent.toFixed(3)}%</dd></div>
            ))}
          </dl>
          <p className="stamp">{report.studyLabel} · {session(row.origin)} close · Issued {eastern(row.issued_at_utc)}</p>
          <details className="model-details" onToggle={e => setDetailsOpen(e.currentTarget.open)}>
            <summary>Model inputs and forecast breakdown</summary>
            {detailsOpen && <Suspense fallback={<p role="status">Loading model details…</p>}>
              <ForecastBreakdown key={row.id} report={report} />
            </Suspense>}
          </details>
        </> : <p role="status">{forecasts.error ?? (forecasts.loading ? "Loading forecast…" : "No forecast available.")}</p>}
        {forecasts.localError && <p role="status">{forecasts.localError}</p>}
      </section>
      <div className="analysis-grid">
        <Suspense fallback={<p role="status">Loading research charts…</p>}>
          <Performance />
          <Market />
        </Suspense>
      </div>
    </>
  );
}
