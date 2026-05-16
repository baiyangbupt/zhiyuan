# Release 3.0.1 Production Deployment Plan

本文档记录当前生产环境从 `prod-3.0.0` 升级到 `3.0.1` 的部署计划。当前 `prod-3.0.0` 已在线上运行，本次升级基于本地 `/root/dev/zhiyuan` 仓库当前 `develop` 分支代码。

## 1. 升级结论

`3.0.1` 是 `prod-3.0.0` 之后的稳定修复版本，不是迁移大版本。升级目标是修复 Web 工作台、方案调整、导出、候选状态提示和 Agent 对话操作的稳定性问题。

本次升级范围：

- 后端 `zhiyuan-server`：需要升级。
- 前端 `zhiyuan-web`：需要升级。
- Agent `zhiyuan-agent`：需要升级。
- Rank 服务：无代码变更，不升级。
- 数据库结构：无新增 migration，本次不执行数据库结构变更。

本次升级不做：

- 不重跑历史方案全量迁移。
- 不改 Rank 服务镜像。
- 不改生产数据库 schema。
- 不切换 LLM provider/model/key。
- 不调整整体部署架构。

## 2. 当前生产运行态

当前生产服务器上 `3.0.0` 运行状态：

| 模块 | 当前运行对象 | 端口 | 说明 |
| --- | --- | --- | --- |
| 后端 | `zhiyuan-server-3.0.0-prod.service` | `8090` | systemd 运行，profile 为 `online` |
| 前端 | `zhiyuan-web-3.0.0-prod` | `88 -> 28688` | 镜像 `zhiyuan-web:3.0.0-amd64-wsfix` |
| Agent | `zhiyuan-agent-3.0.0-prod` | `8091 -> 8009` | 镜像 `zhiyuan-agent:3.0.0-amd64` |
| Rank | `gaokao-volunteer-rank-prod` | `8092 -> 5001` | 继续沿用现有镜像 |

当前后端启动参数关键点：

```text
/usr/bin/java -Xms2048m -Xmx2048m
-Dapp_name=zhiyuan-server-3.0.0
-Dspring.profiles.active=online
-Dspring.config.location=/root/work/zhiyuan-server-3.0.0/application-online.yml
-Dlogging.config=/root/work/zhiyuan-server-3.0.0/logback-spring.xml
-jar /root/work/zhiyuan-server-3.0.0/zhiyuan-server.jar
--spring.flyway.enabled=false
```

升级前应先只读检查机器状态：

```bash
uptime
free -h
df -h
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
systemctl status zhiyuan-server-3.0.0-prod.service --no-pager
```

若 load、内存、磁盘或线上错误率异常，暂停升级。

## 3. 3.0.1 变更范围

相对线上 `prod-3.0.0` 基线，当前 3.0.1 主要变更集中在：

- `docs`：发布计划、稳定性计划、实施设计和升级记录。
- `zhiyuan-server`：规划工作台状态、导出兼容、排序/移动/组级操作、候选状态、行为事件。
- `zhiyuan-web`：`sessionDetailV2` 工作台交互、返回列表、排序/移动/组级操作、状态展示、生产 WebSocket 配置。
- `zhiyuan-agent`：方案操作对话、排序/移动/删除确认链路、去“草稿”语言、结构化日志和回归样例。

已确认：

- `pom.xml` 无依赖变化。
- `package.json` / `package-lock.json` 无依赖变化。
- `pyproject.toml` 无依赖变化。
- 未新增数据库 migration。
- `zhiyuan-web/.env.prod` 包含生产 WebSocket 配置：

```text
NEXT_PUBLIC_AGENT_WS_BASE=wss://www.gaotuzhiyuan.com
```

## 4. 构建和验证

### 4.0 高途权限后端热发布准备

如果本次只发布“高途渠道用户权限管理”能力，发布范围可以收敛为后端 `zhiyuan-server`：

