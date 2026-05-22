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
- 正式生产镜像不要传 `NEXT_PUBLIC_ASSISTANT_API_BASE_URL`、`NEXT_PUBLIC_AGENT_API_BASE_URL`、`NEXT_PUBLIC_OUTER_API_BASE_URL`、`NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE` 覆盖参数；默认值会继续指向 `https://www.gaotuzhiyuan.com`。

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
| Git commit | `5bf204e1eaec79b0c2f2a6df0d0ec952a4f1e2ec` | - | 已构建 |
| Git tag | `prod-3.0.2` | - | 待打 tag |
| 后端 JAR | `zhiyuan-server/target/zhiyuan-server.jar` | `linux/amd64` | `sha256:88d845145aa581b6a9bc5845fb9434c17a68e51429f6127bfaac900559181914` |
| Web 镜像 | `zhiyuan-web:prod-3.0.2` / `zhiyuan-web:3.0.2-amd64` | `linux/amd64` | `sha256:6687262d562fee6ddf7507c298b9da1c2a99c3789695e593a663fc1f5279530f` |
| Agent 镜像 | `zhiyuan-agent:prod-3.0.2` / `zhiyuan-agent:3.0.2-amd64` | `linux/amd64` | `sha256:01b8a9e877740102b068a4f8fb1b63923096224de24dffa515c28dfad3e61f99` |
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

## 8. 本地部署验证走查

上线前需要在本机先完成一次 `3.0.1 -> 3.0.2` 的本地部署验证。验证分两层：

- 本地开发进程 smoke：用于快速确认当前代码在开发环境可运行，便于前端人工验证。
- 本地类生产演练：用于确认生产构建方式、`/assistant-pc` basePath、镜像端口、后端 JAR、数据库迁移和回滚口径没有问题。

### 8.1 本地开发进程 smoke

适用场景：日常修复后快速验证，不代表生产构建产物。

启动：

```bash
bash scripts/start-all.sh
```

如果只验证应用服务且本机 MySQL/Redis 已经运行：

```bash
bash scripts/start-all.sh --skip-infra
```

端口：

| 模块 | 地址 |
| --- | --- |
| Web | `http://127.0.0.1:3001` |
| Backend | `http://127.0.0.1:8080` |
| Agent | `http://127.0.0.1:8000` |
| Rank | `http://127.0.0.1:5001` |

健康检查：

```bash
ZHIYUAN_WEB_PORT=3001 \
ZHIYUAN_WEB_HEALTH_PATH=/session \
ZHIYUAN_SERVER_PORT=8080 \
ZHIYUAN_AGENT_PORT=8000 \
ZHIYUAN_RANK_PORT=5001 \
bash ops/healthcheck.sh --local
```

前端开发态注意：

- Web 必须通过 `scripts/start-all.sh` 或 `npm run dev` 读取 `.env.dev`。
- 不要直接执行 `next dev -p 3001`，否则可能沿用 `.next` 里的生产 `basePath=/assistant-pc`，导致 `/session` 或静态资源 `404`。
- 如发现页面效果与代码不一致，先执行 `bash scripts/status.sh`，确认没有旧 Node / Uvicorn / Java 进程占用端口。

开发 smoke 通过标准：

- `/session`、`/customer`、`/customerDetail`、`/sessionDetailV2?chatSessionId=<known-session-id>` 可访问。
- 新建专业+大学、院校专业组两种模式会话可生成方案。
- 工作台方案数、候选数、筛选、排序、导出、行为事件写入可用。
- Agent 方案查询、预览、确认、执行至少完成一条 smoke。

### 8.2 本地类生产演练

适用场景：正式上线前，验证生产部署方式和回滚方式。生产机不做编译构建，本地或构建机必须先产出可追溯产物。

本地建议端口：

| 模块 | 本地类生产端口 |
| --- | --- |
| Backend | `8090` |
| Web | `18088 -> 28688` |
| Agent | `18091 -> 8009` |
| Rank | `18092 -> 5001` 或沿用本地已启动 Rank |

演练步骤：

1. 基于当前代码构建 3.0.2 后端 JAR、Web amd64 镜像、Agent amd64 镜像。
2. 应用 V4/V5 数据库迁移到本地演练库，确认 `assistant_planning_behavior_event` 表存在。
3. 启动 3.0.1 基线对象，确认后端、Web、Agent、Rank 均健康。
4. 停止 3.0.1 后端、Web、Agent，保留 Rank。
5. 启动 3.0.2 后端、Web、Agent，端口模拟生产保持不变。
6. 执行健康检查和业务 smoke。
7. 停止 3.0.2 后端、Web、Agent，恢复 3.0.1 对象，确认回滚健康。

