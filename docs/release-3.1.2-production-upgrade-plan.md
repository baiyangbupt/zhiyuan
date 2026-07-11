# Release 3.1.2 Production Upgrade Plan

本文记录生产环境从 `prod-3.1.1-hotfix-mobile` 升级到 `prod-3.1.2` 的准备结论、实际部署过程、验证结果和回滚方案。

## 1. 发布基线

| 项 | 记录 |
| --- | --- |
| 目标 tag | `prod-3.1.2` |
| 部署 commit | `11172c7d7703df7cebbce94f8902f1cdf82ba9d6` |
| 上一生产基线 | `prod-3.1.1-hotfix-mobile` |
| 部署时间 | `2026-07-03 10:53 - 10:59 CST` |
| Rank | 未变更，仍为 `gaokao-volunteer-rank:prod-2.0.5` |

本地部署时处于 detached HEAD，HEAD 正好为 `prod-3.1.2`。工作区存在历史文档修改和临时导入 JSON，未纳入构建产物：

- `docs/release-3.1.1-production-upgrade-plan.md`
- `2248_aifill.json`

## 2. 升级结论

本次升级涉及 Backend、Web、Agent；不涉及 Rank、数据库迁移和依赖文件变更。

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| Backend `zhiyuan-server` | 是 | 用户选科提示、上游全量接口 internal 配置、超时提示、候选筛选标签、旧格式导入和方案数量修复 |
| Web `zhiyuan-web` | 是 | 候选加入方案后保持展开和滚动位置、权益请求参数、错误码特殊处理、学费区间上限 |
| Agent `zhiyuan-agent` | 是 | pending 恢复、overlay 超时保护和意图解析稳定性修复 |
| Rank | 否 | 本 tag 不涉及 rank 发布 |
| 数据库 | 否 | 无 `db/migration` 变更 |
| 依赖 | 否 | 后端、前端、agent 依赖文件无变更 |

生产配置已确认：

- `gaotu.zhiyuan.zhiyuan-Url=https://internal.gaotuzhiyuan.com`
- `gaotu.zhiyuan.program-data-Url=https://internal.gaotuzhiyuan.com`
- `gaotu.zhiyuan.user-url=https://internal-user.gaotu100.com`

`queryAllProgramData` 在 3.1.2 中仍是单次全量请求；本版本只增强超时识别和提示，未接入上游分页接口。

## 3. 构建与验证

后端定向回归：

```bash
mvn -Dtest=GaotuServiceTest,PlanningStateServiceTest,VolunteerBizServiceTest,RepairReplacementActionBuilderTest test
```

结果：`177` 个测试，失败 `0`，跳过 `3`。

后端打包：

```bash
mvn -DskipTests package
```

结果：成功。

前端构建：

```bash
npm run build:prod
```

结果：成功；仅有既有 Next env 缺省提示和 `customerDetail/style.module.scss` autoprefixer warning。

Agent 常规 Docker 构建因生产机无法拉取 `python:3.12-slim` 元数据失败；因依赖无变化，本次采用当前生产 `zhiyuan-agent:prod-3.1.1` 作为基础镜像 overlay 覆盖 `app/skills/data`。

## 4. 产物

| 项 | 记录 |
| --- | --- |
| Backend JAR | `/apps/releases/zhiyuan/3.1.2/server/zhiyuan-server.jar` |
| Backend JAR sha256 | `6e33572e794232691c09267730163b100f6d880f4ad5cf9dacb039e616b8004a` |
| Web image | `zhiyuan-web:prod-3.1.2` |
| Web image ID | `sha256:8a69ba09e9f5b675631daf06938e8c20f3275acc436e5ff88d52375054346c9f` |
| Agent image | `zhiyuan-agent:prod-3.1.2` |
| Agent image ID | `sha256:1d0b456656605b5147d7d4718a82500f9675cfe2bd8aa478fc372ec8d634a26b` |
| 发布目录 | `/apps/releases/zhiyuan/3.1.2` |

Web 镜像自检：

