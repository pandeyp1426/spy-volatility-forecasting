import { z } from "zod";

const finite = z.number().finite();
const count = z.number().int().nonnegative();
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const methodSchema = z.enum([
  "ridge",
  "hv5",
  "hv20",
  "forest",
  "boosting",
]);
export type Method = z.infer<typeof methodSchema>;

const metricSchema = z
  .object({
    method: methodSchema,
    n: count,
    mae: finite.nonnegative(),
    rmse: finite.nonnegative(),
    bias: finite,
  })
  .strict();

export const historySchema = z
  .object({
    sources: z.array(
      z
        .object({
          run_id: z.string(),
          record_sha256: z.string().regex(/^[a-f0-9]{64}$/),
          finished_at: z.string().datetime({ offset: true }),
          files: z.array(
            z
              .object({
                name: z.string(),
                sha256: z.string().regex(/^[a-f0-9]{64}$/),
              })
              .strict(),
          ),
        })
        .strict(),
    ),
    coverage: z.object({ start: isoDate, end: isoDate }).strict(),
    performance: z.array(metricSchema),
    tail: z.array(metricSchema),
    sensitivity: z.array(
      z
        .object({
          sample: z.enum(["Original", "Contained", "Every fifth", "Both"]),
          n: count,
          ridge: finite.nonnegative(),
          hv5: finite.nonnegative(),
          hv20: finite.nonnegative(),
        })
        .strict(),
    ),
    offsets: z.array(
      z
        .object({
          offset: z.number().int().min(0).max(4),
          n: count,
          vs20: finite,
          vs5: finite,
        })
        .strict(),
    ),
    uncertainty: z
      .object({
        resamples: count,
        block_length: count,
        n: count,
        intervals: z.array(
          z
            .object({
              method: z.enum(["hv20", "hv5"]),
              estimate: finite,
              lower: finite,
              upper: finite,
            })
            .strict()
            .refine((v) => v.lower <= v.upper, "Invalid interval endpoints"),
        ),
      })
      .strict(),
  })
  .strict();

export const observationsSchema = z
  .object({
    rows: z.array(
      z
        .object({
          date: isoDate,
          observed: finite.nonnegative(),
          ridge: finite.nonnegative(),
          hv5: finite.nonnegative(),
          hv20: finite.nonnegative(),
          ridge_signed: finite,
          hv5_signed: finite,
          hv20_signed: finite,
          ridge_absolute: finite.nonnegative(),
          hv5_absolute: finite.nonnegative(),
          hv20_absolute: finite.nonnegative(),
        })
        .strict(),
    ),
  })
  .strict();

export type History = z.infer<typeof historySchema>;
export type Observation = z.infer<typeof observationsSchema>["rows"][number];
