# Temporal sensitivity results

Completed on 10 November 2026 (local date). The source is the verified temporal run `20261027T001114_temporal_4bf4a071`. The implementation uses saved forecasts only, with no new fits, tuning or data acquisition. See the [frozen subset protocol](../protocols/sensitivity_protocol.md) and `configs/sensitivity.toml`.

Designated completed run: `20261111T035209_sensitivity_f9d56993` (run identifiers use UTC). All **163 tests passed**, including 35 sensitivity tests. A second real offline execution reproduced byte-identical membership, metric, comparison and audit tables. Verification evidence is saved locally in `artifacts/sensitivity_verification_2026-11-10.json`.

## Main comparison

Fixed Ridge continues to have lower aggregate RMSE than both historical benchmarks under annual target containment, every original-session modulo-five offset, and every intersection of these restrictions. This supports robustness of its descriptive aggregate advantage to these particular scoring choices. It does not establish statistical significance or performance in a later untouched period.

| Scoring sample | N | 20-session RMSE | 5-session RMSE | Fixed Ridge RMSE | Fixed forest RMSE | Fixed boosting RMSE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original temporal sample | 1,272 | 0.764881 | 0.723675 | 0.661175 | 0.793810 | 0.804137 |
| Outcomes contained within forecast year | 1,252 | 0.769594 | 0.727041 | 0.665103 | 0.799105 | 0.809505 |
| Nonoverlapping, primary offset 0 | 254 | 0.759064 | 0.720534 | 0.688657 | 0.831813 | 0.836169 |
| Within year and primary offset 0 | 249 | 0.763726 | 0.725361 | 0.693549 | 0.838542 | 0.842992 |

RMSE is measured in daily-volatility percentage points and recomputed from all retained squared errors. Differences between rows reflect changes in sample composition, not improvements obtained by modifying a model.

Containment removes 20 forecasts: 3 from 2020, 5 from 2021, 4 from 2022, 3 from 2023 and 5 from 2024. The remaining forecasts' complete outcomes lie within their forecast calendar years. Models and fitting cutoffs remain unchanged; within-year target overlap remains.

## All sampling offsets

The original `session_number % 5` is applied globally, without resetting the index at annual boundaries or after excluded reserved identities. Offset 0 was fixed as primary before computing these subset scores. All offsets are disclosed.

| Offset | N | N with annual containment | Ridge RMSE reduction vs 20-session benchmark | Ridge RMSE reduction vs 5-session benchmark |
| --- | ---: | ---: | ---: | ---: |
| 0 (primary) | 254 | 249 | 9.28% | 4.42% |
| 1 | 243 | 239 | 19.76% | 13.76% |
| 2 | 254 | 250 | 15.73% | 8.64% |
| 3 | 258 | 254 | 8.79% | 7.51% |
| 4 | 263 | 260 | 14.97% | 9.29% |

The percentage reductions in this table use the nonoverlapping subsets without containment. With containment, Ridge's reduction ranges from 8.82% to 19.90% against the 20-session benchmark and 4.39% to 13.82% against the 5-session benchmark. These ranges describe sensitivity to the offset; they are not confidence intervals. Every offset has at least five original sessions between forecast origins and zero intersecting scored outcome intervals, including across annual boundaries. The offsets overlap in their underlying return information and are not independent replications.

Fixed forest and boosting still have worse aggregate RMSE than both benchmarks in the primary nonoverlapping and combined samples. Across all offsets, forest sometimes narrowly beats the 20-session benchmark but never the 5-session benchmark; boosting beats neither. The small original tuning gains are not uniform: each tuned family has at least one offset with higher RMSE than its fixed counterpart. All eleven variants and unfavorable comparisons remain in the saved tables.

## High-outcome limitation

Annual containment removes none of the original 112 high-outcome forecasts, so their scores are unchanged. The primary nonoverlapping subset contains only 23 high-outcome forecasts. On those rows, the 5-session benchmark has RMSE **1.583905 pp**, compared with **1.878786 pp** for fixed Ridge. Ridge's signed bias is **-1.231997 pp**. The combined containment-plus-offset-zero subset has the same high group and scores.

The existing aggregate advantage therefore still coexists with high-outcome underprediction. Tail membership uses each original fit's training-derived 95th percentile and the realized response; it is an ex-post diagnostic, not an operational forecast-time signal. Sparse tail counts limit precision.

## Reproduce and inspect

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/sensitivity.toml --offline
```

Each execution creates a separate local `artifacts/runs/*_sensitivity_*` directory. Its `run_record.json` identifies the exact source/config hashes and copied execution code. `results.md` provides the readable run report. `membership.csv` records every inclusion/exclusion and its reason. `tables/metrics.csv` includes aggregate and annual MAE, RMSE, MSE, bias and N for all eleven variants and both tail groups, including explicitly unavailable empty groups. `tables/comparisons.csv` retains both benchmark comparisons on identical identities.

The independent verification reconstructs all 12 subset masks, 15,264 membership rows, 2,772 metric rows and 5,544 comparison rows, plus outcome-overlap audits. It uses full-precision saved observations and does not import the producing score functions. The source evidence is hash-checked before and after execution. The 415 pooled reserved identities remain excluded and their responses remain unread and unscored.

The cumulative PDF is unchanged. Dependence-aware uncertainty, a separately frozen later-period evaluation and prospective prediction logging remain subsequent work. Disjoint scored outcome windows leave shared fits, overlapping predictors, persistent volatility and prior historical exposure; these results must not be described as independent observations or an untouched test.
