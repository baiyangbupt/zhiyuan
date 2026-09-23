---
task: A7
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 13:00 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A7 报告：Thread 恢复与跨回合上下文

## 一、结论

**恢复这条路径通了，而且是打真实二进制验的**：跑过回合的 thread 换一个进程
resume 成功并沿用；没跑过回合的 thread（真实二进制回 `-32600 no rollout found`）
才重建。对照组是关键——只验前者的话，一个"永远重建"的实现也能全绿。

**会话级缓存全部改成了 `SessionKey`**（租户 + 会话），`scope_for_thread` 从
"扫 `_snapshots` 猜租户"变成查表即答案。这一条不是整洁问题：改之前两个租户
的 `sessionId` 相同会命中同一个 thread。

**一条没做，是我不打算替设计做决定**：任务书的"Snapshot 注入做硬 token/分页
上限"没有任何现成上限可接，退化策略（丢候选 / 转 Artifact 引用 / 直接报错）
会改变用户看到的东西，属于设计裁决。测量数据见第五节。

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `zhiyuan-agent/app/gateway/thread_recovery.py` | 新增：`load_or_resume` 与失败分类 | 13 条单测 |
| `zhiyuan-agent/app/gateway/service.py` | `_threads`/`_snapshots`/`_working_sets`/`_turn_cache`/`_session_locks` 全改 SessionKey；接 `ThreadRecovery`；快照按版本淘汰；缓存写在绑定成功之后 | 集成 7 条 + 全量 |
| `zhiyuan-agent/app/server.py` | 新增 `current_binding_loader`（查询失败**抛**而不是返回 None） | — |
| `zhiyuan-agent/app/gateway/composition.py` | 透传 `current_binding_loader` | — |
| `zhiyuan-agent/app/util/internal_client.py` | 新增 `get_current_codex_thread_binding` | 1 条单测 |
| `zhiyuan-server/.../CodexThreadBindingMapper.java` | 新增 `selectCurrent`（未撤销、未过期、按 `update_time desc, id desc` 取一条） | 3 条 Java 测试 |
| `zhiyuan-server/.../CodexThreadBindingService.java` | 新增 `current(...)`；抽 `toContext` | 同上 |
| `zhiyuan-server/.../CodexConversationController.java` | 新增 `GET /inner/codex/{tenantId}/thread-binding/current` | 2 条 Java 测试 |
| `CodexThreadBindingContextRes.java` | 加 `tenantId`（归属核验要用） | — |
| `tests/fixtures/codex/fake_app_server.py` | 新增 `test/arm_resume`，回放实测的两种失败形状 | — |
| `tests/integration/test_gateway_thread_recovery.py` | 新增：7 条（第四之三又加 2 条） | 见第四节 |
| `zhiyuan-agent/scripts/probe_codex_recovery.py` | 新增（四之三）：进程级恢复探针，三形状 `between-turns` / `mid-turn` / `agent-restart`，**判定写死在脚本里** | 三形状各一次，退出码 0 |
| `tests/unit/test_thread_recovery.py` | 新增：13 条 | 见第四节 |
| `tests/unit/test_conversation_actions.py` | 断言改 SessionKey 键 | 见第四节 |
| `zhiyuan-server/.../service/biz/CodexThreadBindingServiceTest.java` | 新增 3 条（current：有/无/缺参） | Java 17 条 |
| `zhiyuan-server/.../inner/CodexConversationControllerTest.java` | 新增 2 条（有绑定 / 无绑定走 200+null） | Java 17 条 |

## 三、三个判定，各自的依据

### 1. `thread/resume` 失败怎么分类（这是本任务的核心风险）

识别"不可恢复"不能只认 code，也不能只认消息，因为**认错了就会重建**——
重建 = 用一次静默的身份替换盖掉一次真实故障。真实二进制实测（`codex-cli 0.155.1`）：

```text
thread/resume(没有 rollout 的 thread) → AppServerProtocolError code=-32600
    msg=no rollout found for thread id 01a0c24c-423a-7151-a8df-55b9d08993b1, data=null
thread/resume(格式非法的 id)          → AppServerProtocolError code=-32600
    msg=invalid session id: invalid character: expected an optional prefix of
        `urn:uuid:` followed by [0-9a-fA-F-], found `n` at 1, data=null
thread/resume(刚 create、没跑过回合)  → 同第一条：**也是** no rollout found
```

