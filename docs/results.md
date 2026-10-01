# Baseline results

Verified on **2026-10-01** using the saved SPY snapshot. These results describe the historical-volatility baseline; no learned model has been fitted.

## Validation performance

Errors are in **daily-volatility percentage points**. Lower is better.

| Sample | Forecasts | MAE | RMSE |
| --- | ---: | ---: | ---: |
| Every validation session | 496 | 0.3462 | 0.4664 |
| Every fifth session | 100 | 0.3577 | 0.4663 |

The second sample starts on 2022-01-03 and has disjoint future outcome windows.

| Forecast year | Forecasts | MAE | RMSE | Bias |
| --- | ---: | ---: | ---: | ---: |
| 2022 | 251 | 0.4566 | 0.5843 | +0.0464 |
| 2023 | 245 | 0.2331 | 0.3010 | +0.0617 |

Positive bias means forecasts were too high on average. Error varies across years; these results alone do not establish consistent accuracy or improvement from machine learning.

## Data and checks

- **2,807 price rows:** 2014-11-03 through 2025-12-31, with all expected NYSE sessions present.
- **1,758 training rows and 496 validation rows:** every saved calculation passed the independent check.
- **497 reserved test rows:** prepared but never scored.
- **55 tests passed.** A repeat offline run reproduced the original metrics exactly and seven saved result files byte for byte.

Snapshot SHA-256: `2e65e0a45ec8e6bc81339f2fe3f07a3069c905f8e613e7eda723cb96121e16bf`.

The [saved report](../artifacts/runs/20261001T163824_e4db32f0/results.md) includes charts and links to its run record, audit, verification, and exact metrics. [Reproduction evidence](../artifacts/reliability_recheck.json) records the repeat-run comparison and environment differences. Actual dependencies are saved with each run; the existing environment was not a clean reinstall of the lock file.

These links point to local files ignored by Git. Preserve the snapshot and run folder to reproduce these exact numbers. Use the [README](../README.md) to create a new run, or read [how it works](research_design.md) for the calculation details.
