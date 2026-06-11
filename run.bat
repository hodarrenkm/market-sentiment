@echo off
cd /d "%~dp0"

REM ── Python resolution ─────────────────────────────────────────────────────
REM Set PYTHON_CMD before calling this script to override auto-detection.
REM   e.g. set PYTHON_CMD=C:\Users\darre\miniconda3\envs\market\python.exe
if not defined PYTHON_CMD (
    if exist "%~dp0.venv\Scripts\python.exe" (
        set PYTHON_CMD="%~dp0.venv\Scripts\python.exe"
    ) else (
        set PYTHON_CMD=python
    )
)

REM ── Logging ───────────────────────────────────────────────────────────────
if not exist "%~dp0logs" mkdir "%~dp0logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set LOG=%~dp0logs\pipeline_%TODAY%.log

echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo Started: %date% %time% >> "%LOG%"
echo Python:  %PYTHON_CMD% >> "%LOG%"
echo ============================================ >> "%LOG%"

REM ── Run pipeline ──────────────────────────────────────────────────────────
%PYTHON_CMD% -m src.pipeline >> "%LOG%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo PIPELINE FAILED (exit %ERRORLEVEL%) >> "%LOG%"
    exit /b 1
)
echo Pipeline OK >> "%LOG%"

REM ── Stage generated outputs ───────────────────────────────────────────────
git add docs\index.html data\history.csv >> "%LOG%" 2>&1
if exist "data\sp500_universe.csv" (
    git add data\sp500_universe.csv >> "%LOG%" 2>&1
)

REM ── Commit if there are staged changes ────────────────────────────────────
git diff --cached --quiet 2>nul
if %ERRORLEVEL% neq 0 (
    git commit -m "Auto: dashboard update %TODAY%" >> "%LOG%" 2>&1
    echo Committed >> "%LOG%"
)

REM ── Push (also flushes any previously unpushed commits) ───────────────────
git push origin main >> "%LOG%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo PUSH FAILED -- will retry on next run >> "%LOG%"
    exit /b 1
)
echo Pushed to GitHub >> "%LOG%"

echo Finished: %time% >> "%LOG%"
