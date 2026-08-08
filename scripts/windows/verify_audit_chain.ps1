# Wrapper for scripts/verify_audit_chain.py, matching archive_audit_log.ps1's pattern.
#
# REL-031 (SEC-040): registered as the "TradingOS Audit Chain Verification" Windows Scheduled
# Task. Can still be run manually for an on-demand check:
#   powershell -File scripts\windows\verify_audit_chain.ps1
#
# Assumes tradingos-app is already running (docker compose up). Scheduled Tasks capture no
# output by default, so this appends timestamped output to a log file, same as the archive/backup/
# Shadow Mode wrappers -- and for the same reason, captures via -Encoding utf8 rather than `*>>`
# (which writes UTF-16 and garbles on a plain UTF-8 read).

$logDir = "D:\AI Trading Agent\TradingOS\logs"
$logFile = Join-Path $logDir "verify_audit_chain.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
$output = & "C:\Program Files\Docker\Docker\resources\bin\docker.exe" exec tradingos-app python scripts/verify_audit_chain.py 2>&1 | Out-String
$exitCode = $LASTEXITCODE

Add-Content -Path $logFile -Value "=== $timestamp (exit code $exitCode) ===" -Encoding utf8
Add-Content -Path $logFile -Value $output -Encoding utf8

exit $exitCode
