# ==========================================================================
# Indeed -> Neon: the PUSH half of the desktop's two-button split.
#
#   Run Indeed Scrape  -> scripts/run_indeed_scrape.ps1  (scrapes into the
#                         LOCAL Postgres)
#   Indeed to Neon     -> this script: copies what the local scrape already
#                         stored into Neon. No browser, no scraping, no
#                         queue claiming -- one click, idempotent.
#
# The actual work is scripts/push_indeed_to_neon.py; this wrapper only
# resolves the two DSNs, runs it with the repo venv, and holds the window
# open so the report can be read.
# ==========================================================================
$ErrorActionPreference = 'Stop'
$Repo = 'D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel'
Set-Location $Repo

# Source = local Postgres, target = Neon (process-scoped env; the script
# also falls back to .env itself, this just fails fast with a clear message).
$local = Select-String -Path '.env' -Pattern '^LOCAL_DATABASE_URL=(.*)$'
if (-not $local) { throw 'LOCAL_DATABASE_URL not found in .env' }
$neon = Select-String -Path '.env' -Pattern '^NEON_DATABASE_URL=(.*)$'
if (-not $neon) { throw 'NEON_DATABASE_URL not found in .env' }
$env:LOCAL_DATABASE_URL = $local.Matches[0].Groups[1].Value
$env:NEON_DATABASE_URL = $neon.Matches[0].Groups[1].Value

Write-Host 'Pushing local Indeed rows -> Neon ...' -ForegroundColor Cyan
& "$Repo\.venv\Scripts\python.exe" scripts\push_indeed_to_neon.py
$exit = $LASTEXITCODE

if ($exit -ne 0) {
    Write-Host ''
    Write-Host "Push failed (exit $exit) - see the message above or logs\job_market_intel.log." -ForegroundColor Red
} else {
    Write-Host ''
    Write-Host 'Push complete. Neon now has the local rows.' -ForegroundColor Green
}
Write-Host ''
Write-Host 'Press any key to close...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
