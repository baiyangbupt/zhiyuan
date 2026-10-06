# 本地标准测试环境部署 Runbook

本文记录本机标准测试环境的部署口径，重点覆盖最容易出错的上游路由、Web 静态资源、Backend/Agent 端口和 PC 首页 token 跳转链路。

本文件是本地标准测试环境的唯一维护入口。release 文档只记录版本发布结论，端口、上游路由、私有 `.env.standardtest`、pid、日志、运行时数据和 smoke 过程不要分散写到各个 release 文档里。

## 当前热修回归端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| Web | `3001` | `test-www` 的 `/assistant-pc/` upstream |
| Backend | `18090` | `test-www` 的 `/gaotu-assistant-bot/` upstream |
| Agent | `18091` | `test-www` 的 `/gaotu-assistant-agent/plus/chat` upstream |
| Rank | `18092` | 本地 Rank 服务 |

## 上游路由

标准测试域名 `https://test-www.gaotuzhiyuan.com` 当前由上游直接分流：

```text
/assistant-pc/                  -> http://10.218.4.10:3001
/gaotu-assistant-bot/           -> http://10.218.4.10:18090
/gaotu-assistant-agent/plus/chat -> http://10.218.4.10:18091
```

因此标准测试入口不是生产 Docker Web `:88`。本地排查前端自动登录时，以 `3001/18090/18091` 为准。

## 构建前配置

Next rewrites 是构建期固化进 `.next/routes-manifest.json` 的。虽然 `test-www` 会在 Nginx 层直接分流 `/gaotu-assistant-bot/` 和 `/gaotu-assistant-agent/`，但直接访问 `http://127.0.0.1:3001` 时仍依赖 Next rewrites。

本地私有 `.env.standardtest` 需要使用宿主机可解析地址：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18090
NEXT_PUBLIC_ASSISTANT_API_BASE_URL=http://127.0.0.1:18090
NEXT_PUBLIC_AGENT_API_BASE_URL=http://127.0.0.1:18091
NEXT_PUBLIC_OUTER_API_BASE_URL=https://test-www.gaotuzhiyuan.com
```

构建后必须确认 `zhiyuan-web/.next/routes-manifest.json` 中包含：

```text
/gaotu-assistant-bot/:path* -> http://127.0.0.1:18090/gaotu-assistant-bot/:path*
/gaotu-assistant-agent/:path* -> http://127.0.0.1:18091/gaotu-assistant-agent/:path*
```

## 启动约束

标准测试 Web 必须在 `3001` 重新启动到当前 `.next`，否则容易出现 HTML 引用新 build id、但旧 `next start` 进程找不到 `_next/static` chunk 的情况。

```bash
cd /root/dev/zhiyuan/zhiyuan-web
./node_modules/.bin/env-cmd -f .env.standardtest ./node_modules/.bin/next start -H 0.0.0.0 -p 3001
```

**构建目录与隔离栈分离（2026-10-06）**：隔离栈的 `next dev`（3201）曾与这里共用同一个
`zhiyuan-web/.next`，dev 一热重载就把生产构建的 server 文件清掉（公网 `/assistant-pc/` 500）。
现由 `next.config.mjs` 的 `distDir: process.env.NEXT_DIST_DIR || '.next'` 分离：
**本栈保持默认 `.next`**，隔离栈由 `scripts/start-codex-local.sh` 注入 `.next-dev`。
重建顺序照旧：`env-cmd -f .env.standardtest next build`（必须在当前 `.next`，即不要在
隔离栈 dev 进程活跃时构建）→ 重启 3001。

Backend 必须监听 `18090`，并指向标准测试 Agent/Rank：

```bash
java -jar zhiyuan-server/target/zhiyuan-server.jar \
  --spring.profiles.active=localtest \
  --server.port=18090 \
  --agent.zhiyuan.url=http://127.0.0.1:18091 \
  --volunteer.rank.url=http://127.0.0.1:18092
```

Agent 必须监听 `18091`：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
INTERNAL_SERVICE_URL=http://127.0.0.1:18090 \
RANK_SERVICE_URL=http://127.0.0.1:18092 \
.venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 18091
```

## Smoke 验证

优先使用脚本：

```bash
bash scripts/smoke-standardtest-web-proxy.sh
```

脚本会检查：

- `test-www` 登录页返回 `200`。
- 登录页引用的 `pages/login-*.js` chunk 在 `test-www` 和本机 `3001` 均返回 `200`。
- `test-www` 的 `/gaotu-assistant-bot/` 路由返回 `200`。
- `test-www` 的 `/gaotu-assistant-agent/health` 返回 `200`。
- 直接访问 `3001` 时，Next rewrites 能代理到 `18090/18091`。
- 直接访问 `18090/18091` 均返回 `200`。

