# 系统健康检查与运维工具设计

本文档用于补齐当前智愿系统的系统层健康检查、运维工具和部署优化设计。目标是在 V2 迁移灰度阶段，让服务状态、依赖状态、迁移状态和发布结果可以被快速判断、快速回滚。

当前线上拓扑参考 `docs/zhiyuan-yttell-deployment-notes.md`：

- `zhiyuan-web`：Docker Compose，宿主 `3000 -> 28688`
- `zhiyuan-agent`：Docker Compose，宿主 `8000 -> 8009`
- `zhiyuan-rank`：Docker Compose，宿主 `5001 -> 5001`
- `zhiyuan-server`：systemd，宿主 `8090`
- Nginx：统一代理公网 `zhiyuan.ytell.cn`

本地已有 `scripts/start-all.sh`、`scripts/stop-all.sh`、`scripts/status.sh`、`scripts/logs.sh`，适合开发机联调。线上还需要一套更面向发布和排障的健康检查与运维脚本。

## 1. 当前缺口

### 1.1 健康检查缺口

- Docker Compose 里 `zhiyuan-web`、`zhiyuan-rank`、根目录 `zhiyuan-agent` 当前没有统一 healthcheck。
- 后端 systemd 只保证进程存活，不保证数据库、Redis、Agent、Rank、OSS 等依赖可用。
- Nginx 只做反向代理，没有发布后自动端到端检查。
- 迁移灰度期间缺少一条命令汇总 `legacyPlanImport` 成功率和失败原因。

### 1.2 运维工具缺口

- 本地脚本按 PID 管理，线上实际是 Docker Compose + systemd 混合管理，两套命令不统一。
- 缺少统一的 `ops status` 输出：容器状态、systemd 状态、端口、HTTP、WebSocket、DB、Redis、磁盘、日志错误摘要。
- 缺少发布前检查和发布后检查脚本。
- 缺少标准回滚动作封装。

### 1.3 部署逻辑缺口

- 当前部署形态混合：web/agent/rank 在 Docker Compose，server 在 systemd。短期可以接受，但发布步骤需要文档化和脚本化。
- 前端部署为了根路径访问使用 `APP_ENV=dev` 规避 `basePath=/assistant-pc`，这是可用但容易误配的策略，后续应收口为明确的 `APP_ENV=deploy` 且 `basePath` 可配置。
- 发布依赖人工执行多条命令，缺少可重复的 release 标识、构建产物备份和一键回滚。

## 2. 健康检查分层设计

健康检查分为四层：进程层、接口层、依赖层、业务层。

### 2.1 进程层

检查每个服务是否运行、端口是否监听：

| 服务 | 进程/容器检查 | 端口 |
| --- | --- | --- |
| web | `docker compose ps zhiyuan-web` | `3000` |
| agent | `docker compose ps zhiyuan-agent` | `8000` |
| rank | `docker compose ps zhiyuan-rank` | `5001` |
| server | `systemctl is-active zhiyuan-server.service` | `8090` |
| nginx | `systemctl is-active nginx` 或 `nginx -t` | `80/443` |

### 2.2 接口层

建议每个服务提供轻量健康接口：

| 服务 | 建议接口 | 检查内容 |
| --- | --- | --- |
| web | `GET /` | 页面可返回 HTML |
| server | `GET /gaotu-assistant-bot/actuator/health` 或新增 `/gaotu-assistant-bot/health` | Spring 进程、DB、Redis、Agent、Rank |
| agent | `GET /gaotu-assistant-agent/health` | FastAPI 进程、模型配置、backend 连通性 |
| rank | `GET /gaokao-volunteer-rank/health` | Flask 进程、模型/数据加载状态 |

如果短期不能新增标准 health endpoint，运维脚本可先用现有可达接口替代，但应统一返回口径：

```json
{
  "status": "UP",
  "service": "zhiyuan-server",
  "version": "git-sha-or-release",
  "checks": {
    "mysql": "UP",
    "redis": "UP",
    "agent": "UP",
    "rank": "UP"
  }
}
```

### 2.3 依赖层

后端依赖检查至少包括：

- MySQL 可连接、当前库可查询。
- Redis 可 ping。
- Agent WebSocket/HTTP 基础可达。
- Rank 服务基础可达。
- OSS 配置存在，老方案目录可读。
- `gaotu.zhiyuan.temp-data-path` 存在且可读写。
- MySQL `max_allowed_packet` 达到迁移要求。

Agent 依赖检查至少包括：

- LLM 配置存在：`LLM_BASE_URL`、`LLM_MODEL_NAME`。
- Backend URL 可达。
- `data/` 静态资源可读。
- `HISTORY_DB_PATH` 所在目录可写。