- 不升级 `zhiyuan-web`。
- 不升级 `zhiyuan-agent`。
- 不升级 `zhiyuan-rank`。
- 不执行数据库 schema 变更。
- 生产启动参数继续保留 `--spring.flyway.enabled=false`。

当前后端热发布包：

```text
/tmp/zhiyuan-release-3.0.1-gaotu-permission-59a9fce.tar.gz
```

包内关键文件：

```text
MANIFEST.txt
server/zhiyuan-server.jar
docs/gaotu-user-permission-management.md
docs/release-3.0.1-production-deployment-plan.md
docs/release-3.0.1-implementation-design.md
```

构建来源：

```text
branch=develop
commit=59a9fce
jar_sha256=9a6f87ec2b12f560d55eaef7ddad998567815f8d44e2eacc3f8e4ef602d8d3bb
```

发布前本地验证：

```bash
cd zhiyuan-server
mvn -Dtest=UserBizServiceTest,UserAdminControllerTest test
mvn -DskipTests package
```

已覆盖：

- 高途 `userType=1` 映射为 `VIP`。
- `VIP` 默认 `createSessionLimit=500`。
- `checkRights(CreateSession)` 在已建 499 次时允许、500 次时拒绝。
- 后台按 `memberId` 查询、调整、同步高途权益。
- 找不到本地高途用户时返回业务错误，不再空指针。

生产上线后 smoke：

```bash
# 基础接口
curl -I "http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city"

# 按高途 memberId 查询本系统用户
curl -X GET \
  "http://127.0.0.1:8090/gaotu-assistant-bot/admin/user/gaotu-user?memberId={memberId}&channel=gaotu"

# 按高途权益同步用户等级和限制
curl -X POST \
  "http://127.0.0.1:8090/gaotu-assistant-bot/admin/user/fix-gaotu-user-level?memberId={memberId}&channel=gaotu"
```

生产注意事项：

- `/admin/**` 当前不经过普通登录拦截器，必须确认只能从内网、Nginx allowlist 或运维入口访问。
- 已有 VIP 用户需要重新 token 登录、调用 `fix-gaotu-user-level`，或调用 `update-gaotu-user-level` 后才会刷新到 500。
- 本次仍是建会话总量限制，不是按天限制；智能填报每天 2 个会话的规则仅作为 TODO 记录。

### 4.1 后端验证

在发布包构建前执行后端重点测试：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -Dtest=PlanningExcelExportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test
```

重点覆盖：

- 导出 Excel 序号连续。
- 历史迁移方案导出 ID 兼容。
- 候选状态和空候选/少候选提示。
- 排序、移动、专业组操作。
- 工作台状态派生。

### 4.2 前端验证

执行生产构建：

```bash
cd /root/dev/zhiyuan/zhiyuan-web
npm run build:prod
```

构建后检查：

- 不包含 `ws://localhost:8000`。
- `NEXT_PUBLIC_API_BASE_URL=https://www.gaotuzhiyuan.com`。
- `NEXT_PUBLIC_AGENT_WS_BASE=wss://www.gaotuzhiyuan.com`。
- `/assistant-pc/session` 和 `/assistant-pc/sessionDetailV2` 路由仍可用。

### 4.3 Agent 验证

执行 Agent 单测：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
PYTHONPATH=$(pwd) .venv/bin/pytest
```

重点覆盖：

- 方案现状查询。
- 方案排序 preview -> confirm -> apply。
- 专业组移动和删除。
- 去“草稿”用户话术。
- 旧 router/workflow 兼容路径不误用。

本地发布前复核记录：

- `pytest` 直接使用系统入口时可能因为 `tests` 命名空间或 Python 环境不一致失败；本地应优先使用项目 `.venv/bin/pytest`。
- 2026-05-16 已完成 Agent 测试基线收口：`PYTHONPATH=/Users/baiyang/git/zhiyuan/zhiyuan-agent .venv/bin/pytest -q` 结果为 `2121 passed / 7 skipped`。
- 真实内部服务 e2e 和真实 LLM e2e 默认跳过，避免发布门禁被网络、模型费用或外部服务状态干扰。需要单独执行时设置：
  - `RUN_AGENT_INTERNAL_E2E=1`：执行真实 internal client e2e。
  - `RUN_REAL_LLM_E2E=1`：执行真实 LLM e2e。
- Agent 测试修复边界：兼容 pydantic-ai 新版 `message_history` 对象格式；画像读取兼容历史 `dataValue` payload；catalog 归一化测试隔离缓存；旧 pin/unpin 只验证新版固定/锁定入口关闭后的提示。

如具备真实测试会话和模型配置，可补充 websocket smoke：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
python examples/dialog_regression_runner.py examples/dialog_regression_301_agent_smoke_cases.json
```

