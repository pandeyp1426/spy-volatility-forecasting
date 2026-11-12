# Separate manual pilot: November 11, 2026 close

A real pilot forecast was generated successfully from newly acquired Yahoo Finance SPY data. It predicts the **sample standard deviation of daily log returns over the entire next five trading sessions**, not five separate daily price predictions, a cumulative return, or annualized volatility.

This pilot does not amend or operate the frozen 2027 protocol. Its recorded creation time is over eight hours after the scheduled close, outside the 120-minute rule that applies to that future study. It is not claimed as an on-time or externally timestamped prospective observation. No model was refitted, no reserved outcomes were read or scored, and no scheduler was started.

## Origin, data and calendar

- Origin: **2026-11-11**, scheduled regular-session close **16:00 America/New_York / 15:00 America/Chicago / 21:00 UTC**.
- Explicit adjusted close: **759.8099975585938 USD**.
- Target sessions: **2026-11-12, 2026-11-13, 2026-11-16, 2026-11-17, 2026-11-18**.
- Acquisition: **2026-11-12T05:08:35.390420+00:00**, or November 11 at 23:08:35 America/Chicago.
- Forecast creation: **2026-11-12T05:08:36.047584+00:00**, or November 11 at 23:08:36 America/Chicago.
- Source: Yahoo Finance through **yfinance 1.7.0**, using the existing project's daily request settings: explicit `Adj Close`, `auto_adjust=False`, `back_adjust=False`, `repair=False`, `keepna=True`, `actions=True`, `ignore_tz=True`, no pre/post-market observations, and no rounding.
- Single vintage: **21 positive, finite, ordered, unique and consecutive exchange-session prices from October 14 through November 11, 2026**. No missing or unexpected sessions; no filling, splicing or stale-session fallback. The request end was November 12 exclusive.
- Raw CSV SHA-256: `55f5a71924e4c0f3a7b617d9cebcb76fe11f1e67495010b99df928b6535879d7`.

