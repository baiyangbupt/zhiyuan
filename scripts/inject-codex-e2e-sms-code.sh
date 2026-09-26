#!/usr/bin/env bash
# 给 e2e 用的登录验证码注入（Task C4 的登录态前置）。
#
# 为什么是脚本而不是在浏览器里"想办法" ✓：短信发不出去 ✗（本地栈用占位 AccessKey ✓，
# Java 日志里是 `code: 404, Specified access key is not found` ✓），所以验证码**只能手工塞** ✓。
# 而塞的地方是**本机 Redis** ✓（`127.0.0.1:16379` db 0 ✓——就是那套 compose 实例 ✓），
# 从容器里够不着 ✗（容器没有 docker 权限 ✓），所以注入必须在**宿主**做 ✓✓。
#
# 两个必须照抄的细节 ✓（记在 `zhiyuan-a6-testenv-login` ✓）：
#   1. **值要写成 JSON 串**（带引号 ✓）：`RedisConfig` 给 `StringRedisTemplate` 装的是
#      `Jackson2JsonRedisSerializer` ✓——写裸数字会被读成 Integer ✓，
#      `SmsService.verifyCode` 抛 `ClassCastException` ✓，前端只看到"系统错误" ✗。
#   2. key 是 `gaokao-assistant.sms_code:<mobile>` ✓，EX 7200 ✓。
#
# 用法：
#   bash scripts/inject-codex-e2e-sms-code.sh 13800000001 498921
#   bash scripts/inject-codex-e2e-sms-code.sh --probe 13800000001   # 只探活（用错码 ✓）
set -euo pipefail

REDIS_CONTAINER="${CODEX_E2E_REDIS_CONTAINER:-zhiyuan-codex-local-redis-1}"
REDIS_DB="${CODEX_E2E_REDIS_DB:-0}"
KEY_PREFIX="gaokao-assistant.sms_code:"

fail() { printf 'inject-sms-code: %s\n' "$*" >&2; exit 1; }

[[ $# -ge 1 ]] || fail "用法：$0 <mobile> [code]｜$0 --probe <mobile>"

if [[ "$1" == "--probe" ]]; then
    MOBILE="${2:-}"
    KEY="$KEY_PREFIX$MOBILE"
    # 错码探活 ✓（配方：**错码不消耗** ✓）：`verifyCode` 成功才 delete ✓。
    # 看点在于**返回措辞**：码在→"验证码错误" ✓；码不在→"验证码已过期" ✓；
    # 码在但格式不对→"系统错误" ✗（那正是把值写成裸数字的症状 ✓✓）。
    TTL="$(docker exec "$REDIS_CONTAINER" redis-cli -n "$REDIS_DB" TTL "$KEY" 2>/dev/null || echo -1)"
    RAW="$(docker exec "$REDIS_CONTAINER" redis-cli -n "$REDIS_DB" GET "$KEY" 2>/dev/null || echo '')"
    printf 'key=%s\nTTL=%s\n值前缀=%s\n' "$KEY" "$TTL" "${RAW:0:12}"
    if [[ "$RAW" == '"'*'"' ]]; then
        printf '✓ 值看起来是 **JSON 串**（带引号 ✓）——应用能读成 String ✓\n'
    elif [[ -n "$RAW" ]]; then
        printf '✗ 值是**裸值**（无引号 ✗）——会被读成 Integer ✓，登录会报"系统错误" ✗\n'
    else
        printf '（该 key 当前不存在 ✓）\n'
    fi
    exit 0
fi

MOBILE="$1"
CODE="${2:-}"
[[ -n "$CODE" ]] || fail "缺少验证码（用法：$0 <mobile> <code> ✓）"
[[ "$MOBILE" =~ ^[0-9]{6,20}$ ]] || fail "手机号形状不对：$MOBILE"

# **JSON 串** ✓：外层单引号、内层双引号，整体交给 redis-cli ✓（值里就带引号 ✓）。
docker exec "$REDIS_CONTAINER" redis-cli -n "$REDIS_DB" \
    SET "${KEY_PREFIX}${MOBILE}" "\"$CODE\"" EX 7200 >/dev/null \
    || fail "注入失败（容器 $REDIS_CONTAINER 在吗 ✓）"

echo "✓ 已注入 $KEY_PREFIX$MOBILE（JSON 串 ✓，EX 7200 ✓）"
bash "$0" --probe "$MOBILE"
