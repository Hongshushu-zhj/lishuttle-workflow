@echo off
rem ============================================================
rem 本地运行
rem   用法:  scripts\run_local.bat jobs\example-pl-guangzhou.env
rem          scripts\run_local.bat jobs\xxx.env --no-render
rem
rem 工作目录刻意设在 exe 所在目录：那里是所有运行期文件（runtimelibrary、
rem config、models、antennas、log4cpp.conf）的集中地，所以无论程序是按
rem "相对 exe" 还是"相对当前目录"去找文件，都能找到。
rem 运行结束后再把日志收集到任务输出目录，便于归档和回收。
rem ============================================================
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1
set "PYTHONIOENCODING=gbk:replace"
cd /d "%~dp0.."

set "JOBFILE=%~1"
set "NORENDER=%~2"

if "%JOBFILE%"=="" (
	echo 用法: scripts\run_local.bat jobs\^<任务单^>.env [--no-render]
	echo 例如: scripts\run_local.bat jobs\example-pl-guangzhou.env
	exit /b 1
)
if not exist "%JOBFILE%" (
	echo [错误] 找不到任务单 %JOBFILE%
	exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
	echo [错误] 找不到 python，请确认它在 PATH 上
	exit /b 1
)

call scripts\load_local_env.bat run
if errorlevel 1 exit /b 1
if "!PROJECT_DIR!"=="" (
	echo [错误] 环境变量加载失败。先手动验证一下：
	echo        python scripts\render_schema.py --print-env local-win
	exit /b 1
)

echo ============================================================
echo  本地运行
echo ============================================================
echo  任务单 : %JOBFILE%
echo.

rem ---- 取运行参数 ----
rem 和渲染走的是同一个解析逻辑，所以"渲染用的路径"和"运行用的路径"必然一致。
rem RENDER_BEFORE_RUN 也在这里取，避免批处理去解析含中文注释的任务单文件。
set "FUNC="
set "PRINTMODE=--prepare-render"
if /i "%NORENDER%"=="--no-render" set "PRINTMODE="
for /f "usebackq tokens=1,* delims==" %%a in (`python scripts\render_schema.py "%JOBFILE%" local-win --print-run --batch !PRINTMODE!`) do set "%%a=%%b"

if "!FUNC!"=="" (
	echo [错误] 取运行参数失败。先手动验证一下：
	echo        python scripts\render_schema.py "%JOBFILE%" local-win --print-run
	exit /b 1
)

if /i "%NORENDER%"=="--no-render" (
	echo [跳过] --no-render，沿用已有运行单
	echo.
) else (
	if "!RENDER_BEFORE_RUN!"=="0" (
		echo [跳过] 任务单里 RENDER_BEFORE_RUN=0，沿用已有运行单
		echo.
	) else (
		echo [1/3] 渲染运行单 ...
		python scripts\render_schema.py "%JOBFILE%" local-win
		if errorlevel 1 (
			echo.
			echo [注意] 渲染时有必需文件缺失，继续运行大概率会失败。
			pause
		)
		echo.
	)
)

rem ---- 前置检查 ----
rem Refresh paths from the generated XML after rendering (or manual edits).
for /f "usebackq tokens=1,* delims==" %%a in (`python scripts\render_schema.py "%JOBFILE%" local-win --print-run`) do set "%%a=%%b"

set "EXEDIR=!EXE_DIR:/=\!"
if not exist "!EXE_PATH:/=\!" (
	echo [错误] 找不到可执行文件：!EXE_PATH!
	echo        先跑 scripts\build_local.bat 和 scripts\stage_local.bat
	exit /b 1
)

echo [2/3] 运行 lishuttle ...
echo   可执行文件 : !EXE_PATH!
echo   工作目录   : !EXE_DIR!
echo   命令行     : -f !FUNC! -t !TASK_ID! -c !SCHEMA_ARGS!
echo.

rem ---- 运行 ----
rem 工作目录设在 exe 旁边；产物按 PathlossDirectory（绝对路径）落到任务输出目录
set "STARTDIR=%CD%"
cd /d "!EXEDIR!"
"!EXE_PATH!" -f !FUNC! -t !TASK_ID! -c !SCHEMA_ARGS!
set "RC=!ERRORLEVEL!"
cd /d "!STARTDIR!"

echo.
echo [3/3] 收集日志到任务输出目录 ...
if not exist "!OUT_DIR:/=\!" mkdir "!OUT_DIR:/=\!" >nul 2>&1

rem uplan.log 和各服务的 *_log.txt 是在工作目录（exe 旁边）生成的，
rem 搬到任务输出目录，和 pathloss 结果放一起，便于归档和回收
set "MOVED=0"
if exist "!EXEDIR!\uplan.log" (
	move /y "!EXEDIR!\uplan.log" "!OUT_DIR:/=\!" >nul 2>&1
	set "MOVED=1"
)
for %%F in ("!EXEDIR!\*_log.txt") do (
	if exist "%%F" (
		move /y "%%F" "!OUT_DIR:/=\!" >nul 2>&1
		set "MOVED=1"
	)
)
if "!MOVED!"=="1" (
	echo   日志已移到 !OUT_DIR!
) else (
	echo   没有发现日志文件
)

echo.
echo ============================================================
if "!RC!"=="0" (
	echo  运行结束：成功（退出码 0）
) else (
	echo  运行结束：失败（退出码 !RC!）
	echo  先看 !OUT_DIR!\uplan.log 里的 FATAL / ERROR 行
)
echo ============================================================
echo  输出目录 : !OUT_DIR!
echo  运行记录 : !EXEDIR!\runtimelibrary\!SCHEMA_ARGS!.manifest.json
endlocal
exit /b 0
