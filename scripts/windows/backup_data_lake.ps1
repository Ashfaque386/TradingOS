# DEPRECATED (2026-09-05): the "TradingOS Nightly Backup" Windows Scheduled Task this wrapper
# was registered for (REL-015 E15.5, GLH-13) has been unregistered -- REL-081 moved this job to
# the in-app APScheduler (src/agents/scheduler.py, DATA_LAKE_BACKUP_JOB_ID, 23:00 IST), which is
# now the sole live path. This script is kept only as a manual/CLI fallback:
#   powershell -File scripts\windows\backup_data_lake.ps1
#
# Assumes tradingos-app is already running (docker compose up). Scheduled Tasks capture no
# output by default, so this appends timestamped output to a log file, same as the Shadow Mode
# wrapper -- and for the same reason, captures via -Encoding utf8 rather than `*>>` (which
# writes UTF-16 and garbles on a plain UTF-8 read).

$logDir = "D:\AI Trading Agent\TradingOS\logs"
$logFile = Join-Path $logDir "backup_data_lake.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
$output = & "C:\Program Files\Docker\Docker\resources\bin\docker.exe" exec tradingos-app python scripts/backup_data_lake.py 2>&1 | Out-String
$exitCode = $LASTEXITCODE

Add-Content -Path $logFile -Value "=== $timestamp (exit code $exitCode) ===" -Encoding utf8
Add-Content -Path $logFile -Value $output -Encoding utf8

exit $exitCode
