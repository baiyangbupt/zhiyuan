#!/usr/bin/env bash
set -uo pipefail

MODE="local"
BASE_URL="${ZHIYUAN_SMOKE_BASE_URL:-}"
JSON=0
TENANT_ID="${ZHIYUAN_TENANT_ID:-1}"
BOT_ID="${ZHIYUAN_BOT_ID:-1}"
SESSION_ID="${ZHIYUAN_SESSION_ID:-}"
SERVER_PORT="${ZHIYUAN_SERVER_PORT:-18090}"
WEB_PORT="${ZHIYUAN_WEB_PORT:-3001}"
WEB_BASE_PATH="${ZHIYUAN_WEB_BASE_PATH-/assistant-pc}"
AGENT_PORT="${ZHIYUAN_AGENT_PORT:-18091}"
RANK_PORT="${ZHIYUAN_RANK_PORT:-18092}"
RANK_URL="${ZHIYUAN_RANK_URL:-}"
PYTHON_BIN="${ZHIYUAN_PYTHON:-python3}"
WEBSOCKET_MODE="${ZHIYUAN_SMOKE_WEBSOCKET:-auto}"
TIMEOUT_SECONDS="${ZHIYUAN_SMOKE_TIMEOUT_SECONDS:-10}"

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
    --tenant-id)
      shift
      TENANT_ID="${1:-}"
      ;;
    --bot-id)
      shift
      BOT_ID="${1:-}"
      ;;
    --session-id)
      shift
      SESSION_ID="${1:-}"
      ;;
    --rank-url)
      shift
      RANK_URL="${1:-}"
      ;;
    --websocket)
      WEBSOCKET_MODE="on"
      ;;
    --no-websocket)
      WEBSOCKET_MODE="off"
      ;;
    --help|-h)
      cat <<'USAGE'
Usage:
  bash ops/release-smoke.sh --local
  bash ops/release-smoke.sh --local --session-id 120 --websocket
  bash ops/release-smoke.sh --remote https://test-www.gaotuzhiyuan.com --session-id 120
  bash ops/release-smoke.sh --json

Environment overrides:
  ZHIYUAN_SERVER_PORT=18090
  ZHIYUAN_WEB_PORT=3001
  ZHIYUAN_WEB_BASE_PATH=/assistant-pc (set empty for local dev)
  ZHIYUAN_AGENT_PORT=18091
  ZHIYUAN_RANK_PORT=18092
  ZHIYUAN_TENANT_ID=1
  ZHIYUAN_BOT_ID=1
  ZHIYUAN_SESSION_ID=<optional existing session id>
  ZHIYUAN_RANK_URL=<optional rank health URL for remote smoke>
  ZHIYUAN_PYTHON=<python with websockets installed if --websocket is used>
  ZHIYUAN_SMOKE_WEBSOCKET=auto|on|off
  INTERNAL_SERVICE_TOKEN=<required runtime credential for backend internal checks>

Default checks are read-only and do not create sessions or mutate planning state.
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