- `.next/routes-manifest.json` 中 `basePath=/assistant-pc`。
- 临时容器 `28689->28688` 下 `/assistant-pc/session` 返回 `200`。

Agent 镜像自检：

- `import app.server; import app.service` 通过。
- 容器内 `host.docker.internal` 解析正常。
- 容器内访问 Backend `/gaotu-assistant-bot/inner/ops/health` 返回 `200`。
- 容器内访问 Rank `/health` 返回 `200`。

## 5. 备份与回滚点

备份目录：`/apps/releases/zhiyuan/3.1.2/inspect`。

已保留：

- 旧 Backend JAR：`zhiyuan-server-3.1.1.jar.before-3.1.2-20260703-103510`
- 旧 systemd unit：`zhiyuan-server-3.1.1-prod.service.before-3.1.2-20260703-103510`
- `systemctl cat` 输出
- 旧 Web/Agent 容器 inspect
- 旧 Web/Agent env 文件，权限 `600`
- Web 回滚镜像 tag：`zhiyuan-web:prod-3.1.1-before-3.1.2-20260703-103510`
- Agent 回滚镜像 tag：`zhiyuan-agent:prod-3.1.1-before-3.1.2-20260703-103510`
- Web 回滚容器：`zhiyuan-web-3.1.1-prod-before-3.1.2-20260703-103510`
- Agent 回滚容器：`zhiyuan-agent-3.1.1-prod-before-3.1.2-20260703-103510`

## 6. 切换过程

切换前活跃度：

- 机器负载低，内存余量正常。
- 前台有零星采集页和会话请求；未观察到大量并发。
- 后台数据新鲜度调度每 2 分钟最多 10 个检查，切换后继续保留。

Backend：

1. 基于当前 `zhiyuan-server-3.1.1-prod.service` 生成 `/etc/systemd/system/zhiyuan-server-3.1.2-prod.service`。
2. 仅替换版本号、GC 日志名和 JAR 路径。
3. 保留生产配置、logback 和数据新鲜度参数：
   - `--planning.data-freshness.schedule.enabled=true`
   - `--planning.data-freshness.schedule.fixed-delay-ms=120000`
   - `--planning.data-freshness.schedule.batch-size=10`
   - `--planning.data-freshness.schedule.max-consecutive-tasks=10`
4. 执行 `systemctl daemon-reload`。
5. 停止 `zhiyuan-server-3.1.1-prod.service`。
6. 启动 `zhiyuan-server-3.1.2-prod.service`。

Agent：

1. 停止 `zhiyuan-agent-3.1.1-prod`。
2. 重命名为回滚容器。
3. 使用 `zhiyuan-agent:prod-3.1.2` 启动 `zhiyuan-agent-3.1.2-prod`。
4. 保留 `--add-host host.docker.internal:host-gateway`、`8091->8009`、`--restart unless-stopped` 和生产 env。

Web：

1. 使用 `zhiyuan-web:prod-3.1.2` 启动临时容器 `28689->28688` 冒烟。
2. 临时冒烟通过后停止临时容器。
3. 停止 `zhiyuan-web-3.1.1-prod`。
4. 重命名为回滚容器。
5. 使用 `zhiyuan-web:prod-3.1.2` 启动 `zhiyuan-web-3.1.2-prod`，端口 `88->28688`。

## 7. 上线后状态

检查时间：`2026-07-03 10:59 CST`。

| 项 | 状态 |
| --- | --- |
| Backend | `zhiyuan-server-3.1.2-prod.service active`，PID `4379` |
| Web | `zhiyuan-web-3.1.2-prod` / `zhiyuan-web:prod-3.1.2`，端口 `88->28688` |
| Agent | `zhiyuan-agent-3.1.2-prod` / `zhiyuan-agent:prod-3.1.2`，端口 `8091->8009` |
| Rank | 未变更，端口 `8092->5001` |

健康检查：

| 检查项 | 结果 |
| --- | --- |
| 本机 Web `/assistant-pc/session` | `200`，约 `8ms` |
| 本机 Backend `/inner/ops/health` | `200`，约 `3ms` |
| 本机 Agent `/health` | `200`，约 `2ms` |
| 本机 Rank `/health` | `200`，约 `2ms` |
| 外部 Web `/assistant-pc/session` | `200`，约 `208ms` |
| 外部 Backend `/base-data/ethnicity-list` | `200`，约 `133ms` |

