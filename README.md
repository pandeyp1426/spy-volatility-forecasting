# An AI Agent for Short-Term SPY Volatility Forecasting

Pradeep Pandey · University of Wisconsin–Stout · Independent study with Dr. Augustine Twumasi.

Phase 1 prepares a fixed SPY dataset, builds daily return and volatility features, and evaluates a historical-volatility baseline on validation data. Linear regression, random forest, and an Amazon Bedrock interface backed by S3 are later milestones. This local phase needs no AWS resources or credentials.

See [the progress report](docs/phase1_progress.md) for what actually ran and any empirical results, [research definitions](docs/research_design.md) for the methodology, and [the roadmap](docs/roadmap.md) for later work.

## Windows PowerShell setup

Open the repository folder containing `pyproject.toml`, `configs/`, and this README in VS Code. In the supplied workspace, that is the inner `spy-volatility-forecasting` folder. Run all commands below from this repository root.

The source requires Python 3.11 or newer; the recorded environment uses **Python 3.12.14 on Windows**, so use Python 3.12 to reproduce the pinned dependencies. Install Python from [the official Windows downloads](https://www.python.org/downloads/windows/) if it is unavailable. If a project-local `.venv` already exists, skip its creation and use it directly.

On this machine, setup found only Windows Store aliases on `PATH`. A local runtime was installed under `.tools/python/`, and `.venv` was created from it. Keep that `.tools/python/` directory while using this environment; no activation or global `PATH` change is needed. Both directories are ignored by Git.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

`requirements-lock.txt` records the package versions used for this setup, including test and notebook dependencies. For a new environment that resolves dependencies from `pyproject.toml` instead of reproducing those versions, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,notebook]"
```

The commands call the environment's interpreter explicitly, so activation and PowerShell execution-policy changes are unnecessary. The lock records versions, not package hashes or a cross-platform guarantee; the saved run record also identifies the actual runtime.

## Run Phase 1

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/phase1.toml
```

The first successful run downloads daily SPY data. Later runs reuse the saved snapshot and verify its metadata and SHA-256 hash. Each experiment writes to a separate directory under `artifacts/runs/`. Internet access is needed for the initial download and dependency installation. A failed download or failed data audit stops the experiment; synthetic data is used only in tests.

Settings live in [configs/phase1.toml](configs/phase1.toml): ticker, download dates, historical windows, forecast horizon, split dates, and output locations. The proposed defaults are working choices to discuss with Dr. Twumasi. If you change the ticker, dates, or calendar, also choose a new `paths.snapshot_dir`; a mismatch with existing metadata stops the run. The workflow never silently refreshes an existing snapshot. Relative paths are resolved from the config file's grandparent (the repository root for `configs/phase1.toml`). Preserve the snapshot together with the run artifacts when sharing an experiment outside Git.

## VS Code notebook

1. Install VS Code's Python and Jupyter extensions if they are missing.
2. Use **Python: Select Interpreter** and select `.venv\Scripts\python.exe` in this repository.
3. Open [notebooks/phase1.ipynb](notebooks/phase1.ipynb). At the top right, choose **Select Kernel → Python Environments** and the same `.venv` interpreter.
4. Select **Run All**. The notebook calls `spy_volatility.pipeline.run_phase1`, prints the validation metrics, and displays the saved plots.

The notebook and command line use the same implementation. No separate Jupyter server installation or global kernel registration is required. If the package import fails, confirm the selected kernel and rerun the editable installation command above.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests use clearly labeled artificial fixtures and do not need Yahoo access. They check sample standard deviations, feature and future-target alignment, incomplete windows, chronological boundary purging, data-audit failures, metric units, and the invariance of past inputs when future prices change.

## What is being forecast?

After trading day `t` closes, calculate the daily log return from adjusted closing prices:

```text
r_t = ln(P_t / P_(t-1))
sample_std(x_1, ..., x_n) = sqrt(sum((x_i - mean(x))^2) / (n - 1))
```

