#!/usr/bin/env bash
# ============================================================
# 把服务器上的运行结果和日志回收到本机（在本机 Git Bash 里运行）
#   用法:  scripts/fetch_results.sh jobs/example-pl-guangzhou.env
#
# 同时在服务器上打包，避免逐文件传输的开销（见 docs 里的说明）。
# 回收到 results/<任务名>/ 下，连同运行单和渲染记录一起，便于追溯。
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

JOBFILE="${1:-}"
if [ -z "$JOBFILE" ]; then
    echo "用法: scripts/fetch_results.sh jobs/<任务单>.env" >&2
    echo "例如: scripts/fetch_results.sh jobs/example-pl-guangzhou.env" >&2
    exit 1
fi
if [ ! -f "$JOBFILE" ]; then
    echo "[错误] 找不到任务单 $JOBFILE" >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/env/server.env"
REMOTE="${SSH_USER}@${SSH_HOST}"
REMOTE_WF="$REMOTE_WORKFLOW_DIR"

SSH_OPTS=(-p "$SSH_PORT" -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

echo "============================================================"
echo " 回收结果"
echo "============================================================"
echo " 任务单 : $JOBFILE"
echo " 从     : $REMOTE"
echo

# ---- 在服务器上问出输出目录和 exe 目录 ----
# 用渲染记录作为唯一事实来源，避免本地重复实现一套路径拼接
echo "[1/4] 询问服务器上的输出位置 ..."
PRINTED="$(ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "cd '$REMOTE_WF' && python3 scripts/render_schema.py '$JOBFILE' server --print-run" \
    | tr -d '\r')" || {
    echo "[错误] 取运行参数失败。可能原因：" >&2
    echo "       - SSH 免密没配好" >&2
    echo "       - 服务器上还没跑过渲染（先执行 render_schema.py）" >&2
    exit 1
}

get_field() { printf '%s\n' "$PRINTED" | grep "^$1=" | head -1 | cut -d= -f2- ; }

REMOTE_OUT="$(get_field OUT_DIR)"
REMOTE_EXE_DIR="$(get_field EXE_DIR)"
JOB_NAME="$(get_field JOB_NAME)"
SCHEMA_ARGS="$(get_field SCHEMA_ARGS)"

for pair in "OUT_DIR:$REMOTE_OUT" "EXE_DIR:$REMOTE_EXE_DIR" "JOB_NAME:$JOB_NAME"; do
    if [ -z "${pair#*:}" ]; then
        echo "[错误] 服务器没有返回 ${pair%%:*}，请先在服务器上跑一次渲染" >&2
        exit 1
    fi
done

echo "       输出目录 : $REMOTE_OUT"
echo "       任务名   : $JOB_NAME"
echo

DEST="$ROOT/results/$JOB_NAME"
mkdir -p "$DEST"

# ---- 打包结果 ----
echo "[2/4] 在服务器上打包结果 ..."
if ssh "${SSH_OPTS[@]}" "$REMOTE" "test -d '$REMOTE_OUT'"; then
    ssh "${SSH_OPTS[@]}" "$REMOTE" \
        "cd '$REMOTE_OUT' && tar czf /tmp/lishuttle-result-$$.tar.gz . && ls -lh /tmp/lishuttle-result-$$.tar.gz"
    TARBALL="/tmp/lishuttle-result-$$.tar.gz"
else
    echo "       [警告] 服务器上输出目录还不存在: $REMOTE_OUT"
    echo "              说明任务还没跑，或者跑失败了。只回收下面的运行单和记录。"
    TARBALL=""
fi

# ---- 拉回来 ----
echo "[3/4] 下载到 $DEST ..."
if [ -n "$TARBALL" ]; then
    scp "${SSH_OPTS[@]}" "$REMOTE:$TARBALL" "$DEST/result.tar.gz"
    tar xzf "$DEST/result.tar.gz" -C "$DEST"
    rm -f "$DEST/result.tar.gz"
    ssh "${SSH_OPTS[@]}" "$REMOTE" "rm -f '$TARBALL'"
    echo "       结果已解压"
fi

# 运行单和渲染记录也一起拿回来：出问题时能直接看出当时用的什么参数和路径
echo "       下载运行单和渲染记录 ..."
mkdir -p "$DEST/runtimelibrary"
for name in $SCHEMA_ARGS; do
    scp "${SSH_OPTS[@]}" \
        "$REMOTE:$REMOTE_EXE_DIR/runtimelibrary/${name}*" \
        "$DEST/runtimelibrary/" 2>/dev/null || \
        echo "       [警告] 没取到 $name（可能还没渲染过）"
done

# ---- 汇总 ----
echo
echo "[4/4] 回收完成"
echo "============================================================"
echo " 本地位置 : $DEST"
echo "============================================================"
if [ -d "$DEST" ]; then
    echo "内容："
    # shellcheck disable=SC2012
    ls -1sh "$DEST" | head -20 | sed 's/^/  /'
fi
echo
echo "看日志："
echo "  less $DEST/uplan.log              # 报错先看里面的 FATAL / ERROR 行"
echo "  cat $DEST/nohup.out               # 后台运行时的标准输出"
