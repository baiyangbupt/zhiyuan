# Release 3.1.0 Production Upgrade Plan

本文记录生产环境从 `prod-3.0.3` 升级到 `prod-3.1.0` 的执行步骤、验证清单和回滚方案。生产实际部署时间、构建 hash、镜像 digest 和 smoke 结果需要在上线当天补齐。

## 1. 升级结论

`3.1.0` 是数据新鲜度、审查修复和 Agent 编排增强版本。本次升级涉及运行时代码和数据库结构：

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| Backend `zhiyuan-server` | 是 | 数据新鲜度、巡检索引、FixProposal、审查规则、工作区状态 |
| Web `zhiyuan-web` | 是 | `/assistant-pc` 工作区数据同步提示、候选/方案/审查联动 |
| Agent `zhiyuan-agent` | 是 | 对话编排、review repair、pending confirmation、回复稳定性 |
| Rank `zhiyuan-rank` | 否 | 本轮无 Rank 变更，继续沿用 3.0.3 生产容器 |
| 数据库 | 是 | 新增 V6 巡检索引表 |

本次不做：

- 不重算历史会话。
- 不改主站鉴权协议。
- 不改 Rank 服务。
- 不默认开启数据新鲜度后台巡检。
- 不把真实 LLM key 或数据库连接写入仓库文档。

## 2. 发布标识

统一发布标识：

```text
prod-3.1.0
```

用于：

- Git tag。
- Backend JAR/release 目录。
- Web 镜像 tag。
- Agent 镜像 tag。
- 发布文档和执行记录。

构建前必须确认：

```bash
git status --short
git rev-parse HEAD
git tag -l 'prod-3.1.0'
```

要求：

- 构建源必须是已提交 commit。
- `prod-3.1.0` tag 不应提前存在。
- 构建后 tag 打在最终发布 commit 上。

## 3. 3.0.3 回滚点

回滚点：

```text
prod-3.0.3
```

升级前保留：

- `prod-3.0.3` Backend JAR 和启动配置。
- `prod-3.0.3` Web 镜像/容器。
- `prod-3.0.3` Agent 镜像/容器。
- 现有 Rank 容器。
- 现有 Nginx/主站代理配置备份。

不要在 3.1.0 验证完成前删除 3.0.3 资产。

## 4. 数据库升级

3.1.0 新增：

```text
zhiyuan-server/src/main/resources/db/migration/V6__add_planning_data_freshness_schedule.sql
```

生产环境如果仍使用 `--spring.flyway.enabled=false`，必须手工执行该 SQL。执行前确认当前库已经包含 3.0.3 所需表和 `flyway_schema_history` 当前状态；执行后验证：

```sql
SHOW TABLES LIKE 'assistant_planning_data_freshness_schedule';
SHOW INDEX FROM assistant_planning_data_freshness_schedule;
```

必须存在：

- `assistant_planning_data_freshness_schedule`
- `uk_planning_data_freshness_schedule_session`
- `idx_planning_data_freshness_schedule_due`
- `idx_planning_data_freshness_schedule_status`

回滚说明：

- 如果应用回滚到 3.0.3，该表可以保留。
- 不需要执行 drop table。
- 该表只服务 3.1.0 数据新鲜度巡检，不影响 3.0.3 基础功能。

## 5. 配置检查

Backend：

```yaml
planning:
  data-freshness:
    schedule:
      enabled: false
      fixed-delay-ms: 300000
      batch-size: 5
      seed-batch-size: 10
      max-consecutive-tasks: 2
```

要求：

- 首发 `enabled=false`，避免上线即批量请求高途上游。
- 生产外部配置继续关闭 SQL stdout 明细，避免日志打满根盘。
- 保持生产 MySQL/Redis/高途接口配置不变。

Agent：

- `LLM_PROVIDER=openai_compatible`
- `LLM_MODEL_NAME` 使用线上已验证模型。
- `LLM_BASE_URL`、`LLM_API_KEY` 只在运行环境配置。
- `INTERNAL_SERVICE_URL` 指向生产 Backend。
- `RANK_SERVICE_URL` 指向生产 Rank。

Web：

- 生产构建使用 `/assistant-pc` basePath。
- 不把本地 `NEXT_PUBLIC_*_OVERRIDE` 写进正式生产镜像。
- WebSocket 路径保持 `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`。

Nginx/主站代理：

```nginx
location /assistant-pc/ {
    proxy_pass http://<web-upstream>;
}

location /gaotu-assistant-bot/ {
    proxy_pass http://<backend-upstream>;
}

location /gaotu-assistant-agent/ {
    proxy_pass http://<agent-upstream>;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## 6. 构建

### 6.1 Backend

```bash
cd zhiyuan-server
mvn clean package -DskipTests
```

产物：

```text
zhiyuan-server/target/zhiyuan-server.jar
```

### 6.2 Web

生产构建必须使用 `APP_ENV=prod`：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  -t zhiyuan-web:prod-3.1.0 \
  -t zhiyuan-web:3.1.0-amd64 \
  zhiyuan-web
```

构建后检查：

```bash
docker run --rm --entrypoint sh zhiyuan-web:prod-3.1.0 -lc \
  'grep -R "\"basePath\":\"/assistant-pc\"" -n .next/routes-manifest.json'
```

### 6.3 Agent

```bash
docker build --platform linux/amd64 \
  -t zhiyuan-agent:prod-3.1.0 \
  -t zhiyuan-agent:3.1.0-amd64 \
  zhiyuan-agent
```

构建后检查：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.1.0 -lc \
  'python -c "import app.server; print(\"agent_import_ok\")"'
