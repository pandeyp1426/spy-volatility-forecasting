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

## Execution and objects

`application.ExperimentRunner` is the application boundary. It owns a configuration path and offline setting, selects a workflow from explicit `ExperimentDefinition` objects, and imports only the selected implementation. The CLI uses this class for all six workflows, including prospective preparation. Unknown strategies fail before execution. The existing `pipeline.run_phase1` function delegates to the runner so notebooks and earlier callers remain compatible.

Workflow modules own their scientific sequence and safety checks. `pipeline.run_chronological` implements the original baseline; `pooled` and `next_phase` implement the other model experiments; `sensitivity`, `uncertainty`, and `prospective` handle later stages. Offline-only workflows enforce that restriction internally even if the common CLI flag is omitted.

Numerical calculations remain ordinary functions in `research`, `models` and the diagnostic modules. Scikit-learn estimators already encapsulate fitted model state. Introducing inheritance around every calculation would add indirection without a useful state boundary. Independent verification modules deliberately recompute the arithmetic rather than depending on the producing score functions.

## Reproducibility and compatibility

Source modules remain in one package so existing source-hash and source-copy contracts continue to identify all executing Python files. Existing import paths, notebooks, config locations, raw snapshots, frozen bundles and historical run folders are preserved. Documentation is organized separately; new prospective bundles copy protocol documents from `docs/protocols/`.

`docs/archive/historical/` preserves metrics and source provenance used by the run register. The archived README/requirements bytes are covered by its manifest. Its README describes the original external archive, not commands to run from this checkout. These historical records are not executable report-generation support.

Results use Markdown, CSV/JSON and PNG plots. PDF/LaTeX builders, templates, dependencies and builder-only tests have been removed. The register can still inventory pre-existing report artifacts without generating them. Existing frozen run bundles remain untouched. PDF and LaTeX outputs remain ignored to prevent accidental commits of old local artifacts.
