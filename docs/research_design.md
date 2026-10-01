# How the forecast works

**Volatility measures how much returns vary.** Large swings mean higher volatility; small swings mean lower volatility. This project forecasts that variability, not whether SPY's price will rise or fall.

## 1. Load and check prices

Download daily SPY prices through `yfinance` from **2014-11-01 inclusive to 2026-01-01 exclusive**. Use `Adj Close` with `auto_adjust=False`. The 2014 data supplies history for forecasts starting in 2015.

Save prices once with request settings, retrieval time, package versions, and a SHA-256 fingerprint. Later runs verify and reuse this snapshot. `--offline` requires it to exist. Relative data/output paths are resolved from the config file's grandparent directory.

Check that dates are ordered and unique, adjusted prices are finite and positive, and every expected `NYSE` trading session is present. Holidays are excluded; early-close days still count. Stop on bad data rather than filling or repairing it.

## 2. Calculate returns and the forecast

After trading day `t` closes, calculate its log return:

```text
r_t = ln(adjusted_close_t / adjusted_close_(t-1))
```

The baseline forecast is the **sample standard deviation of the latest 20 returns**, including today's return. Standard deviation measures variability. The historical outcome, or **target**, is the standard deviation of the next five returns:

```text
forecast_t = sample_std(r_(t-19), ..., r_t)
target_t   = sample_std(r_(t+1), ..., r_(t+5))
```

Every standard deviation uses `ddof=1`: subtract the mean, square the differences, sum them, divide by `n-1`, and take the square root. A window of 20 returns needs 21 prices.

These are **daily volatility** values estimated from daily returns. They are not annualized and are not cumulative five-day returns. A value of `0.01` means 1% daily return variability.

Five inputs are saved for later model comparisons:

| Input | Information used after today's close |
| --- | --- |
| `volatility_5`, `volatility_10`, `volatility_20` | Variability of the latest 5, 10, and 20 returns |
| `log_return` | Today's return |
| `momentum_5` | Sum of the latest five returns |

Record the target's start and end dates. Exclude rows with incomplete history or future targets, including the final five observations. Targets judge historical forecasts; they never enter forecast inputs.

## 3. Keep time periods separate

| Forecast dates | Purpose |
| --- | --- |
| 2015-2021 | Training history; later model fitting |
| 2022-2023 | Validation: measure and compare forecasts |
| 2024-2025 | Reserved final test; not scored yet |

Remove training rows whose target ends on or after the first actual validation forecast date. Apply the same rule between validation and test. This is called **purging**: it keeps a future outcome from crossing into the next period. Use actual trading dates, not calendar-day estimates.

Inputs may use earlier observations across a boundary because those prices were already available. Any later preprocessing or model fitting must use training data only. Choose settings using validation, then fix those choices before examining test performance.

## 4. Measure error

For forecast `b` and observed target `y`:

```text
MAE  = 100 * mean(abs(b - y))
RMSE = 100 * sqrt(mean((b - y)^2))
```

Both use **daily-volatility percentage points**. MAE is the average absolute error; RMSE gives large errors more weight. A difference of `0.002` in decimal volatility is `0.2` percentage points.

Report all validation dates and a second sample starting at the first validation date, then taking every fifth trading session. Verify that the second sample's target windows are disjoint. Adjacent daily targets share returns, so their errors are dependent; nonoverlapping windows still do not guarantee independence.

Yearly diagnostics include MAE, RMSE, count, and bias: `100 * mean(b - y)`. Positive bias means overprediction on average. These describe the same validation sample.

## 5. Verify and save

An independent checker recomputes every saved training/validation row using explicit NumPy slices. It checks inputs, targets, dates, purging, predictions, sampling, counts, and errors. Numerical tolerance is `1e-9` relative and `1e-12` absolute. A mismatch fails the run. Reserved test tables are not opened or scored by this checker.

Each successful run saves a report, plots, CSV tables, audit, calculation checks, metrics, configuration, dependency versions, snapshot fingerprint, and source-code fingerprints. Training plots use training data; forecast-comparison plots use validation data.

## Limits

A five-return target is a noisy estimate of volatility. Yahoo can revise historical adjusted prices, so the fixed snapshot is reproducible but does not guarantee what was published on each historical date. Passing calculation checks does not prove forecast usefulness or trading profitability. See [baseline results](results.md) for measured performance.
