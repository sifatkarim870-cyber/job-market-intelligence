# Registers the Kaggle translation watchdog so it runs daily AND catches up
# whenever the laptop comes online.
#
# Why two mechanisms: the Kaggle schedule fires at ~09:03 UTC (15:03 local) and,
# at peak free-tier demand, is allocated a CPU-only slot where the kernel's guard
# aborts in ~10 seconds before uploading anything. A manual `kaggle kernels
# push` waits for a GPU and succeeds (3/3 observed), so this watchdog re-pushes
# the current notebook when the Hugging Face overlay is stale.
#
#   1. schtasks daily 15:20  -- the normal case. Works WITHOUT elevation.
#      (15:20 local = 09:20 UTC, ~17 min after Kaggle's 09:03 UTC schedule
#       fires; gives the scheduled run time to fail fast, then re-pushes for a
#       GPU slot. A healthy GPU run publishes within ~10 minutes, so a fresh
#       overlay by 09:20 UTC means the scheduled run succeeded.)
#   2. HKCU\...\Run         -- runs at every logon, so any run missed while the
#                              machine was off/asleep is caught the moment the
#                              user returns. Also without elevation.
#
# Both point at scripts/run_kaggle_translation.cmd.
#
# Idempotent: re-running replaces the existing entries.
param(
    [string]$RepoPath = "D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel",
    [int]    $AtHour  = 15,
    [int]    $AtMinute = 20
)

$ErrorActionPreference = "Stop"
$wrapper = Join-Path $RepoPath "scripts\run_kaggle_translation.cmd"
if (-not (Test-Path $wrapper)) { throw "wrapper not found: $wrapper" }
New-Item -ItemType Directory -Force -Path (Join-Path $RepoPath "kaggle_translation_logs") | Out-Null

$dailyName = "JMI Kaggle Translation Watchdog (daily)"
$logonKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$logonName = "JMI Kaggle Translation Watchdog"

# 1. daily -------------------------------------------------------------------
$at = "{0}:{1}" -f $AtHour.ToString("00"), $AtMinute.ToString("00")
schtasks /create /tn $dailyName /tr "`"$wrapper`"" /sc daily /st $at /f | Out-Null
Write-Output "scheduled task : $dailyName  (daily $at = $($AtHour.ToString("00")):$($AtMinute.ToString("00")) local, 09:20 UTC)"

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
