# Release 3.1.1 Production Upgrade Plan

本文记录生产环境从 `prod-3.1.0` 升级到 `prod-3.1.1` 的准备结论、部署范围、验证清单、实际投产过程和回滚方案。

## 1. 发布基线

| 项 | 记录 |
| --- | --- |
| 当前线上版本 | Backend/Web/Agent 为 `prod-3.1.0`，Rank 沿用 `prod-2.0.5` |
| 目标版本 | `prod-3.1.1` |
| 目标 tag | `prod-3.1.1` |
| tag commit | `2debb2deaf60b75af2f833acd91e4b814aee6abd` |
| tag 时间 | `2026-06-21 21:58:30 CST` |
| 当前本地分支 | `develop`，HEAD 与 `prod-3.1.1` 一致 |
| 3.1.0 tag | `prod-3.1.0` / `55a786a895cad120752cfff42adf9969a9e6a843` |

`prod-3.1.0..prod-3.1.1` 只有两个提交：

```text
2031758 chore: freeze 3.1.1 dialogue release
2debb2d fix: stabilize data freshness workspace sync
```

## 2. 升级结论

本次是 `3.1.0` 上线后的对话质量和数据新鲜度一致性修复版本，涉及 Backend、Web、Agent；不涉及 Rank、数据库迁移和依赖升级。

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| Backend `zhiyuan-server` | 是 | 数据新鲜度同步、候选/方案引用清理、工作区返回结构、审查失效文案和用户目标提案修复 |
| Web `zhiyuan-web` | 是 | 数据更新通知、候选刷新模式、工作区状态合并、候选查询竞态保护、排序/移动/删除按钮状态和分数输入规则 |
| Agent `zhiyuan-agent` | 是 | 对话质量、约束识别、方案动作边界、审查修复预览、回归观测和 3.1.1 benchmark |
| Rank `zhiyuan-rank` | 否 | `prod-3.1.1` 与 `prod-3.1.0` 相比无 Rank 目录变更 |
| 数据库 | 否 | 无 `db/migration` 变更；不需要执行 SQL |
| 依赖/构建文件 | 否 | `pom.xml`、Web package、Agent requirements/Dockerfile 未变更 |

本次不做：

- 不重算历史会话。
- 不修改主站 token 鉴权协议。
- 不开启数据新鲜度后台巡检，继续保持 `planning.data-freshness.schedule.enabled=false`。
- 不清理或迁移历史 3.1.0 运行资产。
- 不把生产密钥、数据库连接、LLM key 写入文档或仓库。

## 3. 主要变更

### 3.1 Agent 对话质量

来自 `2031758` 的 3.1.1 对话封版内容：

- 压线风险咨询走只读解释，避免误生成确认卡。
- 专业组内局部操作识别收口，避免把“专业组里只保留最稳专业”误当长期就业偏好。
- `only_keep / must_have / exclude` 正负向约束边界补强；正向约束缺少明确保留对象时阻断并要求补充。
- 地域负向、预算/中外合作、只读审查、候选不足、结构缺口等场景继续收口。
- 审查修复预览增加更完整的 action/pair 事实，保证替换预览能展示 `from -> to`。
- 高副作用方案动作继续保持 preview -> pending -> confirm -> apply，不新增用户话术字符串快路由。

相关文档：

- `docs/release-3.1.1-feature-inventory.md`
- `docs/release-3.1.1-dialogue-benchmark.md`
- `docs/release-3.1.1-dialogue-known-issues.md`
- `zhiyuan-agent/docs/plan_action_orchestration_design.md`

### 3.2 数据新鲜度和工作区同步

来自 `2debb2d` 的稳定性修复：

- `PlanningStateService` 增强真实 `fetchLatest` 同步后的候选、方案、推荐 overlay 和 stale 状态一致性。
- `OrderedPlanActionRes` 返回 `workingPlanState`，同时保留 `draftPlanState` 兼容别名，避免旧调用方断裂。
- 候选池真实快照一致时保持 `current`，不弹窗、不错误标记 stale。
- 上游下线或失效志愿不应继续留在工作台方案、排序方案和初始推荐引用里。
- 数据更新通知文案从“自动调整方案”收口为“候选和专家推荐已刷新，当前方案未自动调整，建议复核/审查”。
- 前端候选区按变化类型选择 `local_query` 或完整刷新，避免不必要的重拉和 UI 抖动。

相关设计记录：

- `docs/release-3.1.0-data-freshness-and-impact-notification-design.md`

### 3.3 前端工作区体验

