#!/usr/bin/env bash
# ============================================================
# 服务器运行（在服务器上运行）
#   用法:  scripts/run_server.sh jobs/example-pl-guangzhou.env
#          scripts/run_server.sh jobs/xxx.env --no-render
#          scripts/run_server.sh jobs/xxx.env --foreground
#
# 工作目录刻意设在 exe 所在目录：那里是所有运行期文件（runtimelibrary、
# config、models、antennas、log4cpp.conf）的集中地，所以无论程序是按
# "相对 exe" 还是"相对当前目录"去找文件，都能找到。
# 运行结束后再把日志收集到任务输出目录，便于归档和回收。
#
# 默认后台运行（nohup）：-f acp / -f ai 这类任务可能跑很久，
# 前台跑的话 SSH 一断任务就死了。
# ============================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/env/server.env"

JOBFILE=""
OPT_NORENDER=0
OPT_FOREGROUND=0

for arg in "$@"; do
    case "$arg" in
        --no-render)  OPT_NORENDER=1 ;;
        --foreground) OPT_FOREGROUND=1 ;;
        --*)          echo "[错误] 不认识的选项: $arg" >&2; exit 1 ;;
        *)            JOBFILE="$arg" ;;
    esac
done

if [ -z "$JOBFILE" ]; then
    echo "用法: scripts/run_server.sh jobs/<任务单>.env [--no-render] [--foreground]" >&2
    echo "例如: scripts/run_server.sh jobs/example-pl-guangzhou.env" >&2
    exit 1
fi
if [ ! -f "$JOBFILE" ]; then
    echo "[错误] 找不到任务单 $JOBFILE" >&2
    exit 1
fi

echo "============================================================"
echo " 服务器运行"
echo "============================================================"
echo " 主机   : $(hostname)"
echo " 任务单 : $JOBFILE"
echo

# ---- 是否先重新渲染运行单 ----
if [ "$OPT_NORENDER" = "1" ]; then
    echo "[跳过] --no-render，沿用已有运行单"
    echo
else
    echo "[1/3] 渲染运行单 ..."
    if ! python3 "$ROOT/scripts/render_schema.py" "$JOBFILE" server; then
        echo
        echo "[注意] 渲染时有必需文件缺失，继续运行大概率会失败。" >&2
        read -r -p "按回车继续，或 Ctrl+C 中断 ... " _ || true
    fi
    echo
fi

# ---- 取运行参数 ----
# 从渲染记录里读，保证渲染和运行用的是同一份解析结果。
# 这里用白名单逐个赋值，不用 eval —— 避免任务单内容被当成代码执行。
FUNC="" TASK_ID="" SCHEMA_ARGS="" EXE_DIR="" EXE_PATH="" OUT_DIR="" JOB_NAME="" SERVER_BACKGROUND=""
while IFS='=' read -r key value; do
    case "$key" in
        FUNC)              FUNC="$value" ;;
        TASK_ID)           TASK_ID="$value" ;;
        SCHEMA_ARGS)       SCHEMA_ARGS="$value" ;;
        EXE_DIR)           EXE_DIR="$value" ;;
        EXE_PATH)          EXE_PATH="$value" ;;
        OUT_DIR)           OUT_DIR="$value" ;;
        JOB_NAME)          JOB_NAME="$value" ;;
        SERVER_BACKGROUND) SERVER_BACKGROUND="$value" ;;
    esac
done < <(python3 "$ROOT/scripts/render_schema.py" "$JOBFILE" server --print-run | tr -d '\r')

if [ -z "$FUNC" ]; then
    echo "[错误] 取运行参数失败，请确认上面的渲染步骤成功" >&2
    exit 1
fi
if [ ! -x "$EXE_PATH" ]; then
    echo "[错误] 找不到可执行文件或没有执行权限: $EXE_PATH" >&2
    echo "        先跑 scripts/build_server.sh 和 scripts/stage_server.sh" >&2
    if [ -f "$EXE_PATH" ]; then
        echo "        文件存在但不可执行，试试: chmod +x $EXE_PATH" >&2
    fi
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "[2/3] 运行 lishuttle ..."
echo "  可执行文件 : $EXE_PATH"
echo "  工作目录   : $EXE_DIR"
echo "  命令行     : -f $FUNC -t $TASK_ID -c $SCHEMA_ARGS"
echo "  输出目录   : $OUT_DIR"
echo

FOREGROUND=$OPT_FOREGROUND

cd "$EXE_DIR"

RC=0
if [ "$FOREGROUND" = "1" ]; then
    echo "  运行方式   : 前台（SSH 断开会导致任务终止）"
    echo
    "$EXE_PATH" -f "$FUNC" -t "$TASK_ID" -c "$SCHEMA_ARGS"
    RC=$?
else
    echo "  运行方式   : 后台 nohup"
    echo
    nohup "$EXE_PATH" -f "$FUNC" -t "$TASK_ID" -c "$SCHEMA_ARGS" \
        > "$OUT_DIR/nohup.out" 2>&1 &
    PID=$!
    echo "$PID" > "$OUT_DIR/lishuttle.pid"
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
        echo "  已启动，PID = $PID"
    else
        echo "  [警告] 进程在 2 秒内就退出了，很可能是启动失败"
        echo "        看一下 $OUT_DIR/nohup.out"
        RC=1
    fi
    echo
    echo "  查看进度："
    echo "    tail -f $OUT_DIR/uplan.log"
    echo "    tail -f $OUT_DIR/nohup.out"
    echo "  确认还在跑："
    echo "    ps -p \$(cat $OUT_DIR/lishuttle.pid)"
fi

echo
echo "[3/3] 收集日志到任务输出目录 ..."
MOVED=0
# 后台模式下程序可能还在写，只搬已经收尾的前台模式日志
if [ "$FOREGROUND" = "1" ] || [ "$RC" != "0" ]; then
    if [ -f "$EXE_DIR/uplan.log" ]; then
        mv -f "$EXE_DIR/uplan.log" "$OUT_DIR/" 2>/dev/null && MOVED=1
    fi
    for f in "$EXE_DIR"/*_log.txt; do
        [ -e "$f" ] || continue
        mv -f "$f" "$OUT_DIR/" 2>/dev/null && MOVED=1
    done
fi
if [ "$MOVED" = "1" ]; then
    echo "  日志已移到 $OUT_DIR"
else
    echo "  暂无日志需要搬移（后台任务仍在运行时日志还在 exe 目录）"
fi

echo
echo "============================================================"
if [ "$FOREGROUND" = "1" ]; then
    if [ "$RC" = "0" ]; then
        echo " 运行结束：成功（退出码 0）"
    else
        echo " 运行结束：失败（退出码 $RC）"
        echo " 先看 $OUT_DIR/uplan.log 里的 FATAL / ERROR 行"
    fi
else
    echo " 任务已在后台启动（PID $(cat "$OUT_DIR/lishuttle.pid" 2>/dev/null || echo '?')）"
fi
echo "============================================================"
echo " 输出目录 : $OUT_DIR"
echo " 渲染记录 : $EXE_DIR/runtimelibrary/${SCHEMA_ARGS}.manifest.json"
echo
echo "回收到本机：scripts/fetch_results.sh $JOB_NAME"
exit "$RC"
