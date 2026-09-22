# Phase 1 progress - 2026-09-22

Pradeep Pandey, University of Wisconsin-Stout. One-credit independent study with Dr. Augustine Twumasi.

**Completed:** the local preparation and historical-baseline experiment ran successfully on real SPY observations. The reserved final test has not been scored. No regression, random forest, or AWS integration was performed in this phase.

## Workspace and environment

The existing Git repository was found in the inner `spy-volatility-forecasting` directory. Its original README was expanded and its empty, untracked `.gitignore` was populated. No applicable `AGENTS.md`, `draft_independent_study.docx`, or `SPY_Phase1_Starter.ipynb` was present. The IDE-listed setup prompt was not present on disk; the supplied attachment provided the requirements. No material research-design conflict was found. No commit, remote change, push, or AWS resource creation was performed.

Windows PowerShell initially found only Windows Store Python aliases. Setup downloaded uv 0.12.18 into ignored `.tools/`, used it to obtain a local CPython runtime, and created `.venv`. Actual interpreter: **Python 3.12.14**. Actual platform: `Windows-11-10.0.26200-SP0`. Initial compiled-module imports were slow; they completed successfully and subsequent execution was quick.

Core installed versions: NumPy 2.5.3, pandas 3.0.6, yfinance 1.7.0, pandas_market_calendars 5.4.0, matplotlib 3.11.2, pytest 9.1.1, and ipykernel 7.3.0. Full pins are in [requirements-lock.txt](../requirements-lock.txt); `.python-version` records the runtime. Per-run dependency lists and source-file hashes are saved as well.

## Commands and verification actually completed

Run these from the repository root; the first creation command below records the local runtime used on this machine.

```powershell
.\.tools\python\cpython-3.12.14-windows-x86_64-none\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,notebook]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m spy_volatility --config configs/phase1.toml
```

Installation succeeded. `pip check` reported no broken requirements. **43 tests passed**, including numerical alignment, future-price invariance of historical inputs, incomplete windows, actual-date boundary purging, nonoverlapping windows, audit failures, snapshot tampering, cache reuse, metric units, and the complete pipeline's success/failure paths. Artificial data appears only in the offline test fixtures.

The installed `yfinance.download` signature was inspected and supports every explicit request option used. The four notebook code cells were executed using the project interpreter; with the download function disabled for that check, they reused the saved snapshot and reproduced identical validation metrics. This checks notebook code execution, not the VS Code kernel-selection UI. Both saved PNG plots were visually inspected. An independent NumPy calculation from the raw CSV also matched all 496 saved validation baseline and target values. `git diff --check` passed.

## Real dataset and run records

- Source: Yahoo Finance via yfinance; explicit `Adj Close` with `auto_adjust=False`, `back_adjust=False`, `repair=False`, and `keepna=True`.
- Requested interval: 2014-11-01 inclusive through 2026-01-01 exclusive.
- Retrieved at UTC: `2026-09-22T23:12:26.266690+00:00`.
- Actual coverage: **2014-11-03 through 2025-12-31**, **2,807 rows**, matching all 2,807 expected NYSE sessions.
- Audit passed: chronological dates; no duplicates, missing/nonfinite/nonpositive adjusted prices, missing sessions, or unexpected sessions. No filling or repairs were needed.
- Raw snapshot: [raw.csv](../data/raw/spy_2014-11-01_2026-01-01/raw.csv), with [metadata.json](../data/raw/spy_2014-11-01_2026-01-01/metadata.json).
- SHA-256: `2e65e0a45ec8e6bc81339f2fe3f07a3069c905f8e613e7eda723cb96121e16bf`.
- Real CLI run: [run_record.json](../artifacts/runs/20260922T231222_17bc271a/run_record.json).
- Notebook/cache verification run: [run_record.json](../artifacts/runs/20260922T231257_201f1228/run_record.json).

Data and generated output links point to ignored local artifacts, so they will not appear in a fresh clone. Retain the fixed snapshot with its metadata to reproduce these exact numbers. The raw file is a serialization of the returned single-ticker table, including the other returned price/action fields; no prices were adjusted or repaired by this code.

## Split and validation findings

| Partition | Complete examples before purge | Purged | Retained | Retained forecast dates |
| --- | ---: | ---: | ---: | --- |
| train | 1763 | 5 | 1758 | 2015-01-02 through 2021-12-23 |
| validation | 501 | 5 | 496 | 2022-01-03 through 2023-12-21 |
| test | 497 | 0 | 497 | 2024-01-02 through 2025-12-23 |

The first actual validation forecast is 2022-01-03; the first actual final-test forecast is 2024-01-02. Five rows were purged at each boundary using `target_end >= next_partition_first_forecast`. Warm-up prices are used for inputs, while saved forecast examples begin in 2015. The final five observations lack complete future targets and are excluded.

| Validation sampling | Forecasts | MAE (daily-volatility percentage points) | RMSE (daily-volatility percentage points) |
| --- | ---: | ---: | ---: |
| Every retained validation session | 496 | 0.3462058904 | 0.4663757359 |
| Every fifth session; disjoint target windows | 100 | 0.3576862866 | 0.4662794739 |

The disjoint-window sample is anchored at **2022-01-03** and advances exactly five trading sessions; every outcome window ends before the next one starts. Adjacent daily forecasts share future returns, so their errors are dependent. Disjoint outcomes do not imply statistical independence.

These figures come directly from [metrics.json](../artifacts/runs/20260922T231222_17bc271a/metrics.json). All audit, feature, split, prediction, and plot outputs are saved alongside it. Training-only plots use the purged training partition; observed-versus-baseline plots use validation. The 497 reserved test examples were prepared and saved but **no final-test performance was computed**.

## Remaining issues and discussion with Dr. Twumasi

No operational blocker remains. The baseline supplies a comparison reference; it does not establish that a learned model improves forecasting.

1. Confirm the proposed download interval and 2015-2021 / 2022-2023 / 2024-2025 periods before comparing models.
2. Confirm that the next five daily returns' sample standard deviation, in unannualized daily units, is the intended target.
3. Is Yahoo's retrospective adjusted-price history sufficient for this study, given possible vendor revisions and the absence of a true point-in-time archive?
4. Keep all daily forecasts as the primary validation view and the preselected five-session spacing as the secondary view; agree on how to describe dependent errors.
5. Agree on a small regression/random-forest comparison before the later S3/Bedrock work. Freeze choices using validation before one final-test evaluation.

See [research_design.md](research_design.md) for calculations and limitations, and [roadmap.md](roadmap.md) for the remaining milestones.

## Next command

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/phase1.toml
```

This creates a new experiment directory while verifying and reusing the same snapshot.
