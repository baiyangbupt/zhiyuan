#!/usr/bin/env bash
# P1a 验收：证据签发 → 台账 → 四态核验。
#
# 依赖本机已起的 MySQL/Redis（docker-compose.codex-local.yml，127.0.0.1:13306 / 16379）。
# 脚本自己拉起「上游替身」和 zhiyuan-server，跑完关掉。全部输出原样打印，不做重排。
#
# 用法：bash scripts/evidence_p1a_acceptance.sh
set -uo pipefail

ROOT="/root/dev/zhiyuan/zhiyuan-server"
PY="/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python"
MYSQL_CONTAINER="zhiyuan-codex-local-mysql-1"
DB="zhiyuan_codex_local"
APP_PORT=18080
UPSTREAM_PORT=18811
APP_LOG="/tmp/p1a-app.log"
UPSTREAM_LOG="/tmp/p1a-upstream.log"
BASE="http://127.0.0.1:${APP_PORT}"
UP="http://127.0.0.1:${UPSTREAM_PORT}"

mysql_exec() {
    docker exec -i "${MYSQL_CONTAINER}" sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e "$1" "$0"' "${DB}" "$1" 2>/dev/null
}

mysql_exec_verbose() {
    # 保留 stderr（报错原文）
    docker exec -i "${MYSQL_CONTAINER}" sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e "$1" "$0"' "${DB}" "$1" 2>&1 \
        | grep -v "Using a password"
}

