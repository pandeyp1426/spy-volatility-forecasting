import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  forecastSchema,
  manifestSchema,
  schemas,
  type Forecast,
} from "./types/public";
import { rangeStart } from "./pages/Market";
import { filterRows } from "./pages/Explorer";
import { chartCsv } from "./components/ResearchCharts";
import { dataUrl } from "./services/data";
import { ForecastReport } from "./models/ForecastReport";
const read = (name: string) =>
  JSON.parse(readFileSync("public/data/" + name + ".json", "utf8"));
const pilot: Forecast = forecastSchema.parse(
  read("forecasts").data.rows.find(
    (f: Forecast) => f.study === "manual_pilot_2026",
  ),
);
describe("public research release", () => {
  it("uses model input order and converts only decimal predictors to percent", () => {
    const report = new ForecastReport(pilot);
    expect(report.inputs.map(input => input.key)).toEqual([
      "log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5",
    ]);
    for (const input of report.inputs)
      expect(input.percent).toEqual(100 * pilot.predictors[input.key]);
    expect(report.estimates[0].percent).toEqual(pilot.predictions_pct.ridge);
    expect(report.studyLabel).toBe("Late pilot");
    expect(report.comparison("signed_error_pp").values[0].value).toBe(pilot.outcome!.signed_error_pp.ridge);
    expect(report.comparison("levels").values.at(-1)?.value).toBe(pilot.outcome!.observed_pct);
    const pending = new ForecastReport({...pilot, outcome: undefined, outcome_status: "pending"});
    expect(pending.comparison("absolute_error_pp")).toEqual(pending.comparison("levels"));
    expect(pending.comparison("levels").values).toHaveLength(3);
  });
  it("resolves every typed dataset below the Pages path", () => {
    const manifest = manifestSchema.parse(read("manifest"));
    for (const key of Object.keys(schemas) as (keyof typeof schemas)[]) {
      expect(dataUrl(manifest.datasets[key].file)).toBe(
        "/spy-volatility-forecasting/data/" + key + ".json",
      );
      expect(schemas[key].safeParse(read(key).data).success).toBe(true);
    }
  });
  it("retains verified pilot values and missing observations", () => {
    expect(pilot.predictions_pct.ridge).toBeCloseTo(1.6372786661, 9);
    expect(pilot.outcome?.observed_pct).toBeCloseTo(0.6995661397, 9);
    expect(read("market").data.rows[0].log_return).toBeNull();
    expect(chartCsv([{ v: null }], [{ label: "Vol", value: (r) => r.v }])).toBe(
      '"Vol"\r\n""',
    );
  });
  it("accepts pending and withheld records without a numeric outcome", () => {
    const pending = { ...pilot, outcome: undefined, outcome_status: "pending" };
    expect(forecastSchema.safeParse(pending).success).toBe(true);
    const formal = {
      ...pending,
      study: "formal_2027",
      origin: "2027-01-04",
      timing: "local_on_time",
      outcome_status: "withheld",
    };
    expect(forecastSchema.safeParse(formal).success).toBe(true);
    expect(
      forecastSchema.safeParse({ ...formal, outcome: pilot.outcome }).success,
    ).toBe(false);
    expect(
      forecastSchema.safeParse({ ...formal, comparison: { ridge: 1 } }).success,
    ).toBe(false);
  });
  it("filters records by origin and study and sorts by the selected method", () => {
    const second = {
      ...pilot,
      origin: "2026-11-12",
      study: "pilot_2026" as const,
      predictions_pct: { ...pilot.predictions_pct, hv20: 3 },
    };
    expect(
      filterRows([pilot, second], "", "all", "", "", "highest", "hv20")[0],
    ).toBe(second);
    expect(
      filterRows(
        [pilot, second],
        "November",
        "all",
        "",
        "2026-11-11",
        "oldest",
        "ridge",
      ),
    ).toEqual([pilot]);
    expect(
      filterRows([pilot], "", "formal_2027", "", "", "newest", "ridge"),
    ).toEqual([]);
  });
  it("filters calendar ranges against archived coverage including leap years", () => {
    expect(rangeStart("2024-03-31", 1)).toBe("2024-02-29");
    expect(rangeStart("2025-12-31", 0)).toBe("");
  });
});
