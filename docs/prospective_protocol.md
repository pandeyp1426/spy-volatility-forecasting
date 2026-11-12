# Frozen later-period protocol: calendar year 2027

Protocol chosen on 11 November 2026, before any 2027 observations. The current user request authorizes preparation of this later-period design. This is a project decision, not an externally registered or supervisor-approved protocol. The historical model choice is informed by the completed 2015–2025 development results; it is fixed independently of the uncertainty intervals being computed alongside this work.

## Question and fixed comparison

Does a frozen Ridge model improve five-session SPY daily-volatility forecast error against both the 20-session and five-session historical benchmarks on a genuinely later calendar year? The model will be fitted once at protocol preparation using the existing permitted development rows, then held fixed throughout 2027. Historical model selection is not hidden: a later period is needed precisely because development informed the choice.

- Preserve the five predictors: latest log return, trailing 5/10/20-return sample standard deviations and five-return log momentum. Use explicit adjusted close, decimal units and `ddof=1`. The response remains the sample SD of the five returns after the forecast close; it is not annualized or a cumulative-return SD.
- Ridge alpha is 1.0 with a StandardScaler fitted only on training predictors. Floor predictions at zero. No additional models, hyperparameter searches, adaptive model choice or within-year refits are permitted.
- Train on all permitted 2015–2025 development identities from verified temporal run `20261027T001114_temporal_4bf4a071`, with target end on or before 31 December 2025. Preserve the original 415 pooled reserved identities as excluded. No reserved response matrix is read. Freeze the training-target 95th percentile for later ex-post tail summaries.
- The frozen JSON model contains the feature order, scaler means/scales, Ridge coefficients/intercept and threshold; no opaque pickle is needed. The two benchmarks use the same issue-time inputs and observations as Ridge.
- No 2026 outcomes enter fitting. If acquired later, the final 2026 prices may supply the 21-price warmup for early-2027 predictors only. Historical adjusted prices in the training snapshot remain immutable.

## Evaluation calendar and issue rule