## 5. 产物和命名

建议不要覆盖 `3.0.0` 产物，保留明确回滚点。

### 5.1 后端

建议目录：

```text
/root/work/zhiyuan-server-3.0.1
```

目录内容：

```text
zhiyuan-server.jar
application-online.yml
logback-spring.xml
logs/
```

配置从 `3.0.0` 复制后复核，不改业务连接信息。

建议新增 systemd service：

```text
zhiyuan-server-3.0.1-prod.service
```

启动参数保持与 `3.0.0` 一致，仅调整目录和 app name：

```text
-Dapp_name=zhiyuan-server-3.0.1
-Dspring.config.location=/root/work/zhiyuan-server-3.0.1/application-online.yml
-Dlogging.config=/root/work/zhiyuan-server-3.0.1/logback-spring.xml
-jar /root/work/zhiyuan-server-3.0.1/zhiyuan-server.jar
--spring.flyway.enabled=false
```

### 5.2 前端

建议镜像：

```text
zhiyuan-web:3.0.1-amd64
```

本仓库 Dockerfile 的 `APP_ENV` 是 npm script 后缀，不是 Next.js 运行环境名。生产 `/assistant-pc` 镜像构建必须使用 `APP_ENV=prod`，由 `npm run build:prod` 读取 `.env.prod` 后再把 Next.js 的 `APP_ENV` 设置为 `production`：

```bash
docker build --platform linux/amd64 \
  --build-arg APP_ENV=prod \
  -t zhiyuan-web:3.0.1-amd64 \
  zhiyuan-web
```

不要使用 `--build-arg APP_ENV=production`，否则 Dockerfile 会执行不存在的 `npm run build:production`。

建议容器：

```text
zhiyuan-web-3.0.1-prod
```

端口保持：

```text
88 -> 28688
```

### 5.3 Agent

建议镜像：

```text
zhiyuan-agent:3.0.1-amd64
```

构建命令：

```bash
docker build --platform linux/amd64 \
  -t zhiyuan-agent:3.0.1-amd64 \
  zhiyuan-agent
```

当前 Agent Dockerfile 基于未锁定的 Python 依赖范围构建，会拉取当前最新兼容依赖。后续部署优化建议补充锁文件或约束关键依赖版本，避免同一代码在不同时间构建出不同依赖组合。

建议容器：

```text
zhiyuan-agent-3.0.1-prod
```

端口保持：

```text
8091 -> 8009
```

Agent 环境变量沿用当前生产配置，重点确认：

```text
INTERNAL_SERVICE_URL=http://host.docker.internal:8090
RANK_SERVICE_URL=http://host.docker.internal:8092
```

LLM 配置不在本次升级中变更。记录配置时必须脱敏 API Key。

## 6. 发布顺序

本次升级建议在低峰期执行，按以下顺序推进。

### 6.1 发布前巡检

```bash
uptime
free -h
df -h
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
systemctl status zhiyuan-server-3.0.0-prod.service --no-pager
curl -sS http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=<known-session-id>
```

同时确认：

- 当前服务无异常重启。
- 后端日志没有持续 5xx 或数据库连接异常。
- Agent `/health` 正常。
- 前端页面可访问。
- Rank `8092` 正常。

### 6.2 后端升级

