@echo off
rem Managed Windows entry point. All run logic lives in run_local.py.
setlocal DisableDelayedExpansion
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
call "%~dp0validate_local_python.bat"
set "LISHUTTLE_PYTHON_CHECK=%ERRORLEVEL%"
if not "%LISHUTTLE_PYTHON_CHECK%"=="0" exit /b %LISHUTTLE_PYTHON_CHECK%
"%LISHUTTLE_PYTHON%" "%~dp0run_local.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
