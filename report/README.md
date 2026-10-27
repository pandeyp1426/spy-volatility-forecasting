# Cumulative report

`main.tex` and `references.bib` are the stable cumulative source. The build command generates tables from a named successful pooled run and optional verified temporal development run, checks artifact hashes and protocol compatibility, copies vector figures, and archives the exact source bundle. It reads no reserved test matrix and performs no modeling. Factual ranking claims come from the selected run; fixed scientific prose has compatibility guards.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/pooled.toml --offline
.\.venv\Scripts\python.exe -m spy_volatility.weekly_report --run artifacts/runs/RUN_ID --render
```

Use the `output_dir` printed by the first command. The date defaults to America/Chicago; use `--date 2026-10-23` to reproduce that edition's date. Install Tectonic on PATH or place it at `.tools/tectonic/tectonic.exe`; alternatively pass `--compiler PATH`. Tectonic may download TeX packages on its first build. Rendering requires the `report` optional Python dependency.

To rebuild the completed cumulative edition with temporal results:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.weekly_report --run artifacts/runs/20261024T163643_pooled_b62233b3 --development-run artifacts/runs/20261027T001114_temporal_4bf4a071 --date 2026-10-26 --render
```

To execute the frozen temporal analysis again, run `.\.venv\Scripts\python.exe -m spy_volatility --config configs/temporal.toml --offline` and select its new run folder in the report command. Required local inputs are the intact `data/raw/spy_2014-11-01_2026-01-01` snapshot and the named pooled parent folder, including its saved split map, training/validation tables, predictions, metrics, figures and provenance. They are ignored local artifacts, not downloadable GitHub links. A fresh download cannot replace the snapshot silently.

The temporal edition retains the full machine register and artifact index in its build bundle, renders a compact complete run register in the appendix, and separates pooled, annual development, fitted training and proposed future work. Preserve the build folder and indexed input folders when sharing reproducible evidence. The source ZIP from the earlier progress report and the missing newer EDA archive remain explicitly distinguished.

Outputs are under `output/pdf/`: a dated PDF, `SPY_Research_Report_current.pdf`, and a build directory containing input hashes, generated LaTeX, figures, compiler log and page PNGs. Review **every** rendered page for clipping, missing images, legibility and wrapping. Compilation alone is not visual approval. Builds record visual review as pending until inspected. Existing dated editions are preserved; a revised build gets a distinct name.

Only the agreed 2015-2025 experiment is accepted by this report narrative. Change the narrative deliberately if the study period changes. A successful run does not mean the final test was evaluated: it must remain unscored to build this report.

`historical/` contains exact CSV/README/requirements members of the supplied October 14 progress archive and its hash manifest. `handoff_reference.json` contains rounded comparison values quoted from the handoff, not values used by models or pass/fail thresholds. The newer EDA package was unavailable.
