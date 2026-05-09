# 生产服务器升级实施步骤

本文档记录在当前生产服务器上推进老版本到 V2 升级的实际执行步骤。当前线上尚未部署新版本，生产流量仍在老版本服务上；本次实施先做只读核查、真实样本迁移验证和单会话回滚演练，验证通过后再进入部署。

## 1. 当前前提

当前新版本代码位于：

```text
/root/dev/zhiyuan
```

当前线上实际运行仍是老版本：

- 前端容器：`gaotu-volunteer-assistant-prod`
- Agent 容器：`gaotu-zy-agent-plus-prod`
- Rank 容器：`gaokao-volunteer-rank-prod`
- 后端进程：`/root/work/gaotu-assistant-server/gaotu-assistant-server.jar`

因此当前不会有线上用户触发新版本 `planningState` 懒迁移。正式切流前，必须先完成真实样本验证。

## 2. 实施原则

1. 先验证，后部署。
2. 先只读核查，后复制样本。
3. 不直接修改老方案 JSON。
4. 不直接删除生产 `planningState`，除非明确指定单个会话并完成 dry-run。
5. 不全量重算历史方案。
6. 不立即下线旧页面和旧 `/volunteer/*` 接口。
7. 每一步保留可回滚路径。

## 3. 阶段 A：只读确认生产运行态

目标：确认当前生产服务、配置、数据目录和日志目录。

### A1. 查看运行服务

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
ps -ef | grep -E 'gaotu-assistant-server|gaotu-ai-server|java|uvicorn|gunicorn|next' | grep -v grep
```

预期：

- 能看到老版前端、Agent、Rank 容器。
- 能看到老版 Java 后端进程。

### A2. 查看老后端配置

```bash
sed -n '1,240p' /root/work/gaotu-assistant-server/application-online.yml
```

重点确认：

- `spring.datasource`
- `spring.redis`
- `gaotu.zhiyuan.temp-data-path`
- OSS 配置
- 后端端口
- Rank 服务地址

注意：该步骤只读，不修改配置。

### A3. 查看方案数据目录

根据 `gaotu.zhiyuan.temp-data-path`，执行：

```bash
find <temp-data-path> -maxdepth 2 -type f -name 'session_volunteer_*.json' \
  -printf '%p %s\n' | sort | tail -100
```

目标：

- 确认老方案 JSON 是否在本机。
- 确认是否同时存在 `_temp.json`、`_temp_summary.json`、最终提交 JSON。
- 初步观察文件大小，识别大文件样本。

## 4. 阶段 B：抽样真实老方案 JSON

目标：把真实生产方案 JSON 复制到隔离目录，供新版本迁移测试使用。

样本目录：

```text
/tmp/zhiyuan-migration-samples
```

创建目录：

```bash
mkdir -p /tmp/zhiyuan-migration-samples
```

抽样建议：

- 已提交方案：`session_volunteer_{id}.json`
- 临时方案：`session_volunteer_{id}_temp.json`
- 大文件方案
- 空方案或很小文件
- 专业组模式
- 专业优先模式
- 缺少 `is_preferred` 或 `selectZy` 的旧格式
- 有 `_temp_summary.json` 的会话，但测试目录优先放完整方案 JSON

复制样例：

```bash
cp <temp-data-path>/session_volunteer_1002.json /tmp/zhiyuan-migration-samples/
cp <temp-data-path>/session_volunteer_1003_temp.json /tmp/zhiyuan-migration-samples/
```

注意：

- 只复制，不移动。
- 不删除生产目录里的任何文件。

## 5. 阶段 C：运行真实样本迁移测试

目标：验证新版本后端可以解析真实老 JSON，并转成 V2 `planningState` 结构。

执行：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldImportExternalLegacyCompleteDataSamples \
  -Dlegacy.sample.dir=/tmp/zhiyuan-migration-samples test
```

通过标准：

- 测试通过。
- 没有 JSON 解析异常。
- 没有 NPE。
- 迁移后候选数、优报数、排序数合理。

如果失败：

1. 记录失败文件名。
2. 不修改生产数据。
3. 在新版本迁移解析逻辑中修复兼容。
4. 再重新跑测试。

## 6. 阶段 D：真实会话人工对账

目标：确认新老页面结果一致。

对线上影响说明：

