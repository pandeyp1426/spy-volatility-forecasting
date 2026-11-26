import { useState, type ReactNode } from "react";
import { ChevronDown, Download, Table2 } from "lucide-react";
import { CartesianGrid, Tooltip } from "recharts";
import type { Method } from "../types/history";
import "../styles/research-charts.css";

export const methodNames: Record<Method, string> = {
  ridge: "Ridge",
  hv5: "5-session",
  hv20: "20-session",
  forest: "Random forest",
  boosting: "Gradient boosting",
};
export const methodColors: Record<Method, string> = {
  ridge: "#52e5c4",
  hv5: "#73a7ff",
  hv20: "#f2ad78",
  forest: "#b69af4",
  boosting: "#ed87aa",
};
export const tick = { fill: "#aebcd0", fontSize: 12 };
export const axis = { tick, tickLine: false, axisLine: false };
export const grid = (
  <CartesianGrid stroke="#2b384a" strokeDasharray="3 5" vertical={false} />
);
export const tipStyle = {
  backgroundColor: "#142134",
  border: "1px solid #465777",
  borderRadius: 8,
  color: "#f1f5fb",
  fontSize: 13,
};
export const pretty = (value: number, digits = 3) =>
  value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
export function chartTip(unit: string, digits = 3) {
  return (
    <Tooltip
      contentStyle={tipStyle}
      labelStyle={{ color: "#edf2fa" }}
      itemStyle={{ color: "#e4ecf8" }}
      cursor={{ fill: "#7894b516", stroke: "#64748b" }}
      formatter={(value, name) => [
        typeof value === "number"
          ? `${pretty(value, digits)} ${unit}`
          : "Unavailable",
        name,
      ]}
    />
  );
}

export type TableValue = string | number | null;
export interface TableColumn<Row> {
  label: string;
  value: (row: Row) => TableValue;
  format?: (value: number) => string;
}

function formatCell<Row>(row: Row, column: TableColumn<Row>) {
  const value = column.value(row);
  if (value === null) return "—";
  if (typeof value === "number")
    return column.format ? column.format(value) : pretty(value, 4);
  return value;
}

export function chartCsv<Row>(rows: Row[], columns: TableColumn<Row>[]) {
  const quote = (value: TableValue) =>
    '"' + String(value ?? "").replaceAll('"', '""') + '"';
  return [
    columns.map((c) => quote(c.label)).join(","),
    ...rows.map((row) => columns.map((c) => quote(c.value(row))).join(",")),
  ].join("\r\n");
}

export function ChartData<Row>({
  rows,
  columns,
  name,
}: {
  rows: Row[];
  columns: TableColumn<Row>[];
  name: string;
}) {
  const [page, setPage] = useState(0);
  const count = Math.ceil(rows.length / 12);
  const safePage = Math.max(0, Math.min(page, count - 1));
  function download() {
    const url = URL.createObjectURL(
      new Blob([chartCsv(rows, columns)], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = name + ".csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="rc-data">
      <button
        className="rc-download"
        onClick={download}
        disabled={!rows.length}
        aria-label={`Download ${name} as CSV`}
      >
        <Download size={15} aria-hidden="true" /> CSV
      </button>
      <details>
        <summary>
          <Table2 size={15} aria-hidden="true" /> Data table{" "}
          <ChevronDown size={14} aria-hidden="true" />
        </summary>
        <div
          className="rc-table-scroll"
          tabIndex={0}
          aria-label={`${name} table, scroll horizontally`}
        >
          <table>
            <caption>{name.replaceAll("-", " ")}</caption>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.label} scope="col">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(safePage * 12, safePage * 12 + 12).map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c.label}>{formatCell(row, c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {count > 1 && (
          <div className="rc-pagination">
            <button
              onClick={() => setPage(safePage - 1)}
              disabled={safePage === 0}
            >
              Previous
            </button>
            <span>
              Page {safePage + 1} of {count}
            </span>
            <button
              onClick={() => setPage(safePage + 1)}
              disabled={safePage === count - 1}
            >
              Next
            </button>
          </div>
        )}
      </details>
    </div>
  );
}

export function ChartSurface({
  children,
  title,
  axisLabel,
  compact = false,
}: {
  children: ReactNode;
  title: string;
  axisLabel: string;
  compact?: boolean;
}) {
  return (
    <div className={`rc-surface${compact ? " rc-compact" : ""}`}>
      <p className="rc-y-unit">{axisLabel}</p>
      <div className="rc-plot" role="group" aria-label={title}>
        {children}
      </div>
    </div>
  );
}

export function Segments<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="rc-segments" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ChartLegend({
  items,
}: {
  items: { name: string; color: string }[];
}) {
  return (
    <ul className="rc-legend" aria-label="Chart legend">
      {items.map((item) => (
        <li key={item.name}>
          <i style={{ background: item.color }} />
          {item.name}
        </li>
      ))}
    </ul>
  );
}
