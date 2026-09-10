#!/usr/bin/env bash
# Validate the isolated Codex local stack before any process is started.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

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

usage() {
    cat <<'EOF'
Usage: bash scripts/preflight-codex-local.sh [options]

Read-only checks for the isolated Codex local stack. The command never starts,
adopts, stops, or kills a process.

Required:
  --server-config PATH       Private, untracked Spring configuration file.
  --data-source NAME         Must be exactly "private-resettable".
  --codex-home PATH          Isolated CODEX_HOME with the intended model setup.

Options:
  --backend-port PORT        Default: 18290
  --agent-port PORT          Default: 18291
  --rank-port PORT           Default: 18292
  --web-port PORT            Default: 3201
  --run-dir PATH             Reserved run directory below .runtime/.
  --skip-web                 Do not validate the Web runtime.
  --skip-build               Require an existing backend jar instead of Maven.
  -h, --help                 Show this help.

Environment equivalents use the CODEX_LOCAL_* names documented in
docs/codex-local-stack.md.
EOF
}

fail() {
    printf 'codex-local preflight failed: %s\n' "$*" >&2
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
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

validate_port() {
    local name="$1"
    local port="$2"
    [[ "$port" =~ ^[0-9]+$ ]] || fail "$name must be a numeric port"
    (( port >= 1024 && port <= 65535 )) || fail "$name must be between 1024 and 65535"
}

validate_run_dir() {
    [[ -z "$RUN_DIR" ]] && return
    local run_parent run_name
    run_parent="$(dirname "$RUN_DIR")"
    run_name="$(basename "$RUN_DIR")"
    [[ "$run_parent" == "$ROOT_DIR/.runtime" && "$run_name" == codex-local-* ]] || \
        fail "run directory must be a direct child of $ROOT_DIR/.runtime/codex-local-*"
}

validate_private_server_config() {
    [[ -n "$SERVER_CONFIG" ]] || fail "--server-config or CODEX_LOCAL_SERVER_CONFIG is required"
    [[ "$SERVER_CONFIG" = /* ]] || fail "server configuration must be an absolute path"
    [[ -f "$SERVER_CONFIG" ]] || fail "server configuration does not exist"

    local config_dir config_name resolved_config
    config_dir="$(cd "$(dirname "$SERVER_CONFIG")" && pwd -P)"
    config_name="$(basename "$SERVER_CONFIG")"
    resolved_config="$config_dir/$config_name"
    SERVER_CONFIG="$resolved_config"

    if [[ "$resolved_config" == "$ROOT_DIR/zhiyuan-server/src/main/resources/"* ]]; then
        fail "server configuration must not use zhiyuan-server/src/main/resources defaults"
    fi
    if [[ "$resolved_config" == "$ROOT_DIR/"* && "$resolved_config" != "$ROOT_DIR/.local/codex-local/"* ]]; then
        fail "server configuration inside this repository must be below $ROOT_DIR/.local/codex-local"
    fi
    if [[ "$resolved_config" == "$ROOT_DIR/"* ]]; then
        local repository_path="${resolved_config#"$ROOT_DIR/"}"
        if git -C "$ROOT_DIR" ls-files --error-unmatch -- "$repository_path" >/dev/null 2>&1; then
            fail "server configuration must be private and untracked, not a repository configuration file"
        fi
    fi
}

validate_isolated_data_source() {
    [[ "$DATA_SOURCE" == "private-resettable" ]] || fail \
        "--data-source or CODEX_LOCAL_DATASET must be exactly private-resettable"
}

validate_codex_home() {
    [[ -n "$CODEX_HOME_DIR" ]] || fail "--codex-home or CODEX_LOCAL_CODEX_HOME is required"
    [[ "$CODEX_HOME_DIR" = /* ]] || fail "Codex home must be an absolute path"
    [[ -d "$CODEX_HOME_DIR" ]] || fail "Codex home does not exist"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

ensure_port_is_free() {
    local name="$1"
    local port="$2"
    local pids
    pids="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true)"
    [[ -z "$pids" ]] || fail "$name port $port is already in use by PID(s): $(tr '\n' ' ' <<<"$pids")"
}

validate_private_server_config
validate_isolated_data_source
validate_codex_home
validate_port "backend port" "$BACKEND_PORT"
validate_port "agent port" "$AGENT_PORT"
validate_port "rank port" "$RANK_PORT"
validate_port "web port" "$WEB_PORT"
validate_run_dir

[[ "$BACKEND_PORT" != "$AGENT_PORT" && "$BACKEND_PORT" != "$RANK_PORT" && "$BACKEND_PORT" != "$WEB_PORT" ]] \
    || fail "stack ports must be distinct"
[[ "$AGENT_PORT" != "$RANK_PORT" && "$AGENT_PORT" != "$WEB_PORT" && "$RANK_PORT" != "$WEB_PORT" ]] \
    || fail "stack ports must be distinct"

require_command lsof
require_command curl
require_command java
require_command setsid
require_command "$CODEX_BIN"
[[ -x "$ROOT_DIR/zhiyuan-agent/.venv/bin/uvicorn" ]] || fail "Agent virtual environment is unavailable"
[[ -x "$ROOT_DIR/zhiyuan-rank/.venv/bin/gunicorn" ]] || fail "Rank virtual environment is unavailable"

if [[ "$SKIP_BUILD" == true ]]; then
    [[ -f "$ROOT_DIR/zhiyuan-server/target/zhiyuan-server.jar" ]] || fail \
        "backend jar is unavailable; omit --skip-build or build zhiyuan-server first"
else
    require_command mvn
fi

if [[ "$SKIP_WEB" == false ]]; then
    [[ -x "$ROOT_DIR/zhiyuan-web/node_modules/.bin/next" ]] || fail "Web dependencies are unavailable"
fi

ensure_port_is_free "backend" "$BACKEND_PORT"
ensure_port_is_free "agent" "$AGENT_PORT"
ensure_port_is_free "rank" "$RANK_PORT"
if [[ "$SKIP_WEB" == false ]]; then
    ensure_port_is_free "web" "$WEB_PORT"
fi

printf 'codex-local preflight passed: backend=%s agent=%s rank=%s' \
    "$BACKEND_PORT" "$AGENT_PORT" "$RANK_PORT"
if [[ "$SKIP_WEB" == false ]]; then
    printf ' web=%s' "$WEB_PORT"
fi
printf ' data-source=%s\n' "$DATA_SOURCE"