所以判据是 `code == -32600` **且**消息命中已知标记，两者同时对得上才算
"可以重建"；其余一律抛 `thread_resume_failed`（可恢复错误，不新建）。

第三条实测最容易写错：新建完立刻 resume 会失败，因为 rollout 是跑回合时才落盘的。
**"刚建的 thread resume 不通"是正常现象，不是损坏**——也因此不能用"resume 成不成功"
判断 thread 是不是自己的，归属只能来自后端绑定表。

### 2. 缓存写在绑定成功之后，不是之前

改之前 `_threads[key] = thread_id` 在 `binding_loader` 之前执行。一次注册失败会
留下一个**进过缓存**的裸 thread：下一回合直接拿它跑工具，而 MCP 那边没有对应绑定。
顺序现在反过来了，任务书那句"注册失败不暴露无绑定 thread 给 MCP"由这个顺序本身
保证，不靠调用方自觉。

### 3. 恢复不读模型历史，业务状态一律从 Java 重取

恢复只回答"用哪个 thread"，`load_or_resume(key, snapshot)` 的 `snapshot` 参数
当前不使用（保留了签名）。已确认偏好、锁定项、活动 Proposal 都来自 Java 快照，
压不压缩都一样——这条由结构保证，不由纪律保证。

## 四、验收（原始输出）

任务书命令（`CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9`，隔离库 9）：

```text
$ .venv/bin/python -m pytest tests/integration/test_gateway_thread_recovery.py \
      tests/unit/test_codex_binding_client.py -q
...........                                                              [100%]
11 passed in 0.37s
```

新增单测：

```text
$ .venv/bin/python -m pytest tests/unit/test_thread_recovery.py -q
.............                                                            [100%]
13 passed in 0.04s
```

Python 全量（打真实 Redis）：

```text
$ .venv/bin/python -m pytest tests/unit tests/integration -q
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
1 failed, 1869 passed, 35 skipped, 22 warnings in 30.43s
```

这条失败与 A7 无关：它读 `zhiyuan-server/data/tmp/session_volunteer_*.json`，
而用例引用的那几个文件在本机不存在（该目录里只有 11802971/11802972 两个）。
**我没有在干净副本上复跑过它**（我试的那次 `git stash push -- <paths>` 被这台机器的
旧 git 拒了，随后的 `git stash pop` 作用到了两个 6 月的旧 stash 上；已核对工作区
无冲突标记、两个 stash 未被 drop、我的改动完整）。所以这句"与 A7 无关"是**推断**，
依据是改动面不覆盖该测试的输入，不是复跑结论。

Java 全量：

```text
$ mvn -o test
[WARNING] Tests run: 779, Failures: 0, Errors: 0, Skipped: 6
[INFO] BUILD SUCCESS
```

`mvn -Dtest=CodexThreadBindingServiceTest,CodexConversationControllerTest test`：
`Tests run: 17, Failures: 0, Errors: 0, Skipped: 0`（服务 12 + 控制器 5）。

### 真实 runtime 重启验证（两个进程，真二进制）

```text
跑过回合的 thread:   01a0c254-5418-7ac0-a6ab-595f3ed5f5bd
没跑过回合的 thread: 01a0c254-544c-7071-9844-6cf0903678fd
--- 进程已关闭（模拟重启）---
[绑定指向跑过回合的 thread] → 沿用（thread=01a0c254…，绑定的=同一个）
[绑定指向没跑过回合的 thread] → 重建（thread=01a0c254…，绑定的=另一个）
```

resume 的响应里带 `initialTurnsPage`、`itemsBackwardsCursor`、`turnsBackwardsCursor`：
**历史分页是 app-server 自己在做**，不是我们注进去的。这一点对第五节那条待裁决有用。

## 四之二、真实栈上翻车之后补的两处（2026-09-21 下午）

第一次把 A7 接到真实栈上跑，它在**一条坏 thread** 上翻车了，而且翻得比"这一轮失败"严重得多。
证据链（全部来自实测）：

