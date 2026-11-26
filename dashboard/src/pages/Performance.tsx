import { useState } from "react";
import { Layers3, Waypoints } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { History } from "../types/history";
import { useDataset } from "../services/data";
import { DataState, Panel } from "../components/UI";
import { HistoricalAccuracy } from "../components/HistoricalAccuracy";
import {
  axis,
  ChartData,
  ChartLegend,
  ChartSurface,
  chartTip,
  grid,
  methodColors,
  methodNames,
  pretty,
  Segments,
} from "../components/ResearchCharts";

const cmp = ["hv20", "hv5", "ridge"] as const;
const metrics = [
  { value: "rmse", label: "RMSE" },
  { value: "mae", label: "MAE" },
  { value: "bias", label: "Bias" },
  { value: "all", label: "All metrics" },
] as const;
type Metric = (typeof metrics)[number]["value"];
const metricColors = {
  rmse: methodColors.ridge,
  mae: methodColors.hv5,
  bias: methodColors.hv20,
};
const metricNames = { rmse: "RMSE", mae: "MAE", bias: "Signed bias" };
const metricDescriptions: Record<Metric, string> = {
  rmse: "Lower RMSE is better. Large misses carry more weight.",
  mae: "Lower MAE means a smaller average absolute error.",
  bias: "Signed bias averages predicted minus observed volatility. Negative values indicate underprediction on average.",
  all: "Each metric uses the same forecast origins. MAE and RMSE measure error size. Signed bias measures its direction.",
};
const shortName: Record<string, string> = {
  "Random forest": "Forest",
  "Gradient boosting": "Boosting",
};
const highColumns = [
  {
    label: "Method",
    value: (r: History["tail"][number]) => methodNames[r.method],
  },
  { label: "N", value: (r: History["tail"][number]) => String(r.n) },
  ...(["rmse", "mae", "bias"] as const).map((k) => ({
    label: metricNames[k] + " (pp)",
    value: (r: History["tail"][number]) => r[k],
  })),
];

