# 生产巡检记录 2026-05-10

巡检时间：`2026-05-10 08:08:30 CST`

巡检范围：系统资源、端口、Docker 容器、后端 systemd、Web/Backend/Agent/Rank 健康接口、WebSocket 握手、近期错误日志、回滚对象状态。

## 1. 总体结论

- 当前系统整体健康，生产主链路可用。
- 服务器负载低，CPU 基本空闲，内存和磁盘余量充足。
- 新版 Web、Backend、Agent 均已运行；Rank 继续使用老生产容器，符合本次升级策略。
- Web/Backend/Agent 健康检查均返回 200，公网 Agent WebSocket 握手返回 101。
- 最近 30 分钟 Web、Backend、Agent、Rank 未发现错误关键字日志。
- 机器层存在两个历史 failed systemd unit：`cloud-final.service`、`kdump.service`，与当前应用主链路无直接关系，建议后续运维窗口确认。

## 2. 系统资源

### 2.1 负载和 CPU

```text
08:08:32 up 423 days, 16:04, 1 user, load average: 0.05, 0.06, 0.05
Tasks: 156 total, 1 running, 155 sleeping, 0 stopped, 0 zombie
%Cpu(s): 0.0 us, 0.0 sy, 100.0 id, 0.0 wa
```

高 CPU 进程主要为系统采集和安全进程，应用进程 CPU 占用低：

```text
aegis_client        2.3%
openai/codex node   1.0%
n9e-collector       1.0%
zhiyuan-server      0.8%
```

### 2.2 内存

```text
Mem: 15G total, 5.9G used, 1.5G free, 8.0G buff/cache, 8.6G available
Swap: 0B
```

高内存进程：

```text
gaotu-ai-server      15.6%
zhiyuan-server       11.5%
zhiyuan-agent         1.2%
rank worker          about 1.0% each
```

### 2.3 磁盘和 inode

```text
/          40G  22G  16G  58%
/apps     197G  25G 163G  14%
/boot/efi 200M  12M 189M   6%
```

inode：

```text
/      16%
/apps   1%
```

磁盘和 inode 均无容量风险。

## 3. 端口监听

```text
88    docker-proxy -> zhiyuan-web
8090  java -> zhiyuan-server-3.0.0
8091  docker-proxy -> zhiyuan-agent
8092  docker-proxy -> gaokao-volunteer-rank
8080  java -> gaotu-ai-server
22    sshd
2058  n9e-collector
5066  filebeat localhost
```

说明：`8080` 是长期运行的 `gaotu-ai-server`，不是本次志愿新版后端。新版后端监听 `8090`。

## 4. 服务状态

### 4.1 后端

- systemd：`zhiyuan-server-3.0.0-prod.service`
- 状态：`active (running)`
- 启动时间：`2026-05-10 05:47:29 CST`
- 监听端口：`8090`
- profile：`online`
- 配置文件：`/root/work/zhiyuan-server-3.0.0/application-online.yml`
- JAR：`/root/work/zhiyuan-server-3.0.0/zhiyuan-server.jar`
- JAR sha256：`d21c8ca57ef3bcf825f45cec96890f4d6fa2d135fe3721c973c74669233edb69`
- JVM：`-Xms2048m -Xmx2048m`
- Flyway：启动参数中已显式 `--spring.flyway.enabled=false`

### 4.2 Web

- 容器：`zhiyuan-web-3.0.0-prod`
- 镜像：`zhiyuan-web:3.0.0-amd64-wsfix`
- 状态：`Up 2 hours`
- 端口：`88 -> 28688`
- 生产 env：
  - `NEXT_PUBLIC_API_BASE_URL=https://www.gaotuzhiyuan.com`
  - `NEXT_PUBLIC_AGENT_WS_BASE=wss://www.gaotuzhiyuan.com`
- 构建产物地址扫描：
  - `ws://localhost:8000`：0
  - `localhost:8080`：0
  - `127.0.0.1`：0
  - `zhiyuan.ytell.cn`：0
  - 测试域名：0
  - `wss://www.gaotuzhiyuan.com`：2
  - `https://www.gaotuzhiyuan.com`：7

### 4.3 Agent

- 容器：`zhiyuan-agent-3.0.0-prod`
- 镜像：`zhiyuan-agent:3.0.0-amd64`
- 状态：`Up 2 hours`
- 端口：`8091 -> 8009`
- 后端依赖：`INTERNAL_SERVICE_URL=http://host.docker.internal:8090`
- Rank 依赖：`RANK_SERVICE_URL=http://host.docker.internal:8092`
- 当前模型配置为测试期间指定配置：
  - `LLM_PROVIDER=openai_compatible`
  - `LLM_MODEL_NAME=Pro/moonshotai/Kimi-K2.6`
  - `LLM_BASE_URL=https://api.siliconflow.cn/v1`
  - `LLM_TEMPERATURE=0.7`
  - `LLM_MAX_TOKENS=4096`
