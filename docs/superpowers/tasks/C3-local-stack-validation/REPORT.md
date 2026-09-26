---
task: C3（含 C2 的一部分：本地栈启动）
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 08:45 +0800
source: docs/superpowers/plans/2026-09-20-codex-browser-validation.md
---

# 本地栈验证报告：整条链路第一次真的走通

## 一、结论

**四服务栈起来了，整条链路在真实 HTTP + WebSocket 上跑通了**：取票 → 带票握手 →
编号进度事件 → 域内工具真的取到数据 → 终态答案。这是本轮所有服务端工作的
第一次端到端兑现。

**没有用浏览器**：我以浏览器等价的客户端（直连 HTTP + WS，带同样的 tk/pf 与 Origin）
驱动。浏览器那一步仍待 C4 的 Playwright。

## 二、链路实测（逐条原始输出）

```
① 未登录取票             → HTTP 401        ← LoginInterceptor 的新分支
② 无票 / 假票 / 换 Origin 连 WS → HTTP 403   ← 四种情况同一结果
③ 登录取票               → HTTP 200 {"ticket":"T20bkCux…","expiresInSeconds":60}
④ 带票 + Origin 握手      → 成功
⑤ 发消息「帮我看看计算机怎么样」
   [1] v1 {protocolVersion:1, sequence:3, streamEpoch:"92c93f…", type:"tool.progress"}
   [2] v1 {protocolVersion:1, sequence:4, …}
   [3] v1 {protocolVersion:1, sequence:5, …}
   [4] v1 {protocolVersion:1, sequence:6, …}
   [5] 旧信封 type='text' content='「计算机」目前还不能直接当作一个可查询的对象…'
```

`sequence` 从 **3** 开始而不是 1：同一会话上一轮已发过 1、2，
编号按会话连续、跨回合保持——这正是前端去重与 resync 依赖的性质。

rollout 上核对：`binding_resolution_failed` **0 次**（修复前 7 次），
`entity.resolve` 返回 `status=ok`。

## 三、发现并修复的三个问题（都在这条链上）

### 3.1 MCP server 静默打到生产（最要紧）

`INTERNAL_SERVICE_URL` 的默认值是 **`https://zhiyuan.ytell.cn`（生产）**，
而 MCP server 是 **codex 的子进程**，**不自动继承** agent 进程的环境变量。

后果：本地栈的 MCP server 拿不到那个变量 → 落到生产默认值 → 去**生产**解析
线程绑定。失败信息只有 `binding_resolution_failed`，**完全看不出它打到了哪里**。
模型据此如实回答"工具不可用"——那是对的，但没人能从这个信息里查出错在哪。

修法：`build_codex_command` 显式声明 `env_vars=["INTERNAL_SERVICE_URL",
"INTERNAL_SERVICE_TIMEOUT_SECONDS"]`（codex 的 `RawMcpServerConfig.env_vars`
支持按名透传父进程的变量）。有测试钉住。

**附带一条需要裁决的**：那个默认值本身是生产。一个漏配的环境不会报错，
它会安静地读生产数据。要不要把默认改成"必须显式配置、否则拒绝启动"，
是设计侧的决定，我没有擅自改。

### 3.2 `wx.miniapp.configs: []` 让后端起不来

`WxMaConfiguration.wxMaService()` 只判了 `configs == null`，没判空列表，
而 `setMultiConfigs` 对空集合取 `next()` → `NoSuchElementException`。
**任何配了空列表的部署都起不来**，报错信息也看不出缺的是哪个配置。
已改为空列表与 null 同样处理（返回空的 service）。

### 3.3 我自己的两处失误

- 漏了 `internal_client` 的导入 → 拒绝路径走成 HTTP 500 而不是 403。
- 编辑 3.2 时把 `return` 吞掉了，导致修复不生效、白重启一次栈。
  同一个老毛病：改完没看**最内层**的抛出点就以为修好了。

## 四、为跑通链路做的临时动作（C3 要正式化的）

