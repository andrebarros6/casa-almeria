# Daily run of the browser-based sources (Fotocasa) on this PC.
# Registered with Windows Task Scheduler. See README "PC sources".
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "local\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("run-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

# Random 0-20 min delay so the visit time isn't identical every day.
Start-Sleep -Seconds (Get-Random -Minimum 0 -Maximum 1200)

& "$root\.venv\Scripts\python.exe" -m scraper.run --sources local *>> $log
exit $LASTEXITCODE
