# zhiyuan.ytell.cn 部署记录与问题处理

本文记录 2026-05-05 在当前服务器部署新版智愿系统、清理旧版服务时的环境处理、问题原因和改造项。

## 当前部署拓扑

公网入口：

- 域名：`zhiyuan.ytell.cn`
- Nginx 配置：`/etc/nginx/nginx.conf`
- 证书：
  - `/home/ubuntu/work/nginx/conf/sslcert/zhiyuan.ytell.cn_bundle.crt`
  - `/home/ubuntu/work/nginx/conf/sslcert/zhiyuan.ytell.cn.key`

运行服务：

| 服务 | 运行方式 | 宿主端口 | 说明 |
| --- | --- | --- | --- |
| `zhiyuan-web` | Docker Compose | `3000 -> 28688` | Next.js 前端 |
| `zhiyuan-agent` | Docker Compose | `8000 -> 8009` | FastAPI Agent / WebSocket |
| `zhiyuan-rank` | Docker Compose | `5001 -> 5001` | Flask 排序服务 |
| `zhiyuan-server` | systemd | `8090` | Spring Boot 后端 |

Nginx 路由：

| 路径 | 代理目标 |
| --- | --- |
| `/` | `http://127.0.0.1:3000` |
| `/gaotu-assistant-bot/` | `http://127.0.0.1:8090` |
| `/gaotu-assistant-agent/` | `http://127.0.0.1:8000` |
| `/gaokao-volunteer-rank/` | `http://127.0.0.1:5001` |

## 旧服务清理

服务器上旧版服务主要来自 `/root/work`，运行形态包括 Docker 容器和宿主机 Java 进程。

已停止的旧 Docker 容器：

- `gaotu-zy-agent-v3-test`
- `gaotu-zy-agent-plus-test`
- `gaotu-volunteer-assistant-test`
- `gaokao-volunteer-rank-test`

已停止的旧 Java 后端：

- `/root/work/gaotu-assistant-server-test/gaotu-assistant-server.jar`
- `/root/assistant-test/target/gaotu-assistant-server.jar`

旧端口释放后，新版本使用：

- `3000`
- `8000`
- `5001`
- `8090`

## 本次改造

### Docker Compose

`docker-compose.yml` 做了这些调整：

- 前端构建使用 `APP_ENV=deploy`
- 三个 Docker 服务增加 `restart: unless-stopped`
- `zhiyuan-agent` 增加数据目录挂载：

```yaml
volumes:
  - ./zhiyuan-agent/logs:/app/logs
  - ./zhiyuan-agent/data:/app/data:ro
```

原因：Agent 运行时需要读取 `data/option/*.json`、`*.csv` 等静态数据；原 Dockerfile 没有把 `data` 目录打进镜像，导致启动时报 `Major data file not found`。

### 前端部署环境

新增 `zhiyuan-web/.env.deploy`，用于当前服务器部署：

- API：`https://zhiyuan.ytell.cn`
- WebSocket：`wss://zhiyuan.ytell.cn`
- 外部志愿基础接口：`https://www.gaotuzhiyuan.com`
- `APP_ENV=dev`

这里使用 `APP_ENV=dev` 是为了让 `next.config.mjs` 的 `basePath` 为空。原配置里所有非 `dev` 环境都会使用 `/assistant-pc`：

```js
const basePath = process.env.APP_ENV === 'dev' ? '' : '/assistant-pc';
```

如果使用 `APP_ENV=deploy` 或 `production` 构建，真实访问路径会变成：

```text
/assistant-pc/customer
```

而用户期望的是：

```text
/customer
```

所以当前部署环境保持空 `basePath`。

注意：`APP_ENV=dev` 会启用 `next.config.mjs` 里的开发代理规则。当前部署中，内部 assistant 接口仍指向 `https://zhiyuan.ytell.cn`，但 `/hl-wish`、`/v1`、`/hl-saas` 这类外部志愿接口必须通过 `NEXT_PUBLIC_OUTER_API_BASE_URL` 指向真实外部域名，不能指向本站。

### Dockerfile 基础镜像

旧 Dockerfile 依赖私有镜像仓库，当前服务器拉取失败：

```text
pull access denied
insufficient_scope: authorization failed
```

处理方式：

- `zhiyuan-rank/Dockerfile.fast` 改用 `docker.m.daocloud.io/library/python:3.10-slim`
- `zhiyuan-web/Dockerfile` 改用 `docker.m.daocloud.io/library/node:22.14.0`
- `zhiyuan-web/Dockerfile.fast` 同步改为公开 node 镜像