隔离库里**没有任何账号**（0 用户 / 0 会话），所以直接插了最小种子：

```sql
INSERT INTO assistant_user_base (id, tenant_id, bot_id, mobile, user_name) VALUES (900001, 1, 1, …);
INSERT INTO assistant_user_credential (user_id, login_type, login_token, channel, identifier)
  VALUES (900001, 7, 'codex-local-test-token', 'web', …);
INSERT INTO assistant_chat_session (id, tenant_id, user_id, bot_id, …) VALUES (900001, 1, 900001, 1, …);
```

**这是临时动作，不是交付物**：C3 的 `scripts/seed-codex-acceptance.py` 仍要写，
且必须只操作 private-resettable 库、按 runId 标识、凭证另存 0600 文件。

## 五、栈的当前状态

```
Backend 18290 · Agent 18291 · Rank 18292 · Web 3201
Run:   .runtime/codex-local-20260921-082947-27879
启动:  CODEX_LOCAL_SERVER_CONFIG=… CODEX_LOCAL_DATASET=private-resettable \
       CODEX_LOCAL_CODEX_HOME=… CODEX_APP_SERVER_BIN=<真实二进制> \
       CODEX_APP_SERVER_USER_INPUT_MODE=native \
       CODEX_EVENT_STORE_REDIS_URL=redis://127.0.0.1:16379/9
停止:  bash scripts/stop-codex-local.sh <绝对路径>
```

## 六、验收

```
zhiyuan-agent: pytest tests/ -q
# 1 failed, 1852 passed, 56 skipped
# 唯一失败是 test_dialog_quality_gate（台账基线）
# 注：另一条 test_ops_release_smoke 现在独立跑也过——它是**环境相关**的，
#     之前不是真回归，现在也不是被修好的。

zhiyuan-server: mvn -o test
# Tests run: 774, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS

zhiyuan-web: node --test + tsc --noEmit
# 43 passed；tsc 24 条 = 既有基线
```

## 七、未完成

1. **浏览器没跑**（C4）：这次是等价客户端，不是真实浏览器。渲染、键盘可达性、
   断线重连的页面行为都还没验。
2. **测试域名没验**（C2/C3）：`test-wwww.gaotuzhiyuan.com` 的 DNS/TLS/WSS、
   代理、Cookie 全都没碰；当前栈只在 loopback 上。
3. **`PlanningController` facade 与 inner 外露拦截**（C1/C2）没做——前端仍在直连 inner。
4. **seed 脚本没写**（见第四节）。
5. **来源白名单没配测试域名**：现在两端都只允许 `http://127.0.0.1:3201`。
6. **`session.resync` 没验**：编号事件通了，但重连时的快照恢复还没接（A7）。
7. **澄清卡没在这次链路里触发**：开了 native 开关，但那轮模型没提问。

## 八、证据边界

- 客户端是 Python 脚本（websockets），**不是浏览器**：不覆盖 JS、CORS、混合内容、
  Cookie、代理等浏览器侧的真实约束。
- 用的是真实 codex 二进制 + 真实模型（deepseek-flash）+ 真实 Java + 真实 MySQL/Redis。
- 上游（gaotu）**没有真实调用**：域内工具走的是本地 Java 与本地数据。
- 种子数据是手插的，不是 C3 的正规 fixture。


---

## 续作（2026-09-26，实现会话；上一节的 `PARTIAL` 仍在 ✗）

> 评审入口：`docs/superpowers/tasks/2026-09-26-评审入口（C线三份与B6补充）.md` §3 ✓

> 上一轮把"整条链路第一次走通"做完了 ✓；这一轮接着做 **C3 里自足、不依赖浏览器的那部分** ✓。
> **改动未提交** ✗。判定照旧由设计侧给 ✓（实现方不自评 ✓）。

**新增** ✓：

