@echo off
rem Caller must disable delayed expansion so literal ! in paths survives.
rem An explicit override is authoritative; never replace a broken interpreter.
if not defined LISHUTTLE_PYTHON set "LISHUTTLE_PYTHON=python"
rem Accept both raw and inherited quoted executable values, then quote once.
set "LISHUTTLE_PYTHON=%LISHUTTLE_PYTHON:"=%"
"%LISHUTTLE_PYTHON%" -B -c "import sys, argparse, json, pathlib, subprocess, xml.etree.ElementTree"
if not errorlevel 1 exit /b 0
set "LISHUTTLE_PYTHON_ERROR=%ERRORLEVEL%"
>&2 echo [ERROR] Python validation failed for "%LISHUTTLE_PYTHON%" ^(exit %LISHUTTLE_PYTHON_ERROR%^).
exit /b %LISHUTTLE_PYTHON_ERROR%
