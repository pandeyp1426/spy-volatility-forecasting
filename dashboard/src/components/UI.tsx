import type { ReactNode } from "react";
import { Activity, Check, RotateCw } from "lucide-react";
import { useDataset } from "../services/data";
export const repo = "https://github.com/pandeyp1426/spy-volatility-forecasting";
export function PageTitle({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="page-title">
      <div className="kicker">
        <span />
        {eyebrow}
      </div>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}
export function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {description && <p className="panel-desc">{description}</p>}
      {children}
    </section>
  );
}
export function DataState({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error: string | null;
  retry: () => void;
}) {
  return (
    <div className="data-state" role="status">
      <Activity size={18} />
      {loading
        ? "Loading verified research data…"
        : error || "No approved observations are available."}
      {error && (
        <button onClick={retry}>
          <RotateCw size={14} /> Retry
        </button>
      )}
    </div>
  );
}
export function Milestones() {
  const state = useDataset("status");
  return (
    <Panel title="Research progress">
      {state.data ? (
        <>
          <ul className="milestones">
            {state.data.milestones.map((x) => (
              <li key={x}>
                <Check size={16} />
                {x}
              </li>
            ))}
          </ul>
          <small>
            Reviewed {state.data.reviewed_on} · Collection:{" "}
            {state.data.collector} · Formal study: {state.data.formal}
          </small>
        </>
      ) : (
        <DataState {...state} />
      )}
    </Panel>
  );
}
export function formatDate(day: string, short = false) {
  return new Intl.DateTimeFormat("en-US", {
    month: short ? "short" : "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(day + "T00:00:00Z"));
}
export function utc(iso: string) {
  return new Date(iso).toISOString().slice(0, 19).replace("T", " ") + " UTC";
}
