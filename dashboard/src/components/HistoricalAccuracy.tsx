import { useState } from "react";
import { LineChart, Line, ResponsiveContainer, ReferenceLine, XAxis, YAxis } from "recharts";
import { useDataset } from "../services/data";
import { methods, methodNames, type Method } from "../types/public";
import { DataState, Panel } from "./UI";
import { axis, chartTip, ChartData, ChartLegend, grid, methodColors, Segments } from "./ResearchCharts";

export function HistoricalAccuracy() {
  const state = useDataset("observations"),
    [method, setMethod] = useState<Method>("ridge"),
    [view, setView] = useState<"levels" | "signed" | "absolute">("levels"),
    [year, setYear] = useState("all");
  const rows =
    state.data?.rows.filter((r) => year === "all" || r.date.startsWith(year)) ||
    [];
  const key = view === "levels" ? method : (`${method}_${view}` as const),
    unit = view === "levels" ? "%" : "pp";
  return (
    <Panel
      title="Historical forecast errors"
      description="Historical development sample. Each observation covers the following five sessions."
    >
      <div className="filters">
        <label>
          Method
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as Method)}
          >
            {methods.map((m) => (
              <option key={m} value={m}>
                {methodNames[m]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Forecast year
          <select value={year} onChange={(e) => setYear(e.target.value)}>
            <option value="all">All years</option>
            {[...new Set(state.data?.rows.map((r) => r.date.slice(0, 4)))].map(
              (y) => (
                <option key={y}>{y}</option>
              ),
            )}
          </select>
        </label>
        <Segments
          label="Historical accuracy chart"
          value={view}
          onChange={setView}
          options={[
            { value: "levels", label: "Forecast & observed" },
            { value: "signed", label: "Signed error" },
            { value: "absolute", label: "Absolute error" },
          ]}
        />
      </div>
      {!state.data ? (
        <DataState {...state} />
      ) : (
        <>
          <p className="unit">
            {rows.length.toLocaleString()} origins ·{" "}
            {view === "levels"
              ? "Daily volatility (%)"
              : "Daily-volatility error (pp)"}
          </p>
          <div className="largeplot">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} accessibilityLayer>
                {grid}
                <XAxis {...axis} dataKey="date" minTickGap={35} />
                <YAxis {...axis} width={40} />
                {chartTip(unit, 4)}
                {view !== "levels" && <ReferenceLine y={0} stroke="#8794a5" />}
                {view === "levels" && (
                  <Line
                    dataKey="observed"
                    stroke="#cad4e4"
                    dot={false}
                    strokeDasharray="3 2"
                    name="Observed"
                    isAnimationActive={false}
                  />
                )}
                <Line
                  dataKey={key}
                  stroke={methodColors[method]}
                  dot={false}
                  name={methodNames[method]}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ChartLegend
            items={[
              { name: methodNames[method], color: methodColors[method] },
              ...(view === "levels"
                ? [{ name: "Observed", color: "#cad4e4" }]
                : []),
            ]}
          />
          <ChartData
            name="historical-forecast-errors"
            rows={rows}
            columns={[
              { label: "Origin", value: (r) => r.date },
              { label: "Observed (%)", value: (r) => r.observed },
              { label: methodNames[method] + " (%)", value: (r) => r[method] },
              {
                label: "Signed error (pp)",
                value: (r) => r[`${method}_signed`],
              },
              {
                label: "Absolute error (pp)",
                value: (r) => r[`${method}_absolute`],
              },
            ]}
          />
        </>
      )}
    </Panel>
  );
}
