@echo off
rem ============================================================
rem 复制运行期配置和动态库到 exe 旁边
rem   用法:  scripts\stage_local.bat
rem
rem 为什么必须复制到 exe 旁边：程序用 get_executable_path() 把配置目录
rem 解析为 <exe目录>/runtimelibrary/（main.cpp:68-94），与工作目录无关。
rem 另外 ThirdPart\Config 和 ThirdPart\Dll 被刻意排除在 VS 同步之外，
rem 所以这一步没法省。
rem ============================================================
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1
set "PYTHONIOENCODING=gbk:replace"
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
	echo [错误] 找不到 python，请确认它在 PATH 上
	exit /b 1
)

call scripts\load_local_env.bat stage
if errorlevel 1 exit /b 1

if "!PROJECT_DIR!"=="" (
	echo [错误] 环境变量加载失败。先手动验证一下：
	echo        python scripts\render_schema.py --print-env local-win
	exit /b 1
)

set "PROJ=!PROJECT_DIR:/=\!"
set "BUILD=!BUILD_SUBDIR:/=\!"
set "CONFIGSRC=!CONFIG_SOURCE_DIR:/=\!"
set "DLLSRC=!DLL_SOURCE_DIR:/=\!"
set "EXEDIR=!PROJ!\!BUILD!\Bin"

echo ============================================================
echo  复制运行期文件到 exe 旁边
echo ============================================================
echo  源配置文件 : !CONFIGSRC!
echo  源动态库   : !DLLSRC!
echo  目标       : !EXEDIR!
echo.

if not exist "!CONFIGSRC!\" (
	echo [错误] 找不到配置源目录：!CONFIGSRC!
	exit /b 1
)
if not exist "!EXEDIR!\" (
	echo [错误] 找不到 exe 目录：!EXEDIR!
	echo        先跑 scripts\build_local.bat
	exit /b 1
)
if not exist "!EXEDIR!\!EXE_NAME!" (
	echo [警告] exe 还不存在：!EXEDIR!\!EXE_NAME!
	echo        配置仍会复制过去，但运行前必须先编译
	echo.
)

rem ---- 复制运行期配置 ----
rem robocopy 的退出码含义：0-7 都算成功（其中 1 表示有文件被复制），
rem 8 及以上才是真错误。所以这里用 ">= 8" 判断失败。
echo [1/3] 复制运行期配置 ...
robocopy "!CONFIGSRC!" "!EXEDIR!" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
	echo [错误] 复制配置失败，robocopy 退出码 !ERRORLEVEL!
	exit /b 1
)
echo       完成

rem ---- 复制动态库 ----
echo [2/3] 复制动态库 ...
robocopy "!DLLSRC!" "!EXEDIR!" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
	echo [错误] 复制动态库失败，robocopy 退出码 !ERRORLEVEL!
	exit /b 1
)
echo       完成

rem ---- 补充散装 xml 到 exe 旁边 ----
rem 程序是在 <exe目录>\cellformat.xml 直接找这个文件的，不是在 config\ 子目录下。
rem 实测日志：Failed to load D:\...\Bin\\cellformat.xml!
rem 所以 config\ 下这几个 xml 要额外复制一份到 exe 目录，两处都放才稳。
echo [3/3] 补充 cellformat.xml 等到 exe 旁边 ...
robocopy "!CONFIGSRC!\config" "!EXEDIR!" *.xml /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
	echo [错误] 复制 xml 失败，robocopy 退出码 !ERRORLEVEL!
	exit /b 1
)
echo       完成

echo.
echo [完成] exe 旁边现在应当包含：
echo   runtimelibrary\   运行单和场景配置（渲染出来的运行单也在这里）
echo   config\           cellformat / cluttermatchsettings / penetrationformat
echo   models\           LiShuttleModel.xml 等
echo   antennas\         天线方向图
echo   pyAndsh\          Python 侧脚本（-f ai 需要）
echo   log4cpp.conf      日志配置
echo   lishuttlesign     签名文件
echo   *.dll             uplancommon / uplangraphic / lishuttlectl / log4cpp 等
echo.
echo 下一步：python scripts\render_schema.py jobs\^<任务单^>.env local-win
endlocal
exit /b 0
