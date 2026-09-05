# DEPRECATED (2026-09-05): the "TradingOS Daily Shadow Mode" Windows Scheduled Task this wrapper
# was registered for has been unregistered -- REL-081 moved this job to the in-app APScheduler
# (src/agents/scheduler.py, SHADOW_MODE_DAILY_CYCLE_JOB_ID), which is now the sole live path.
# This script is kept only as a manual/CLI fallback:
#   powershell -File scripts\windows\run_daily_shadow_mode.ps1
#
# Just runs scripts/run_daily_shadow_mode.py inside the real running container and appends
# timestamped output to a log file, since Scheduled Tasks captured no output by default.
#
# Assumes tradingos-app is already running (docker compose up) and today's broker tokens have
# already been refreshed -- if either isn't true, the underlying script reports that honestly
# (a "not configured" or a real broker error) rather than silently doing nothing.

$logDir = "D:\AI Trading Agent\TradingOS\logs"
$logFile = Join-Path $logDir "shadow_mode_daily.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
# `*>>` redirection writes UTF-16, which Get-Content's default UTF-8 read then garbles into a
# space between every character -- capturing to a string and appending with -Encoding utf8
# avoids that (confirmed by reproducing the garbled output on the first real run of this task).
$output = & "C:\Program Files\Docker\Docker\resources\bin\docker.exe" exec tradingos-app python scripts/run_daily_shadow_mode.py 2>&1 | Out-String

Add-Content -Path $logFile -Value "=== $timestamp ===" -Encoding utf8
Add-Content -Path $logFile -Value $output -Encoding utf8
