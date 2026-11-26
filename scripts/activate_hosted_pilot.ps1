# Run once on the research PC after the dashboard workflow is merged to main.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EvidenceCheckout,
    [string]$GitHubCLI = 'gh'
)
$ErrorActionPreference = 'Stop'
$public = 'pandeyp1426/spy-volatility-forecasting'
$private = 'pandeyp1426/spy-volatility-pilot-evidence'
$taskName = 'SPY Volatility Lab - 2026 after-close pilots'
$state = (Resolve-Path -LiteralPath $EvidenceCheckout).Path
$root = Split-Path $PSScriptRoot -Parent
function Checked($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)." }
}
Push-Location $root
try {
    $workflow = '.github/workflows/dashboard.yml'
    $merged = Checked $GitHubCLI @('api', "repos/$public/contents/${workflow}?ref=main", '--jq', '.sha')
    if ($merged -ne (Checked git @('hash-object', "--path=$workflow", $workflow))) {
        throw 'Merge the reviewed dashboard workflow before transferring collection.'
    }
    if ((Checked $GitHubCLI @('api', "repos/$private", '--jq', '.visibility')) -ne 'private') {
        throw 'Expected a private evidence repository.'
    }
    $stateGit = @('-C', $state)
    if ((Checked git ($stateGit + @('remote','get-url','origin'))) -ne "https://github.com/$private.git" -or
        (Checked git ($stateGit + @('branch','--show-current'))) -ne 'main' -or
        (Checked git ($stateGit + @('status','--porcelain')))) {
        throw 'Use a clean main checkout of the private evidence repository.'
    }
    $variables = Checked $GitHubCLI @('variable','list','--repo',$public,'--json','name,value') | ConvertFrom-Json
    if ($variables | Where-Object { $_.name -eq 'PILOT_HOSTED' -and $_.value -eq 'true' }) {
        throw 'Hosted collection is already enabled.'
    }
    Checked git ($stateGit + @('pull','--ff-only'))
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.State -eq 'Running') { throw 'The local collector is running. Wait for its attempt to finish.' }
    $wasEnabled = $task.State -ne 'Disabled'
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    try {
        Checked '.\.venv\Scripts\python.exe' @('-m','spy_volatility.workflows.hosted_pilot','handoff',$state)
        Checked git ($stateGit + @('add','--','artifacts','data'))
        if (Checked git ($stateGit + @('diff','--cached','--name-only'))) {
            Checked git ($stateGit + @('commit','--quiet','-m','Preserve final local pilot evidence before hosted handoff'))
        }
        Checked git ($stateGit + @('push','origin','HEAD:main'))
    } catch {
        if ($wasEnabled) { Enable-ScheduledTask -TaskName $taskName | Out-Null }
        throw
    }
    try {
        Checked $GitHubCLI @('variable','set','PILOT_HOSTED','--body','true','--repo',$public)
    } catch {
        # A lost response can follow a successful write. Confirm the state before resuming locally.
        $variables = Checked $GitHubCLI @('variable','list','--repo',$public,'--json','name,value') | ConvertFrom-Json
        if ($wasEnabled -and -not ($variables | Where-Object { $_.name -eq 'PILOT_HOSTED' -and $_.value -eq 'true' })) {
            Enable-ScheduledTask -TaskName $taskName | Out-Null
        }
        throw
    }
    Checked $GitHubCLI @('workflow','run','dashboard.yml','--ref','main','--repo',$public)
    Write-Output "Hosted collection enabled. Follow the run at https://github.com/$public/actions/workflows/dashboard.yml"
} finally {
    Pop-Location
}
