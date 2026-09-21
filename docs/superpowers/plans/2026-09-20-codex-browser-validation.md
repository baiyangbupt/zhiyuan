# Codex 本地与测试域名浏览器验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在隔离本地栈和 `https://test-wwww.gaotuzhiyuan.com` 用真实浏览器证明选项、进度、事实、方案确认及恢复可用。

**Architecture:** 本地四服务仍只监听 loopback，由 HTTPS/WSS 代理开放 Web 与已认证入口。Java 签发会话专属短期 WS ticket，Gateway 验票后再连接会话；UI 与 Java 状态联合验收。

**Tech Stack:** 现有 Bash/Docker Compose、Next.js、Nginx、Java 登录拦截器与 Redis、Python Gateway、新增 Playwright。

**Spec:** [核心设计](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)，以及 [A 交互计划](2026-09-20-codex-native-interaction.md)、[B 业务计划](2026-09-20-codex-domain-and-plan-transactions.md)。

## Global Constraints

- 仅使用 private-resettable 本地数据库/Redis，真实写入用例不连接共享/线上业务库；固定 domain 为用户给出的 test-wwww，不能混成 test-www。
- dev 页面的 basePath 是 `/`；公网浏览器不得连接 localhost/127.0.0.1 或 ws://。HTTP upstream 仍用 loopback，不指回公网自身。
- 只将本地验证端口反向代理开放；不暴露 App Server/MCP/数据库/Rank/inner 管理接口。
- 本文是实施与检验步骤，不能因本地服务曾启动过就勾选浏览器或域名验收完成。
- A/B 确定性 gate 完成后再运行完整业务验收；B3 未有真实来源时章程/年度计划 gate 明确未完成，不能计入已交付。

## Task C1：登录、会话 ownership 与 WebSocket 票据

**Files:** 新增 `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationAccessService.java`、`manager/cache/ConversationWsTicketStore.java`、`web/controller/ConversationAccessController.java`、`web/controller/inner/ConversationAccessInnerController.java`、`web/controller/PlanningController.java`、对应 `src/test/java/.../service/biz/ConversationAccessServiceTest.java` 与 `web/controller/ConversationAccessControllerTest.java`；修改 `web/controller/ChatController.java`、`service/biz/ChatSessionBizService.java`、`common/config/WebConfig.java`、`zhiyuan-agent/app/server.py`；新增 `zhiyuan-agent/app/gateway/access.py` 与 `tests/integration/test_gateway_access.py`；修改 Web 的 `src/service/apis/sessionDetail.ts`、`src/hooks/useWebSocket.tsx`、`src/interface/api/volunteer.ts`。

**Interfaces:** `requireOwnedSession(tenantId,sessionId,principalUserId)->ChatSession`；`POST /gaotu-assistant-bot/chat/{tenantId}/conversation/ws-ticket`（body sessionId,botId）；`POST /gaotu-assistant-bot/inner/conversation/ws-ticket/consume`（ticket,origin）。consume 响应 `{tenantId,sessionId,userId,botId,expiresAt}`，只给内部可信 Gateway。

```json
{"sessionId":"42","botId":"1"}
```

- [ ] 先写 ownership 测试：有效用户、自报另一个 userId、其他 tenant/其他用户的 session、不存在 session、错误 bot、ticket 复用与过期。当前 `getUserSessionDetail` 仅 getById，不能把它当已授权。
- [ ] 登录 HTTP 继续复用 `LoginInterceptor` 的 tk/pf 与 `UserInfoThreadLocalUtil.get().getUserId()`；新增 ConversationAccessService 从 `ChatSessionSharedService.getById` 取 session，逐项比对 tenant/user/bot，失败统一 403，不泄露 session 是否存在。

实现 HTTP 状态时补修改 `web/interceptor/LoginInterceptor.java` 与 `common/config/GlobalExceptionHandler.java`：当前未登录返回业务码800，BusinessException 默认 HTTP200。新 ticket/facade 使用专用 `ConversationAccessException`（新增 `common/exception/ConversationAccessException.java`）及 ResponseEntity 映射为 HTTP401/403；LoginInterceptor 在新路径未登录时也设401。保留旧接口既有业务码兼容语义，不全站改变状态码。上面 requireOwner 骨架最终改抛专用异常；HTTP测试必须断言 transport status 和 body.code，不能只断言异常类型。