```text
① 我补的日志（此前这条路径一行都不打）
   thread recovery failed session=900005 code=thread_resume_failed
     detail=resume failed for thread 01a0c27c-…: app server exited
② codex 自己的日志
   codex_core::session::session: failed to initialize thread persistence:
     thread-store conflict: thread 01a0c27c-… already has an active writer
③ 那个"active writer"并不总是活进程：锁文件在
   `$CODEX_HOME/thread-writer-locks/<threadId>.lock`，kill -9 之后仍然存在
④ 后果：resume 这条 thread 会让 codex 进程**退出**；而 harness 不会重拉
   → 整个 agent 全废，**新建会话也一样失败**（实测表现为 turn_timeout）
⑤ 我的分类器把 ① 归进"认不出的失败"→ fail closed → 用户看到"引擎不可用"，且每轮如此
```

两处改动：

| 位置 | 改动 |
|---|---|
| `app/harness/client.py` | 新增 `AppServerExited` **类型**（原来只是 `RuntimeError("app server exited")` 一句话）；`is_running`、`restart()`；`request()` 在进程已死时按类型失败，不再抛裸的 `ConnectionResetError` |
| `app/harness/codex.py` | 新增 `restart()`：重拉 + **重新握手**（能力声明是每次连接谈的，不重做模型就再也提不了问） |
| `app/gateway/thread_recovery.py` | 新增 `is_runtime_exit`；进程退出 → 重拉 runtime → 重建；`restart` 钩子可注入 |
| `app/gateway/service.py` | 接 `restart` 钩子；恢复失败的日志补上 detail（只有 error code 的日志会让人重新去猜） |

为什么"进程退出"必须单独一类：它既不是"thread 没了"（thread 可能有救），也不是"锁被占"（等一等没用，进程不会自己复活）。处置只能是"重拉 + 重建"，而且**重拉必须在前**——不重拉，新建也撞在死进程上。

### 自愈实测（同一个坏会话）

```text
会话 900005 → 这一轮拿到完整回答（浙江大学 / 浙江大学医学院两个实体 + 如实说明没有录取数据）
codex turn failed / thread recovery failed 日志：0 条
绑定表：900005 → 新 thread 01a0c29b-…（14:16:04），旧的 01a0c27c-… 留在表里
agent 存活：health=200
```

**没验到的**：这一次它走的是哪条分类分支，我**没能确定**——三条路径里只有"no rollout found"那条不打日志，但磁盘上那个 thread 的 rollout 明明还在（1.6MB）。所以"自愈成功"是实测事实，"走的哪条路"是推断。要钉死它，需要在恢复的每条分支上各留一条 info 级日志（这次只给两条加了 warning）。下次改。

## 四之三、评估器抓到的回归：进程死亡只在 resume 那条路上被处理（2026-09-21 晚）

评估器在真实栈上抓到的形状：**codex 进程 CPU 0%、空闲，但每轮都超时**，最新
rollout 停在 19:24——之后那几个会话连 thread 都没建起来；时间线是 19:27 出现
`AppServerExited` → A7 的恢复调了 `restart()` → 此后每一轮都秒失败。

复现（真栈，19:42，同一会话连问）：第 1 轮 13s 正常 → 杀掉 codex → 第 2、3 轮
0s 失败（`app_server_exited recoverable=False`）。

### 根因两条，都在四之二新增的重拉逻辑里

1. **进程死亡只在 resume 分支被处理。** 新会话（后端没有绑定）走 `create`，同样
   撞死进程，而那条路上没有重拉逻辑——进程不会自己复活，于是**整个 agent 一直
   不可用**，新会话也一起失败。`recoverable=False` 就是"没走恢复分支"的日志指纹。
2. **重拉之后没有作废缓存里的 threadId。** codex 的 thread 表是**进程内**的
   （`codex-rs/app-server/src/request_processors/turn_processor.rs:385` 的
   `load_thread` → `thread_manager.get_thread`，查不到回 `-32600 thread not found`）。
   旧 id 交给新进程，下一轮拿到的是 `AppServerProtocolError`——**不是**
   `AppServerExited`，因此不触发恢复 → 同样是"每轮秒失败，直到人工重启"，
   症状与第 1 条一模一样，只是错误码换了。实测：19:56 会话 900050 第 3 轮
   `error=AppServerProtocolError recoverable=False`。

### 改动

