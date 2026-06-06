# Release 3.0.3 Production Upgrade Plan

本文记录生产环境从 `prod-3.0.2` 升级到 `prod-3.0.3` 的部署准备、执行步骤、验证清单和回滚方案。目标是给线上运维/研发按本文直接执行升级；实际构建 hash、镜像 digest、执行时间和 smoke 结果需要在上线当天补齐。

## 1. 升级结论

`3.0.3` 是 `3.0.2` 之后的 Agent 效果、确认协议和方案操作稳定性版本。本次不是数据迁移大版本。

本次升级范围：

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| Backend `zhiyuan-server` | 是 | 显式偏好/约束状态、`pendingConfirmation` 工作区联动、权益 hotfix 合并后的稳定口径 |
| Web `zhiyuan-web` | 是 | 确认卡片、旧卡片置灰、处理中态、工作区视图保持、消息展示 |
| Agent `zhiyuan-agent` | 是 | 统一 `preview -> pendingConfirmation -> confirm -> apply`，只读/调整边界、回复质量和回归框架 |
| Rank `zhiyuan-rank` | 否 | 本轮没有 Rank 代码或模型数据变更，继续沿用生产现有容器 |
| 数据库结构 | 否 | 本轮无新增 DDL；`3.0.2` 已有行为事件表继续保留 |

本次升级不做：

- 不执行新的数据库 migration。
- 不重算历史方案。
- 不改 Rank 镜像。
- 不切换生产部署架构。
- 不配置 `gaotu.zhiyuan.volunteer-super-vip-only`；该全局开关已经废弃，不能进入 3.0.3 生产配置。
- 不在本轮迁移 Docker root 目录；`/var/lib/docker` 仍在根盘，迁移需要单独维护窗口停 Docker。

## 2. 发布标识

统一发布标识：

```text
prod-3.0.3
```

该标识用于：

- Git tag。
- 后端部署目录和 systemd service。
- Web 镜像 tag。
- Agent 镜像 tag。
- release 包目录和文件名。
- 生产执行记录。

正式构建前要求：

```bash
git status --short
git rev-parse HEAD
```

要求：

- 构建使用的代码必须是已提交 commit。
- `git status --short` 不应包含未提交运行时代码；上线执行记录类文档可在构建后补写 hash。
- 当前准备基线曾记录为 `07c7c4541bde35acdaa6d53224004606e3ec573a`，最终以上线前实际 tag 对应 commit 为准。

## 3. 当前 3.0.2 回滚点

生产当前回滚点以 `prod-3.0.2` 和 `docs/release-3.0.2-production-upgrade-plan.md` 的资产记录为准。

| 模块 | 当前回滚对象 |
| --- | --- |
| Git tag | `prod-3.0.2` |
| Backend | `zhiyuan-server-3.0.2-prod.service`，目录 `/root/work/zhiyuan-server-3.0.2` |
| Web | 容器 `zhiyuan-web-3.0.2-prod`，镜像 `zhiyuan-web:prod-3.0.2` / `zhiyuan-web:3.0.2-amd64` |
| Agent | 容器 `zhiyuan-agent-3.0.2-prod`，镜像 `zhiyuan-agent:prod-3.0.2` / `zhiyuan-agent:3.0.2-amd64` |
| Rank | `gaokao-volunteer-rank-prod`，继续沿用 |

升级前不要删除上述 service、容器、镜像和部署目录。

## 4. 数据库和状态兼容

`3.0.3` 不新增数据库表和字段。

需要确认：

- `3.0.2` 行为事件表 `assistant_planning_behavior_event` 已存在并可读写。
- `pendingConfirmation`、显式偏好和约束状态写入 extra-data / planning state JSON。
- 旧 `planEditCache` 仅作为兼容 adapter，3.0.3 新链路以 `pendingConfirmation` 为准。

回滚兼容说明：

- 因为没有 DDL，回滚不需要执行数据库结构回滚。
- 3.0.3 写入的 `pendingConfirmation` 等 extra-data 在 3.0.2 下可能无法完整展示新确认卡片，但不会破坏基础方案数据。
- 若回滚后出现旧会话残留待确认卡片造成用户误解，可以针对单会话清理 `pendingConfirmation`，不要全量删除 planning state。

## 5. 构建产物

常规建议是在本地或构建机生成产物并复制到生产机。

