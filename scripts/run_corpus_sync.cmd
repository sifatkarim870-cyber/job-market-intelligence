@echo off
REM Wrapper for the corpus sync scheduled tasks.
REM
REM Two limits make this file necessary rather than convenient:
REM   * schtasks /tr accepts at most 261 characters, and the full python +
REM     script + --dest + log-redirect command exceeds that.
REM   * Task Scheduler has no native log redirection.
REM
REM --max-age-hours 20 makes the daily trigger and the logon trigger safe to
REM have both point here: whichever fires first does the work, the other sees a
REM fresh manifest and exits without downloading anything.

setlocal
set "REPO=D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel"
set "DEST=D:\Research_Project\JobMarketAnalysisPlatform\DataBase\corpus_backup"

if not exist "%DEST%\logs" mkdir "%DEST%\logs"

"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\sync_corpus_from_hf.py" --dest "%DEST%" --max-age-hours 20 >> "%DEST%\logs\sync.log" 2>&1
set "PULL_RC=%ERRORLEVEL%"

REM Push local -> HF. The requirement is that local and HF always agree, and a
REM pull-only sync cannot deliver that: any correction made on this laptop (a
REM re-resolved location, a merged row, an applied translation) would sit here
REM while HF kept serving the old values. That is exactly how 87,486 rows kept
REM a stale location on HF. Failures are logged but do not fail the task, so a
REM transient Hub outage cannot stop the pull half from having run.
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\export_corpus_to_hf.py" >> "%DEST%\logs\sync.log" 2>&1
if errorlevel 1 echo [run_corpus_sync] export to HF FAILED, see sync.log

exit /b %PULL_RC%