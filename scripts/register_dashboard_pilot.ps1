# Register the remaining eligible 2026 pilot closes for the current Windows user.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$taskName = 'SPY Volatility Lab - 2026 after-close pilots'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonWindowless = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$configPath = Join-Path $projectRoot 'configs\operations.toml'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) { throw "Task already exists. Inspect it with Get-ScheduledTask -TaskName '$taskName'." }
$schedule = & $pythonPath -m spy_volatility.workflows.dashboard_pilot schedule
if ($LASTEXITCODE -ne 0) { throw 'Could not construct the NYSE schedule.' }
$triggers = @(foreach ($instant in ($schedule | ConvertFrom-Json)) {
    $localTime = [DateTimeOffset]::Parse($instant).LocalDateTime
    New-ScheduledTaskTrigger -Once -At $localTime -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Minutes 110)
})
if ($triggers.Count -eq 0) { throw 'No remaining 2026 pilot windows.' }
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('-m spy_volatility.workflows.dashboard_pilot tick --config "' + $configPath + '"') -WorkingDirectory $projectRoot
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Verified, local 2026 pilots after eligible NYSE closes. Requires a logged-in research user.'
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime,LastRunTime,LastTaskResult