本次生产机实际执行时，Docker Hub 官方基础镜像拉取失败，已在生产机完成一次受控构建：Backend 直接 Maven 构建；Web/Agent 因依赖文件相对 `prod-3.0.2` 未变化，采用离线方式基于本机已有 `prod-3.0.2` 镜像替换 3.0.3 源码并重新构建/校验。该构建方式不切换服务、不重启线上容器。

### 5.1 Backend

构建：

```bash
cd zhiyuan-server
mvn clean package -DskipTests
```

生产运行目录使用稳定路径，不在路径中暴露版本号：

```text
/apps/zhiyuan-server-prod
```

版本号记录在 release 目录、备份目录、systemd 描述和镜像 tag 中。后续小版本升级优先替换稳定运行目录内的 jar/config，减少 systemd 路径变更。

目录内容：

```text
zhiyuan-server.jar
application-online.yml
logback-spring.xml
logs/
```

配置从 `3.0.2` 复制后复核，只调整目录、app name 和日志输出口径，不改生产连接信息。

生产机实际大盘挂载在 `/apps`，根盘空间较小。后端稳定运行目录、应用日志、GC 日志和 release/backup 产物都应落在 `/apps`，不要继续新增到 `/root/work`、`/tmp` 或根盘下的临时目录。

建议 systemd service：

```text
zhiyuan-server-3.0.3-prod.service
```

关键启动参数保持生产端口 `8090`：

```text
-Dapp_name=zhiyuan-server-3.0.3
-Dspring.profiles.active=online
-Dspring.config.location=/apps/zhiyuan-server-prod/application-online.yml
-Dlogging.config=/apps/zhiyuan-server-prod/logback-spring.xml
-Xloggc:/apps/zhiyuan-server-prod/logs/zhiyuan-server-3.0.3-gc.log
-jar /apps/zhiyuan-server-prod/zhiyuan-server.jar
--spring.flyway.enabled=false
```

日志配置要求：

- `logback-spring.xml` 的 `LOG_HOME` 需要指向 `/apps/zhiyuan-server-prod/logs`，或通过 `WorkingDirectory=/apps/zhiyuan-server-prod` 保证 `./logs` 落在 `/apps`。
- `application-online.yml` 不要继续使用 `mybatis-plus.configuration.log-impl: org.apache.ibatis.logging.stdout.StdOutImpl`。该配置会把 SQL 明细打到 stdout，并进入 `/var/log/messages`，当前生产根盘已经出现 `messages` 单文件数 GB 的风险。
- 推荐改为 `org.apache.ibatis.logging.slf4j.Slf4jImpl`，或直接移除 SQL stdout 明细输出；如需临时排查 SQL，必须限定窗口并在排查后恢复。

### 5.2 Web

生产 `/assistant-pc` 镜像必须使用 `APP_ENV=prod`，不要写成 `production`：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  -t zhiyuan-web:prod-3.0.3 \
  -t zhiyuan-web:3.0.3-amd64 \
  zhiyuan-web
```

正式生产镜像不要传以下本地覆盖参数：

```text
NEXT_PUBLIC_ASSISTANT_API_BASE_URL
NEXT_PUBLIC_AGENT_API_BASE_URL
NEXT_PUBLIC_OUTER_API_BASE_URL
NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE
```

构建后检查：

```bash
docker run --rm --entrypoint sh zhiyuan-web:prod-3.0.3 -lc \
  'grep -R "ws://localhost:8000" -n .next public 2>/dev/null; test $? -ne 0'

docker run --rm --entrypoint sh zhiyuan-web:prod-3.0.3 -lc \
  'grep -R "\"basePath\":\"/assistant-pc\"" -n .next/routes-manifest.json'
```

### 5.3 Agent

构建：

```bash
docker build --platform linux/amd64 \
  -t zhiyuan-agent:prod-3.0.3 \
  -t zhiyuan-agent:3.0.3-amd64 \
  zhiyuan-agent
```

构建后检查：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.0.3 -lc \
  'python -c "import app.server; print(\"agent_import_ok\")"'
```

Agent 生产环境变量沿用 `3.0.2`，重点复核：

```text
INTERNAL_SERVICE_URL=http://host.docker.internal:8090
RANK_SERVICE_URL=http://host.docker.internal:8092
LLM_BASE_URL=<脱敏>
LLM_MODEL_NAME=<脱敏>
LLM_API_KEY=<只在环境变量中配置，不写入文档>
```

