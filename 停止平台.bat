@echo off
rem ============================================================
rem 停止 lishuttle 本地平台（双击即可）
rem   按 8641 端口找到平台进程并结束（含它派生的 lishuttle 子进程）
rem ============================================================
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1

set "FOUND=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8641" ^| findstr "LISTENING" 2^>nul') do (
    rem 只杀 python 进程，避免误伤恰好占用该端口的其他程序
    tasklist /FI "PID eq %%p" 2>nul | findstr /I "python" >nul
    if not errorlevel 1 (
        echo [停止] 结束平台进程 PID=%%p（连同其子进程）
        taskkill /F /T /PID %%p >nul 2>&1
        set "FOUND=1"
    )
)

if "!FOUND!"=="0" (
    echo [提示] 平台没有在运行。
) else (
    echo [完成] 平台已停止。
)
ping -n 3 127.0.0.1 >nul
