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
    local deadline=$((SECONDS + 90))
    while (( SECONDS < deadline )); do
        if curl --silent --show-error --fail --max-time 2 "$url" >"$RUN_DIR/$name-health.json" 2>/dev/null; then
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

start_service "backend" "$ROOT_DIR/zhiyuan-server" \
    java -jar "$ROOT_DIR/zhiyuan-server/target/zhiyuan-server.jar" \
    "--spring.profiles.active=localtest" \
    "--spring.config.additional-location=file:$SERVER_CONFIG" \
    "--server.port=$BACKEND_PORT" \
    "--server.address=127.0.0.1" \
    "--agent.zhiyuan.url=$AGENT_URL" \
    "--volunteer.rank.url=$RANK_URL"
wait_for_http "backend" "$BACKEND_URL/gaotu-assistant-bot/inner/ops/health"

start_service "agent" "$ROOT_DIR/zhiyuan-agent" \
    env \
    "CODEX_HOME=$CODEX_HOME_DIR" \
    "CODEX_APP_SERVER_BIN=$CODEX_BIN" \
    "CODEX_APP_SERVER_BINDING_REGISTRY_PATH=$RUN_DIR/codex-thread-bindings.sqlite" \
    "CODEX_APP_SERVER_APPROVAL_POLICY=never" \
    "CODEX_APP_SERVER_SANDBOX_POLICY=read-only" \
    # 整轮截止时间。默认 30s 会**掐断**慢回合（读技能 + 取数 + 长推理很容易超），
    # 用户看到的是"当前对话引擎暂时不可用"，而链路上只看得到 turn_timeout。
    # 和 compat 层的 _CHAT_SERVICE_TIMEOUT_SECONDS=180 对齐。
    "CODEX_APP_SERVER_TIMEOUT_SECONDS=180" \
    "GATEWAY_MODE=codex_readonly" \
    "INTERNAL_SERVICE_URL=$BACKEND_URL" \
    "RANK_SERVICE_URL=$RANK_URL" \
    "MCP_MODE=readonly" \
    "MCP_WRITE_TOOLS_ENABLED=false" \
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
