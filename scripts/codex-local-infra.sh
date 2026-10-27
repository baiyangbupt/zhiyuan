#!/usr/bin/env bash
# Manage the disposable MySQL/Redis foundation for the Codex local stack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.codex-local.yml"
PROJECT_NAME="${CODEX_LOCAL_COMPOSE_PROJECT:-zhiyuan-codex-local}"
STATE_DIR="${CODEX_LOCAL_INFRA_DIR:-$ROOT_DIR/.local/codex-local}"
ENV_FILE="$STATE_DIR/infra.env"
SERVER_CONFIG="$STATE_DIR/application-codex-local.yml"
MYSQL_PORT="${CODEX_LOCAL_MYSQL_PORT:-13306}"
REDIS_PORT="${CODEX_LOCAL_REDIS_PORT:-16379}"
MYSQL_DATABASE="${CODEX_LOCAL_MYSQL_DATABASE:-zhiyuan_codex_local}"
PREPARE_TYPE_FALLBACK="${CODEX_LOCAL_PREPARE_TYPE_FALLBACK-PREDICT}"

usage() {
    cat <<'EOF'
Usage: bash scripts/codex-local-infra.sh COMMAND

Commands:
  start   Start the isolated MySQL/Redis containers and write Spring config.
  stop    Stop the containers while retaining their dedicated volumes.
  status  Show container status for this Compose project.
  reset   Stop containers and delete only the dedicated Codex local volumes.

Environment:
  CODEX_LOCAL_INFRA_DIR       Private state directory (default: .local/codex-local).
  CODEX_LOCAL_COMPOSE_PROJECT Compose project name (default: zhiyuan-codex-local).
  CODEX_LOCAL_MYSQL_PORT      Host MySQL port (default: 13306).
  CODEX_LOCAL_REDIS_PORT      Host Redis port (default: 16379).
  CODEX_LOCAL_PREPARE_TYPE_FALLBACK  Demo data mode (default: PREDICT; empty disables).
EOF
}

fail() {
    printf 'codex-local infra failed: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 1 ]] || { usage >&2; exit 1; }
COMMAND="$1"
[[ "$COMMAND" == "-h" || "$COMMAND" == "--help" ]] && { usage; exit 0; }
case "$COMMAND" in
    start|stop|status|reset) ;;
    *) fail "unknown command: $COMMAND" ;;
esac

case "$PREPARE_TYPE_FALLBACK" in
    ""|PREDICT|VOLUNTEER) ;;
    *) fail "CODEX_LOCAL_PREPARE_TYPE_FALLBACK must be PREDICT, VOLUNTEER, or empty" ;;
esac

command -v docker >/dev/null 2>&1 || fail "required command is unavailable: docker"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file does not exist: $COMPOSE_FILE"

compose() {
    docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" \
        --file "$COMPOSE_FILE" "$@"
}

ensure_state_dir() {
    [[ "$STATE_DIR" = /* ]] || fail "CODEX_LOCAL_INFRA_DIR must be an absolute path"
    umask 077
    mkdir -p "$STATE_DIR"
}

ensure_env_file() {
    ensure_state_dir
    if [[ ! -f "$ENV_FILE" ]]; then
        command -v openssl >/dev/null 2>&1 || fail "openssl is required to create the private database password"
        local password
        password="$(openssl rand -hex 24)"
        cat > "$ENV_FILE" <<EOF
MYSQL_ROOT_PASSWORD=$password
MYSQL_DATABASE=$MYSQL_DATABASE
MYSQL_PORT=$MYSQL_PORT
REDIS_PORT=$REDIS_PORT
EOF
    fi
    [[ -r "$ENV_FILE" ]] || fail "cannot read private environment file: $ENV_FILE"
    grep -q '^MYSQL_ROOT_PASSWORD=[^[:space:]]\+$' "$ENV_FILE" || \
        fail "private environment file has no valid MYSQL_ROOT_PASSWORD"
}

write_server_config() {
    local password database mysql_port redis_port
    password="$(sed -n 's/^MYSQL_ROOT_PASSWORD=//p' "$ENV_FILE" | head -n 1)"
    database="$(sed -n 's/^MYSQL_DATABASE=//p' "$ENV_FILE" | head -n 1)"
    mysql_port="$(sed -n 's/^MYSQL_PORT=//p' "$ENV_FILE" | head -n 1)"
    redis_port="$(sed -n 's/^REDIS_PORT=//p' "$ENV_FILE" | head -n 1)"
    [[ -n "$password" && -n "$database" && -n "$mysql_port" && -n "$redis_port" ]] || \
        fail "private environment file is missing generated connection settings"

    cat > "$SERVER_CONFIG" <<EOF
spring:
  application:
    name: zhiyuan-server-codex-local
  profiles:
    active: localtest
  datasource:
    dynamic:
      datasource:
        master:
          driver-class-name: com.mysql.cj.jdbc.Driver
          username: root
          password: $password
          url: jdbc:mysql://127.0.0.1:$mysql_port/$database?useUnicode=true&useSSL=false&characterEncoding=utf8&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true
  redis:
    host: 127.0.0.1
    port: $redis_port
    database: 0
    timeout: 2000

agent:
  zhiyuan:
    url: http://127.0.0.1:18291
demo:
  prepare-type-fallback: "$PREPARE_TYPE_FALLBACK"
volunteer:
  rank:
    url: http://127.0.0.1:18292
    env: local

gaotu:
  zhiyuan:
    evn: codex-local
    zhiyuan-url: https://127.0.0.1.invalid
    program-data-url: https://127.0.0.1.invalid
    user-url: https://127.0.0.1.invalid
    risk-url: https://127.0.0.1.invalid
    risk-open: false
    auth-open: false
    temp-data-path: $STATE_DIR/tmp

ali:
  oss:
    endpoint: https://oss-cn-beijing.aliyuncs.com
    region: cn-beijing
    bucket: codex-local-disabled
    accessKeyId: codex-local-disabled
    accessKeySecret: codex-local-disabled
  sms:
    endpoint: dysmsapi.aliyuncs.com
    accessKeyId: codex-local-disabled
    accessKeySecret: codex-local-disabled
    signName: codex-local-disabled
    template: codex-local-disabled

wx:
  miniapp:
    configs: []

planning:
  pending-command:
    retention:
      enabled: false
  data-freshness:
    schedule:
      enabled: false
EOF
    chmod 600 "$SERVER_CONFIG"
}

case "$COMMAND" in
    start)
        ensure_env_file
        write_server_config
        compose up -d --wait --wait-timeout 180
        printf 'codex-local infra is ready\n'
        printf '  MySQL: 127.0.0.1:%s\n' "$(sed -n 's/^MYSQL_PORT=//p' "$ENV_FILE" | head -n 1)"
        printf '  Redis:  127.0.0.1:%s\n' "$(sed -n 's/^REDIS_PORT=//p' "$ENV_FILE" | head -n 1)"
        printf '  Config: %s\n' "$SERVER_CONFIG"
        ;;
    stop)
        ensure_env_file
        compose stop
        ;;
    status)
        ensure_env_file
        compose ps
        ;;
    reset)
        ensure_env_file
        compose down --volumes --remove-orphans
        rm -f "$ENV_FILE" "$SERVER_CONFIG"
        rm -rf "$STATE_DIR/tmp"
        printf 'codex-local infra reset complete\n'
        ;;
esac