推荐优先准备 `3.0.1` 后端 service，但不立即删除 `3.0.0`。

如果只能占用 `8090`，执行低峰短暂停机切换：

1. 停止 `zhiyuan-server-3.0.0-prod.service`。
2. 启动 `zhiyuan-server-3.0.1-prod.service`。
3. 立即检查 `8090` 健康接口和核心接口。
4. 观察日志 3-5 分钟。

切换后检查：

```bash
systemctl status zhiyuan-server-3.0.1-prod.service --no-pager
journalctl -u zhiyuan-server-3.0.1-prod.service -n 200 --no-pager
curl -sS http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=<known-session-id>
```

### 6.3 Agent 升级

Agent 3.0.1 依赖新版后端接口和新版方案操作语义，应在后端成功后升级。

流程：

1. 保留当前 `zhiyuan-agent-3.0.0-prod` 容器或镜像。
2. 使用 `zhiyuan-agent:3.0.1-amd64` 启动新容器。
3. 端口保持 `8091 -> 8009`。
4. 检查 `/health`。
5. 用测试会话验证 websocket 对话。

检查：

```bash
curl -sS http://127.0.0.1:8091/health
docker logs --tail 200 zhiyuan-agent-3.0.1-prod
```

### 6.4 前端升级

前端必须和后端、Agent 同步升级，否则会出现新接口不可用或对话工作台联动不一致。

流程：

1. 保留 `zhiyuan-web-3.0.0-prod` 容器或镜像。
2. 使用 `zhiyuan-web:3.0.1-amd64` 启动新容器。
3. 端口保持 `88 -> 28688`。
4. 检查页面和静态资源。
5. 检查 websocket 请求走 `wss://www.gaotuzhiyuan.com`。

检查：

```bash
curl -I http://127.0.0.1:88/assistant-pc/session
docker logs --tail 200 zhiyuan-web-3.0.1-prod
```

## 7. 发布后冒烟

至少覆盖以下场景：

### 7.1 页面和登录

- 官网 token 入口登录正常：

```text
/login?channel=gaotu&token=<token>
```

- `/assistant-pc/session` 能打开。
- `/assistant-pc/sessionDetailV2` 能打开。
- B 端详情页有返回会话列表入口。

### 7.2 新建会话

- 新建 `major` 模式会话，方案初始化正常。
- 新建 `majorGroup` 模式会话，方案初始化正常。
- 候选为空时有明确提示，不显示“成功生成空方案”。
- 专项计划、批次、偏好过窄等样本提示合理。

### 7.3 历史会话

- `_final` 历史已提交方案展示正常。
- `_temp` 历史未提交方案展示正常。
- 无后缀 original 仅作为兜底参考，不误判为已提交方案。
- 历史方案导出不丢院校和专业明细。

### 7.4 方案操作

- 方案排序：录取率、院校层次、推荐系数。
- 单条移动：移动到第 N 位、顶部、底部。
- 专业组移动：整组移动，组内专业不打散。
- 专业组删除：不残留孤立专业。
- 操作后审查状态变为待重新审查。

### 7.5 审查和导出

- 手动触发审查正常。
- 审查结果展示正常。
- 导出 Excel 序号从 1 连续递增。
- 页面顺序与导出顺序一致。
- 学校、专业、计划、学费、学制、选科、历史分数尽量回填。

### 7.6 Agent 对话

- “看看当前方案”返回正常，不触发无意义工作台卡片。
- “按录取率排序”能先预览，确认后执行。
- “把第 3 个专业组移到第 5 位”能预览并执行。
- “删除这个专业组”能预览并执行。
- 回复中不出现面向用户的“草稿/排序区/画像”等旧话术。

## 8. 观察期

发布后建议至少观察 30 分钟：

```bash
journalctl -u zhiyuan-server-3.0.1-prod.service -f
docker logs -f zhiyuan-agent-3.0.1-prod
docker logs -f zhiyuan-web-3.0.1-prod
```

重点观察：