当前 3.0.3 主模型以线上 `kimi-k2.6` 口径为准。回复质量优先于极限延迟，不为了降低延迟临时切到未验证模型。

### 5.4 Release 包

建议导出目录：

```text
/apps/releases/zhiyuan/3.0.3
```

建议内容：

```text
MANIFEST.txt
server/zhiyuan-server.jar
images/zhiyuan-web-prod-3.0.3-amd64.tar
images/zhiyuan-agent-prod-3.0.3-amd64.tar
docs/release-3.0.3-production-upgrade-plan.md
docs/release-3.0.3-summary-and-upgrade-plan.md
docs/release-3.0.3-agent-intent-plan-mutation-confirmation-design.md
```

本次生产机直接使用本地 Docker 镜像，不导出镜像 tar。若后续要跨机器迁移，再单独在 `/apps/releases/zhiyuan/<version>/images` 下导出镜像 tar 并补齐 hash。

## 6. 发布资产记录

实际构建后补齐：

| 资产 | 标签/路径 | 架构 | Hash / Digest |
| --- | --- | --- | --- |
| Git commit | `15c11ebf27b56daf76c4b7fa2f2b8b5a48b46c23` | - | 生产机实际构建 |
| Git tag | `prod-3.0.3` | - | 执行前用 `git rev-parse prod-3.0.3` 复核 |
| 后端 JAR | `zhiyuan-server/target/zhiyuan-server.jar` | `linux/amd64` | `sha256:6df5a3671f9447105202bc514c51e253fb5128adf48bcbff33695faa43cd5ed6` |
| Web 镜像 | `zhiyuan-web:prod-3.0.3` / `zhiyuan-web:3.0.3-amd64` | `linux/amd64` | image `sha256:5b7b6e932c5476ea4bb25a4b7bd59d868bf7e6fef9f82c35e9d83454f11e0b12`; tar 待导出后补齐 |
| Agent 镜像 | `zhiyuan-agent:prod-3.0.3` / `zhiyuan-agent:3.0.3-amd64` | `linux/amd64` | image `sha256:be4619a1bbf8892463b264d3b94eea473bad5437d8711d6ef6247484be1de5ed`; tar 待导出后补齐 |
| Release 包 | 不导出整包 tar | - | 本次生产机直接使用本地 JAR 和本地 Docker 镜像 |

记录命令：

```bash
shasum -a 256 zhiyuan-server/target/zhiyuan-server.jar
docker image inspect zhiyuan-web:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
docker image inspect zhiyuan-agent:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
```

更新规则：

- 只要重新打包 JAR、重新构建镜像或重新导出 release 包，就必须更新本节。
- 生产切换前以 hash/digest 为准，不以文件名或 tag 名称为准。

## 7. 发布前验证

### 7.1 已完成回归基线

当前本地记录：

| 模块 | 验证项 | 结果 |
| --- | --- | --- |
| Agent | `cd zhiyuan-agent && .venv/bin/python -m pytest tests -q` | `2367 passed, 8 skipped` |
| Agent live | 88 个真实对话派生场景 | `88/88 functional steps`；3 个 case 超过 100s，最长约 `182.7s` |
| Backend targeted | `mvn -Dtest=UserBizServiceTest,ChatSessionBizServiceTest test` | `16 tests, 0 failures, 0 errors` |
| Backend full | `mvn test` | sandbox 内唯一错误为本地 MySQL 连接限制；单独非 sandbox 复跑通过 |
| Rank | `.venv/bin/python -m unittest discover -s tests -v` | `11 tests, OK` |
| Web | `./node_modules/.bin/tsc --noEmit --pretty false` | 未通过，失败为既有 TS debt，不在 3.0.3 触达文件范围 |

上线前最低要求：

- Agent 单测全量通过。
- Backend 关键测试通过。
- 88 个 Agent live case 功能断言为 0 失败。
- Web 生产镜像构建通过，`/assistant-pc` basePath 检查通过。
- 前端人工走查通过。

### 7.2 本地开发态 smoke

适用：快速确认当前代码可运行。

```bash
bash scripts/start-all.sh
```

端口：

| 模块 | 地址 |
| --- | --- |
| Web | `http://127.0.0.1:3001/session` |
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

