#Requires -Version 5.1
# Install / uninstall the daily registry freshness check on Windows.
#
# Registers a Task Scheduler entry that runs
#   python -m update.freshness_check
# every day at the chosen time.  The report lands at
#   update/notifications/freshness-<YYYY-MM-DD>.md
#
# Usage (in an elevated PowerShell):
#   .\scripts\install-schedule-daily.ps1
#   .\scripts\install-schedule-daily.ps1 -RunTime 07:30
#   .\scripts\install-schedule-daily.ps1 -Uninstall

[CmdletBinding()]
param(
    [string]$RunTime  = "06:00",
    [string]$TaskName = "bioflow-daily-freshness",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "✓ Removed task '$TaskName'."
    } else {
        Write-Host "Task '$TaskName' was not registered."
    }
    return
}

$python = (Get-Command python).Source
$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m update.freshness_check" `
    -WorkingDirectory $repoRoot

$trigger  = New-ScheduledTaskTrigger -Daily -At $RunTime
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "bioflow daily registry freshness check (T1 cadence)" `
    -Force | Out-Null

Write-Host "✓ Registered '$TaskName' to run daily at $RunTime."
Write-Host "  Reports → $repoRoot\update\notifications\"
