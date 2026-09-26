#!/usr/bin/env bash
# 隔离栈的**访问面**口径（Task C2）：本地模式 vs 公开测试模式的 URL 生成与守卫。
#
# 为什么单独一份：`start-codex-local.sh`（真正用这些值起 Web ✓）与
# `preflight-codex-local.sh`（启动前拦错配置 ✓）**必须是同一套判据** ✓——
# 两处各写一份，早晚会出现"预检放行、启动拒绝"这种自相矛盾 ✗
# （区域匹配那轮就是这么踩的 ✗）。
#
# 用法：`source scripts/codex-local-access.sh`
#
# 口径（任务书 Task C2）：
#   local       —— WS 用显式 loopback override ✓；outer 默认生产源（保持既有行为 ✓）。
#   public-test —— **清空 WS override** ✓（同源由 `window.location` 派生 ✓）；
#                  outer 必须是**显式配置的受控测试源** ✓（不许回落到生产默认 ✗，
#                  也不许指向 origin 自己 ✗）。
#
# 对外提供：
#   codex_local_access_resolve   → 设置 ACCESS_MODE / ACCESS_WS_OVERRIDE /
#                                  ACCESS_OUTER_API_BASE_URL（无效则 fail ✓）
#   codex_local_access_print     → 打印上面三个值（`--print-access-env` 用 ✓）

# 默认生产 outer：**只在 local 模式下**当默认值用 ✓。
CODEX_LOCAL_DEFAULT_OUTER_API_BASE_URL="${CODEX_LOCAL_DEFAULT_OUTER_API_BASE_URL:-https://www.gaotuzhiyuan.com}"

_codex_local_access_fail() {
    printf 'codex-local start failed: %s\n' "$*" >&2
    exit 1
}

# origin 只允许 `https://<host>[:port]` ✓：带路径 ✗／带凭证 ✗ 一律拒。
_codex_local_access_validate_origin() {
    local origin="$1"
    [[ -n "$origin" ]] || _codex_local_access_fail "public origin is required in public-test mode"
    [[ "$origin" == https://* ]] || _codex_local_access_fail "public origin must use https: $origin"
    local host_part="${origin#https://}"
    [[ -n "$host_part" ]] || _codex_local_access_fail "public origin is missing a host: $origin"
    [[ "$host_part" != *"/"* ]] || _codex_local_access_fail "public origin must not carry a path: $origin"
    [[ "$host_part" != *"@"* ]] || _codex_local_access_fail "public origin must not carry credentials: $origin"
}

codex_local_access_resolve() {
    ACCESS_MODE="${CODEX_LOCAL_ACCESS_MODE:-local}"
    local public_origin="${CODEX_LOCAL_PUBLIC_ORIGIN:-}"
    local configured_outer="${CODEX_LOCAL_OUTER_API_BASE_URL:-}"
    local agent_port="${1:-18291}"
    local web_port="${2:-3201}"

    case "$ACCESS_MODE" in
        local)
            ACCESS_WS_OVERRIDE="ws://127.0.0.1:$agent_port"
            ACCESS_ALLOWED_ORIGINS="http://127.0.0.1:$web_port,http://localhost:$web_port"
            ACCESS_OUTER_API_BASE_URL="${configured_outer:-$CODEX_LOCAL_DEFAULT_OUTER_API_BASE_URL}"
            ;;
        public-test)
            _codex_local_access_validate_origin "$public_origin"
            # Agent 的 Origin 白名单：公开 origin **必须**在里面 ✓（否则真浏览器连不上 ✗），
            # 回环也留着 ✓（本机自测与冒烟要走 ✓）。
            ACCESS_ALLOWED_ORIGINS="$public_origin,http://127.0.0.1:$web_port,http://localhost:$web_port"
            # 公开模式**必须显式给 outer** ✗：不显式就会悄悄回落到生产源 ✗，
            # 而这一模式的全部意义就是"只连受控测试源" ✓。
            [[ -n "$configured_outer" ]] || _codex_local_access_fail \
                "public-test mode requires an explicit CODEX_LOCAL_OUTER_API_BASE_URL (refusing the default production outer)"
            [[ "$configured_outer" != "${public_origin%/}" ]] || _codex_local_access_fail \
                "outer API base must not point at the public origin itself: $configured_outer"
            # 清空 override ✓：让浏览器按 `window.location` 派生同源 wss ✓。
            ACCESS_WS_OVERRIDE=""
            ACCESS_OUTER_API_BASE_URL="$configured_outer"
            ;;
        *)
            _codex_local_access_fail "unknown CODEX_LOCAL_ACCESS_MODE: $ACCESS_MODE (want local|public-test)"
            ;;
    esac
}

codex_local_access_print() {
    printf 'CODEX_LOCAL_ACCESS_MODE=%s\n' "$ACCESS_MODE"
    printf 'NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE="%s"\n' "$ACCESS_WS_OVERRIDE"
    printf 'NEXT_PUBLIC_OUTER_API_BASE_URL=%s\n' "$ACCESS_OUTER_API_BASE_URL"
    # 模式也下发到 Web ✓：公开测试模式下浏览器要**忽略**任何显式 base ✗、按同源派生 ✓。
    printf 'NEXT_PUBLIC_CODEX_ACCESS_MODE=%s\n' "$ACCESS_MODE"
    printf 'CODEX_WS_ALLOWED_ORIGINS=%s\n' "$ACCESS_ALLOWED_ORIGINS"
}