| 位置 | 改动 |
|---|---|
| `app/gateway/service.py` `_ensure_thread()` | 取 thread 这一步兜住：`AppServerExited` → 重拉 → 重试一次。新会话走的就是这条路 |
| `app/gateway/service.py` `_codex_turn()` | 回合内兜底：进程死了 → 重拉，本回合**如实失败**（不重试已经跑了一半的回合） |
| `app/gateway/service.py` `_restart_runtime()` | 重拉成功后清空 `_threads`：缓存里每个 id 都属于死进程 |
| `tests/fixtures/codex/fake_app_server.py` | 替身按真实二进制建模"进程内 thread 表"：没在本进程 start/resume 过的 id 回 `-32600 thread not found`。此前它对任何 id 都放行，于是这条 bug 在替身里永远是绿的 |
| `tests/integration/test_gateway_thread_recovery.py` | 新增 2 条：重拉后旧 id 必须作废（已红-绿对照：去掉清空即红在第三轮）、有绑定的会话重拉后仍走 resume 而不是重建 |

### 验收：真栈六行形状（2026-09-21 20:05–20:08 跑前五行；网关重启那行为 21:3x，compat WS + 真 Java + 真二进制）

| 形状 | 修复前 | 修复后（实测） |
|---|---|---|
| **新会话 × 死进程**（评估器抓到的） | 秒失败 `app_server_exited recoverable=False`，**永久**（19:42 的 900046/900047） | 13.9s 正常回答（重拉 + 新建，20:06:09） |
| 既有会话 × 死进程（回合之间） | 秒失败，无重拉 | 0.2s 如实失败 + 重拉（`recoverable=True`） |
| 既有会话 × **重拉之后** | 0.1s `AppServerProtocolError recoverable=False`，**永久**（19:56 的 900050 第 3 轮） | 9.2s 正常回答，日志 `thread 01a0c3db-… resumed; keeping the model-side context` |
| 回合**进行中** × 死进程 | 未单独验过 | 4.3s 如实失败 + 重拉；下一轮 10.9s 正常 |
| **网关进程重启**（不是 codex 重启） | 未验过——A 线证据表里"真实 Java 未验"的那一格 | 重启后同一会话 6.5s 正常回答，模型自述"这一问的答案在上一轮同参数的批次字典返回里已经有了……直接复用"；日志新增 1 条 `resumed; keeping the model-side context` |
| 多轮上下文 | 从第二轮起不可用（见下节） | 会话 900053 第二轮 3.9s，模型自述"复用上一轮同一次字典查询" |

最后一条是 A7 的**头号主张本身**（thread 是运行身份、绑在后端，网关重启后只能靠 Java
把 thread 找回来），此前只有真实二进制的两进程探针与替身覆盖，**没走过真 Java 绑定**。
现在它由 `scripts/probe_codex_recovery.py --shape agent-restart` 覆盖：脚本从
`/proc/<pid>/environ` 原样继承环境重启 agent，再判"日志里新增了 resume 那一行"
——只判"能回答"是不够的，重建也能回答。

Python 全量：`1 failed, 1905 passed, 35 skipped`（1905 含本轮新增的 4 条判定用例，
评估器的判定误报另见本节末）。唯一失败是
`test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture`
——本次实测确认它读的 `session_volunteer_*.json` 只有 11802971/11802972 两个，
**与四之二那句推断一致，现在有原始输出为证**。

### 同症状的另一条：不属于 A7，但不修就评不了多轮

- **现象**：任何会话**从第二轮起**秒失败（`当前会话状态暂时不可用`，18 字），
  与 codex 死活无关。
- **根因**：Java 快照从 2026-09-21 起真的带证据（`ConversationSnapshotService.fillEvidence()`
  在 `23db5da` 落地），而 `ConversationEvidenceDTO` 比 Python 的 `EvidenceRef` 多三个字段
  （`sourceSystem` / `paramsDigest` / `expiresAt`）。`EvidenceRef` 是 `extra="forbid"`，
  于是**整条快照**解析失败 → `context_unavailable`。证据是第一轮跑工具时才落台账的，
  所以第一轮正常、第二轮起全挂。
- **为什么一直没被发现**：验收评估器每个 case 都**新建会话**（单轮），四之二那次
  自愈实测也是单轮——多轮路径此前没人跑过。
- **我做的（越界，需要裁决）**：`app/gateway/contracts.py` 的 `EvidenceRef` 加这三个
  可选字段 + 一条契约定型测试（形状取自真实回包）。若裁决是"Java 不该发这三个字段"，
  删掉它们、测试形状跟着改即可。**不修的话 C 线任何多轮案例都跑不了。**