注意：不要直接执行 `next dev -p 3001`，否则可能沿用 `.next` 中的生产 basePath，导致静态资源或 `/session` 404。

### 7.3 本地类生产演练

适用：正式上线前验证生产构建方式、端口、basePath 和回滚口径。

建议端口：

| 模块 | 本地类生产端口 |
| --- | --- |
| Backend | `8090` |
| Web | `18088 -> 28688` |
| Agent | `18091 -> 8009` |
| Rank | `18092 -> 5001` 或沿用本地 Rank |

演练步骤：

1. 启动 `prod-3.0.2` 基线对象，确认 Backend、Web、Agent、Rank 健康。
2. 停止 3.0.2 Backend、Web、Agent，保留 Rank。
3. 启动 3.0.3 Backend、Web、Agent，端口保持不变。
4. 执行健康检查和业务 smoke。
5. 回滚到 3.0.2，确认回滚健康。

类生产健康检查：

```bash
ZHIYUAN_WEB_PORT=18088 \
ZHIYUAN_WEB_HEALTH_PATH=/assistant-pc/session \
ZHIYUAN_SERVER_PORT=8090 \
ZHIYUAN_AGENT_PORT=18091 \
ZHIYUAN_RANK_PORT=18092 \
bash ops/healthcheck.sh --local
```

本地功能验证注意：

- 正式 `prod-3.0.3` Web 镜像 rewrite 默认指向 `https://www.gaotuzhiyuan.com`。
- 如果要让本地 Web 镜像请求本地 Backend/Agent，必须单独构建 local-api 验证镜像，不覆盖正式 tag：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  --build-arg NEXT_PUBLIC_ASSISTANT_API_BASE_URL=http://host.docker.internal:8090 \
  --build-arg NEXT_PUBLIC_AGENT_API_BASE_URL=http://host.docker.internal:18091 \
  --build-arg NEXT_PUBLIC_OUTER_API_BASE_URL=https://www.gaotuzhiyuan.com \
  --build-arg NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=ws://host.docker.internal:18091 \
  -t zhiyuan-web:prod-3.0.3-local-api \
  zhiyuan-web
```

### 7.4 本地类生产演练记录

执行时间：2026-06-06。

本机类生产对象：

| 模块 | 对象 | 端口 | 结果 |
| --- | --- | --- | --- |
| Backend | `zhiyuan-server/target/zhiyuan-server.jar`，local profile | `8090` | 启动成功；Flyway 校验本地 schema version `5`，无新增 migration |
| Web | `zhiyuan-web:prod-3.0.3` | `18088 -> 28688` | 启动成功；`/assistant-pc/session` 返回 `200` |
| Agent | `zhiyuan-agent:prod-3.0.3` | `18091 -> 8009` | 启动成功；`/health` 返回 `200` |
| Rank | `zhiyuan-rank:prod-3.0.0` | `18092 -> 5001` | 启动成功；本轮不升级 Rank |

基础健康检查：

```text
ZHIYUAN_WEB_PORT=18088 \
ZHIYUAN_WEB_HEALTH_PATH=/assistant-pc/session \
ZHIYUAN_SERVER_PORT=8090 \
ZHIYUAN_AGENT_PORT=18091 \
ZHIYUAN_RANK_PORT=18092 \
bash ops/healthcheck.sh --local
```

结果：

```text
web local    PASS
server local PASS
agent local  PASS
rank local   PASS
failures=0
```

macOS 本机没有 systemd/nginx，`systemd server` 和 `nginx config` 为 `SKIP`，不影响本地类生产验证结论。

业务 smoke：

| 检查项 | 结果 |
| --- | --- |
| Backend `/gaotu-assistant-bot/base-data/province-city` | `200`，约 `0.797s` |
| Web `/assistant-pc/session` | `200`，约 `0.625s` |
| Agent `/health` | `200`，约 `0.475s` |
| `workspace-state?chatSessionId=16` | `200`，约 `3.828s`，`697026` bytes |
| `workspace-state?chatSessionId=17` | `200`，约 `3.828s`，`338214` bytes |
| `candidate-pool/filter-options?chatSessionId=17` | `200`，约 `3.137s`，`21125` bytes；包含 `schoolKeywords` |
| `ordered-plan/export?chatSessionId=17` | `200`，约 `5.132s`，`17305` bytes；文件识别为 Microsoft OOXML |

结构检查：

- `workspace-state` 返回包含 `constraintState`、`staleFlags`、`orderedPlanState`、`candidatePoolState`。
- Web 正式镜像检查通过：不包含 `ws://localhost:8000`，`routes-manifest.json` 包含 `basePath=/assistant-pc`。
- Agent 镜像 import 检查通过：`agent_import_ok`。