if [ -n "$WEB_BASE_PATH" ]; then
  case "$WEB_BASE_PATH" in
    /*) ;;
    *) WEB_BASE_PATH="/${WEB_BASE_PATH}" ;;
  esac
  WEB_BASE_PATH="${WEB_BASE_PATH%/}"
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

curl_check() {
  local name="$1"
  local url="$2"
  local expected="${3:-}"
  local scope="${4:-public}"
  if [ "$scope" = "internal" ]; then
    local token="${INTERNAL_SERVICE_TOKEN:-}"
    if [[ -z "${token//[[:space:]]/}" || "$token" == *$'\r'* || "$token" == *$'\n'* ]]; then
      record "$name" "FAIL" "INTERNAL_SERVICE_TOKEN must be a nonempty single-line credential"
      return
    fi
  fi
  if ! have curl; then
    record "$name" "SKIP" "curl not found"
    return
  fi

  if [ "$scope" = "internal" ]; then
    local escaped_token="${token//\\/\\\\}"
    escaped_token="${escaped_token//\"/\\\"}"
    local response
    if ! response="$(printf 'header = "X-Internal-Service-Token: %s"\n' "$escaped_token" | curl -q --config - --proto '=http,https' -sS -m "$TIMEOUT_SECONDS" -w $'\n%{http_code}' "$url" 2>/dev/null)"; then
      record "$name" "FAIL" "authenticated HTTP probe failed"
      return
    fi
    local internal_http_code="${response##*$'\n'}"
    if ! [[ "$internal_http_code" =~ ^2[0-9][0-9]$ ]]; then
      record "$name" "FAIL" "authenticated probe requires HTTP 2xx"
      return
    fi
    if [ -n "$expected" ] && ! printf '%s' "${response%$'\n'*}" | grep "$expected" >/dev/null; then
      record "$name" "FAIL" "HTTP ${internal_http_code}, expected '${expected}' not found"
      return
    fi
    record "$name" "PASS" "HTTP ${internal_http_code}"
    return
  fi

  local body_file
  body_file="$(mktemp)"
  local http_code
  http_code="$(curl -k -L -sS -m "$TIMEOUT_SECONDS" -w '%{http_code}' -o "$body_file" "$url" 2>"${body_file}.err")"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    record "$name" "FAIL" "$(tail -1 "${body_file}.err")"
    rm -f "$body_file" "${body_file}.err"
    return
  fi
  if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 400 ]; then
    record "$name" "FAIL" "HTTP ${http_code}"
    rm -f "$body_file" "${body_file}.err"
    return
  fi
  if [ -n "$expected" ] && ! grep -q "$expected" "$body_file"; then
    record "$name" "FAIL" "HTTP ${http_code}, expected '${expected}' not found"
    rm -f "$body_file" "${body_file}.err"
    return
  fi
  record "$name" "PASS" "HTTP ${http_code}"
  rm -f "$body_file" "${body_file}.err"
}

file_contains_check() {
  local name="$1"
  local path="$2"
  local expected="$3"
  if [ ! -f "$path" ]; then
    record "$name" "WARN" "${path} not found"
    return
  fi
  if grep -q "$expected" "$path"; then
    record "$name" "PASS" "$path"
  else
    record "$name" "FAIL" "expected '${expected}' not found in ${path}"
  fi
}

websocket_url_from_base() {
  local base="$1"
  case "$base" in
    https://*) printf 'wss://%s' "${base#https://}" ;;
    http://*) printf 'ws://%s' "${base#http://}" ;;
    *) printf '%s' "$base" ;;
  esac
}

websocket_check() {
  local name="$1"
  local url="$2"
  if [ "$WEBSOCKET_MODE" = "off" ]; then
    record "$name" "SKIP" "websocket smoke disabled"
    return
  fi
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    if [ "$WEBSOCKET_MODE" = "on" ]; then
      record "$name" "FAIL" "${PYTHON_BIN} not found"
    else
      record "$name" "WARN" "${PYTHON_BIN} not found"
    fi
    return
  fi
  if ! "$PYTHON_BIN" -c 'import websockets' >/dev/null 2>&1; then
    if [ "$WEBSOCKET_MODE" = "on" ]; then
      record "$name" "FAIL" "python package websockets not found"
    else
      record "$name" "WARN" "python package websockets not found"
    fi
    return
  fi

  local output
  if output="$(SMOKE_WS_URL="$url" "$PYTHON_BIN" - <<'PY' 2>&1
import asyncio
import os
import websockets

async def main() -> None:
    async with websockets.connect(
        os.environ["SMOKE_WS_URL"],
        open_timeout=8,
        close_timeout=2,
    ) as ws:
        await ws.close()

asyncio.run(main())
print("connected")
PY
)"; then
    record "$name" "PASS" "$(printf '%s' "$output" | tail -1)"
  else
    record "$name" "FAIL" "$(printf '%s' "$output" | tail -1)"
  fi
}

json_string() {
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    "$PYTHON_BIN" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
  else
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
  fi
}

if [ "$MODE" = "local" ]; then
  WEB_BASE="http://127.0.0.1:${WEB_PORT}"
  SERVER_BASE="http://127.0.0.1:${SERVER_PORT}"
  AGENT_BASE="http://127.0.0.1:${AGENT_PORT}"
  [ -n "$RANK_URL" ] || RANK_URL="http://127.0.0.1:${RANK_PORT}/health"
  WS_BASE="ws://127.0.0.1:${AGENT_PORT}"
else
  BASE_URL="${BASE_URL%/}"
  WEB_BASE="$BASE_URL"
  SERVER_BASE="$BASE_URL"
  AGENT_BASE="$BASE_URL"
  WS_BASE="$(websocket_url_from_base "$BASE_URL")"
fi

curl_check "web session page" "${WEB_BASE}${WEB_BASE_PATH}/session" "__NEXT_DATA__"
curl_check "web detail page" "${WEB_BASE}${WEB_BASE_PATH}/sessionDetailV2" "__NEXT_DATA__"
if [ "$MODE" = "local" ]; then
  if [ -n "$WEB_BASE_PATH" ]; then
    file_contains_check "web basePath manifest" "zhiyuan-web/.next/routes-manifest.json" "\"${WEB_BASE_PATH}\""
  else
    record "web basePath manifest" "PASS" "development basePath disabled"
  fi
fi

curl_check "server health" "${SERVER_BASE}/gaotu-assistant-bot/inner/ops/health" '"status"' internal
curl_check "server base data" "${SERVER_BASE}/gaotu-assistant-bot/base-data/province-city" '"data"'
curl_check "server review rules" "${SERVER_BASE}/gaotu-assistant-bot/inner/planning/${TENANT_ID}/review/rules" '"data"' internal

curl_check "agent health" "${AGENT_BASE}/gaotu-assistant-agent/health" '"status"'
websocket_check "agent websocket" "${WS_BASE}/gaotu-assistant-agent/plus/chat/${TENANT_ID}/bot/${BOT_ID}/do"

if [ -n "$RANK_URL" ]; then
  curl_check "rank health" "$RANK_URL" '"status"'
elif [ "$MODE" = "remote" ]; then
  record "rank health" "SKIP" "set ZHIYUAN_RANK_URL or --rank-url for remote rank smoke"
fi

if [ -n "$SESSION_ID" ]; then
  curl_check "workspace state" "${SERVER_BASE}/gaotu-assistant-bot/inner/planning/${TENANT_ID}/session/workspace-state?chatSessionId=${SESSION_ID}" '"data"' internal
  curl_check "data freshness" "${SERVER_BASE}/gaotu-assistant-bot/inner/planning/${TENANT_ID}/session/data-freshness?chatSessionId=${SESSION_ID}" '"data"' internal
  curl_check "freshness schedule" "${SERVER_BASE}/gaotu-assistant-bot/inner/planning/${TENANT_ID}/session/data-freshness/schedule?chatSessionId=${SESSION_ID}" '"data"' internal
else
  record "workspace state" "SKIP" "set --session-id to validate workspace/data-freshness read APIs"
fi

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
  echo "Zhiyuan release smoke (${MODE})"
  echo "=============================="
  for item in "${RESULTS[@]}"; do
    IFS='|' read -r name status detail <<EOF
$item
EOF
    printf '%-24s %-5s %s\n' "$name" "$status" "$detail"
  done
  echo ""
  echo "failures=${FAILURES} warnings=${WARNINGS}"
fi

[ "$FAILURES" -eq 0 ]