- 只分析 `/tmp/zhiyuan-migration-samples` 中已复制出来的 JSON 样本，不访问接口、不连接数据库、不写 `planningState`，对线上无影响。
- 使用 V2 页面或 V2 后端接口对真实 `chatSessionId` 做对账时，如果该会话缺少 `planningState`，会触发懒迁移并写入一条 V2 状态。因此这一步必须等新版本服务部署后，按指定会话小范围执行。
- 执行页面/API 对账前，先确认系统负载、磁盘、内存、容器状态；低峰期操作；每批对账后看日志和接口耗时。

### D1. 离线样本结构对账

先对复制出来的老 JSON 样本做只读结构对账：

```bash
cd /root/dev/zhiyuan
python3 zhiyuan-server/scripts/analyze_legacy_plan_samples.py /tmp/zhiyuan-migration-samples
```

当前已完成一次生产样本对账：

- 样本文件：20 个。
- 覆盖会话：`400 / 953 / 960 / 965 / 968 / 989 / 990 / 1378 / 1496`。
- 解析结果：`files_ok=20`，`files_failed=0`。
- 汇总规模：学校/专业组记录 `23309` 条，候选/专业记录 `58896` 条。
- 字段完整性：学校 ID、学校名称、计划学校 ID、专业身份字段缺失均为 `0`。
- 老格式差异：部分 `_final`、`_temp` 文件缺少显式优选标记，合计 `missing_pref_flag=9663`，后续仍按迁移逻辑中的冲/稳/保目标数量补选策略处理。
- 空方案边界：`1378`、`1496` 的 `_final/_temp` 样本解析为空方案，无异常。

### D2. 页面/API 人工对账

建议先选至少 20 个真实 `chatSessionId`：

- 10 个已提交方案。
- 10 个未提交或只有临时方案。

对账口径：

- 老页面优报总数 = V2 `orderedPlanState.items` 总数。
- 老页面冲/稳/保优报数 = V2 ordered 冲/稳/保数量。
- 老页面候补项在 V2 candidate 中仍可查询。
- 已提交方案顺序保持一致。
- 导出 Excel 主要字段一致。
- 有 `planEditCache` 的会话只提示，不自动改方案。

建议记录表：

| chatSessionId | 老状态 | 老优报数 | V2 ordered 数 | 冲/稳/保是否一致 | 顺序是否一致 | 导出是否一致 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 7. 阶段 E：单会话回滚演练

目标：确认某个会话的 V2 状态可以删除并重新懒迁移。

先 dry-run：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
python3 scripts/reset_planning_state.py --session-id 1002
```

确认 SQL 只命中：

```text
data_key = 'planningState'
data_version = 0
chat_session_id = 1002
```

再执行：

```bash
python3 scripts/reset_planning_state.py --session-id 1002 --execute
```

验证：

- 删除后进入 V2，会重新触发懒迁移。
- 回到 legacy 页面仍能查看老方案。
- 老方案 JSON 未被修改。

## 8. 阶段 F：补齐上线前 P0

当前文档中明确的 P0 遗留：

1. 真实老方案样本测试。
2. 真实会话新旧对账。
3. 单会话回滚演练。
4. 前端 V2 对 `legacy_submitted` 展示明确提示。

其中第 4 项建议改造：

- 读取 `orderedPlanState.generationMode`。
- 当值为 `legacy_submitted` 时，在工作台顶部展示：

```text
历史已提交方案，建议只读查看；如需调整，请先复制或重新生成方案。
```

并避免给用户强烈暗示“可随意编辑已提交历史方案”。

## 9. 阶段 G：部署准备

真实样本和对账通过后，再进入部署准备。

当前 3.0.0 发布候选信息：

| 项目 | 值 |
| --- | --- |
| Release 版本 | `3.0.0` |
| 当前候选 commit | `3a005aa`，后续如继续提交部署文档修正，以最终 `git rev-parse --short HEAD` 为准 |
| 目标生产入口 | `/assistant-pc` |
| 后端构建产物 | `zhiyuan-server/target/zhiyuan-server.jar` |
| 前端构建方式 | `npm run build:prod` |
| Tag 策略 | 构建验证、真实样本验证和灰度前检查通过后再创建 `v3.0.0` |

### G1. 构建边界

生产环境不作为编译构建环境。生产机只接收已经验证过的 JAR、Docker 镜像或打包产物，并执行启动、切流、健康检查和回滚。

构建应在本地、CI 或独立构建机完成：

- 后端：运行单测并构建 Spring Boot JAR。
- 前端：按目标访问路径选择正确环境构建。
- Agent：仅在 agent 代码或模型运行配置变化时构建新镜像。
- Rank：本次迁移不涉及 rank 算法或数据字段变化时不升级。

不要直接打包当前工作区目录上传生产。若需要源码包，使用 `git archive HEAD` 或生产机 `git pull` 固定提交，避免把本地 `.env`、构建缓存、临时 JSON 等未提交文件带到生产。

### G2. 固定版本

发布前先确认本地提交已经进入远端分支：

```bash
git status --short --branch
git log --oneline -5
git push origin develop
```

生产或构建环境使用固定 commit：

```bash
cd /root/dev/zhiyuan
git fetch origin develop
git checkout develop
git pull --ff-only origin develop
git rev-parse --short HEAD
```

记录本次发布 commit，后续 JAR、镜像 tag、备份目录都使用同一个 release 标识。

注意：当前本地工作区允许存在 `.env`、`tsconfig.tsbuildinfo`、临时样本 JSON 等未提交文件用于本地调试，但发布包不能从脏工作区直接复制。生产应只基于固定 commit 构建产物，或从该 commit 的 `git archive` 获取源码快照。

### G3. 后端构建与产物路径

构建机执行：

```bash
cd zhiyuan-server
mvn test
mvn package -DskipTests
```

产物：

```text
zhiyuan-server/target/zhiyuan-server.jar
```

生产建议使用新目录承载 V2 后端，避免直接覆盖老服务：

```text
/root/work/zhiyuan-server/
  zhiyuan-server.jar
  application-online.yml
  logs/
  backup/
