# Registers the corpus sync so it runs daily AND catches up whenever the
# laptop comes online.
#
# Why two mechanisms: the requirement is "it lands on my laptop whenever it comes
# online", which a single daily schedule cannot satisfy -- a machine that is
# asleep or powered off at 03:20 silently misses it, and only syncs the next
# time it happens to be awake at that minute.
#
#   1. schtasks daily 03:20  -- the normal case. Works WITHOUT elevation.
#   2. HKCU\...\Run         -- runs at every logon, so any run missed while the
#                              machine was off/asleep is caught the moment the
#                              user returns. Also without elevation.
#
# A schtasks /sc onlogon task would be the tidier way to express (2), but it
# needs administrator rights ("Access is denied"); the per-user Run key needs
# none and has the same logon semantics.
#
# Both point at scripts/run_corpus_sync.cmd, which passes --max-age-hours 20.
# That is what makes the overlap safe: whichever fires first does the work, the
# other sees a fresh manifest and exits without downloading anything.
#
# Idempotent: re-running replaces the existing entries.
param(
    [string]$RepoPath = "D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel",
    [string]$DestPath = "D:\Research_Project\JobMarketAnalysisPlatform\DataBase\corpus_backup",
    # Not $At/$Minute: those names collide with formatting operators here.
    [int]    $AtHour  = 3,
    [int]    $AtMinute = 20
)

$ErrorActionPreference = "Stop"
$wrapper = Join-Path $RepoPath "scripts\run_corpus_sync.cmd"
if (-not (Test-Path $wrapper)) { throw "wrapper not found: $wrapper" }
New-Item -ItemType Directory -Force -Path (Join-Path $DestPath "logs") | Out-Null

$dailyName = "JMI Corpus Sync (daily)"
$logonKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$logonName = "JMI Corpus Sync"

# 1. daily -------------------------------------------------------------------
$at = "{0}:{1}" -f $AtHour.ToString("00"), $AtMinute.ToString("00")
schtasks /create /tn $dailyName /tr "`"$wrapper`"" /sc daily /st $at /f | Out-Null
Write-Output "scheduled task : $dailyName  (daily $at)"

# 2. every logon -------------------------------------------------------------
if (-not (Test-Path $logonKey)) { New-Item -Path $logonKey -Force | Out-Null }
New-ItemProperty -Path $logonKey -Name $logonName -Value "`"$wrapper`"" `
    -PropertyType String -Force | Out-Null
Write-Output "logon trigger   : HKCU\...\Run\$logonName"

# verify ---------------------------------------------------------------------
$info = schtasks /query /tn $dailyName /fo LIST /v 2>&1
$info | Select-String -Pattern "^Next Run Time|^Status|^Task To Run" |
    ForEach-Object { "  $($_.Line.Trim())" }
$run = (Get-ItemProperty -Path $logonKey).$logonName
Write-Output "  logon value    : $run"

Write-Output ""
Write-Output "run now : schtasks /run /tn `"$dailyName`""
Write-Output "remove  : schtasks /delete /tn `"$dailyName`" /f  ;  Remove-ItemProperty -Path `"$logonKey`" -Name `"$logonName`""
Write-Output "log     : $(Join-Path $DestPath 'logs\sync.log')"