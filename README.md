# SPY Volatility Forecasting

This project estimates how much SPY's daily returns will vary over the next five trading sessions. It uses the variability of the latest 20 daily returns as a simple starting forecast, called a **baseline**.

**Load prices → check data → calculate forecasts → compare with what happened → save results.**

The current version evaluates historical forecasts locally. It does not yet train a machine-learning model.

## Run in PowerShell

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

The report includes checks, scores, yearly results, and charts. The 2024-2025 final test remains reserved and unscored.

See [how it works](docs/research_design.md) for the calculations and [baseline results](docs/results.md) for the verified numbers.

## Project files

| Location | Purpose |
| --- | --- |
| `configs/phase1.toml` | Dates, forecast windows, and file locations |
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

Next: compare linear regression and random forest with the baseline on the same validation dates, then fix model choices before evaluating the reserved test.