```

## 7. 切换顺序

推荐顺序：

1. 停止或旁路准备 Backend 新版本。
2. 确认 V6 SQL 已执行。
3. 启动 Backend 3.1.0，`planning.data-freshness.schedule.enabled=false`。
4. 验证 Backend health 和基础数据接口。
5. 启动 Agent 3.1.0。
6. 验证 Agent health 和 WebSocket 握手。
7. 启动 Web 3.1.0。
8. 验证 `/assistant-pc/session` 和 `/assistant-pc/sessionDetailV2`。
9. 主站代理入口验证。

不建议先启用后台巡检；上线稳定后再单独开启。

## 8. 发布冒烟

本地标准测试环境：

```bash
ZHIYUAN_SERVER_PORT=18090 \
ZHIYUAN_WEB_PORT=3001 \
ZHIYUAN_AGENT_PORT=18091 \
ZHIYUAN_RANK_PORT=18092 \
bash ops/release-smoke.sh --local
```

带真实会话：

```bash
bash ops/release-smoke.sh --local --session-id <chatSessionId>
```

生产或测试主站代理：

```bash
bash ops/release-smoke.sh --remote https://test-www.gaotuzhiyuan.com --session-id <chatSessionId>
```

检查项：

- Web `/assistant-pc/session`
- Web `/assistant-pc/sessionDetailV2`
- Backend `/gaotu-assistant-bot/inner/ops/health`
- Backend `/gaotu-assistant-bot/base-data/province-city`
- Backend `/gaotu-assistant-bot/inner/planning/{tenantId}/review/rules`
- Agent `/gaotu-assistant-agent/health`
- Agent WebSocket `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`
- Rank `/health`
- 可选会话工作区、数据新鲜度、巡检状态只读接口

本机标准测试环境验证记录（2026-06-18）：

| 项 | 结果 |
| --- | --- |
| Backend | 已用当前 `develop` 构建 JAR 并启动在 `18090`，health 通过 |
| Web | 已用 `.env.standardtest` 构建并启动在 `3001`，`/assistant-pc/session` 与 `/assistant-pc/sessionDetailV2` 通过 |
| Agent | 已用当前代码重封装 `zhiyuan-agent:local310` 并重建 `zhiyuan-agent-local302`，`18091` health 与 WebSocket 握手通过 |
| Rank | 沿用 `zhiyuan-rank-local302`，`18092` health 通过 |
| 数据库 | 本地测试库 Flyway 已验证 6 个 migration，当前 schema version `6`，无需新增迁移 |
| 冒烟命令 | `ZHIYUAN_PYTHON=/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python bash ops/release-smoke.sh --local --session-id 122 --websocket` |
| 冒烟结果 | `12` 项 PASS，`0` failures，`0` warnings |

## 9. 人工验收清单

主站链路：

- `test-www.gaotuzhiyuan.com/assistant-pc` 能通过高途渠道鉴权进入列表。
- 未登录时进入登录页，登录后不循环跳回。
- PC 端不出现移动端抽屉布局。
- `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do` WebSocket 正常建立。

工作区：

- 新建 PREDICT 会话展示“数据为 2025 年的志愿数据”，不触发数据同步弹窗。
- 新建 VOLUNTEER 会话展示“2026 年招生计划”，有最新同步时间和 hover 摘要能力。
- 无真实数据变化时不弹窗。
- 候选区、方案区、审查区正常加载推荐系数、录取率、历年录取信息。
- 进入候选区后，若后端标记需要刷新，候选自动刷新，不需要用户点单独按钮。

对话：

- 快捷入口和手动输入都有回复。
- 只读咨询不生成方案修改确认卡片。
- 明确方案修改生成 pending confirmation 卡片，确认前不落盘。
- 审查问题可以解释，并能生成修复建议。
- 旧卡片/旧 pending 不可被历史文本误执行。

权益：

- `SUPER_VIP` 不受智能填报日限。
- 非 `SUPER_VIP` 创建 `VOLUNTEER` 会话每天最多 2 个。
- `PREDICT` 模拟填报不进入该日限。

## 10. 观察项

上线后至少观察：

- Backend error log、慢 SQL、数据库连接池、Redis 错误。
- `assistant_planning_data_freshness_schedule` 写入和查询是否正常。
- `planning.data-freshness.schedule.enabled=false` 时没有后台巡检批量请求日志。
- Agent 超时、LLM provider 长尾、WebSocket 断开率。
- Web 控制台是否有静态资源、API、WebSocket 报错。
- 高途渠道鉴权成功率。

## 11. 回滚

应用回滚：

1. 停止 Web 3.1.0，恢复 Web 3.0.3。
2. 停止 Agent 3.1.0，恢复 Agent 3.0.3。
3. 停止 Backend 3.1.0，恢复 Backend 3.0.3。
4. Rank 不动。
5. 验证主站入口、列表、详情、对话基础功能。

数据库：

- 不删除 `assistant_planning_data_freshness_schedule`。
- 如果已经开启过后台巡检，先关闭调度配置再回滚应用。

回滚后可用 3.0.3 smoke 或基础 curl 检查：

```bash
curl -sS http://127.0.0.1:<backend-port>/gaotu-assistant-bot/inner/ops/health
curl -sS http://127.0.0.1:<agent-port>/gaotu-assistant-agent/health
curl -I http://127.0.0.1:<web-port>/assistant-pc/session
```

## 12. 上线执行记录

上线当天补齐：

| 项 | 记录 |
| --- | --- |
| 执行时间 | 待补 |
| 发布 commit | 待补 |
| Git tag | `prod-3.1.0` |
| Backend JAR sha256 | 待补 |
| Web image digest | 待补 |
| Agent image digest | 待补 |
| V6 SQL 执行结果 | 待补 |
| smoke 结果 | 待补 |
| 回滚资产确认 | 待补 |
| 遗留风险 | 待补 |
