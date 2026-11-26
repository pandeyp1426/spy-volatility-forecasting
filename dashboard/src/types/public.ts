import { z } from "zod";
import { historySchema, observationsSchema } from "./history.ts";
const number = z.number().finite();
const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const instant = z.string().datetime({ offset: true });
const digest = z.string().regex(/^[0-9a-f]{64}$/);
export const methods = ["ridge", "hv5", "hv20"] as const;
export type Method = (typeof methods)[number];
export const methodNames = {
  ridge: "Ridge regression",
  hv5: "5-session benchmark",
  hv20: "20-session benchmark",
};
const values = z.object({ ridge: number, hv5: number, hv20: number }).strict();
const predictors = z
  .object({
    log_return: number,
    volatility_5: number,
    volatility_10: number,
    volatility_20: number,
    momentum_5: number,
  })
  .strict();
const outcome = z
  .object({
    observed_pct: number.nonnegative(),
    acquired_at_utc: instant,
    signed_error_pp: values,
    absolute_error_pp: values,
  })
  .strict();
export const forecastSchema = z
  .object({
    id: digest,
    origin: day,
    target_sessions: z.array(day).length(5),
    issued_at_utc: instant,
    acquired_at_utc: instant,
    scheduled_close_utc: instant,
    study: z.enum(["manual_pilot_2026", "pilot_2026", "formal_2027"]),
    timing: z.enum(["historical_manual_pilot", "local_on_time", "late"]),
    outcome_status: z.enum(["observed", "pending", "withheld"]),
    validation: z.literal("verified"),
    source: z.literal("Yahoo Finance via yfinance"),
    model_id: z.string().min(1),
    predictions_pct: values,
    predictors,
    outcome: outcome.optional(),
  })
  .strict()
  .superRefine((f, ctx) => {
    if (
      (f.outcome_status === "observed") !== !!f.outcome ||
      (f.origin.startsWith("2027") &&
        (f.study !== "formal_2027" || f.outcome_status !== "withheld")) ||
      (f.study === "formal_2027" &&
        (!f.origin.startsWith("2027") || f.outcome_status !== "withheld"))
    )
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Unexpected publication status",
      });
  });
export type Forecast = z.infer<typeof forecastSchema>;
const marketRow = z
  .object({
    date: day,
    price: number.positive(),
    log_return: number.nullable(),
    volatility_5: number.nonnegative().nullable(),
    volatility_10: number.nonnegative().nullable(),
    volatility_20: number.nonnegative().nullable(),
  })
  .strict();
export const marketSchema = z
  .object({ rows: z.array(marketRow), acquired_at: instant })
  .strict();
const status = z
  .object({
    reviewed_on: day,
    collector: z.string(),
    formal: z.string(),
    milestones: z.array(z.string()),
  })
  .strict();
export const schemas = {
  market: marketSchema,
  market_preview: marketSchema,
  forecasts: z.object({ rows: z.array(forecastSchema) }).strict(),
  history: historySchema,
  observations: observationsSchema,
  status,
};
export type Dataset = keyof typeof schemas;
export type Data<K extends Dataset> = z.infer<(typeof schemas)[K]>;
const entry = z
  .object({
    file: z.string(),
    sha256: digest,
    status: z.enum(["available", "empty"]),
  })
  .strict();
export const manifestSchema = z
  .object({
    schema_version: z.literal(1),
    generated_at: instant,
    datasets: z
      .object({
        market: entry,
        market_preview: entry,
        forecasts: entry,
        history: entry,
        observations: entry,
        status: entry,
      })
      .strict(),
  })
  .strict();
export const envelope = z
  .object({
    schema_version: z.literal(1),
    dataset: z.enum([
      "market",
      "market_preview",
      "forecasts",
      "history",
      "observations",
      "status",
    ]),
    generated_at: instant,
    source: z.string(),
    units: z.string(),
    coverage: z.object({ start: day.nullable(), end: day.nullable() }).strict(),
    status: z.enum(["available", "empty"]),
    data: z.unknown(),
  })
  .strict();
