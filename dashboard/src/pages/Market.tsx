import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Brush,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { DataState, Panel } from "../components/UI";
import {
  axis,
  chartTip,
  ChartData,
  ChartLegend,
  ChartSurface,
  grid,
  methodColors,
  Segments,
  type TableColumn,
} from "../components/ResearchCharts";
import { useDataset } from "../services/data";

const ranges = [
  { value: 1, label: "1M" },
  { value: 3, label: "3M" },
  { value: 6, label: "6M" },
  { value: 12, label: "1Y" },
  { value: 0, label: "All" },
];
const windows = [5, 10, 20] as const;
type Window = (typeof windows)[number];
type WindowKey = `volatility_${Window}`;
const volKey = (w: Window): WindowKey => `volatility_${w}`;
const colors = {
  5: methodColors.hv5,
  10: methodColors.ridge,
  20: methodColors.hv20,
};
const dash = { 5: undefined, 10: "6 3", 20: "2 3" };
const margin = { top: 8, right: 12, bottom: 0, left: 0 };
const dateAxis = (dataKey: string, full: boolean) => (
  <XAxis
    {...axis}
    dataKey={dataKey}
    minTickGap={28}
    tickMargin={8}
    height={32}
    tickFormatter={(value) =>
      full ? String(value).slice(0, 4) : String(value).slice(5)
    }
  />
);

/** Calendar-month filter relative to the last date in the archived series. */
export function rangeStart(last: string, months: number) {
  if (!months) return "";
  const d = new Date(last + "T00:00:00Z");
  const day = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - months);
  const daysInMonth = new Date(
    Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0),
  ).getUTCDate();
  d.setUTCDate(Math.min(day, daysInMonth));
  return d.toISOString().slice(0, 10);
}

