import { forecastSchema } from "../types/public";
import { useDataset } from "./data";
import { useLocalFeed } from "./local";

const pilots = forecastSchema.array().refine((rows) => rows.every((r) =>
  r.study === "pilot_2026" && r.origin.startsWith("2026-") &&
  r.outcome_status === "pending" && r.target_sessions.every((day) => day.startsWith("2026-"))));

export function useForecasts() {
  const approved = useDataset("forecasts");
  const local = useLocalFeed("pilots.json", pilots);
  const published = approved.data?.rows ?? [];
  const origins = new Set(published.map((row) => row.origin));
  const privateRows = (local.value ?? []).filter((row) => !origins.has(row.origin));
  const rows = [...published, ...privateRows].sort((a, b) => b.origin.localeCompare(a.origin));
  return {...approved, data: approved.data || rows.length ? {rows} : null,
    localIds: new Set(privateRows.map((r) => r.id)),
    localError: local.failed ? "Local forecasts could not be refreshed." : null};
}