类生产健康检查：

```bash
ZHIYUAN_WEB_PORT=18088 \
ZHIYUAN_WEB_HEALTH_PATH=/assistant-pc/session \
ZHIYUAN_SERVER_PORT=8090 \
ZHIYUAN_AGENT_PORT=18091 \
ZHIYUAN_RANK_PORT=18092 \
bash ops/healthcheck.sh --local
```

类生产 Web 构建检查：

```bash
docker run --rm --entrypoint sh zhiyuan-web:prod-3.0.2 -lc \
  'grep -R "ws://localhost:8000" -n .next public 2>/dev/null; test $? -ne 0'

docker run --rm --entrypoint sh zhiyuan-web:prod-3.0.2 -lc \
  'grep -R "\"basePath\":\"/assistant-pc\"" -n .next/routes-manifest.json'
```

注意：`next.config.mjs` 的 `rewrites` 在 `next build` 阶段固化。正式 `prod-3.0.2` 镜像默认会把 `/gaotu-assistant-bot` 和 `/gaotu-assistant-agent` 代理到 `https://www.gaotuzhiyuan.com`；如果直接用该镜像在本机 `18088` 做功能验证，页面代码是 3.0.2，但接口可能命中线上环境，容易误判为本地功能回退。

需要验证本地 3.0.2 Backend / Agent 时，单独构建本地验证镜像，不覆盖正式发布 tag：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  --build-arg NEXT_PUBLIC_ASSISTANT_API_BASE_URL=http://host.docker.internal:8090 \
  --build-arg NEXT_PUBLIC_AGENT_API_BASE_URL=http://host.docker.internal:18091 \
  --build-arg NEXT_PUBLIC_OUTER_API_BASE_URL=https://www.gaotuzhiyuan.com \
  --build-arg NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=ws://host.docker.internal:18091 \
  -t zhiyuan-web:prod-3.0.2-local-api \
  zhiyuan-web
```

启动本地验证镜像后，应至少直接校验代理落点：

```bash
curl 'http://127.0.0.1:18088/gaotu-assistant-bot/inner/planning/1/session/candidate-pool/filter-options?chatSessionId=17' \
  | grep -E 'schoolKeywords|majorTree|院校名称|专业名称'
```

如该接口仍返回线上数据或旧结构，先检查 Web 镜像是否用上述 build arg 重新构建，不能只在 `docker run -e` 阶段补环境变量。

2026-05-22 已完成一次本地 API 验证镜像构建：

- 镜像：`zhiyuan-web:prod-3.0.2-local-api`
- 镜像 ID：`sha256:4a5b158c507fe2dfcb2820c97415eb2edd91fcd81ee188b198c739e3261a1a7b`
- `routes-manifest.json` 确认 `/gaotu-assistant-bot` 指向 `http://host.docker.internal:8090`，`/gaotu-assistant-agent` 指向 `http://host.docker.internal:18091`。
- 当前本机 `zhiyuan-web-3.0.2-walkthrough` 已临时切到该镜像，`http://127.0.0.1:18088/assistant-pc/session` 可用于本地 Backend 功能走查。
- 通过 `18088` 代理验证 `candidate-pool/filter-options?chatSessionId=17` 已返回 `schoolKeywords / 院校名称 / 专业名称 / majorTree`。
- 通过 `18088` 代理验证 `ordered-plan/export`：session `17` 返回 `200 / 17308 bytes / 1.298s`，session `16` 返回 `200 / 26064 bytes / 8.495s`。

类生产 Agent 检查：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.0.2 -lc \
  'python -c "import app.server; print(\"agent_import_ok\")"'
