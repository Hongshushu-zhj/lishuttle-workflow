@echo off
rem ============================================================
rem 启动 lishuttle 本地平台（双击即可）
rem   - 平台已在运行  -> 直接打开浏览器
rem   - 平台未在运行  -> 启动服务并自动打开浏览器
rem   关闭本窗口或按 Ctrl+C 即停止平台（同时会结束正在跑的任务）
rem ============================================================
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 找不到 python，请确认它在 PATH 上
    pause
    exit /b 1
)

rem ---- 检查 8641 端口是否已被本平台占用 ----
set "RUNNING=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8641" ^| findstr "LISTENING" 2^>nul') do (
    for /f "tokens=1" %%n in ('tasklist /FI "PID eq %%p" ^| findstr /I "python"') do set "RUNNING=1"
)

if "!RUNNING!"=="1" (
    echo [提示] 平台已在运行，直接打开浏览器： http://127.0.0.1:8641
    start http://127.0.0.1:8641
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

echo [启动] lishuttle 本地平台 ...
echo        页面地址: http://127.0.0.1:8641
echo        停止方式: 关闭本窗口 / Ctrl+C  /  双击 停止平台.bat
echo.
python platform\backend\server.py
