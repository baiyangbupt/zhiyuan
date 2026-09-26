#!/usr/bin/env bash
# 公开测试域的冒烟（Task C2）：页面 ✓、静态资源 ✓、内网路径**必须拒绝** ✓、
# 带合法票据的 WebSocket 必须升级到 101 ✓。
#
# 为什么不复用旧的固定 test-www / assistant-pc 冒烟 ✗：那些脚本把域名与路径写死了 ✗，
# 换个 origin/前缀就得改脚本 ✓——这里两个都做成参数 ✓。
#
# 用法：
#   bash scripts/smoke-codex-public.sh --origin https://test-wwww.gaotuzhiyuan.com [--base-path /]
#
# 凭证（可选，给了才跑升级检查 ✓）：
#   CODEX_SMOKE_TICKET=<一次性 WS 票据>   CODEX_SMOKE_COOKIE='<cookie 头>'
# 没给就只跑匿名检查 ✓，并在结论里写 `authenticated=not_run` ✓——**不假装通过** ✗。
set -euo pipefail

ORIGIN="${CODEX_SMOKE_ORIGIN:-}"
BASE_PATH="/"
TICKET="${CODEX_SMOKE_TICKET:-}"
COOKIE="${CODEX_SMOKE_COOKIE:-}"

usage() {
    cat <<'EOF'
Usage: bash scripts/smoke-codex-public.sh --origin https://<host> [--base-path /]

Checks the public test origin: page, static assets, internal-path rejection,
and (with credentials) a WebSocket upgrade.

Env (optional):
  CODEX_SMOKE_TICKET   One-time WS ticket; enables the upgrade check.
  CODEX_SMOKE_COOKIE   Cookie header sent with requests.
EOF
}

fail() {
    printf 'codex-public smoke failed: %s\n' "$*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --origin)
            [[ -n "${2:-}" ]] || fail "--origin requires a value"
            ORIGIN="$2"; shift 2 ;;
        --base-path)
            [[ -n "${2:-}" ]] || fail "--base-path requires a value"
            BASE_PATH="$2"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            fail "unknown option: $1" ;;
    esac
done

[[ -n "$ORIGIN" ]] || fail "--origin is required (or set CODEX_SMOKE_ORIGIN)"
[[ "$ORIGIN" == https://* ]] || fail "--origin must be https: $ORIGIN"
[[ "$ORIGIN" != */* ]] || fail "--origin must not carry a path: $ORIGIN"
[[ "$BASE_PATH" == /* ]] || fail "--base-path must start with /: $BASE_PATH"
BASE_PATH="${BASE_PATH%/}"

CURL_ARGS=(-sS -m 20 -o /dev/null -w '%{http_code}')
[[ -n "$COOKIE" ]] && CURL_ARGS+=(-H "Cookie: $COOKIE")

failures=0
check_status() {
    local label="$1" expected="$2" url="$3"
    local actual
    actual="$(curl "${CURL_ARGS[@]}" "$url" || echo 000)"
    if [[ "$actual" == "$expected" ]]; then
        printf '  ✓ %s -> %s（期望 %s）\n' "$label" "$actual" "$expected"
    else
        printf '  ✗ %s -> %s（期望 %s）\n' "$label" "$actual" "$expected" >&2
        failures=$((failures + 1))
    fi
}

printf '公开测试域冒烟：%s%s\n' "$ORIGIN" "$BASE_PATH"

# 1) 页面与静态资源 ✓
check_status '页面' 200 "$ORIGIN$BASE_PATH/"
check_status '首页静态资源' 200 "$ORIGIN$BASE_PATH/_next/static/"

# 2) 内网面**必须拒绝** ✓（放行了就是事故 ✗）
check_status '内网 planning 路径应拒绝' 404 "$ORIGIN$BASE_PATH/gaotu-assistant-bot/inner/planning/1/session/state"
check_status '内网 evidence 路径应拒绝' 404 "$ORIGIN$BASE_PATH/internal/evidence/"

# 3) 带票据的升级检查 ✓（没凭证就如实记 not_run ✓）
if [[ -n "$TICKET" ]]; then
    code="$(curl -sS -m 20 -o /dev/null -w '%{http_code}' \
        -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
        -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
        ${COOKIE:+-H "Cookie: $COOKIE"} \
        "$ORIGIN$BASE_PATH/ws/chat?ticket=$TICKET" || echo 000)"
    if [[ "$code" == "101" ]]; then
        printf '  ✓ WebSocket 升级 -> 101（ticket 合法）\n'
    else
        printf '  ✗ WebSocket 升级 -> %s（期望 101）\n' "$code" >&2
        failures=$((failures + 1))
    fi
    printf 'authenticated=run\n'
else
    printf '  ⃝ 升级检查跳过：没有票据（CODEX_SMOKE_TICKET）\n'
    printf 'authenticated=not_run\n'
fi

if [[ "$failures" -gt 0 ]]; then
    printf 'RESULT=FAIL failures=%d\n' "$failures"
    exit 1
fi
printf 'RESULT=PASS\n'
