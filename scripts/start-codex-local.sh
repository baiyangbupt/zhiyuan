#!/usr/bin/env bash
# Start a fresh, isolated Codex conversation stack for local validation.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# 访问面口径（模式/WS override/outer）与预检**共用同一份判据** ✓（见该文件头注释 ✓）。
# shellcheck source=scripts/codex-local-access.sh
source "$ROOT_DIR/scripts/codex-local-access.sh"

SERVER_CONFIG="${CODEX_LOCAL_SERVER_CONFIG:-}"
DATA_SOURCE="${CODEX_LOCAL_DATASET:-}"
CODEX_HOME_DIR="${CODEX_LOCAL_CODEX_HOME:-}"
BACKEND_PORT="${CODEX_LOCAL_BACKEND_PORT:-18290}"
AGENT_PORT="${CODEX_LOCAL_AGENT_PORT:-18291}"
RANK_PORT="${CODEX_LOCAL_RANK_PORT:-18292}"
WEB_PORT="${CODEX_LOCAL_WEB_PORT:-3201}"
RUN_DIR="${CODEX_LOCAL_RUN_DIR:-}"
CODEX_BIN="${CODEX_APP_SERVER_BIN:-codex}"
SKIP_WEB=false
SKIP_BUILD=false
PRINT_ACCESS_ENV=false

usage() {
    cat <<'EOF'
Usage: bash scripts/start-codex-local.sh [options]

Starts an isolated Backend, Rank, Codex Gateway Agent, and optionally Web UI.
It first runs the read-only preflight and refuses to use a shared or checked-in
backend configuration. It never adopts, stops, or replaces an existing process.

Required:
  --server-config PATH       Private, untracked Spring configuration file.
  --data-source NAME         Must be exactly "private-resettable".
  --codex-home PATH          Isolated CODEX_HOME with the intended model setup.
  INTERNAL_SERVICE_TOKEN    Export the shared internal-service credential.

Options:
  --backend-port PORT        Default: 18290
  --agent-port PORT          Default: 18291
  --rank-port PORT           Default: 18292
  --web-port PORT            Default: 3201
  --run-dir PATH             Fresh directory below .runtime/ for this run.
  --skip-web                 Do not start Next.js.
  --skip-build               Use the existing backend jar.
  --print-access-env         Print the effective access-mode env and exit 0.
  -h, --help                 Show this help.
EOF
}

fail() {
    printf 'codex-local start failed: %s\n' "$*" >&2
    exit 1
}

require_option_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" ]] || fail "$option requires a value"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server-config)
            require_option_value "$1" "${2:-}"
            SERVER_CONFIG="$2"
            shift 2
            ;;
        --data-source)
            require_option_value "$1" "${2:-}"
            DATA_SOURCE="$2"
            shift 2
            ;;
        --codex-home)
            require_option_value "$1" "${2:-}"
            CODEX_HOME_DIR="$2"
            shift 2
            ;;
        --backend-port)
            require_option_value "$1" "${2:-}"
            BACKEND_PORT="$2"
            shift 2
            ;;
        --agent-port)
            require_option_value "$1" "${2:-}"
            AGENT_PORT="$2"
            shift 2
            ;;
        --rank-port)
            require_option_value "$1" "${2:-}"
            RANK_PORT="$2"
            shift 2
            ;;
        --web-port)
            require_option_value "$1" "${2:-}"
            WEB_PORT="$2"
            shift 2
            ;;
        --run-dir)
            require_option_value "$1" "${2:-}"
            RUN_DIR="$2"
            shift 2
            ;;
        --skip-web)
            SKIP_WEB=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --print-access-env)
            PRINT_ACCESS_ENV=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

# 访问面先解析 ✓：模式不认识/公开模式缺 origin/outer 都在这里**拒** ✓，
# 而且发生在 preflight 与建目录之前 ✓（错配置不该留下任何痕迹 ✓）。
codex_local_access_resolve "$AGENT_PORT" "$WEB_PORT"
if [[ "$PRINT_ACCESS_ENV" == true ]]; then
    codex_local_access_print
    exit 0
fi

if [[ -z "$RUN_DIR" ]]; then
    RUN_DIR="$ROOT_DIR/.runtime/codex-local-$(date +%Y%m%d-%H%M%S)-$$"
fi

