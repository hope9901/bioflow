# Install a monthly Windows scheduled task for `bioflow update auto`.
#
# Run this script ONCE in an elevated PowerShell.  It registers a task
# named "bioflow-monthly-update" that fires on the 1st of every month
# at 02:30 local time and runs `bioflow update auto` against the
# repository at $RepoPath.
#
# Why scheduled here and not as a bioflow daemon?  The bioflow design
# explicitly avoids long-running services (Part 5 of the design doc).
# Windows Task Scheduler is the right OS primitive — battle-tested,
# survives reboots, logs visible in Event Viewer.
#
# Usage:
#   .\install-schedule-windows.ps1                    # uses defaults
#   .\install-schedule-windows.ps1 -RepoPath C:\bio -AutoApprove
#   .\install-schedule-windows.ps1 -Uninstall         # remove the task

param(
    [string]$RepoPath = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$PythonExe = (Get-Command python).Path,
    [string]$TaskName = "bioflow-monthly-update",
    [string]$RunDay = "1",          # 1st of every month
    [string]$RunTime = "02:30",     # 2:30 AM
    [switch]$AutoApprove,           # also approve passing candidates
    [switch]$Real,                  # use real DockerBackend (slow)
    [switch]$GitPush,               # MAINTAINER ONLY: commit + push to origin
    [string]$GitRemote = "origin",
    [string]$GitBranch = "",
    [switch]$Uninstall
)

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
    } else {
        Write-Host "No task named '$TaskName' is registered." -ForegroundColor Yellow
    }
    exit 0
}

if (-not (Test-Path "$RepoPath\bioflow\__init__.py")) {
    Write-Error "RepoPath '$RepoPath' doesn't look like a bioflow checkout."
    exit 1
}

# Build the command we want the task to run
$cmdArgs = @("-m", "bioflow.cli", "update", "auto")
if ($AutoApprove) { $cmdArgs += "--auto-approve" }
if ($Real)        { $cmdArgs += "--real" }
if ($GitPush) {
    $cmdArgs += "--git-push"
    $cmdArgs += @("--git-remote", $GitRemote)
    if ($GitBranch) { $cmdArgs += @("--git-branch", $GitBranch) }
}
$cmdArgs += @("--report", "$RepoPath\update\last_run.json")

# Wrap as a single command line for schtasks
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument ($cmdArgs -join ' ') `
    -WorkingDirectory $RepoPath

# Monthly trigger — 1st of every month at $RunTime
$trigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday `
    -At $RunTime `
    -WeeksInterval 4   # roughly monthly; Task Scheduler doesn't have
                       # a true "1st of month" trigger via PowerShell,
                       # so we use 4-week interval.

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Monthly bioflow update auto run — benchmarks new candidate tools" `
    | Out-Null

Write-Host ""
Write-Host "✓ Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "  Runs every 4 weeks at $RunTime"
Write-Host "  Command: $PythonExe $($cmdArgs -join ' ')"
Write-Host "  Auto-approve: $($AutoApprove.IsPresent)"
Write-Host "  Real Docker:  $($Real.IsPresent)"
Write-Host "  Git push:     $($GitPush.IsPresent) (maintainer-only)"
Write-Host ""
Write-Host "Manual trigger:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Inspect last run:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  Get-Content $RepoPath\update\last_run.json"
