# SPY Volatility Forecasting

Estimate the standard deviation of SPY daily returns over the **next five trading sessions**. The project compares historical-volatility benchmarks, Ridge, Random Forest and gradient boosting using reproducible historical experiments.

Ridge has lower aggregate temporal RMSE than both benchmarks, but dependence-aware uncertainty leaves its advantage over the five-session benchmark inconclusive. High-volatility underprediction remains unresolved. The 2027 model/protocol is prepared; live forecasting has not started. See [results](docs/results/uncertainty_results.md) and [the future evaluation protocol](docs/protocols/prospective_protocol.md).

## Setup

Run from the directory containing `pyproject.toml`. Use Python 3.12 for the pinned environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

An existing `.venv` can be used directly without activation. On the original development computer it depends on `.tools/python/`; retain that directory.

## Run

All workflows share one entry point:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/uncertainty.toml --offline
```

| Configuration | Workflow | Required local evidence |
| --- | --- | --- |
| `phase1.toml` | Chronological baseline | Cached prices; omit `--offline` for the initial download |
| `pooled.toml` | Pooled model comparison | Cached prices |
| `temporal.toml` | Annual evaluation, tuning and ablation | Named pooled run and cached prices |
| `sensitivity.toml` | Annual containment and nonoverlapping windows | Named temporal run |
| `uncertainty.toml` | Paired block-bootstrap intervals | Named temporal run |
| `prospective.toml` | Prepare frozen 2027 model/protocol | Named temporal development data |

Use `configs/<name>` in the command above. After installation, `spy-volatility` is an equivalent command; the older `spy-phase1` command remains supported. Downstream configurations reference local, ignored evidence and cannot reproduce results from a fresh clone alone. Source snapshots and parent run hashes are checked before use.

Experiments create new folders under `artifacts/runs/`; prospective preparation creates `artifacts/protocols/`. Read the printed report and status. Use successful experiment runs only; a prospective bundle must say `prepared_not_live`. Reserved test responses are not scored by routine commands. No daily scheduler or forecast logger is started.

## Project structure

```text
configs/                 Experiment settings
src/spy_volatility/
  application.py         Class-based workflow selection
  core/                  Data, features, targets and models
  analysis/              EDA, temporal fitting, diagnostics and Markdown results
  workflows/             Baseline, pooled, temporal and later-stage orchestration
  verification/          Independent calculation audits
  infrastructure/        Source provenance and experiment register
tests/                   Mirrors the package responsibilities
docs/
  protocols/             Research definitions and frozen rules
  results/               Findings and limitations
  archive/               Small historical evidence files used by the run register
  architecture.md        Code responsibilities and reproducibility contracts
  decision_log.md        Research decisions and completed milestones
notebooks/               Optional notebook entry points
```

`data/`, `artifacts/`, `output/`, environments and caches stay local and are ignored by Git. Keep the data and run evidence needed by later experiments. Results use Markdown, CSV/JSON and PNG plots; PDF/LaTeX generation is not part of the project.

## Verify and inspect results

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

If this Windows environment denies access to its default temporary directory, use a fresh local path with `--basetemp artifacts/test_tmp_local -p no:cacheprovider`.

Open each successful run's `results.md` where available, together with its CSV/JSON evidence and PNG plots. The [architecture guide](docs/architecture.md) explains the class-based application boundary, functional calculations, compatibility and file-retention choices. [Research decisions](docs/decision_log.md) preserve the full experimental history.