| 产物 | 说明 |
|---|---|
| `scripts/seed-codex-acceptance.py` ✓ | 合成数据的**建/清**（runId 作用域 ✓）：默认 dry-run ✓、`--apply` 才写 ✓、`--expect-instance` 指名 + **端口归属**核对 ✓✓ |
| `zhiyuan-agent/tests/unit/test_seed_codex_acceptance.py` ✓ | **8 passed** ✓：确定性 id ✓、**reset 只覆盖 fixture 记录的 id** ✓✓、缺 `createdRows` 拒绝 ✓、表名/列名只允许标识符 ✓、实例核对三态 ✓、dry-run 不写库 ✓ |
| `docs/validation/codex-native-environment.md` ✓ | 环境基线：四服务端口/版本 ✓、数据面**共用实例**的发现 ✓✓、DNS/TLS 阻塞项 ✓、解释器与浏览器现状 ✓ |
| `docs/validation/codex-native-browser-checklist.md` ✓ | 人工浏览器清单（本地 ✓ / 公开域 ✓ / 收尾 ✓ 三段，每步写明**要记什么** ✓） |

**两条要紧的实测发现** ✓✓：

1. **数据实例是共用的** ✗✓：`zhiyuan-codex-local` 那套 MySQL/Redis（13306/16379 ✓）
   **正被跑着的共享栈用着** ✓（Java 配置指向它 ✓）。所以"reset 只删本次 runId"不是礼貌要求 ✓，
   是**动它就会连共享栈数据一起清掉** ✗✗——脚本因此把删除范围钉死在 fixture 的 `createdRows` ✓，
   并有单测盯着 ✓。
2. **公开域那半在本机不具备条件** ✗：`test-wwww.gaotuzhiyuan.com` **DNS 解析不到** ✗
   （`getent hosts` ✓ 与 `curl --head` ✓ 都失败 ✓）。按任务书要求写成**具体阻塞项** ✓，
   不对公网域下的行为下任何"通过"结论 ✗。

**`--apply` 实测：已完成 ✓✓**（2026-09-26，**用户点名授权**："允许向 13306 的 zhiyuan_codex_local 库写入，
并在验证后删除 c3-live 那批 tenant/session 行" ✓）。原始对账读数 ✓：

| | 写入前基线 | 写后 | 删后 |
|---|---|---|---|
| `assistant_chat_session` | 412 | 416（+4 ✓）| **412** ✓ |
| `assistant_tenant_info` | 0 | 2（+2 ✓）| **0** ✓ |
| `assistant_chat_session_extra_data` | 568 | — | **568** ✓ |
| 最近三个会话 id | 10041936 / 10031936 / 10021936 | — | **完全一致** ✓ |

- seed 建的 6 行都在 runId 推出来的号上 ✓（租户 96270/96271 ✓、会话 9862700/701/710/711 ✓）；
- reset **只删了 fixture 记录的 6 行** ✓；980 万号段里既有的 **24 个回放会话一行未动** ✓✓
  （这正是"reset 只限本次 runId"在真库上的证据 ✓）；
- `credentials.json` 权限 **0600** ✓（fixture 里不含凭证 ✓）；
- **fail-closed 亲测** ✓✓：第一次 reset 忘了给 `--expect-instance`，脚本**拒绝删除** ✓
  （"读不到容器 的端口" ✓）——守卫不是摆设 ✓；
- 顺带踩到两处操作坑 ✓：seed 要 **3.10 且带 `mysql-connector` 的解释器** ✗（agent 的 venv 没有 ✗）；
  命令里用 `| tail` 会**吞掉退出码** ✗（我因此把一次失败当成了成功 ✓）。

**仍未做（阻塞项）** ✗：浏览器里的人工基线（**本机 glibc 2.17 ✗、chromium 要 2.18/2.25 ✗** →
改走**容器** ✓，见环境文档第四节 ✓）；公开域的 DNS/TLS 与"另一台设备"检查（DNS ✗）；
数据端口 `0.0.0.0` 的修复需**栈的主人**重建容器 ✓。
