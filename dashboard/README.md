# SPY Volatility Lab

The public site presents approved research observations from the Python project. Build and export from the repository containing `pyproject.toml`. GitHub Pages serves the static site under `/spy-volatility-forecasting/`.

## Source map

The single-page dashboard shows the SPY price, the five-session forecast, the frozen Ridge inputs, and historical market and model-performance charts. The local preview checks Yahoo Finance each minute and displays the last completed regular-session minute bar in Eastern time. The static version embeds a TradingView quote. Provider delay and market closures affect both feeds. Ridge uses adjusted daily closes.

`ForecastReport` presents each validated forecast in model order and converts predictor units for display. The research charts use verified series and metrics from the Python exporter.

On the research machine, run `npm.cmd run build` and `npm.cmd run pilot` in `dashboard/`, then open `http://127.0.0.1:4173/spy-volatility-forecasting/`. The preview includes verified local 2026 pilot forecasts. The static release displays approved public forecasts. See [operations](../docs/operations.md) for scheduling and recovery.

| Public dataset | Trusted input | Publication boundary |
| --- | --- | --- |
| Market | Original 2014-11-03 through 2025-12-31 Yahoo SPY adjusted-close snapshot | Verify the designated digest offline, then run `core.research.build_predictors`. Publish prices and trailing return series only. Preserve missing warm-up values. |
| Historical results | Designated annual temporal run, sensitivity run and uncertainty run | Selected aggregate metrics, tail results, subset comparisons and previously evaluated development observations. No pooled reserved responses. |
| Forecasts | Live 2026 pilot events replayed from private evidence and individually approved records | Publish projections of approved records. Only separately approved 2026 labels can carry an observed value. Formal results require a separate reviewed evaluation release even after January 10, 2028. |
| Research status | Maintained public status configuration, research decisions and protocol documents | Reviewed milestones and activation status as of the stated review date. |
| Manifest | Exporter's UTC clock and SHA-256 of each public dataset | Distinguish publication time from forecast issue time, price vintage and study status. |

The public repository contains only the website's projected datasets. The hosted runner restores its inputs from the private evidence repository. A fresh clone can serve the included approved release. Python supplies the forecasts and benchmarks.

## Run and test

Use Node.js 24 and the checked-in lockfile. From the repository root in PowerShell:

```powershell
cd dashboard
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/spy-volatility-forecasting/` (or the printed port). Existing page bookmarks open the same single-page view.

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
npm.cmd run test:browser
npm.cmd run preview -- --host 127.0.0.1
```

The browser tests start an isolated production preview on port 4187. They use installed Microsoft Edge on Windows. On Linux, run `npx playwright install --with-deps chromium` first. The production build writes `dashboard/dist/` and audits its file inventory, release schemas, SHA-256 fingerprints, historical date bounds and common credential signatures.

## Refresh from verified private evidence

The exporter automatically releases each original, verified 2026 pilot. A date and event hash in `configs/public_forecasts.toml` can select a specific record. Publishing a pilot outcome requires its own approved hash. Formal 2027 forecasts require an explicit hash and a qualifying retention receipt. Formal outcomes require separate review.

```powershell
# From the repository root on the research host
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations verify
.\.venv\Scripts\python.exe -m spy_volatility.workflows.public_export
$testPath = 'artifacts/w' + [Guid]::NewGuid().ToString('N').Substring(0,5)
.\.venv\Scripts\python.exe -m pytest -q --basetemp $testPath -p no:cacheprovider
```

The exporter checks the designated run records and selected tables, replays approved forecast/label calculations and reads the journal in a read-only transaction. It stages all six datasets before replacing the public files, then replaces the manifest last. Verify the resulting build and inspect the release diff. All generated scientific values are deterministic for identical evidence. Each export receives a new UTC publication timestamp. Input vintage, forecast issue time, historical date coverage and outcome acquisition time are retained independently.

Missing or changed source artifacts stop the export. Restore the pinned evidence on the research host and rerun. A visible dashboard checks the manifest once a minute, on returning to the tab and on manual refresh. A replacement release must pass schema and digest checks for previously loaded data before the page switches. A failed check keeps the previous verified release visible. The footer shows the export timestamp and last successful check separately. Missing rolling-window values stay `null`.

## Hosted updates

After activation, GitHub Actions checks for eligible closes, checkpoints the private journal, replays the forecasts and deploys the verified dashboard to Pages. An open tab checks for a release every minute. The displayed issue time comes from the journal. The live ticker updates independently. See the [one-time handoff and recovery instructions](../docs/operations.md#hosted-2026-pilot).