- 候选查询增加签名保护，避免旧请求覆盖新筛选/排序结果。
- 切换工作区视图时再滚动到顶部，避免数据刷新导致用户位置跳动。
- 工作区 merge state 时不再无条件覆盖候选池状态，降低 stale/empty 状态误写风险。
- 排序、移动、删除、移出方案等按钮 loading 精确到条目或专业组，避免一个操作让全区按钮都像在处理中。
- 数据更新弹窗和 tooltip 支持 `current` 状态下携带最近变化摘要，不只依赖 `statusCode=changed`。
- 新增前端工具测试：`planningDataFreshness.test.mjs`、`scoreRules.test.mjs`。

### 3.4 后端提案和审查策略

- `UserGoalFixProposalReq.Target` 增加 `scopeLevel`，便于区分目标粒度。
- `UserGoalProposalBuilder` 增强用户目标修复提案构建。
- `ReviewInvalidationPolicy` 文案调整为“候选池和专家推荐已刷新，当前方案未自动调整，建议重新审查确认”。
- `PlanningStateServiceTest` 和 `UserGoalProposalBuilderTest` 覆盖新增逻辑。

## 4. 投产前生产运行态

检查时间：`2026-06-22 05:25 CST`。

| 项 | 当前状态 |
| --- | --- |
| Backend | `zhiyuan-server-3.1.0-prod` active，启动参数含 `--planning.data-freshness.schedule.enabled=false` |
| Web | `zhiyuan-web-3.1.0-prod` / `zhiyuan-web:prod-3.1.0` |
| Agent | `zhiyuan-agent-3.1.0-prod` / `zhiyuan-agent:prod-3.1.0` |
| Rank | `gaokao-volunteer-rank-prod`，镜像仍为 `prod-2.0.5` |
| 发布目录 | 当前已有 `/apps/releases/zhiyuan/3.0.3`、`/apps/releases/zhiyuan/3.1.0` |

投产前资源状态：

| 项 | 结果 |
| --- | --- |
| load average | `0.01, 0.16, 0.20` |
| 内存 | 15G total，6.8G available |
| 根盘 | `/` 40G，总使用 65%，可用 14G |
| 发布盘 | `/apps` 197G，总使用 23%，可用 144G |
| 本机 Web health | `http://127.0.0.1:88/assistant-pc/session` 返回 200 |
| 本机 Backend health | `http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city` 返回 200 |
| 本机 Agent health | `http://127.0.0.1:8091/gaotu-assistant-agent/health` 返回 200 |

## 5. 构建准备

建议沿用 `/apps/releases/zhiyuan/3.1.1` 作为产物目录，服务运行目录仍使用稳定路径 `/apps/zhiyuan-server-prod`，不要把运行路径绑定到版本号。

### 5.1 Backend

```bash
cd /root/dev/zhiyuan
# 确认 tag 和工作区
git rev-parse 'prod-3.1.1^{}'
git status --short

cd zhiyuan-server
mvn clean package -DskipTests
```

产物：

```text
zhiyuan-server/target/zhiyuan-server.jar
/apps/releases/zhiyuan/3.1.1/server/zhiyuan-server.jar
```

建议记录 JAR sha256：

```bash
sha256sum /apps/releases/zhiyuan/3.1.1/server/zhiyuan-server.jar
```

### 5.2 Web

生产构建使用 `APP_ENV=prod`：

```bash
docker build --platform linux/amd64   --build-arg APP_ENV=prod   -t zhiyuan-web:prod-3.1.1   -t zhiyuan-web:3.1.1-amd64   zhiyuan-web
```

构建后检查 basePath：

```bash
docker run --rm --entrypoint sh zhiyuan-web:prod-3.1.1 -lc   'grep -R ""basePath":"/assistant-pc"" -n .next/routes-manifest.json'
```

### 5.3 Agent

```bash
docker build --platform linux/amd64   -t zhiyuan-agent:prod-3.1.1   -t zhiyuan-agent:3.1.1-amd64   zhiyuan-agent
```

