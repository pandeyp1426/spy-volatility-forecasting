# Collector review, November 27, 2026 (America/Chicago)

Work is isolated on `fix/collector-deadlines-and-formal-2027`; no production switch or formal activation has occurred.

## Diagnosis

The NYSE early close was November 27 at 18:00 UTC / noon Central. The unchanged issue deadline was 20:00 UTC / 2 p.m. Central. Workflow cron requested early-close attempts at 18:07, 18:37, 19:07 and 19:37 UTC, plus ordinary-close fallback polls at 21:07, 21:37, 22:07 and 22:37 UTC. Ordinary November closes are 21:00 UTC / 3 p.m. Central with a 23:00 UTC deadline.

The complete scheduled-run API returned only three runs since activation, with no queued or cancelled entries:

| Run | Created/start UTC | Collection log UTC | Result |
| --- | --- | --- | --- |
| [45935025093](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/runs/45935025093) | Nov 27 03:35:09 | Nov 27 03:36:04.809 | Outside window; no forecast; deployment skipped |
| [46093065017](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/runs/46093065017) | Nov 28 01:25:47 | Nov 28 01:26:42.316 | Outside window; no forecast; deployment skipped |
| [46101732041](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/runs/46101732041) | Nov 28 03:12:32 | Nov 28 03:13:19.205 | Outside window; no forecast; deployment skipped |

For run 46093065017 the Windows job started at 01:26:00 UTC, 13 seconds after run creation; collection ran 42 seconds later. Its collection was already 5h26m beyond the early-close deadline. There is no API run record for the earlier November 27 triggers. These data do not distinguish a dropped trigger from one that never materialized, or identify which cron slot produced each delayed run. They do show that the visible runner startup duration was not the source of the multi-hour delay. `cancel-in-progress:false` cannot make delayed or missing cron events meet a deadline.

The wrapper's outside-window return also skipped missing-session accounting and all outcome maintenance. Comparing only forecast rows prevented a coverage-only dashboard update. The fix preserves the original deadline and truthful timestamps; it does not reconstruct November 27 or any other missed forecast.

Official references: [NYSE hours and early closes](https://www.nyse.com/trade/hours-calendars), [GitHub scheduled-event limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [Windows Task Scheduler](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page).

## Observed production state

- `PILOT_HOSTED=true`; the `pilot-evidence` environment permits only `main` and contains the named deploy-key secret. Only secret metadata was inspected.
- `spy-volatility-pilot-evidence` is private; its designated deploy key is write-enabled. Latest checkpoint is `6f2a2b8`, with 15 journal events, zero missing-session events and zero external receipts. Offline chain, evidence and numerical replay passed.
- Latest published origin: **2026-11-20**; actual issue: **2026-11-22T05:22:28.095106+00:00** (November 21, 11:22:28 p.m. Central), **late**. Event hash: `76fbfcde2a912bcaf7ed082b3c13e9b51977f345b74939e3cf0e86765493771b`. All three predictions remain unchanged.
- Its five targets are November 23, 24, 25, 27 and 30; the original forecast must not gain an outcome before November 30's close.
- [Current Pages dashboard](https://pandeyp1426.github.io/spy-volatility-forecasting/), [last observed successful deployment run](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/runs/46100259759), [workflow history](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/workflows/dashboard.yml).

## Validation and remaining activation

The complete Python suite passed **351 tests** in 243.44 seconds with no failures or skips (`artifacts/collector-final.xml`). After the final restored-journal and Git-ancestry safeguards, **16 focused service/retention tests** passed (`artifacts/collector-service-final.xml`); these include three new isolated receipt-probe checks. The dashboard passed type checking, lint, six unit tests, the production build/schema/hash audit and seven browser tests, including visible missed-session coverage without replacing the original forecast.

The real Windows scheduled probe used the same interactive user, hidden invocation, battery/wake and overlap settings as the proposed pilot service. Its configured trigger was **2026-11-28T03:30:23Z**; the script began **03:30:24.8971809Z** and completed **03:30:29.3383768Z**, with Task Scheduler result 0 and zero missed runs. It performed only the read-only formal readiness check: all 36 frozen hashes passed and the frozen calendar still contains 251 sessions / 246 eligible origins. An initial probe using default AC-only settings did not launch on this battery-powered laptop; the final task permits battery operation. The one-time probe was removed after saving its definition and result under `artifacts/scheduler_review/`. This validates an available host's launch timing, not future power/network uptime or next-close acquisition.

The separate disabled formal task XML passed the Microsoft Task Scheduler schema. Changed PowerShell scripts parsed successfully. A real S3 probe was attempted with the checked-in formal configuration and correctly refused because retention is disabled. AWS CLI and an AWS profile are absent. No genuine receipt is claimed. The frozen protocol, model and existing pilot operations configuration were not changed; the private journal was inspected and replayed without adding events.

The next pilot live acceptance session is **November 30, 2026**, 3–5 p.m. Central, pending merge, writer handoff and host availability. Verify collection, private checkpoint, replay and Pages separately. Formal collection remains inactive; its first eligible session is **January 4, 2027**, 3–5 p.m. Central. Administrator-provisioned S3, effective IAM review, a successful isolated receipt and explicit formal activation remain required.
