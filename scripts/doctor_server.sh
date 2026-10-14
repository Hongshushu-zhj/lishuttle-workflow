#!/usr/bin/env bash
# ============================================================
# 服务器环境体检（在服务器上运行）
#   用法:  scripts/doctor_server.sh
# 只读检查，不修改任何东西
# ============================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# 读环境文件。KEY="VALUE" 格式带引号，bash 可以直接 source
# shellcheck disable=SC1091
source "$ROOT/env/server.env"

FAIL=0

ok()   { printf '  [OK  ] %s\n' "$1"; }
bad()  { printf '  [缺失] %s\n         %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }
warn() { printf '  [警告] %s\n         %s\n' "$1" "$2"; }
opt()  { printf '  [可选] %s\n' "$1"; }

check_cmd() {
    local label="$1" cmd="$2" version_arg="${3:---version}"
    if command -v "$cmd" >/dev/null 2>&1; then
        local ver
        ver="$("$cmd" "$version_arg" 2>&1 | head -1)"
        ok "$label  ($ver)"
    else
        bad "$label" "命令 $cmd 不在 PATH 上"
    fi
}

echo "============================================================"
echo " 服务器环境体检"
echo " 主机: $(hostname)   用户: $(whoami)"
echo "============================================================"
echo

echo "[工具链]"
check_cmd "cmake"  cmake
check_cmd "ninja"  ninja
check_cmd "gcc"    gcc
check_cmd "python3" python3
echo "         顶层 CMakeLists.txt 要求 cmake >= 3.10"

echo
echo "[第三方依赖]"
echo "  这些被 VS 的同步排除在外，是人工预置的，必须存在"
if [ -d "$THIRDPART_ROOT" ]; then
    ok "$THIRDPART_ROOT"
    for sub in Lib include; do
        if [ -d "$THIRDPART_ROOT/$sub" ]; then
            local_count=$(find "$THIRDPART_ROOT/$sub" -maxdepth 1 | wc -l)
            ok "  $sub  ($((local_count-1)) 项)"
        else
            warn "  $sub 不存在" "$THIRDPART_ROOT/$sub"
        fi
    done
    # 链接时明确用到的库
    for lib in libuplancommon libuplangraphic liblishuttlectl liblog4cpp; do
        if find "$THIRDPART_ROOT" -name "${lib}*" 2>/dev/null | grep -q .; then
            ok "  $lib"
        else
            warn "  找不到 $lib 相关文件" \
                 "顶层 CMakeLists.txt 的 link_directories 指向 $THIRDPART_ROOT/Lib"
        fi
    done
else
    bad "$THIRDPART_ROOT" "顶层 CMakeLists.txt:73 的 link_directories 指向它，必须先准备好"
fi

# log4cpp 头文件：Linux 分支从这两个位置找
if [ -d /usr/include/log4cpp ] || [ -d /usr/local/include/log4cpp ]; then
    ok "log4cpp 头文件"
else
    bad "log4cpp 头文件" "顶层 CMakeLists.txt:67 从 /usr/include/log4cpp 或 /usr/local/include/log4cpp 找，需要安装 log4cpp-devel"
fi

echo
echo "[项目]"
if [ -f "$PROJECT_DIR/CMakeLists.txt" ]; then
    ok "$PROJECT_DIR"
    [ -f "$PROJECT_DIR/CMakePresets.json" ] && ok "  CMakePresets.json" \
        || bad "  CMakePresets.json" "找不到，无法用 --preset $PRESET"
else
    bad "$PROJECT_DIR" "源码还没同步过来，先在本地跑 scripts/sync_push.sh"
fi

echo
echo "[数据根]"
for pair in "地图根:$MAP_ROOT" "任务包根:$CASE_ROOT" "输出根:$OUT_ROOT"; do
    label="${pair%%:*}"; path="${pair#*:}"
    if [ -d "$path" ]; then
        ok "$label  $path"
    else
        bad "$label" "$path 不存在，请核对 env/server.env"
    fi
done
if [ -d "$DT_ROOT" ]; then
    ok "路测数据根  $DT_ROOT"
else
    warn "路测数据根  $DT_ROOT 不存在" "只有 -f dt / -f cali 需要它"
fi

echo
echo "[地图数据抽查]"
if [ -d "$MAP_ROOT" ]; then
    echo "  已装载的城市："
    # shellcheck disable=SC2012
    ls -1 "$MAP_ROOT" 2>/dev/null | head -20 | sed 's/^/    /'
    for city in guangzhou hefei; do
        if [ -d "$MAP_ROOT/$city" ]; then
            ok "  $city 存在"
        else
            opt "  $city 不存在（没用到就不用管）"
        fi
    done
fi

echo
echo "[构建产物]"
if [ -x "$PROJECT_DIR/$BUILD_SUBDIR/Bin/$EXE_NAME" ]; then
    ok "可执行文件  $PROJECT_DIR/$BUILD_SUBDIR/Bin/$EXE_NAME"
    # 确认 RPATH 生效：应指向 $ORIGIN/../Lib
    if command -v readelf >/dev/null 2>&1; then
        rpath="$(readelf -d "$PROJECT_DIR/$BUILD_SUBDIR/Bin/$EXE_NAME" 2>/dev/null \
                 | grep -i 'runpath\|rpath' || true)"
        if [ -n "$rpath" ]; then
            echo "         RPATH: $(echo "$rpath" | sed 's/.*\[\(.*\)\]/\1/')"
        fi
    fi
    if [ -d "$PROJECT_DIR/$BUILD_SUBDIR/Lib" ]; then
        ok "库目录      $PROJECT_DIR/$BUILD_SUBDIR/Lib"
    else
        bad "库目录" "$PROJECT_DIR/$BUILD_SUBDIR/Lib 不存在，动态库会找不到"
    fi
else
    opt "还没编译：$PROJECT_DIR/$BUILD_SUBDIR/Bin/$EXE_NAME"
    echo "         先跑 scripts/build_server.sh"
fi

if [ -d "$INSTALL_PREFIX" ]; then
    ok "安装前缀    $INSTALL_PREFIX"
else
    opt "安装前缀 $INSTALL_PREFIX 不存在（只有跑 --install 才需要）"
fi

echo
echo "[磁盘空间]"
df -h "$PROJECT_DIR" 2>/dev/null | sed 's/^/  /'

echo
echo "============================================================"
if [ "$FAIL" -eq 0 ]; then
    echo " 体检结果：关键项全部就位"
else
    echo " 体检结果：有 $FAIL 项关键项缺失，见上面的 [缺失]"
fi
echo "============================================================"
exit "$FAIL"
