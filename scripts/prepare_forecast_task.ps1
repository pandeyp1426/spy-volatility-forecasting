# Build an XML proposal only. No task registration, enabling or execution.
[CmdletBinding()]
param([string]$OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'artifacts\scheduler_review\SPY-Volatility.xml'))
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runner = Join-Path $PSScriptRoot 'run_forecast_cycle.ps1'
$configPath = Join-Path $projectRoot 'configs\operations.toml'
$destination = [System.IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $destination) {
    throw 'The proposal already exists. Choose a new OutputPath; prior proposals are preserved.'
}
$accountSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "' + $runner + '" -Config "' + $configPath + '"'
# Construct a file directly: even creating CIM task objects can require access
# to Task Scheduler's service. This preparation never contacts that service.
$escapedCommand = [System.Security.SecurityElement]::Escape("$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe")
$escapedArguments = [System.Security.SecurityElement]::Escape($arguments)
$escapedRoot = [System.Security.SecurityElement]::Escape($projectRoot)
$boundary = [DateTime]::UtcNow.AddMinutes(5).ToString('yyyy-MM-ddTHH:mm:ssZ')
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>SPY collection proposal. Local timestamp evidence only; review before enabling.</Description></RegistrationInfo>
  <Triggers><TimeTrigger><Enabled>true</Enabled><StartBoundary>$boundary</StartBoundary><Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$accountSid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>false</Enabled><Hidden>true</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT15M</ExecutionTimeLimit><Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>$escapedCommand</Command><Arguments>$escapedArguments</Arguments><WorkingDirectory>$escapedRoot</WorkingDirectory></Exec></Actions>
</Task>
"@
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($destination)) | Out-Null
$stream = [System.IO.File]::Open($destination, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
try {
    $preamble = [System.Text.Encoding]::Unicode.GetPreamble()
    $stream.Write($preamble, 0, $preamble.Length)
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($xml)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush($true)
}
finally {
    $stream.Dispose()
}
Write-Output "Saved disabled task proposal: $destination"
Write-Output 'No task was registered, enabled, or run.'
