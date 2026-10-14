#!/usr/bin/env bash
# ============================================================
# 服务器编译（Linux / linux-release 预设，在服务器上运行）
#   用法:  scripts/build_server.sh             仅编译
#          scripts/build_server.sh --install   编译并安装
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/env/server.env"

echo "============================================================"
echo " 服务器编译"
echo "============================================================"
echo " 主机      : $(hostname)"
echo " 项目目录  : $PROJECT_DIR"
echo " 预设      : $PRESET"
echo " 构建目录  : $BUILD_SUBDIR"
echo

# ---- 前置检查 ----
for cmd in cmake ninja; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[错误] 找不到 $cmd，先跑 scripts/doctor_server.sh 看缺什么" >&2
        exit 1
    fi
done

if [ ! -f "$PROJECT_DIR/CMakeLists.txt" ]; then
    echo "[错误] 找不到项目: $PROJECT_DIR" >&2
    echo "        先在本地跑 scripts/sync_push.sh 把源码推过来" >&2
    exit 1
fi

cd "$PROJECT_DIR"

# ---- 生成 ----
echo "[1/3] CMake 生成 ..."
cmake --preset "$PRESET"
echo

# ---- 编译 ----
echo "[2/3] 编译 ..."
cmake --build "$BUILD_SUBDIR" -j "$(nproc 2>/dev/null || echo 4)"
echo

echo "[完成] 编译产物："
echo "  可执行文件 : $PROJECT_DIR/$BUILD_SUBDIR/Bin/$EXE_NAME"
echo "  库文件     : $PROJECT_DIR/$BUILD_SUBDIR/Lib/"
echo

# ---- 可选安装 ----
if [ "${1:-}" = "--install" ]; then
    echo "[附加] 安装 ..."
    cmake --install "$BUILD_SUBDIR"
    echo "[完成] 已安装到 $INSTALL_PREFIX"
    echo
fi

echo "下一步：scripts/stage_server.sh"
