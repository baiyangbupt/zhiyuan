---
status: DONE_WITH_CONCERNS
task: C2（显式本地/公开模式和反向代理）
source: docs/superpowers/plans/2026-09-20-codex-browser-validation.md（Task C2 段）
date: 2026-09-26
---

# C2 报告：本地/公开测试两套访问面

> 评审入口：`docs/superpowers/tasks/2026-09-26-评审入口（C线三份与B6补充）.md` §2 ✓

> 任务书就是那份 B/C 计划里的 **Task C2** 段 ✓（本目录是为了让它**有个可回收的落点** ✓——
> 它此前既无任务目录也无报告 ✗，B/C 线的任务都没进台账 ✓，这是结构缺口之一 ✓）。
> 实现会话写 ✓；**改动未提交** ✗。

## 一、做了什么（按任务书的复选框）

| 复选框 | 落点 |
|---|---|
| 访问面模式与守卫（local / public-test ✓） | **`scripts/codex-local-access.sh`（新增 ✓）** —— `start` 与 `preflight` **共用一份判据** ✓（两处各写一份早晚会"预检放行、启动拒绝" ✗）|
| `--print-access-env` | `start-codex-local.sh` ✓：纯计算 ✓、在 preflight 与建目录**之前** ✓（错配置不留痕迹 ✓），打印**实际会用的值** ✓ |
| 公开 origin 守卫 | 必须 `https://<host>[:port]` ✓；**带路径 ✗／带凭证 ✗ 一律拒** ✓ |
| outer 守卫 | `public-test` **必须显式给** ✓（不许回落到生产默认 ✗）、**不许指向 origin 自己** ✗ |
| WebSocket base 派生 | **`zhiyuan-web/src/utils/conversationSocket.mjs`（新增 ✓）**：`public-test` **忽略一切显式 base** ✓（含历史遗留的 `NEXT_PUBLIC_AGENT_WS_BASE` ✗）→ 按 `window.location` 同源派生 ✓ |
| 真实拼 URL 的调用点 | `MessageList/index.tsx:498-508` ✓——原先那句 `override \|\| WS_BASE \|\| ''` 正是漏点 ✗（旧变量非空就会盖过同源 ✗）；现走统一判据 ✓ |
| 模式下发到 Web | 脚本传 `NEXT_PUBLIC_CODEX_ACCESS_MODE` ✓（浏览器要知道自己在公开模式 ✓）|
| Agent Origin 白名单 | 脚本传 `CODEX_WS_ALLOWED_ORIGINS` ✓：`local`＝回环 ✓；`public-test`＝**公开 origin + 回环** ✓ |
| Nginx 位置块 | **`ops/nginx/codex-test.locations.conf`（新增 ✓）**：`map`/`log_format` 标注属 http 层 ✓、其余放现有 HTTPS server 内 ✓；`/inner/`、`/internal/`、`/admin/`、`/debug/` 一律 404 ✓ |
| Next rewrite 兜底穿透 | **`next.config.mjs`** ✓：`/gaotu-assistant-bot/:path*` 那条通用规则会把 `/inner/...` 透到后端 ✗；新增 `INTERNAL_PATH_GUARDS` ✓ 并**前置**（rewrite 按顺序匹配 ✓），dev 与 test 两分支都挂 ✓ |
| 回环绑定 | `start-codex-local.sh` 的 Java 加 `--server.address=127.0.0.1` ✓；`docker-compose.codex-local.yml` 两个数据端口改 `127.0.0.1:` ✓（Agent/Rank/Web 本来就是回环 ✓）|
| 公开域冒烟 | **`scripts/smoke-codex-public.sh`（新增 ✓）**：`--origin` + `--base-path` ✓；页面 ✓、静态资源 ✓、内网路径**必须 404** ✓、带票据的升级 **101** ✓；**无票据只跑匿名检查并如实写 `authenticated=not_run`** ✓ |
| 文档 | `docs/codex-local-stack.md` 补「访问面」一节 ✓ |

## 二、验证（原始读数）

**红-绿** ✓：
- Python 侧先红 ✓：`unknown option: --print-access-env` ✓（脚本原本硬设 loopback 与生产 outer ✓，正如任务书所述 ✓）。
- Node 侧先红 ✓：模块不存在 ✓。

**绿** ✓：
- `zhiyuan-agent/tests/unit/test_codex_local_stack_scripts.py` **13 passed** ✓
  （新增 6 条：4 条模式/守卫 ✓ + 1 条**接线回归** ✓——盯"解析出的值真的被用上 ✓、两处硬设已消失 ✗" ✓ + 1 条冒烟脚本守卫 ✓）。
- `zhiyuan-web/src/utils/*.test.mjs` **48 passed / 0 failed** ✓
  （新增 `conversationSocket.test.mjs` 5 条 ✓，含任务书那条验收原文："旧 `WS_BASE` 非空、override 为空、public-test → 仍得当前域名 wss" ✓；
   `codexLocalRewrite.test.mjs` 新增 1 条 ✓ 盯内网守卫**排在第一** ✓）。
- `bash -n` 三个脚本 ✓；冒烟脚本的四条守卫**当场手跑**过 ✓（缺 origin ✓／非 https ✓／带路径 ✓／未知选项 ✓）。
- **agent 全量 1983 passed / 59 skipped / 1 failed（旧账 `test_dialog_quality_gate` ✓）** ✓。

**模式实读** ✓（`--print-access-env` ✓）：

```text
CODEX_LOCAL_ACCESS_MODE=public-test
NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=""
NEXT_PUBLIC_OUTER_API_BASE_URL=https://test-api.example
NEXT_PUBLIC_CODEX_ACCESS_MODE=public-test
CODEX_WS_ALLOWED_ORIGINS=https://test-wwww.gaotuzhiyuan.com,http://127.0.0.1:3201,http://localhost:3201
```

## 三、自标未验 ✗（concerns）

1. **Nginx 配置没有部署** ✗：本机不是那台反向代理主机 ✓，只做了 `nginx -t` 无法执行的静态落地 ✓——
   部署前必须在真实代理上 `nginx -t` ✓（任务书自己也是这么要求的 ✓）。
2. **公开域冒烟没有对着真 origin 跑** ✗：需要 `test-wwww.gaotuzhiyuan.com` 可达 + 一次性票据 ✓；
   本次只验证了**守卫与匿名检查的形状** ✓，`authenticated` 分支从未真实执行 ✓。
3. **回环绑定未在隔离栈上实测** ✗：改的是隔离栈的启动脚本与 compose ✓，
   本次没有起隔离栈 ✓（跑着的共享栈 18090/18091 不受影响 ✓，但它不是这一项的对象 ✓）。
4. ~~前端没有 typecheck 验证~~ **已补** ✓✓（2026-09-26，C4 那边跑的 ✓）：
   `npx --no-install tsc --noEmit --incremental false` → 退出码 2 ✓、**错误 24 个全是既有**
   ✓✓（`userCenter` 18 ✓／`subjectScores` 4 ✓／`service/*` 2 ✓），
   **本任务的改动一个都不在榜上** ✓（`MessageList/index.tsx` ✓、`conversationSocket.mjs` ✓、
   `playwright.config.ts` ✓）。**24 是基线** ✓，读数留在
   `docs/superpowers/tasks/C4-browser-matrix/REPORT.md` §三 ✓。
5. **`.mjs` 的工具函数被 TSX 导入** ✓ 已是仓库既有做法 ✓，但 `socketBase` 的第三个参数（模式）
   在类型上是宽松的 ✓——若日后要更严，可给 `.d.ts` ✓（未做 ✗）。
