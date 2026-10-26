@echo off
rem ============================================================
rem 本地环境体检：跑任务之前先确认工具链和数据都在
rem   用法:  scripts\doctor_local.bat
rem 只读检查，不修改任何东西
rem ============================================================
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1
set "PYTHONIOENCODING=gbk:replace"
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
	echo [错误] 找不到 python
	echo        本套脚本用 python 解析环境文件和运行单，请确认它在 PATH 上
	exit /b 1
)

rem ---- 加载环境变量 ----
rem 刻意不自己逐行解析 env 文件：那是 UTF-8 带中文注释，而 cmd 按当前
rem 代码页（中文 Windows 是 GBK）解码，中文注释的字节会把行结构解析乱掉，
rem 导致前半段键被整个跳过。交给 python 输出才可靠。
call scripts\load_local_env.bat doctor
if errorlevel 1 exit /b 1

if "!PROJECT_DIR!"=="" (
	echo [错误] 环境变量加载失败。先手动验证一下：
	echo        python scripts\render_schema.py --print-env local-win
	exit /b 1
)

rem ---- 统一转成 Windows 反斜杠形式，供文件系统命令使用 ----
set "PROJ=!PROJECT_DIR:/=\!"
set "BUILD=!BUILD_SUBDIR:/=\!"
set "EXEDIR=!PROJ!\!BUILD!\Bin"
set "LIBDIR=!PROJ!\!BUILD!\Lib"
set "CONFIGSRC=!CONFIG_SOURCE_DIR:/=\!"
set "DLLSRC=!DLL_SOURCE_DIR:/=\!"
set "MAPROOT=!MAP_ROOT:/=\!"

set "FAIL=0"

echo ============================================================
echo  本地环境体检
echo ============================================================
echo.

echo [工具链]
call :chkfile "VS2022 自带的 CMake"       "!CMAKE!"
call :chkfile "VS2022 自带的 Ninja"       "!NINJA!"
call :chkfile "vcvars64.bat（加载 MSVC）" "!VCVARS!"

echo.
echo [项目]
call :chkdir  "项目根目录"                "!PROJ!"
call :chkfile "CMakeLists.txt"            "!PROJ!\CMakeLists.txt"
call :chkfile "CMakePresets.json"         "!PROJ!\CMakePresets.json"

echo.
echo [第三方依赖（Windows 用仓库内的）]
call :chkdir  "ThirdPart\Lib"             "!PROJ!\ThirdPart\Lib"
call :chkdir  "ThirdPart\Dll"             "!DLLSRC!"
call :chkfile "uplancommon.lib"           "!PROJ!\ThirdPart\Lib\uplancommon.lib"
call :chkfile "uplancommon.dll"           "!DLLSRC!\uplancommon.dll"
call :chkfile "lishuttlectl.lib"          "!PROJ!\ThirdPart\Lib\lishuttlectl.lib"
call :chkfile "lishuttlectl.dll"          "!DLLSRC!\lishuttlectl.dll"

echo.
echo [运行期配置源头]
call :chkdir  "ThirdPart\Config"          "!CONFIGSRC!"
call :chkdir  "  runtimelibrary"          "!CONFIGSRC!\runtimelibrary"
call :chkdir  "  models"                  "!CONFIGSRC!\models"
call :chkdir  "  antennas"                "!CONFIGSRC!\antennas"
call :chkfile "  log4cpp.conf"            "!CONFIGSRC!\log4cpp.conf"
call :chkfile "  lishuttlesign"           "!CONFIGSRC!\lishuttlesign"

echo.
echo [数据根]
call :chkdir  "地图数据根"                "!MAPROOT!"
call :chkdir  "结果输出根"                "!OUT_ROOT!"
call :chkdir  "工参任务根目录"              "!GONGCAN_ROOT:/=\!"

echo.
echo [构建产物]
if exist "!EXEDIR!\!EXE_NAME!" (
	echo   [OK  ] 可执行文件        !EXEDIR!\!EXE_NAME!
) else (
	echo   [未生成] 可执行文件
	echo           !EXEDIR!\!EXE_NAME!
	echo           还没编译过，或编译到了别的预设。先跑 scripts\build_local.bat
)
if exist "!EXEDIR!\runtimelibrary\runtimeschema.xml" (
	echo   [OK  ] 已渲染运行单      !EXEDIR!\runtimelibrary\runtimeschema.xml
) else (
	echo   [未渲染] 运行单
	echo           !EXEDIR!\runtimelibrary\runtimeschema.xml
	echo           先跑 render_schema.py 渲染
)

echo.
echo ============================================================
if "!FAIL!"=="0" (
	echo  体检结果：关键项全部就位
) else (
	echo  体检结果：有 !FAIL! 项关键项缺失，见上面的 [缺失]
)
echo ============================================================
endlocal
exit /b 0

rem ---- 子过程 ----
rem 用 %~2 去掉引号再加引号，避免出现 "路径"\ 这种 cmd 解析不了的写法
:chkfile
if exist "%~2" (
	echo   [OK  ] %~1
) else (
	echo   [缺失] %~1
	echo           %~2
	set /a FAIL+=1
)
exit /b 0

:chkdir
if exist "%~2\" (
	echo   [OK  ] %~1
) else (
	echo   [缺失] %~1
	echo           %~2
	set /a FAIL+=1
)
exit /b 0
