# Cumulative report

`main.tex` and `references.bib` are the stable source. The build command generates tables from a named successful pooled run, verifies artifact hashes, copies the run's vector figures, and archives the exact source bundle. It reads no reserved test matrix and performs no modeling.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility --config configs/pooled.toml --offline
.\.venv\Scripts\python.exe -m spy_volatility.weekly_report --run artifacts/runs/RUN_ID --render
```

Use the `output_dir` printed by the first command. The date defaults to America/Chicago; use `--date 2026-10-23` to reproduce that edition's date. Install Tectonic on PATH or place it at `.tools/tectonic/tectonic.exe`; alternatively pass `--compiler PATH`. Tectonic may download TeX packages on its first build. Rendering requires the `report` optional Python dependency.

Outputs are under `output/pdf/`: a dated PDF, `SPY_Research_Report_current.pdf`, and a build directory containing input hashes, generated LaTeX, figures, compiler log and page PNGs. Review **every** rendered page for clipping, missing images, legibility and wrapping. Compilation alone is not visual approval. Builds record visual review as pending until inspected. Existing dated editions are preserved; a revised build gets a distinct name.

Only the agreed 2015-2025 experiment is accepted by this report narrative. Change the narrative deliberately if the study period changes. A successful run does not mean the final test was evaluated: it must remain unscored to build this report.

`historical/` contains exact CSV/README/requirements members of the supplied October 14 progress archive and its hash manifest. `handoff_reference.json` contains rounded comparison values quoted from the handoff, not values used by models or pass/fail thresholds. The newer EDA package was unavailable.
