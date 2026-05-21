# Release 3.0.2 Production Upgrade Plan

本文记录生产环境从 `prod-3.0.1` 升级到 `prod-3.0.2` 的准备事项。当前文档先作为发布前检查清单，最终构建 hash、镜像 digest 和执行记录需要在实际构建/上线后补齐。

## 1. 升级结论

`3.0.2` 是 `3.0.1` 之后的稳定修复版本，重点处理：

- 外部初始化会话接口兼容无版本路径，并允许 `sex / strategyType` 缺省。
- 新建会话采集流程缓存、回填、批次线、总分位次派生和创建成功跳转稳定。
- 方案工作台筛选、方案排序、导出、专业组内专业顺序和行为事件记录稳定。
- Agent 对话的 preview -> confirm -> apply 链路和长历史污染治理收口。

本次升级范围：

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| Backend | 是 | 需要新增行为事件表迁移，并包含外部初始化兜底、导出/排序/事件记录等修复 |
| Web | 是 | 需要包含 3.0.2 创建流程、筛选、工作台展示与类型调整 |
| Agent | 是 | 需要包含 3.0.2 pending / preview / confirm 回归修复 |
| Rank | 否 | 当前没有 rank 代码或数据变更，继续沿用生产容器 |

## 2. 发布标识

统一发布标识：

```text
prod-3.0.2
```

该标识用于：

- Git tag
- 后端部署目录
- 后端 JAR 文件记录
- Web 镜像 tag
- Agent 镜像 tag
- release 包目录和文件名
- 生产执行记录

## 3. 当前 3.0.1 回滚点

生产当前回滚点以 `docs/production-upgrade-3.0.1-execution-record-2026-05-17.md` 为准：

| 模块 | 当前对象 |
| --- | --- |
| Git tag | `prod-3.0.1` |
| Backend | `zhiyuan-server-3.0.1-prod.service` |
| Backend 目录 | `/root/work/zhiyuan-server-3.0.1` |
| Web 容器 | `zhiyuan-web-3.0.1-prod` |
| Web 镜像 | `zhiyuan-web:prod-3.0.1` / `zhiyuan-web:3.0.1-amd64` |
| Agent 容器 | `zhiyuan-agent-3.0.1-prod` |
| Agent 镜像 | `zhiyuan-agent:prod-3.0.1` / `zhiyuan-agent:3.0.1-amd64` |
| Rank 容器 | `gaokao-volunteer-rank-prod`，不升级 |

升级前不要删除上述对象。

## 4. 数据库变化

`3.0.2` 新增行为事件独立表：

- `zhiyuan-server/src/main/resources/db/migration/V4__add_planning_behavior_event.sql`
- `zhiyuan-server/src/main/resources/db/migration/V5__add_planning_behavior_event_payload.sql`

目标表：

```text
assistant_planning_behavior_event
```

用途：

- 记录方案添加、删除、移动、排序、导出等行为。
- `plan_export` 作为导出正反馈。
- `exportStatus / lastExportedAt` 改为从该表读取。
- 旧 `planningState.behaviorEvents` 不再作为业务读写来源。

生产注意：

- 当前生产历史上 Flyway 一直通过启动参数 `--spring.flyway.enabled=false` 关闭。
- 如果本次继续关闭 Flyway，需要在上线后端前手动执行 V4、V5 SQL，或在受控窗口临时打开 Flyway 并确认只执行新增迁移。
- 两个 SQL 都按幂等方向编写：V4 使用 `CREATE TABLE IF NOT EXISTS`，V5 会先检查列是否存在。
- 手动执行前先备份库结构；执行后检查表和索引存在。

手动检查 SQL：

```sql
SHOW TABLES LIKE 'assistant_planning_behavior_event';
SHOW COLUMNS FROM assistant_planning_behavior_event;
SHOW INDEX FROM assistant_planning_behavior_event;
```

## 5. 构建产物

发布前在本地或构建机生成产物，生产机不做编译构建。

### 5.1 Backend

构建：

```bash
cd zhiyuan-server
mvn clean package -DskipTests
```

建议部署目录：

```text
/root/work/zhiyuan-server-3.0.2
```

目录内容：

```text
zhiyuan-server.jar
application-online.yml
logback-spring.xml
logs/
```

配置从 3.0.1 复制并复核，不在仓库文档记录敏感信息。

### 5.2 Web

生产 `/assistant-pc` 构建仍使用 `APP_ENV=prod`，不要写成 `production`：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  -t zhiyuan-web:prod-3.0.2 \
  -t zhiyuan-web:3.0.2-amd64 \
  zhiyuan-web
```

验证点：

- `.next/routes-manifest.json` 中 `basePath=/assistant-pc`。
- 构建产物不包含 `ws://localhost:8000`。
- WebSocket 地址走 `wss://www.gaotuzhiyuan.com`。

### 5.3 Agent

构建：

```bash
docker build --platform linux/amd64 \
  -t zhiyuan-agent:prod-3.0.2 \
  -t zhiyuan-agent:3.0.2-amd64 \
  zhiyuan-agent
```