PREFLIGHT_ARGS=(
    --backend-port "$BACKEND_PORT"
    --agent-port "$AGENT_PORT"
    --rank-port "$RANK_PORT"
    --web-port "$WEB_PORT"
    --run-dir "$RUN_DIR"
)
[[ -n "$SERVER_CONFIG" ]] && PREFLIGHT_ARGS+=(--server-config "$SERVER_CONFIG")
[[ -n "$DATA_SOURCE" ]] && PREFLIGHT_ARGS+=(--data-source "$DATA_SOURCE")
[[ -n "$CODEX_HOME_DIR" ]] && PREFLIGHT_ARGS+=(--codex-home "$CODEX_HOME_DIR")
[[ "$SKIP_WEB" == true ]] && PREFLIGHT_ARGS+=(--skip-web)
[[ "$SKIP_BUILD" == true ]] && PREFLIGHT_ARGS+=(--skip-build)
bash "$ROOT_DIR/scripts/preflight-codex-local.sh" "${PREFLIGHT_ARGS[@]}"

token="${INTERNAL_SERVICE_TOKEN:-}"
if [[ -z "${token//[[:space:]]/}" || "$token" == *$'\r'* || "$token" == *$'\n'* ]]; then
    fail "INTERNAL_SERVICE_TOKEN must be a nonempty single-line credential"
fi

[[ ! -e "$RUN_DIR" ]] || fail "run directory already exists: $RUN_DIR"
umask 077
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/pids"

BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
AGENT_URL="http://127.0.0.1:$AGENT_PORT"
RANK_URL="http://127.0.0.1:$RANK_PORT"
WEB_URL="http://127.0.0.1:$WEB_PORT"

cat > "$RUN_DIR/stack.env" <<EOF
BACKEND_URL=$BACKEND_URL
AGENT_URL=$AGENT_URL
RANK_URL=$RANK_URL
WEB_URL=$WEB_URL
EOF

cleanup_after_failure() {
    local exit_code=$?
    trap - ERR
    printf 'codex-local start failed after creating %s; stopping this run\n' "$RUN_DIR" >&2
    bash "$ROOT_DIR/scripts/stop-codex-local.sh" "$RUN_DIR" >/dev/null 2>&1 || true
    exit "$exit_code"
}
trap cleanup_after_failure ERR

start_service() {
    local name="$1"
    local working_dir="$2"
    shift 2
    (
        cd "$working_dir"
        exec env "CODEX_LOCAL_RUN_DIR=$RUN_DIR" setsid "$@"
    ) >"$RUN_DIR/logs/$name.log" 2>&1 < /dev/null &
    local pid=$!
    printf '%s\n' "$pid" > "$RUN_DIR/pids/$name.pid"
    printf 'started %s (PID %s)\n' "$name" "$pid"
}

