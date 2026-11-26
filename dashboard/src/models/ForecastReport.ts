import type { Forecast, Method } from "../types/public";

const predictors = [
  ["log_return", "Latest log return"],
  ["volatility_5", "5-session volatility"],
  ["volatility_10", "10-session volatility"],
  ["volatility_20", "20-session volatility"],
  ["momentum_5", "5-session log momentum"],
] as const;

const methods = ["ridge", "hv20", "hv5"] as const;
const labels = { ridge: "Ridge model", hv20: "20-session benchmark", hv5: "5-session benchmark" };
export type ComparisonMetric = "levels" | "signed_error_pp" | "absolute_error_pp";
type ChartValue = { method: Method | "observed"; value: number };

/** Presents one validated record. The Python release supplies every scientific value. */
export class ForecastReport {
  constructor(readonly record: Forecast) {}

  get inputs() {
    return predictors.map(([key, label]) => ({key, label, percent: 100 * this.record.predictors[key]}));
  }

  get estimates() {
    return methods.map(method => ({method, label: labels[method], percent: this.record.predictions_pct[method]}));
  }

  get studyLabel() {
    if (this.record.study === "formal_2027") return "Formal 2027 forecast";
    if (this.record.timing === "local_on_time") return "Locally on-time pilot";
    return "Late pilot";
  }

  comparison(metric: ComparisonMetric) {
    const { outcome } = this.record;
    if (metric !== "levels" && outcome) {
      const values: ChartValue[] = methods.map(method => ({method, value: outcome[metric][method]}));
      return {values, label: metric === "signed_error_pp" ? "Signed error" : "Absolute error", unit: "pp"};
    }
    const values: ChartValue[] = this.estimates.map(({method, percent}) => ({method, value: percent}));
    if (outcome) values.push({method: "observed", value: outcome.observed_pct});
    return {values, label: "Daily volatility", unit: "%"};
  }
}