Use forecast sessions in `[2027-01-01, 2028-01-01)` whose complete five future sessions also fall within 2027. The bundled NYSE calendar currently yields 251 sessions and 246 eligible forecast origins, starting 4 January and ending 23 December 2027. The last five sessions cannot be origins under this containment rule. A saved schedule records each close, deadline and target interval. Calendar calculations are versioned, and the official [NYSE holiday and trading-hours schedule](https://www.nyse.com/trade/hours-calendars) is the operational reference, including early closes.

Issue each forecast strictly after its actual session close and no later than 120 minutes after that close. Deadlines follow the session's close rather than a constant UTC hour; daylight-saving changes and early closes therefore remain explicit. Preserve the local schedule and UTC issue timestamp. If an unscheduled exchange closure or hours change occurs, append its official announcement, acquisition timestamp and revised schedule before the affected issue; never rewrite the frozen calendar or invent a missing session. A change must affect scheduling only, without selecting observations based on error.

The primary record for an origin is the first complete, valid, on-time forecast record. Preserve later revisions separately. Missing, late or invalid forecasts are recorded as failures with their reason and are not retrospectively backfilled into the primary sample. No calendar-date forward filling is allowed. All three predictions must be recorded together on the same input vintage.

This repository change prepares the model and protocol only. **No automatic daily acquisition, scheduler or live forecast logger is started.** Before 2027 begins, the acquisition and append-only forecast-record workflow must be implemented and tested against this protocol. A stored forecast produced after its deadline can never become a prospective observation by supplying an earlier date.

## Point-in-time data and records

Use daily SPY observations with the existing yfinance source and explicit `Adj Close` (`auto_adjust=False`). Archive exact provider responses, request settings, provider/package versions, acquisition UTC timestamps, complete input rows and SHA-256 values separately for every forecast. A forecast snapshot must contain the actual 21 consecutive exchange-session prices ending at its origin, with positive finite values and no missing sessions. Reject observations after the origin. Do not splice different adjustment vintages inside one 21-price feature window or overwrite the old training snapshot. Acquisition timestamps must be at or before issue time. Revised provider history is a separate vintage, never a silent replacement.

Each forecast record must include protocol-bundle ID/hash, model JSON hash, forecast session and global session position, scheduled/actual close, issue time, input snapshot/hash, ordered predictors, raw and floored Ridge prediction, both benchmarks, intended target start/end, and validation status. Use append-only storage with a previous-record hash and external timestamped/versioned retention before any outcome is observed. A hash chain alone does not prove historical issue time; absence of trustworthy issue evidence must be reported. Record unsuccessful issuance attempts as well as successes. Do not claim point-in-time validity until this recordkeeping is operational.

When the fifth outcome session closes, archive the first complete valid adjusted-price snapshot covering the origin and its next five sessions, no later than 24 hours after that target close. Compute the five log returns and sample SD from that single archived vintage. Store labels separately from forecast records, with acquisition time and source hash. Missing labels remain missing; delayed data and corrections are retained only in separately labeled sensitivity records, with no silent replacement of primary outcomes. Provider revisions and retrospectively adjusted training data remain documented limitations even with prospective forecast timestamps.

## Scoring, missingness and stopping

Freeze the observation period regardless of interim market conditions or apparent performance. Do not compute or inspect comparative error summaries or model rankings until 10 January 2028; operational monitoring may inspect data/schema/timestamp validity and coverage, without using outcomes to change the model or sample rules. This command neither reads new prices nor scores the later period.

At final evaluation, score all origins with on-time valid predictions for all three methods and a primary archived label. Apply the identical mask to all models; show the scheduled count, successful forecasts, missing/late/invalid counts and their dates/reasons. Report coverage by month and high/low outcome group where labels exist; a low-coverage result describes the observed subset and must not be presented as the full year. Do not add retrospective forecasts to improve coverage. Report N, MAE, RMSE, MSE and signed bias, plus monthly descriptive and training-threshold high/low-group summaries. Sparse or empty groups remain explicitly unavailable.

Errors are `100 * (prediction - observed)` in daily-volatility percentage points. Recompute aggregate RMSE as `sqrt(mean(error ** 2))` over retained rows; never average monthly RMSE. Primary paired contrasts are fixed Ridge RMSE minus each benchmark RMSE. Also disclose MSE and MAE contrasts and the full tail diagnostics; they cannot replace the primary metric after results are known.

## Frozen uncertainty and evidence rule

Use the [dependence-aware uncertainty protocol](uncertainty_protocol.md): paired stationary bootstrap on the original session grid, retaining missing-identity gaps, one 2027 calendar stratum, 5,000 replicates and seed 42. The expected block length is 20 sessions for the primary result; disclose 5, 10, 20, 40 and 60 sessions without choosing a favorable length. Use nominal 95% percentile intervals and, for the two primary RMSE contrasts, 97.5% individual percentile intervals (quantiles 0.0125 and 0.9875), corresponding to a Bonferroni approximation for a joint 95% family. Do not reselect the method from the historical uncertainty outputs.

The prespecified empirical evidence criterion is lower point RMSE against both benchmarks **and** both multiplicity-adjusted upper bounds below zero at the primary 20-session length. Disclose every sensitivity interval even if it weakens that conclusion. This criterion is an approximate inferential decision under dependence/stability assumptions, not a guarantee of coverage, independence, future profitability or benefit in every volatility regime. A failure to meet it is inconclusive evidence of aggregate improvement, not proof that the forecasts are equivalent. Tail results are secondary and cannot be used to redefine the winning model.

## Freeze and amendments

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.prospective --config configs/prospective.toml
```

The command is offline and creates a new `artifacts/protocols/*_prospective_*` directory, fitting only the permitted historical development data. It records config/input/source hashes, copies the exact inputs, serializes the model, verifies JSON predictions against the fitted estimator, and saves the calendar and a readiness report. It rejects a freeze on or after the evaluation's first calendar date in America/Chicago. Output status is `prepared_not_live`; it is not a completed future evaluation. Repeating the preparation creates a separately identified candidate bundle and never replaces a prior one. Designate one bundle before live collection and record its ID in every forecast.

Any substantive amendment requires a new version, its UTC timestamp, reason and an explicit assessment of what future data or outcomes were already seen. Preserve all earlier versions. Never portray a revised protocol as the original prospective plan. If implementation is not ready before the first eligible session, retain failures and report incomplete coverage under the original window; a different period must be explicitly frozen as a separate study before that period begins.
