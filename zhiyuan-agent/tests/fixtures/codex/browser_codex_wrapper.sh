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

# 真实形状（2026-09-26 实测，`app/gateway/composition.py:build_codex_command` ✓）：
#     <bin> [--config mcp_servers.…={…}] [NATIVE_USER_INPUT_FLAGS…] app-server --stdio
# —— 配置参数**在子命令之前** ✓，**子命令在最后** ✓。第一版我假设 `$1` 就是 `app-server` ✗，
# 于是在真栈上被拒（退出码 64 ✓，日志 `app server exited on its own returncode=64` ✓）。
# 所以只能"**在整串参数里找**"，不能看位置 ✓。
[[ $# -ge 1 ]] || fail "没有任何参数：期望 '… app-server --stdio'（收到 0 个 ✗）"
APP_SERVER_SEEN=false
STDIO_SEEN=false
for arg in "$@"; do
    [[ "$arg" == "app-server" ]] && APP_SERVER_SEEN=true
    [[ "$arg" == "--stdio" ]] && STDIO_SEEN=true
done
[[ "$APP_SERVER_SEEN" == true ]] || fail "参数里没有 app-server 子命令 ✓（收到：$* ✗）"
# `--stdio` 必须在 ✓：非 stdio 模式我们没实现 ✓，静默放过去只会浪费一轮 ✗。
[[ "$STDIO_SEEN" == true ]] || fail "缺少 --stdio ✓（收到：$* ✗）"

# 注意 ✓：`--config …` 我们不消费 ✓（替身不发真实 MCP 调用 ✓，只发合成的 MCP 项 ✓，
# 那正是闸门用例要的形状 ✓）；原样透传即可 ✓。
exec "$PYTHON_BIN" "$APP_SERVER" "$@"