构建后检查：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.1.1 -lc   'python -c "import app.server; import app.service; print("agent_import_ok")"'
```

## 6. 切换顺序

建议低峰期执行。切换前再次确认机器负载、磁盘、今日新增会话/消息、后端 error log 和容器资源。

推荐顺序：

1. 备份当前 3.1.0 Backend JAR、systemd unit、生产配置、logback、Web/Agent 容器 inspect、Web/Agent 镜像 inspect、Agent env。
2. 准备 `/apps/releases/zhiyuan/3.1.1` 产物和 smoke 脚本。
3. 替换 Backend JAR，启动 `zhiyuan-server-3.1.1-prod` 或按现有 unit 命名策略启动新服务；继续带 `--planning.data-freshness.schedule.enabled=false`。
4. 验证 Backend 本机接口。
5. 启动 Agent 3.1.1 容器，复用现有生产 LLM、Bocha、Backend、Rank 配置。
6. 验证 Agent health 和 WebSocket smoke。
7. 启动 Web 3.1.1 容器并绑定现有 `88` 端口。
8. 验证 `/assistant-pc/session`、`/assistant-pc/sessionDetailV2`、主站 token 跳转。
9. 观察日志和资源至少 15 到 30 分钟。

Rank 不切换。

## 7. Smoke 清单

### 7.1 基础健康

```bash
curl -sS -o /dev/null -w 'web:%{http_code}
' http://127.0.0.1:88/assistant-pc/session
curl -sS -o /dev/null -w 'backend:%{http_code}
' http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city
curl -sS -o /dev/null -w 'agent:%{http_code}
' http://127.0.0.1:8091/gaotu-assistant-agent/health
curl -sS -o /dev/null -w 'rank:%{http_code}
' http://127.0.0.1:8092/health
```

### 7.2 业务验证

- 主站 token 跳转到 `/assistant-pc/session`。
- 会话列表展示最新会话，确认 session ID 不被截断。
- 打开 3.1.0 已有会话，工作区正常加载，候选/方案/审查状态不丢失。
- 新建会话，候选、方案、排序方案、审查入口正常。
- 外部 initialize 接口创建会话后，确认 `tk` 鉴权用户与 `externalRequestId` 中 memberId 一致，列表页可见新会话。
- 对话触发“看看现在方案”“压线风险”“只保留/必须有/排除”“审查修复预览”“专业组内最稳专业”等 3.1.1 重点 case。
- 对话侧审查后，工作区概览和审查结果区域能刷新。
- 数据新鲜度提示：`PREDICT` 会话不应弹 2026 数据更新；`VOLUNTEER` 会话只在真实变化时提示，不应无变化弹窗。
- 候选筛选/排序快速切换时，旧请求不能覆盖新结果。
- 排序、移动、删除、移出方案按钮 loading 只影响当前条目/专业组。
- 导出、审查、重新审查、排序仍可用。

### 7.3 日志观察

重点观察：

- Backend error log 是否新增持续异常。
- Agent 是否出现 LLM provider 错误、tool call 循环、WebSocket 断连。
- Web 容器是否出现前端运行时错误。
- 数据新鲜度接口是否出现批量高途请求；后台调度应仍关闭。
- DB 连接池、CPU、内存、根盘和 `/apps` 空间。

## 8. 回归建议

投产前本机或构建环境至少执行：

### 8.1 Backend

```bash
cd zhiyuan-server
mvn test -Dtest=PlanningStateServiceTest,UserGoalProposalBuilderTest
```

### 8.2 Web

```bash
cd zhiyuan-web
node src/utils/planningDataFreshness.test.mjs
node src/utils/scoreRules.test.mjs
npm run build
```

### 8.3 Agent

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python -m pytest   tests/unit/test_intent_state_tool.py   tests/unit/test_plan_semantic_action_tool.py   tests/unit/test_planning_workflow_tool.py   tests/unit/test_dialog_regression_runner.py
```

完整对话回归按 `docs/release-3.1.1-dialogue-benchmark.md` 执行。生产切换前如果时间有限，优先跑 P0 定向集合和 review/repair、constraint plan action 集合。

## 9. 回滚方案

回滚资产必须保留到 3.1.1 验收完成后：

- 3.1.0 Backend JAR 和 systemd unit。
- `zhiyuan-web:prod-3.1.0` 镜像和切换前容器 inspect。
- `zhiyuan-agent:prod-3.1.0` 镜像和切换前容器 inspect。
- 现有 Rank 容器。
- 生产配置、Agent env、Nginx/代理配置。

回滚触发条件：

- Backend 启动失败或核心接口持续失败。
- Web 入口、会话列表、详情页大面积不可用。
- Agent WebSocket 持续无回复或对话大量报错。
- 旧会话工作区无法打开，候选/方案/审查状态明显丢失。
- 数据新鲜度误触发大量上游请求或大量错误弹窗。
- 机器负载、内存、磁盘或 DB 连接出现明显异常。

回滚动作：