export default function Market() {
  const { data, error, loading, retry } = useDataset("market");
  const [months, setMonths] = useState(12);
  const [chart, setChart] = useState("price");
  const [visible, setVisible] = useState<Window[]>([5, 10, 20]);
  const last = data?.rows.at(-1);
  const subset = useMemo(() => {
    if (!data || !last) return [];
    const start = rangeStart(last.date, months);
    return data.rows.filter((p) => p.date >= start);
  }, [data, last, months]);
  const first = subset[0];
  type Row = (typeof subset)[number];
  const dateCol: TableColumn<Row> = {
    label: "Trading session",
    value: (r) => r.date,
  };
  const priceCol: TableColumn<Row> = {
    label: "Adjusted close (USD)",
    value: (r) => r.price,
    format: (n) => n.toFixed(2),
  };
  const returnCol: TableColumn<Row> = {
    label: "Daily log return (%)",
    value: (r) => r.log_return,
  };
  const volCols: TableColumn<Row>[] = visible.map((w) => ({
    label: `${w}-session SD (%)`,
    value: (r) => r[volKey(w)],
  }));
  function toggle(w: Window) {
    setVisible((previous) =>
      previous.includes(w)
        ? previous.filter((x) => x !== w)
        : windows.filter((x) => x === w || previous.includes(x)),
    );
  }
  return (
    <section className="research-card" aria-labelledby="market-title">
      <header className="research-head">
        <h2 id="market-title">Market history</h2>
        <select aria-label="Market chart" value={chart} onChange={e => setChart(e.target.value)}>
          <option value="price">Adjusted price</option>
          <option value="returns">Daily returns</option>
          <option value="volatility">Rolling volatility</option>
        </select>
      </header>
      {!data ? (
        <DataState loading={loading} error={error} retry={retry} />
      ) : !last || !first ? (
        <p className="rc-empty">
          No approved market sessions are available in this release.
        </p>
      ) : (
        <>
          <div className="rc-rangebar">
            <div>
              <strong>
                {first.date} — {last.date}
              </strong>
              <span>{subset.length.toLocaleString()} sessions</span>
            </div>
            <Segments
              value={months}
              onChange={setMonths}
              options={ranges}
              label="Market history range"
            />
          </div>
          {chart === "price" && <Panel
            title="SPY adjusted close"
          >
            <ChartSurface
              title="SPY adjusted closing prices by trading session"
              axisLabel="Adjusted price · USD"
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={subset} margin={margin} accessibilityLayer>
                  {grid}
                  {dateAxis("date", !months)}
                  <YAxis
                    {...axis}
                    domain={["auto", "auto"]}
                    width={52}
                    tickFormatter={(n) => "$" + Number(n).toFixed(0)}
                  />
                  {chartTip("USD", 2)}
                  <Area
                    type="linear"
                    dataKey="price"
                    name="Adjusted close"
                    stroke={methodColors.ridge}
                    fill={methodColors.ridge}
                    fillOpacity={0.09}
                    strokeWidth={2}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Brush
                    key={months}
                    dataKey="date"
                    height={23}
                    stroke="#7894a7"
                    fill="#132234"
                    travellerWidth={9}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </ChartSurface>
            <p className="rc-x-label">Trading session</p>
            <ChartData
              name="spy-adjusted-prices"
              rows={subset}
              columns={[dateCol, priceCol]}
            />
          </Panel>}
          {chart === "returns" && <Panel
            title="Daily log returns"
          >
            <ChartLegend
              items={[
                { name: "Positive return", color: methodColors.ridge },
                { name: "Negative return", color: "#ed87aa" },
              ]}
            />
            <ChartSurface
              title="Positive and negative daily log returns"
              axisLabel="Daily log return · %"
              compact
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={subset} margin={margin} accessibilityLayer>
                  {grid}
                  {dateAxis("date", !months)}
                  <YAxis {...axis} width={48} />
                  <ReferenceLine y={0} stroke="#a4b5ca" />
                  {chartTip("%")}
                  <Bar
                    dataKey="log_return"
                    name="Log return"
                    isAnimationActive={false}
                  >
                    {subset.map((p) => (
                      <Cell
                        key={p.date}
                        fill={
                          p.log_return !== null && p.log_return < 0
                            ? "#ed87aa"
                            : methodColors.ridge
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartSurface>
            <p className="rc-x-label">Trading session</p>
            <ChartData
              name="spy-daily-log-returns"
              rows={subset}
              columns={[dateCol, returnCol]}
            />
          </Panel>}
          {chart === "volatility" && <Panel
            title="Trailing volatility"
          >
            <div
              className="rc-toggle-group"
              role="group"
              aria-label="Volatility windows"
            >
              {windows.map((w) => (
                <button
                  key={w}
                  onClick={() => toggle(w)}
                  aria-pressed={visible.includes(w)}
                >
                  <i style={{ background: colors[w] }} />
                  {w} sessions
                </button>
              ))}
            </div>
            {visible.length ? (
              <>
                <ChartSurface
                  title="5-, 10- and 20-session return volatility"
                  axisLabel="Daily-return sample SD · % (unannualized)"
                  compact
                >
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={subset} margin={margin} accessibilityLayer>
                      {grid}
                      {dateAxis("date", !months)}
                      <YAxis {...axis} width={48} domain={[0, "auto"]} />
                      {chartTip("%")}
                      {visible.map((w) => (
                        <Line
                          key={w}
                          dataKey={volKey(w)}
                          name={w + " sessions"}
                          type="linear"
                          dot={false}
                          stroke={colors[w]}
                          strokeWidth={1.8}
                          strokeDasharray={dash[w]}
                          connectNulls={false}
                          isAnimationActive={false}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </ChartSurface>
                <p className="rc-x-label">Trading session</p>
              </>
            ) : (
              <p className="rc-empty">
                Select a window to display its volatility series.
              </p>
            )}
            <ChartData
              name="spy-historical-volatility"
              rows={subset}
              columns={[dateCol, ...volCols]}
            />
          </Panel>}
        </>
      )}
    </section>
  );
}