```

类生产业务 smoke 至少覆盖：

- `/assistant-pc/session` 可打开。
- `/assistant-pc/sessionDetailV2?chatSessionId=<known-session-id>` 可打开。
- `GET /gaotu-assistant-bot/base-data/province-city` 返回 `200`。
- `GET /health` 或 Agent 健康接口返回 `200`。
- 专业+大学模式导出为一条志愿一行，不按学校聚合。
- 院校专业组模式组内专业按录取率正排，导出与页面一致。
- 外部初始化旧路径 `/integration/session/initialize` 和 `v1` 路径均可用；缺 `sex / strategyType` 可兜底。
- 导出后新表存在 `plan_export` 事件；导出后再移动方案时导出态变为需重新导出。

本地类生产演练通过后，把实际执行时间、commit、JAR SHA-256、镜像 digest、release 包路径和 smoke 结果补充到第 6 节资产表和 `docs/release-3.0.2-acceptance-checklist.md`。

### 8.3 本地构建记录

执行时间：2026-05-22。

本机环境：

- macOS + Docker Desktop 4.40.0。
- Docker Client `darwin/arm64`，Docker Server `linux/arm64`。
- 生产目标为 `linux/amd64`，Web / Agent 镜像均显式使用 `--platform linux/amd64` 构建。
- 本机根分区剩余约 `24Gi`；Docker 构建完成后镜像占用约 `5.0GB`，Build Cache 约 `1.6GB`。

构建结果：

- 后端 JAR 构建通过：`mvn clean package -DskipTests`，产物 `110M`，SHA-256 见第 6 节。
- Web 镜像构建通过：`zhiyuan-web:prod-3.0.2` / `zhiyuan-web:3.0.2-amd64`。
- Agent 镜像构建通过：`zhiyuan-agent:prod-3.0.2` / `zhiyuan-agent:3.0.2-amd64`。

构建校验：

- Web 镜像架构为 `amd64/linux`。
- Web 镜像 `.next/routes-manifest.json` 包含 `basePath=/assistant-pc`。
- Web 镜像未检出 `ws://localhost:8000`。
- Agent 镜像架构为 `amd64/linux`。
- Agent 镜像 import 检查通过：`agent_import_ok`。

本地类生产启动 smoke：

- 启动口径：Web / Agent 使用 `prod-3.0.2` amd64 镜像；Rank 沿用 `zhiyuan-rank:prod-3.0.0`；后端使用 3.0.2 JAR + `local` profile + `server.port=8090`，同时覆盖 Rank/Agent 地址到本地类生产端口。
- 不直接使用仓库内 `application-online.yml` 做本地演练，避免误连生产 MySQL / Redis / OSS / 上游服务。
- 后端启动时 Flyway 校验本地 `sales_bot` schema 当前版本为 `5`，V4/V5 行为事件表迁移已在本地库生效。

基础健康检查：

| 检查项 | 结果 |
| --- | --- |
| Web `/assistant-pc/session` | `200`，约 `0.108s` |
| Web `/assistant-pc/sessionDetailV2?chatSessionId=17` | `200`，约 `0.021s` |
| Agent `/health` | `200`，约 `0.048s` |
| Rank `/health` | `200`，约 `0.025s` |
| Backend `/gaotu-assistant-bot/base-data/province-city` | `200`，约 `0.451s` |

业务 smoke：

| 检查项 | 结果 |
| --- | --- |
| `workspace-state?chatSessionId=16` | `200`，约 `2.087s`，`orderedItems=176`，`orderedUnits=45`，`phase=ordered` |
| `workspace-state?chatSessionId=17` | `200`，约 `1.193s`，`orderedItems=94`，`orderedUnits=45`，`phase=ordered` |
| `candidate-pool/query?chatSessionId=17` | `200`，约 `1.237s`，`total=402` |
| `ordered-plan/export?chatSessionId=16` | `200`，约 `9.139s`，`26064` bytes |
| `ordered-plan/export?chatSessionId=17` | `200`，约 `3.323s`，`17305` bytes |
| `assistant_planning_behavior_event` | 写入 `plan_export`：`session=16 mode=majorGroup positive_feedback=1`，`session=17 mode=major positive_feedback=1` |

本地回滚 smoke：

- Web 回滚镜像 `zhiyuan-web:prod-3.0.1` 启动到 `18088 -> 28688`，`/assistant-pc/session` 返回 `200`，约 `0.079s`。
- Agent 回滚镜像 `zhiyuan-agent:prod-3.0.1` 启动到 `18091 -> 8009`，`/health` 返回 `200`，约 `0.031s`。
- Rank 回滚容器继续使用 `zhiyuan-rank:prod-3.0.0`，`/health` 返回 `200`，约 `0.040s`。
- 本机未保留 3.0.1 后端 JAR，只保留 `prod-3.0.1` git tag 和生产执行记录；本地未重建旧 JAR 做后端回滚 smoke。生产回滚仍以已保留的 `zhiyuan-server-3.0.1-prod.service` 和 `/root/work/zhiyuan-server-3.0.1` 为准。

清理记录：

- 本地演练容器均已停止并删除。
- `8090` 类生产后端进程已停止，端口已释放。

待补：

- release 包导出路径和包 hash。
- 正式 `prod-3.0.2` git tag。

### 8.4 本地 3.0.1 -> 3.0.2 人工走查环境

执行时间：2026-05-22。

目标：