The inputs are sample standard deviations of the latest 5, 10, and 20 returns, the latest return, and the sum of the latest 5 returns. Every input uses information through `t` only. The target is the sample standard deviation of the next 5 returns, from `t+1` through `t+5`. The baseline forecast is the sample standard deviation of the latest 20 returns, including `r_t`.

Every standard deviation uses `ddof=1`. The target and baseline remain **unannualized daily volatility**: the five-day horizon supplies five daily observations. For example, volatility `0.01` means approximately 1% daily return variability. It does not represent a cumulative five-day return.

## Dataset and evaluation

The requested download begins **2014-11-01 inclusive** and ends **2026-01-01 exclusive**. The initial 2014 observations provide historical warm-up; forecast examples begin in 2015. The download explicitly uses `auto_adjust=False`, and returns use the `Adj Close` field. The source documents inclusive/exclusive date boundaries and single-ticker column behavior in the [yfinance download reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html).

The audit checks date order, duplicate dates, finite positive adjusted prices, and expected U.S. equity sessions using the `NYSE` calendar in [pandas_market_calendars](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html). Missing sessions are investigated instead of filled. Early-close days still count as trading sessions.

| Forecast dates | Role |
| --- | --- |
| 2015–2021 | Training-period exploratory plots; future model fitting |
| 2022–2023 | Validation of the historical baseline; later model choices |
| 2024–2025 | Reserved final test; performance remains uncomputed |

Examples with incomplete historical inputs or incomplete future targets are excluded, including the final five observations. Each retained example records its target's start and end dates. Training rows are removed when their target-end date reaches or passes the first actual validation forecast date; the same rule separates validation from the final test. This uses observed trading dates rather than calendar-day estimates.

Validation MAE and RMSE are reported in **daily-volatility percentage points**, with forecast counts. Errors computed from decimal returns are multiplied by 100: an error of `0.002` is `0.2` percentage points. A second evaluation uses forecasts spaced five trading sessions apart and explicitly checks that future outcome windows do not overlap. Daily forecasts have overlapping targets, so their errors are dependent; nonoverlapping windows reduce this overlap but do not establish statistical independence.

## Saved files

Raw snapshots live under `data/raw/<snapshot>/`, with source data and metadata recording request settings, retrieval time, date coverage, package versions, and the data hash. Generated data, local environments, and run outputs are ignored by Git.

Each successful `artifacts/runs/<unique UTC run>/` contains:

| File | Purpose |
| --- | --- |
| `data_audit.json` | Data integrity and trading-session checks |
| `features.csv` | Complete historical inputs, targets, and target dates |
| `split_summary.json` | Date coverage, counts, and boundary purging |
| `train.csv`, `validation.csv`, `test_reserved.csv` | Chronological experiment tables |
| `training_history.png` | Returns and historical volatility during training |
| `validation_predictions.csv` | Daily validation targets and baseline forecasts |
| `validation_nonoverlapping_predictions.csv` | Validation subset with disjoint outcome windows |
| `validation_baseline.png` | Observed validation volatility versus the baseline |
| `metrics.json` | Validation MAE, RMSE, counts, and unit labels |
| `run_record.json` | Run configuration and exact snapshot reference/hash |
| `dependencies.txt` | Installed package versions for this run |

`test_reserved.csv` is saved for the later final evaluation. Its existence is not a test score; avoid using its outcomes to choose features or models.

If the provider or audit fails, the run records the actual error in `run_record.json` and `error.txt`, plus `data_audit.json` when available. No empirical metrics are invented. Inspect these files before retrying; a partial or altered snapshot requires investigation rather than automatic replacement.

```text
configs/                 Experiment configuration
src/spy_volatility/      Shared data, feature, evaluation, and pipeline functions
notebooks/phase1.ipynb    Thin notebook using the shared pipeline
tests/                   Focused offline checks
docs/                    Research design, actual progress, and roadmap
data/raw/                Local fixed snapshots (ignored)
artifacts/runs/          Local experiment outputs (ignored)
```

Yahoo's historical adjusted prices can be revised. A fixed snapshot makes this experiment reproducible, but it is a retrospective dataset rather than a guaranteed point-in-time archive of what was published on each forecast date. Document source limitations and any future data-source change before interpreting the results.
