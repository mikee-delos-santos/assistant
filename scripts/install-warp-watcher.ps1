# Installs the Brice Warp launch watcher as a logon scheduled task.
#
# The task runs in Mark's interactive session (LogonType Interactive) so the watcher can
# open a visible Warp window. Run this once. If Register-ScheduledTask reports access
# denied, re-run this script from an elevated PowerShell (Run as administrator).

$ErrorActionPreference = 'Stop'

$watcher = Join-Path $PSScriptRoot 'warp-launch-watcher.ps1'
if (-not (Test-Path $watcher)) { throw "watcher script not found: $watcher" }

$TaskName = 'BriceWarpLaunchWatcher'
$psExe = (Get-Command powershell.exe).Source

$action = New-ScheduledTaskAction -Execute $psExe `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "Registered scheduled task '$TaskName' (runs at logon)."

Start-ScheduledTask -TaskName $TaskName
Write-Output "Started it now (no need to log off)."
Write-Output "Log file: $env:LOCALAPPDATA\brice-launch\watcher.log"