The versioned `pandas_market_calendars 5.4.0` NYSE schedule determines completed sessions using `market_close < selection_time`, including daylight saving and early closes. The [official NYSE holiday and trading-hours page](https://www.nyse.com/trade/hours-calendars), reviewed November 11, confirms regular 16:00 Eastern closes and the 2026 holiday/early-close schedule. Veterans Day is not an exchange holiday. The next November closure is Thanksgiving on November 26, followed by a 13:00 Eastern close on November 27. Calendar tests cover weekends, holidays, early closes, daylight saving and the exact close boundary. Actual exchange close-event timestamps were not independently acquired; unscheduled changes remain an operational limitation.

## Frozen model identity

The decision log designates `20261112T033437_prospective_121fb52e`, whose status remains `prepared_not_live`. All **36** recorded artifact hashes passed, along with the frozen config, source and input hash checks. Historical inputs were hashed without parsing response tables. The existing preparation verification reports that JSON predictions match the originally fitted estimator exactly.

- Model SHA-256: `b9fb8225931f0f0e0ce55a6862842baa011f6b0479b0250a54294331dd34a85c`.
- Freeze-record SHA-256: `f4802ee310ca641c31444ae9a54e7b581808b44e8d78bbbd6876f7bfd0620d03`.
- Frozen config SHA-256: `03cc4aa16a36f1d099342fddd33643e65acae2908bdfab33419a7ec717f2aab4`.
- Ridge alpha: **1.0**; prediction floor: **0.0**; **2,346** permitted historical training rows with labels ending no later than December 31, 2025.
- Scaler means/scales, ordered coefficients and intercept are loaded unchanged from `artifacts/protocols/20261112T033437_prospective_121fb52e/model.json`. The pilot also retains an exact copy in its output directory. No replacement model can be trained by this command.

## Calculations and forecast

For adjusted price `P_t`, the return is `r_t = ln(P_t / P_(t-1))`. Each trailing SD uses the latest `n` returns including `r_t`, subtracts their mean and divides squared deviations by **n - 1**. Momentum is the sum of the last five log returns, also checked against `ln(P_t / P_(t-5))`.

| Predictor, in stored model order | Decimal value | Units |
| --- | ---: | --- |
| `log_return` | 0.01310188742648096 | Daily log return |
| `volatility_5` | 0.026261164111068235 | Daily log-return sample SD |
| `volatility_10` | 0.0193901114267922 | Daily log-return sample SD |
| `volatility_20` | 0.014239191914939334 | Daily log-return sample SD |
| `momentum_5` | -0.009170650300842706 | Sum of five daily log returns |

Stored scaling gives `z = (x - mean) / scale`, in the same order:

```text
[1.1391593307795234, 2.450782400210697, 1.5708189123145564,
 0.7800898183050331, -0.50691892722783]
```

The raw Ridge value is `z @ coefficients + intercept`, with stored intercept `0.00874768790164364`. The final value is `max(raw, 0)`.

| Forecast | Decimal daily SD | Daily SD (%) |
| --- | ---: | ---: |
| Raw Ridge | 0.016372786661413053 | 1.6372786661 |
| Final Ridge | 0.016372786661413053 | 1.6372786661 |
| 20-session historical benchmark | 0.014239191914939334 | 1.4239191915 |
| 5-session historical benchmark | 0.026261164111068235 | 2.6261164111 |

The floor was not active. All three forecasts share the same origin and input vintage. Their future target is `sample_SD(r_(t+1), ..., r_(t+5))`; no target values were acquired or calculated.

## Verification and retained evidence

Successful output: `artifacts/pilots/20261112T050827_pilot_76608a08/`.

- `pilot_record.json`: timestamps, prepared identity, results, source/config hashes, artifact manifest and limitations.
- `snapshot/raw.csv` and `snapshot/metadata.json`: complete yfinance-returned fields, request settings, acquisition time, versions and vintage hash.
- `calendar.csv`: the 21 input sessions and five intended target sessions, with scheduled opens and closes.
- `returns.csv`, `data_audit.json`, `verification.json`: all 20 calculated returns, input audit and 14 passing numerical checks.
- `model.json`, `source/`, `report.md`: copied frozen parameters, executing source and readable results.

The verifier uses scalar `math.log`, explicit trailing slices, `statistics.stdev` and `math.fsum`, independent of the pandas rolling path. It checks all returns, each predictor, momentum's telescoping identity, feature order, scaling, raw prediction, zero floor and both benchmarks. A restored StandardScaler and Ridge estimator also predict without any fit calls. Tolerance is **rtol=1e-9, atol=1e-12**; maximum raw Ridge difference was **3.47e-18**, and maximum difference across all checks, including standardized features, was **8.88e-16**.

The new predictor extraction also passed an artificial-data comparison against the **unchanged, hash-verified research.py saved in the prepared bundle**, including complete historical examples and truncated 21-price prefixes. This verifies the extraction without supplying fabricated future outcomes to the live calculation. Offline replay of the real pilot passed and reproduced its numerical results exactly.

Two unsuccessful attempts remain preserved: `20261112T050726_pilot_d82991fe` (default yfinance cache inaccessible) and `20261112T050805_pilot_5991d070` (restricted network connection). A workspace-local cache resolved the first issue, and an approved network-enabled invocation resolved the second. Neither attempt contains a forecast.

## Reproduction commands

From the directory containing `pyproject.toml`, acquire a **new** vintage for the then-latest completed session:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.workflows.pilot --config configs/pilot.toml
```

To reproduce this recorded forecast **offline**, without issuing another forecast:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.workflows.pilot --replay artifacts/pilots/20261112T050827_pilot_76608a08
```

The prepared bundle and pilot artifacts are local ignored evidence; preserve them. A fresh clone alone cannot replay the result. Replay rechecks the original bundle and all pilot artifact hashes. The new-acquisition command does not accept a backdated issue time and never silently falls back to older prices.

Focused and complete verification commands (use a fresh temporary path for each invocation):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/workflows/test_pilot.py tests/core/test_research.py tests/workflows/test_prospective.py -q --basetemp artifacts/test_tmp_pilot_first -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q --basetemp artifacts/test_tmp_pilot_full -p no:cacheprovider
```

The focused run passed **68 tests**; the full suite passed **245 tests** in 141.10 seconds. Tests exercise missing/corrupt prepared artifacts, the zero floor, malformed and stale prices, explicit adjusted-close selection, tamper detection, offline replay, and guards against fitting or response-table access.

Yahoo may revise adjusted prices. The retained CSV is the exact numeric DataFrame vintage returned by yfinance, not the original HTTP response bytes. No independent vendor price check or trusted external timestamp retention was added. Local hashes establish consistency, not historical publication time. This pilot provides a verified forecast calculation, not evidence of predictive performance.
