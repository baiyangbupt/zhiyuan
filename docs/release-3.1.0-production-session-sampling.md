# 3.1.0 生产会话仿真采样工具与操作记录

## 目标

为测试环境仿真、回归评估和后续 Agent 效果优化，低风险采样生产环境最近真实会话，形成一个可传输的数据包。采样内容覆盖：

- `message/list-all`：真实用户消息和线上回复，用于抽取真实口吻、追问链路、失败上下文。
- `userScoreDetail`：省份、选科、分数、位次、批次、填报模式、专业组/院校专业模式、偏好专业、排除专业、地域、学费等。
- `workspace-state` 摘要：候选池摘要、方案摘要、冲稳保分布、审查结果、stale 状态、专业组/专业数量、数据更新状态。
- `assistant_chat_session` / `assistant_user_base` 基础信息：会话状态、用户等级、创建时间、`prepareType` 分层分析所需字段。

## 工具位置

```bash
zhiyuan-agent/examples/collect_production_session_samples.py
```

脚本只做只读采样：

- 通过 MySQL `SELECT` 查询最近会话和用户基础字段。
- 通过内部 `GET` 接口读取消息、`userScoreDetail` 和工作区状态。
- 不调用创建会话、生成方案、审查、刷新、保存、确认、补偿等写接口。
- `workspace-state` 只在本地提炼摘要，不导出完整候选池和方案明细数组。

## 只读数据源

数据库查询：

```sql
SELECT ...
FROM assistant_chat_session s
LEFT JOIN assistant_user_base u ON u.id=s.user_id
WHERE s.tenant_id=1
  AND EXISTS (SELECT 1 FROM assistant_chat_message mx WHERE mx.chat_session_id=s.id AND mx.message_from='1' LIMIT 1)
  AND EXISTS (SELECT 1 FROM assistant_chat_message my WHERE my.chat_session_id=s.id AND my.message_from='0' LIMIT 1)
ORDER BY s.create_time DESC, s.id DESC
LIMIT ${scanLimit};
```

内部接口：

```text
GET /gaotu-assistant-bot/inner/chat/1/message/list-all?chatSessionId=...
GET /gaotu-assistant-bot/inner/chat/1/session/get-extra-data?chatSessionId=...&keyList=userScoreDetail&version=0
GET /gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=...
```

## 使用方法

生产机上低峰期执行，默认读取 `/apps/zhiyuan-server-prod/application-online.yml` 中的数据源密码，也可以通过 `ZHIYUAN_SAMPLE_DB_PASSWORD` 或 `MYSQL_PWD` 覆盖。

小样本验证：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
python examples/collect_production_session_samples.py \
  --config-path /apps/zhiyuan-server-prod/application-online.yml \
  --limit 3 \
  --scan-limit 20 \
  --output /tmp/zhiyuan-production-sample-test3.json
```

正式采样最近 100 个有效会话：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
python examples/collect_production_session_samples.py \
  --config-path /apps/zhiyuan-server-prod/application-online.yml \
  --limit 100 \
  --scan-limit 300 \
  --gzip
```

传输到测试机：

```bash
scp /tmp/zhiyuan-production-sample-100-YYYYMMDD-HHMMSS.json.gz root@10.218.4.10:/tmp/
```

完整性校验：

```bash
sha256sum /tmp/zhiyuan-production-sample-100-YYYYMMDD-HHMMSS.json.gz
ssh root@10.218.4.10 sha256sum /tmp/zhiyuan-production-sample-100-YYYYMMDD-HHMMSS.json.gz
```

结构和统计校验：

```bash
python - <<'PY'
import gzip, json, collections
p = '/tmp/zhiyuan-production-sample-100-YYYYMMDD-HHMMSS.json.gz'
with gzip.open(p, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(data['metadata'])
print('count', len(data['sessions']), 'errors', len(data['errors']), 'skipped', len(data['skipped']))
prep = collections.Counter()
phase = collections.Counter()
levels = collections.Counter()
message_total = 0
for session in data['sessions']:
    user_score = session.get('userScoreDetail') or {}
    prepare_type = user_score.get('prepareType') or {}
    prep[prepare_type.get('code') if isinstance(prepare_type, dict) else str(prepare_type)] += 1
    phase[(session.get('planningState') or {}).get('phase')] += 1
    levels[session.get('session', {}).get('userLevel')] += 1
    message_total += session.get('messages', {}).get('total', 0)
print('prepareType', dict(prep))
print('phase', dict(phase))
print('userLevel', dict(levels))
print('messageTotal', message_total)
print('firstIds', [s['session']['sessionId'] for s in data['sessions'][:20]])
PY
```

## 参数说明

常用参数：

