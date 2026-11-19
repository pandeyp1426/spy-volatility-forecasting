# Project architecture

## Repository boundaries

| Directory | Responsibility |
| --- | --- |
| `src/spy_volatility/` | Importable application and scientific calculations |
| `configs/` | Versioned experimental choices; keep at this depth because paths resolve relative to the project root |
| `tests/` | Artificial-data tests, integration checks and holdout protections |
| `docs/protocols/` | Research definitions and frozen evaluation rules |
| `docs/results/` | Human-readable findings and limitations |
| `docs/archive/` | Small historical metrics and provenance used by the run register |
| `notebooks/` | Optional thin entry points using the same application code |
| `data/`, `artifacts/`, `output/` | Ignored local snapshots, immutable experiment evidence, prepared models and generated reports |

## Package responsibilities

- `application.py`: `ExperimentRunner` and immutable workflow definitions; one CLI entry point.
- `core/`: data loading/audits, feature/target calculations and model definitions.
- `analysis/`: training EDA, temporal fitting/search, diagnostic metrics and Markdown results.
- `workflows/`: orchestrates each experiment, its config, evidence and verification.
- `verification/`: independent arithmetic and membership checks; deliberately does not reuse producing score functions.
- `infrastructure/`: recursive source hashing/snapshotting and experiment inventory.

Tests mirror these responsibilities. End-to-end workflow tests remain with their workflow so their safety guards and artificial fixtures are easy to locate. Config files stay immediately under `configs/` because all saved experiment paths resolve relative to its parent.

## Execution and compatibility

`ExperimentRunner` loads a configuration and lazily selects its workflow. `workflows.baseline.run_phase1` remains the compatibility function used by the updated notebooks. The unified `python -m spy_volatility --config ...` command and both console-script aliases stay unchanged. The old standalone `python -m spy_volatility.prospective` command has a tiny forwarding entry point; the actual implementation is in `workflows/prospective.py`.

Python modules now use explicit imports such as `spy_volatility.core.models` and `spy_volatility.workflows.baseline`. Consumers of the former flat Python module paths must update imports; the project tests and notebooks have been updated. Numerical functions remain functions, and fitted sklearn estimators retain model state. This avoids class hierarchies with no useful state boundary.

The separate manual `python -m spy_volatility.workflows.pilot` command loads the designated prepared bundle through pinned hashes. `core.research.build_predictors` exposes the same historical predictor calculations used by `build_features`, without requiring future labels. `verification.pilot` independently checks scalar return/window arithmetic and reconstructs sklearn prediction state without fitting. New snapshots, reports and unsuccessful attempts go only to `artifacts/pilots/`; `--replay` verifies a saved pilot offline without issuing another forecast. This is not the 2027 collection workflow. See [pilot evidence and commands](pilot_forecast.md).

`workflows.operations.Operations` runs one collection tick and reuses `pilot.calculate`, `load_prepared`, `get_snapshot` and their existing numerical checks. `core.outcomes` contains the mature target and guarded scoring formulas, including independent scalar verification. `infrastructure.forecast_store` owns the append-only SQLite journal, previous-event hashes, evidence manifests and process lock. `infrastructure.retention` provides optional versioned S3 uploads through AWS CLI v2; credentials remain outside the repository. The collector's storage adapter never refits an estimator or opens reserved response tables.

Forecast attempts and outcome attempts have separate immutable directories and linked journal events. Importing the November 11 pilot preserves its original record and issue time. Corrections append new events, and a restarted process labels incomplete attempts as interrupted. Hashes and local clocks alone are never certified as prospective timestamp evidence. External version/checksum/server-time receipts supplement them; real 2027 issuance is blocked when retention is disabled. All formal errors and aggregate comparisons are embargoed until the frozen scoring date.

The PowerShell scripts under `scripts/` are a one-tick logging wrapper and a file-only scheduler proposal generator. The proposal is disabled and unregistered. Neither a persistent service nor an automatically activated scheduled task is installed. Artificial-clock demonstrations use `workflows.operations_demo` and a distinct store marked `synthetic_demo`; production acquisition rejects synthetic snapshots. See [operations](operations.md) for deployment boundaries, backup/recovery, known-calendar notices and commands.

## Reproducibility

`infrastructure.provenance` hashes every Python module recursively with a package-relative path. Its shared source-copy routine preserves subfolders and validates every copy against the run's source hashes. New run bundles therefore include the complete nested implementation rather than just the workflow directory. Old frozen source bundles, parent runs, snapshots and model protocols remain unchanged and keep their original recorded paths and hashes.

`docs/archive/historical/` preserves metrics and source provenance used by the run register. The archived README/requirements bytes are covered by its manifest. Its README describes the original external archive, not commands to run from this checkout. These historical records are not executable report-generation support.

Results use Markdown, CSV/JSON and PNG plots. PDF/LaTeX builders, templates, dependencies and builder-only tests have been removed. The register can still inventory pre-existing report artifacts without generating them. Existing frozen run bundles remain untouched. PDF and LaTeX outputs remain ignored to prevent accidental commits of old local artifacts.
