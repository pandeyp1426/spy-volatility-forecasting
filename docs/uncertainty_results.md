# Dependence-aware uncertainty results

Completed 11 November 2026 local time. Source temporal run: `20261027T001114_temporal_4bf4a071`. The [frozen protocol](uncertainty_protocol.md) predates these interval calculations; historical model comparisons were already known.

Designated uncertainty run: `20261112T033412_uncertainty_33ba49a1`. Designated prepared 2027 bundle: `20261112T033437_prospective_121fb52e`, under `artifacts/protocols/`. IDs use UTC. Full suite: **231 tests passed**, including 68 new focused tests. Repeated real executions reproduced all bootstrap arrays and result tables, and the frozen model/schedule. Input/output hashes and all 12 annual-grid audit rows were verified. Evidence: `artifacts/uncertainty_prospective_verification_2026-11-11.json`.

## Main finding

Ridge retains lower observed aggregate RMSE than both benchmarks, but the uncertainty estimates distinguish the two comparisons. Against the 20-session benchmark the primary interval excludes zero; against the five-session benchmark it includes zero. Therefore the historical evidence does not establish a reliable advantage over both benchmarks under this approximation.

| Fixed Ridge minus benchmark | RMSE difference (pp) | Nominal 95% interval | Adjusted individual 97.5% interval |
| --- | ---: | --- | --- |
| 20-session volatility | -0.104491 | [-0.191275, -0.019687] | [-0.205119, -0.011320] |
| Five-session volatility | -0.061938 | [-0.155012, +0.038964] | [-0.162735, +0.051089] |

Negative values favor Ridge. These primary estimates use 1,252 observations with outcomes contained within each forecast year, mean block length 20 original sessions, and 5,000 paired replicates. The adjusted intervals account for the two primary comparisons only; they do not account for prior historical model selection. Nominal coverage is not a guarantee of actual coverage.

Across all five declared block lengths (5, 10, 20, 40, 60), and both the contained and original samples, the nominal interval for Ridge versus the 20-session benchmark stays below zero, while the interval against the five-session benchmark crosses zero. These are disclosed sensitivity analyses, not a search for a favorable interval. Crossing zero does not prove equal performance.

## Computation and verification

The bootstrap resamples consecutive original-session blocks within annual strata, jointly for every model. Excluded/reserved origins remain masked positions rather than being compressed out of the time axis. Each year retains its original scoring weight, with its resampled loss sum divided by its resampled eligible count. RMSE is the square root of aggregate MSE. No model is refitted and no reserved response matrix is read.

Saved evidence includes all five sets of resampling indices, replicate scores and counts; 440 score intervals; and 720 paired comparison intervals covering benchmarks, tuning and feature ablation. Independent verification regenerated **37,575,000 indices** and reconstructed loss arithmetic and interval endpoints. No invalid draws occurred. Every source identity/hash check passed; all 415 reserved identities remained excluded.

## Limits and next evaluation

The estimates condition on already fitted, historically selected models and the original six-year composition. They omit training/selection uncertainty and cross-year dependence. Within-year stationarity and circular joins are approximations, particularly during crises. They are not future-volatility prediction intervals or confirmatory evidence of generalization.

The stationary-bootstrap foundation is described by [Politis and Romano](https://users.ssc.wisc.edu/~behansen/718/Politis%20Romano.pdf); [Hardle, Horowitz and Kreiss](https://www.ssc.wisc.edu/~bhansen/718/HardleHorowitzKreiss.pdf) discuss limitations of time-series bootstrap approximations. The masked annual construction is a project adaptation.

The [2027 protocol](prospective_protocol.md) freezes fixed Ridge and both benchmarks before future outcomes. A model has been prepared from 2,346 permitted 2015–2025 observations, with no future data acquisition or scoring. The calendar has 246 contained forecast origins. Implementing trustworthy daily acquisition and timestamped forecast records remains necessary before live collection; no scheduler or logger was started by this work.