上线后观察：

- Web Next 启动正常，`Ready in 550ms`。
- Agent Uvicorn 启动正常，health 通过，并有 WebSocket 连接进入。
- Backend 上线后无 error 级别 journal 日志。
- 真实用户登录、会话列表、工作区、候选查询、初始方案生成、方案移除等接口均有 `200` 响应。
- Druid 空闲连接回收 warning 仍存在，与之前生产表现一致，当前不视为阻断。

## 8. 回滚方式

Backend 回滚：

```bash
systemctl stop zhiyuan-server-3.1.2-prod.service
systemctl start zhiyuan-server-3.1.1-prod.service
```

如需恢复 3.1.1 unit 文件，使用：

```bash
cp /apps/releases/zhiyuan/3.1.2/inspect/zhiyuan-server-3.1.1-prod.service.before-3.1.2-20260703-103510 /etc/systemd/system/zhiyuan-server-3.1.1-prod.service
systemctl daemon-reload
```

Agent 回滚：

```bash
docker stop zhiyuan-agent-3.1.2-prod
docker start zhiyuan-agent-3.1.1-prod-before-3.1.2-20260703-103510
```

Web 回滚：

```bash
docker stop zhiyuan-web-3.1.2-prod
docker start zhiyuan-web-3.1.1-prod-before-3.1.2-20260703-103510
```

回滚后复查：

- `http://127.0.0.1:88/assistant-pc/session`
- `http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health`
- `http://127.0.0.1:8091/gaotu-assistant-agent/health`
- `http://127.0.0.1:8092/health`


## 9. 采集页学费区间热修

处理时间：`2026-07-03 12:59 - 13:01 CST`。

变更范围：仅后端采集流程配置资源，不重建、不重启 Web/Agent/Rank。采集页 `/customer` 的学费滑块读取 Backend `collect-flow` 返回配置，因此前端代码无需改动。

配置变更：

- `tuitionRange.max`：`100000` -> `200000`
- `tuitionRange.defaultValue.maxValue`：`60000` -> `100000`
- `tuitionRange.min` 保持 `0`，`step` 保持 `1000`

代码验证：

```bash
mvn -q -Dtest=FlowConfigResourceTest test
nice -n 10 mvn -q -DskipTests package
```

结果：定向测试通过，后端打包成功。新 JAR 内 `BOOT-INF/classes/bizdata/gaokao_volunteer_flow_config.json` 已确认包含 `max=200000` 和 `defaultValue.maxValue=100000`。

部署记录：

| 项 | 记录 |
| --- | --- |
| 旧 JAR 备份 | `/apps/releases/zhiyuan/3.1.2/server/zhiyuan-server.jar.before-tuition-range-20260703-125956` |
| 旧 JAR sha256 | `6e33572e794232691c09267730163b100f6d880f4ad5cf9dacb039e616b8004a` |
| 新 JAR sha256 | `d9a6b0392d926e032390e064c0fceb9553e4b953d80271f0b957ae90b0c766d4` |
| 服务 | `zhiyuan-server-3.1.2-prod.service` |
| 新 PID | `24983` |

上线验证：

- Backend `/gaotu-assistant-bot/inner/ops/health` 返回 `200`，约 `4ms`。
- Backend `/gaotu-assistant-bot/base-data/ethnicity-list` 返回 `200`，约 `4ms`。
- `journalctl -u zhiyuan-server-3.1.2-prod.service --since '2026-07-03 13:00:00' -p err` 无记录。
- 裸调 `collect-flow` 因无登录态返回 `code=800 不合法请求`，未作为配置响应验证依据。

回滚方式：将备份 JAR 覆盖回 `/apps/releases/zhiyuan/3.1.2/server/zhiyuan-server.jar` 后重启 `zhiyuan-server-3.1.2-prod.service`，再复查 Backend health。
