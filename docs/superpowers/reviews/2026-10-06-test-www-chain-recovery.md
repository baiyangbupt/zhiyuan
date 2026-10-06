# `test-www` 链路打通与恢复（2026-10-06）

> 性质：对 [2026-10-05 复核](2026-10-05-test-www-chain-functional-review.md) 的执行与现场记录。
> 基线：`wip/2026-09-28-p2-write-loop-green`（工作树，改动随后分批提交）。
> 本机条目均为当日实测；公网条目注明时点。

## 一、链路真相对齐（10-05 复核的修正与补全）

公网 `test-www` 按路径分流到本机，**不是整体反代**：

| 公网路径 | 上游 | 10-06 实测 |
|---|---|---|
| `/assistant-pc/` | 本机 3001（Next 生产构建） | 与本机构建逐字节一致；buildId `r5kkGJIzvdokNeWUTXZi3` |
| `/gaotu-assistant-bot/` | 本机 18090（Java **直连，不经 Next**） | 请求 trace 落在本机 Java 日志 |
| `/gaotu-assistant-agent/plus/chat` | 本机 18091（compat WS） | 无票 403（验票生效） |
| `/ws/chat`、`/` 等其余路径 | **另一个前端部署**（buildId `mPNub…`，不在本机） | `/ws/chat` 404 HTML（主站 Next 的 404 页） |

两处断点的根因（10-05 只定位到"没到验票入口"，本轮钉死）：

1. **`/ws/chat` 404**：test-www 生效 vhost 没有 `/ws/chat` 的 location（V3 路由是后加的）。
   前端构建产物确认浏览器连的就是同源 `wss://test-www.gaotuzhiyuan.com/ws/chat` →
   请求落进兜底被转给主站 Next → 404。**修复=代理加一个 location，在本机之外**。
2. **匿名 `/inner` 200**：同一 vhost 把 `/gaotu-assistant-bot/` 整体直通 18090，而 Java
   `LoginInterceptor` 主动排除 `/**/inner/**`、`/**/admin/**`、`/internal/evidence/**`
   （`WebConfig.java:42-45`，"靠网络隔离"）。三层叠加：代理没挡 + Java 放行 +
   Next 生产分支无守卫。**第一道修在代理层**。

## 二、本轮落地（全部已部署到标准测试栈）

### P0（Next 层守卫，纵深）

生产分支此前漏挂内网守卫。三种写法实测后定形（`next.config.mjs`）：

- rewrite 挂相对死路径 → Next 13.5 校验拒绝（`basePath:false` 目标须为外部 URL），**构建失败**；
- `src/middleware.ts` → 只拦带 basePath 的形态，浏览器真实的根路径不进 middleware；
- **最终**：生产 rewrites 首部加守卫，死路径落在 **Agent 未映射路径**（干净 404 JSON；
  后端对未映射路径统一 500，不合 404/403 验收口径）；middleware 保留兜 basePath 形态。
- 直连 3001 实测：根形态 404 ✓、basePath 形态 404 ✓、公开路由 200 ✓
  （`src/utils/codexLocalRewrite.test.mjs` 3 用例钉住形状）。

### P1（test-www 最短会话链，**本机段全绿**）

`scripts/probe-standardtest-ws-chain.py`（新增，可重复跑）实测：

```
无票 /ws/chat            → HTTP 403 ✓（不消费票）
错 Origin（带票）        → HTTP 403 ✓（不消费票，票仍可用）
合法票                   → WS 101 ✓
turn.started → turn.phase → tool.progress×2
  → assistant.completed（真实模型回复，实际调用只读工具 catalog.get_major）
  → turn.completed{executionStatus: completed, toolStatus: completed} ✓
助手回复与用户消息均已落 Java（message/page 可查，4 行）✓
```

- 取票：`POST /chat/1/conversation/ws-ticket`（tk/pf/Origin，body `{sessionId,botId}`）code=0。
- 会话：`session/create` draft 新建 10041940（用户 900001）。
- 终态帧带**真实执行状态**（不是硬编码 completed，见下）。

### 工作台公开 facade（P0 封堵的前置，后端已就绪）

