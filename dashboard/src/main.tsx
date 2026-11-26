import { createRoot } from "react-dom/client";
import { RefreshCw } from "lucide-react";
import { checkPublication, usePublicationMonitor } from "./services/data";
import Overview from "./pages/Overview";
import "./styles/forecast.css";

function Dashboard() {
  const publication = usePublicationMonitor();
  const checked = publication.checkedAt;
  const release = publication.release?.manifest.generated_at;
  function refresh() {
    window.dispatchEvent(new Event("research-refresh"));
    void checkPublication();
  }
  return (
    <main className="dashboard">
      <header className="dashboard-head">
        <h1>SPY volatility forecast</h1>
        <button onClick={refresh} disabled={publication.checking} aria-label="Refresh data" title="Refresh data">
          <RefreshCw size={16} aria-hidden="true" /> Refresh
        </button>
      </header>
      <Overview />
      <footer>
        {publication.failed ? <span role="status">Public release check failed.</span> :
          checked && <span title={release ? "Public release: " + new Date(release).toUTCString() : undefined}>Release checked {new Date(checked).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}</span>}
      </footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Dashboard />);