- `LLM_API_KEY` 仅在容器环境变量中，不记录明文。

### 4.4 Rank

- 容器：`gaokao-volunteer-rank-prod`
- 镜像：`crpi-zmigon88wuzuzy3k.cn-hangzhou.personal.cr.aliyuncs.com/gt_test_123/gaokao-volunteer-rank:prod-2.0.5`
- 状态：`Up 5 months`
- 端口：`8092 -> 5001`

## 5. 容器资源

```text
zhiyuan-web-3.0.0-prod        CPU 0.00%  Mem 104.5MiB  PIDs 43
zhiyuan-agent-3.0.0-prod      CPU 0.11%  Mem 185.3MiB  PIDs 7
gaokao-volunteer-rank-prod    CPU 0.01%  Mem 666.3MiB  PIDs 33
```

Docker 磁盘：

```text
Images       6.311GB, reclaimable 2.485GB
Containers   1.017GB, reclaimable 1.015GB
Build Cache  1.253kB
```

说明：当前保留回滚容器和历史镜像，不建议在升级观察期清理 Docker 可回收空间。

## 6. 健康检查

HTTP 检查：

```text
web_pc_session  200 0.004s  http://127.0.0.1:88/assistant-pc/session
web_v2          200 0.001s  http://127.0.0.1:88/assistant-pc/sessionDetailV2
web_public_v2   200 0.153s  https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2
backend_base    200 0.002s  http://127.0.0.1:8090/gaotu-assistant-bot/base-data/province-city
agent_health    200 0.001s  http://127.0.0.1:8091/gaotu-assistant-agent/health
```

公网 Agent WebSocket：

```text
https://www.gaotuzhiyuan.com/gaotu-assistant-agent/plus/chat/1/bot/1/do
HTTP/1.1 101 Switching Protocols
```

## 7. 日志检查

最近 30 分钟错误关键字检查范围：

- 后端：`journalctl -u zhiyuan-server-3.0.0-prod.service --since '30 min ago'`
- Web：`docker logs --since 30m zhiyuan-web-3.0.0-prod`
- Agent：`docker logs --since 30m zhiyuan-agent-3.0.0-prod`
- Rank：`docker logs --since 30m gaokao-volunteer-rank-prod`

关键字：`ERROR`、`Exception`、`Traceback`、`Failed`、`timeout`、`OutOfMemory`、`500`

结果：未发现匹配错误日志。

## 8. systemd failed unit

```text
cloud-final.service  failed Execute cloud user/final scripts
kdump.service        failed Crash recovery kernel arming
```

判断：

- 与当前应用主链路无直接关系。
- 建议后续运维窗口确认是否需要清理 failed 状态或修复 kdump。

## 9. 回滚对象

```text
zhiyuan-web-3.0.0-prod-before-wsfix   Exited, 修复前 3.0.0 前端容器
gaotu-volunteer-assistant-prod        Exited, 老生产前端容器
gaotu-zy-agent-plus-prod              Exited, 老生产 Agent 容器
gaokao-volunteer-rank-prod            Running, 老生产 Rank 容器，当前仍作为生产 Rank 使用
gaotu-assistant-server-rollback.service stopped, 老生产后端回滚服务
```

## 10. 遗留关注项

1. `gaotu.zhiyuan.evn=grayTest`
   - 新老后端 online 配置一致，非本次升级引入。
   - 代码会将该值作为 `traffic-env` 请求头传给高途内部接口。
   - 是否调整需确认高途内部流量路由约定，不建议直接修改。

2. 前端 `.env.prod` 中 `NEXT_PUBLIC_ASSISTANT_API_BASE_URL`、`NEXT_PUBLIC_OUTER_API_BASE_URL` 缺失
   - 当前 `APP_ENV=production` 下生产 rewrites 写死到 `https://www.gaotuzhiyuan.com`，主链路不受影响。
   - Next 启动会提示 warning，后续可补生产值消除告警。

3. 本机未发现 Nginx/OpenResty 进程，`/etc/nginx` 不存在
   - 公网访问应由外层网关或负载均衡转发到本机端口。
   - 后续如需调整公网路由，需要到外层网关侧确认。

4. Docker 可回收空间
   - 当前约 2.5G 镜像、1.0G 停止容器层可回收。
   - 升级观察期建议保留，确认稳定后再清理临时构建容器和旧镜像。

## 11. 巡检结论

本次巡检结论为：当前生产服务器资源健康，应用主链路健康，Web/Backend/Agent/Rank 运行状态正常，公网 WebSocket 可用，近期无明显应用错误日志。建议继续保留回滚对象并观察一段时间，暂不做清理或配置变更。
