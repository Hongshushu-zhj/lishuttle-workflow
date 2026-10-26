@echo off
rem ============================================================
rem 本地编译（Windows / x64-release 预设）
rem   用法:  scripts\build_local.bat             仅编译
rem          scripts\build_local.bat --install   编译并安装
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

call scripts\load_local_env.bat build
if errorlevel 1 exit /b 1

if "!PROJECT_DIR!"=="" (
	echo [错误] 环境变量加载失败。先手动验证一下：
	echo        python scripts\render_schema.py --print-env local-win
	exit /b 1
)

set "PROJ=!PROJECT_DIR:/=\!"
set "BUILD=!BUILD_SUBDIR:/=\!"

echo ============================================================
echo  本地编译
echo ============================================================
echo  项目目录 : !PROJECT_DIR!
echo  预设     : !PRESET!
echo  构建目录 : !BUILD_SUBDIR!
echo.

rem ---- 检查工具链 ----
if not exist "!CMAKE!" (
	echo [错误] 找不到 cmake
	echo        期望位置：!CMAKE!
	echo        请核对 env\local-win.env 里的 CMAKE 一行
	exit /b 1
)
if not exist "!VCVARS!" (
	echo [错误] 找不到 vcvars64.bat
	echo        期望位置：!VCVARS!
	echo        请核对 env\local-win.env 里的 VCVARS 一行
	exit /b 1
)
if not exist "!PROJ!\CMakePresets.json" (
	echo [错误] 找不到项目或 CMakePresets.json：!PROJ!
	echo        请核对 env\local-win.env 里的 PROJECT_DIR 一行
	exit /b 1
)

rem ---- 让 ninja 进 PATH：预设用的是 Ninja 生成器 ----
for %%I in ("!NINJA!") do set "NINJA_DIR=%%~dpI"
set "PATH=!NINJA_DIR!;!PATH!"

rem ---- 加载 MSVC 环境 ----
rem 必须做这一步，否则 cl.exe 不在 PATH 上。
rem 预设里写死了 CMAKE_CXX_COMPILER=cl.exe，找不到编译器就直接配置失败。
echo [1/3] 加载 MSVC 编译环境 ...
call "!VCVARS!" >nul
if errorlevel 1 (
	echo [错误] 加载 vcvars64.bat 失败
	exit /b 1
)

cd /d "!PROJ!"

rem ---- 生成 ----
echo [2/3] CMake 生成 ...
"!CMAKE!" --preset !PRESET!
if errorlevel 1 (
	echo.
	echo [错误] CMake 生成失败。常见原因：
	echo        - 预设名不对：核对 env\local-win.env 里的 PRESET
	echo        - 构建目录损坏：删掉 "!BUILD!" 后重试
	echo        - 之前用 VS 打开过：先关掉 VS，避免文件占用
	exit /b 1
)

rem ---- 编译 ----
echo [3/3] 编译 ...
"!CMAKE!" --build "!BUILD!"
if errorlevel 1 (
	echo.
	echo [错误] 编译失败，请往上看第一条 error
	exit /b 1
)

echo.
echo [完成] 编译产物：
echo   可执行文件 : !PROJ!\!BUILD!\Bin\!EXE_NAME!
echo   库文件     : !PROJ!\!BUILD!\Lib\

rem ---- 可选安装 ----
if /i "%~1"=="--install" (
	echo.
	echo [附加] 安装 ...
	"!CMAKE!" --install "!BUILD!"
	if errorlevel 1 (
		echo [错误] 安装失败
		exit /b 1
	)
	echo [完成] 已安装到 !PROJ!\!INSTALL_SUBDIR:/=\!\
)

echo.
echo 下一步：scripts\stage_local.bat
endlocal
exit /b 0
