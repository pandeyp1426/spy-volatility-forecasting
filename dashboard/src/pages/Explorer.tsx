import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { HistoricalAccuracy } from "../components/HistoricalAccuracy";
import { useForecasts } from "../services/forecasts";
import { PageTitle, Panel, DataState, formatDate } from "../components/UI";
import {
  ForecastDetail,
  timingLabels,
  studyLabels,
} from "../components/Forecast";
import {
  methods,
  methodNames,
  type Forecast,
  type Method,
} from "../types/public";
export function filterRows(
  rows: Forecast[],
  q: string,
  study: string,
  from: string,
  to: string,
  sort: string,
  method: Method,
) {
  return rows
    .filter(
      (f) =>
        (study === "all" || f.study === study) &&
        (!from || f.origin >= from) &&
        (!to || f.origin <= to) &&
        (
          f.origin +
          " " +
          studyLabels[f.study] +
          " " +
          timingLabels[f.timing] +
          " " +
          methodNames[method] +
          " " +
          f.model_id
        )
          .toLowerCase()
          .includes(q.trim().toLowerCase()),
    )
    .sort((a, b) =>
      sort === "oldest"
        ? a.origin.localeCompare(b.origin)
        : sort === "highest"
          ? b.predictions_pct[method] - a.predictions_pct[method]
          : b.origin.localeCompare(a.origin),
    );
}
export default function Explorer() {
  const { id } = useParams(),
    state = useForecasts(),
    [q, search] = useState(""),
    [study, setStudy] = useState("all"),
    [sort, setSort] = useState("newest"),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [method, setMethod] = useState<Method | "all">("all"),
    [page, setPage] = useState(0);
  const rows = filterRows(
      state.data?.rows || [],
      q,
      study,
      from,
      to,
      sort,
      method === "all" ? "ridge" : method,
    ),
    columns = method === "all" ? methods : [method],
    pages = Math.ceil(rows.length / 10),
    p = Math.min(page, Math.max(0, pages - 1));
  const selected = state.data?.rows.find((f) => f.id === id);
  return (
    <div className="stack">
      <PageTitle
        eyebrow="Forecast archive"
        title="Forecast explorer"
        description={state.localIds.size ? "Explore approved records and verified local 2026 pilots. Local pilots await public release approval." : "Inspect approved forecasts, their input vintages and the five trading sessions covered by each prediction."}
      />
      {state.localError && <p className="notice" role="status">{state.localError}</p>}
      {id ? (
        <>
          <Link to="/forecasts">Back to forecast history</Link>
          {!state.data ? (
            <DataState {...state} />
          ) : selected ? (
            <Panel
              title={
                (selected.study === "manual_pilot_2026"
                  ? "Historical Manual Pilot"
                  : studyLabels[selected.study]) +
                " — " +
                formatDate(selected.origin)
              }
              description={[timingLabels[selected.timing], state.localIds.has(selected.id) && "Local pilot preview"].filter(Boolean).join(" · ")}
            >
              <ForecastDetail f={selected} />
            </Panel>
          ) : (
            <p className="notice">
              This forecast ID does not appear in the approved release.
            </p>
          )}
        </>
      ) : (
        <>
          <Panel title="Forecast history">
            <div className="filters">
              <label>
                Search
                <input
                  type="search"
                  placeholder="Date, study or model"
                  value={q}
                  onChange={(e) => {
                    search(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <label>
                Study
                <select
                  value={study}
                  onChange={(e) => {
                    setStudy(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="all">All studies</option>
                  {Object.entries(studyLabels).map(([k, v]) => (
                    <option value={k} key={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Method
                <select
                  value={method}
                  onChange={(e) => setMethod(e.target.value as Method | "all")}
                >
                  <option value="all">All methods</option>
                  {methods.map((m) => (
                    <option value={m} key={m}>
                      {methodNames[m]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                From
                <input
                  type="date"
                  value={from}
                  onChange={(e) => {
                    setFrom(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <label>
                Through
                <input
                  type="date"
                  value={to}
                  onChange={(e) => {
                    setTo(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <label>
                Sort
                <select value={sort} onChange={(e) => setSort(e.target.value)}>
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                  <option value="highest">
                    Highest selected forecast (default Ridge)
                  </option>
                </select>
              </label>
            </div>
            {!state.data ? (
              <DataState {...state} />
            ) : !rows.length ? (
              <p className="notice">
                No approved forecasts match these filters.
              </p>
            ) : (
              <>
                <div className="tablewrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Origin</th>
                        <th>Target window</th>
                        {columns.map((m) => (
                          <th key={m}>{methodNames[m]} (%)</th>
                        ))}
                        <th>Status</th>
                        <th>Outcome</th>
                        <th>Study</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(10 * p, 10 * p + 10).map((f) => (
                        <tr key={f.id}>
                          <td>
                            <Link to={"/forecasts/" + f.id}>{f.origin}</Link>
                          </td>
                          <td>
                            {f.target_sessions[0]} – {f.target_sessions[4]}
                          </td>
                          {columns.map((m) => (
                            <td key={m}>{f.predictions_pct[m].toFixed(4)}</td>
                          ))}
                          <td>{timingLabels[f.timing]}</td>
                          <td>{f.outcome_status}</td>
                          <td>{studyLabels[f.study]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="pager">
                  <button disabled={p === 0} onClick={() => setPage(p - 1)}>
                    Previous
                  </button>{" "}
                  Page {p + 1} of {pages}{" "}
                  <button
                    disabled={p + 1 >= pages}
                    onClick={() => setPage(p + 1)}
                  >
                    Next
                  </button>
                </div>
              </>
            )}
          </Panel>
          <HistoricalAccuracy />
        </>
      )}
    </div>
  );
}
