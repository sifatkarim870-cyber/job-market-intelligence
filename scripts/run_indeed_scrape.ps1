# Indeed scraper — manual run
#
# Idempotent per-run behaviour (the pipeline already guarantees this):
#   - claims up to INDEED_ITEMS_PER_RUN=1 queue row (one combination),
#   - collects up to the per-session caps from that one combination,
#   - persists each batch of results to the database,
#   - marks the row done/pending accordingly, so the NEXT run claims the
#     next-oldest eligible combination (it claims last_scraped_at NULLS FIRST).
#
# If that combination yields fewer than the target, whatever it found is
# what's saved (page end or a detected challenge), and it is reported as-is.
#
# Env is scoped to this process only; it does not change repo defaults or CI.
$ErrorActionPreference = 'Stop'
$Repo = 'D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel'
Set-Location $Repo

# One combination per run; give that combination room to fill ~100 jobs.
$env:INDEED_ITEMS_PER_RUN = '1'
$env:INDEED_MAX_SEARCH_PAGES_PER_SESSION = '8'     # ~15 jobs/search page => ~120 available search hits
$env:INDEED_MAX_DETAIL_PAGES_PER_SESSION = '100'   # fetch detail pages for up to 100 jobs
$env:INDEED_UC_ENABLED = 'false'
$env:INDEED_HEADLESS = 'true'

# Small pause between each job's detail-page fetch. This is the knob to turn
# if Cloudflare challenges one run more than usual; raising it makes the
# crawl slower but less bursty.
$env:INDEED_DETAIL_PAGE_DELAY_MIN_SECONDS = '2.0'
$env:INDEED_DETAIL_PAGE_DELAY_MAX_SECONDS = '4.0'

$Summary = Join-Path $env:TEMP 'indeed_run_summary.json'
Remove-Item $Summary -ErrorAction SilentlyContinue

& "$Repo\.venv\Scripts\python.exe" scripts\run_indeed_scraper.py --summary-json $Summary

# --- PowerShell report -------------------------------------------------------
Write-Host ''
Write-Host '============================== INDEED RUN REPORT =============================='
if (Test-Path $Summary) {
    $s = Get-Content $Summary -Raw | ConvertFrom-Json
    $s | Format-List @{n='Outcome';e={$_.outcome}}, `
        @{n='Rows worked';e={$_.rows_worked}}, `
        @{n='Jobs inserted';e={$_.jobs_inserted}}, `
        @{n='Jobs updated';e={$_.jobs_updated}}, `
        @{n='Search pages visited';e={$_.search_pages_visited}}, `
        @{n='Detail pages visited';e={$_.detail_pages_visited}}, `
        @{n='Proxy used';e={$_.proxy_used}}, `
        @{n='Blocked reasons';e={ if ($_.blocked_reasons) { $_.blocked_reasons -join ' | ' } else { '(none)' } }}

    switch ($s.outcome) {
        'ok'      { Write-Host 'Result: completed normally.' -ForegroundColor Green }
        'partial' { Write-Host 'Result: challenged partway, but did collect this many jobs.' -ForegroundColor Yellow }
        'blocked' { Write-Host 'Result: challenged by Indeed/Cloudflare before collecting -- no new data. Cloudflare often needs this IP to cool down; try again later.' -ForegroundColor Yellow }
        'empty'   { Write-Host 'Result: queue was empty. Re-seed with scripts/seed_indeed_queries.py if needed.' -ForegroundColor DarkYellow }
        'error'   { Write-Host 'Result: run failed (see log).' -ForegroundColor Red }
    }
} else {
    Write-Host 'No summary file was written; the run likely crashed. Check logs\job_market_intel.log.' -ForegroundColor Red
}
Write-Host '================================================================================'
Write-Host ''
Write-Host 'Press any key to close...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
