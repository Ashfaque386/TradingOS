# Wrapper for scripts/backup_data_lake.py, matching run_daily_shadow_mode.ps1's pattern -- no
# Windows Scheduled Task is registered for this yet (that's a separate, explicit decision the
# same way the Shadow Mode one was). Run manually for now:
#   powershell -File scripts\windows\backup_data_lake.ps1
# or register a nightly Scheduled Task pointed at this script later, once wanted.
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
