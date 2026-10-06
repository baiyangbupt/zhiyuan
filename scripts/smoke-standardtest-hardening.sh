#!/usr/bin/env bash
#
# test-www 加固验收烟测（2026-10-06，P0/P1）。
# 断言的是**加固之后**的目标状态；部署 ops/nginx/test-www.locations.conf 之前跑，
# 第 3、5 条会是红的 ✓——那正是当前的两处断点（匿名 inner 200 ✗、/ws/chat 404 ✗）。
#
# 用法：
#   bash scripts/smoke-standardtest-hardening.sh
#   WEB_URL=https://test-www.gaotuzhiyuan.com bash scripts/smoke-standardtest-hardening.sh
#
# 只读探针：不带任何凭证、不枚举会话（固定 chatSessionId=0，与复核文档同口径）。

set -uo pipefail

WEB_URL="${WEB_URL:-https://test-www.gaotuzhiyuan.com}"

failures=0

pass() { printf '[PASS] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failures=$((failures + 1)); }

# 断言 HTTP 状态码 + 可选 content-type 子串
expect_status() {
  local label=$1 url=$2 want=$3 want_type=${4:-}
  local out code ctype
  out=$(curl -sS -o /tmp/hardening_probe_body.$$ -w '%{http_code} %{content_type}' \
        --max-time 15 "$url" 2>/dev/null) || { fail "$label -> curl failed"; return; }
  code="${out%% *}"; ctype="${out#* }"
  if [ "$code" != "$want" ]; then
    fail "$label -> $code（期望 $want）"
    return
  fi
  if [ -n "$want_type" ] && [[ "$ctype" != *"$want_type"* ]]; then
    fail "$label -> $code 但 content-type=$ctype（期望含 $want_type）"
    return
  fi
  pass "$label -> $code${want_type:+ ($ctype)}"
}

echo "test-www hardening smoke"
echo "WEB_URL=$WEB_URL"
echo

# 1) 既有公开路由不回归 ✓
expect_status "web login page (no regression)" \
  "$WEB_URL/assistant-pc/login?channel=gaotu" 200 text/html
expect_status "public bot route (no regression)" \
  "$WEB_URL/gaotu-assistant-bot/base-data/province-city" 200 application/json
expect_status "agent health route (no regression)" \
  "$WEB_URL/gaotu-assistant-agent/health" 200

# 2) 取票端点的未登录语义不回归：真实 401 JSON ✓（端点只收 POST ✓）
ticket_out=$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' --max-time 15 \
  -X POST -H 'Content-Type: application/json' -d '{"sessionId":0,"botId":1}' \
  "$WEB_URL/gaotu-assistant-bot/chat/1/conversation/ws-ticket" 2>/dev/null) || ticket_out="000 "
if [[ "$ticket_out" == 401*application/json* ]]; then
  pass "ws-ticket without login -> 401 application/json"
else
  fail "ws-ticket without login -> $ticket_out（期望 401 application/json）"
fi

# 3) P0：匿名 inner 必须被拒 ✗→✓（部署前是 200 application/json）
expect_status "anonymous inner planning state (expect 404)" \
  "$WEB_URL/gaotu-assistant-bot/inner/planning/1/session/state?chatSessionId=0" 404
expect_status "anonymous internal evidence (expect 404)" \
  "$WEB_URL/internal/evidence/verify" 404

# 4) P1：/ws/chat 必须到达 Agent 验票路由 ✓
#    无票时 Agent 在 accept 前拒握手 → HTTP 403 text/plain ✓；
#    若仍是 404 text/html，说明 nginx 还没有 /ws/chat location（未部署 ✗）；
#    若 101，说明无票也能升级，属严重回归 ✗。
ws_probe() {
  curl -sS -o /tmp/hardening_ws_body.$$ -w '%{http_code} %{content_type}' --max-time 15 \
    -H "Connection: Upgrade" -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
    -H "Origin: $WEB_URL" \
    "$WEB_URL/ws/chat?chatSessionId=0" 2>/dev/null
}

ws_out=$(ws_probe) || ws_out="000 curl_failed"
ws_code="${ws_out%% *}"; ws_type="${ws_out##* }"
case "$ws_code" in
  403)
    if [[ "$ws_type" == *"text/plain"* ]]; then
      pass "ws/chat no-ticket upgrade -> 403 ($ws_type)（到达 Agent 验票）"
    else
      fail "ws/chat -> 403 但 content-type=$ws_type（期望 text/plain，疑似被别的 403 兜住）"
    fi
    ;;
  404)
    fail "ws/chat -> 404（nginx 尚无该 location，P1 未部署）"
    ;;
  101)
    fail "ws/chat -> 101（无票也能升级，验票被绕过）"
    ;;
  *)
    fail "ws/chat -> $ws_code $ws_type"
    ;;
esac

rm -f /tmp/hardening_probe_body.$$ /tmp/hardening_ws_body.$$

echo
if [ "$failures" -eq 0 ]; then
  echo "硬性加固验收通过。"
  exit 0
fi
echo "$failures 项未通过（部署前红 2 项为预期：anonymous inner 404 与 ws/chat 403）。"
exit 1
