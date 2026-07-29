#!/usr/bin/env bash
#
# Smoke check for the standard-test upstream routes.
# Defaults match the test-www route config:
#   /assistant-pc/        -> 127.0.0.1:3001
#   /gaotu-assistant-bot/ -> 127.0.0.1:18090
#   /gaotu-assistant-agent/plus/chat -> 127.0.0.1:18091
#
# Usage:
#   bash scripts/smoke-standardtest-web-proxy.sh
#   WEB_URL=https://test-www.gaotuzhiyuan.com bash scripts/smoke-standardtest-web-proxy.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="${WEB_DIR:-$ROOT_DIR/zhiyuan-web}"
WEB_URL="${WEB_URL:-https://test-www.gaotuzhiyuan.com}"
DIRECT_WEB_URL="${DIRECT_WEB_URL:-http://127.0.0.1:3001}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:18090}"
AGENT_URL="${AGENT_URL:-http://127.0.0.1:18091}"

failures=0
login_html=""
login_chunk=""

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  failures=$((failures + 1))
}

http_code() {
  local url=$1
  curl -sS -o /dev/null -w '%{http_code}' "$url"
}

expect_http_200() {
  local label=$1
  local url=$2
  local code
  if code=$(http_code "$url"); then
    if [ "$code" = "200" ]; then
      pass "$label -> 200"
    else
      fail "$label -> $code"
    fi
  else
    fail "$label -> curl failed"
  fi
}

fetch_login_html() {
  local url=$1
  local target
  target="$(mktemp)"
  if curl -sS -o "$target" "$url/assistant-pc/login?channel=gaotu"; then
    login_html="$target"
    pass "Fetch login HTML"
  else
    fail "Fetch login HTML"
  fi
}

extract_login_chunk() {
  if [ -z "$login_html" ] || [ ! -f "$login_html" ]; then
    fail "Extract login chunk -> missing login HTML"
    return
  fi
  login_chunk=$(grep -o '/assistant-pc/_next/static/chunks/pages/login-[^"]*\.js' "$login_html" | head -n 1 || true)
  if [ -n "$login_chunk" ]; then
    pass "Extract login chunk -> $login_chunk"
  else
    fail "Extract login chunk"
  fi
}

expect_manifest_target() {
  local label=$1
  local pattern=$2
  local manifest="$WEB_DIR/.next/routes-manifest.json"
  if [ ! -f "$manifest" ]; then
    fail "$label -> missing $manifest"
    return
  fi
  if grep -q "$pattern" "$manifest"; then
    pass "$label"
  else
    fail "$label -> pattern not found: $pattern"
  fi
}

printf 'Standard-test upstream smoke\n'
printf 'WEB_URL=%s\n' "$WEB_URL"
printf 'DIRECT_WEB_URL=%s\n' "$DIRECT_WEB_URL"
printf 'BACKEND_URL=%s\n' "$BACKEND_URL"
printf 'AGENT_URL=%s\n' "$AGENT_URL"
printf '\n'

expect_manifest_target \
  "Next rewrite points direct Web bot API to $BACKEND_URL" \
  "${BACKEND_URL//\//\\/}\\/gaotu-assistant-bot"
expect_manifest_target \
  "Next rewrite points direct Web agent API to $AGENT_URL" \
  "${AGENT_URL//\//\\/}\\/gaotu-assistant-agent"

fetch_login_html "$WEB_URL"
extract_login_chunk

expect_http_200 "Upstream Web login page" "$WEB_URL/assistant-pc/login?channel=gaotu"
if [ -n "$login_chunk" ]; then
  expect_http_200 "Upstream login chunk" "$WEB_URL$login_chunk"
fi
expect_http_200 "Upstream bot route" "$WEB_URL/gaotu-assistant-bot/base-data/province-city"
expect_http_200 "Upstream agent health route" "$WEB_URL/gaotu-assistant-agent/health"

expect_http_200 "Direct Web login page" "$DIRECT_WEB_URL/assistant-pc/login?channel=gaotu"
if [ -n "$login_chunk" ]; then
  expect_http_200 "Direct Web login chunk" "$DIRECT_WEB_URL$login_chunk"
fi
expect_http_200 "Direct Web bot rewrite" "$DIRECT_WEB_URL/gaotu-assistant-bot/base-data/province-city"
expect_http_200 "Direct Web agent rewrite" "$DIRECT_WEB_URL/gaotu-assistant-agent/health"
expect_http_200 "Direct backend" "$BACKEND_URL/gaotu-assistant-bot/base-data/province-city"
expect_http_200 "Direct agent" "$AGENT_URL/gaotu-assistant-agent/health"

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'Smoke passed.\n'
  exit 0
fi

printf 'Smoke failed: %s check(s) failed.\n' "$failures"
exit 1
