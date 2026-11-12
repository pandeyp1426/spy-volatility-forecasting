# Retrospective temporal development results

Completed run: `20261027T001114_temporal_4bf4a071` (26 October 2026 local; run ID uses UTC). Parent pooled run: `20261024T163643_pooled_b62233b3`. Starting commit: `7a8c55aa19b85782ecec7786438cc95e150a1819`; the run records executing source hashes and copies, including uncommitted implementation changes.

This is a separately named retrospective robustness analysis. The original snapshot and saved pooled membership are unchanged. All 415 pooled reserved identities are excluded from new fitting, tuning and diagnostic scoring. No reserved response matrix was opened. Shared underlying returns and prior historical data reuse mean this is not an untouched final test.

## Executed protocol

The preregistration in `docs/decision_log.md` and `configs/temporal.toml` preceded scoring. Development has 2,346 rows. Six annual outer folds (2020–2025) produce 1,272 common evaluation observations per model. Each annual fit uses development labels fully known by the previous year's final trading close. Inner selection uses three earlier annual folds with the same label-availability checks. Actual session timestamps, membership and excluded boundary rows are saved.

Execution order: unchanged fixed models; 5-session comparator; frozen nested search; fixed three-volatility feature ablation. There were 26 candidates per outer fold, 156 candidate evaluations, 468 inner fits and 66 outer model/comparator records, with zero fit failures. The experiment recorded 111.27 seconds of compute time, excluding subsequent diagnostics and report work. Lowest full-precision concatenated inner RMSE selects each family, with candidate ID breaking exact ties.

## Measured results

All errors below use daily-volatility percentage points; all rows have N=1,272. Aggregate RMSE is calculated from concatenated errors, not averaged annual RMSE.

| Model / variant | MAE | RMSE | Signed bias |
| --- | ---: | ---: | ---: |
| 20-session baseline | 0.453678 | 0.764881 | +0.071697 |
| 5-session comparator | 0.464684 | 0.723675 | +0.003463 |
| Fixed Ridge | 0.387937 | 0.661175 | -0.069041 |
| Fixed Random Forest | 0.410661 | 0.793810 | -0.126779 |
| Fixed gradient boosting | 0.414673 | 0.804137 | -0.127539 |
| Tuned Ridge | 0.387089 | 0.660334 | -0.068942 |
| Tuned Random Forest | 0.409384 | 0.791692 | -0.129919 |
| Tuned gradient boosting | 0.414822 | 0.803606 | -0.133430 |
| Volatility-only Ridge | 0.404154 | 0.702558 | -0.066428 |
| Volatility-only Random Forest | 0.429678 | 0.814449 | -0.121429 |
| Volatility-only gradient boosting | 0.439119 | 0.876837 | -0.123967 |

The pooled tree-model advantage does not persist on this temporal sample. Fixed Ridge reduces RMSE by 13.56% against the 20-session baseline and 8.64% against the 5-session comparator. Fixed forest and boosting lower MAE but increase RMSE against both benchmarks. The pooled and temporal samples differ, so their absolute score levels are not a controlled before/after comparison.

Tuning lowers aggregate RMSE by about 0.13%, 0.27% and 0.07% for Ridge, forest and boosting, respectively. These small descriptive changes are not evidence of statistical significance. Boosting MAE worsens. Removing return and momentum worsens aggregate MAE and RMSE for all three fixed families; this supports their joint predictive contribution within these models, not causation.

The 112 outcomes at or above each fold's training-derived 95th percentile expose a limitation: the 5-session comparator has RMSE 1.719777, lower than fixed Ridge's 1.823184 and tuned Ridge's 1.823956. Fixed forest/boosting tail RMSE is approximately 2.3744. Tuning worsens tail RMSE for Ridge and boosting, while forest improves slightly. Every learned model underpredicts on average in this high group. The threshold grouping uses realized outcomes and is ex-post, not a forecast-time decision rule.

## Saved evidence and verification

Paths below are relative to the completed run directory in local `artifacts/runs/`. These ignored files are not advertised as GitHub downloads.

| Artifact | Purpose |
| --- | --- |
| `run_record.json`, `source/`, `dependencies.txt` | Data/config/code hashes, source copies, environment and completed status |
| `source_split_assignments.csv`, `reserved_identities.csv`, `development.csv` | Saved roles, excluded identity metadata and permitted observations |
| `temporal_membership.csv`, `temporal_boundary_exclusions.csv`, `temporal_folds.csv` | Exact inner/outer fit and evaluation membership and label timing |
| `temporal_predictions.csv`, `inner_predictions.csv`, `temporal_training_predictions.csv` | Outer predictions, candidate evidence and descriptive fitted errors |
| `candidate_grid.*`, `search_results.csv`, `chosen_parameters.json`, `fit_failures.csv`, `timing.csv` | Complete search, including unselected candidates and empty failure log |
| `tables/diagnostic_{pooled,temporal}_*.csv` | Aggregate, annual/fold, high/low-tail, training gaps, both-benchmark comparisons and full-precision MSE |
| `figures/diagnostic_*.pdf` | Identity scatter, actual-date history and signed-error views |
| `calculation_verification.json` | Independent NumPy windows, exact memberships, selection, scaling and metric arithmetic; passed |
| `experiment_register.json`, `experiment_register.md`, `artifact_index.csv`, `artifact_index.md` | Every discovered run, missing evidence and exact artifact guide |

The original pooled validation predictions were reverified and reused. Only fitted training diagnostics were added; these are labeled descriptive, not validation. Annual and high/low-group tables retain unfavorable outcomes and unavailable empty groups. All calculations use full-precision saved predictions.

## Deferred work

The EDA supports multi-window persistence but also overlapping information and a noisy five-return response. Error diagnostics justify focusing on tail underprediction and annual stability. A separately frozen future-period evaluation and dependence-aware uncertainty analysis remain proposed. No enlarged grid, transformed target, neural network, future download, test scoring or trading-performance claim was added.
