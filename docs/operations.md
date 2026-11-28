# Forecast collection and operations

## November 27 collector correction (separate review branch)

The hosted GitHub schedules missed the November 27 early-close window. The calendar and two-hour deadline were correct; Actions materialized runs too late. The wrapper also returned before recording missing sessions or collecting matured labels. See [the diagnosis and verification record](results/collector_review_2026-11-27.md). The proposed replacement uses one persistent Windows writer and Actions for private-checkpoint replay and Pages publication. It remains pending merge and activation; the old local task remains disabled.

`operations pilot-cycle` retains missed-session records and matured outcomes even outside the issue window, without issuing retrospective forecasts. `hosted_pilot tick` reports new forecast/outcome/missing counts separately. Full private replay precedes public export. Missing dates are published even if the latest forecast is unchanged. Pilot outcomes remain subject to explicit release approval. No formal outcome or score is automatically published.

After this branch is reviewed and merged, switch the research checkout to clean, updated `main` and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File scripts/activate_pilot_service.ps1 -EvidenceCheckout ..\pilot-evidence-seed-20261124 -WorkerRoot ..\pilot-worker
```

The command verifies merged source and private visibility, creates a separate pinned worker checkout, mounts the private evidence, sets `PILOT_WRITER=windows`, and refuses activation while any old hosted job remains active. If a job is active, wait and rerun. It leaves the original local task disabled. The new task polls every five minutes, uses `IgnoreNew`, and holds an OS lock over the complete pull/collect/checkpoint/replay/dispatch transaction. Git push must succeed before publication; divergent journals are never merged or overwritten. Failed push attempts preserve local evidence for retry. Only the configured writer may collect.

The research PC must stay powered, signed in and connected. The pilot task expires January 2, 2027, after the last pilot label deadline. Keep `PILOT_HOSTED=true` so Actions can publish; `PILOT_WRITER=windows` makes its collection step skip. An external scheduler that merely dispatches Actions would still depend on runner queues and is not a reliable issuance fix. Do not enable simultaneous independent local and hosted writers. To roll back, disable and drain the Windows task, checkpoint its state, then change the writer variable; GitHub cron still cannot promise the deadline.

Monitor the local task `SPY Volatility Lab - persistent pilot`, logs under the worker's `output/pilot_invocations/`, and the separate Actions collection/verification/deployment summaries. At the next eligible close, November 30, 2026 at 3 p.m. Central, verify one original on-time record containing all three methods, a private checkpoint, passed replay, and the identical origin, event ID and actual issue timestamp in Pages. The deadline stays 5 p.m. Central. November 20's fifth target also closes that day; outcome acquisition must be strictly later.

Formal activation is separate: follow [the 2027 runtime, S3 receipt and scheduler checklist](formal_2027_activation.md). AWS CLI, bucket/profile and genuine S3 receipt are not configured or verified on this machine. The sections below retain the earlier deployment history and manual commands.

The research machine has a Windows task for eligible 2026 pilot forecasts. It was registered November 21, 2026 Central, with the first trigger November 23 at 3:05 p.m. Central. It requires a signed-in research user, a running machine and access to Yahoo Finance. External timestamp storage is unconfigured. The formal 2027 collector remains inactive. See the [collection rules](protocols/collection_protocol.md) and [frozen protocol](protocols/prospective_protocol.md).

## Hosted 2026 pilot

The GitHub-hosted Windows runner restores the frozen model, journal and archived inputs from the private `pandeyp1426/spy-volatility-pilot-evidence` repository. An eligible close produces one Ridge forecast and two benchmarks for daily-return volatility across the next five trading sessions. The runner persists the attempt in private Git, replays the evidence, and sends only the six public datasets and their manifest to the dashboard build. The site refreshes after the build and browser checks pass.

**One-time handoff.** Merge the dashboard PR, then run this command from the research repository on the original Windows PC. It uses the authenticated GitHub CLI and the existing private checkout. It verifies the merged workflow, pauses the local task, transfers any subsequent journal events, enables the hosted schedule and requests the first deployment.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\activate_hosted_pilot.ps1 -EvidenceCheckout ..\pilot-evidence-seed-20261124
```

The `pilot-evidence` Actions environment allows only `main` and holds the private repository's write-enabled deploy key under `PILOT_EVIDENCE_SSH_KEY`. Set Pages' build source to GitHub Actions. Collection runs when the public repository variable `PILOT_HOSTED` is `true`. To recreate the seed on the research PC, run `.\.venv\Scripts\python.exe -m spy_volatility.workflows.hosted_pilot seed ..\new-private-seed` and push that checkout only to the private evidence repository.

**Timing and retries.** Attempts are scheduled at 7 and 37 minutes past the hour during the regular two-hour window, with additional attempts after the November 27 early close. The NYSE calendar checks actual eligibility when the runner starts. The last eligible origin is December 23. A delay can miss an origin. The collector records issue times from its clock, and repeated runs reuse the original forecast.

**Monitor or retry.** Inspect the [dashboard workflow runs](https://github.com/pandeyp1426/spy-volatility-forecasting/actions/workflows/dashboard.yml). To retry collection or a failed deployment, run `gh workflow run dashboard.yml --ref main`. Outside the issue window this replays existing evidence. The last successful site stays available if a new build fails. To pause hosted runs, use `gh variable set PILOT_HOSTED --body false` and let the current run finish. Restore the latest private checkpoint before switching collectors. The hosted journal supports pilot recovery. Formal 2027 retention uses the frozen protocol.

### Local after-close pilot

The task starts five minutes after each eligible NYSE close and retries every ten minutes within the two-hour issue window. The last eligible origin is December 23. Retries reuse an existing forecast for the same origin. The worker independently replays the stored forecast before writing a forecast-only projection under `artifacts/dashboard_pilot/`. Each projection is local to the research machine. The public exporter automatically selects verified original 2026 pilot forecasts. Outcomes still require an explicit event hash. The task does not acquire outcomes or score the model.

```powershell
# Run from the repository root. Inspect or pause the installed task.
$pilotTask = 'SPY Volatility Lab - 2026 after-close pilots'
Get-ScheduledTask -TaskName $pilotTask
Get-ScheduledTaskInfo -TaskName $pilotTask
Disable-ScheduledTask -TaskName $pilotTask
# Re-enable a paused task
Enable-ScheduledTask -TaskName $pilotTask
# Install only on an unconfigured research host
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File scripts/register_dashboard_pilot.ps1
# Collect the latest eligible completed session now. A late issuance is recorded as late.
.\.venv\Scripts\python.exe -m spy_volatility.workflows.dashboard_pilot latest
```

Run commands from the directory containing `pyproject.toml`, using the existing Python 3.12 environment. Preserve `.venv`, `.tools/python`, all prepared artifacts and the original pilot. No new Python dependency is required for local operation; optional remote retention requires AWS CLI v2.

## Manual commands

```powershell
# Read-only model, protocol, and calendar readiness check. No acquisition/store.
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations check

# One collection tick: import the designated pilot, forecast the latest eligible
# close, record missed deadlines, collect matured labels, and score 2026 pilots.
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations cycle

# Individual operations
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations forecast
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations import-pilot
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations outcomes --origin 2026-11-11
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations status
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations verify

# Explicit corrections preserve originals; forecasts still use the latest origin.
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations forecast --reason "Provider correction investigation"
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations outcomes --origin 2026-11-11 --reason "Provider revised adjusted history"

# Separate descriptive samples; the formal command is blocked before Jan 10, 2028.
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations metrics --study manual_pilot_2026
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations metrics --study pilot_2026
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations metrics --study formal_2027
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations score
```

No CLI option accepts a backdated forecast issue time or a historical forecast origin. `--origin` selects an already preserved forecast for outcome collection only. Pending outcomes cause no download or premature target calculation. An unsuccessful/invalid/blocked operation exits nonzero; scripts should inspect the recorded reason, not just whether a process ran.

`configs/operations.toml` pins the designated model and protocol record hashes, the November 11 pilot hash, collection start and local store. A changed scientific configuration needs a separate store. External-retention configuration changes are explicitly journaled and do not rewrite prior records.

## Storage, replay and recovery

The default store is `artifacts/operations/`, containing `journal.sqlite3`, a permanent worker-lock file, separate `pilot_2026/` and `formal_2027/` attempt directories, and optional retention packages. Every successful attempt preserves exact configuration and executing source, model JSON, calendar where applicable, raw snapshot, metadata, audits and numerical checks. Journal payloads contain predictions, outcome links and event hashes. Forecast displays include decimal SD and daily-volatility percent.

`verify` is offline: it validates the chain and artifacts and recalculates forecasts, targets, errors and aggregate metrics. It verifies imported pilot evidence through the existing replay command. Never edit the database, delete evidence to hide failures, or reset the chain to make a run appear timely.

Each scheduled invocation uses an OS lock, plus transactional journal appends. A concurrent invocation records a busy result. An interrupted attempt keeps partial files and receives an interrupted record on the next invocation. A new attempt never adopts those partial data as a valid old forecast. Disk-full, access or journal-integrity failures can prevent even a failure record being appended; the process then fails and the wrapper's separate log is the immediate evidence. Correct the storage problem, preserve its files, and rerun `verify` before resuming. Do not delete the lock file to unlock an active worker; the OS releases it when the process exits.

For backups, pause the task and copy the **whole store and prepared bundle** to a versioned destination. Do not copy a running SQLite database casually or retain the journal without its referenced evidence. S3 packages support durable per-record retention, but restoring the entire local working store remains a separate backup responsibility. Local chain checks cannot prove that an attacker did not remove the end of the chain.

Known official market interruptions must be recorded before affected work in a new JSON file under `artifacts/market_notices/`:

```json
{
  "acquired_at_utc": "<actual timezone-aware acquisition timestamp>",
  "official_source_url": "<NYSE/ICE official announcement URL>",
  "affected_sessions": ["<YYYY-MM-DD>"],
  "reason": "<announced closure or changed hours; retain the source separately>"
}
```

The collector copies a relevant notice into failed-attempt evidence and refuses affected work. It also refuses disagreement with the frozen 2027 schedule. Reviewed calendar amendments are not applied automatically; preserve official evidence and version any amendment before resuming affected formal collection. The software is not an automatic exchange-announcement or actual-close verification service.

## External timestamped retention

The optional adapter uses a private, existing **S3 general-purpose bucket with versioning Enabled**. Install AWS CLI v2 separately and configure a restricted profile using your chosen credential mechanism, such as AWS IAM Identity Center. Credentials, access keys and tokens must not be placed in TOML, source, command examples or Git. No credentials were inspected or invented here.

After review, change only the retention section:

```toml
[retention]
mode = "s3"
bucket = "YOUR-EXISTING-PRIVATE-VERSIONED-BUCKET"
prefix = "spy-volatility/evidence"
region = "YOUR-REGION"
profile = "spy-research"
```

Required permissions include bucket-versioning reads, writes limited to that prefix, and object/version reads for checksum verification. Deny object-version deletion to the collector; consider a separately administered S3 Object Lock retention policy. Customer-managed KMS encryption may require additional KMS permissions for checksum reads. Keep all public access blocked. Bucket creation, IAM, Object Lock and credential provisioning are deliberately not performed by this code.

```powershell
aws --version
aws sso login --profile spy-research
aws s3api get-bucket-versioning --bucket YOUR-BUCKET --profile spy-research
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations retain
```

Each upload uses an immutable event-hash key and conditional creation. It verifies the archive checksum, byte size, version ID and server `LastModified` using a version-specific HEAD request. The record plus journal prefix, supporting files and frozen protocol identification are archived. Interrupted local packages remain preserved; retries produce deterministic equivalent packages. Remote time proves that version existed by the server's timestamp, not when Yahoo published its data. A failed upload is logged and retried; late retention is never silently promoted into timely evidence. Full historical prospective validity is not claimed automatically.

The APIs and conditional-write/version semantics follow [AWS PutObject documentation](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html) and [versioned HEAD/checksum documentation](https://docs.aws.amazon.com/cli/latest/reference/s3api/head-object.html). No live S3 connection has been verified in this environment.

## Scheduling choice and proposal

Use **Windows Task Scheduler on this existing machine**, polling every five minutes throughout the day. The Python calendar decides whether a forecast or target is due. This accommodates early closes, holidays and daylight saving without a fixed UTC-close assumption. A polling interval is not a guarantee: the actual recorded issue time still determines timeliness.

| Option | Assessment |
| --- | --- |
| Windows Task Scheduler | Recommended initial deployment; uses the installed environment and local persistent evidence. Requires a reliable machine and separate remote retention. |
| GitHub Actions cron | Suitable for CI or secondary checks; scheduled jobs may be delayed or dropped and runners are ephemeral. Requires explicit durable evidence storage and cannot guarantee the 120-minute deadline. |
| Persistent server/service | Better uptime if this computer cannot stay available; requires provisioning, supervision and credential management. |
| Cloud scheduled worker | Feasible later with a durable external store, locking and operational monitoring; no cloud deployment is currently configured. |

GitHub documents [scheduled-event delays and dropped jobs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). The Windows proposal follows Microsoft's [task settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset) and [XML schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema).

Prepare an XML proposal without contacting Task Scheduler's registration service:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File scripts/prepare_forecast_task.ps1 -OutputPath artifacts/scheduler_review/SPY-Volatility.xml
```

This writes a **disabled, unregistered** definition and refuses to overwrite an existing proposal. Review the absolute paths, user SID, start boundary, five-minute repetition, `IgnoreNew`, `StartWhenAvailable`, wake request, hidden window and 15-minute execution limit. The current-account interactive logon mode uses no stored password. `RemoteSigned` applies only to the launched PowerShell process; it does not change machine policy and cannot override organizational policy.

**Only after review and explicit activation**, register the disabled proposal, then enable it:

```powershell
$taskName = 'SPY Volatility Collection'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Task already exists; inspect it before changing it.' }
$taskXml = Get-Content -LiteralPath artifacts/scheduler_review/SPY-Volatility.xml -Raw
Register-ScheduledTask -TaskName $taskName -Xml $taskXml
# Separate activation step, after configuration and evidence checks:
Enable-ScheduledTask -TaskName $taskName

# Monitor or pause
Get-ScheduledTaskInfo -TaskName $taskName
Disable-ScheduledTask -TaskName $taskName
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations status
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations verify
```

These activation commands have **not** been executed. The task action calls `scripts/run_forecast_cycle.ps1`, which retains a unique invocation log under `artifacts/operation_invocations/`. Review nonzero exits, missing forecasts/labels, failed remote retention, storage capacity and clock synchronization daily. No email or messaging alert integration is configured.

The computer must remain **powered on, logged in and internet-connected**. A locked screen is compatible with the chosen interactive token; a signed-out user or shut-down computer cannot run it. Wake timers require OS/hardware support and may not wake a laptop reliably. Keep it on AC power; the proposal allows battery operation but does not override lid, hibernation or organization policies. Downtime can lose the 120-minute window; the next tick records that failure instead of backdating it. If these requirements cannot be met, use a supervised always-on host before the formal study.

## Test and demonstrate safely

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations demo
.\.venv\Scripts\python.exe -m pytest -q --basetemp artifacts/t_final -p no:cacheprovider
```

Choose a **new, short** temporary path on each test invocation; long Windows paths can exceed legacy path limits. The demonstration uses deterministic artificial prices, simulated time and a separate `artifacts/automation_demos/<id>/` journal. It performs no network acquisition or external upload and never becomes a real forecast. It covers forecast creation, duplicate skipping, premature-target refusal, a matured label, error calculation, a revised outcome and offline replay. Production commands have no simulated-time option.

The existing November 11 pilot remains replayable with its original command. Operational tests use no-fit and no-reserved-response guards. Local tests do not establish remote availability, exchange announcement monitoring, power/wake reliability or an external timestamp service connection; those require deployment review.

## Verified state on November 19, 2026

The final complete suite passed **296 tests, with zero failures, errors or skips**, in 171.05 seconds. The seven focused timestamp-resolution and invalid-input checks also passed. The complete run's command was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp artifacts/t_end4 -p no:cacheprovider --junitxml=artifacts/automation_final_tests_v2.xml
```

Preserve that run's files; choose a new short `--basetemp` and report filename when repeating it. Its [saved log](../artifacts/automation_final_tests_v2.log), [JUnit report](../artifacts/automation_final_tests_v2.xml) and [final verification record](../artifacts/automation_verification_2026-11-19.json) document the result.

| Area | Observed result |
| --- | --- |
| Scientific preservation | All 36 prepared artifact hashes passed; original pilot record, pilot replay and historical raw-price hash unchanged. Existing research modules and frozen protocol were not edited. |
| Synthetic demonstration | `artifacts/automation_demos/a48f742518c44a6dba9aa347461f8df8/demo_summary.json`; three artificial acquisitions and nine verified journal events, with duplicate, premature-outcome and revision checks. |
| Real manual pilot | Imported the unchanged November 11 forecast; acquired its six-price matured target at `2026-11-19T08:08:53.546912+00:00`; observed SD `0.006995661396605764`. Eleven live journal events replayed, including two preserved failed attempts. No new live forecast was issued. |
| Independent outcome checks | Scalar returns/mean/sample SD and the existing research rolling-target expression agree within `rtol=1e-9`, `atol=1e-12`; pilot errors and descriptive metrics replay. |
| Local configuration | Prepared hashes and local store configured; one manual pilot outcome recorded. No recurring collection started. |
| Scheduler | `artifacts/scheduler_review/SPY-Volatility-review-2.xml` validates against the published Microsoft schema. It is disabled and has not been registered or run. |
| External retention | Adapter tests passed using mocked responses. AWS CLI is unavailable, the bucket/profile are not configured, and zero real external receipts exist. |
| Formal 2027 study | No forecasts or outcomes collected; issuance and scoring gates tested using artificial data. The model remains prepared, not live. |

The first live target download was blocked by the restricted network. A network-enabled retry exposed a seconds-versus-microseconds datetime-index mismatch in the new archive comparison. The collector now compares indexes at a common precision and requires exact price equality. A fresh successful retry and a focused regression test verified the correction; both failed attempt directories remain intact. This change does not modify the historical downloader or scientific formulas.

Replay and inspect the saved manual result without another market download:

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations verify
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations status
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations metrics --study manual_pilot_2026
```

`metrics` appends a descriptive summary; `verify` recalculates the saved evidence. Ordinary repeated `outcomes --origin 2026-11-11` now skips the existing label. Use an explicit revision reason only when intentionally investigating a new vintage. The [research progress summary](results/automation_progress.md) reports the separate pilot outcome and its limitations.