```

老后端保留在：

```text
/root/work/gaotu-assistant-server/gaotu-assistant-server.jar
```

建议新后端先启动到独立端口，例如 `8091`；验证通过后再由 Nginx 切接口流量。若必须复用 `8090`，发布前必须先准备好老 JAR、老配置和回滚启动命令。

当前本地 3.0.0 候选已执行：

```bash
cd zhiyuan-server
mvn -q -DskipTests package
ls -lh target/zhiyuan-server.jar
```

结果：通过，产物大小约 `110M`。该命令只验证可打包性；发布前仍以完整测试、真实样本验证和灰度前检查作为准入条件。

### G4. 前端构建方式

前端必须先确认目标访问路径。

正式生产老入口使用 `/assistant-pc` 时，不能使用 `build:dev` 或当前 `zhiyuan.ytell.cn` 根路径策略。`next.config.mjs` 当前规则为：

```js
const basePath = process.env.APP_ENV === 'dev' ? '' : '/assistant-pc';
```

因此正式生产 `/assistant-pc` 应使用非 `dev` 环境构建，例如：

```bash
cd zhiyuan-web
npm run build:prod
```

或 Docker 镜像：

```bash
docker build --build-arg APP_ENV=production -t zhiyuan-web:<release> zhiyuan-web
```

如果部署目标是 `zhiyuan.ytell.cn` 根路径，才使用当前 `.env.deploy` 中的 `APP_ENV=dev` 策略，让 `basePath` 为空。

两类前端包不能混用：

| 目标环境 | 访问路径 | 构建方式 | 说明 |
| --- | --- | --- | --- |
| 正式生产老入口 | `/assistant-pc/...` | `npm run build:prod` 或 `APP_ENV=production` 镜像 | 需要 `basePath=/assistant-pc` |
| `zhiyuan.ytell.cn` 新域名 | `/...` | 当前 `.env.deploy` / `APP_ENV=dev` 策略 | 根路径访问，不能直接用于 `/assistant-pc` |

当前本地 3.0.0 候选已执行：

```bash
cd zhiyuan-web
npm run build:prod
rg -n '"basePath"|assistant-pc|sessionDetailV2|sessionDetailLegacy' \
  .next/routes-manifest.json .next/build-manifest.json .next/server/pages-manifest.json
```

结果：通过，`.next/routes-manifest.json` 中 `basePath=/assistant-pc`，构建产物包含 `/sessionDetailV2` 和 `/sessionDetailLegacy`。当前存在 3 类非阻断提示：

- `.env.prod` 未显式设置 `NEXT_PUBLIC_ASSISTANT_API_BASE_URL` 和 `NEXT_PUBLIC_OUTER_API_BASE_URL`，Next 配置校验提示缺少字符串；生产包当前仍使用 `next.config.mjs` 的线上 rewrite 指向 `https://www.gaotuzhiyuan.com`。
- 未安装可选依赖 `sharp`，Next 提示生产图片优化建议；当前 `images.unoptimized=true`，不影响构建通过。
- `customerDetail/style.module.scss` 存在既有 autoprefixer `end` 兼容提示，建议后续改为 `flex-end` 清理 warning。

