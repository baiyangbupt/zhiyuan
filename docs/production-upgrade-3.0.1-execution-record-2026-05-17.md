# Production Upgrade 3.0.1 Execution Record 2026-05-17

本文记录生产服务器从 `3.0.0` 升级到 `3.0.1` 的实际执行过程、验证结果和回滚对象。

## 1. 基本信息

- 执行时间：`2026-05-17 01:55 - 02:30 CST`
- 代码目录：`/root/dev/zhiyuan`
- Git 提交：`7a3528f feat: add gaotu user permission management`
- Git 标签：`prod-3.0.1`
- 当前分支：`develop`
- 升级类型：生产稳定修复版升级
- 数据库 schema：未变更
- Flyway：继续通过启动参数 `--spring.flyway.enabled=false` 关闭
- Rank：未升级，继续使用原生产容器

## 2. 升级前生产状态

升级前生产运行对象：

| 模块 | 运行对象 | 端口 | 说明 |
| --- | --- | --- | --- |
| Backend | `zhiyuan-server-3.0.0-prod.service` | `8090` | systemd，profile=`online` |
| Web | `zhiyuan-web-3.0.0-prod` | `88 -> 28688` | 镜像 `zhiyuan-web:3.0.0-amd64-wsfix` |
| Agent | `zhiyuan-agent-3.0.0-prod` | `8091 -> 8009` | 镜像 `zhiyuan-agent:3.0.0-amd64` |
| Rank | `gaokao-volunteer-rank-prod` | `8092 -> 5001` | 继续沿用原镜像 |

切换前复核：

- 时间：`2026-05-17 02:18:29 CST`
- 负载：`load average: 0.00, 0.10, 0.12`
- 内存：`15G total / 7.3G available`
- 生产端口 `88 / 8090 / 8091 / 8092` 无已建立连接
- 后端最近 10 分钟无用户请求日志
- Agent 最近 10 分钟无对话日志

判断：切换窗口内无活跃用户连接。

## 3. 构建和产物

### 3.1 后端测试

执行后端重点测试：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -Dtest=PlanningExcelExportBuilderTest,PlanningStateServiceTest,PlanningStateSuggestionMappingTest,UserBizServiceTest,UserAdminControllerTest test
```

结果：

```text
115 run / 0 failures / 0 errors / 2 skipped
```

### 3.2 后端 JAR

执行构建：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -DskipTests package
```

结果：构建成功。

JAR 校验：

```text
3.0.1 JAR: 765133a9c3d5b3d92a5c89e48603b41bf71472b44eb33079e6d7e826dc3d9a57
3.0.0 JAR: d21c8ca57ef3bcf825f45cec96890f4d6fa2d135fe3721c973c74669233edb69
```

说明：`/root/work/zhiyuan-server-3.0.1/zhiyuan-server.jar` 来自当前 `prod-3.0.1` 代码构建产物，不是 3.0.0 JAR。3.0.1 仅复用 3.0.0 的生产配置文件：

- `application-online.yml`
- `logback-spring.xml`

### 3.3 Web 镜像

常规 Docker build 拉取 Docker Hub 基础镜像时失败：

```text
node:22.14.0: pull access denied / insufficient_scope
```

处理方式：基于本机已有 `zhiyuan-web:3.0.0-amd64` 作为构建基底，复制 3.0.1 前端代码后重新执行 `npm run build:prod`。

临时构建文件：

```text
ops/release-build/Dockerfile.web-prod-3.0.1
```

生成镜像：

```text
zhiyuan-web:prod-3.0.1
zhiyuan-web:3.0.1-amd64
```

镜像验证：

- `.next/routes-manifest.json` 中 `basePath=/assistant-pc`
- 构建产物包含 `wss://www.gaotuzhiyuan.com`
- 未发现 `ws://localhost:8000`

### 3.4 Agent 镜像

常规 Docker build 拉取 Docker Hub 基础镜像时失败：

```text
python:3.12-slim: pull access denied / insufficient_scope
```

