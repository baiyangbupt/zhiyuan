#!/usr/bin/env bash
# 起动**合同栈**：隔离 infra + 四服务 ✓，但 Codex 侧换成**带闸门的替身**（Task C4 ②）。
#
# 三条纪律 ✓：
#   1. **先起控制服务，再起 Gateway** ✓——替身在 `turn/start` 时会去控制服务登记闸门 ✓，
#      服务晚起来就会先收到一堆连不上的等待 ✗；
#   2. **18293 被占就拒** ✗（"不能接管已有进程" ✓）：不做 kill、不做接管 ✓，
#      只报是谁占着 ✓，让人自己决定 ✓；
#   3. **只有本脚本设 `CODEX_APP_SERVER_BIN`** ✓（指向 wrapper 的**绝对路径** ✓）——
#      "这一轮用的是假模型"因此在**部署配置**上看得见 ✓（项目名不算证据 ✗）。
#
# 用法：
#   bash scripts/start-codex-contract.sh [--run-id NAME] [-- <start-codex-local.sh 的参数>]
#
# 停：Ctrl-C ✓（脚本会带走控制服务 ✓）或 `kill <控制服务 PID>`（它会打印出来 ✓）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CONTROL_PORT="${CODEX_BROWSER_CONTROL_PORT:-18293}"
CONTROL_HOST="${CODEX_BROWSER_CONTROL_HOST:-127.0.0.1}"
RUN_ID="${CODEX_BROWSER_RUN_ID:-contract-$(date +%Y%m%d-%H%M%S)}"
CONTROL_PY="$ROOT_DIR/zhiyuan-agent/tests/fixtures/codex/browser_runtime_control.py"
WRAPPER="$ROOT_DIR/zhiyuan-agent/tests/fixtures/codex/browser_codex_wrapper.sh"
PYTHON_BIN="${CODEX_BROWSER_PYTHON:-$ROOT_DIR/zhiyuan-agent/.venv/bin/python}"

fail() {
    printf 'codex-contract start failed: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: bash scripts/start-codex-contract.sh [--run-id NAME] [-- <start-codex-local.sh args>]

Starts the contract stack: the gated fake Codex (behind a loopback control service on
127.0.0.1:18293) plus the usual isolated infra and services.

Env:
  CODEX_BROWSER_CONTROL_PORT   default 18293
  CODEX_BROWSER_RUN_ID         default contract-<timestamp>（reset 按它清闸门 ✓）
  CODEX_BROWSER_PYTHON         default zhiyuan-agent/.venv/bin/python
EOF
}

LOCAL_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-id) [[ -n "${2:-}" ]] || fail "--run-id requires a value"; RUN_ID="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        --) shift; LOCAL_ARGS=("$@"); break ;;
        *) LOCAL_ARGS+=("$1"); shift ;;
    esac
done

[[ -f "$CONTROL_PY" ]] || fail "找不到控制服务：$CONTROL_PY"
[[ -x "$WRAPPER" ]] || fail "wrapper 不可执行：$WRAPPER（chmod +x ✓）"
[[ -x "$PYTHON_BIN" ]] || fail "测试 venv 的 python 不可执行：$PYTHON_BIN"

# ② 端口被占 → **拒绝启动** ✗（不接管 ✓、不强杀 ✓）。先看监听 ✓，再看健康与否 ✓，把话说清 ✓。
if (ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null) | grep -qE "[:.]${CONTROL_PORT}\b"; then
    holder="$( (ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null) | grep -E "[:.]${CONTROL_PORT}\b" | head -1 )"
    fail "控制端口 ${CONTROL_PORT} 已被占用 ✗（不接管已有进程 ✓）：$holder"
fi

echo "== 1/3 起控制服务（${CONTROL_HOST}:${CONTROL_PORT}）=="
"$PYTHON_BIN" "$CONTROL_PY" --host "$CONTROL_HOST" --port "$CONTROL_PORT" &
CONTROL_PID=$!
cleanup() {
    if kill -0 "$CONTROL_PID" 2>/dev/null; then
        echo "== 停控制服务（pid $CONTROL_PID）=="
        kill "$CONTROL_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# 等它就绪 ✓（连不上就不往下走 ✗——否则替身会在等待里超时 ✓，看起来像"闸门没放行" ✗✓）。
for _ in $(seq 1 40); do
    if curl -sS -m 2 "http://${CONTROL_HOST}:${CONTROL_PORT}/identity" >/dev/null 2>&1; then
        break
    fi
    sleep 0.25
done
IDENTITY="$(curl -sS -m 3 "http://${CONTROL_HOST}:${CONTROL_PORT}/identity" || true)"
[[ -n "$IDENTITY" ]] || fail "控制服务没起来（${CONTROL_HOST}:${CONTROL_PORT} 无响应 ✗）"
case "$IDENTITY" in
    *'"runtimeKind": "fake"'*|*'"runtimeKind":"fake"'*)
        echo "    ✓ identity: $IDENTITY（runtimeKind=fake ✓）" ;;
    *)
        fail "identity 不是 fake ✗：$IDENTITY" ;;
esac
echo "    ✓ 控制服务 pid=$CONTROL_PID（Ctrl-C 会带走它 ✓）"

echo "== 2/3 起隔离栈（Codex 侧指向替身 ✓）=="
echo "    CODEX_APP_SERVER_BIN=$WRAPPER（**只有本脚本设它** ✓）"
# 替身要能连上控制服务 ✓、并按 runId 登记闸门 ✓（reset 才清得到 ✓）。
CODEX_APP_SERVER_BIN="$WRAPPER" \
CODEX_BROWSER_CONTROL_BASE="http://${CONTROL_HOST}:${CONTROL_PORT}" \
CODEX_BROWSER_RUN_ID="$RUN_ID" \
    bash "$ROOT_DIR/scripts/start-codex-local.sh" ${LOCAL_ARGS[@]+"${LOCAL_ARGS[@]}"}

echo "== 3/3 合同栈已就绪 ✓ =="
echo "    runId=$RUN_ID（reset：curl -X POST http://${CONTROL_HOST}:${CONTROL_PORT}/runs/${RUN_ID}/reset ✓）"
echo "    跑用例："
echo "      ZHIYUAN_E2E_ORIGIN=<页面 origin> ZHIYUAN_E2E_SESSION_URL=<会话路由> \\"
echo "        bash scripts/run-codex-e2e-in-container.sh --project contract"

# 隔离栈是长跑的 ✓，这里**不等它退出**就交还控制权吗 ✗？——不 ✓：本脚本负责控制服务的生命周期 ✓，
# 所以它在前台守着 ✓，退出时由 trap 带走控制服务 ✓（隔离栈另有它自己的 stop 脚本 ✓）。
wait "$CONTROL_PID"