- 在本机按同一组类生产端口先启动 `3.0.1` 基线，再切换到 `3.0.2`。
- 切换后保留 `3.0.2` 环境，供浏览器人工走查。

端口：

| 模块 | 端口 |
| --- | --- |
| Web | `18088 -> 28688` |
| Backend | `8090` |
| Agent | `18091 -> 8009` |
| Rank | `18092 -> 5001` |

3.0.1 基线准备：

- 本机已有 `zhiyuan-web:prod-3.0.1` 和 `zhiyuan-agent:prod-3.0.1` 镜像。
- 本机未保留 3.0.1 后端 JAR，因此从 `prod-3.0.1` tag 创建临时 worktree `/private/tmp/zhiyuan-prod-3.0.1` 并执行 `mvn clean package -DskipTests` 构建旧 JAR。
- 3.0.1 后端使用 `local` profile 启动到 `8090`，并关闭 Flyway：`--spring.flyway.enabled=false`。这样可以模拟旧版本后端运行，同时避免旧版本迁移定义和当前本地 schema version 5 冲突。

3.0.1 基线健康检查：

| 检查项 | 结果 |
| --- | --- |
| Backend `/gaotu-assistant-bot/base-data/province-city` | `200`，约 `0.498s` |
| Web `/assistant-pc/session` | `200`，约 `0.055s` |
| Agent `/health` | `200`，约 `0.018s` |
| Rank `/health` | `200`，约 `0.034s` |

升级切换：

1. 停止并删除 `zhiyuan-web-3.0.1-walkthrough`、`zhiyuan-agent-3.0.1-walkthrough`、`zhiyuan-rank-3.0.1-walkthrough`。
2. 停止 3.0.1 后端 Java 进程。
3. 启动 `zhiyuan-web:prod-3.0.2`、`zhiyuan-agent:prod-3.0.2`、`zhiyuan-rank:prod-3.0.0`。
4. 启动当前 3.0.2 JAR 到 `8090`，使用 `local` profile；Flyway 校验本地 schema version 5，无需新增迁移。

3.0.2 升级后健康检查：

| 检查项 | 结果 |
| --- | --- |
| Backend `/gaotu-assistant-bot/base-data/province-city` | `200`，约 `0.434s` |
| Web `/assistant-pc/session` | `200`，约 `0.087s` |
| Agent `/health` | `200`，约 `0.041s` |
| Rank `/health` | `200`，约 `0.045s` |

3.0.2 升级后业务 smoke：

| 检查项 | 结果 |
| --- | --- |
| `workspace-state?chatSessionId=16` | `200`，约 `2.788s`，`688528` bytes |
| `workspace-state?chatSessionId=17` | `200`，约 `2.111s`，`335640` bytes |
| `ordered-plan/export?chatSessionId=17` | `200`，约 `3.737s`，`17305` bytes |

走查注意：

- 当前保留的 `zhiyuan-web:prod-3.0.2` 是正式生产口径镜像，production rewrite 默认指向 `https://www.gaotuzhiyuan.com`。
- 因此 `http://127.0.0.1:18088/assistant-pc/session` 只能用于验证“生产构建前端可打开”；不能直接作为本地 Backend 功能验收依据。
- 如果要验证本地 Backend 的筛选项、导出、排序等接口行为，必须使用第 8.2 节的 `zhiyuan-web:prod-3.0.2-local-api` 验证镜像，或改用本地开发前端连接 `8090`。
- 已定位到一次误判：正式镜像的页面代码包含 3.0.2 的“院校名称 / 专业名称 / majorTree”筛选逻辑，但 `18088` 通过 rewrite 请求接口时可能命中线上，导致页面看起来像回退到旧筛选/旧导出行为。

当前保留给人工走查的地址：

```text
http://127.0.0.1:18088/assistant-pc/session
```

当前保留运行的对象：

- `zhiyuan-web-3.0.2-walkthrough`
- `zhiyuan-agent-3.0.2-walkthrough`
- `zhiyuan-rank-3.0.2-walkthrough`
- 3.0.2 后端 Java 进程，监听 `8090`

人工走查建议覆盖：

- 登录后会话列表入口。
- session `16` 院校专业组模式工作台：方案、候选、组内专业、导出。
- session `17` 专业+大学模式工作台：筛选、排序、已选状态、导出。
- 新建专业+大学、院校专业组两种模式会话。
- 外部初始化接口创建会话后详情页学员姓名展示。
- Agent 对话的方案查询、预览、确认、执行。

## 9. 发布顺序

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

## 10. 发布后 smoke

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

## 11. 回滚

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
