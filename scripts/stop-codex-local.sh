#!/usr/bin/env bash
# Stop only processes recorded by start-codex-local.sh for one isolated run.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

usage() {
    cat <<'EOF'
Usage: bash scripts/stop-codex-local.sh RUN_DIRECTORY

Stops only PIDs created by scripts/start-codex-local.sh. The run directory must
be below .runtime/codex-local-*. Existing listeners that are not recorded in
that directory are never adopted or stopped.
EOF
}

fail() {
    printf 'codex-local stop failed: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 1 ]] || { usage >&2; exit 1; }
[[ "$1" != "-h" && "$1" != "--help" ]] || { usage; exit 0; }

RUN_DIR="$1"
RUN_PARENT="$(dirname "$RUN_DIR")"
RUN_NAME="$(basename "$RUN_DIR")"
[[ "$RUN_PARENT" == "$ROOT_DIR/.runtime" && "$RUN_NAME" == codex-local-* ]] || \
    fail "run directory must be a direct child of $ROOT_DIR/.runtime/codex-local-*"
[[ -d "$RUN_DIR" ]] || fail "run directory does not exist"
RUN_DIR="$(cd "$RUN_DIR" && pwd -P)"
[[ "$(dirname "$RUN_DIR")" == "$ROOT_DIR/.runtime" && "$(basename "$RUN_DIR")" == codex-local-* ]] || \
    fail "run directory must resolve below $ROOT_DIR/.runtime/codex-local-*"

environment_matches_run() {
    local pid="$1"
    tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -Fqx "CODEX_LOCAL_RUN_DIR=$RUN_DIR"
}

stop_service() {
    local name="$1"
    local process_hint="$2"
    local pidfile="$RUN_DIR/pids/$name.pid"
    # 无 pid 文件 = 该服务不在本 run 内，跳过；**必须 return 0**——set -e 下裸 `return`
    # 会带上 `[[ ]]` 的 1，web 是首个调用点，整个停链就地中断（2026-10-07 H2 实测）。
    [[ -f "$pidfile" ]] || return 0

    local pid command_line
    pid="$(<"$pidfile")"
    [[ "$pid" =~ ^[0-9]+$ ]] || { printf 'skip %s: invalid PID record\n' "$name" >&2; return; }
    kill -0 "$pid" 2>/dev/null || { printf 'skip %s: PID %s is not running\n' "$name" "$pid"; return; }
    command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if [[ "$command_line" != *"$ROOT_DIR"* || "$command_line" != *"$process_hint"* ]]; then
        printf 'skip %s: PID %s does not match this run\n' "$name" "$pid" >&2
        return
    fi
    if ! environment_matches_run "$pid"; then
        printf 'skip %s: PID %s does not carry this run marker\n' "$name" "$pid" >&2
        return
    fi

    kill -TERM "$pid" 2>/dev/null || true
    local attempt
    for attempt in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
    printf 'stopped %s (PID %s)\n' "$name" "$pid"
}

stop_service "web" "next"
stop_service "agent" "uvicorn"
stop_service "backend" "zhiyuan-server.jar"
stop_service "rank" "gunicorn"