- 后端 5xx。
- 数据库连接池异常。
- `candidate_pool_empty` 是否集中出现。
- 导出接口异常。
- Agent websocket 超时。
- Agent LLM 请求失败或耗时异常。
- 前端静态资源或 websocket 地址错误。

## 9. 回滚方案

### 9.1 回滚原则

- 不删除 3.0.0 service、容器和镜像。
- 不修改数据库 schema，因此回滚不需要数据库回滚。
- 如果 3.0.1 已写入新的 planningState 字段，3.0.0 读取旧字段仍应能兼容；如发现兼容风险，优先回滚前端和 Agent，保留后端观察。

### 9.2 后端回滚

```bash
systemctl stop zhiyuan-server-3.0.1-prod.service
systemctl start zhiyuan-server-3.0.0-prod.service
systemctl status zhiyuan-server-3.0.0-prod.service --no-pager
```

### 9.3 Agent 回滚

停止 `3.0.1` 容器，恢复 `3.0.0` 容器或用旧镜像重新启动：

```text
zhiyuan-agent:3.0.0-amd64
```

端口仍保持：

```text
8091 -> 8009
```

### 9.4 前端回滚

停止 `3.0.1` 容器，恢复旧容器或用旧镜像重新启动：

```text
zhiyuan-web:3.0.0-amd64-wsfix
```

端口仍保持：

```text
88 -> 28688
```

## 10. 风险点

1. 前端、后端、Agent 必须在同一发布窗口升级。单独升级任一模块都可能出现接口或语义不一致。
2. 3.0.1 新增工作台操作接口，旧前端看不到新状态，新前端依赖新后端。
3. Agent 对话操作依赖新版后端接口和新版 action schema，不能只升 Agent。
4. 空候选提示是本版重点，发布后要观察是否有批量出现，尤其四川专项计划、批次边界和偏好过窄样本。
5. 导出修复是核心验收项，必须用历史迁移会话和新建会话都验证。
6. 移动端不是本版本完整适配范围；如果共享样式影响移动端，需要至少做冒烟。

## 11. 本地生产式升级演练记录

执行时间：2026-05-16。

本机环境：

- macOS + Docker Desktop。
- Docker daemon 架构为 `aarch64`，生产目标为 `amd64`，因此镜像构建显式使用 `--platform linux/amd64`。
- 本地演练端口：后端 `8090`，Web `18088 -> 28688`，Agent `18091 -> 8009`，Rank `18092 -> 5001`。
- Rank 沿用 `zhiyuan-rank:prod-3.0.0`，符合本次 3.0.1 不升级 Rank 的发布范围。

构建和测试结果：

- 后端重点测试通过：`mvn -Dtest=PlanningExcelExportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest test`，结果 `104 run / 0 failures / 0 errors / 2 skipped`。
- 后端 3.0.1 JAR 构建通过：`mvn -DskipTests package`。
- 前端生产构建通过：`npm run build:prod`；产物 `basePath=/assistant-pc`，包含 `/session`、`/sessionDetailV2`、`/sessionDetailLegacy`。
- 前端 3.0.1 amd64 镜像构建通过：`docker build --platform linux/amd64 --build-arg APP_ENV=prod -t zhiyuan-web:prod-3.0.1 -t zhiyuan-web:3.0.1-amd64 zhiyuan-web`。
- Agent 3.0.1 amd64 镜像构建通过：`docker build --platform linux/amd64 -t zhiyuan-agent:prod-3.0.1 -t zhiyuan-agent:3.0.1-amd64 zhiyuan-agent`。
- Agent 全量 pytest 已收口，详见 4.3；真实 internal/LLM e2e 改为显式开关执行，不进入默认离线发布门禁。

升级流程验证：

