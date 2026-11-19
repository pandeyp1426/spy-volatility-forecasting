# Operational collection rules, version 1

Documented November 18, 2026. This implements collection around the existing frozen model. It does not amend `prospective_protocol.md`, its frozen bundle, or any historical experiment. No recurring task or formal collection has been activated.

## Preserved research state

Before this extension, the project had a verified November 11 manual pilot, the designated `20261112T033437_prospective_121fb52e` bundle, and no operational collection system. The bundle's 36 artifact hashes and the original pilot replay passed inspection. Historical development informed model choice: aggregate temporal Ridge error was lower than both benchmarks, but dependence-aware uncertainty remained inconclusive against the five-session benchmark, and high-volatility underprediction remained unresolved. Those findings are unchanged.

The parent snapshot begins November 1, 2014 inclusive; original global session numbers count the NYSE grid from that request's first session. The separate frozen 2027 schedule position is also preserved. Source code, configuration, model and data hashes identify each new attempt. Historical prices, 415 reserved identities, reserved response files, model parameters and the frozen protocol remain untouched. Hashing the bundle's allowed preparation inputs does not fit a model or parse reserved responses.

## Forecast collection

`cycle` uses the existing NYSE calendar and verified pilot functions, with UTC and Eastern timestamps. It selects the latest strictly completed session, requires the actual 21 consecutive adjusted-close prices, and rejects stale, incomplete, nonfinite, nonpositive, duplicate or unordered data. The provider settings remain explicit yfinance `Adj Close`, `auto_adjust=False`, `back_adjust=False`, `repair=False`, daily intervals and no filling or rounding. Every attempt uses a new directory and a single acquisition vintage.

Inputs stay in the frozen order: latest log return, trailing 5/10/20-return sample SDs and five-return log momentum. SD uses `ddof=1`; values stay decimal and unannualized. Frozen scaling, coefficients, intercept, alpha 1 and the zero floor are unchanged. Ridge and both benchmarks share one origin and vintage. Independent scalar arithmetic and reconstructed sklearn prediction state verify the output without fitting.

A complete local record created after close and at or before close + 120 minutes is a **locally on-time candidate**, not automatically certified prospective evidence. Late forecasts remain diagnostic records. Subsequent scheduled invocations skip a completed forecast; an explicit revision reason creates a separate record. Failures retain their evidence and cause a nonzero process exit. A later poll retries acquisition without backdating. Sessions missed during downtime receive missing records after the deadline; only the latest completed origin can receive a new forecast.

The calendar records scheduled closes, with `actual_close_utc=null` until independently verified. Officially known disruptions supplied under `artifacts/market_notices/` block affected acquisition. A mismatch between the installed calendar and frozen 2027 schedule also blocks collection. A revised calendar requires explicit review, retained official evidence and a separately versioned amendment; this implementation does not silently alter frozen dates.

## Separate 2026 pilot policy

New operational pilot origins begin November 12, 2026. Both the origin and all five targets must remain in 2026, so the last eligible origin is December 23. This is an operational pilot decision, not a change to the 2027 study. Uncollected origins are recorded as missing, not retrospectively generated.

The November 11 manual forecast is imported only by its pinned original record hash and successful offline replay. It keeps its original issue time, values, evidence and separate-manual-pilot designation. Importing it does not reissue it or convert its late timestamp into an on-time observation.

For descriptive `pilot_2026` metrics, select the first valid forecast and first valid outcome for each operational pilot origin, including explicitly labelled late diagnostics. Revised vintages are sensitivity comparisons, not additional observations in the aggregate. `manual_pilot_2026` is its own sample containing only the imported manual pilot. All three methods use the same rows. These small, selected pilot samples cannot establish prospective generalization or override unfavorable historical results.

## Outcome collection

Only strictly after the fifth target session closes may the worker acquire six consecutive prices: origin plus five targets. One new adjusted-price vintage supplies all five returns. No origin price is spliced from the earlier forecast snapshot. The saved outcome includes returns, mean return, sample SD, source/settings/versions, acquisition timestamps, identity links and verification against independent scalar arithmetic.

The first complete valid snapshot acquired no later than target close + 24 hours is the timely label candidate. Missing labels are recorded once the deadline passes. Later successful data are `late_sensitivity`; explicitly requested corrections are `revised_sensitivity`. Neither can overwrite an earlier label or silently enter the formal primary sample. Recent maturity deadlines take priority over old gaps.

## Scoring and embargo

Per-method signed error is `100 * (prediction - observed)` in daily-volatility percentage points; absolute error is its magnitude and squared error is in pp squared. Aggregate MAE, MSE and bias average the common observation-level errors; RMSE is the square root of aggregate MSE. No averaging of monthly RMSE or “accuracy percentage” is used. Empty samples report unavailable metrics, not zeros.

2026 pilot errors may be calculated after maturity. The worker archives formal 2027 labels but does not compute their errors or expose them in routine command output. All formal per-forecast and aggregate comparisons are blocked until **January 10, 2028, 00:00 America/Chicago**. The classification is derived from origin/target dates, so a 2027 forecast cannot bypass the gate by calling itself a pilot.

After that date, the descriptive formal aggregate selects the first valid forecast meeting both local issue-time and timely external-retention requirements, together with the first timely label, on a common mask. An earlier unretained attempt cannot displace a later fully qualifying record. The final study still requires the frozen coverage, monthly/tail diagnostics and paired stationary-bootstrap analysis; this collector does not replace that full evaluation or certify empirical success.

## Evidence retention

Each attempt has a unique evidence directory. A SQLite journal commits append-only events atomically with sequence and previous-event hashes; SQL triggers reject updates/deletes. A process lock prevents concurrent workers, and interrupted starts become explicit interrupted-attempt records on recovery. Forecasts and outcomes are stored separately. Later records only reference earlier IDs; they never edit earlier forecasts.

Local hashes establish consistency relative to the surviving chain. They cannot prove original issue time, prevent a privileged user from rewriting the entire store, or detect deletion of its tail without an external checkpoint. The optional S3 adapter retains evidence packages using conditional unique keys, enabled bucket versioning, checked SHA-256 checksums, a version ID, and S3 `LastModified`. Retry receipts are separate journal events. An upload after the forecast deadline cannot retrospectively qualify a forecast.

External retention is **disabled by default**. It requires a private versioned bucket, AWS CLI v2 and credentials held outside the repository. Real 2027 forecasting refuses to proceed without configured retention. Configuring it is not proof it works; successful server receipts and an operational review are necessary. No bucket, credentials, scheduler or running study was created by this implementation. Original Yahoo HTTP response bodies and independently observed exchange close events are not captured; the archived raw data are the complete numeric DataFrame returned by yfinance.