Rank 依赖检查至少包括：

- Flask 进程可响应。
- 排序数据和模型初始化完成。

### 2.4 业务层

V2 迁移灰度期间，业务层健康检查建议覆盖：

- 获取会话详情：`session/detail`
- 获取 V2 工作台轻量状态：`workspace-state`
- 查询候选池：`candidate-pool/query`
- 导出当前方案：`ordered-plan/export` 可在非高峰人工抽查
- Legacy 兜底：`volunteer/recommend-list`
- Agent WebSocket 握手和最小消息链路

业务层检查不建议在高频健康探针中执行复杂生成动作，避免触发推荐重算或 LLM 调用。

## 3. 运维工具设计

建议新增 `ops/` 目录，和本地 `scripts/` 区分：

```text
ops/
  healthcheck.sh
  deploy.sh
  rollback.sh
  logs.sh
  migration-status.sh
  collect-diagnostics.sh
  env-check.sh
```

### 3.1 `ops/healthcheck.sh`

目标：一条命令输出系统整体状态。

建议支持：

```bash
bash ops/healthcheck.sh --local
bash ops/healthcheck.sh --remote https://zhiyuan.ytell.cn
bash ops/healthcheck.sh --json
```

输出内容：

- Nginx 配置检查：`nginx -t`
- Docker Compose 服务状态：web/agent/rank
- systemd 状态：server
- HTTP 可达性：web/server/agent/rank
- DB/Redis 可达性
- 磁盘空间和日志目录空间
- 最近错误日志摘要
- 迁移日志最近成功/失败数量

本地开发联调和生产式演练需要区分：

- 开发联调可以只启动 `scripts/start-all.sh` 管理的本地进程：Web `3001`、Backend `8080`、Agent `8000`、Rank `5001`。
- 生产式演练使用 Docker/systemd 端口映射：Web `18088 -> 28688`、Backend `8090`、Agent `18091 -> 8009`、Rank `18092 -> 5001`。
- `ops/healthcheck.sh --local` 支持用环境变量覆盖端口和 Web 健康路径，例如：

```bash
ZHIYUAN_WEB_PORT=3001 \
ZHIYUAN_WEB_HEALTH_PATH=/session \
ZHIYUAN_SERVER_PORT=8080 \
ZHIYUAN_AGENT_PORT=8000 \
ZHIYUAN_RANK_PORT=5001 \
bash ops/healthcheck.sh --local
```

- 在开发联调场景，如果 Docker daemon 不可达，`compose ps` 记录为 `WARN`，不阻断本地 HTTP/e2e 判断；生产式演练仍应单独确认 Docker Compose 状态为正常。
- Web 本地开发必须通过 `npm run dev` 启动，让 `.env.dev` 设置 `APP_ENV=dev`。不要直接执行 `next dev -p 3001`，否则可能沿用 `.next` 中的生产 `basePath=/assistant-pc` 和线上 rewrites，导致 `/session`、`/sessionDetailV2` 本地访问异常。

### 3.2 `ops/deploy.sh`

目标：标准化发布步骤。

建议流程：

1. 打印当前版本和目标版本。
2. 执行发布前检查：
   - git 工作区是否干净
   - 必要环境变量是否存在
   - `nginx -t`
   - DB/Redis 可达
   - 备份当前后端 JAR 和 compose 镜像 tag
3. 构建或拉取镜像。
4. 先发布 backend 兼容版本，再发布 web/agent/rank。
5. 发布后运行 `ops/healthcheck.sh`。
6. 输出回滚命令。

### 3.3 `ops/rollback.sh`

目标：按模块回滚。

建议支持：

```bash
bash ops/rollback.sh web --version <tag>
bash ops/rollback.sh agent --version <tag>
bash ops/rollback.sh rank --version <tag>
bash ops/rollback.sh server --jar /root/work/backup/zhiyuan-server.jar
```

回滚后必须自动执行：

- 服务重启
- 进程/端口检查
- 关键接口检查
- 输出日志位置

### 3.4 `ops/migration-status.sh`

目标：灰度期间快速判断 legacy 懒迁移状态。

封装现有脚本：

```bash
tail -10000 /root/work/zhiyuan-server/logs/server.log \
  | python3 zhiyuan-server/scripts/analyze_legacy_migration_logs.py -
```

建议输出：

- 成功数、失败数、跳过数。
- source 分布：submitted/temp/regenerated/none。
- 候选数、优报数、排序数范围。
- Top 失败原因。
- Top unavailable reason。

### 3.5 `ops/collect-diagnostics.sh`

目标：故障时一键收集上下文，不直接修改状态。

收集内容：