1. 使用 `prod-3.0.0` git tag 在临时 worktree 构建 3.0.0 后端 JAR。
2. 启动 3.0.0 基线：后端 `8090`、Web `zhiyuan-web:prod-3.0.0`、Agent `zhiyuan-agent:prod-3.0.0`、Rank `zhiyuan-rank:prod-3.0.0`。
3. 基线健康检查通过：
   - 后端 `GET /gaotu-assistant-bot/base-data/province-city` 返回 `200`，约 `0.86s`。
   - Rank `GET /health` 返回 `200`，约 `0.05s`。
   - Agent `GET /health` 返回 `200`，约 `0.04s`。
   - Web `GET /assistant-pc/session` 返回 `200`。
4. 停止 3.0.0 后端、Web、Agent，保留 Rank。
5. 启动 3.0.1 后端、Web、Agent。
6. 3.0.1 健康检查通过：
   - 后端 `GET /gaotu-assistant-bot/base-data/province-city` 返回 `200`，约 `0.44s`。
   - Rank `GET /health` 返回 `200`，约 `0.04s`。
   - Agent `GET /health` 返回 `200`，约 `0.05s`。
   - Web `GET /assistant-pc/session`、`/assistant-pc/sessionDetailV2`、`/assistant-pc/sessionDetailLegacy` 均返回 `200`。
   - 3.0.1 Web 镜像内未检出 `ws://localhost:8000`，`.next/routes-manifest.json` 中 `basePath=/assistant-pc`。
7. 回滚演练通过：停止 3.0.1 后端、Web、Agent 后，恢复 3.0.0 后端、Web、Agent，后端/Agent/Web 健康检查均返回 `200`。

演练发现的问题：

- `ops/healthcheck.sh --local` 默认检查 Web 根路径 `/`，对正式生产 `/assistant-pc` 包会误报 `404`。本次已为脚本补充 `ZHIYUAN_WEB_HEALTH_PATH` 覆盖项，生产式本地演练应设置为 `/assistant-pc/session`。
- 发布文档中如果写 `--build-arg APP_ENV=production` 会导致 Docker 构建失败，已更正为 `APP_ENV=prod`。
- Agent 默认全量 pytest 已通过；真实 internal/LLM e2e 已拆为显式开关，发布前按依赖条件单独补跑。
- 本地 macOS 不能复刻 systemd，后端用前台 Java 进程模拟；生产仍按 systemd service 执行。

## 12. 本地开发 e2e 验证记录

执行时间：2026-05-16。

本地开发服务端口：

- Web：`3001`
- Backend：`8080`
- Agent：`8000`
- Rank：`5001`

正确启动方式：

```bash
bash scripts/start-all.sh
```

或单独启动 Web：

```bash
cd zhiyuan-web
npm run dev
```

注意：Web 必须通过 `npm run dev` 读取 `.env.dev`，确保 `APP_ENV=dev`。如果直接执行 `next dev -p 3001`，会沿用 `.next` 中的生产 `basePath=/assistant-pc` 和线上 rewrites，本地访问 `/session`、`/sessionDetailV2` 会出现 `404` 或错误代理。

本地健康检查命令：

```bash
ZHIYUAN_WEB_PORT=3001 \
ZHIYUAN_WEB_HEALTH_PATH=/session \
ZHIYUAN_SERVER_PORT=8080 \
ZHIYUAN_AGENT_PORT=8000 \
ZHIYUAN_RANK_PORT=5001 \
bash ops/healthcheck.sh --local
```

验证结果：

- `web local`、`server local`、`agent local`、`rank local` 均通过。
- macOS 本地 Docker daemon 不可达时，`compose ps` 记录为 `WARN`，不阻断纯本地服务 e2e；生产式 Docker 演练仍应单独确认 compose 状态。
- Web 路由验证通过：`GET /session` 返回 `200`，`GET /sessionDetailV2` 返回 `200`。
- Internal client e2e 通过：`RUN_AGENT_INTERNAL_E2E=1 PYTHONPATH=/Users/baiyang/git/zhiyuan/zhiyuan-agent .venv/bin/pytest tests/e2e/test_internal_client.py -q -s`，结果 `2 passed`。
- 真实 LLM e2e 通过：`RUN_REAL_LLM_E2E=1 PYTHONPATH=/Users/baiyang/git/zhiyuan/zhiyuan-agent .venv/bin/pytest tests/e2e/test_real_llm.py -q -s`，结果 `4 passed / 1 skipped`。
- 真实 WebSocket smoke 通过：`PYTHONPATH=/Users/baiyang/git/zhiyuan/zhiyuan-agent .venv/bin/python examples/dialog_regression_runner.py --cases examples/dialog_regression_301_agent_smoke_cases.json --response-timeout 180`。