- `--limit`：导出的有效会话数量，默认 `100`。
- `--scan-limit`：从最近会话中扫描的数量，默认 `300`。如果近期空会话很多，可适当调大。
- `--include-empty`：包含没有用户/助手来回对话的会话。默认不包含。
- `--sleep`：每个会话之间的暂停秒数，默认 `0.05`，用于避免请求突刺。
- `--gzip`：输出 gzip 压缩文件。
- `--output` / `--output-dir`：指定输出路径，默认 `/tmp/zhiyuan-production-sample-${limit}-${timestamp}.json`。
- `--workspace-sample-size`：候选/方案样例数量，默认每类只保留 `5` 条样例。
- `--max-content-chars`：单条消息内容最大字符数，默认 `5000`。

环境变量覆盖：

- `ZHIYUAN_SAMPLE_BASE_URL`
- `ZHIYUAN_SAMPLE_TENANT_ID`
- `ZHIYUAN_SAMPLE_CONFIG_PATH`
- `ZHIYUAN_SAMPLE_DB_HOST`
- `ZHIYUAN_SAMPLE_DB_PORT`
- `ZHIYUAN_SAMPLE_DB_USER`
- `ZHIYUAN_SAMPLE_DB_NAME`
- `ZHIYUAN_SAMPLE_DB_PASSWORD` 或 `MYSQL_PWD`

## 隐私和数据边界

脚本会脱敏明显的手机号、token、超长 token、头像、登录凭证等字段，但消息文本、专业/院校/分数画像等会保留用于仿真分析。采样文件仍按生产敏感数据处理：

- 不提交到 Git。
- 不放入公开对象存储。
- 只传到受控测试环境。
- 后续沉淀到稳定回归 case 前，需要人工抽象和二次脱敏。

## 性能和线上影响控制

- 数据库仅执行一次最近会话 `SELECT`，不做写入。
- HTTP 请求按会话串行执行：每个有效会话最多 3 个内部 `GET`。
- 默认过滤掉空会话，避免对没有价值的会话继续读取工作区。
- 工作区接口返回体可能较大，但脚本只在本地提炼摘要，输出文件体积可控。
- 建议低峰期执行，并在执行过程中观察 `uptime`、`ps` 或现有监控。

## 2026-06-14 操作记录

执行环境：生产机 `/root/dev/zhiyuan`，生产服务 `zhiyuan-server-3.0.3`，本机内部接口 `http://127.0.0.1:8090`。

小样本验证：

```bash
/tmp/zhiyuan_sample_recent_sessions.py --limit 3 --scan-limit 20 --output /tmp/zhiyuan-production-sample-test3-v2.json
```

结果：

```json
{"output":"/tmp/zhiyuan-production-sample-test3-v2.json","selectedCount":3,"skippedCount":0,"errorCount":0,"firstSessionIds":[3154,3151,3139]}
```

正式采样：

```bash
/tmp/zhiyuan_sample_recent_sessions.py --limit 100 --scan-limit 300 --gzip
```

结果文件：

```text
/tmp/zhiyuan-production-sample-100-20260614-043817.json.gz
```

采样结果：

- 会话数：`100`
- 消息数：`852`
- 采集错误：`0`
- 跳过：`0`
- 文件大小：`508K`
- SHA256：`2d3e2c3b9c0f4d3595b4f257fba3a646a7532a70ca4ddac27f4255b002e40247`

分布：

- `prepareType`：`PREDICT 95`，`VOLUNTEER 5`
- 会话阶段：`ordered 40`，`reviewed 30`，`candidate_generated 15`，`profile_ready 13`，`drafting 2`
- 用户等级：`SUPER_VIP 40`，`ORIGIN 34`，`VIP 26`

传输到测试机：

```bash
scp /tmp/zhiyuan-production-sample-100-20260614-043817.json.gz root@10.218.4.10:/tmp/
ssh root@10.218.4.10 ls -lh /tmp/zhiyuan-production-sample-100-20260614-043817.json.gz
ssh root@10.218.4.10 sha256sum /tmp/zhiyuan-production-sample-100-20260614-043817.json.gz
```

远端校验：

```text
-rw-r--r-- 1 root root 508K Jun 14 06:52 /tmp/zhiyuan-production-sample-100-20260614-043817.json.gz
2d3e2c3b9c0f4d3595b4f257fba3a646a7532a70ca4ddac27f4255b002e40247  /tmp/zhiyuan-production-sample-100-20260614-043817.json.gz
```

执行期间机器负载检查：

```text
load average: 0.07, 0.05, 0.05
zhiyuan-server Java CPU 约 0.5%
```

小样本验证文件已清理，只保留正式 100 个样本文件在 `/tmp`。

## 与生产对话 case 导出的关系

已有工具 `zhiyuan-agent/examples/export_production_dialogue_cases.py` 用于把真实对话抽象成回归 case 候选，重点是 Agent 对话效果回归。

本工具 `collect_production_session_samples.py` 用于测试环境仿真采样，覆盖会话上下文、用户画像和工作区摘要，适合构建测试数据包和做分层分析。两者互补，不互相替代。