1. 停止 3.1.1 Backend，恢复 3.1.0 JAR/unit 并启动。
2. 停止 3.1.1 Agent/Web 容器，恢复 3.1.0 容器或按 3.1.0 镜像重建容器。
3. Rank 不变。
4. 复跑基础 health 和主站入口 smoke。
5. 保留 3.1.1 日志和产物，用于事后定位。

## 10. 实际投产记录

投产时间：`2026-06-22 05:29 - 05:32 CST`。

### 10.1 构建与产物

| 项 | 记录 |
| --- | --- |
| 部署 commit | `2debb2deaf60b75af2f833acd91e4b814aee6abd` |
| 部署 tag | `prod-3.1.1` |
| Backend JAR | `/apps/releases/zhiyuan/3.1.1/server/zhiyuan-server.jar` |
| Backend JAR sha256 | `1156677a98afc7a31c2e6d00bb5fcb4dd7e163513f27520aa4df8e37179abdb2` |
| Web image | `zhiyuan-web:prod-3.1.1` / `b6168f37fe1c` |
| Agent image | `zhiyuan-agent:prod-3.1.1` / `46db396f1bb8` |
| Rank image | 未变更，仍为 `gaokao-volunteer-rank:prod-2.0.5` |
| 发布目录 | `/apps/releases/zhiyuan/3.1.1` |
| 运行配置 | 复用 `/apps/zhiyuan-server-prod/application-online.yml`、`/apps/zhiyuan-server-prod/logback-spring.xml` |
| 数据新鲜度后台调度 | 继续关闭：`--planning.data-freshness.schedule.enabled=false` |

构建后自检：

| 项 | 结果 |
| --- | --- |
| Web basePath | `.next/routes-manifest.json` 为 `/assistant-pc` |
| Agent import | `import app.server; import app.service` 通过 |
| Backend health | 本机基础数据接口启动后返回 200 |

### 10.2 备份与回滚点

回滚备份目录：`/apps/releases/zhiyuan/3.1.1/inspect`。

已保留：

- `zhiyuan-server-3.1.0-prod` systemd unit 和 `systemctl cat` 输出。
- `zhiyuan-web-3.1.0-prod`、`zhiyuan-agent-3.1.0-prod` 的容器 inspect。
- Web/Agent 生产 env 文件，权限设置为 `600`，仅用于回滚或重建，不写入仓库。
- 旧镜像：`zhiyuan-web:prod-3.1.0`、`zhiyuan-agent:prod-3.1.0`。
- 旧容器保留为：
  - `zhiyuan-web-3.1.0-prod-before-3.1.1-20260622-053116`
  - `zhiyuan-agent-3.1.0-prod-before-3.1.1-20260622-053013`

### 10.3 切换过程

Backend：

1. 新增 `/etc/systemd/system/zhiyuan-server-3.1.1-prod.service`。
2. 保持原生产配置、logback、JVM 规格和数据新鲜度调度关闭参数。
3. 停止 `zhiyuan-server-3.1.0-prod`。
4. 启动 `zhiyuan-server-3.1.1-prod`。
5. 第 5 次健康检查通过，服务 active。

Agent：

1. 首次尝试直接 rename 旧容器后启动新容器，旧容器仍在运行并占用 `8091`，新容器因端口占用未启动。
2. 确认旧 Agent 仍健康后，删除创建失败的新容器。
3. 停止旧 Agent 备份容器，按原 env 和端口启动 `zhiyuan-agent-3.1.1-prod`。
4. 第 3 次健康检查通过。

Web：

1. 停止 `zhiyuan-web-3.1.0-prod`。
2. rename 为 3.1.0 回滚备份容器。
3. 按原 env 和端口启动 `zhiyuan-web-3.1.1-prod`。
4. 第 2 次健康检查通过。

### 10.4 投产后运行态

检查时间：`2026-06-22 05:32 CST`。

| 项 | 当前状态 |
| --- | --- |
| Backend | `zhiyuan-server-3.1.1-prod` active，PID `26448` |
| Web | `zhiyuan-web-3.1.1-prod` / `zhiyuan-web:prod-3.1.1`，端口 `88->28688` |
| Agent | `zhiyuan-agent-3.1.1-prod` / `zhiyuan-agent:prod-3.1.1`，端口 `8091->8009` |
| Rank | `gaokao-volunteer-rank-prod`，未变更，端口 `8092->5001` |
| Backend 内存 | systemd 显示约 1.4G，JVM 参数仍为 `-Xms2048m -Xmx2048m` |
| load average | `0.10, 0.17, 0.19` |
| 内存 | 15G total，8.7G available |

