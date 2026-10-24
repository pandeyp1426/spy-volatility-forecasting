# SPY volatility forecasting — progress report and reproducible pilot

Prepared for Pradeep Pandey's independent study with Dr. Augustine Twumasi,
14 October 2026. This is a separate analysis package; it does not edit the
GitHub repository.

## Scope and limitations

The report uses the supplied original chronological `train.csv` (1,758 rows)
and `validation.csv` (496 rows). It does **not** run the planned pooled
2015–2025 random 70/15/15 experiment. No test dataset is included or scored.
The original adjusted-price snapshot and 2024–2025 data were unavailable,
and a new Yahoo request was rate-limited. The original partitions omit
boundary rows, so concatenating them cannot reconstruct a complete raw series.

The PDF is a progress draft, not a final research-results submission.
The LaTeX has no abstract or table of contents. The figures are vector PDFs.

## Contents

- `Spy_Volatility_forecasting.tex` — editable report.
- `Spy_Volatility_forecasting.pdf` — compiled report.
- `analyze_available_data.py` — standalone audit, EDA, and untuned pilot.
- `requirements.txt` — analytical package versions used in this run.
- `inputs/train.csv`, `inputs/validation.csv` — byte-for-byte supplied inputs.
- `data/` — six-column model tables (five inputs plus response), and separate
  metadata for the combined available sample. These are NOT final random splits.
- `tables/` — audit, detailed checks/statistics, model scores, predictions,
  coefficients, and exploratory Random Forest permutation importance.
- `figures/` — report figures plus the complete validation prediction timeline.

## Reproduce

Use Python 3.12.14 with the package versions in `requirements.txt` (or record
any version changes). From this directory:

```bash
python -m pip install -r requirements.txt
python analyze_available_data.py inputs
latexmk -pdf -interaction=nonstopmode -halt-on-error Spy_Volatility_forecasting.tex
```

If `latexmk` is not installed, run `pdflatex` twice. The LaTeX source expects
the adjacent `figures/` directory. The standalone `.tex` download is editable,
but the full ZIP is the easiest way to reproduce the PDF.

Running the analysis regenerates its derived CSVs, figures, and audit JSON.
Raw input files are read-only to the script. No network requests are made.
Package installation above is an optional local setup step, not a step that
was executed on the user's computer during preparation of this report.

## Modeling conventions

The forecast is made after session t closes. Inputs are today's log return,
sample standard deviations of the latest 5/10/20 daily log returns, and the
sum of the latest 5 log returns. The response is the sample standard deviation
of returns for sessions t+1 through t+5. Standard deviations use ddof=1.
All model data are in decimal units. Metrics use percentage points of daily
volatility. The response is not annualized or cumulative-five-day volatility.

The benchmark predicts the 20-session historical standard deviation.
OLS has an intercept and a zero prediction floor (no validation predictions
were negative). Random Forest settings: 200 trees, maximum depth 5, minimum
leaf size 10, max_features=1.0, bootstrap=True, random_state=42, n_jobs=1.
No hyperparameter search was performed. The every-fifth check starts at the
first validation row's session number; it is not a best-offset selection.

Permutation importance is exploratory, evaluated on the pilot validation
sample with 10 repetitions. It is not causal evidence; correlated predictors
can share or mask predictive information. No feature was removed on this basis.

The independent rolling checks operate on supplied log returns only when the
entire source window is present. They do not independently verify adjusted
prices, exchange calendars, or absent boundary observations.

## Next required input and final-study safeguards

Recover the original `data/raw/spy_2014-11-01_2026-01-01` snapshot and provenance
files if possible. A complete new snapshot is an alternative but must have
new provenance, consistent settings, and validation; do not mix snapshot versions.
Reconstruct the master dataset before random splitting. Preserve professor's
70/15/15 design, fix seed 42, do not stratify, and keep dates out of X but in
metadata. Record exact counts and the row map. Fit preprocessing only on train.

Overlapping time-series windows create dependence across random partitions;
random holdout is not a substitute for a future-only forecasting test. Some
future random-test dates will have appeared in this pilot, so disclose that
history. Seek professor agreement about a separately reserved chronological
check before examining any genuinely untouched period. No PPTX is created yet.
