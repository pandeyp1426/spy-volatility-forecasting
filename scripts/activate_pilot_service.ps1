# Activate only the reviewed, merged source. Never permits two evidence writers.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EvidenceCheckout,
    [Parameter(Mandatory)][string]$WorkerRoot,
    [string]$GitHubCLI = 'gh'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if ($GitHubCLI -eq 'gh' -and !(Get-Command gh -ErrorAction SilentlyContinue)) {
    $GitHubCLI = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\gh.exe'
}
function Checked($exe, [string[]]$arguments) {
    $value = & $exe @arguments
    if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)" }
    return $value
}
$public = 'pandeyp1426/spy-volatility-forecasting'
$state = (Resolve-Path -LiteralPath $EvidenceCheckout).Path
$worker = [System.IO.Path]::GetFullPath($WorkerRoot)
$python = Join-Path $root '.venv\Scripts\python.exe'
$main = Checked $GitHubCLI @('api', "repos/$public/commits/main", '--jq', '.sha')
if ((Checked git @('-C',$root,'rev-parse','HEAD')) -ne $main -or
    (Checked git @('-C',$root,'status','--porcelain'))) {
    throw 'Switch to clean, updated main after the collector PR is merged before activation.'
}
if ((Checked $GitHubCLI @('api','repos/pandeyp1426/spy-volatility-pilot-evidence','--jq','.private')) -ne 'true') {
    throw 'Evidence repository is not private.'
}
if (!(Test-Path -LiteralPath $worker)) {
    Checked git @('clone','--no-hardlinks','--no-checkout',$root,$worker)
    Checked git @('-C',$worker,'checkout','--detach',$main)
    foreach ($name in 'artifacts','data') {
        New-Item -ItemType Junction -Path (Join-Path $worker $name) -Target (Join-Path $state $name) | Out-Null
    }
} elseif ((Checked git @('-C',$worker,'rev-parse','HEAD')) -ne $main) {
    throw 'Existing worker uses different source. Preserve it and choose a new WorkerRoot.'
}
# Stop future hosted writes first. If an old job remains active, leave local
# collection disabled and rerun after it finishes; never race its checkpoint.
Checked $GitHubCLI @('variable','set','PILOT_WRITER','--body','windows','--repo',$public)
$runs = Checked $GitHubCLI @('run','list','--repo',$public,'--workflow','dashboard.yml','--branch','main','--limit','100','--json','status') | ConvertFrom-Json
if ($runs | Where-Object { $_.status -ne 'completed' }) { throw 'A hosted run is active. Wait until it finishes, then rerun this activation.' }
$old = Get-ScheduledTask -TaskName 'SPY Volatility Lab - 2026 after-close pilots' -ErrorAction SilentlyContinue
if ($old.State -eq 'Running') { throw 'The original local task is still running.' }
if ($old) { Disable-ScheduledTask -InputObject $old | Out-Null }
$env:PYTHONPATH = Join-Path $worker 'src'
Push-Location $worker
try {
    Checked $python @('-m','spy_volatility.workflows.hosted_pilot','verify')
} finally { Pop-Location }
& (Join-Path $worker 'scripts\register_pilot_service.ps1') -WorkerRoot $worker -EvidenceCheckout $state -Python $python -GitHubCLI $GitHubCLI
Write-Output 'Windows pilot writer registered. Keep this host powered, signed in, and connected; inspect output/pilot_invocations and Pages deployment separately.'
