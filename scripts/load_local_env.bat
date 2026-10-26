@echo off
rem Shared local profile loader. Caller uses setlocal.
rem Capture once; all later render/print-run subprocesses inherit this snapshot.
chcp 936 >nul 2>&1
set "PYTHONIOENCODING=gbk:replace"
set "LISHUTTLE_ENV_EXPORT=%TEMP%\lishuttle-env-%RANDOM%-%RANDOM%.tmp"
if not defined LISHUTTLE_CONFIG_SNAPSHOT (
    python scripts\project_config.py --snapshot > "%LISHUTTLE_ENV_EXPORT%"
    if errorlevel 1 (
        del /q "%LISHUTTLE_ENV_EXPORT%" 2>nul
        exit /b 1
    )
    set /p LISHUTTLE_CONFIG_SNAPSHOT=<"%LISHUTTLE_ENV_EXPORT%"
)
if not defined LISHUTTLE_CONFIG_SNAPSHOT exit /b 1
python scripts\render_schema.py --print-env local-win --batch --check-%~1 > "%LISHUTTLE_ENV_EXPORT%"
if errorlevel 1 (
    del /q "%LISHUTTLE_ENV_EXPORT%" 2>nul
    exit /b 1
)
for %%K in (PROJECT_DIR PRESET BUILD_SUBDIR INSTALL_SUBDIR EXE_NAME VS_ROOT CMAKE NINJA VCVARS CONFIG_SRC DLL_SRC MAP_ROOT CASE_ROOT OUT_ROOT DT_ROOT GONGCAN_ROOT PROJECT_PROFILE_ID PROJECT_PROFILE_REVISION CONFIG_SOURCE_DIR DLL_SOURCE_DIR) do set "%%K="
for /f "usebackq tokens=1,* delims==" %%a in ("%LISHUTTLE_ENV_EXPORT%") do set "%%a=%%b"
del /q "%LISHUTTLE_ENV_EXPORT%" 2>nul
set "LISHUTTLE_ENV_EXPORT="
if not defined PROJECT_DIR exit /b 1
exit /b 0