### Agent 写权限

Agent 容器使用非 root 用户 `appuser`，SQLite 历史库需要写入可写目录。

本次处理：

- `HISTORY_DB_PATH=/app/logs/chat_history.db`
- 宿主机目录授权给容器用户：

```bash
chown -R 1000:1000 /root/zhiyuan/zhiyuan-agent/logs
```

否则会报：

```text
sqlite3.OperationalError: unable to open database file
```

### 后端 systemd 托管

后端使用 systemd 托管，服务名：

```bash
zhiyuan-server.service
```

服务文件：

```text
/etc/systemd/system/zhiyuan-server.service
```

原因：直接用 `nohup ... &` 从当前执行会话启动，进程会被会话回收，无法稳定保活。systemd 可以保证进程常驻和开机自启。

常用命令：

```bash
systemctl status zhiyuan-server.service
systemctl restart zhiyuan-server.service
systemctl stop zhiyuan-server.service
journalctl -u zhiyuan-server.service -f
```

### 后端外部配置

后端部署目录：

```text
/root/work/zhiyuan-server
```

关键文件：

```text
/root/work/zhiyuan-server/zhiyuan-server.jar
/root/work/zhiyuan-server/application-online.yml
/root/work/zhiyuan-server/logback-spring.xml
```

`application-online.yml` 复用了旧测试环境的数据库、Redis、OSS、短信等连接参数，并调整：

- `server.port=8090`
- `mybatis-plus.typeAliasesPackage=com.ytell.zhiyuan.model`
- `mybatis-plus.typeEnumsPackage=com.ytell.zhiyuan.model.enums`
- `agent.zhiyuan.url=http://127.0.0.1:8000`
- `volunteer.rank.url=http://127.0.0.1:5001`
- `gaotu.zhiyuan.temp-data-path=/root/work/zhiyuan-server/data/tmp`

## 部署过程中遇到的问题

### 1. Maven 构建无法写 `/root/.m2`

现象：

```text
Read-only file system
Failed to create parent directories for tracking file /root/.m2/...
```

原因：默认沙箱环境不允许写 `/root/.m2`。

处理：提权运行 Maven 构建：

```bash
mvn package -DskipTests
```

### 2. Rank/Web 私有基础镜像拉取失败

现象：

```text
pull access denied
repository does not exist or may require authorization
```

原因：Dockerfile 使用旧私有仓库基础镜像，当前机器没有权限。

处理：改为公开基础镜像，见“Dockerfile 基础镜像”。

### 3. Agent 镜像缺少静态数据

现象：

```text
FileNotFoundError: Major data file not found: /app/data/option/major_bachelor.json
```

原因：Dockerfile 只复制了 `app` 和 `skills`，没有复制 `data`。

处理：当前通过 Compose 只读挂载 `./zhiyuan-agent/data:/app/data:ro`。Dockerfile 也已补充 `COPY data ./data`，后续可以重新完整构建镜像。

### 4. Agent SQLite 文件无法打开

现象：

```text
sqlite3.OperationalError: unable to open database file
```

原因：SQLite 路径在容器内不可写，或挂载目录权限不属于 `appuser`。

处理：

- 将 `HISTORY_DB_PATH` 改为 `/app/logs/chat_history.db`
- 将宿主机 `zhiyuan-agent/logs` 改为 UID 1000 可写

### 5. 后端 Flyway 无法启动已有库

现象：

```text
Found non-empty schema(s) `gaotu_zhiyuan` but no schema history table.
Use baseline() or set baselineOnMigrate to true
```

原因：旧库已有业务表，但没有 `flyway_schema_history`。外部 `application-online.yml` 覆盖了 jar 内默认配置，导致 `baseline-on-migrate` 没生效。

处理：

- 在外部配置里补充 Flyway 配置
- systemd 启动参数里显式加：

```bash
--spring.flyway.baseline-on-migrate=true --spring.flyway.baseline-version=1
```

启动成功后，Flyway 创建了 `flyway_schema_history` 并执行了 V2 迁移。

### 6. 前端根路径 404

现象：

```text
https://zhiyuan.ytell.cn/customer -> 404
https://zhiyuan.ytell.cn/assistant-pc/customer -> 200
```

原因：前端非 `dev` 环境构建时启用了 `basePath=/assistant-pc`。

处理：`zhiyuan-web/.env.deploy` 使用 `APP_ENV=dev` 构建，使根路径可直接访问。