```java
// ConversationAccessService 的核心授权判断；session 来自数据库。
static void requireOwner(com.ytell.zhiyuan.model.entity.biz.ChatSession session,
                         Long tenantId, Long principalUserId) {
    if (session == null || !java.util.Objects.equals(session.getTenantId(), tenantId)
            || !java.util.Objects.equals(session.getUserId(), principalUserId)) {
        throw new com.ytell.zhiyuan.common.exception.BusinessException(403, "session_forbidden");
    }
}
```

- [ ] Redis ticket：SecureRandom 32 bytes，base64url；服务器仅存 SHA-256(ticket)→身份+允许 Origin，TTL=60秒，Lua GET+DEL 原子消费。ticket 不承载用户可修改身份；WS 重连重新取票。inner consume 要内部服务认证与网络限制，不能只靠 URL 含 inner。
- [ ] 浏览器通过现有 tk/pf HTTP client 取票，再把 ticket 放连接 query；两个 WS 路由在 accept 前消费并核 Origin 与 tenant/session/bot，忽略 WS body 的身份；本地 Origin allowlist 仅 `http://127.0.0.1:3201`，公网仅指定 HTTPS 域名。禁止任意 Origin 通配。
- [ ] 删除浏览器 hook 的完整 WS URL 日志、服务端 query URL 日志和代理 query 日志；只记 path、连接 ID、匿名 session 摘要。控制台、HAR、Playwright trace 按凭证脱敏后归档。
- [ ] 公共 PlanningController 定义 `/gaotu-assistant-bot/chat/{tenant}/planning/session/...`：将 sessionDetail.ts 里全部 `/inner/planning/{tenant}/session/...` 逐个迁到 facade（state、workspace-state、候选查询/筛选、view-state、review、preview、确认、导出）。每个方法先 requireOwnedSession 再调用现有服务，禁止通配 path 透传 inner；现有手动编辑动作仍用各自明确 request DTO/CAS。
- [ ] 同时补 ChatController 的 session/detail、message/page、反馈/导出/画像等所有可触达 session 入口 ownership；messageId 必须先解析所属 session 再核验。session list/create 使用登录身份，不信任 body.userId。iframe/代理不会替应用完成此检查。
- [ ] 执行 Java `mvn -Dtest=ConversationAccessServiceTest,ConversationAccessControllerTest test`，Python `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_gateway_access.py -q`；明确未登录=401/拒绝握手、跨用户=403、已消费票据拒绝，合法用户能读取自己的工作台。

## Task C2：显式本地/公开模式和反向代理

**Files:** Modify `scripts/start-codex-local.sh`、`scripts/preflight-codex-local.sh`、`zhiyuan-web/next.config.mjs`、`zhiyuan-web/src/hooks/useWebSocket.tsx`、`zhiyuan-agent/tests/unit/test_codex_local_stack_scripts.py`、`zhiyuan-web/src/utils/codexLocalRewrite.test.mjs`；Create `ops/nginx/codex-test.locations.conf`、`scripts/smoke-codex-public.sh`；Update `docs/codex-local-stack.md`。

**Interfaces:** 新配置 `CODEX_LOCAL_ACCESS_MODE=local|public-test`，`CODEX_LOCAL_PUBLIC_ORIGIN=https://test-wwww.gaotuzhiyuan.com`，`CODEX_LOCAL_OUTER_API_BASE_URL`（必须显式配置受控测试源）。脚本将值落实到实际使用的 NEXT_PUBLIC 变量及 Agent Origin allowlist，不只声明一个未消费的 PUBLIC_TEST_ORIGIN。

- [ ] 先写脚本/URL 测试：local 生成 loopback ws，public-test 生成同源 wss，拒绝公网 origin 含路径/凭证、拒绝 outer 指向自己或默认生产域名。当前脚本硬设 loopback 和 production outer，测试应失败。
- [ ] 公开模式清空 WS override，hook 以 `window.location` 派生；本地使用现有 override。注意 `NEXT_PUBLIC_*` 按构建时固化；dev 重启，production 重新 build/start，不仅改 Nginx。