wait_for_http() {
    local name="$1"
    local url="$2"
    local auth_config=""
    if [[ "$name" == "backend" ]]; then
        local token="${INTERNAL_SERVICE_TOKEN:-}"
        if [[ -z "${token//[[:space:]]/}" || "$token" == *$'\r'* || "$token" == *$'\n'* ]]; then
            fail "INTERNAL_SERVICE_TOKEN must be a nonempty single-line credential"
            return 1
        fi
        local escaped_token="${token//\\/\\\\}"
        escaped_token="${escaped_token//\"/\\\"}"
        auth_config="$(printf 'header = "X-Internal-Service-Token: %s"\n' "$escaped_token")"
    fi
    local deadline=$((SECONDS + 90))
    local http_code
    while (( SECONDS < deadline )); do
        if [[ "$name" == "backend" ]]; then
            if http_code="$(printf '%s\n' "$auth_config" | curl -q --config - --proto '=http,https' --silent --show-error --max-time 2 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)" && [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
                printf '%s is healthy: %s\n' "$name" "$url"
                return
            fi
        elif curl --proto '=http,https' --silent --show-error --fail --max-time 2 "$url" >"$RUN_DIR/$name-health.json" 2>/dev/null; then
            printf '%s is healthy: %s\n' "$name" "$url"
            return
        fi
        sleep 1
    done
    fail "$name did not become healthy within 90 seconds; see $RUN_DIR/logs/$name.log"
}

if [[ "$SKIP_BUILD" == false ]]; then
    printf 'building backend jar\n'
    (
        cd "$ROOT_DIR/zhiyuan-server"
        mvn -q -DskipTests package
    )
fi

start_service "rank" "$ROOT_DIR/zhiyuan-rank" \
    "$ROOT_DIR/zhiyuan-rank/.venv/bin/gunicorn" -w 1 -b "127.0.0.1:$RANK_PORT" app:app
wait_for_http "rank" "$RANK_URL/health"

# 说明（同一个坑今天踩了两次 ✓✓）：下面这一串都是**同一条命令** ✓，中间**不能**夹注释 ✗——
# `\` 续行后接 `#` 注释会在这里终止命令 ✓，后面的参数会被当成独立命令执行 ✗
#（实测症状：`--conversation.ws.allowed-origins=…: 没有那个文件或目录` ✓）。
#   `conversation.ws.allowed-origins` —— WS 票据的来源白名单 ✓。共享配置里写的是
#   "测试域名 + 127.0.0.1:3001" ✓（注释明说"不做通配" ✓），而隔离栈的 web 跑在 ${WEB_PORT} ✓，
#   浏览器来自它 ✓ → 不在名单里就 `origin_forbidden` ✗（实测：`POST /conversation/ws-ticket` 403 ✓
#   → 前端"任何 403 整页跳回 /login" ✓ → 弹回登录页 ✓）。这里用**同一个访问面助手**算出的集合 ✓
#   （`ACCESS_ALLOWED_ORIGINS` ✓，与 agent 侧同源 ✓），不写第二份判据 ✓，也不做通配 ✓。
start_service "backend" "$ROOT_DIR/zhiyuan-server" \
    java -jar "$ROOT_DIR/zhiyuan-server/target/zhiyuan-server.jar" \
    "--spring.profiles.active=localtest" \
    "--spring.config.additional-location=file:$SERVER_CONFIG" \
    "--server.port=$BACKEND_PORT" \
    "--server.address=127.0.0.1" \
    "--conversation.ws.allowed-origins=https://test-www.gaotuzhiyuan.com,http://127.0.0.1:3001,${ACCESS_ALLOWED_ORIGINS}" \
    "--agent.zhiyuan.url=$AGENT_URL" \
    "--volunteer.rank.url=$RANK_URL"
wait_for_http "backend" "$BACKEND_URL/gaotu-assistant-bot/inner/ops/health"

# 说明（曾是一处真缺陷 ✓）：下面这一串环境赋值是**同一条命令** ✓，中间**不能**夹注释 ✗——
# `\` 续行后接 `#` 注释会在这里终止命令 ✓，后面的赋值会被当成独立命令执行 ✗
#（2026-09-26 起合同栈时实测：`CODEX_APP_SERVER_TIMEOUT_SECONDS=180: 未找到命令` ✓）。
# 各变量的原注释：
#   CODEX_APP_SERVER_TIMEOUT_SECONDS=180 —— 整轮截止时间。默认 30s 会掐断慢回合，
#     用户看到"当前对话引擎暂时不可用"而链路上只有 turn_timeout；与 compat 层对齐 ✓。
# 说明（第三处、同一个坑 ✓✓）：下面这一串也是**同一条命令** ✓，**不能**夹注释 ✗。
#   `CODEX_EVENT_STORE_REDIS_URL` —— **事件存储** ✓✓。有 store 时 `ConnectionChannel` 发的就是
#   **编号过的 V1 事件** ✓（`session_runtime.py:100-115` ✓ =
#   `{protocolVersion,type,sessionId,turnId,streamEpoch,sequence,payload}` ✓）；**没有 store 才退回老信封的映射** ✗
#   （`_native_event_frame` ✓，其注释写明是"给旧前端"的 ✓）。
#   隔离栈一直没配它 ✗ → 页面收到的全是老帧 ✓ → 新前端的 V1 reducer 无帧可吃 ✓（实测：帧里没有 turnId ✗）。
#   共享 agent 早就配了同一个键 ✓（`redis://127.0.0.1:16379/9` ✓）——这里对齐它 ✓。
# 说明（第四处、**同一个坑第三次** ✗✗）：下面这一串同样是**一条命令** ✓，**不能**夹注释 ✗。
#   `CODEX_APP_SERVER_USER_INPUT_MODE` —— **原生提问（A4 的桥）** ✓✓。
#   它的默认值是保守的 `structured_final` ✗（`app/config.py:157` ✓，注释原话：
#   "**开关没接上之前声明成 native，就是把'没测过的组合'当默认**" ✓）；
#   而那两个开关（`features.default_mode_request_user_input` /
#   `tools.experimental_request_user_input`）**只在声明 native 时才传** ✓（`composition.py:74-77` ✓）。
#   所以契约栈要练这条桥 ✓，就得在这里显式打开 ✓✓——**只给隔离栈** ✓（共享栈不动 ✗）。
# 说明（第五处、**也是"续行链里夹注释"那个坑** ✓✓）：下面这串同样是**一条命令** ✓，注释只能写在块外 ✗。
#   `GATEWAY_MODE` —— **默认一个字节都不变** ✓✓：写模式是 P2 的 `codex_write` ✓，它的语义不是
#   "给模型开写工具" ✗，而是"**确认链**在这台实例上是活的" ✓——所以 `MCP_MODE=readonly` 保持不变
#   是**对的** ✓，别顺手一起改 ✗。可覆盖的形状与上面 `CODEX_APP_SERVER_USER_INPUT_MODE` 一致 ✓；
#   谁要用：契约栈跑 F07/F08/F09/F13 那几格时 ✓（写路径的用例 ✗）。
start_service "agent" "$ROOT_DIR/zhiyuan-agent" \
    env \
    "CODEX_HOME=$CODEX_HOME_DIR" \
    "CODEX_APP_SERVER_BIN=$CODEX_BIN" \
    "CODEX_APP_SERVER_BINDING_REGISTRY_PATH=$RUN_DIR/codex-thread-bindings.sqlite" \
    "CODEX_APP_SERVER_APPROVAL_POLICY=never" \
    "CODEX_APP_SERVER_SANDBOX_POLICY=read-only" \
    "CODEX_APP_SERVER_TIMEOUT_SECONDS=180" \
    "CODEX_EVENT_STORE_REDIS_URL=redis://127.0.0.1:16379/9" \
    "CODEX_APP_SERVER_USER_INPUT_MODE=${CODEX_APP_SERVER_USER_INPUT_MODE:-native}" \
    "GATEWAY_MODE=${CODEX_LOCAL_GATEWAY_MODE:-codex_readonly}" \
    "INTERNAL_SERVICE_URL=$BACKEND_URL" \
    "RANK_SERVICE_URL=$RANK_URL" \
    "MCP_MODE=readonly" \
    "LOGFIRE_ENABLED=false" \
    env "CODEX_WS_ALLOWED_ORIGINS=$ACCESS_ALLOWED_ORIGINS" \
    "$ROOT_DIR/zhiyuan-agent/.venv/bin/uvicorn" app.server:app --host 127.0.0.1 --port "$AGENT_PORT"
wait_for_http "agent" "$AGENT_URL/health"

if [[ "$SKIP_WEB" == false ]]; then
    start_service "web" "$ROOT_DIR/zhiyuan-web" \
        env \
        "APP_ENV=dev" \
        "NEXT_PUBLIC_API_BASE_URL=$BACKEND_URL" \
        "NEXT_PUBLIC_ASSISTANT_API_BASE_URL=$BACKEND_URL" \
        "NEXT_PUBLIC_AGENT_API_BASE_URL=$AGENT_URL" \
        "NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=$ACCESS_WS_OVERRIDE" \
        "NEXT_PUBLIC_OUTER_API_BASE_URL=$ACCESS_OUTER_API_BASE_URL" \
        "NEXT_PUBLIC_CODEX_ACCESS_MODE=$ACCESS_MODE" \
        "NEXT_DIST_DIR=.next-dev" \
        "$ROOT_DIR/zhiyuan-web/node_modules/.bin/next" dev -H 127.0.0.1 -p "$WEB_PORT"
    wait_for_http "web" "$WEB_URL/gaotu-assistant-agent/health"
fi

trap - ERR
printf '\nCodex local stack is ready.\n'
printf '  Backend: %s\n  Agent:   %s\n  Rank:    %s\n' "$BACKEND_URL" "$AGENT_URL" "$RANK_URL"
if [[ "$SKIP_WEB" == false ]]; then
    printf '  Web:     %s\n' "$WEB_URL"
fi
printf '  Run:     %s\n' "$RUN_DIR"
printf '  Stop:    bash scripts/stop-codex-local.sh %s\n' "$RUN_DIR"
