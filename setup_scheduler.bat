@echo off
setlocal

set "TASK=MarketSentimentDashboard"
set "SCRIPT=%~dp0run.bat"

echo Task:     %TASK%
echo Script:   %SCRIPT%
echo Schedule: daily at 08:00 local time
echo           (make sure your PC clock is set to SGT / UTC+8)
echo.

REM Remove existing task so /create is idempotent
schtasks /delete /tn "%TASK%" /f >nul 2>&1

REM Create the daily task running as the current user.
REM  cmd /c ""path"" is the correct quoting for paths with spaces in /tr.
schtasks /create ^
    /tn "%TASK%" ^
    /tr "cmd /c \"\"%SCRIPT%\"\"" ^
    /sc daily ^
    /st 08:00 ^
    /ru "%USERNAME%" ^
    /f

if %ERRORLEVEL% neq 0 (
    echo.
    echo FAILED. Common fixes:
    echo   1. Run this script as Administrator.
    echo   2. Open Task Scheduler manually and create the task pointing to:
    echo      %SCRIPT%
    exit /b 1
)

echo.
echo SUCCESS. Verifying:
schtasks /query /tn "%TASK%" /fo list /v 2>nul | findstr /i "task name\|status\|next run\|run as"
echo.
echo To disable: schtasks /delete /tn "%TASK%" /f
echo To run now: schtasks /run /tn "%TASK%"