### G5. Agent 和 Rank

Agent：

- 若本次只发布 V2 迁移前后端能力，agent 可暂不升级。
- 若调整大模型配置、对话编排或 WebSocket 事件，需要构建并发布新 agent 镜像。
- 发布前确认 `LLM_BASE_URL`、`LLM_MODEL_NAME`、`LLM_API_KEY` 为有效配置，不使用占位值。

Rank：

- 如果本次没有算法或数据改造，默认不升级 rank。
- 如果 V2 依赖新 rank 字段，需先在构建/测试环境验证 rank 响应字段，再单独升级。

### G6. 发布前确认清单

发布前必须确认：

- 本次 release commit。
- 后端 JAR 路径、配置路径、启动端口。
- 前端目标路径是 `/assistant-pc` 还是根路径。
- 前端构建环境与目标路径一致。
- 新 web 端口，例如 `3001`；老 web 端口保持不动。
- 新 server 端口，例如 `8091`；老 server 端口保持不动。
- Nginx 切换目标和回滚目标。
- 老前端容器、老后端进程、老 agent、老 rank 均未删除。
- 数据库、Redis、老方案 JSON 目录只读确认完成。
- 真实样本迁移测试、真实会话对账、单会话回滚 dry-run 已完成。

### G7. Release 包形态

3.0.0 release 包建议按固定 commit 生成，不从脏工作区直接打包。短期继续沿用当前混合部署形态：

- `zhiyuan-server.jar`：后端 Spring Boot 产物，生产放到 `/root/work/zhiyuan-server/zhiyuan-server.jar`，由 systemd 托管。
- `zhiyuan-web` Docker 镜像或镜像 tar：正式生产 `/assistant-pc` 使用 `APP_ENV=production` / `build:prod`；`zhiyuan.ytell.cn` 根路径环境才使用 `APP_ENV=deploy` 当前策略。
- `zhiyuan-agent` Docker 镜像或镜像 tar：如果发布本次 agent 健康接口、对话编排或模型配置变更，需要同步发布。
- `zhiyuan-rank` Docker 镜像或镜像 tar：本次没有 rank 代码变化时可不发布，只保留现有容器。
- `docker-compose.yml`、`ops/healthcheck.sh`、`ops/migration-status.sh`：用于生产健康检查和迁移灰度观测。

推荐在构建机准备 release staging 目录：

```bash
RELEASE=3.0.0
COMMIT=$(git rev-parse --short HEAD)
STAGING=/tmp/zhiyuan-release-${RELEASE}-${COMMIT}
mkdir -p "${STAGING}"/{server,ops,compose}
cp zhiyuan-server/target/zhiyuan-server.jar "${STAGING}/server/"
cp docker-compose.yml "${STAGING}/compose/"
cp ops/healthcheck.sh ops/migration-status.sh "${STAGING}/ops/"
git rev-parse HEAD > "${STAGING}/COMMIT"
```

如果生产无法从镜像仓库拉取镜像，则在构建机导出镜像 tar：

```bash
RELEASE=3.0.0
docker build --build-arg APP_ENV=production -t zhiyuan-web:${RELEASE} zhiyuan-web
docker build -t zhiyuan-agent:${RELEASE} zhiyuan-agent
docker save zhiyuan-web:${RELEASE} -o "${STAGING}/zhiyuan-web-${RELEASE}.tar"
docker save zhiyuan-agent:${RELEASE} -o "${STAGING}/zhiyuan-agent-${RELEASE}.tar"
```

上传生产后先 `docker load`，再用固定 tag 更新 Compose；不要在生产执行 `docker compose build`。

## 10. 阶段 H：正式部署和灰度

部署前必须明确：

- 使用新目录 `/root/work/zhiyuan-server` 还是直接替换老目录。推荐新目录。
- 新后端端口和 Nginx 接口代理目标。
- 新前端端口和 Nginx `/assistant-pc` 代理目标。
- Agent WebSocket 路由是否切到新 Agent。
- 每个模块的回滚命令。

推荐灰度：