`PlanningFacadeController`（新）：`/gaotu-assistant-bot/chat/{tenantId}/planning/session/...`，
17 个活端点 + 新 evidence 端点；每方法 `requireOwnedSession`（tenant/user/bot 三项），
跨用户/跨租户真实 403；未登录真实 401（`LoginInterceptor` 扩展）；
响应结构与 inner **逐字节相同**（隔离栈实证）；6 个死端点未搬。
前端路径切换进行中（另一条线）。

### 空会话「同会话补录成绩」（产品裁决=同会话补录）

`POST /chat/{tenantId}/session/update-score-detail?chatSessionId=`：
五项校验 + 权益 + ownership → userScoreDetail **merge upsert**（null 不覆盖）→
志愿数据文件重拉（`fetchLatestSourceData(persist=true)`）→ 规划版本 +1 与 stale 置位
（candidatePool/推荐/方案/review）→ `requiresWorkspaceReload=true`。
Java 847 测试全绿；网关侧补 3 条快照刷新用例。前端入口 UI 待做（另一条线）。

### 核心对话四修复（隔离栈 contract 12 + write 4 全绿）

1. 终态帧真实状态（`server.py` 从 result 取 executionStatus/limitations；失败支不再假 completed）；
2. 纯文本回合在事件流侧渲染（gate 补 answer/proposal/error；并修掉 e2e 抓到的
   "老信封空 turnId 幽灵回合"回归）；
3. `turn.started` / `turn.phase` 生产者（此前白名单有、全仓无生产者）；
4. `clarification.resolved` 走 V1（澄清卡即时收起）。
单测：agent 1906 passed（+7 新增）+ web 36 passed；唯一红仍是既有的
dialog_quality_gate 夹具缺失（数据/环境，非代码）。

## 三、当日两起事故与根治

1. **`.next` 共用**：隔离栈 `next dev`（3201）与标准栈 `next start`（3001）长期共用
   `zhiyuan-web/.next`，dev 配置热重载清掉生产文件 → 公网 `/assistant-pc/` 500（约 10 分钟）。
   **根治**：`distDir: process.env.NEXT_DIST_DIR || '.next'`，隔离栈注入 `.next-dev`
   （`scripts/start-codex-local.sh`，已加 .gitignore），两栈可并行。
2. **磁盘 100% 满（埋了 8 天）**：Redis `MISCONF…stop-writes-on-bgsave-error`
   （上次成功落盘 ≈09-28）→ 取票写 Redis 失败（code -1）→ 登录/取票链路断。
   症状与修法：`redis-cli info persistence | grep rdb_last_bgsave_status`；
   清理 `/root/.npm/_cacache`（2.6G）+ 截断 330MB 的 Java 活日志后 `BGSAVE` 恢复。
   当前 94%（2.6G 可用）；docker 另有 ~3.7G 可回收（e2e playwright 镜像在用，未动）。

## 四、剩余（按归属）

**代理持有方（本机之外，ops）** —— 交付物 `ops/nginx/test-www.locations.conf`：
1. `location = /ws/chat` → `http://10.218.4.10:18091`（Upgrade/Connection/900s/关缓冲）；
2. `location ~* ^/gaotu-assistant-bot/(inner/|internal/|admin/|debug/) { return 404; }`
   + `/internal/evidence/` 与 agent 前缀同型守卫；
3. 部署后跑 `bash scripts/smoke-standardtest-hardening.sh`（当前 2 红=待部署项）
   + `scripts/probe-standardtest-ws-chain.py`（101 全链）+ 浏览器真登录验收；
4. 封堵 inner 的连带面：`ops/release-smoke.sh` remote 模式与 `ops/healthcheck.sh:142`
   的 inner 探针指向公网，需改直连后端；浏览器工作台需待前端 facade 切换合入。

**本仓库（已在推进）**：
- 前端 facade 路径切换（会话中）；
- 空会话补录的前端入口 UI；
- 后续优化（已定位）：`conversation_action` 路径的快照缓存可能旧（补录后紧急操作会用到
  缓存快照，建议强制重读）；`assistant.delta` 未流式（首字延迟感知）；老信封伴发帧的
  长期收敛；dialog_quality_gate 夹具（需真实数据，禁造数）。