手动验证命令：

```bash
curl -sS -o /dev/null -w 'login:%{http_code}\n' \
  'https://test-www.gaotuzhiyuan.com/assistant-pc/login?channel=gaotu'
curl -sS -o /dev/null -w 'backend_proxy:%{http_code}\n' \
  'https://test-www.gaotuzhiyuan.com/gaotu-assistant-bot/base-data/province-city'
curl -sS -o /dev/null -w 'agent_proxy:%{http_code}\n' \
  'https://test-www.gaotuzhiyuan.com/gaotu-assistant-agent/health'
```

### 加固与 WS 链路（2026-10-06 新增）

- `bash scripts/smoke-standardtest-hardening.sh`：断言 P0/P1 目标态——匿名 `/inner` 404、
  `/ws/chat` 无票 403（到 Agent 验票路由）、既有公开路由不回归。**部署代理加固前，
  inner 与 ws/chat 两项为预期红**。
- `zhiyuan-agent/.venv/bin/python scripts/probe-standardtest-ws-chain.py <chatSessionId>`：
  本机段全链（无票/错 Origin 403 → 合法票 101 → turn 事件 → 终态）。会话需属
  `tk: codex-local-test-token` 对应的用户 900001（可取新建 draft 会话）。
- 代理侧交付物：`ops/nginx/test-www.locations.conf`（`/ws/chat` location + inner 守卫），
  部署与验收步骤见该文件注释；完整状态见
  [2026-10-06 复核](../superpowers/reviews/2026-10-06-test-www-chain-recovery.md)。

## PC 首页 Token 跳转

PC 端链接没有 `source=minip` 时，登录成功后的预期跳转是：

```text
/assistant-pc/session
```

不应跳到移动端入口 `/assistant-pc/customer`。如果同一个 token 重复使用后上游返回 token 异常，不能继续用该链接判断前端跳转，需要从首页重新生成新的 token 链接。

## 常见故障

| 现象 | 优先检查 |
| --- | --- |
| 首页 token 登录后不跳转 | `test-www /gaotu-assistant-bot/chat/user/login/by-token` 是否到 `18090` 且业务 `code=0` |
| 登录页空白或不执行自动登录 | `test-www` 和 `3001` 的 `pages/login-*.js` chunk 是否返回 `200` |
| 对话输入闪一下又消失 | `/gaotu-assistant-agent/plus/chat` 是否到 `18091`，Agent 是否监听 `0.0.0.0:18091` |
| 发消息完全无响应（连不上） | 公网 `/ws/chat` 是否有代理 location（2026-10-06 前一直缺，见复核 §一）；跑 `smoke-standardtest-hardening.sh` 第 5 项 |
| 取票失败（code -1）/ 登录异常 | Redis 是否 `MISCONF`（`docker exec zhiyuan-codex-local-redis-1 redis-cli info persistence` 看 `rdb_last_bgsave_status`）；**先查磁盘 `df -h /`**（10-06 曾 100% 满致 8 天未落盘） |
| 直接访问 `3001` API 失败 | `.env.standardtest` 是否仍是 Docker 专用 `host.docker.internal` |
| 改了 ENV 但代理仍走旧端口 | 是否重新执行过 `next build` |
| PC 端误进 `/customer` | URL/storage 是否带 `source=minip`，PC 链接应进入 `/session` |

## Git 维护边界

可以进仓维护：

- 本 runbook。
- 不含密钥和个人路径的 smoke 脚本，例如 `scripts/smoke-standardtest-web-proxy.sh`。
- 与标准测试环境兼容相关的通用代码修复。

不应进仓：

- 私有环境文件：`zhiyuan-web/.env.standardtest`、`zhiyuan-agent/.env`。
  - **2026-10-06 起 `.env.standardtest` 是仓内实体文件** ✓（此前是指向 `.local-prod-3.0.2/zhiyuan-web/`
    的软链，该目录在一次磁盘清理中被误删导致 3001 无法启动 ✗）。**不要删除 `.local-prod-3.0.2`
    之类的"旧目录"前先 `find /root/dev/zhiyuan -xtype l` 查悬空链** ✓；备份副本在
    `.local/standardtest-env-backup/.env.standardtest` ✓。
- pid 和日志：`.pids*`、`logs/`。
- 运行时志愿文件：`zhiyuan-server/data/tmp/session_volunteer_*.json`。
- 生产回捞原始资产和本地回放结果：`assets/`。
- 含测试库账号、内网地址、一次性 session 或 token 的临时脚本和便签。