WebSocket smoke 覆盖：

- `session=17 / 看看现在的方案`：约 `16.2s`，返回结构化方案概况，无无效工作台卡片。
- `session=17 / 帮我审查一下`：约 `16.0s`，返回审查风险和下一步建议。
- `session=16 / 按院校层次排序 -> 确认`：预览约 `23.3s`，确认约 `5.5s`，返回 `ordered` 刷新卡片。
- `session=16 / 把第3个专业组移到第5位 -> 确认`：预览约 `32.1s`，确认约 `6.3s`，返回 `ordered` 刷新卡片。

补充接口 smoke：

- 工作区轻量状态：
  - `GET /gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=16` 返回 `200`，专业组模式，`orderedItems=176`，`orderedUnits=45`，引用候选评分字段无缺失。
  - `GET /gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=17` 返回 `200`，专业模式，`orderedItems=94`，位置连续，引用候选评分字段无缺失。
- 导出：
  - `POST /gaotu-assistant-bot/inner/planning/1/session/ordered-plan/export?chatSessionId=16` 返回 `200`，生成 xlsx `26058` bytes。
  - `POST /gaotu-assistant-bot/inner/planning/1/session/ordered-plan/export?chatSessionId=17` 返回 `200`，生成 xlsx `17757` bytes。
- 审查：
  - `POST /gaotu-assistant-bot/inner/planning/1/session/review/run?chatSessionId=17` 返回 `200`，`status=completed`，审查结果 `9 passed / 1 warn / 3 risk`。
- 候选查询：
  - `POST /gaotu-assistant-bot/inner/planning/1/session/candidate-pool/query?chatSessionId=16` 返回 `200`，首页 `10` 条，`total=6421`。
  - `POST /gaotu-assistant-bot/inner/planning/1/session/candidate-pool/query?chatSessionId=17` 返回 `200`，首页 `10` 条，`total=402`。

未完成项：

- 外部系统初始化新建会话接口 `POST /gaotu-assistant-bot/chat/1/integration/session/initialize` 需要 `tk/pf` 登录态。当前本地没有可用授权 token，未执行真实新建；拿到可用 `loginToken` 后需补跑：初始化创建、幂等重试、返回 URL、workspace-state、导出。

## 13. 发布准入清单

发布前必须满足：

- 后端重点测试通过。
- Agent 离线单元/回归发布子集通过；真实 e2e/LLM smoke 在依赖齐备时单独执行并记录。
- 前端生产构建通过。
- 3.0.1 产物已放到独立目录或独立镜像标签。
- 后端生产配置已复核，未误改数据库、Redis、OSS、Rank、Gaotu 上游地址。
- Agent 生产配置已复核，API Key 不记录明文。
- 前端生产 WebSocket 地址为 `wss://www.gaotuzhiyuan.com`。
- 3.0.0 回滚 service、容器和镜像仍保留。
- 已准备至少一个新建会话样本、一个历史 `_final` 样本、一个历史 `_temp` 样本、一个空候选/少候选样本做发布后验证。

## 14. 相关文档

- `docs/release-3.0.1-stability-plan.md`
- `docs/release-3.0.1-implementation-design.md`
- `docs/release-3.0.1-current-state-and-optimization-roadmap.md`
- `docs/release-3.0.1-agent-optimization-design.md`
- `docs/production-upgrade-implementation-steps.md`
- `docs/legacy-to-v2-upgrade-migration-status.md`
