# Dependence-aware uncertainty protocol

Fixed on 11 November 2026 before computing these intervals. Historical scores and model comparisons were already examined; this is retrospective uncertainty analysis, not a confirmatory preregistration. The source is temporal run `20261027T001114_temporal_4bf4a071`. All saved model forecasts, training thresholds and reserved identities remain fixed. No new data, fitting, tuning or reserved responses are used.

## Estimand and sampling

Estimate uncertainty in aggregate forecast error and paired model-minus-reference error differences, conditional on the saved fits and the original six-year composition. Primary sample: outcomes contained in the forecast calendar year. The original temporal sample is a sensitivity analysis. All eleven saved model/variant groups remain paired on identical forecast identities.

Construct each annual grid from every eligible forecast identity in the saved pooled assignment map, including reserved identities at both edges. Grids retain consecutive original trading-session numbers. Reserved and excluded origins are masked positions with no observed loss; they are never compressed or treated as observed zero errors. The grid spans the original eligible forecast dates, not unavailable later forecast origins beyond the frozen snapshot.

Use a paired stationary bootstrap within each annual grid. Start uniformly at a grid position. At each subsequent position, restart uniformly with probability `1 / mean_block_length`; otherwise advance one original session, wrapping circularly within that annual grid. Draw exactly the original grid length for each replicate/year. Resample the eligibility masks and every model's losses with the same indices.

Use 5,000 replicates, seed 42, and separate deterministic generators `default_rng(SeedSequence([42, block_length, year]))`. Expected block lengths are 5, 10, **20 (primary)**, 40 and 60 original trading sessions. These are frozen sensitivity choices, not estimated optimal lengths. Disclose every length; never select the interval that looks most favorable.

For each subset, year and replicate, divide each summed eligible loss by that replicate's eligible count. Combine annual mean losses using fixed original subset weights `n_year / N`. Compute aggregate RMSE as the square root of the aggregated squared error, never the average of annual RMSEs. This holds historical year composition fixed despite variation in resampled masks. Retain and report zero-denominator draws; withhold interval endpoints if any replicate is invalid, rather than redraw or silently drop it. An original zero-count stratum has zero weight.

## Reported intervals and comparison family

Report nominal 95% percentile intervals (linear-interpolated 2.5th/97.5th percentiles) for MAE, MSE, RMSE and signed bias. Paired differences cover all nine learned variants versus both benchmarks, tuned versus fixed within each family, and volatility-only versus full fixed features. Compute differences within each paired replicate, including differences of square roots for RMSE.

The two primary contrasts are **fixed Ridge minus each historical benchmark in RMSE**, on the contained sample with expected block length 20. In addition to their nominal 95% intervals, report 97.5% individual percentile intervals (1.25th/98.75th percentiles), a Bonferroni adjustment for this two-comparison family at approximate 95% family coverage. All other models, metrics, lengths and subsets remain exploratory. The adjustment does not account for prior model selection or all exploratory comparisons.

Negative differences favor the named learned model. An interval containing zero does not establish the sign of the difference under this approximation; it is not proof of equal performance. No bootstrap sign fraction is reported as a p-value or probability that a model is best. These are intervals for aggregate errors and differences, not prediction intervals for future volatility. Sparse tail groups retain descriptive scores from the prior phase; this phase does not estimate tail intervals.

## Assumptions and limits

Politis and Romano's stationary bootstrap resamples random-length blocks under stationarity and weak-dependence assumptions. Percentile intervals rely on asymptotic approximation. Our masked, annually stratified scheme is a project adaptation; its coverage is not established by citing that theorem. [Original paper](https://users.ssc.wisc.edu/~behansen/718/Politis%20Romano.pdf).

Annual strata preserve regime weights but ignore dependence across annual boundaries. Containment removes cross-year response sharing, not all cross-year dependence. Approximate stationarity within a crisis year may fail. Circular sampling creates artificial year-end/year-start joins; length 60 provides few effective blocks per year. Time-series bootstrap accuracy can be poor in finite samples. [Methodological review](https://www.ssc.wisc.edu/~bhansen/718/HardleHorowitzKreiss.pdf).

The intervals condition on already fitted and historically selected models; training and selection uncertainty are omitted. They do not establish performance in an untouched period, and even a zero-excluding adjusted interval is retrospective evidence under these assumptions. The separately frozen [2027 evaluation protocol](prospective_protocol.md) uses its own future observations.

## Reproduction and independent audit

Save source predictions and identity metadata, full configuration and execution source, original point estimates, all resampling indices, replicate scores/counts, complete interval tables, missing-draw counts and input/output hashes in a fresh run directory. Independently reconstruct masks, generator draws, weighted metrics and quantiles from the saved evidence. Preserve the original experiment files and excluded response matrices.