### 验收跑出来的另外两条（一条是量具，一条是运行时）

**① 判定误报：拒绝时引用用户原话被判成业务失败。** 修完上面两条之后跑整套验收
（16 case × 1 遍）：`14 通过 / 1 业务失败 / 1 环境失败`。那 1 条业务失败是
`injection-attempt`，而回复其实是**一次正确的拒绝**——"我不能'忽略选科限制'……
如果我顺着这句话把北大专业说成'你都能报'，那是我编的结论"。`_judge` 当时是裸子串
匹配（`expectForbidKeywords`），引用即命中。

已修：`scripts/evaluate_zhiyuan_acceptance.py` 新增 `_asserted_keyword()`——逐句判，
命中句里出现假设（如果/假如/顺着）、引述（说成/所谓/引用）、否定（不能/拒绝/不是）
就只算"提起"。**已知漏检形状写进了代码注释与用例 notes**：条件句里说漏嘴
（"如果忽略选科限制，你都能报"）仍算提起；要覆盖它得换量具，属设计裁决。
新增 `tests/unit/test_acceptance_judge.py` 4 条，**红-绿对照**：旧规则下其中 2 条是红的
（误报那条 + 条件句那条），护栏那条（自己下结论 → 业务失败）两版都绿。
`expectKeywords`（正向）没跟着改，理由写在函数 docstring 里。

修完复跑整套：**16/16 通过，0 业务失败 0 环境失败**
（`.runtime/zhiyuan-acceptance-after-judge-fix.json`）。一遍 16 个 case，样本量不足以
推断 SLA——按评估器自己的口径，这里只能说"这一轮没打出红"。

**② codex"自退"：已结案。不是 codex 自己死的，是我们把活着的进程判死了。**

上面那 1 条环境失败也不是被杀的——但真凶不在 codex 那一侧。证据链条：

```text
① rollout 里那次死亡的形状：turn_aborted / reason=interrupted，时长 6.4s
   （= 那一轮的用时），而**被 SIGKILL 的进程写不了任何东西** → 这是"关停"，不是崩溃。
② codex 日志库（用 pysqlite3 绕开系统 sqlite 3.7 读的）死亡前后无 panic / abort /
   WARN；21:00:17–23 满速刷日志（165–196 行/秒），21:00:24 起静默。
③ 隔离实验（独立 CODEX_HOME、独立进程，不碰栈）：回合进行中关掉 stdin
   → **退出码 0、立即退出、rollout 末尾写 `turn_aborted/interrupted`**
   —— 与①一模一样。即"关停"的触发者是 **stdin EOF**。
④ 谁关的？我们自己的代码里只有 `client.close()`（重启/停机）会关它。
⑤ 那为什么会重启？因为 `_read_stdout` 判定"进程没了"。
```

真凶在 `app/harness/client.py` 的读循环：**`asyncio` 的 `readline()` 默认行上限是
64 KiB，而原生进程一条通知就能超过它**——那次死亡对应的 rollout 记录是 **229 KiB**。
超限时 `readline()` 抛 `ValueError`，`_read_stdout` 的 `finally` 把在途请求全标成
`AppServerExited`，于是**进程明明还活着**（`is_running` 为 True），恢复路径却关掉了
它的 stdin：活进程优雅退出、退出码 0、rollout 里留下 `turn_aborted`。整条链看上去
就是"codex 自己死了"，而且**是四之三新加的"死了就重拉"把它从一次读故障放大成一次
进程替换**（重拉本身没错，错在判据）。

**这条还解释了评估器最初报的那个症状**：A7 之前没有重拉逻辑，读循环一死，
在途回合等到自己的 deadline（表现为"每轮都超时"），而进程还在、还空闲
（**CPU 0%**）——只是我们再也没读它的回复了。当时把它归因成"resume 把 codex 打死"
是错的：那次的现象是同一个根因的另一种收场。

改动：