投产后 smoke：

| 检查项 | 结果 |
| --- | --- |
| 本机 Web | `http://127.0.0.1:88/assistant-pc/session` 返回 200，耗时约 8ms |
| 本机 Backend | `http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city` 返回 200，耗时约 4ms |
| 本机 Agent | `http://127.0.0.1:8091/gaotu-assistant-agent/health` 返回 200，耗时约 2ms |
| 外部 Web | `https://www.gaotuzhiyuan.com/assistant-pc/session` 返回 200，耗时约 174ms |
| 外部 Backend | `https://www.gaotuzhiyuan.com/gaotu-assistant-bot/base-data/province-city` 返回 200，耗时约 168ms |
| Web 日志 | Next.js ready，未见启动错误 |
| Agent 日志 | Uvicorn 启动完成，health 通过，并已有 WebSocket 连接进入 |
| Backend 日志 | 启动完成，基础接口、主站 token 登录、用户信息、会话列表接口均有 200 记录 |

数据库只读统计：

| 项 | 结果 |
| --- | --- |
| 统计时间 | `2026-06-22 05:32:51` |
| 今日会话 | 3 个会话，3 个用户，最新 `2026-06-22 00:50:57` |
| 今日消息 | 9 条，最新 `2026-06-22 00:56:24` |
| 今日行为事件 | 15 条，最新 `2026-06-22 00:29:37` |

行为采集在投产前已确认正常累计：`assistant_planning_behavior_event` 累计 `5963` 条，近 7 天每日均有增量；投产后暂无新用户行为写入并不代表异常，需结合后续真实访问继续观察。

### 10.5 投产后注意事项

- Backend 启动后出现 Druid `discard long time none received connection` 告警，发生在连接池丢弃空闲旧连接阶段，后续请求返回 200，当前不视为阻断。
- Agent 首次切换尝试因旧容器仍占用端口失败，旧服务未中断；已改用停止旧容器后启动新容器的方式完成切换。
- 当前后台数据新鲜度调度仍关闭；用户打开工作区触发的按需检查仍需观察上游请求量。
- 旧 3.1.0 服务和容器备份先保留，待 3.1.1 观察稳定后再清理。
- 还需要人工在浏览器验证主站 token 跳转、会话列表、已有会话工作区、新建会话、对话 WebSocket、审查联动、导出和数据更新提示。


### 10.6 Agent host 映射遗漏与前端异常消息

发现时间：`2026-06-22 05:39 - 05:44 CST`。

现象：

- 前端对话区发送消息后看起来没有正常响应。
- 会话 `3890` 前端短暂遗留一条异常回复：`你目前还没有正式方案...`。

原因：

- 3.1.1 Agent 首次重建容器时只复用了 env、端口和镜像，漏掉了旧容器的 Docker host 映射参数：`--add-host host.docker.internal:host-gateway`。
- Agent env 中 `INTERNAL_SERVICE_URL` 和 `RANK_SERVICE_URL` 均指向 `host.docker.internal`。
- 缺少该映射后，Agent 容器内无法解析 `host.docker.internal`，导致读取用户分数、工作区、planningState 和保存消息失败。
- Agent 仍能连接 LLM，并基于空历史/空工作区生成回复，再通过 WebSocket 发给前端；因此前端出现了临时异常回复。

故障日志特征：

```text
Cannot connect to host host.docker.internal:8090 ssl:default [Name or service not known]
获取 planning workspaceState 失败
获取 planningState 失败
保存消息失败异常
```

影响范围：

- 会话 `3890` 在故障窗口内收到一条临时 WebSocket 回复，但该回复保存后端失败。
- 数据库核查 `assistant_chat_message` 后确认，该异常回复未落库；会话 `3890` 当前落库消息为欢迎语和修复后的正常两轮对话。
- 后端、Web、Rank 服务本身未异常。

修复动作：

1. 停止并 rename 缺少 host 映射的 Agent 容器：`zhiyuan-agent-3.1.1-prod-missing-host-20260622-054111`。
2. 使用同一镜像和 env 重建 Agent 容器，并补充：`--add-host host.docker.internal:host-gateway`。
3. 修复后验证：
   - Agent health 返回 200。
   - 容器内 `getent hosts host.docker.internal` 解析到 `172.17.0.1`。
   - 容器内访问 Backend `/gaotu-assistant-bot/base-data/province-city` 返回 200。
   - 容器内访问 Rank `/health` 返回 200。
   - 修复后 Agent 日志不再出现 `Name or service not known` / `Cannot connect to host host.docker.internal`。

