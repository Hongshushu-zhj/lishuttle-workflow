#!/usr/bin/env bash
# ============================================================
# 把源码和工作流脚本推到服务器（在本机 Git Bash 里运行）
#   用法:  scripts/sync_push.sh
#
# 传输方式：tar 打包后走 SSH 管道。
# 为什么不用 scp -r：scp 是逐文件往返的，几千个小文件会慢到难以忍受。
# 打包成一个流只走一次网络，几十 MB 的源码几秒钟就传完了。
#
# 排除清单刻意和 CMakePresets.json 里的 copyExcludeDirectoriesList
# 保持一致：那几项在服务器上是人工预置的，不需要也不应该同步过去。
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# 本地项目位置在 local-win.env，连接信息在 server.env，两个都要读。
# 注意顺序：先读本地、把值取出来，再读服务器那份覆盖 PROJECT_DIR。
# shellcheck disable=SC1091
source "$ROOT/env/local-win.env"
LOCAL_PROJECT="${PROJECT_DIR%/}"

# shellcheck disable=SC1091
source "$ROOT/env/server.env"
REMOTE_PROJECT="$PROJECT_DIR"
REMOTE_WF="$REMOTE_WORKFLOW_DIR"
REMOTE="${SSH_USER}@${SSH_HOST}"

SSH_OPTS=(-p "$SSH_PORT" -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

echo "============================================================"
echo " 推送源码到服务器"
echo "============================================================"
echo " 本地项目   : $LOCAL_PROJECT"
echo " 本地工作流 : $ROOT"
echo " 服务器     : $REMOTE"
echo " 远程项目   : $REMOTE_PROJECT"
echo " 远程工作流 : $REMOTE_WF"
echo

if [ ! -d "$LOCAL_PROJECT" ]; then
    echo "[错误] 找不到本地项目目录: $LOCAL_PROJECT" >&2
    echo "        核对 env/local-win.env 里的 PROJECT_DIR" >&2
    exit 1
fi
if [ ! -f "$SSH_KEY" ]; then
    echo "[错误] 找不到私钥: $SSH_KEY" >&2
    echo "        先按 docs/ssh-免密与Xshell对应.md 生成并安装密钥" >&2
    exit 1
fi

# ---- 先确认免密可用 ----
# BatchMode=yes 保证它不会卡在密码提示上，而是直接失败
echo "[0/3] 检查 SSH 免密连接 ..."
if ! ssh "${SSH_OPTS[@]}" "$REMOTE" "echo ok" >/dev/null 2>&1; then
    echo "[错误] SSH 免密登录失败" >&2
    echo "       请先按 docs/ssh-免密与Xshell对应.md 配置公钥" >&2
    echo "       验证命令：" >&2
    echo "         ssh -i \"$SSH_KEY\" $REMOTE \"echo ok\"" >&2
    exit 1
fi
echo "       连接正常"
echo

# ---- 推源码 ----
echo "[1/3] 推送源码 ..."
tar czf - -C "$LOCAL_PROJECT" \
    --exclude='./.svn' \
    --exclude='./.vs' \
    --exclude='./out' \
    --exclude='./bak' \
    --exclude='./ThirdPart/Dll' \
    --exclude='./ThirdPart/Lib' \
    --exclude='./ThirdPart/include/log4cpp' \
    --exclude='./ThirdPart/include/python' \
    --exclude='./ThirdPart/Config' \
    . | ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "mkdir -p '$REMOTE_PROJECT' && tar xzf - -C '$REMOTE_PROJECT'"
echo "       完成（已排除 .svn / .vs / out / bak 和服务器上人工预置的 ThirdPart 子目录）"

# ---- 推工作流脚本 ----
echo "[2/3] 推送工作流脚本 ..."
tar czf - -C "$ROOT" \
    --exclude='./results' \
    scripts env jobs templates docs README.md \
    | ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "mkdir -p '$REMOTE_WF' && tar xzf - -C '$REMOTE_WF'"
echo "       完成"

# ---- 修正换行符和权限 ----
# Windows 上编辑过的文件可能带 CRLF，Linux 的 bash 会报
#   $'\r': command not found
# 每次推送后统一清一遍，这样即便你在 Windows 上编辑过也没事。
echo "[3/3] 修正换行符和可执行权限 ..."
ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "cd '$REMOTE_WF' && sed -i 's/\r\$//' scripts/*.sh env/*.env 2>/dev/null; chmod +x scripts/*.sh; echo '       完成'"

echo
echo "============================================================"
echo " 推送完成"
echo "============================================================"
echo
echo "在服务器上继续（可以直接用 Xshell 连上去敲）："
echo "  cd $REMOTE_WF"
echo "  scripts/doctor_server.sh"
echo "  scripts/build_server.sh"
echo "  scripts/stage_server.sh"
echo "  python3 scripts/render_schema.py jobs/<任务单>.env server"
echo "  scripts/run_server.sh jobs/<任务单>.env"
echo
echo "也可以在本机一条命令远程执行，例如："
echo "  ssh -i \"$SSH_KEY\" $REMOTE 'cd $REMOTE_WF && scripts/build_server.sh'"
