@echo off
REM Wrapper for the Kaggle translation kernel watchdog scheduled task.
REM
REM Three limits make this file necessary rather than convenient:
REM   * schtasks /tr accepts at most 261 characters, and the full python +
REM     script + log-redirect command exceeds that.
REM   * Task Scheduler has no native log redirection.
REM   * `kaggle` is deliberately NOT a project dependency (see
REM     tests/unit/test_declared_dependencies.py), so the project venv cannot
REM     import it. `uv run --with kaggle` supplies it at run time -- which also
REM     means the interpreter the watchdog re-execs (`sys.executable -m kaggle`)
REM     is the one that actually has the package.
REM
REM uv is invoked by absolute path because a scheduled task starts with a
REM minimal PATH that does not include %USERPROFILE%\.local\bin.
REM
REM The watchdog checks whether today's Kaggle-scheduled run published to the
REM Hugging Face overlay. Kaggle's schedule fires at ~09:03 UTC (15:03 local)
REM and, at peak free-tier demand, is allocated a CPU-only slot where the
REM kernel's guard aborts in ~10 seconds before uploading anything. A manual
REM `kaggle kernels push` waits for a GPU and succeeds (3/3 observed), so this
REM wrapper re-pushes the current notebook when the overlay is stale.
REM
REM Kaggle's API blocks GitHub Actions' datacenter IPs (HTTP 403), so this
REM MUST run from this laptop's residential connection -- not from CI.
REM Runs at 15:20 local (09:20 UTC), ~17 min after the Kaggle schedule fires.

setlocal

set "REPO=D:\Research_Project\JobMarketAnalysisPlatform\DataBase\job-market-intel"
set "LOGDIR=%REPO%\kaggle_translation_logs"
set "UV=C:\Users\Sifat\.local\bin\uv.exe"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%UV%" (
    >> "%LOGDIR%\kaggle_translation.log" echo [%DATE% %TIME%] uv not found at "%UV%"
    exit /b 1
)

cd /d "%REPO%"
"%UV%" run --with kaggle python "%REPO%\scripts\kaggle_watchdog_local.py" >> "%LOGDIR%\kaggle_translation.log" 2>&1
exit /b %ERRORLEVEL%