处理方式：基于本机已有 `zhiyuan-agent:3.0.0-amd64` 作为运行基底，复制 3.0.1 Agent 代码后生成镜像。

临时构建文件：

```text
ops/release-build/Dockerfile.agent-prod-3.0.1
```

生成镜像：

```text
zhiyuan-agent:prod-3.0.1
zhiyuan-agent:3.0.1-amd64
```

镜像验证：

```bash
docker run --rm --entrypoint sh zhiyuan-agent:prod-3.0.1 -lc 'python -c "import app.server; print(\"agent_import_ok\")"'
```

结果：`agent_import_ok`。

## 4. 部署准备

### 4.1 后端目录

创建目录：

```text
/root/work/zhiyuan-server-3.0.1
/root/work/zhiyuan-server-3.0.1/logs
```

复制文件：

```text
/root/work/zhiyuan-server-3.0.1/zhiyuan-server.jar
/root/work/zhiyuan-server-3.0.1/application-online.yml
/root/work/zhiyuan-server-3.0.1/logback-spring.xml
```

### 4.2 后端 systemd

新增 service：

```text
/etc/systemd/system/zhiyuan-server-3.0.1-prod.service
```

关键启动参数：

```text
-Dapp_name=zhiyuan-server-3.0.1
-Dspring.profiles.active=online
-Dspring.config.location=/root/work/zhiyuan-server-3.0.1/application-online.yml
-Dlogging.config=/root/work/zhiyuan-server-3.0.1/logback-spring.xml
-jar /root/work/zhiyuan-server-3.0.1/zhiyuan-server.jar
--spring.flyway.enabled=false
```

执行：

```bash
systemctl daemon-reload
```

### 4.3 Agent LLM 配置

新建运行时 env：

```text
/root/work/zhiyuan-agent-3.0.1/.env
```

权限：

```text
-rw------- root root
```

非敏感配置：

```text
INTERNAL_SERVICE_URL=http://host.docker.internal:8090
RANK_SERVICE_URL=http://host.docker.internal:8092
LLM_PROVIDER=openai_compatible
LLM_MODEL_NAME=kimi-k2.6
LLM_BASE_URL=https://llm.baijia.com/v1
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=4096
```

`LLM_API_KEY` 已写入该文件，但不在本文记录明文。

## 5. 切换过程

### 5.1 后端切换

```bash
systemctl stop zhiyuan-server-3.0.0-prod.service
systemctl start zhiyuan-server-3.0.1-prod.service
```

验证：

```bash
systemctl status zhiyuan-server-3.0.1-prod.service --no-pager
curl -sS -o /dev/null -w 'backend %{http_code} %{time_total}\n' \
  http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city
```

结果：

```text
backend 200
```

### 5.2 Agent 切换

保留旧容器作为回滚对象：

```bash
docker stop zhiyuan-agent-3.0.0-prod
docker rename zhiyuan-agent-3.0.0-prod zhiyuan-agent-3.0.0-prod-rollback
```

启动新容器：

```bash
docker run -d \
  --name zhiyuan-agent-3.0.1-prod \
  --restart unless-stopped \
  -p 8091:8009 \
  --env-file /root/work/zhiyuan-agent-3.0.1/.env \
  --add-host host.docker.internal:host-gateway \
  zhiyuan-agent:prod-3.0.1
```

验证：

```text
agent 200
LLM_PROVIDER=openai_compatible
LLM_MODEL_NAME=kimi-k2.6
LLM_BASE_URL=https://llm.baijia.com/v1
```

### 5.3 Web 切换

保留旧容器作为回滚对象：

```bash
docker stop zhiyuan-web-3.0.0-prod
docker rename zhiyuan-web-3.0.0-prod zhiyuan-web-3.0.0-prod-rollback
```

启动新容器：

```bash
docker run -d \
  --name zhiyuan-web-3.0.1-prod \
  --restart unless-stopped \
  -p 88:28688 \
  -e APP_ENV=prod \
  --add-host host.docker.internal:host-gateway \
  zhiyuan-web:prod-3.0.1
```