后续要求：

- 后续重建 Agent 容器必须保留 `--add-host host.docker.internal:host-gateway`，或改为 Docker network/service name 方式统一内部服务发现。
- 部署脚本或文档中的 Agent `docker run` 示例必须显式包含该参数，不能只复制 env 和端口。
- 对话类 smoke 不应只检查 Agent health，还要至少发送一条测试消息，确认 Agent 能读取后端上下文并能保存消息。


### 10.7 前端创建会话 Hainan 常量缺失热修复

发现时间：`2026-06-22 11:40 - 11:55 CST`。

现象：

- 线上前端创建会话时报错：`ReferenceError HAINAN_PROVINCE_CODE is not defined`。
- 问题发生在 PC/Web `/assistant-pc/session` 的创建智能方案抽屉路径，页面表现为创建流程中断。

原因：

- `zhiyuan-web/src/pageComponents/session/ModalForm/index.tsx` 在 3.1.1 中使用了 `HAINAN_PROVINCE_CODE`、`validateHainanTotalScore`、`resolveTotalScoreLabel`。
- 该文件遗漏了从 `@/utils/scoreRules.mjs` 导入上述符号。
- 同类的 `/customerDetail` 用户信息采集路径已正确导入，因此不是所有创建入口都会触发。
- `ModalForm` 组件渲染时会直接计算 `provinceValue === HAINAN_PROVINCE_CODE`，因此不只海南用户会受影响。

影响范围：

- 影响 PC/Web 会话列表页直接创建智能方案的抽屉入口。
- 正常小程序入口会跳转到 `/customer?source=minip&openSessionList=1`，通常不经过该抽屉；但如果 source 或 UA 识别异常，仍可能落到 PC 创建路径。
- 后端、Agent、Rank 未受影响。

修复动作：

1. 在 `ModalForm/index.tsx` 补充 `scoreRules.mjs` 导入。
2. 执行 `node src/utils/scoreRules.test.mjs`，结果通过。
3. 重建 web 镜像：
   - `zhiyuan-web:prod-3.1.1`
   - `zhiyuan-web:3.1.1-hainan-fix-amd64`
   - 新镜像 ID：`4c34938a105a`
4. 切换前将旧 web 镜像保留为回滚 tag：`zhiyuan-web:prod-3.1.1-before-hainan-fix-20260622`，旧镜像 ID：`b6168f37fe1c`。
5. 先用临时 188 端口启动新镜像冒烟，`/assistant-pc/session` 返回 200 后，再切换生产 88 端口。
6. 旧容器保留为：`zhiyuan-web-3.1.1-prod-before-hainan-fix-20260622-115241`。

验证结果：

- 本机入口 `http://127.0.0.1:88/assistant-pc/session` 返回 200。
- 外部入口 `https://www.gaotuzhiyuan.com/assistant-pc/session` 返回 200。
- 新 web 容器启动日志正常，`Next.js Ready`。

后续要求：

- 需要人工在浏览器点击 `/assistant-pc/session` 的创建智能方案入口，确认创建抽屉可正常打开，浏览器控制台不再出现 `HAINAN_PROVINCE_CODE` 引用错误。
- 后续涉及 `scoreRules.mjs` 的前端改动，应同步检查 PC 创建抽屉、用户信息采集页、外部初始化结果页三类入口。


### 10.8 普通用户智能填报免费试用入口取消

调整时间：`2026-06-22 14:00 - 14:25 CST`。

背景：

- `UserLevel.ORIGIN` 当前仍带有 7 天有效期，历史上会形成普通用户免费试用行为。
- 在智能填报 `VOLUNTEER` 模式下，需要取消普通用户免费试用入口。
- 调整口径只针对智能填报创建入口，不扩大到历史模拟填报 `PREDICT`。

行为设计：

- `ORIGIN + VOLUNTEER + CreateSession`：直接拒绝。
- `VIP + VOLUNTEER`：保留当前非 `SUPER_VIP` 每天最多 2 个智能填报会话限制。
- `SUPER_VIP + VOLUNTEER`：保留不限每日 2 次的逻辑。
- 白名单用户：保留当前绕过限制，用于内部验证。
- 高途 `gaotu` channel 用户仍按高途权益接口返回的 `userType` 映射 `userLevel`，不按 channel 字符串直接拦截；因此高途 VIP/SUPER_VIP 用户不受影响。
- 高途 B 端 `source=B` 登录会走 `gaotu4b` 并建成 `SUPER_VIP`，不受普通用户拦截影响。

修复动作：