### 7. Nginx 新 server 块变量被吞掉

现象：

```text
invalid number of arguments in "proxy_set_header" directive
```

原因：用命令写入 nginx 配置时，`$host`、`$remote_addr` 等变量被 shell/perl 展开为空。

处理：修复为 nginx 变量字面量：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

### 8. 选科情况接口 431 / 提示未连接

现象：创建新会话后进入“选科情况”，页面提示选科信息没有正确获取、没有连接。

Nginx 访问日志显示：

```text
GET /hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy?areaId=340000 HTTP/1.1
status=431 upstream=127.0.0.1:3000
```

同时 `X-Forwarded-For` 中反复出现本站 IP 和 Docker 网关 IP。

原因：`zhiyuan-web/.env.deploy` 中曾将 `NEXT_PUBLIC_OUTER_API_BASE_URL` 配成 `https://zhiyuan.ytell.cn`。前端在 `APP_ENV=dev` 下会把 `/hl-wish/*` rewrite 到该变量，于是请求形成闭环：

```text
浏览器 -> zhiyuan.ytell.cn -> nginx -> zhiyuan-web -> zhiyuan.ytell.cn -> ...
```

代理链路反复追加请求头，最终触发 nginx/上游的 `431 Request Header Fields Too Large`。

处理：将外部志愿接口地址改为真实外部服务：

```dotenv
NEXT_PUBLIC_OUTER_API_BASE_URL=https://www.gaotuzhiyuan.com
```

然后重建并重启前端：

```bash
docker compose build zhiyuan-web
docker compose up -d zhiyuan-web
```

### 9. 新建会话后初始规划系统错误

现象：新建会话后进入详情页，生成初始规划时报“系统错误”。

后端日志显示：

```text
Packet for query is too large (19,577,884 > 4,194,304)
SQL: UPDATE assistant_chat_session_extra_data SET ... data_value=? ...
```

原因：新版后端在 `PlanningStateService.savePlanningState` 中会将完整 `PlanningStateDTO` 序列化为 JSON，并整体写入 `assistant_chat_session_extra_data.data_value`。本次生成的规划状态约 19.6MB，而当前 MySQL `max_allowed_packet` 只有 4MB。

短期处理：

```sql
SET GLOBAL max_allowed_packet=67108864;
```

并重启后端以刷新连接池：

```bash
systemctl restart zhiyuan-server.service
```

验证：

```sql
SHOW VARIABLES LIKE 'max_allowed_packet';
SHOW GLOBAL VARIABLES LIKE 'max_allowed_packet';
```

结果均为 `67108864`。

后续优化建议：

- 不要将完整候选池和规划状态反复全量写入单个 MySQL 字段。
- 将大体积候选池明细拆到独立表，按 `chat_session_id`、阶段、批次分页存储。
- `planning_state` 只保留轻量元数据、筛选条件、版本号、OSS 文件引用或候选池引用。
- 对前端只返回当前页面/当前步骤需要的字段，避免每次加载都传输完整状态。
- 如果短期仍需 JSON 存储，可先拆分 dataKey，例如 `planning_state_meta`、`candidate_pool_state`、`recommendation_overlay_state`，减少单次 UPDATE 包大小和锁持有时间。

### 10. sessionId=59 方案上移慢且无明确前端提示

现象：在方案中上移一个志愿，页面等待很久，且按钮/页面没有足够明确的加载提示。

日志记录：

```text
POST /gaotu-assistant-bot/inner/planning/1/session/ordered-plan/move?chatSessionId=59
response_size=20699854
request_time=15.307s
upstream_response_time=2.240s

GET /gaotu-assistant-bot/inner/planning/1/session/state?chatSessionId=59
response_size=20699755
request_time=13.897s
upstream_response_time=0.976s
```

原因：后端实际处理上移约 2.24 秒，但接口返回完整规划状态，响应体约 20.7MB；前端拿到 `move` 返回后又调用了一次 `fetchPlanningState()`，再次拉取约 20.7MB 数据。总等待主要耗在重复传输和前端解析大 JSON。

TODO：

- 后端：`ordered-plan/move` 返回轻量结果，例如移动后的 `orderedPlanState.items` 或变更后的两个位置，不返回完整 `PlanningStateDTO`。
- 前端：`handleMoveOrderedItem` 中收到 `move` 成功后避免无条件再次 `fetchPlanningState()`；可本地乐观更新排序，必要时后台静默刷新。
- 前端：上移/下移/固定/删除按钮应显示当前操作中的 loading，并禁用同组按钮，提示“正在调整志愿顺序”。
- 接口：补充 `state` 轻量查询或按模块查询接口，避免每次返回 20MB 全量状态。

