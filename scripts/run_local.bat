@echo off
rem Managed Windows entry point. All run logic lives in run_local.py.
setlocal DisableDelayedExpansion
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not available on PATH.
    exit /b 2
)
python "%~dp0run_local.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