1. 后端 `UserBizService.checkRights` 在 `CreateSession` 且 `prepareType=VOLUNTEER` 时，对 `UserLevel.ORIGIN` 直接返回不可操作。
2. 创建会话接口本身已有后端兜底：`ChatSessionBizService.createChatSession` 会先默认/规范化 `prepareType=VOLUNTEER`，再调用 `checkRights`。
3. 前端三处创建入口权益预检补充 `prepareType: 'VOLUNTEER'`：
   - PC `/session` 创建智能方案按钮。
   - `/customer` 创建智能方案按钮。
   - 移动端会话列表抽屉创建智能方案按钮。
4. 用户中心普通用户权益文案去掉“VIP权益试用期 7 天”，改为提示智能填报需开通志愿服务权益。

验证结果：

- `mvn -Dtest=UserBizServiceTest test` 通过，`13` 个用例全部成功。
- 新增覆盖：`ORIGIN + VOLUNTEER` 被拒绝；`ORIGIN + PREDICT` 不受本次规则影响。
- `mvn -DskipTests package` 通过，后端 JAR 可构建。
- `npm run build:prod` 通过；Next 构建跳过既有 TS 类型检查，存在的 warning 为 env 缺省提示和既有 SCSS autoprefixer warning。

待生产动作：

- 如需立即生效，需要同时部署后端 JAR 和 web 镜像/容器。
- 只部署后端也能兜底拦截创建接口；同时部署 web 后，普通用户会在点击入口时提前收到权益提示，不再进入采集流程。


### 10.9 2026 各省志愿填报政策图解 OSS 更新

更新时间：`2026-06-22 15:05 - 15:18 CST`；云南追加更新时间：`2026-06-22 17:21 CST`。

背景：

- 采集页“#{provinceName}最新志愿填报政策和要求，新的一年可能有轻微变动”使用 OSS 图片：`https://yuzhi-gaotu.oss-cn-beijing.aliyuncs.com/ui/tianbaozhengce-#{provinceCode}.jpg`。
- 当前目录 `高考政策截图/` 提供了 2026 年新的省份政策截图，文件按省份中文名命名。

处理范围：

- 首次共发现并更新 `29` 张本地图片；后续补充并更新 `云南`，累计更新 `30` 张。
- 缺失省份：`西藏`，按要求暂不更新。
- 更新方式为覆盖页面实际引用的 `yuzhi-gaotu` bucket 同名 key：`ui/tianbaozhengce-{provinceCode}.jpg`。

操作记录：

1. 生成省份中文名到省份 code 的映射，确认 29 张图片均可映射。
2. 覆盖前备份线上旧图到：`/tmp/gaokao-policy-backup-20260622-151104`。
3. 通过后端 OSS 签名接口获取 `dir=ui/` 的上传签名。
4. 注意：签名接口默认返回的 host 是当前应用 bucket，页面政策图实际读取 `yuzhi-gaotu` bucket；已将上传 host 指向 `https://yuzhi-gaotu.oss-cn-beijing.aliyuncs.com` 完成覆盖。
5. 覆盖完成后通过公开 URL `HEAD` 校验 `Content-Length`，29/29 与本地新图大小一致。
6. 云南补充更新：本地文件 `高考政策截图/云南.jpg` 覆盖 `ui/tianbaozhengce-530000.jpg`；旧图备份到 `/tmp/gaokao-policy-backup-20260622-yunnan/tianbaozhengce-530000.before.jpg`；上传后公开 URL `Content-Length=500742`，与本地文件大小一致。

已更新省份：

- 上海、云南、内蒙古、北京、吉林、四川、天津、宁夏、安徽、山东、山西、广东、广西、新疆、江苏、江西、河北、河南、浙江、海南、湖北、湖南、甘肃、福建、贵州、辽宁、重庆、陕西、青海、黑龙江。

验证结果：

- `verified_public_url=30/30`。
- 未改后端流程配置 URL，页面仍使用原有 `tianbaozhengce-{provinceCode}.jpg` 规则。
- 如浏览器或 CDN 命中旧缓存，可通过刷新或后续版本化 URL 进一步规避；当前 OSS 公开 URL 已返回新文件大小。

## 11. 待补充验收项

| 项 | 状态 |
| --- | --- |
| 构建时间 | 已完成，见第 10 节 |
| Backend JAR sha256 | 已完成，见第 10 节 |
| Web image id/digest | 已完成，见第 10 节 |
| Agent image id/digest | 已完成，见第 10 节 |
| 回滚备份目录 | 已完成，见第 10 节 |
| 切换开始/完成时间 | 已完成，见第 10 节 |
| smoke 会话 ID | 待补 |
| 人工验收结果 | 待补 |
| 上线后 30 分钟日志和资源观察 | 待补 |