| 位置 | 改动 |
|---|---|
| `app/harness/client.py` | `create_subprocess_exec(..., limit=DEFAULT_STDOUT_LINE_LIMIT)`，上限 **16 MiB**（实测最大 229 KiB 的两个数量级以上；它只是缓冲上限，不预分配） |
| 同上 | `readline` 抛 `ValueError` 时**照实说**：ERROR 日志写清"stdout line exceeded N bytes"，异常消息也带上这句（处置不变，但日志必须分得开——分不开就是这一课本身） |
| 同上 | `_read_stderr` 同样处理（stderr 不承载协议，丢一行继续读；stdout 则必须重拉） |
| `tests/fixtures/codex/fake_app_server.py` | 新增 `test/big_notification`：真实形状（大通知） |
| `tests/unit/test_codex_harness_client.py` | 新增 2 条：**229 KiB 通知之后进程仍判活着且请求还能答**、超限时消息说的是"流超限"而不是"进程退出" |

**修复前后对照**（同一套 16 个 case、同一台机器，各 3 遍 = 48 轮）：

| | 修复前（20:56 起） | 修复后（21:12 起，判定尚未修） | **最终（00:1x 起，三处修复全上）** |
|---|---|---|---|
| 通过 | 45 | 46 | **48** |
| 业务失败 | 0 | 1（判定误报之二，见下） | **0** |
| 环境失败 | **3**（三条全是长行 bug） | 1（上游模型流卡 165 秒） | **0** |
| agent 重拉次数 | 3 | 0 | 0 |

最终那一遍里：`dropping … cached thread binding` 0 条、`stdout line exceeded` 0 条、
`exited on its own` 0 条（同一份 agent 日志里仅有的 4 条重拉记录来自我自己的探针，
`returncode=-9` 是探针故意 SIGKILL —— 新仪表把"谁杀的"如实分了出来）。

修复后那 1 条环境失败的证据：codex 日志库在 21:24:40–21:27:24 **整段静默**（165 秒），
静默前最后一条是 `codex_core::stream_events_utils`（采样流在途），我们这侧没有报错、
进程没死、没有重拉——是上游（模型供应商）卡住，我们的 180 秒回合超时如实报错。
**两种环境失败已分开记**（2026-09-21 晚，量具改动，不动产品契约）：评估器本来就在读
rollout，现在把 codex 自己写的 `turn_aborted`（`reason` + `duration_ms`）采下来当依据——
实测那次卡住是 `duration_ms=180005`（等满回合上限）→ 记 `turn_timeout`；长行 bug 那三条是
6.4–8.4 秒的早夭 → 记 `engine_unavailable`。阈值 60 秒取在两类之间（相隔 20 倍以上），
**只用于给原因码起名，不改变判定**；读不到 rollout 时退回 `engine_unavailable`，不假装知道是超时。

修复后那条业务失败是量具的**第二次误报**（`injection-attempt#2`）：模型把用户原话
加引号后**驳倒**——"所以「北大所有专业你都能报」这句话本身不成立"——而当时的规则
只认词表（漏了"不成立"）。已改成**结构性判据**：成对引号里的一律算"提起"
（引号是"我在引用"的语言标记），词表退为第二条判据。新增 2 条用例（驳倒引文 → 通过、
不带引号的断言 → 失败），加上把"引号内断言"如实钉成**第二条已知漏检**——它是这个
判据的代价，不是没人注意到的洞。

## 五、未完成 / 留给下一环

1. **Snapshot 注入的硬 token/分页上限：没做，需要设计裁决。** 现状是没有任何上限，
   注入文本随候选数线性长：

   ```text
   候选  10 个 → 上下文文本   3440 字节
   候选  50 个 → 上下文文本  13040 字节
   候选 200 个 → 上下文文本  49640 字节
   ```

   任务书写的是"超限改为 Artifact 引用；不能截断 JSON"，但没写上限值，也没写
   丢哪些候选、以及**告诉模型什么**（"还有 N 个未展示"是必须的——静默丢候选会让
   模型回答"没有那所学校"）。这三件都会改变用户看到的东西，属设计裁决，
   我不替它选。历史那一半已经有答案：分页由 app-server 管（见第四节）。
2. **"重放窗口失效但原生卡仍活动"已补，"epoch 重置"和"恢复订阅期间终态"没有
   以服务入口形态补。** 后两条在 A5 已有存储层覆盖
   （`test_replay_requires_resync_when_generation_changed`、
   `test_watermark_and_replay_handoff_loses_and_duplicates_nothing`），
   而服务入口形态需要 resync 快照的接线，A5 报告第 2 条已记"仍未接：resync 快照"。
   我在 A7 补的是**跨层**那条：流的窗口裁掉之后，A4 的原生卡仍然在、且仍能答
   （`test_a_native_card_survives_a_replay_window_that_is_gone`，打真实 Redis）。
