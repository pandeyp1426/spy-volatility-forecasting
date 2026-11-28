[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$WorkerRoot,
    [Parameter(Mandatory)][string]$EvidenceCheckout,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$GitHubCLI
)
$ErrorActionPreference = 'Stop'
$logDirectory = Join-Path $WorkerRoot 'output\pilot_invocations'
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
$invocationId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '_' + [Guid]::NewGuid().ToString('N')
$logPath = Join-Path $logDirectory ($invocationId + '.log')
$env:PYTHONPATH = Join-Path $WorkerRoot 'src'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GH_PROMPT_DISABLED = '1'
& $Python -m spy_volatility.workflows.pilot_service --root $WorkerRoot --state $EvidenceCheckout --gh $GitHubCLI *> $logPath
exit $LASTEXITCODE
