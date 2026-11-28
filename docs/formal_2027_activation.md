# Separate formal collector activation

Prepared on November 27, 2026; not activated. The frozen protocol and model are unchanged. The separate configuration is `configs/formal_2027.toml`, with `study="formal_2027"` and store `artifacts/formal_operations_2027`. The hosted pilot's private Git checkpoint is not formal S3 retention.

Use an always-available Windows host with the pinned Python 3.12.14 distribution and `requirements-lock.txt`. Run `operations formal-cycle` every five minutes using Windows Task Scheduler. The calendar controls issuance strictly after close through close + 120 minutes, including early closes and daylight saving. It records missed origins and collects labels strictly after the fifth target close even outside the issuance window. It never computes formal errors. January 10, 2028 at 00:00 America/Chicago remains the scoring release boundary. There are 246 eligible origins, January 4 through December 23, 2027.

## Required external setup

An AWS administrator must supply a private general-purpose S3 bucket, region and restricted runtime identity. Enable versioning, all four Block Public Access flags, and a nonpublic bucket policy. Preserve versions; deny the runtime identity object/version deletion and bucket policy/versioning changes. Object Lock should be administered independently if required. Retain backups of the complete working journal and frozen bundle as well as the per-event S3 packages.

The collector needs these permissions, restricted to the named bucket and prefix:

| Resource | Allowed actions |
| --- | --- |
| Bucket ARN | `s3:GetBucketVersioning`, `s3:GetBucketPublicAccessBlock`, `s3:GetBucketPolicyStatus` |
| `BUCKET/spy-volatility/formal-2027/*` | `s3:PutObject`, `s3:GetObject`, `s3:GetObjectVersion` |

Explicitly deny `s3:DeleteObject`, `s3:DeleteObjectVersion` on that prefix and `s3:PutBucketVersioning`, `s3:PutBucketPolicy`, `s3:DeleteBucketPolicy`, `s3:PutBucketPublicAccessBlock` on the bucket for the collector. Review all attached policies and permission boundaries, not just this allow list. Customer-managed KMS keys can require additional restricted KMS permissions. Prefer renewable short-lived credentials suitable for unattended operation; an expired interactive SSO login is not unattended readiness. Never save credentials in TOML or Git.

Install AWS CLI v2, authenticate using the approved identity, and copy `configs/formal_2027.toml` to ignored `configs/formal_2027.local.toml`. Set only the retention values (`mode="s3"`, real bucket, region and optional profile). Keep the dedicated store and scientific fields unchanged. The local file is configuration, not a place for secret values.

```powershell
.\.venv\Scripts\python.exe -m spy_volatility.workflows.operations check --config configs/formal_2027.local.toml
.\.venv\Scripts\python.exe -m spy_volatility.workflows.retention_probe --config configs/formal_2027.local.toml
```

The probe checks versioning and privacy, writes an isolated record under `spy-volatility/formal-2027/preflight/`, verifies its SHA-256/size/version/server LastModified, and repeats conditional creation to check that the original version is reused. It preserves its local package and receipts under `artifacts/retention_probes/`. It never creates a forecast or writes the formal journal. Its receipt establishes only the test object's timestamp. Administrator review of effective credential scope remains separate.

## Register only after a genuine successful receipt

Prepare a new disabled proposal using the final paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File scripts/prepare_forecast_task.ps1 -Config configs/formal_2027.local.toml -Action formal-cycle -OutputPath artifacts/scheduler_review/formal-2027-approved.xml
```

Review the proposal, the actual receipt, host availability and IAM scope. Then explicitly activate the formal collector:

```powershell
$formalTask = 'SPY Volatility - formal 2027'
if (Get-ScheduledTask -TaskName $formalTask -ErrorAction SilentlyContinue) { throw 'Task already exists.' }
Register-ScheduledTask -TaskName $formalTask -Xml (Get-Content artifacts/scheduler_review/formal-2027-approved.xml -Raw)
Enable-ScheduledTask -TaskName $formalTask
```

The proposed interactive logon requires this user to remain signed in; a locked screen is acceptable. Power, network, credential renewal, clock synchronization and wake behavior require monitoring. The one-time local scheduler probe cannot certify unattended uptime for a year. If this host cannot remain available, provision a supervised Windows host and repeat runtime, scheduler and receipt validation there before activation.

Inspect `artifacts/operation_invocations/`, the journal's failed/missing events and retention receipts daily. Failures return nonzero. No comparative summaries are released before the embargo. The first formal live test is January 4, 2027, after 3 p.m. and by 5 p.m. Central; its five targets end January 11. Late forecasts, labels and S3 receipts retain their actual times and cannot be promoted into primary observations.

AWS semantics: [conditional PutObject](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html), [version-specific HEAD/checksum](https://docs.aws.amazon.com/cli/latest/reference/s3api/head-object.html), [public-access block](https://docs.aws.amazon.com/cli/latest/reference/s3api/get-public-access-block.html).