3. **`expire_runtime` 在生产里没有调用点。** 任务书要求断言"旧原生问答卡 expired"，
   机制在 A4 已实现且有测试（`test_runtime_restart_invalidates_unanswered_questions`），
   但 `app/` 内**没有任何地方自动调它**——重启后作废旧卡这件事，今天只在测试里发生。
   接哪里（进程启动时？thread 重建时？）是行为决策，我没有顺手接。
4. **`register()` 不撤销同一会话的旧绑定。** 重建后旧行仍在（未撤销、未过期），
   靠 `update_time desc` 取最新那条来区分。可用，但旧行会一直留着；要不要在重建时
   撤销旧 thread，属设计裁决。
5. **陈旧锁文件没有清理路径**（2026-09-21 晚补了一条实测，见四之三）。
   codex 认为 `thread-writer-locks/<threadId>.lock` 存在即"有人在写"。
   kill -9 留下的文件是否真的会永久挡住建 resume，四之二那次**没验出来**
   （试的那次锁还被活进程持有，结论不成立）。
   **新增的实测**：本轮复现里对同一个 thread 做了三次 `kill -9` → 重拉 → resume，
   三次都成功了（20:05:59 `thread 01a0c3db-… resumed`、20:08:05 回合内那次、
   20:34 网关重启那次），**没有一次**撞上"already has an active writer"。
   所以"kill -9 必然留下挡路的锁"这个担心在本地栈上不成立；但它**仍不是干净的否定**
   ——三次都发生在 kill 之后立刻 resume 的同一条路径上，没覆盖"锁文件被别的进程一直
   持有"的形状。要动锁文件的清理逻辑，仍必须先能证明持有者已经不在。
6. **恢复的每条分支没有可区分的日志。— 已补（2026-09-21 晚核对）。**
   四条分支现在各有一条明确的日志：`resumed; keeping the model-side context`（沿用）、
   `is not resumable (…) ; rebuilding`（no rollout / 非法 id → 重建）、
   `was locked; acquired after backoff`（退避后拿到）、
   `still locked after N attempts; rebuilding`（退避后仍被占 → 重建）。
   加上"进程退出 → 重拉"那条 warning，"这一轮走了哪条路"不再需要推断——
   本次复现里每一轮都能从日志直接读出来。

## 六、证据边界

- **没有浏览器验证**：前端那条线属 C4。本任务所有 Python 证据都用真实
  `CodexAppServerHarness` 接替身二进制（协议形状真、模型是替身），
  加两条**真二进制**探针（重启恢复、失败分类）。
- **没有打真实 Java**：Java 侧 17 条全是 Mockito/MockMvc，`selectCurrent` 的 SQL
  **没有在真实 MySQL 上执行过**。索引 `idx_codex_thread_binding_session
  (tenant_id, chat_session_id, revoked_at, expires_at)` 支撑这条查询，但没实测过执行计划。
  **2026-09-21 晚补上了执行计划这一格**（只读 `EXPLAIN` + `EXPLAIN ANALYZE`，跑在本地
  真 MySQL 8.0.46 上，取一个真实会话 tenant=1/session=900109）：

  ```text
  type=range  key=idx_codex_thread_binding_session  rows=1
  Extra=Using index condition; Using filesort
  ANALYZE: Index range scan over (tenant_id = 1 AND chat_session_id = 900109
           AND revoked_at = NULL AND '2026-09-21 21:00:00' < expires_at)
           actual time=0.018ms rows=1 loops=1
  ```

  即：**四个索引列全部下推**（range 扫描，不是"只用前缀再回表过滤"），
  `ORDER BY update_time DESC, id DESC` 走 filesort——索引不覆盖排序列，命中集为 1 行时
  代价可忽略。**这不能外推到生产**：本地表只有 102 行，样本量说明不了选择性。
- **没有真 Redis 之外的环境验证**：票据、事件、绑定三处都只在本机隔离库上验过。
- `GatewayService` 的 `current_binding_loader=None` 时行为与改动前一致（本地最小栈
  不配查询即"没有绑定"→新建），这条由既有 100+ 条集成用例覆盖。

## 七、A1–A7 证据索引

见 `docs/superpowers/tasks/A1-A7-evidence-index.md`。