## 6. 发布后验证

基础健康检查：

```text
backend 200
web_session 200
web_v2 200
agent 200
rank 200
public_v2 200
public_agent_health 200
```

业务 smoke：

```text
workspace_2098 200 0.662s bytes=758044
candidate_2098 200 0.167s bytes=27127
export_2098 200 0.878s bytes=28605
```

验证接口：

```bash
curl 'http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=2098'
curl -X POST -H 'Content-Type: application/json' -d '{"page":1,"pageSize":10}' \
  'http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/candidate-pool/query?chatSessionId=2098'
curl -X POST -o /tmp/ordered-plan-2098.xlsx \
  'http://127.0.0.1:8090/gaotu-assistant-bot/inner/planning/1/session/ordered-plan/export?chatSessionId=2098'
```

发布后容器状态：

| 容器 | 镜像 | 状态 | 端口 |
| --- | --- | --- | --- |
| `zhiyuan-web-3.0.1-prod` | `zhiyuan-web:prod-3.0.1` | Up | `88 -> 28688` |
| `zhiyuan-agent-3.0.1-prod` | `zhiyuan-agent:prod-3.0.1` | Up | `8091 -> 8009` |
| `gaokao-volunteer-rank-prod` | 原 Rank 镜像 | Up | `8092 -> 5001` |

发布后 systemd 状态：

```text
zhiyuan-server-3.0.1-prod.service active (running)
zhiyuan-server-3.0.0-prod.service inactive/unknown
```

## 7. 发布后观察

日志检查：

- 后端未发现 5xx、异常堆栈或启动失败。
- Agent 未发现 `error / exception / failed / traceback / critical`。
- Web 启动完成并返回页面 200。

已知 warning：

```text
Invalid next.config.mjs options detected:
env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL is missing
env.NEXT_PUBLIC_OUTER_API_BASE_URL is missing
```

该 warning 在 Web 启动时出现，发布后页面和接口健康检查均为 `200`，本次未作为阻断项。

后端日志中出现 Druid 丢弃长时间空闲连接的 WARN：

```text
discard long time none received connection
```

该模式在 3.0.0 运行期间也存在，本次 smoke 请求后自动重建连接并返回 `200`。

## 8. 回滚对象

已保留：

| 模块 | 回滚对象 |
| --- | --- |
| Backend | `zhiyuan-server-3.0.0-prod.service` |
| Web 容器 | `zhiyuan-web-3.0.0-prod-rollback` |
| Web 镜像 | `zhiyuan-web:3.0.0-amd64-wsfix` |
| Agent 容器 | `zhiyuan-agent-3.0.0-prod-rollback` |
| Agent 镜像 | `zhiyuan-agent:3.0.0-amd64` |

回滚命令：

```bash
systemctl stop zhiyuan-server-3.0.1-prod.service
systemctl start zhiyuan-server-3.0.0-prod.service

docker stop zhiyuan-agent-3.0.1-prod
docker start zhiyuan-agent-3.0.0-prod-rollback

docker stop zhiyuan-web-3.0.1-prod
docker start zhiyuan-web-3.0.0-prod-rollback
```

回滚后检查：

```bash
curl -sS -o /dev/null -w 'backend %{http_code} %{time_total}\n' \
  http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city
curl -sS -o /dev/null -w 'web_session %{http_code} %{time_total}\n' \
  http://127.0.0.1:88/assistant-pc/session
curl -sS -o /dev/null -w 'agent %{http_code} %{time_total}\n' \
  http://127.0.0.1:8091/gaotu-assistant-agent/health
```

## 9. 当前遗留

当前 Git 工作区存在未跟踪目录：

```text
ops/release-build/
```

用途：记录本次在 Docker Hub 基础镜像不可拉取时，基于本机已有 3.0.0 镜像重建 3.0.1 Web/Agent 生产镜像的临时 Dockerfile。

后续可选择：

- 保留并纳入版本控制，作为生产应急构建方式。
- 或在确认不再需要后删除。

