#Requires -Version 5.1
# Install / uninstall the weekly release-watch on Windows.
#
# Registers a Task Scheduler entry that runs
#   python -m update.release_watch
# every Monday at the chosen time, filing candidate YAML drafts under
# update/candidates/<YYYY-MM>/ when GitHub upstreams release a new
# version.
#
# Usage:
#   .\scripts\install-schedule-weekly.ps1
#   .\scripts\install-schedule-weekly.ps1 -RunTime 08:00 -DayOfWeek Monday
#   .\scripts\install-schedule-weekly.ps1 -Uninstall

[CmdletBinding()]
param(
    [string]$RunTime   = "08:00",
    [string]$DayOfWeek = "Monday",
    [string]$TaskName  = "bioflow-weekly-release-watch",
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
    -Argument "-m update.release_watch" `
    -WorkingDirectory $repoRoot

$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $RunTime
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "bioflow weekly GitHub release watch (T2 cadence)" `
    -Force | Out-Null

Write-Host "✓ Registered '$TaskName' to run every $DayOfWeek at $RunTime."
Write-Host "  Candidates → $repoRoot\update\candidates\<YYYY-MM>\"