cleanup() {
    [ -n "${APP_PID:-}" ] && kill "${APP_PID}" 2>/dev/null
    [ -n "${UPSTREAM_PID:-}" ] && kill "${UPSTREAM_PID}" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT

step() {
    echo
    echo "=============================================================="
    echo "## $*"
    echo "=============================================================="
}

extract() {
    # $1 = 响应体，$2 = 取 evidence[0] 的哪个字段
    "${PY}" -c '
import json, sys
payload = json.loads(sys.argv[1])
evidence = payload.get("evidence") or []
field = sys.argv[2]
print("<无 evidence>" if not evidence else evidence[0].get(field))
' "$1" "$2"
}

step "0. 启动上游替身与 zhiyuan-server"
"${PY}" "${ROOT}/scripts/evidence_fake_upstream.py" "${UPSTREAM_PORT}" >"${UPSTREAM_LOG}" 2>&1 &
UPSTREAM_PID=$!
mysql_exec "DELETE FROM evidence_ledger; DELETE FROM evidence_source_version;" >/dev/null
MYSQL_PASSWORD=$(docker exec "${MYSQL_CONTAINER}" sh -c 'printf %s "$MYSQL_ROOT_PASSWORD"')
java -jar "${ROOT}/target/zhiyuan-server.jar" \
    --spring.profiles.active=local \
    --spring.datasource.dynamic.datasource.master.url="jdbc:mysql://127.0.0.1:13306/${DB}?useUnicode=true&useSSL=false&characterEncoding=utf8&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true" \
    --spring.datasource.dynamic.datasource.master.username=root \
    --spring.datasource.dynamic.datasource.master.password="${MYSQL_PASSWORD}" \
    --spring.redis.host=127.0.0.1 --spring.redis.port=16379 \
    --server.port="${APP_PORT}" \
    --gaotu.zhiyuan.zhiyuan-url="${UP}" >"${APP_LOG}" 2>&1 &
APP_PID=$!
unset MYSQL_PASSWORD
READY=0
for i in $(seq 1 60); do
    if curl -s -m 2 -o /dev/null "${BASE}/gaotu-assistant-bot/inner/ops/health"; then READY=1; break; fi
    if ! kill -0 "${APP_PID}" 2>/dev/null; then echo "服务启动失败，日志尾部："; tail -30 "${APP_LOG}"; exit 1; fi
    sleep 1
done
if [ "${READY}" -ne 1 ]; then echo "服务 60 秒内未就绪，日志尾部："; tail -30 "${APP_LOG}"; exit 1; fi
echo "服务已就绪：${BASE}"
echo "上游替身：${UP}"
echo "Flyway 版本记录（V14 / V15）："
mysql_exec "SELECT version, description, success FROM flyway_schema_history WHERE version IN ('14','15') ORDER BY version;"
echo "台账初始行数："
mysql_exec "SELECT COUNT(*) FROM evidence_ledger;"

PARAMS_V1='{"areaId":"330000","batch":"本科批","majorId":"major-cs","schoolId":"school-1","year":2025,"subjectType":"物理类"}'
PARAMS_V2='{"areaId":"330000","batch":"本科批","majorId":"major-cs","schoolId":"school-1","year":2024,"subjectType":"物理类"}'
PARAMS_V3='{"areaId":"330000","batch":"本科批","majorId":"major-cs","schoolId":"school-2","year":2025,"subjectType":"物理类"}'
SCOPE="tenantId=7&chatSessionId=42&threadId=thread-1"

call_score_line() {
    curl -s -X POST "${BASE}/gaotu-assistant-bot/inner/gaotu/score-line/query?${SCOPE}" \
        -H 'Content-Type: application/json' -d "$1"
}

step "1. 同一查询参数连续两次：两个不同 evidenceId、相同 paramsDigest"
echo "--- 第 1 次原始响应 ---"
R1=$(call_score_line "${PARAMS_V1}")
echo "${R1}"
echo "--- 第 2 次原始响应 ---"
R2=$(call_score_line "${PARAMS_V1}")
echo "${R2}"
echo "--- 提取 ---"
ID1=$(extract "${R1}" evidenceId)
ID2=$(extract "${R2}" evidenceId)
D1=$(extract "${R1}" paramsDigest)
D2=$(extract "${R2}" paramsDigest)
echo "第 1 次 evidenceId   = ${ID1}"
echo "第 2 次 evidenceId   = ${ID2}"
echo "evidenceId 不同      = $([ "${ID1}" != "${ID2}" ] && echo true || echo false)"
echo "第 1 次 paramsDigest = ${D1}"
echo "第 2 次 paramsDigest = ${D2}"
echo "paramsDigest 相同    = $([ "${D1}" = "${D2}" ] && echo true || echo false)"
echo "--- 上游收到 2 次请求（替身计数）---"
curl -s "${UP}/__control/state"

step "2. 反向对照：改一个参数值（year 2025 → 2024），paramsDigest 必须变"
R3=$(call_score_line "${PARAMS_V2}")
echo "${R3}"
D3=$(extract "${R3}" paramsDigest)
echo "year=2025 paramsDigest = ${D1}"
echo "year=2024 paramsDigest = ${D3}"
echo "paramsDigest 变化      = $([ "${D1}" != "${D3}" ] && echo true || echo false)"

step "3. 台账内容（签发确实落库）"
mysql_exec "SELECT evidence_id, tenant_id, chat_session_id, thread_id, source_system, params_digest, data_version, observed_at, expires_at FROM evidence_ledger ORDER BY observed_at;"
echo "--- 来源版本登记（键是 source_system + params_digest）---"
mysql_exec "SELECT source_system, params_digest, data_version, observed_at FROM evidence_source_version;"

step "4. 响应 data 缺失 → 不签发（对照：data 存在时必须签发）"
echo "--- 控制面把 data 置为 null ---"
curl -s -X POST "${UP}/__control/data" -H 'Content-Type: application/json' -d '{"dataNull": true}'
echo
BEFORE=$(mysql_exec "SELECT COUNT(*) FROM evidence_ledger;")
R4=$(call_score_line "${PARAMS_V1}")
echo "--- 原始响应 ---"
echo "${R4}"
AFTER=$(mysql_exec "SELECT COUNT(*) FROM evidence_ledger;")
echo "调用前台账行数 = ${BEFORE}"
echo "调用后台账行数 = ${AFTER}"
echo "未产生新记录   = $([ "${BEFORE}" = "${AFTER}" ] && echo true || echo false)"
echo "--- 控制面恢复 data ---"
curl -s -X POST "${UP}/__control/data" -H 'Content-Type: application/json' -d '{"dataNull": false}'
echo
R5=$(call_score_line "${PARAMS_V1}")
AFTER2=$(mysql_exec "SELECT COUNT(*) FROM evidence_ledger;")
echo "恢复 data 后再调用，台账行数 = ${AFTER2}"
echo "对照：data 存在时必须产生记录 = $([ "${AFTER2}" -gt "${AFTER}" ] && echo true || echo false)"
ID5=$(extract "${R5}" evidenceId)
echo "新签发 evidenceId = ${ID5}"

step "5. 四态核验：valid"
verify() {
    curl -s -X POST "${BASE}/internal/evidence/verify" \
        -H 'Content-Type: application/json' \
        -d "{\"tenantId\":7,\"chatSessionId\":42,\"threadId\":\"thread-1\",\"evidenceIds\":$1}"
}
echo "--- verify(${ID5}) ---"
verify "[\"${ID5}\"]"

step "6. 四态核验：stale（上游内容变了，旧记录当时正确、现已失效）"
echo "--- 控制面把响应内容里的 minScore 从 612 改成 620（相当于上游数据更新），再查一次 ---"
curl -s -X POST "${UP}/__control/content" -H 'Content-Type: application/json' -d '{"scoreLineMinScore": "620"}'
echo
R6=$(call_score_line "${PARAMS_V1}")
ID6=$(extract "${R6}" evidenceId)
echo "新记录 evidenceId = ${ID6}"
echo "--- 旧记录与新记录一起核验 ---"
verify "[\"${ID5}\",\"${ID6}\"]"
echo "--- 对照：删掉 ${ID5} 之后必须返回 unknown ---"
mysql_exec "DELETE FROM evidence_ledger WHERE evidence_id = '${ID5}';"
verify "[\"${ID5}\",\"${ID6}\"]"

step "7. 四态核验：expired（把 expires_at 改到过去）"
mysql_exec "UPDATE evidence_ledger SET expires_at = DATE_SUB(NOW(), INTERVAL 1 DAY) WHERE evidence_id = '${ID6}';"
echo "--- 核验 ${ID6} ---"
verify "[\"${ID6}\"]"

step "8. 范围校验：换一个会话核验同一个 ID，必须 unknown"
curl -s -X POST "${BASE}/internal/evidence/verify" \
    -H 'Content-Type: application/json' \
    -d "{\"tenantId\":7,\"chatSessionId\":43,\"threadId\":\"thread-1\",\"evidenceIds\":[\"${ID6}\"]}"

step "9. data_version NOT NULL 约束的负向对照（拿不到版本就不签发，而不是写空值）"
echo "--- 绕过签发逻辑，直接插一条 data_version = NULL ---"
PROBE=$(mysql_exec_verbose "INSERT INTO evidence_ledger (evidence_id, tenant_id, chat_session_id, source_system, params_digest, data_version, observed_at, expires_at) VALUES ('ev_null_version_probe', 7, 42, 'gaotu.schoolMajorScoreLine', '0123456789abcdef0123456789abcdef', NULL, NOW(), NOW());")
PROBE_CODE=$?
echo "${PROBE}"
echo "mysql 退出码 = ${PROBE_CODE}"
echo "--- 台账里是否落进了这条探针行 ---"
mysql_exec "SELECT COUNT(*) FROM evidence_ledger WHERE evidence_id = 'ev_null_version_probe';"

step "10. 版本表键的对照：同来源、不同参数的第二条证据签发后，第一条必须仍是 valid"
echo "--- 参数组 1（schoolId=school-1，前面一直在用的那组）---"
R_KEY1=$(call_score_line "${PARAMS_V1}")
KEY1=$(extract "${R_KEY1}" evidenceId)
echo "evidenceId = ${KEY1}"
echo "--- 参数组 3（只把 schoolId 改成 school-2）---"
R_KEY2=$(call_score_line "${PARAMS_V3}")
KEY2=$(extract "${R_KEY2}" evidenceId)
echo "evidenceId = ${KEY2}"
echo "--- 版本表当前内容（应有两行，params_digest 不同）---"
mysql_exec "SELECT source_system, params_digest, data_version FROM evidence_source_version ORDER BY params_digest;"
echo "--- 核验两条：第二条签发后第一条必须仍是 valid ---"
verify "[\"${KEY1}\",\"${KEY2}\"]"

step "11. 版本表键的对照（有牙齿版）：两组参数、两次内容各不相同，后签的不得让先签的失效"
echo "--- 内容当前为 minScore=620，用参数组 1 签一条 ---"
RA=$(call_score_line "${PARAMS_V1}")
IDA=$(extract "${RA}" evidenceId)
VA=$(extract "${RA}" dataVersion)
PA=$(extract "${RA}" paramsDigest)
echo "evidenceId=${IDA}  paramsDigest=${PA}  dataVersion=${VA}"
echo "--- 把内容改成 minScore=612，再用参数组 3（schoolId=school-2）签一条 ---"
curl -s -X POST "${UP}/__control/content" -H 'Content-Type: application/json' -d '{"scoreLineMinScore": "612"}'
echo
RB=$(call_score_line "${PARAMS_V3}")
IDB=$(extract "${RB}" evidenceId)
VB=$(extract "${RB}" dataVersion)
PB=$(extract "${RB}" paramsDigest)
echo "evidenceId=${IDB}  paramsDigest=${PB}  dataVersion=${VB}"
echo "两条 paramsDigest 不同 = $([ "${PA}" != "${PB}" ] && echo true || echo false)"
echo "两条 dataVersion 不同   = $([ "${VA}" != "${VB}" ] && echo true || echo false)"
echo "--- 版本表（键必须是 source_system + params_digest）---"
mysql_exec "SELECT source_system, params_digest, data_version FROM evidence_source_version ORDER BY params_digest;"
echo "--- 核验：后签的 B 不得让先签的 A 失效（对照见报告：把键退回单行，A 必然变 stale）---"
verify "[\"${IDA}\",\"${IDB}\"]"

step "12. 收尾：停止服务"
echo "上游替身请求计数："
curl -s "${UP}/__control/state"
echo