function Overall({ rows }: { rows: History["performance"] }) {
  const [metric, setMetric] = useState<Metric>("rmse");
  const keys = metric === "all" ? (["rmse", "mae", "bias"] as const) : [metric];
  const chartRows = rows.map((r) => ({ ...r, label: methodNames[r.method] }));
  return (
    <Panel
      title="Overall model comparison"
    >
      <Segments
        value={metric}
        onChange={setMetric}
        options={metrics}
        label="Historical error metric"
      />
      <ChartSurface
        title="Historical errors by forecasting method"
        axisLabel="Error · daily-volatility percentage points"
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartRows}
            margin={{ top: 20, right: 12, left: 0, bottom: 4 }}
            accessibilityLayer
            barCategoryGap="20%"
          >
            {grid}
            <XAxis
              {...axis}
              dataKey="label"
              tickFormatter={(v) => shortName[v] ?? v}
              tickMargin={8}
              interval={0}
            />
            <YAxis {...axis} width={42} />
            <ReferenceLine y={0} stroke="#8d9eb3" />
            {chartTip("pp", 5)}
            {keys.map((k) => (
              <Bar
                dataKey={k}
                key={k}
                name={metricNames[k]}
                fill={metricColors[k]}
                maxBarSize={52}
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              >
                {metric !== "all" &&
                  rows.map((r) => (
                    <Cell key={r.method} fill={methodColors[r.method]} />
                  ))}
                {metric !== "all" && (
                  <LabelList dataKey={k} position="top" fill="#dce8f0" fontSize={11}
                    formatter={(value: number) => value.toFixed(3)} />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartSurface>
      {metric === "all" && (
        <ChartLegend
          items={keys.map((k) => ({
            name: metricNames[k],
            color: metricColors[k],
          }))}
        />
      )}
      <p className="rc-note">{metricDescriptions[metric]}</p>
      <ChartData
        rows={rows}
        columns={highColumns}
        name="temporal-model-performance"
      />
    </Panel>
  );
}

const sampleNotes = {
  Original: "All eligible historical annual temporal-evaluation observations.",
  Contained:
    "Both ends of the five-session outcome window fall in the year of its forecast origin.",
  "Every fifth":
    "Offset zero retains origins divisible by five on the original trading grid. Their scored future-return windows are disjoint.",
  Both: "Annual containment and offset-zero sampling apply together.",
};
function Sensitivity({ rows }: { rows: History["sensitivity"] }) {
  const [sample, setSample] = useState<keyof typeof sampleNotes>("Original");
  const selected = rows.find((r) => r.sample === sample);
  return (
    <Panel
      title="Sensitivity to the evaluation sample"
      description="The same fitted forecasts are scored under four rules. Changing the sample changes which observations contribute to RMSE."
    >
      {selected ? (
        <>
          <Segments
            label="Scoring sample"
            value={sample}
            options={rows.map((r) => ({ value: r.sample, label: r.sample }))}
            onChange={setSample}
          />
          <div className="rc-callout">
            <Layers3 size={20} aria-hidden="true" />
            <div>
              <strong>{selected.n.toLocaleString()} observations</strong>
              <p>{sampleNotes[sample]}</p>
            </div>
          </div>
          <ChartSurface
            title={"Historical RMSE on " + sample + " sample"}
            axisLabel="RMSE · percentage points"
            compact
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={[selected]}
                margin={{ top: 8, right: 12, bottom: 0, left: 0 }}
                barGap="8%"
                accessibilityLayer
              >
                {grid}
                <XAxis {...axis} dataKey="sample" />
                <YAxis {...axis} width={42} domain={[0, "auto"]} />
                {chartTip("pp", 6)}
                {cmp.map((m) => (
                  <Bar
                    key={m}
                    dataKey={m}
                    name={methodNames[m]}
                    fill={methodColors[m]}
                    maxBarSize={90}
                    radius={[3, 3, 0, 0]}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </ChartSurface>
          <ChartLegend
            items={cmp.map((m) => ({
              name: methodNames[m],
              color: methodColors[m],
            }))}
          />
        </>
      ) : (
        <p className="rc-empty">This sample has no approved metrics.</p>
      )}
      <ChartData
        rows={rows}
        columns={[
          { label: "Sample", value: (r) => r.sample },
          { label: "N", value: (r) => String(r.n) },
          ...cmp.map((m) => ({
            label: methodNames[m] + " RMSE (pp)",
            value: (r: History["sensitivity"][number]) => r[m],
          })),
        ]}
        name="temporal-sensitivity"
      />
    </Panel>
  );
}

function Offsets({ rows }: { rows: History["offsets"] }) {
  const [offset, setOffset] = useState(0);
  const selected = rows.find((r) => r.offset === offset);
  return (
    <Panel
      title="Does the starting session matter?"
      description="Choose an offset k to retain original session positions whose remainder after division by five equals k. The numbering continues across calendar years."
    >
      <Segments
        value={offset}
        onChange={setOffset}
        options={rows.map((r) => ({
          value: r.offset,
          label: "k = " + r.offset,
        }))}
        label="Modulo-five offset"
      />
      <div
        className="rc-position-grid"
        aria-label={`Illustrative original positions 0 to 14, retained remainder ${offset}`}
      >
        {Array.from({ length: 15 }, (_, i) => (
          <span
            key={i}
            className={i % 5 === offset ? "selected" : ""}
            aria-label={`Position ${i}${i % 5 === offset ? ", retained" : ", omitted"}`}
          >
            {i}
          </span>
        ))}
      </div>
      <p className="rc-x-label">
        Illustrative original-session positions · Highlighted positions are
        retained
      </p>
      {selected && (
        <div className="rc-offset-metrics">
          <div>
            <span>Retained origins</span>
            <strong>{selected.n}</strong>
          </div>
          <div>
            <span>RMSE reduction vs 20-session</span>
            <strong>{pretty(selected.vs20, 2)}%</strong>
          </div>
          <div>
            <span>RMSE reduction vs 5-session</span>
            <strong>{pretty(selected.vs5, 2)}%</strong>
          </div>
        </div>
      )}
      <p className="rc-note">
        Reduction is 100 × (1 − Ridge RMSE / benchmark RMSE). The five offsets
        share model fits and underlying market history, so their results are
        dependent.
      </p>
      <ChartData
        rows={rows}
        columns={[
          { label: "Offset", value: (r) => String(r.offset) },
          { label: "N", value: (r) => String(r.n) },
          { label: "Reduction vs 20-session (%)", value: (r) => r.vs20 },
          { label: "Reduction vs 5-session (%)", value: (r) => r.vs5 },
        ]}
        name="temporal-offset-gains"
      />
    </Panel>
  );
}

function Intervals({ study }: { study: History["uncertainty"] }) {
  const series = study.intervals.map((r, i) => ({
    ...r,
    row: i,
    span: [r.estimate - r.lower, r.upper - r.estimate],
  }));
  if (!series.length)
    return <p className="rc-empty">Bootstrap intervals are unavailable.</p>;
  const min = Math.min(0, ...series.map((r) => r.lower));
  const max = Math.max(0, ...series.map((r) => r.upper));
  const pad = (max - min) * 0.1 || 0.01;
  return (
    <Panel
      title="How certain is the Ridge advantage?"
      description="Paired stationary-bootstrap intervals for the difference between historical Ridge RMSE and each benchmark RMSE on the contained sample."
    >
      <ChartSurface
        title="Adjusted 97.5% uncertainty intervals for historical RMSE differences"
        axisLabel="Benchmark comparison · dot = estimate, line = adjusted 97.5% interval"
        compact
      >
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart
            margin={{ top: 10, bottom: 6, right: 16, left: 0 }}
            accessibilityLayer
          >
            <CartesianGrid
              stroke="#2b384a"
              strokeDasharray="3 5"
              horizontal={false}
            />
            <XAxis
              {...axis}
              dataKey="estimate"
              name="RMSE difference"
              type="number"
              domain={[min - pad, max + pad]}
              allowDataOverflow
              tickFormatter={(n) => pretty(n, 2)}
              tickCount={5}
            />
            <YAxis
              {...axis}
              type="number"
              dataKey="row"
              ticks={series.map((r) => r.row)}
              domain={[-0.5, series.length - 0.5]}
              width={80}
              tickFormatter={(n) =>
                series[n] ? methodNames[series[n].method] : ""
              }
            />
            <ReferenceLine
              x={0}
              stroke="#eef3f9"
              strokeDasharray="4 3"
              label={{
                value: "Zero",
                fill: "#e2eaf4",
                position: "insideTopRight",
              }}
            />
            <Tooltip
              content={({ active, payload }) => {
                const item = payload?.[0]?.payload as
                  | (typeof series)[number]
                  | undefined;
                return active && item ? (
                  <div className="rc-tip">
                    <strong>Ridge minus {methodNames[item.method]}</strong>
                    <div>Estimate {pretty(item.estimate, 6)} pp</div>
                    <div>
                      Interval [{pretty(item.lower, 6)}, {pretty(item.upper, 6)}
                      ] pp
                    </div>
                  </div>
                ) : null;
              }}
            />
            <Scatter
              data={series}
              fill={methodColors.ridge}
              isAnimationActive={false}
            >
              <ErrorBar
                dataKey="span"
                direction="x"
                width={7}
                stroke={methodColors.ridge}
                strokeWidth={2}
              />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </ChartSurface>
      <p className="rc-x-label">
        Ridge RMSE minus benchmark RMSE · percentage points
      </p>
      <div className="rc-callout">
        <Waypoints size={20} aria-hidden="true" />
        <div>
          <strong>{study.resamples.toLocaleString()} paired repetitions</strong>
          <p>
            Mean block length {study.block_length} trading sessions, preserving
            local dependence within years. The {study.n.toLocaleString()}{" "}
            eligible origins retain their original annual weights.
          </p>
        </div>
      </div>
      <p className="rc-note">
        Negative differences favor Ridge. The 20-session interval stays below
        zero, supporting lower historical error under these assumptions. The
        five-session interval crosses zero, leaving that comparison
        inconclusive. These intervals describe historical performance
        differences and omit earlier model-selection uncertainty.
      </p>
      <ChartData
        rows={study.intervals}
        columns={[
          {
            label: "Comparison",
            value: (r) => "Ridge minus " + methodNames[r.method],
          },
          { label: "Difference (pp)", value: (r) => r.estimate },
          { label: "Adjusted lower (pp)", value: (r) => r.lower },
          { label: "Adjusted upper (pp)", value: (r) => r.upper },
        ]}
        name="paired-bootstrap-intervals"
      />
    </Panel>
  );
}

export default function Performance() {
  const [chart, setChart] = useState("comparison");
  const { data, error, loading, retry } = useDataset("history");
  const highRidge = data?.tail.find((r) => r.method === "ridge");
  const highBenchmark = data?.tail.find((r) => r.method === "hv5");
  return (
    <section className="research-card" aria-labelledby="performance-title">
      <header className="research-head">
        <h2 id="performance-title">Model performance</h2>
        <select aria-label="Model analysis chart" value={chart} onChange={e => setChart(e.target.value)}>
          <option value="comparison">Model comparison</option>
          <option value="accuracy">Forecast vs. observed</option>
          <option value="uncertainty">Uncertainty intervals</option>
          <option value="sensitivity">Sample sensitivity</option>
          <option value="offsets">Starting session</option>
          <option value="spikes">Volatility spikes</option>
        </select>
      </header>
      {chart === "accuracy" ? <HistoricalAccuracy /> : !data ? (
        <DataState loading={loading} error={error} retry={retry} />
      ) : !data.performance.length ? (
        <p className="rc-empty">
          Verified temporal comparison metrics are unavailable in this release.
        </p>
      ) : (
        <>
          <div className="rc-rangebar">
            <div>
              <strong>Annual expanding-window evaluation</strong>
              <span>
                {data.coverage.start} — {data.coverage.end}
              </span>
            </div>
            {chart === "comparison" && <span>
              {data.performance[0].n.toLocaleString()} common forecasts
            </span>}
          </div>
          {chart === "comparison" && <Overall rows={data.performance} />}
          {chart === "sensitivity" && <Sensitivity rows={data.sensitivity} />}
          {chart === "offsets" && <Offsets rows={data.offsets} />}
          {chart === "uncertainty" && <Intervals study={data.uncertainty} />}
          {chart === "spikes" && <Panel
            title="When volatility spikes"
            description="High-outcome forecasts have observed volatility at or above the training sample’s 95th percentile for that fit. This classification becomes available after the target window closes."
          >
            {highRidge && highBenchmark ? (
              <>
                <div className="rc-offset-metrics">
                  <div>
                    <span>High-outcome origins</span>
                    <strong>{highRidge.n}</strong>
                  </div>
                  <div>
                    <span>Ridge RMSE</span>
                    <strong>{pretty(highRidge.rmse, 4)} pp</strong>
                  </div>
                  <div>
                    <span>5-session RMSE</span>
                    <strong>{pretty(highBenchmark.rmse, 4)} pp</strong>
                  </div>
                </div>
                <p className="rc-note">
                  Ridge underpredicted these outcomes by{" "}
                  {pretty(Math.abs(highRidge.bias), 4)} percentage points on
                  average. The five-session benchmark had smaller RMSE in this
                  group, reversing the overall comparison.
                </p>
              </>
            ) : (
              <p className="rc-empty">
                High-outcome diagnostics are unavailable.
              </p>
            )}
            <ChartData
              rows={data.tail}
              columns={highColumns}
              name="temporal-high-volatility-errors"
            />
          </Panel>}
        </>
      )}
    </section>
  );
}
