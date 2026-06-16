#!/usr/bin/env bash
set -uo pipefail

MODE="local"
BASE_URL="${ZHIYUAN_HEALTH_BASE_URL:-}"
JSON=0
COMPOSE_FILE="${ZHIYUAN_COMPOSE_FILE:-docker-compose.yml}"
SERVER_SERVICE="${ZHIYUAN_SERVER_SERVICE:-zhiyuan-server.service}"
SERVER_PORT="${ZHIYUAN_SERVER_PORT:-8090}"
WEB_PORT="${ZHIYUAN_WEB_PORT:-3000}"
WEB_HEALTH_PATH="${ZHIYUAN_WEB_HEALTH_PATH:-/}"
AGENT_PORT="${ZHIYUAN_AGENT_PORT:-8000}"
RANK_PORT="${ZHIYUAN_RANK_PORT:-5001}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --local)
      MODE="local"
      ;;
    --remote)
      MODE="remote"
      shift
      BASE_URL="${1:-}"
      ;;
    --json)
      JSON=1
      ;;
    --help|-h)
      cat <<'USAGE'
Usage:
  bash ops/healthcheck.sh --local
  bash ops/healthcheck.sh --remote https://zhiyuan.ytell.cn
  bash ops/healthcheck.sh --json

Environment overrides:
  ZHIYUAN_COMPOSE_FILE, ZHIYUAN_SERVER_SERVICE, ZHIYUAN_SERVER_PORT,
  ZHIYUAN_WEB_PORT, ZHIYUAN_WEB_HEALTH_PATH,
  ZHIYUAN_AGENT_PORT, ZHIYUAN_RANK_PORT
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$MODE" = "remote" ] && [ -z "$BASE_URL" ]; then
  echo "--remote requires a base URL" >&2
  exit 2
fi

RESULTS=()
FAILURES=0
WARNINGS=0

record() {
  local name="$1"
  local status="$2"
  local detail="${3:-}"
  RESULTS+=("${name}|${status}|${detail}")
  case "$status" in
    FAIL) FAILURES=$((FAILURES + 1)) ;;
    WARN|SKIP) WARNINGS=$((WARNINGS + 1)) ;;
  esac
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run_check() {
  local name="$1"
  shift
  local output
  if output="$("$@" 2>&1)"; then
    record "$name" "PASS" "$(printf '%s' "$output" | tail -1)"
  else
    record "$name" "FAIL" "$(printf '%s' "$output" | tail -1)"
  fi
}

http_check() {
  local name="$1"
  local url="$2"
  if have curl; then
    run_check "$name" curl -fsS -m 8 -o /dev/null "$url"
  else
    record "$name" "SKIP" "curl not found"
  fi
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif have docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    return 127
  fi
}

check_local_processes() {
  if have docker; then
    local output
    if output="$(compose_cmd ps zhiyuan-web zhiyuan-agent zhiyuan-rank 2>&1)"; then
      record "compose ps" "PASS" "$(printf '%s' "$output" | tail -1)"
    else
      record "compose ps" "WARN" "$(printf '%s' "$output" | tail -1)"
    fi
  else
    record "compose ps" "SKIP" "docker not found"
  fi

  if have systemctl; then
    run_check "systemd server" systemctl is-active "$SERVER_SERVICE"
    if have nginx; then
      run_check "nginx config" nginx -t
    else
      record "nginx config" "SKIP" "nginx not found"
    fi
  else
    record "systemd server" "SKIP" "systemctl not found"
    record "nginx config" "SKIP" "systemctl not found"
  fi
}

check_local_http() {
  http_check "web local" "http://127.0.0.1:${WEB_PORT}${WEB_HEALTH_PATH}"
  http_check "server local" "http://127.0.0.1:${SERVER_PORT}/gaotu-assistant-bot/inner/ops/health"
  http_check "server local data" "http://127.0.0.1:${SERVER_PORT}/gaotu-assistant-bot/base-data/province-city"
  http_check "agent local" "http://127.0.0.1:${AGENT_PORT}/health"
  http_check "rank local" "http://127.0.0.1:${RANK_PORT}/health"
}

check_remote_http() {
  local base="${BASE_URL%/}"
  http_check "web remote" "${base}/assistant-pc/customer"
  http_check "web v2 remote" "${base}/assistant-pc/sessionDetailV2"
  http_check "server remote" "${base}/gaotu-assistant-bot/inner/ops/health"
  http_check "server remote data" "${base}/gaotu-assistant-bot/base-data/province-city"
  http_check "agent remote" "${base}/gaotu-assistant-agent/health"
  http_check "rank remote" "${base}/gaokao-volunteer-rank/recommend"
}

check_disk() {
  if have df; then
    run_check "disk" df -h .
  else
    record "disk" "SKIP" "df not found"
  fi
}

json_string() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

if [ "$MODE" = "local" ]; then
  check_local_processes
  check_local_http
else
  check_remote_http
fi
check_disk

if [ "$JSON" -eq 1 ]; then
  printf '{"status":"%s","failures":%s,"warnings":%s,"checks":[' \
    "$([ "$FAILURES" -eq 0 ] && printf UP || printf DOWN)" "$FAILURES" "$WARNINGS"
  first=1
  for item in "${RESULTS[@]}"; do
    IFS='|' read -r name status detail <<EOF
$item
EOF
    [ "$first" -eq 1 ] || printf ','
    first=0
    printf '{"name":%s,"status":%s,"detail":%s}' \
      "$(printf '%s' "$name" | json_string)" \
      "$(printf '%s' "$status" | json_string)" \
      "$(printf '%s' "$detail" | json_string)"
  done
  printf ']}\n'
else
  echo "Zhiyuan healthcheck (${MODE})"
  echo "=========================="
  for item in "${RESULTS[@]}"; do
    IFS='|' read -r name status detail <<EOF
$item
EOF
    printf '%-22s %-5s %s\n' "$name" "$status" "$detail"
  done
  echo ""
  echo "failures=${FAILURES} warnings=${WARNINGS}"
fi

[ "$FAILURES" -eq 0 ]
