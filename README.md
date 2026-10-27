# SPY Volatility Forecasting

This project estimates how much SPY's daily returns will vary over the next five trading sessions. It uses the variability of the latest 20 daily returns as a simple starting forecast, called a **baseline**.

**Load prices → check data → calculate forecasts → compare with what happened → save results.**

The project includes the pooled 2015–2025 comparison and a completed retrospective temporal robustness analysis with annual 2020–2025 folds, nested tuning and a fixed feature ablation. The earlier chronological pilot is preserved. The pooled reserved test identities remain excluded from every new fit, tuning and scored diagnostic.

The newer EDA research archive was unavailable. The integrated run uses the original cached yfinance snapshot and does not claim exact reproduction of that missing archive.

## Current pooled experiment and cumulative report

Run from the folder containing `pyproject.toml`:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/pooled.toml --offline
.\.venv\Scripts\python.exe -m spy_volatility.weekly_report --run artifacts/runs/RUN_ID --render
```

Replace `RUN_ID` with the printed run folder. The report requires Tectonic and optional PDF-rendering dependencies; see [report build instructions](report/README.md). The stable source is [report/main.tex](report/main.tex); dated/current PDFs are saved under `output/pdf/`. The [pooled notebook](notebooks/pooled.ipynb) invokes the same pipeline.

The exact split is one NumPy seed-42 permutation: floor 70% training, floor 15% validation, remainder testing. Rows are disjoint, but outcome returns overlap across subsets: this is a pooled comparison, not a leakage-free future forecasting test. Test data are structurally audited and reserved, never predicted or scored. See [decisions and discrepancies](docs/decision_log.md).

## Completed temporal development phase

The named pooled run is a required local input. The temporal command always uses the frozen snapshot offline and creates a new run directory:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/temporal.toml --offline
.\.venv\Scripts\python.exe -m spy_volatility.weekly_report --run artifacts/runs/20261024T163643_pooled_b62233b3 --development-run artifacts/runs/20261027T001114_temporal_4bf4a071 --render
```

The second command rebuilds the completed edition from saved results; replace its development run ID to report a new run. See [temporal results](docs/temporal_results.md) for exact evidence and limitations. Fixed Ridge improves aggregate RMSE over both window benchmarks; the fixed tree models do not. Tuning gains are small and tail failures remain. This is retrospective development on reused history, not a pristine final test.

## Preserved chronological baseline

Open the folder containing `pyproject.toml`. If `.venv` already exists, run:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/phase1.toml
```

The first run downloads and saves the data. Later runs reuse that snapshot. To require saved data without internet access:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/phase1.toml --offline
```

Open the printed `report` path (`results.md`) in VS Code and press **Ctrl+Shift+V** to view the tables and charts. Each run creates a new folder under `artifacts/runs/`.

## First-time setup

Use Python 3.12 for the pinned environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Activation is unnecessary because these commands use `.venv` directly. On this computer, the existing environment uses Python from `.tools/python/`; keep that directory while using this environment.

For the notebook, open [phase1.ipynb](notebooks/phase1.ipynb), select `.venv` as its Python kernel, and choose **Run All**. It uses the same code as the command line.

## Read the results

- **MAE:** average absolute forecast error. Lower is better.
- **RMSE:** gives larger errors more weight. Lower is better.
- Both use **daily-volatility percentage points**. A forecast of 1.0% and an observed value of 1.2% differ by 0.2 percentage points.
- **Daily** scores use every validation session. **Nonoverlapping** scores use every fifth session so their future outcome windows do not overlap.

The report includes checks, scores, yearly results, and charts. In the chronological experiment, the 2024-2025 final test remains reserved and unscored. The separately requested pooled experiment has its own reserved random subset.

See [pooled results](docs/pooled_results.md) for the current comparison, [how it works](docs/research_design.md) for the calculations, and [baseline results](docs/results.md) for the preserved chronological pilot.

## Project files

| Location | Purpose |
| --- | --- |
| `configs/phase1.toml` | Preserved chronological pilot |
| `configs/pooled.toml` | Requested pooled experiment |
| `configs/temporal.toml` | Frozen annual development and nested search protocol |
| `src/spy_volatility/temporal.py`, `next_phase.py` | Annual folds, fixed comparison, comparator, tuning and ablation |
| `src/spy_volatility/diagnostics.py`, `next_phase_verification.py` | Separate pooled/temporal diagnostics and independent arithmetic checks |
| `src/spy_volatility/experiment_register.py` | Complete local run register and artifact index |
| `src/spy_volatility/pooled.py` | Exact split, overlap audits and offline comparison |
| `src/spy_volatility/models.py`, `eda.py` | Fixed regressions and training-only EDA |
| `report/main.tex`, `src/spy_volatility/weekly_report.py` | Cumulative source and weekly PDF build |
| `src/spy_volatility/data.py` | Load and check prices |
| `src/spy_volatility/research.py` | Calculate inputs, targets, splits, and errors |
| `src/spy_volatility/pipeline.py` | Run the steps in order |
| `src/spy_volatility/verification.py` | Independently check saved calculations |
| `src/spy_volatility/reporting.py` | Create the results report |
| `src/spy_volatility/provenance.py` | Record which source code was used |
| `tests/` | Check calculations and failure cases with artificial data |
| `data/raw/` | Saved prices and metadata (ignored by Git) |
| `artifacts/runs/` | Generated reports, tables, plots, and run records (ignored by Git) |

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

If you change the ticker, download dates, or calendar, choose a new `snapshot_dir` in the config. Existing snapshots are never silently replaced. Use only runs whose `run_record.json` says `success`; failed runs may contain partial files and an `error.txt` explaining the problem.

Next, proposed only: freeze a separately reserved future-period protocol and justify a dependence-aware uncertainty analysis. Large-outcome underprediction and unstable annual errors deserve attention before expanding the model collection. No future period was downloaded or scored, and no routine command evaluates a final test.
