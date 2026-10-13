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

REM Fold CI's shards back into local BEFORE pushing. Order is load-bearing.
REM CI scrapes into an ephemeral container whose core.jobs starts empty, so its
REM rows exist only as HF shards. export_corpus_to_hf.py rebuilds shards/ from
REM local alone and DELETES every shard it did not just write, so an unmerged CI
REM row is destroyed by the very push meant to publish it. That is not
REM hypothetical: 10 of the 17 ledger paths were 404 before the merge existed.
REM Failing this step is still worth pushing for -- the merge only ever adds
REM rows -- so the failure is recorded and the push continues.
REM The pull half has already run by this point, so there is nothing left to
REM protect by swallowing a failure here. Previously this file ended with
REM "exit /b %PULL_RC%", which returned ONLY the pull's exit code: a merge or
REM export failure printed a line to the console, was written to the log, and
REM was then discarded. Task Scheduler reported result 0 -- success. That is
REM how a 401 Unauthorized on the HF publish step went unnoticed for hours on
REM 2026-10-13, with local and HF silently out of step the whole time.
REM Each stage's code is captured and the worst one is returned.
set "MERGE_RC=0"
set "EXPORT_RC=0"

"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\merge_incoming_shards.py" >> "%DEST%\logs\sync.log" 2>&1
if errorlevel 1 (
  echo [run_corpus_sync] merge_incoming_shards FAILED, see sync.log
  set "MERGE_RC=1"
)

REM Push local -> HF. The requirement is that local and HF always agree, and a
REM pull-only sync cannot deliver that: any correction made on this laptop (a
REM re-resolved location, a merged row, an applied translation) would sit here
REM while HF kept serving the old values. That is exactly how 87,486 rows kept
REM a stale location on HF.
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\export_corpus_to_hf.py" >> "%DEST%\logs\sync.log" 2>&1
if errorlevel 1 (
  echo [run_corpus_sync] export to HF FAILED, see sync.log
  set "EXPORT_RC=1"
)

if not "%PULL_RC%"=="0"   set "PULL_RC=1"
if "%MERGE_RC%"=="1"     set "PULL_RC=1"
if "%EXPORT_RC%"=="1"    set "PULL_RC=1"

if "%PULL_RC%"=="0" (
  echo [run_corpus_sync] OK ^(pull^ merge^ export^ all succeeded^)
) else (
  echo [run_corpus_sync] FAILED ^(pull=%PULL_RC% merge=%MERGE_RC% export=%EXPORT_RC%^)
)

exit /b %PULL_RC%