1. 后端先上线兼容版本，旧接口保留。
2. 新前端先启动在独立端口，正式生产通过 `/assistant-pc/sessionDetailV2` 做内部访问。
3. 少量真实会话进入 V2。
4. 观察迁移日志：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
python3 scripts/analyze_legacy_migration_logs.py /path/to/server.log
```

5. 无异常后扩大入口。

### H1. 后端启动和验证

示例：

```bash
mkdir -p /root/work/zhiyuan-server/logs /root/work/zhiyuan-server/backup
cp /tmp/release/zhiyuan-server.jar /root/work/zhiyuan-server/
cp /root/work/gaotu-assistant-server/application-online.yml /root/work/zhiyuan-server/application-online.yml
```

启动方式可以继续使用 systemd，但建议使用新的 unit，例如 `zhiyuan-server.service`，并让新服务监听独立端口。

验证：

```bash
systemctl status zhiyuan-server.service
journalctl -u zhiyuan-server.service -n 200 --no-pager
NEW_SERVER_PORT=8091
curl -I "http://127.0.0.1:${NEW_SERVER_PORT}/gaotu-assistant-bot/base-data/province-city"
```

### H2. 前端启动和验证

如果使用 Docker 镜像：

```bash
RELEASE=<release>
NEW_WEB_PORT=3001
docker run -d --name "zhiyuan-web-${RELEASE}" \
  -p "${NEW_WEB_PORT}:28688" \
  --restart unless-stopped \
  "zhiyuan-web:${RELEASE}"
```

正式生产 `/assistant-pc` 包验证：

```bash
NEW_WEB_PORT=3001
curl -I "http://127.0.0.1:${NEW_WEB_PORT}/assistant-pc/customer"
curl -I "http://127.0.0.1:${NEW_WEB_PORT}/assistant-pc/sessionDetailV2"
```

如果这里根路径 `/customer` 可访问但 `/assistant-pc/customer` 不可访问，说明误用了根路径包，不应切生产。

### H2.1 Compose 健康检查和运维脚本

本次已为 `zhiyuan-web / zhiyuan-agent / zhiyuan-rank` 增加 Compose healthcheck。生产更新 Compose 后检查：

```bash
docker compose ps
bash ops/healthcheck.sh --local
bash ops/healthcheck.sh --remote https://<prod-domain>
```

灰度期间观察 legacy 懒迁移：

```bash
bash ops/migration-status.sh /root/work/zhiyuan-server/logs/server.log
```

`ops/healthcheck.sh` 的远端检查包含：

- `/assistant-pc/customer`
- `/assistant-pc/sessionDetailV2`
- `/gaotu-assistant-bot/base-data/province-city`
- `/gaotu-assistant-agent/health`
- `/gaokao-volunteer-rank/recommend` rank 现有 GET 接口

### H3. Nginx 切换

正式生产 `/assistant-pc` 示例：

```nginx
location /assistant-pc/ {
    proxy_pass http://127.0.0.1:<new-web-port>;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /gaotu-assistant-bot/ {
    proxy_pass http://127.0.0.1:<new-server-port>;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

切换前检查：

```bash
nginx -t
```

切换后：

```bash
nginx -s reload
curl -I https://<prod-domain>/assistant-pc/customer
curl -I https://<prod-domain>/gaotu-assistant-bot/base-data/province-city
```

## 11. 回滚要点

前端回滚：

```bash
# Nginx 切回老前端端口
nginx -t
nginx -s reload

# 如果新前端使用独立容器，停止新容器
RELEASE=<release>
docker stop "zhiyuan-web-${RELEASE}"
```

如果是覆盖式发布，则启动老前端容器：

```bash
docker start gaotu-volunteer-assistant-prod
```

保留 `/sessionDetailLegacy`，不要在回滚时删除旧页面入口。

后端回滚：

```bash
systemctl stop zhiyuan-server.service
systemctl start gaotu-assistant-server.service
nginx -t
nginx -s reload
```

若复用了同一个 systemd unit，则恢复老 JAR：

```bash
cp /root/work/zhiyuan-server/backup/zhiyuan-server.jar.<old-release> \
  /root/work/zhiyuan-server/zhiyuan-server.jar
systemctl restart zhiyuan-server.service
```

新增 `planningState` dataKey 对老版本无影响，回滚时不需要批量删除。

Agent 回滚：

```bash
docker stop <new-agent-container>
docker start gaotu-zy-agent-plus-prod
```

Rank 回滚：

```bash
docker stop <new-rank-container>
docker start gaokao-volunteer-rank-prod
```

单会话回滚：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
python3 scripts/reset_planning_state.py --session-id <id>
python3 scripts/reset_planning_state.py --session-id <id> --execute
```

生产数据保护：

- 不删除老 JSON。
- 不删除旧 `/volunteer/*` 接口。
- 不批量删除 `planningState`。