## 12. 当前注意事项

- 当前仓库还有既有未提交文档改动：`release-3.1.0-production-dialogue-case-export.md`、`release-3.1.0-production-session-sampling.md`、`release-3.1.0-production-upgrade-plan.md`。构建 3.1.1 代码时必须确认这些文档改动不会混入运行产物，或先单独提交/处理文档。
- `prod-3.1.1` 已经存在且与当前 `develop` HEAD 一致，不需要重新打 tag。
- 本轮无 DB migration，不需要生产 SQL。
- 数据新鲜度后台调度继续关闭；如果后续要开启，需要单独评估上游请求量和巡检节流参数。

### 10.10 普通用户智能填报入口禁用与数据更新容错热修

时间：`2026-06-23 06:39 - 07:05 CST`。

上线内容：

- 后端：`CreateSession + prepareType=VOLUNTEER` 场景下，`ORIGIN` 普通用户不再享受智能填报免费试用，直接返回不可操作；`PREDICT` 模拟填报不受影响。
- 前端：智能填报创建入口在进入采集/创建流程前带 `prepareType=VOLUNTEER` 调用权益校验，实现入口前拦截。
- 后端：合入远端提交 `79deb6f`，对招生计划最新数据拉取失败场景做降级处理，避免异常直接打断工作区。
- 前端：`checkPlanningDataFreshnessApi` 增加 `84009` 特殊错误码处理。

验证记录：

- 后端单测：`mvn -Dtest=UserBizServiceTest,PlanningStateServiceTest test`，`177` 个测试，失败 `0`，跳过 `3`。
- 后端打包：`mvn -DskipTests package` 成功。
- 前端构建：`npm run build:prod` 成功，仅有既有 next config/env 和 SCSS autoprefixer 警告。
- 前端镜像：`zhiyuan-web:prod-3.1.1`，镜像 ID `ab46568307a2`。
- 后端 JAR：`/apps/releases/zhiyuan/3.1.1/server/zhiyuan-server.jar`，sha256 `2cb922ef27588d08611d43ac0996a7ba5fe52605863294dca9a76846e5b9784c`。

部署过程：

1. 首次手工 `nohup java` 启动没有沿用生产管理方式，旧进程退出后新进程未正确保持服务；已停止该路径。
2. 确认生产后端实际由 `systemd` 服务 `/etc/systemd/system/zhiyuan-server-3.1.1-prod.service` 管理，不是当前活跃的 `supervisord`。
3. 先用备份 JAR 恢复服务，确认 `ops health=200` 后，改用 `systemctl stop/start zhiyuan-server-3.1.1-prod` 完成新 JAR 切换。
4. 前端先备份旧镜像标签 `zhiyuan-web:prod-3.1.1-before-rights-20260623-064524`，再构建并切换容器。
5. `Dockerfile.fast` 因仓库既有 `package.json/package-lock.json` 不同步导致 `npm ci` 失败；本次改用常规 `Dockerfile` 构建，常规 Dockerfile 使用 `npm install --no-package-lock`，构建成功。

回滚信息：

- 后端备份 JAR：`/apps/releases/zhiyuan/3.1.1/server/zhiyuan-server.jar.before-rights-20260623-064744`。
- 前端旧镜像：`zhiyuan-web:prod-3.1.1-before-rights-20260623-064524`。
- 前端旧容器：`zhiyuan-web-3.1.1-prod-before-rights-20260623-065925`。

上线后健康检查：

- 后端 `http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health` 返回 `200`。
- 本机前端 `http://127.0.0.1:88/assistant-pc/session` 返回 `200`。
- 外部前端 `https://www.gaotuzhiyuan.com/assistant-pc/session` 返回 `200`。
- 生产后端服务：`zhiyuan-server-3.1.1-prod.service active (running)`。
- 生产前端容器：`zhiyuan-web-3.1.1-prod Up`。

权益验证说明：

- 使用用户提供 token 验证时，该 token 对应用户为 `ORIGIN`，但同时命中内置权益白名单，因此 `VOLUNTEER` 和 `PREDICT` 都返回 `canOperate=true`，符合白名单优先放行逻辑。
- 普通非白名单 `ORIGIN + VOLUNTEER` 的生产接口验证仍待使用非白名单测试 token 补充；代码层面已有单测覆盖。