- `docker compose ps`
- `systemctl status zhiyuan-server.service`
- `nginx -t`
- `df -h`
- `free -m`
- 关键端口监听
- 最近 300 行 web/agent/rank/server/nginx 日志
- 最近迁移日志摘要

输出到：

```text
/tmp/zhiyuan-diagnostics-{timestamp}.tgz
```

## 4. 部署逻辑优化建议

### 4.1 短期：保留混合部署，但脚本化

当前线上 `Docker Compose + systemd` 可以继续使用。短期优化重点不是立即重构部署形态，而是：

- 固化发布顺序。
- 固化健康检查。
- 固化回滚。
- 固化日志位置。
- 固化迁移灰度观察。

建议发布顺序：

1. 备份数据库、老方案目录和当前产物。
2. 发布 backend 兼容版本。
3. 运行 server 健康检查。
4. 发布 rank/agent。
5. 发布 web。
6. Nginx reload。
7. 运行端到端健康检查。
8. 小流量验证迁移样本。

### 4.2 中期：统一容器化或统一进程管理

当前唯一非容器服务是 `zhiyuan-server`。后续有两个方向：

方案 A：后端也纳入 Docker Compose。

- 优点：部署形态统一，`docker compose ps/logs/restart` 一套命令。
- 风险：需要处理 JDK、配置挂载、日志目录、JVM 参数、宿主网络访问。

方案 B：继续 systemd，但补齐标准 unit 和脚本。

- 优点：Java 服务 JVM 参数和日志控制更直接。
- 风险：web/agent/rank 与 server 运维命令仍然分裂。

当前建议先选方案 B，等 V2 迁移稳定后再评估后端容器化。

### 4.3 前端部署环境收口

当前 `.env.deploy` 使用 `APP_ENV=dev` 来避免 `basePath=/assistant-pc`。建议后续改为：

- `APP_ENV=deploy`
- 新增显式环境变量控制 basePath，例如 `NEXT_PUBLIC_BASE_PATH=`
- `next.config.mjs` 不再通过 `APP_ENV !== dev` 隐式开启 `/assistant-pc`

这样可以减少“deploy 环境但 dev 行为”的认知风险。

### 4.4 Docker Compose healthcheck

建议为 Compose 服务补充 healthcheck：

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:28688/ || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 40s
```

不同服务使用各自端口：

- web 容器内 `28688`
- agent 容器内 `8009`
- rank 容器内 `5001`

### 4.5 后端健康接口

建议 backend 增加内部健康接口：

```text
GET /gaotu-assistant-bot/inner/ops/health
```

返回：

- 应用版本
- profile
- MySQL
- Redis
- Agent
- Rank
- temp-data-path
- max_allowed_packet
- 最近 legacy migration counters

该接口建议只允许内网或需要鉴权，不直接暴露敏感配置。

## 5. V2 迁移灰度专项检查

灰度期间每次发布后建议执行：

1. 随机选 3 个老会话进入 `/sessionDetailV2`，确认懒迁移成功。
2. 随机选 1 个已提交老方案，确认 `legacy_submitted`、顺序、数量一致。
3. 随机选 1 个临时方案，确认 `legacy_import`。
4. 打开 `/sessionDetailLegacy`，确认老方案兜底可用。
5. 使用 `reset_planning_state.py` 对测试会话 dry-run，确认单会话回滚工具可用。
6. 使用 `analyze_legacy_migration_logs.py` 汇总最近日志。

## 6. 落地优先级

### P0

- 新增 `ops/healthcheck.sh`，先聚合线上真实命令和 HTTP 检查。已落地，支持 `--local`、`--remote`、`--json`。
- 新增 `ops/migration-status.sh`，封装 legacy 迁移日志分析。已落地，默认读取 `/root/work/zhiyuan-server/logs/server.log` 最近 10000 行。
- 在部署记录中补充标准发布前/发布后检查清单。
- 为 Docker Compose 的 web/agent/rank 增加 healthcheck。已落地，容器内分别检查 web `28688`、agent `8009`、rank `5001`。

### P1

- 新增 backend `/inner/ops/health`。
- 新增 `ops/collect-diagnostics.sh`。
- 新增 `ops/rollback.sh`。
- 前端 `APP_ENV/basePath` 逻辑收口。

### P2

- 后端容器化评估。
- 统一日志采集和告警。
- 拆分大 `planningState` 存储后的专项健康检查。

## 7. 当前结论

当前部署逻辑短期可以继续使用，不需要为了 V2 迁移立即重构为全容器或 Kubernetes。更高收益的优化是：

- 先补统一健康检查。
- 再补迁移灰度观测。
- 然后把发布、回滚、诊断脚本化。
- 最后再考虑后端容器化和前端部署环境变量收口。