注意：

- 正式 `prod-3.0.3` Web 镜像 rewrite 指向 `https://www.gaotuzhiyuan.com`，因此本地业务接口 smoke 使用 `8090` 直连 Backend。
- 首次在 sandbox 内启动 Backend JAR 失败，原因是 sandbox 禁止 Java 连接本机 MySQL/Redis，错误为 `java.net.SocketException: Operation not permitted`；提升权限后同一 JAR 启动成功。
- Agent Docker 构建阶段现场拉取未锁依赖，受网络影响耗时较长；生产部署应使用已导出的 release 镜像 tar，不在生产机现场构建。

## 8. 生产发布顺序

建议低峰期执行，按 Backend -> Agent -> Web 的顺序切换。Rank 不动。

### 8.1 发布前只读巡检

```bash
uptime
free -h
df -h
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
systemctl status zhiyuan-server-3.0.2-prod.service --no-pager
curl -sS http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city >/dev/null
curl -sS http://127.0.0.1:8091/health
curl -sS http://127.0.0.1:8092/health
```

如果 CPU、内存、磁盘、数据库连接、后端 5xx 或 Agent 超时已经异常，暂停升级。

### 8.2 备份

至少备份：

```bash
BACKUP_DIR=/apps/upgrade-backup/zhiyuan/prod-3.0.2-$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

systemctl cat zhiyuan-server-3.0.2-prod.service \
  > "$BACKUP_DIR/zhiyuan-server-3.0.2-prod.service.txt"

docker inspect zhiyuan-web-3.0.2-prod \
  > "$BACKUP_DIR/zhiyuan-web-3.0.2-prod.inspect.json"

docker inspect zhiyuan-agent-3.0.2-prod \
  > "$BACKUP_DIR/zhiyuan-agent-3.0.2-prod.inspect.json"
```

数据库至少做结构和关键业务库备份。即使本轮无 DDL，也需要保留上线前恢复点。

### 8.3 上传和加载产物

生产机已存在本地镜像，不再导出或加载 tar：

```bash
docker image inspect zhiyuan-web:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
docker image inspect zhiyuan-agent:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
```

部署后端目录：

```bash
mkdir -p /apps/zhiyuan-server-prod/logs
cp /apps/releases/zhiyuan/3.0.3/server/zhiyuan-server.jar /apps/zhiyuan-server-prod/
cp /root/work/zhiyuan-server-3.0.2/application-online.yml /apps/zhiyuan-server-prod/
cp /root/work/zhiyuan-server-3.0.2/logback-spring.xml /apps/zhiyuan-server-prod/
```

复核：

```bash
shasum -a 256 /apps/zhiyuan-server-prod/zhiyuan-server.jar
docker image inspect zhiyuan-web:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
docker image inspect zhiyuan-agent:prod-3.0.3 --format '{{.Id}} {{.Architecture}}/{{.Os}}'
```

### 8.4 Backend 切换

创建并加载 `zhiyuan-server-3.0.3-prod.service`，确认启动参数只把 `3.0.2` 路径替换为 `3.0.3`。

切换：

```bash
systemctl stop zhiyuan-server-3.0.2-prod.service
systemctl start zhiyuan-server-3.0.3-prod.service
systemctl status zhiyuan-server-3.0.3-prod.service --no-pager
journalctl -u zhiyuan-server-3.0.3-prod.service -n 200 --no-pager
```

Backend smoke：

```bash
curl -sS http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city >/dev/null
curl -sS 'http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=<known-session-id>' >/dev/null
```

### 8.5 Agent 切换

Agent 依赖 Backend 的 pending/工作区接口，必须在 Backend smoke 通过后切换。

示例启动口径，以生产现有 `docker inspect` 为准补齐 env：

