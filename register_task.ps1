# Registers a daily scheduled task that runs export_granola.py as the current user.
# Usage:  .\register_task.ps1 [-At '11:00PM'] [-OutDir 'C:\path\to\notes'] [-TaskName 'Granola Daily Export']
param(
    [string]$At = '11:00PM',
    [string]$OutDir = '',
    [string]$TaskName = 'Granola Daily Export'
)
$ErrorActionPreference = 'Stop'
$py = (Get-Command python -ErrorAction Stop).Source
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
$script = Join-Path $PSScriptRoot 'export_granola.py'
$arg = "`"$script`""
if ($OutDir) { $arg += " --out `"$OutDir`"" }

$action   = New-ScheduledTaskAction -Execute $pyw -Argument $arg -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Exports Granola notes + transcripts to markdown' -Force | Out-Null
Write-Host "Registered '$TaskName' (daily $At) using $pyw"
if ($OutDir) { Write-Host "Output folder: $OutDir" }
