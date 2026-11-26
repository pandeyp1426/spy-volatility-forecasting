import { useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import {
  axis,
  chartTip,
  ChartData,
  methodColors,
  Segments,
} from "./ResearchCharts";
import { methods, methodNames, type Forecast } from "../types/public";
import { ForecastReport, type ComparisonMetric } from "../models/ForecastReport";
export const timingLabels = {
  historical_manual_pilot: "Historical manual pilot",
  local_on_time: "Locally on time",
  late: "Late diagnostic",
};
export const studyLabels = {
  manual_pilot_2026: "November 11 manual pilot",
  pilot_2026: "2026 operational pilots",
  formal_2027: "Formal 2027 study",
};
export function ModelInputs({ report }: { report: ForecastReport }) {
  return <>
    <p className="model-note">Ridge standardizes these five inputs with its training scaler, applies its frozen coefficients and floors the estimate at zero. Volatility uses the sample standard deviation of daily log returns.</p>
    <dl className="model-inputs">
      {report.inputs.map(({key, label, percent}) => <div key={key}>
        <dt>{label}</dt><dd>{percent.toFixed(4)}%</dd>
      </div>)}
    </dl>
    <small>Inputs from {report.record.source} · Model <code>{report.record.model_id}</code></small>
  </>;
}
export function Compare({
  report,
  showErrors = false,
}: {
  report: ForecastReport;
  showErrors?: boolean;
}) {
  const [view, setView] = useState<ComparisonMetric>("levels");
  const {values, label: metric, unit} = report.comparison(showErrors ? view : "levels");
  const names = {ridge: "Ridge", hv5: "5-session", hv20: "20-session", observed: "Observed"};
  const rows = values.map(({method, value}) => ({
    name: names[method],
    value,
    color: method === "observed" ? "#dddfe9" : methodColors[method],
  }));
  return (
    <>
      {showErrors && report.record.outcome && (
        <Segments
          label="Pilot comparison metric"
          value={view}
          onChange={setView}
          options={[
            { value: "levels", label: "Forecast & observed" },
            { value: "signed_error_pp", label: "Signed error" },
            { value: "absolute_error_pp", label: "Absolute error" },
          ]}
        />
      )}
      <p className="unit">
        {metric} ({unit})
      </p>
      <div className="compareplot">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 6, right: 18, bottom: 4, left: 0 }}
            accessibilityLayer
          >
            <XAxis
              {...axis}
              type="number"
              tickFormatter={(v) => v + unit}
              tickCount={4}
            />
            <YAxis {...axis} type="category" dataKey="name" width={78} />
            {chartTip(unit, 4)}
            {unit === "pp" && <ReferenceLine x={0} stroke="#adbfcd" />}
            <Bar
              dataKey="value"
              name={metric}
              barSize={17}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
            >
              {rows.map((r) => (
                <Cell key={r.name} fill={r.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartData
        name="forecast-comparison"
        rows={rows}
        columns={[
          { label: "Method or observation", value: (r) => r.name },
          { label: metric + " (" + unit + ")", value: (r) => r.value },
        ]}
      />
    </>
  );
}
export function ForecastBreakdown({ report }: { report: ForecastReport }) {
  const { outcome, outcome_status } = report.record;
  let outcomeText = "Outcome pending.";
  if (outcome) outcomeText = "Observed five-session volatility " + outcome.observed_pct.toFixed(4) + "%";
  if (outcome_status === "withheld") outcomeText = "Outcome withheld under the 2027 protocol.";
  return <div className="breakdown">
    <div><h3>Frozen Ridge inputs</h3><ModelInputs report={report} /></div>
    <div>
      <h3>{outcome ? "Forecast and observed volatility" : "Forecast comparison"}</h3>
      <Compare report={report} showErrors />
      <small>{outcomeText}</small>
    </div>
  </div>;
}

export function ForecastDetail({ f }: { f: Forecast }) {
  const report = new ForecastReport(f);
  return (
    <div className="details">
      <dl>
        {Object.entries({
          "Issued (UTC)": f.issued_at_utc,
          "Input vintage (UTC)": f.acquired_at_utc,
          "Scheduled close (UTC)": f.scheduled_close_utc,
          Source: f.source,
          "Model bundle": f.model_id,
          Validation: f.validation,
          "Five target sessions": f.target_sessions.join(" · "),
        }).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <h3>Frozen model inputs</h3>
      <ModelInputs report={report} />
      <h3>Forecast and outcome</h3>
      <Compare report={report} showErrors />
      {f.outcome ? (
        <>
          <p>
            Observed daily volatility{" "}
            <b>{f.outcome.observed_pct.toFixed(6)}%</b> · acquired{" "}
            {f.outcome.acquired_at_utc}
          </p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Forecast (%)</th>
                  <th>Signed error (pp)</th>
                  <th>Absolute error (pp)</th>
                </tr>
              </thead>
              <tbody>
                {methods.map((k) => (
                  <tr key={k}>
                    <td>{methodNames[k]}</td>
                    <td>{f.predictions_pct[k].toFixed(6)}</td>
                    <td>{f.outcome!.signed_error_pp[k].toFixed(6)}</td>
                    <td>{f.outcome!.absolute_error_pp[k].toFixed(6)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="notice">
          {f.outcome_status === "withheld"
            ? "Outcome comparison withheld under the prospective evaluation protocol."
            : "Outcome pending."}
        </p>
      )}
    </div>
  );
}
