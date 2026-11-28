# Run after PILOT_WRITER=windows and after all hosted writer jobs have ended.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$WorkerRoot,
    [Parameter(Mandatory)][string]$EvidenceCheckout,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$GitHubCLI,
    [string]$TaskName = 'SPY Volatility Lab - persistent pilot'
)
$ErrorActionPreference = 'Stop'
foreach ($path in $WorkerRoot,$EvidenceCheckout,$Python,$GitHubCLI) {
    if (!(Test-Path -LiteralPath $path)) { throw "Required path unavailable: $path" }
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'Task exists; inspect before changing it.' }
$runner = Join-Path $WorkerRoot 'scripts\run_pilot_service.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "' + $runner + '" -WorkerRoot "' + $WorkerRoot + '" -EvidenceCheckout "' + $EvidenceCheckout + '" -Python "' + $Python + '" -GitHubCLI "' + $GitHubCLI + '"'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $WorkerRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$trigger.EndBoundary = '2027-01-02T00:00:00-06:00'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Select-Object TaskName,State