```bash
docker stop zhiyuan-agent-3.0.2-prod

docker run -d \
  --name zhiyuan-agent-3.0.3-prod \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -p 8091:8009 \
  --env-file /root/work/zhiyuan-agent-prod/.env \
  -e INTERNAL_SERVICE_URL=http://host.docker.internal:8090 \
  -e RANK_SERVICE_URL=http://host.docker.internal:8092 \
  zhiyuan-agent:prod-3.0.3
```

Agent smoke：

```bash
curl -sS http://127.0.0.1:8091/health
docker logs --tail 200 zhiyuan-agent-3.0.3-prod
```

### 8.6 Web 切换

Web 必须在 Backend 和 Agent 通过 smoke 后切换。

```bash
docker stop zhiyuan-web-3.0.2-prod

docker run -d \
  --name zhiyuan-web-3.0.3-prod \
  --restart unless-stopped \
  -p 88:28688 \
  zhiyuan-web:prod-3.0.3
```

Web smoke：

```bash
curl -I http://127.0.0.1:88/assistant-pc/session
docker logs --tail 200 zhiyuan-web-3.0.3-prod
```

## 9. 发布后业务 smoke

至少覆盖以下场景。

### 9.1 基础页面

- PC 登录后进入 `/assistant-pc/session`，不进入移动端抽屉页。
- 点击左上角高途志愿：PC 进入会话列表；高途渠道外跳官网逻辑保持原有行为。
- 打开 `/assistant-pc/sessionDetailV2?chatSessionId=<known-session-id>`。
- 工作台方案/候选 tab、筛选、导出按钮可用。

### 9.2 会话和方案

- 新建专业+大学模式会话。
- 新建院校专业组模式会话。
- 旧会话 `workspace-state` 能打开。
- 专业+大学模式导出为单个志愿单行，不按学校聚合。
- 院校专业组模式页面和导出组内专业顺序一致。
- 行为事件记录方案层动作和导出动作。

### 9.3 Agent 只读和确认链路

- “看看当前方案”只读分析，不生成调整卡片。
- “帮我审查一下当前方案”生成审查结果，不直接修改方案。
- “删除某个学校/专业/专业组”生成确认卡片，点击前不执行。
- “把某个志愿移动到第 N 位”生成确认卡片，点击前不执行。
- 卡片点击后进入处理中，成功后变为已采纳；旧卡片置灰不可再次点击。
- 用户只回复“确认/可以”时，只能消费当前 active pending，不执行历史动作。
- 无 active pending 时，确认类短文本不应触发修改。

### 9.4 意向、偏好和约束

- “不太想去江苏”作为软偏好，不应宣称物理缩小候选池。
- “不去江苏”作为硬要求，确认后进入后续过滤/排除参考。
- “想学传播学”作为正向偏好，卡片文案不能写降低优先级。
- 负向硬要求命中当前方案时，应披露命中项；是否删除当前方案需再走方案调整确认。
- 正向偏好/硬要求采纳后，工作区能刷新推荐系数和专家优选推荐参考。

### 9.5 外部接口和权益

- 外部初始化无版本路径和 `v1` 路径继续可用。
- 缺 `sex / strategyType` 仍能兜底创建，不导致方案数量异常放大。
- 学员姓名能展示在详情页标题中。
- `SUPER_VIP` 不受智能填报每日 2 次限制。
- 非 `SUPER_VIP` 的 `prepareType=VOLUNTEER` 每日 2 次限制保持生效。

## 10. 观察和告警

发布后至少观察 30 分钟：

```bash
journalctl -u zhiyuan-server-3.0.3-prod.service -f
docker logs -f zhiyuan-agent-3.0.3-prod
docker logs -f zhiyuan-web-3.0.3-prod
```

重点观察：

- 后端持续 5xx、数据库连接池异常、Redis 异常。
- `workspace-state`、导出、行为事件写入异常。
- Agent websocket 断连、LLM 请求失败、pending apply 失败。
- Agent 单轮超过 100s 的比例。当前已知 3 个 dialogue-derived case 出现约 180s 长尾，属于需要重点观察的 release risk。
- 前端静态资源 404、WebSocket 地址错误、确认卡片状态不同步。

建议发布后记录：

| 时间 | 检查项 | 结果 | 备注 |
| --- | --- | --- | --- |
| 待补 | Backend health | 待补 |  |
| 待补 | Agent health | 待补 |  |
| 待补 | Web `/assistant-pc/session` | 待补 |  |
| 待补 | 业务 smoke | 待补 |  |
| 待补 | 日志观察 | 待补 |  |

