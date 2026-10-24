# Pooled development results

Verified on **2026-10-24** using the original cached yfinance snapshot. Test remains reserved and unscored.

| Model | N | MAE (pp) | RMSE (pp) | Bias (pp) |
| --- | ---: | ---: | ---: | ---: |
| baseline | 414 | 0.425492 | 0.744812 | 0.066660 |
| ridge | 414 | 0.362214 | 0.631828 | 0.008138 |
| random_forest | 414 | 0.347832 | 0.605301 | 0.009412 |
| gradient_boosting | 414 | 0.338782 | 0.555092 | 0.019159 |

Units are daily-volatility percentage points. All models use the same 414 validation rows; no predictions required the zero floor. The split has 1,932 training / 414 validation / 415 reserved test rows. All validation and reserved test targets overlap training outcome returns. This is a pooled random-holdout comparison with information overlap, not a leakage-free future forecasting evaluation.

The newer archive described by the handoff was unavailable. Results are a new run on the preserved snapshot, not exact archive reproduction. Baseline and Ridge are close to the rounded handoff figures; small tree-model differences cannot be uniquely attributed without the missing snapshot and version record. Model settings were not changed to match reference scores.

- [Run report](../artifacts/runs/20261024T163643_pooled_b62233b3/results.md)
- [Run record and source hashes](../artifacts/runs/20261024T163643_pooled_b62233b3/run_record.json)
- [Verification evidence](../artifacts/integration_verification_2026-10-24.json)
- [Current cumulative PDF](../output/pdf/SPY_Research_Report_current.pdf)
- [Stable LaTeX source](../report/main.tex) and [weekly build instructions](../report/README.md)
- [Historical chronological baseline](results.md) remains a different evaluation sample.

The full suite passed 70 tests; after final figure/font and open-PDF handling changes, all 15 focused pooled/report tests passed. The original baseline reproduces its recorded metrics. Six core pooled outputs match byte-for-byte across repeated offline runs. All seven final PDF pages were visually checked.

Generated artifacts and raw data are ignored by Git; preserve the snapshot, selected run and report build bundle to reproduce this edition. Next: agree temporal robustness dates, row roles and label-availability purge before execution. No final test evaluation was added.
