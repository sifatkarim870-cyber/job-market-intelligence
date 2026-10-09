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
exit /b %ERRORLEVEL%