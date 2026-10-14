#!/usr/bin/env bash
# ============================================================
# 复制运行期配置到 exe 旁边（在服务器上运行）
#   用法:  scripts/stage_server.sh
#
# 为什么必须复制到 exe 旁边：程序用 get_executable_path() 把配置目录
# 解析为 <exe目录>/runtimelibrary/（main.cpp:68-94），与工作目录无关。
# 而 ThirdPart/Config 被 CMakePresets.json 的 copyExcludeDirectoriesList
# 排除在同步之外，所以这一步无法省。
#
# Linux 不需要复制动态库：第三方库在 $THIRDPART_ROOT/Lib，
# 运行期动态库靠 RPATH $ORIGIN/../Lib 自动找到。
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/env/server.env"

CONFIG_SRC_ABS="$PROJECT_DIR/$CONFIG_SRC"
EXE_DIR="$PROJECT_DIR/$BUILD_SUBDIR/Bin"

echo "============================================================"
echo " 复制运行期配置到 exe 旁边"
echo "============================================================"
echo " 源   : $CONFIG_SRC_ABS"
echo " 目标 : $EXE_DIR"
echo

if [ ! -d "$CONFIG_SRC_ABS" ]; then
    echo "[错误] 找不到配置源目录: $CONFIG_SRC_ABS" >&2
    exit 1
fi
if [ ! -d "$EXE_DIR" ]; then
    echo "[错误] 找不到 exe 目录: $EXE_DIR" >&2
    echo "        先跑 scripts/build_server.sh" >&2
    exit 1
fi
if [ ! -x "$EXE_DIR/$EXE_NAME" ]; then
    echo "[警告] exe 还不存在或没有执行权限: $EXE_DIR/$EXE_NAME"
    echo "        配置仍会复制过去，但运行前必须先编译"
    echo
fi

# 逐个目录复制，比整体 cp -a 更容易看出缺了什么
echo "复制以下内容："
for item in runtimelibrary config models antennas pyAndsh; do
    if [ -d "$CONFIG_SRC_ABS/$item" ]; then
        mkdir -p "$EXE_DIR/$item"
        cp -a "$CONFIG_SRC_ABS/$item/." "$EXE_DIR/$item/"
        printf '  [OK  ] %-16s -> %s/%s\n' "$item" "$EXE_DIR" "$item"
    else
        printf '  [跳过] %-16s 源目录不存在\n' "$item"
    fi
done

for item in log4cpp.conf lishuttlesign; do
    if [ -f "$CONFIG_SRC_ABS/$item" ]; then
        cp -a "$CONFIG_SRC_ABS/$item" "$EXE_DIR/$item"
        printf '  [OK  ] %-16s -> %s/%s\n' "$item" "$EXE_DIR" "$item"
    else
        printf '  [跳过] %-16s 源文件不存在\n' "$item"
    fi
done

# 根目录下的散装 csv（ap.csv、UrbanMeteorologicalData.csv 等）
shopt -s nullglob
for csv in "$CONFIG_SRC_ABS"/*.csv; do
    cp -a "$csv" "$EXE_DIR/"
    printf '  [OK  ] %-16s -> %s/\n' "$(basename "$csv")" "$EXE_DIR"
done

# config/ 下的几个 xml 额外复制一份到 exe 目录。
# 程序是在 <exe目录>/cellformat.xml 直接找它的，不是在 config/ 子目录下
# （实测日志：Failed to load .../Bin//cellformat.xml），两处都放才稳。
for xml in "$CONFIG_SRC_ABS"/config/*.xml; do
    cp -a "$xml" "$EXE_DIR/"
    printf '  [OK  ] %-16s -> %s/\n' "$(basename "$xml")" "$EXE_DIR"
done
shopt -u nullglob

echo
echo "[完成] exe 旁边现在应当包含："
echo "  runtimelibrary/   运行单和场景配置（渲染出来的运行单也在这里）"
echo "  config/           cellformat / cluttermatchsettings / penetrationformat"
echo "  models/           LiShuttleModel.xml 等"
echo "  antennas/         天线方向图"
echo "  pyAndsh/          Python 侧脚本（-f ai 需要）"
echo "  log4cpp.conf      日志配置"
echo "  lishuttlesign     签名文件"
echo
echo "下一步：python3 scripts/render_schema.py jobs/<任务单>.env server"