同时修改 `src/pageComponents/sessionDetailV2/MessageList/index.tsx` 的 URL 构造调用点（实际在此拼 URL）：公开模式强制传同源配置，不再回退到 `NEXT_PUBLIC_AGENT_WS_BASE`。新增测试“旧 WS_BASE 非空、override为空、public-test模式”，仍必须得到当前域名 wss；仅改 hook 不够。

```javascript
export function socketBase(location, override) {
  if (override) return override.replace(/\/$/, '');
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`;
}
```

将函数放新增 `src/utils/conversationSocket.mjs` 并由 hook 导入；对应 `conversationSocket.test.mjs` 检查远程 HTTPS、不带尾斜线、本地 override。HTTP rewrites 明确保留 loopback upstream。

- [ ] 以下是可 review 的 location 配置，放在现有受控 TLS server 中；TLS证书/server_name 复用实际代理配置，部署前 `nginx -t`。`map` 与 `log_format` 放 http 层，不能误塞 server 内。

```nginx
# http 层
map $http_upgrade $codex_connection_upgrade { default upgrade; '' close; }
log_format codex_no_query '$remote_addr $request_method $uri $status';

# server_name test-wwww.gaotuzhiyuan.com 的现有 HTTPS server 内
access_log /var/log/nginx/codex-test-access.log codex_no_query;
location ~* ^/gaotu-assistant-bot/(inner/|internal/|admin/|debug/) { return 404; }
location ^~ /internal/evidence/ { return 404; }
location = /ws/chat {
    proxy_pass http://127.0.0.1:18291;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $codex_connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 900s;
    proxy_buffering off;
}
location /gaotu-assistant-agent/plus/chat/ {
    proxy_pass http://127.0.0.1:18291;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $codex_connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 900s;
    proxy_buffering off;
}
location /gaotu-assistant-bot/chat/ {
    proxy_pass http://127.0.0.1:18290;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /gaotu-assistant-bot/ { return 404; }
location /gaotu-assistant-agent/ { return 404; }
location / {
    proxy_pass http://127.0.0.1:3201;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $codex_connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

以上 chat 路径只有完成 C1 全入口 ownership 后才开放；现有页面还需要哪些匿名 base-data 路径由 C3 Network 清单核实，逐个 exact location 放行且确认仅基础字典，不能 broad proxy 整个 bot/agent。Next rewrite 也必须阻止 `/inner/` 由 `/` 兜底穿透；外层明确拒绝这些路径。

- [ ] Agent/Java/Rank 仍只监听 127.0.0.1，数据端口也不对外；确认反向代理进程能访问宿主 loopback（若代理在容器需显式网络映射，不能把容器的 127.0.0.1 当宿主）。

这是明确代码改动：`docker-compose.codex-local.yml` 两处 ports 改为 `127.0.0.1:${MYSQL_PORT:-13306}:3306` 与 `127.0.0.1:${REDIS_PORT:-16379}:6379`；Java启动加 `--server.address=127.0.0.1`。运行 `ss -ltnp` 核对四服务和两个数据端口，不允许 0.0.0.0/::。当前代码没有满足该断言，不能只改文档。
- [ ] `smoke-codex-public.sh` 参数为 `--origin` 与 `--base-path /`，检查 HTTPS 页面、静态资源、内网路径拒绝、合法 ticket Upgrade=101；没有凭证只运行匿名拒绝检查并记 authenticated=not_run。不原样复用固定 test-www/assistant-pc 的旧 smoke。
- [ ] 验证 `bash -n scripts/start-codex-local.sh scripts/preflight-codex-local.sh scripts/smoke-codex-public.sh`，Node URL/rewrites 测试、Agent 脚本单测；保存 Nginx 配置差异，实际部署入口动作仅在 C3 环境确认为本次测试服务时执行。

## Task C3：可重置栈与人工浏览器基线

**Files:** Create `scripts/seed-codex-acceptance.py`、`docs/validation/codex-native-environment.md`、`docs/validation/codex-native-browser-checklist.md`；Modify `docs/codex-local-stack.md`。seed 脚本只允许本地 private-resettable 数据，输入合成测试账户、成绩画像、两个 tenant、多个 session，不从线上复制个人资料。

**Interfaces:** seed 产出忽略目录 `.runtime/codex-acceptance/fixture-ids.json`（tenant/session/账户别名/案例映射），认证凭证另存 0600 文件；reset 只删除本次 runId 创建的数据，不能重置整个已有本地栈。

- [ ] 读取当前实际监听与启动记录，确认是否复用用户已启动的测试栈；没有记录的 PID 不接管、不停止。启动新栈前用 preflight 检查四端口及数据库/Redis实际实例标识，`private-resettable` 字符串本身不是隔离证明。
- [ ] 新栈按现有命令启动（以下在 zhiyuan 根目录；首次创建隔离配置，填写受控上游连接，不打印其内容）：

```bash
bash scripts/codex-local-infra.sh start
export CODEX_LOCAL_SERVER_CONFIG="$PWD/.local/codex-local/application-codex-local.yml"
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME="$PWD/.local/codex-local/runtime-home"
export CODEX_LOCAL_ACCESS_MODE=local
bash scripts/preflight-codex-local.sh
bash scripts/start-codex-local.sh
```

CODEX_LOCAL_OUTER_API_BASE_URL、模型登录和 B3 来源在启动前用私有配置补好；缺失时预检失败，不能退回生产默认值。runtime-home 需已配置合法模型访问，建立空目录不等于可调用。

- [ ] seed 脚本校验目标 DB/Redis 与 runId，然后建立两个 tenant 的数据；确认非 tenant1 用例；生成只在测试域名下使用的登录会话。
- [ ] 本机打开 `http://127.0.0.1:3201/` 与实际 sessionDetailV2 路由，登录并完成一条历史查询。记录页面路径、Network 请求路径/目标、WS handshake、第一条进度、最终消息、workspace API；禁止记录原始 token 或 ticket。
- [ ] 本地场景通过后用该 run 的 stop 脚本停止；保留隔离数据，将 `CODEX_LOCAL_ACCESS_MODE=public-test`、`CODEX_LOCAL_PUBLIC_ORIGIN=https://test-wwww.gaotuzhiyuan.com` 重新启动。在新模式下只用 HTTPS origin 重新登录/取票，不再要求 loopback 页面执行对话，不跨 Origin 复用票据。
- [ ] 验证 DNS/TLS：`getent hosts test-wwww.gaotuzhiyuan.com`，`curl --fail --head https://test-wwww.gaotuzhiyuan.com/`；实际域名映射与证书 SAN 一致才加载 C2 配置。HTTP 成功不证明 WS 已升级，必须在浏览器再取票确认 101。
- [ ] 从另一台设备/网络打开 HTTPS 域名，Network 中没有 localhost、ws://、旧 test-www、production API、inner endpoint；公开 inner 返回拒绝；页面静态资源/HMR 在 dev 可用。加入确需匿名字典的 exact 代理路径后重跑。
- [ ] 保存 baseline 报告：四服务版本/端口、代理路径、数据实例标识（无凭证）、浏览器版本、功能开关、实际验证项。未配 DNS/证书或入口权限时写具体阻塞项，不将本地 curl 代替公网通过。

## Task C4：浏览器自动化与真实交互验收矩阵

**Files:** Modify `zhiyuan-web/package.json` 与实际包管理器 lockfile；Create `zhiyuan-web/playwright.config.ts`、`tests/e2e/conversation.spec.ts`、`tests/e2e/proposal.spec.ts`、`tests/e2e/access.spec.ts`、`tests/e2e/fixtures.ts`；Create `zhiyuan-agent/tests/fixtures/codex/browser_app_server.py`（可控阶段闸门）；补 MessageList/卡片元素 data-testid。

**Interfaces:** 两个 project：`contract`（真实浏览器+Gateway+Java隔离库，fake Codex 精确控制事件）；`real`（同栈改真实 Codex+真实只读上游/批准的隔离写入数据）。`ZHIYUAN_E2E_ORIGIN` 提供页面 origin；`ZHIYUAN_E2E_SESSION_URL` 提供 C3 确认的会话路由。

- [ ] 明确安装浏览器测试依赖，当前项目没有 Playwright：在 Node≥22.14.0 下按现有 lockfile 选择包管理器，新增固定版本 `@playwright/test`，安装 Chromium，package scripts 加 `test:e2e`。不假定已存在 Jest/Vitest。
- [ ] 新增 `scripts/start-codex-contract.sh`、`zhiyuan-agent/tests/fixtures/codex/browser_runtime_control.py`、`browser_codex_wrapper.sh`。wrapper 可执行，以测试 venv Python 启动 browser_app_server.py，接受并校验 composition 传来的 `app-server --stdio`/配置参数；仅 contract launcher 设置 CODEX_APP_SERVER_BIN 为其绝对路径。新增 loopback 控制端口18293，`GET /identity` 返回 runtimeKind=fake、`POST /gates/{turnId}/release` 放行、`POST /runs/{runId}/reset` 只清本次闸门。fake app-server 通过本地控制连接等待闸门，launcher 记录控制服务 PID 并负责停止；不开放该端口到 Nginx。
- [ ] contract 命令为 `bash scripts/start-codex-contract.sh`（复用隔离infra和四服务，先启动control再Gateway），测试前校验 identity=fake；real 命令用常规 start-codex-local.sh 和真实二进制能力报告，校验 identity/版本证据为真实。项目名本身不能决定 Runtime。port18293占用时拒绝启动，不能接管已有进程。
- [ ] 配置代码（首次必须因缺 origin/session/auth fixture 失败；不能默认打生产）：

```typescript
import { defineConfig } from '@playwright/test';
if (!process.env.ZHIYUAN_E2E_ORIGIN) throw new Error('ZHIYUAN_E2E_ORIGIN required');
export default defineConfig({
  testDir: './tests/e2e', workers: 1, retries: 0,
  use: { baseURL: process.env.ZHIYUAN_E2E_ORIGIN, trace: 'off', screenshot: 'only-on-failure' },
  projects: [
    { name: 'contract', testMatch: '**/*.contract.spec.ts' },
    { name: 'real', testMatch: '**/*.real.spec.ts' },
  ],
});
```

实际文件名按上面的 testMatch 分为 `conversation.contract.spec.ts`、`proposal.contract.spec.ts`、`access.contract.spec.ts` 和 `admissions.real.spec.ts`、`planning.real.spec.ts`。fixture 以 C3 的测试账户登录，server-side fake gate 控制只在 contract 栈启用；不能让公网用户传参数切换 fake 模型。真实 project 单独启动 runtime，不并发打模型；敏感截图在归档前脱敏。

每例创建独立 session 与固定初始版本，通过 fixture-ids/runId 标识；fixtures 导出 `{sessionUrl,turnId,expectedSourceVersion,runtimeGate}`，客户端测试注入固定下一次 clientRequestId/turnId（仅测试构建），元素标记 `data-turn-id`。Proposal 用例同时记录初始 operation 数量、方案内容、版本。失败保留本例数据和日志，成功才按 runId 清理；不得复用 C3 已聊过的 session 来断言全页消息数。

- [ ] 一条不依赖固定延时的流式测试：fake 模型等 fixture 控制释放终态，UI 必须先显示进度、停止仍可操作。

```typescript
import { test, expect } from './fixtures';
test('执行尚未结束时已显示工具阶段', async ({ page, runtimeGate, sessionUrl, turnId }) => {
  await page.goto(sessionUrl);
  await page.getByTestId('chat-input').fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();
  const turn = page.locator(`[data-turn-id="${turnId}"]`);
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取');
  await expect(turn.getByTestId('turn-stop')).toBeEnabled();
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);
  await runtimeGate.releaseFinal();
  await expect(turn.getByTestId('assistant-final')).toHaveCount(1);
});
```

`fixtures.ts` 定义 `runtimeGate:{releaseFinal():Promise<void>}`，通过仅 loopback 的测试控制服务完成闸门；真实 project 不运行闸门测试（用明确 testMatch 分配，不能 skip 后声称覆盖）。卡片/断线用 contract，业务数据用 real。

- [ ] 按下表新增断言；每例检查 UI 和服务端结果，不能只截图：

| case | 行为 | 必查结果 |
|---|---|---|
| F01 | 明确学校历史查询 | 不额外确认；进度早于终态；同年份/口径与 Evidence |
| F02 | “计算机”歧义 | 选项+自由输入；原 request 回答继续同 Turn |
| F03 | 画像已知/缺失 | 不重复问已知省份；只补必要缺项 |
| F04 | 概率/年度计划/政策 | 上游概率单位；最近发布年；原文条款；无源明确不足 |
| F05 | 双校双专业对比 | 同口径矩阵、缺项、Rank与概率分离 |
| F06 | 完整生成 major/group | 预览前后正式表不变；确认后数量/组内/锁定正确 |
| F07 | 调整与取消 | diff准确；取消不改变正式内容；active Pending 终止 |
| F08 | 确认双击/网络重传 | 同 operationId；无重复写；applied 后读 workspace |
| F09 | 版本冲突 | stale_state；原 Proposal 不能重用；不能自动确认新预览 |
| F10 | 断线/刷新/换会话 | cursor去重、恢复待答卡、不会把旧队列发到新会话 |
| F11 | 日志 epoch 重置 | resync重建基线；不漏新代低序号消息 |
| F12 | 停止/问题超时 | 真 interrupt；卡片关闭；无假 completed |
| F13 | applying时断线 | 不取消已提交事务；查原operation恢复最终结果 |
| F14 | 越权访问 | 无票/错Origin/过期票/跨用户/跨租户拒绝；无数据泄漏 |
| F15 | 上游异常/模型格式坏 | 已有事实不编造；显示可恢复错误；无 JSON/reasoning 泄漏 |
| F16 | 审查与压缩后引用 | 方案内容不变、review版本推进；旧有效Evidence仍可引用 |

- [ ] 命令：`cd zhiyuan-web && npx playwright test --project=contract`；再切真实栈 `npx playwright test --project=real`。同时 `node --test src/utils/conversationEvents.test.mjs src/utils/conversationSession.test.mjs src/utils/conversationSocket.test.mjs`、`npx --no-install tsc --noEmit --incremental false`。build 单独记录，不代替类型/浏览器验证。
- [ ] 指标记录时间戳：用户发送、Gateway接收、第一进度、提问出现、回答送达、最终答案、applied、workspace同步。确定性环境目标：受理回显≤1秒；收到原生事件后 UI 展示≤500ms；工作台读取成功后≤1秒同步。模型/上游延迟单列实测，不用固定 loading 动画伪造性能。

## Task C5：验收报告、发布门禁与回滚演练

**Files:** Create `docs/validation/codex-native-acceptance-report.md`、`scripts/check-codex-acceptance-report.py`；Update 原 `docs/codex-local-stack.md` 与任务 LEDGER（仅实际完成后记录状态）。

**Interfaces:** 报告按 runId 索引机器结果 JSON、脱敏 trace/screenshot、版本和环境；checker 遇 missing/not_run/skipped gate 返回非0。不要用“计划有该用例”作通过证明。

- [ ] 报告至少填写以下字段：

```json
{"runId":"codex-native-acceptance-1","sourceVersions":{"codex":"record-at-run","zhiyuan":"record-at-run"},"layers":{"contract":{"total":16,"passed":0,"failed":0,"notRun":16},"realModel":{"total":48,"passed":0,"businessFailed":0,"environmentFailed":0,"notRun":48},"publicBrowser":{"status":"not_run"}},"criticalViolations":[],"rollback":{"status":"not_run"}}
```

这是空报告模板，绝不可原样当通过。执行器用真实版本/计数覆盖，所有尝试保留，不删除环境失败。

- [ ] checker 校验每层计数和分母、必须场景覆盖、关键错写/跨租户/造数/假 applied 为0；deterministic tests 全过；真实数据 gate 要对应源码接口和外部脱敏结果。输出总体 `ready|not_ready`，同时保留原因。
- [ ] 灰度按能力逐步启用：内部只读→推荐/预览→内部确认写→测试域名受控账户；新开关建议 `conversationProtocolV1`、`nativeClarification`、`domainSources`、`proposalApply`，服务端配置默认关闭新写能力。是否扩大到生产是后续发布决定，本文不视作授权。
- [ ] 回滚演练：关闭 proposalApply，新确认收到明确不可执行结果；已有 applying operation 对账到终态；再将新会话 runtime 改 legacy。验证无自动重发、无 Pending/Artifact 丢失、不删除 Evidence；记录一次实测。
- [ ] 本地收尾只用 `scripts/stop-codex-local.sh` 携带该 run 的真实目录；不按端口 kill 用户原栈。保留隔离数据用于复核，重置动作单独操作。
- [ ] 最终交付必须区分“文档已定稿、代码已实现、fixture已通过、真实上游已通过、真实域名浏览器已通过”；任一没有证据就保留未完成。提交报告与校验器日志后才把对应任务勾选完成。
