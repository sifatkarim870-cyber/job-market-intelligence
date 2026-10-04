# ==========================================================================
# Indeed -> Neon: manual one-or-twice-a-day run.
#
# Thin wrapper that forces the scrape to write into the Neon (cloud) database
# and then runs the standard Indeed launcher (pacing + report included).
# Everything the launcher does -- one queue row, up to ~100 results from it,
# persistence, a final PowerShell report -- is unchanged; only the target DB
# is pinned to Neon here.
# ==========================================================================
$ErrorActionPreference = 'Stop'
$Repo = 'D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel'
Set-Location $Repo

# Pull NEON_DATABASE_URL out of .env and pin DATABASE_URL to it for this
# process. The scraper's config prefers the process env over .env, so every
# job insert in this run lands in Neon, even if .env gets edited later.
$neon = (Select-String -Path '.env' -Pattern '^NEON_DATABASE_URL=(.*)$').Matches.Groups[1].Value
if (-not $neon) { throw "NEON_DATABASE_URL not found in .env" }
$env:DATABASE_URL = $neon

& "$Repo\scripts\run_indeed_scrape.ps1"