## 11. 回滚方案

### 11.1 回滚触发条件

出现以下情况之一，优先回滚或暂停继续切换：

- Backend 无法稳定启动或核心接口持续 5xx。
- Web 页面无法打开、静态资源大面积 404、登录主入口错误。
- Agent 大面积无法回复、websocket 连接失败、确认卡片点击普遍失败。
- 方案删除/移动/排序出现未确认即执行或确认后执行错对象。
- 外部初始化接口创建异常影响线上渠道联调。

### 11.2 Backend 回滚

```bash
systemctl stop zhiyuan-server-3.0.3-prod.service
systemctl start zhiyuan-server-3.0.2-prod.service
systemctl status zhiyuan-server-3.0.2-prod.service --no-pager
```

回滚后检查：

```bash
curl -sS http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city >/dev/null
curl -sS 'http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=<known-session-id>' >/dev/null
```

### 11.3 Agent 回滚

```bash
docker stop zhiyuan-agent-3.0.3-prod
docker start zhiyuan-agent-3.0.2-prod
curl -sS http://127.0.0.1:8091/health
```

如果 `3.0.2` 容器已被删除，用保留镜像重新启动，并沿用 3.0.2 的 env、端口和 `host.docker.internal` 配置。

### 11.4 Web 回滚

```bash
docker stop zhiyuan-web-3.0.3-prod
docker start zhiyuan-web-3.0.2-prod
curl -I http://127.0.0.1:88/assistant-pc/session
```

### 11.5 数据状态处理

- 不删除 `assistant_planning_behavior_event`。
- 不全量删除 `pendingConfirmation`。
- 如果单个会话出现旧 pending 卡片误展示，先记录 `chatSessionId`、用户输入、pending payload，再按单会话清理。
- 回滚后仍需观察 15-30 分钟，确认旧版本恢复稳定。

## 12. Go / No-Go 标准

可以上线：

- 3.0.3 代码已提交并打 `prod-3.0.3` tag。
- 后端 JAR、Web 镜像、Agent 镜像 hash/digest 已记录。
- 本地类生产演练通过。
- Agent 88 case 功能断言 0 失败；长尾 case 已列入观察项。
- 前端人工走查通过。
- 回滚对象和命令确认可用。

暂停上线：

- Web 生产镜像 basePath 或 rewrite 检查失败。
- Backend 核心测试失败且不能定位为环境问题。
- Agent 确认卡片、短文本确认或方案动作出现执行错对象。
- 外部初始化接口、权益日限或详情页学员姓名展示回退。
- 生产巡检时机器、数据库或线上错误率已异常。

## 13. 上线后执行记录

上线当天补齐：

| 项目 | 结果 |
| --- | --- |
| 执行时间 | 2026-06-06 21:58-22:13 CST |
| 执行人 | production server assisted deployment |
| Git commit | `15c11ebf27b56daf76c4b7fa2f2b8b5a48b46c23` |
| Git tag | `prod-3.0.3` |
| 后端 JAR sha256 | `6df5a3671f9447105202bc514c51e253fb5128adf48bcbff33695faa43cd5ed6` |
| Web image digest | `sha256:5b7b6e932c5476ea4bb25a4b7bd59d868bf7e6fef9f82c35e9d83454f11e0b12` |
| Agent image digest | `sha256:be4619a1bbf8892463b264d3b94eea473bad5437d8711d6ef6247484be1de5ed` |
| Release 包 sha256 | 不导出 release tar，直接使用本地 JAR 和本地镜像 |
| Backend 切换时间 | 2026-06-06 22:00 CST |
| Agent 切换时间 | 2026-06-06 22:09 CST；首次因 env-file 漏 `LLM_*` 回滚到 3.0.2，补齐 LLM/Bocha 后成功 |
| Web 切换时间 | 2026-06-06 22:11 CST |
| smoke 结果 | Backend 200、Agent health 200、Web 本地与域名入口 200、workspace-state 200 |
| 是否回滚 | 未整体回滚；Agent 首次启动失败后临时恢复 3.0.2，再成功切 3.0.3 |
| 遗留观察项 | 继续观察 Agent 长尾、Bocha web search 实际调用、Backend Druid idle WARN；保留 stopped 3.0.2 容器用于快速回滚 |