已完成的短期优化：

- `ordered-plan/move`、`ordered-plan/pin`、`ordered-plan/unpin` 后端响应改为 `OrderedPlanActionRes`，只返回 `sessionId`、`version`、`phase`、`staleFlags`、`orderedPlanState`。
- 前端上移/下移/固定/取消固定成功后合并轻量响应，不再立即二次调用完整 `session/state`。
- 前端操作时增加全局 message loading 和当前志愿按钮 loading。

验证记录：

```text
POST /ordered-plan/move?chatSessionId=59
优化前响应体约 20.7MB，请求耗时约 15.3s
优化后响应体约 121KB，请求耗时约 1.9s-3.8s

GET /session/state?chatSessionId=59
完整状态响应体仍约 20.7MB
```

剩余优化：当前数据库仍保存完整 `PlanningStateDTO`，所以后端写库仍有秒级耗时。下一步应拆分规划状态存储，或让排序操作只更新 ordered-plan 子结构，避免每次 UPDATE 20MB JSON。

### 11. sessionId=59 对话“方案哪里要注意”没有回复

现象：用户发送“方案哪里要注意”后，页面未收到 assistant 回复。

后端和 agent 日志显示：

```text
saveMessage chatSessionId=59 content="方案哪里要注意" status=200
ChatService handling message: session_id=59 user_id=3 content_len=7
Fetched planning summary: phase=ordered version=3 draft_total=45 ordered_total=45
HTTP Request: POST https://v3.codesome.cn/v1/messages?beta=true "HTTP/1.1 401 Unauthorized"
INVALID_API_KEY
```

原因：消息已保存，agent 也已收到并成功读取成绩、画像、规划摘要，但调用模型网关失败。当前 `zhiyuan-agent` 容器环境变量为：

```text
LLM_PROVIDER=anthropic
LLM_MODEL_NAME=claude-opus-4-6
LLM_BASE_URL=https://v3.codesome.cn
LLM_API_KEY=sk-
```

`LLM_API_KEY=sk-` 是占位值，不是有效密钥。

TODO：

- 配置有效的模型网关 API Key，更新 `zhiyuan-agent/.env` 后重启 agent。
- agent 在模型调用 401/异常时，应通过 WebSocket 给前端返回明确错误事件，而不是让用户一直等待。
- 前端对 agent WebSocket 错误事件增加用户提示，例如“AI 服务认证失败，请稍后重试或联系管理员”。

## 验证记录

本机强制解析到当前 nginx：

```bash
curl -k -I --resolve zhiyuan.ytell.cn:443:127.0.0.1 https://zhiyuan.ytell.cn/customer
```

结果：`HTTP/1.1 200 OK`

后端代理：

```bash
curl -k -I --resolve zhiyuan.ytell.cn:443:127.0.0.1 \
  https://zhiyuan.ytell.cn/gaotu-assistant-bot/base-data/province-city
```

结果：`HTTP/1.1 200`

选科政策接口：

```bash
curl -I "https://zhiyuan.ytell.cn/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy?areaId=340000"
```

结果：`HTTP/1.1 200 OK`

证书：

```bash
openssl s_client -connect 127.0.0.1:443 -servername zhiyuan.ytell.cn </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -dates -ext subjectAltName
```

结果包含：

```text
subject=CN = zhiyuan.ytell.cn
DNS:zhiyuan.ytell.cn
```

## 注意事项

当前服务器本机 DNS 查询一度无法解析 `zhiyuan.ytell.cn`：

```text
Could not resolve host: zhiyuan.ytell.cn
```

如果公网访问异常，先确认 DNS A 记录是否已指向本机公网 IP，并等待解析生效。

## 常用运维命令

查看 Docker 服务：

```bash
docker ps
docker compose ps
```

重启 Docker 服务：

```bash
cd /root/zhiyuan
docker compose up -d --no-build zhiyuan-rank zhiyuan-agent zhiyuan-web
```

重建前端：

```bash
cd /root/zhiyuan
docker compose build zhiyuan-web
docker compose up -d zhiyuan-web
```

查看 Agent 日志：

```bash
docker logs -f zhiyuan-zhiyuan-agent-1
```

查看后端：

```bash
systemctl status zhiyuan-server.service
journalctl -u zhiyuan-server.service -f
```

检查 nginx：

```bash
nginx -t
nginx -s reload
```
