# One invocation only. This script does not register or enable a scheduled task.
[CmdletBinding()]
param(
    [string]$Config = '',
    [ValidateSet('cycle','formal-cycle')][string]$Action = 'cycle'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (!$Config) { $Config = Join-Path $projectRoot 'configs\operations.toml' }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$logDirectory = Join-Path $projectRoot 'artifacts\operation_invocations'
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
$invocationId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '_' + [Guid]::NewGuid().ToString('N')
$logPath = Join-Path $logDirectory ($invocationId + '.log')
$exitStatus = 1
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m spy_volatility.workflows.operations $Action --config $configPath *> $logPath
    $exitStatus = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitStatus
