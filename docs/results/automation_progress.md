# Technical progress: SPY forecast collection

Prepared for research discussion with Dr. Augustine Twumasi, University of Wisconsin–Stout. Updated November 19, 2026.

## What changed

The project now has an operational workflow that can be called manually or by a scheduler. It finds the latest completed NYSE session, requests adjusted SPY prices from Yahoo Finance through the existing yfinance settings, and generates the same three volatility forecasts as the verified manual pilot. It stores the forecast before collecting its later outcome. This reduces the risk of missed manual steps and makes failures, data revisions and timestamps auditable.

The model has not changed. The five-session and twenty-session benchmarks use recent sample return variability directly. Ridge combines the original five inputs using its frozen training scaler and coefficients. All three predict one sample standard deviation of daily log returns over the next five trading sessions, not prices or annualized volatility. The workflow reuses the existing pilot calculation and independent verification functions; no retraining, tuning or reserved-response scoring occurs.

## Evidence and outcomes

Each attempt receives an identifier, an isolated data snapshot and an append-only journal entry. The record includes the input vintage, ordered predictors, model/protocol hashes, scheduled close, local creation/acquisition timestamps, target dates and validity/timeliness status. Corrections and retries preserve earlier records. An interrupted worker leaves evidence that the next invocation identifies explicitly.

Only after the fifth future session closes can the system acquire a new six-price snapshot covering the origin and five future sessions. It calculates the five log returns, their mean and sample standard deviation using `ddof=1`. A separate implementation checks the arithmetic. This outcome is linked to the forecast without editing it. The 24-hour target-acquisition deadline is enforced for the formal primary label candidate; delayed or revised data are sensitivity records.

The optional S3 adapter can retain an evidence package with a checksum, immutable object-version identity and storage-provider timestamp. It requires a configured private versioned bucket and external credentials. It has not been connected to a live destination. Local hashes alone cannot prove historical publication time or prevent a privileged operator from rewriting an entire local history. The implementation also does not independently observe the actual exchange closing event or automatically monitor official interruption announcements.

## Scientific separation

The November 11 forecast remains a separate manual pilot with its original issue time. New 2026 operational pilots have an explicit separate sample policy. Neither is a qualifying 2027 result.

The prepared 2027 study is different from the earlier retrospective work because its parameters were fixed before the evaluation period and its forecasts must be retained before the future outcomes are available. Operational monitoring may check data completeness and record validity. Per-forecast errors and comparative aggregates for 2027 remain blocked until January 10, 2028. Descriptive MAE, MSE, RMSE and bias functions have been implemented for that future evaluation; the full frozen dependence-aware uncertainty and coverage analysis remains required at final scoring.

No general conclusion about Ridge's predictive advantage follows from automation or one pilot observation. Historical uncertainty against the five-session benchmark remains inconclusive, and high-volatility underprediction remains a limitation.

## Verified manual pilot outcome

On November 19 at **08:08:53.546912 UTC**, the collector acquired six adjusted closes from Yahoo for November 11, 12, 13, 16, 17 and 18. The fifth target session's scheduled close was November 18 at 21:00 UTC. The new acquisition was within its 24-hour label window; this does not change the original forecast's late issue time. No new live forecast was issued.

The observed sample standard deviation of the five daily log returns was **0.006995661396605764**, or **0.6995661397% daily volatility**. Independent scalar arithmetic differed by only `8.67e-19` in decimal units. These values describe the whole five-session window, not five daily price predictions.

| Method | Original predicted daily volatility | Signed error (percentage points) |
| --- | ---: | ---: |
| Frozen Ridge | 1.6372786661% | +0.9377125265 |
| 20-session benchmark | 1.4239191915% | +0.7243530518 |
| 5-session benchmark | 2.6261164111% | +1.9265502714 |

All three overpredicted this single outcome. The separate `manual_pilot_2026` sample has **n = 1** and supports no general performance claim. The outcome is preserved as `artifacts/operations/pilot_2026/outcomes/20d5fac72b60421186cbc91e4c58089d/`, linked to the unchanged original forecast. Its raw CSV SHA-256 is `fa4a55173f9dae37923104649dd7dfef1293846df3d96a23c3ad292aaefaad51`.

Two earlier attempts remain in the journal: a restricted-network failure and a datetime-index precision mismatch. The latter exposed a pandas/yfinance compatibility issue; normalizing only the comparison's index precision now allows identical session dates while requiring exact price equality. A regression test covers both forecast and outcome acquisition. The successful retry used a new data snapshot rather than rewriting either failed attempt. No external timestamp receipt exists for this local pilot evidence.

## Demonstration and activation status

The controlled demonstration uses artificial prices, a simulated clock and a separately labelled journal. It exercises forecast creation, duplicate suppression, refusal of premature outcomes, matured target calculation, error computation, revised outcomes and offline replay. It is not a new market forecast. Automated tests also cover calendar boundaries, malformed/stale data, preservation, interruption recovery, model/data tampering, the scoring embargo, and storage-adapter receipts without using real cloud credentials.

The final full suite passed **296 tests with no failures or skips**. All 36 prepared artifact hashes still match; the original historical price snapshot and manual forecast are unchanged. The final synthetic demonstration verified nine journal events, and the separate live manual-pilot journal verified eleven. The [verification record](../../artifacts/automation_verification_2026-11-19.json) identifies the exact source hashes, tests, preserved data, demo and real outcome.

A disabled Windows Task Scheduler XML proposal has been generated and checked against Microsoft's published schema. No task has been registered or enabled. The recommended deployment polls every five minutes and relies on the exchange calendar inside Python. The machine must remain powered, logged in and connected; downtime produces missing or late records rather than backdated observations.

Before activation: configure and verify external versioned retention, review the collection rules and paths, verify permissions and system clock synchronization, test task execution and wake behavior under the intended account, establish daily failure monitoring, and approve activation. Formal 2027 issuance is blocked while retention is disabled. Instructions and exact commands are in [operations](../operations.md).
