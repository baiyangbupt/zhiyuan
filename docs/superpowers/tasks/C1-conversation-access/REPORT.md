---
task: C1
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 11:30 +0800
source: docs/superpowers/plans/2026-09-20-codex-browser-validation.md
---

# C1 报告（部分）：登录、会话 ownership 与 WebSocket 票据

## 一、结论

**票据链路端到端接通了**：浏览器取票 → WS 带票连接 → Gateway 在 **accept 之前**
换成身份 → 校验来源。两侧全绿（Java 774 / Python 1846）。

**并且我把"半数会破坏功能"的那一半也做了**：guard 是**强制**的，如果只做服务端、
不做前端取票，浏览器会连不上——那是把安全做完、把功能做坏。前端取票与 hook 的
"每次连接重新取票"已一并接上。

## 二、交付

| 路径 | 变更 |
|---|---|
| `manager/cache/ConversationWsTicketStore.java` | 新增：哈希存储 + Lua 原子消费 + 来源绑定 |
| `model/dto/conversation/TicketIdentity.java`、`WsTicketReq/Res/ConsumeRes` | 新增 |
| `service/biz/ConversationAccessService.java` | 新增：`requireOwnedSession` / 签发 / 消费 |
| `web/controller/ConversationAccessController.java` | 新增：`POST /chat/{tenantId}/conversation/ws-ticket` |
| `web/controller/inner/ConversationAccessInnerController.java` | 新增：`POST /inner/conversation/ws-ticket/consume` |
| `common/exception/ConversationAccessException.java` | 新增 |
| `common/config/GlobalExceptionHandler.java` | 新增 401/403 映射（**旧语义不变**） |
| `web/interceptor/LoginInterceptor.java` | 新路径返回真实 401，旧路径仍 800 |
| `test/.../ConversationWsTicketStoreTest.java` | 新增，8 条 |
| `test/.../ConversationAccessServiceTest.java` | 新增，9 条 |
| `app/gateway/access.py` | 新增：`ConversationAccessGuard` |
| `tests/integration/test_gateway_access.py` | 新增，7 条 |
| `app/util/internal_client.py` | 新增 `consume_ws_ticket` |
| `app/server.py` | 两条 WS 路由在 accept 前校验；compat 路由核对路径 tenant/bot |
| `zhiyuan-web/src/service/apis/conversationAccess.ts`、`interface/api/conversationAccess.ts` | 新增 |
| `zhiyuan-web/src/hooks/useWebSocket.tsx`、`websocket.ts` | 新增 `authenticate`：**每次连接尝试取新票** |
| `zhiyuan-web/.../MessageList/index.tsx` | 接上取票 |

## 三、四条写进代码的边界

1. **只存哈希。** Redis 里的键是 `conv:ws-ticket:` + SHA-256(ticket)。
   库被读到也不能拿去连。
2. **原子消费。** GET + DEL 走一段 Lua。拆成两次会出现"两个连接同时读到同一张票"的窗口。
3. **来源绑定，不做通配。** 票只在签发时认定的来源可用。
4. **三种失败同一个回包**（不存在/已用/过期）：区分开来等于告诉对方"这张票存在过"。

另有一条容易做错的：**来源不在白名单时连票都不消费**。消费掉的话，一次攻击尝试
就能把用户的票作废——那是一个可被利用的拒绝服务。有测试钉这一条。

## 四、前端那半：为什么必须"每次连接都取票"

票据是一次性且 60 秒有效的。如果在挂载时取一次、之后复用，**重连必然失败**——
而那种失败表现为"连不上"，看起来像网络问题，很难查到票据头上。

所以 `useWebSocket` 新增的 `authenticate` 是在**每次 `new WebSocket(url)` 之前**
调用；取不到票就**不连**（连上去也会被拒，还会白白消耗一次重连计数）。

## 五、一处必须一起改的兼容问题

既有异常处理器把 `BusinessException` 映射成 **HTTP 200 + body.code**。
新路径需要**真实的 401/403**（浏览器与代理按传输层状态决定要不要重新登录），
所以新增了 `ConversationAccessException` 与它的映射，**没有动旧语义**——
那是全站兼容问题，不能顺手改。

`LoginInterceptor` 同理：只在路径含 `/conversation/` 时抛 401，其余仍是 800。

## 六、验收

```
zhiyuan-server: mvn -o test
# Tests run: 774, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS

zhiyuan-agent: pytest tests/ -q
# 2 failed, 1846 passed, 56 skipped（两条与台账基线逐字同名）

zhiyuan-web: node --test（四个文件）+ tsc --noEmit
# 45 passed；tsc 错误 24 条 = 既有基线，本任务文件零错误
```

## 七、未完成

1. **`PlanningController` 公开 facade 没建**：计划要求把 `sessionDetail.ts` 里
   全部 `/inner/planning/{tenant}/session/...` 调用逐个迁到带 ownership 的公开路径。
   现在前端仍在直连 inner（这也是 C2 要"阻止 inner 外露"的直接原因）。
2. **`ChatController` 的 ownership 补全没做**：session/detail、message/page、
   反馈/导出/画像这些入口仍是 `getById` 级别的检查，没有按 owner 校验。
3. **既有 WS 测试装了放行替身**：这是必要的（否则它们连不上），但意味着
   **"生产路径无条件校验"这条只由 C1 自己的 7 条 + 9 条覆盖**，没有一条
   从真实 WS 路由进去验证"没票就被拒"。要补的话需要一个不装替身的用例。
4. **来源白名单还没配到测试域名**：Java 默认 `http://127.0.0.1:3201`，
   Python 侧用 `CODEX_WS_ALLOWED_ORIGINS`。公网测试域名要显式加进去（属 C2/C3）。
5. **真实 Redis 没跑过**：票据存储的测试全是 mock，Lua 脚本**没有在真实 Redis 上执行过**。
6. `WebConfig` 确认过 `loginInterceptor` 注册在 `/**` 上，新端点已被覆盖——这一条是核过的，
   但没有端到端的 HTTP 用例证明"未登录取票返回 401"。

## 八、证据边界

- Java 侧全部是 Mockito；**没有一条打到真实 Redis 或真实 HTTP**。
- Python 侧的 guard 测试用替身 `consume`，没有真实调 Java。
- 前端只有 tsc 与既有 node 测试；**取票与重连取票的实际行为没有浏览器验证**。
