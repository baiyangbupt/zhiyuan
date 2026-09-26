#!/usr/bin/env bash
# 合同栈的 Codex 二进制替身外壳（Task C4 ②）。
#
# 作用：把"`CODEX_APP_SERVER_BIN` 指向谁"这件事**收进一个可审计的文件** ✓——
# 只有 `scripts/start-codex-contract.sh` 会把它设成这个脚本的绝对路径 ✓，
# 于是"这一轮用的是假模型"在**部署配置**上就看得见 ✓（项目名不算证据 ✗）。
#
# 它做两件事 ✓：
#   1. **校验参数形状** ✓：composition 必须按 `app-server --stdio …` 起它 ✓（形状不对就拒 ✗——
#      静默忽略参数会让"起错了协议"变成一轮难查的假绿 ✗）；
#   2. 用**测试 venv 的 python** ✓ 执行 `browser_app_server.py` ✓，其余参数原样透传 ✓。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APP_SERVER="$HERE/browser_app_server.py"
# 测试 venv 的 python ✓（宿主 /usr/bin/python3 是 3.6 ✗，连 `from __future__` 都过不去 ✓）。
PYTHON_BIN="${CODEX_BROWSER_PYTHON:-$HERE/../../../.venv/bin/python}"

fail() {
    printf 'browser_codex_wrapper: %s\n' "$*" >&2
    exit 64   # 用法错误 ✓（与进程自身失败区分开 ✓）
}

[[ -x "$PYTHON_BIN" ]] || fail "测试 venv 的 python 不可执行：$PYTHON_BIN（可用 CODEX_BROWSER_PYTHON 指定 ✓）"
[[ -f "$APP_SERVER" ]] || fail "找不到 browser_app_server.py：$APP_SERVER"

[[ $# -ge 1 ]] || fail "缺少子命令：期望 'app-server --stdio …'（收到 0 个参数 ✗）"
SUBCOMMAND="$1"
shift
[[ "$SUBCOMMAND" == "app-server" ]] || fail "只认 'app-server' ✓（收到 '$SUBCOMMAND' ✗）"

# `--stdio` 必须在 ✓：非 stdio 模式我们没实现 ✓，静默放过去只会浪费一轮 ✗。
STDIO_SEEN=false
for arg in "$@"; do
    [[ "$arg" == "--stdio" ]] && STDIO_SEEN=true
done
[[ "$STDIO_SEEN" == true ]] || fail "缺少 --stdio ✓（收到：$* ✗）"

exec "$PYTHON_BIN" "$APP_SERVER" "$@"
