# One scheduled read-only readiness check. No collection, market data or upload.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$started = [DateTime]::UtcNow.ToString('o')
$checks = & (Join-Path $root '.venv\Scripts\python.exe') -m spy_volatility.workflows.operations check --config (Join-Path $root 'configs\formal_2027.toml')
$exitStatus = $LASTEXITCODE
@{ started_at_utc=$started; completed_at_utc=[DateTime]::UtcNow.ToString('o'); exit_code=$exitStatus; checks=($checks | ConvertFrom-Json) } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
exit $exitStatus