验证点：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.0.2 -lc 'python -c "import app.server; print(\"agent_import_ok\")"'
```

Agent `.env` 沿用 3.0.1 生产配置，重点复核：

```text
INTERNAL_SERVICE_URL=http://host.docker.internal:8090
RANK_SERVICE_URL=http://host.docker.internal:8092
LLM_BASE_URL=<脱敏>
LLM_MODEL_NAME=<脱敏>
LLM_API_KEY=<只在环境变量中配置，不写入文档>
```

## 6. 发布资产记录

实际构建后补齐：

| 资产 | 标签/路径 | 架构 | Hash / Digest |
| --- | --- | --- | --- |
| Git tag | `prod-3.0.2` | - | 待补 |
| 后端 JAR | `server/zhiyuan-server.jar` | `linux/amd64` | 待补 |
| Web 镜像 | `zhiyuan-web:prod-3.0.2` / `zhiyuan-web:3.0.2-amd64` | `linux/amd64` | 待补 |
| Agent 镜像 | `zhiyuan-agent:prod-3.0.2` / `zhiyuan-agent:3.0.2-amd64` | `linux/amd64` | 待补 |
| Release 包 | 待补 | - | 待补 |

更新规则：

- 只要重新打包 JAR、重新构建镜像或重新导出 release 包，就必须更新本表。
- 生产切换前以 hash/digest 为准，不以文件名或 tag 名称为准。

## 7. 发布前验证

已完成或需完成的验证以 `docs/release-3.0.2-acceptance-checklist.md` 为主。发布前最低要求：

- `git diff --check`
- 后端定向测试：

```bash
cd zhiyuan-server
mvn clean -Dtest=ChatSessionBizServiceTest,IntegrationSessionServiceTest,IntegrationSessionControllerTest,PlanningStateServiceTest#shouldFallbackToCautiousStrategyWhenStrategyTypeMissing,PlanningStateServiceTest#shouldFallbackToDefaultPlanCountWhenNeedCountMissing,PlanningStateServiceTest#shouldPreferStoredStrategyTypeWhenBuildingRequiredTierCounts test
```

- 后端行为事件和规划状态测试：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest,PlanningBehaviorEventSharedServiceTest test
```

- Agent 单元回归：

```bash
cd zhiyuan-agent
pytest tests/unit/models/test_conversation_phase.py \
  tests/unit/test_chat_service_history_persistence.py \
  tests/unit/test_plan_execution_tool.py
```

- 前端人工 smoke：
  - `/assistant-pc/session`
  - `/assistant-pc/sessionDetailV2?chatSessionId=<known-session-id>`
  - 新建专业+大学模式会话
  - 新建院校专业组模式会话
  - 外部初始化接口创建会话后详情页展示学员姓名

## 8. 发布顺序

建议低峰期执行：

1. 生产只读巡检：CPU、内存、磁盘、端口、当前活跃连接、后端/agent/web/rank 日志。
2. 备份当前部署对象和数据库结构。
3. 执行 V4/V5 数据库迁移并校验表结构。
4. 启动 `zhiyuan-server-3.0.2-prod.service`，保持端口 `8090`。
5. 后端健康检查和核心接口 smoke 通过。
6. 启动 `zhiyuan-agent-3.0.2-prod`，保持 `8091 -> 8009`。
7. Agent `/health` 和一次对话 smoke 通过。
8. 启动 `zhiyuan-web-3.0.2-prod`，保持 `88 -> 28688`。
9. 页面、创建会话、外部初始化、方案导出、行为事件写入 smoke。
10. 观察日志 10-30 分钟，再确认切换完成。

## 9. 发布后 smoke

至少覆盖：

- 登录后默认进入会话列表。
- 新建专业+大学模式会话，方案数量不异常放大。
- 新建院校专业组模式会话，组内专业按录取率正排。
- 外部初始化无版本路径可用，缺 `sex / strategyType` 仍能创建，`strategy_type` 可兼容。
- 工作台候选筛选、已选标签、学校名和三级专业筛选可用。
- 方案排序、移动、删除、导出可用。
- 导出后 `assistant_planning_behavior_event` 有 `plan_export` 事件。
- 导出后再移动方案，导出状态显示为需重新导出。
- Agent 预览 -> 确认 -> 执行动作可用，版本过期时不误执行。

## 10. 回滚

回滚原则：

- 不删除 3.0.1 service、容器和镜像。
- 如果 Web 或 Agent 出现问题，优先回滚 Web / Agent。
- 如果 Backend 出现问题，停 `3.0.2` service，恢复 `3.0.1` service。
- 新增行为事件表不需要回滚删除；3.0.1 不依赖该表，保留不影响旧版本运行。

Backend 回滚：

```bash
systemctl stop zhiyuan-server-3.0.2-prod.service
systemctl start zhiyuan-server-3.0.1-prod.service
systemctl status zhiyuan-server-3.0.1-prod.service --no-pager
```

Web / Agent 回滚：

```bash
docker stop zhiyuan-web-3.0.2-prod
docker start zhiyuan-web-3.0.1-prod

docker stop zhiyuan-agent-3.0.2-prod
docker start zhiyuan-agent-3.0.1-prod
```

回滚后再次执行页面、Agent `/health`、后端 workspace-state smoke。
