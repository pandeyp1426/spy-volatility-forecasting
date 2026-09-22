# Phase 1 research design

Pradeep Pandey, University of Wisconsin–Stout. One-credit independent study with Dr. Augustine Twumasi.

The research question is whether simple statistical and machine-learning models improve short-term SPY volatility forecasts over a historical-volatility baseline. Phase 1 establishes the data and evaluation protocol. It does not fit linear regression or random forest and does not evaluate the reserved final test.

## Timing, inputs, and target

A forecast is issued after trading session `t` closes. With adjusted close `P_t`, the daily log return is `r_t = ln(P_t / P_(t-1))`. A window of `w` daily returns needs `w+1` closing prices. Historical windows include the return ending at `t`.

The default input vector is:

| Input | Definition |
| --- | --- |
| 5-session volatility | Sample standard deviation of `r_(t-4), ..., r_t` |
| 10-session volatility | Sample standard deviation of `r_(t-9), ..., r_t` |
| 20-session volatility | Sample standard deviation of `r_(t-19), ..., r_t` |
| Latest return | `r_t` |
| 5-session return sum | `r_(t-4) + ... + r_t` |

The sum of log returns also equals `ln(P_t / P_(t-5))`. The baseline predicts the next target using only the 20-session volatility input; it has no fitted coefficients.

The target is `sample_std(r_(t+1), ..., r_(t+5))`, with divisor `5-1`. All historical volatilities also use the sample formula (`ddof=1`). No square-root-of-252 annualization or square-root-of-five scaling is applied. The horizon defines the observations used to measure future **daily** volatility; the target is neither a five-day cumulative return nor its standard deviation across repeated five-day periods.

Record the actual dates of `t+1` and `t+5` beside every target. Incomplete historical windows and incomplete future windows are excluded. The final five price observations therefore cannot be forecast examples with known outcomes. The first return is also undefined until a previous price is available.

Ticker, dates, windows, horizon, and split boundaries are configurable. Changes are separate experiment choices and must be reported; the definitions above describe the initial five-session experiment.

## Source, snapshot, and audit

The initial candidate is Yahoo Finance accessed through `yfinance`. Request daily observations from 2014-11-01 inclusive to 2026-01-01 exclusive. The 2014 portion supplies warm-up for forecast dates beginning in 2015. Set `auto_adjust=False` explicitly and select `Adj Close`; do not accidentally calculate returns from raw `Close` or rely on an API default. The implementation handles a single-ticker result, including hierarchical columns. The [current download reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) documents these API options and date conventions.

A raw snapshot and its metadata identify the source, retrieval time, request, actual coverage, package versions, and SHA-256 digest. Repeated runs validate and reuse that snapshot. Data-request changes require a new configured snapshot directory; a settings mismatch stops the run. There is no automatic refresh of an existing experiment's data.

Before calculating returns, audit the full requested period for unordered or duplicate dates, missing/nonfinite/nonpositive adjusted prices, and missing or unexpected trading sessions. Expected daily sessions come from the `NYSE` calendar in [pandas_market_calendars](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html), a documented U.S. equity schedule. Holidays are excluded; early-close sessions remain valid daily observations. A mismatch requires investigation of the provider data and calendar. The pipeline must not forward-fill a missing session, silently drop a bad price, or substitute artificial data for a failed real download.

This is a retrospective adjusted-price study. Fixing the raw snapshot prevents unnoticed changes between runs, but cannot prove that all adjustment values were available on the historical forecast dates. Calendar definitions and vendor history can also change across versions. The audit and pinned environment make these choices inspectable; a genuine point-in-time dataset would be a later methodological improvement. Before distributing raw data or moving it to S3, review the data provider's applicable terms.

## Chronological split and boundary rules

Use forecast dates in 2015–2021 for training, 2022–2023 for validation, and 2024–2025 for the reserved final test. These proposed dates need discussion with Dr. Twumasi. Training data supplies exploratory plots and, later, fitted-model parameters. Validation supports model comparison and tuning. Final-test outcomes must not guide design choices.

Let `v0` be the first actual validation forecast date. Remove every training example with `target_end >= v0`. Let `q0` be the first actual final-test forecast date. Remove every validation example with `target_end >= q0`. Evaluate these inequalities using the recorded trading dates, not a fixed number of calendar days. Save the excluded-row counts and retained date ranges in the split summary.

Historical feature windows may reach backward across a split boundary because those past observations would already be available when forecasting. Future target windows must respect the purge rule. Any later scaler, imputer, or feature-selection procedure must be fitted on training data only. A focused test changes prices after a cutoff and confirms that inputs at and before that cutoff remain unchanged for the supplied price series.

## Validation metrics and overlap

For `n` validation forecasts, with baseline `b_t` and target `y_t` in decimal daily-volatility units:

```text
MAE  = 100 * mean(abs(b_t - y_t))
RMSE = 100 * sqrt(mean((b_t - y_t)^2))
```

Report both in daily-volatility percentage points, together with `n`. Multiplying by 100 changes units; it does not annualize the result. For example, a baseline of `0.010` and target of `0.012` differ by `0.2` percentage points.

The primary evaluation uses every retained validation forecast. Adjacent targets share four of five daily returns, so their errors are dependent. The secondary evaluation begins at the first retained validation forecast and selects every fifth trading session. Verify that each selected target-end date is strictly earlier than the next selected target-start date. This produces disjoint outcome windows, while volatility persistence can still induce dependence. Report both results; do not treat the larger daily count as independent trials or choose a favorable sampling offset after inspecting scores.

Plots of return history and historical volatility use training data. The observed-versus-baseline comparison uses validation only. Store the final-test table for future use, while leaving all final-test performance uncomputed.

## Reproducibility and interpretation

Each run saves the audit, complete feature table, purged splits, predictions, plots, metrics, resolved configuration, snapshot digest, and dependency versions. The raw snapshot and generated results stay local and are ignored by Git; code, configuration, the lock file, and research notes are tracked. Reproduction requires the saved snapshot as well as the code and environment, because a future fresh Yahoo download may differ.

A five-return sample standard deviation is a noisy realized proxy. Predicting it does not directly predict SPY's price direction or option-implied volatility. Phase 1 establishes a numerical reference for later models; it is not evidence of a trading strategy's profitability. Any empirical statements belong in [phase1_progress.md](phase1_progress.md) and must match the saved output files.
