# C4 契约套件转绿：红灯追因 + resync 接线 + F02 卡片 + 用例隔离 — 2026-09-26

> 本轮把 `conversation.contract` / `access.contract` 从**整片红**做到 **7 passed** ✓。
> 术语照旧 ✓／✗：✓ = 有读数支撑 ✓，✗ = 没读到或没做 ✓。
> **全部改动未提交** ✓（按分工模型 ✓）。

## 一、结论（四条改动，各有一条"它为什么必须存在"的判据）

| # | 改动 | 判据（不是口味，是代码/读数） |
|---|---|---|
| ① | 契约栈 agent 补 `CODEX_EVENT_STORE_REDIS_URL` | `uses_v1 = self._store is not None`（`session_runtime.py:93`）——没 store ⇒ 只发老信封 ⇒ 前端永远拿不到 `turnId` ✓ |
| ② | 回合的进度/终态改走**会话当前**连接 | 收尾可能发生在重连之后（F10 的刷新 ✓）；发在"收到消息时那条连接"上就是**永远收不到** ✓（旧连接已关） |
| ③ | 断线连上时**补发当前回合**（＝ A5 报告 §七-2 记的"resync 快照接线"） | `event_store.replay()` 与 `ui_events.resync_snapshot()` 此前都是**死代码** ✓（全仓 grep 只有定义、无调用 ✓） |
| ④ | 澄清卡自由输入**常显** + 契约替身补 `isOther` | 设计文档 `2026-09-20-codex-native-interaction.md:315` 原话"choice 每题 **radio + 自由输入**" ✓；同文档 :196 的报文示例里就有 `"isOther": true` ✓ |
| ⑤ | **游标续传接线**（A5 §七-2 的另一半 ✓）：连上时带 `(代际, 序号)` → 服务端补"我漏掉的那一段" | `event_store.replay(key, epoch, after)` 的入参本来就是它 ✓；而 A6 明写 `localSequence: true` 是"**此序号不可用于恢复**" ✓——所以游标只认**真编号** ✓，老信封那条路一律拿不出游标 ✓ |
| ⑥ | 前端 `needsResync` 从 `console.warn` 变成真的重同步 | A6 的不变量是"缺口不补平" ✓——可**不补平的前提是有人处理它** ✗；只打一行日志等于没处理 ✓（用户看到"少了几条"而无从判断 ✓） |

用例卫生两条（都不是产品行为，是测试自己的状态泄漏 ✓）：

- **场景按 runId 存在控制服务上、`reset` 不清它** ✗ → 上一条设的 `clarification` 会继承 ✗（实测：test4/F12 的回合先去弹卡等人作答 → 放行后终态 20s 等不到 ✗）；
- **用例共用一条会话** ✗ → 上一条故意留着的在飞回合把下一条判成 BUSY 拒收 ✗；重连补发还会把**上一条**的回合补进这一条的页面 ✗，于是断言对着旧回合"假绿" ✓。

## 二、原始读数

**契约套件（容器内真浏览器 ✓）**：

```text
✓  1 [setup] 登录并保存 storageState
✓  2 [contract] 会话页面能打开，且全程不碰内网路径
✓  3 [contract] 会话路由是**相对路径**，不是硬编码的域名
✓  4 [contract] F14 越权：拿到无效票据时，连接起不来且不泄漏任何回合数据
✓  5 [contract] 终态放行前：进度已显示、停止仍可点、答案还没有
✓  6 [contract] F12 停止：真中断收尾，且不会冒出假 successful 的答案
✓  7 [contract] F10 刷新：断线重连后回合能恢复，且不重复渲染
✓  8 [contract] F02 歧义：原生卡给出选项与自由输入，回答后仍在同一回合里继续
✓  9 [contract] F10 断线重连（不刷新）：断线期间落下的终态靠游标补回来   ← ⑤ 的验收（5.2s）
  8 passed (26.5s)
```

**那条新用例为什么真的钉得住 ⑤** ✓✓：它在**不刷新**的前提下断开连接 ✓（`context.setOffline` 只影响新连接 ✗，
已建立的 socket 不保证被关掉 ✗——第一版就栽在这儿 ✓，改成"把 `WebSocket` 包一层记实例、再从页面里
`close()`" ✓，静态常量 `OPEN/CONNECTING` 也要照搬 ✗✓，否则 hook 的判等永远为假 → 消息只入队不发 ✓）；
断开**之后**才放行 ✓ → 终态只落进事件流 ✓；而那一刻回合已经结束 ✓（`active_turn` 是 None ✓）——
**"补当前回合"那条路根本补不到它** ✗ → 只有游标这条路能把它捞回来 ✓✓。

**替身账本**（本轮新加的探针 ✓，原文 ✓）——它把"闸门有没有被放行、放了之后有没有收尾"逐条记下来 ✓：

```text
turn_2  放行 +0.20s → finish_once(正常)
turn_3  +0.07s      → finish_once(中断)        ← F12 真中断（无假 completed ✓）
turn_3  迟到放行     → finish_once.skipped      ← "终态只发一次"挡住迟到的放行 ✓
turn_5  60s 超时     → finish_once(中断)        ← 没人放行的那一轮，按**失败态**收尾 ✓
turn_6  放行 +0.06s → finish_once(正常)        ← F02
```

**单测**：`tests/unit/test_ws_reconnect_replay.py` **11 passed** ✓（补发的范围/顺序/失败分支 ✓、会话键来自票据 ✓、游标尾巴与 resync 回落 ✓、以及"事件走会话当前连接"3 条 ✓）；
`tests/unit/test_browser_app_server.py` 6 passed ✓；`tests/integration/test_conversation_replay.py` 15 passed ✓（含新增 `current_epoch` ✓）；
web 侧 `src/utils/conversationCursor.test.mjs` **5 passed** ✓（`node --test` ✓），web 单测合计 36 passed ✓；
tsc **24 条 = A6 基线** ✓（零新增 ✓，顺手补齐了 e2e 里 `RuntimeGate.setScenario` 的**类型漏** ✗✓）。
**agent 全量单测** 1884 passed ✓；唯一一条红是 `test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture` ✗——
它读的是 `zhiyuan-server/data/tmp/session_volunteer_*.json`（**08-14** 的旧文件 ✓），与本轮无关 ✓。

## 三、我先报错了一条，随后用账本推翻（记下来，别让后人重踩）

我一度判断"闸门放行了、替身却等到 60s 超时 ✗"，据此怀疑收尾机制坏了 ✗——**错的** ✓。
账本一击推翻：放行→收尾是**即时**的（50ms 轮询 ✓）；只有**没人放行**的轮次才等满
`CODEX_BROWSER_RELEASE_TIMEOUT`（默认 60s ✓）再按失败态收尾 ✓（设计如此 ✓）。

当时那两条症状的真因是另外两件事，正是上表的 ② 与"用例共用会话"✓。
另外，我把"终态事件的回合号与进度的不同 ✗"当成了 id 不匹配 ✗——也不是 ✓：
**两个 id 空间本来就是分开的** ✓（浏览器认应用的 uuid ✓；替身登记闸门用它自己的 `turn_N` ✓，
账本里 `clientTurnId: null` ✓）——这条替身源码里早写着 ✓，是我没读到位 ✓。

## 四、未完成 / 未验（自标 ✗）

1. **`session.resync` 的"窗口失效"分支真栈未跑到** ✗：`replay()` 回 `None` 的三种成因（代际变／窗口被裁／游标超前 ✓）
   只有单测 ✓；两条真栈用例走的都是**补发成功**那条 ✓。
2. **F10 的第三格"换会话"没做** ✗：任务书那一格的原文是"断线／刷新／**换会话**：cursor 去重、**恢复待答卡**、
   不会把旧队列发到新会话" ✓——前两格有了用例 ✓（刷新 ✓／断线 ✓），**换会话**与**待答卡恢复**没有 ✗。
3. **每用例会话依赖本地私有数据里连号的会话 id** ✗（实测 900003–900047 ✓）——换数据源/
   换 runId 播种时会红 ✓；取法与判据写在 `fixtures.ts` 的注释里 ✓。
4. **改了替身夹具必须重启 agent** ✗（它的 app-server 进程长命 ✓）——不改就是"文件改了、跑的仍是旧代码" ✓。
5. **游标的粒度是"每条会话一份、存内存"** ✓：换会话即作废 ✓（`cursorRef` 随会话重置 ✓）、刷新即没有 ✓
   （刻意不落盘 ✓，见 `conversationCursor.mjs` 的注释 ✓）——将来若要支持多标签页共用一个会话，
   得改成按连接存游标 ✗（现在没有这个需求 ✓）。

## 五、证据边界

- "7 passed"是在**合同栈 + 假运行时**上读的 ✓（`runtimeKind=fake` 由 fixture 开跑前强制校验 ✓）；真实 Codex 二进制上的行为**没验** ✗。
- ② 的判据是"发到会话当前连接" ✓，单测钉住了"优先走会话域、退回本通道、无 runtime 时行为不变" ✓；
  真栈上只由 F10 这一条用例覆盖 ✓。
- 替身账本是**新增的调试能力** ✓（`CODEX_BROWSER_FAKE_TRACE`，默认 `/tmp/codex-fake-runtime.log` ✓）：
  它的 stdout 被网关吞掉 ✗，所以在这之前，"替身到底看到了什么"从外面看不见 ✗。

## 六、复跑（宿主，逐条可直接粘贴）

```bash
# 1) 起合同栈（三项必需环境变量：server-config / data-source / codex-home）
export CODEX_LOCAL_SERVER_CONFIG=/root/dev/zhiyuan/.local/codex-local/application-codex-local.yml
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME=/root/dev/zhiyuan/.local/codex-local/runtime-home
bash /root/dev/zhiyuan/scripts/start-codex-contract.sh --run-id <RUN_ID>

# 2) 每次跑用例前**必须重注验证码**（登录成功即被消费 ✗）
bash /root/dev/zhiyuan/scripts/inject-codex-e2e-sms-code.sh 13000000002 498921

# 3) 跑契约（RUN_ID 必须与第 1 步一致，否则 cleanGates 的 reset 清不到本 run 的闸门 ✗）
env ZHIYUAN_E2E_ORIGIN=http://127.0.0.1:3201 \
    ZHIYUAN_E2E_SESSION_URL='/sessionDetailV2?chatSessionId=900047&userId=900002&page=1&pageSize=10' \
    ZHIYUAN_E2E_RUN_ID=<RUN_ID> ZHIYUAN_E2E_MOBILE=13000000002 ZHIYUAN_E2E_SMS_CODE=498921 \
    bash /root/dev/zhiyuan/scripts/run-codex-e2e-in-container.sh --project contract

# 4) 排"闸门/回合"类问题时先看账本
cat /tmp/codex-fake-runtime.log
```

---

## 七、续作：把 contract 半场补齐（2026-09-26 晚）——**11 passed** ✓✓

**目标**（用户定的"近路"✓）：把任务书 F 表里**只读栈能验的那些格子**补成用例 ✓。
结果：`contract` 项目从 8 条 → **12 条用例（11 passed ✓）**，新增覆盖 **F15、F11**，
外加 **F10 的另两格**（断线不刷新 ✓、刷新恢复待答卡 ✓）。

### 用例现状（12 条 / 11 passed）

| 用例 | 判据（任务书原文） | 状态 |
|---|---|---|
| access×2、F14 | 相对路径 / 无票/跨租户拒绝 | ✓ |
| 终态放行前 | 进度早于终态、停止可点、无假完成 | ✓ |
| F12 停止 | 真 interrupt、无假 completed | ✓ |
| F10 刷新 | cursor 去重、恢复不重复 | ✓ |
| F10 断线（不刷新） | 断线期间落下的终态靠**游标**补回 | ✓ |
| F10 恢复待答卡 | 卡的事件在流里、答回原请求 | ✓ |
| F15 模型格式坏 | 显示可恢复错误、无 JSON/reasoning 泄漏 | ✓ |
| F11 存储换代 | resync 重建基线、**不漏新代低序号** | ✓ |
| F02 歧义 | 选项+自由输入、原 request 续同一 Turn | ✓ |

（仍未覆盖：**F07/F08/F09/F13** 属写路径 ✓——契约栈现在是 `codex_readonly` ✗，
要它们得先给契约栈开 `codex_write` ✓；**F16** 需工作台/review 流 ✓；F01/F03–F06 属 `real` 半场 ✓。）

### 这一轮修掉的**真缺陷**（全部有实测 ✓，多数是产品侧 ✓）

| # | 症状（用户可见的） | 根因 | 修在哪 |
|---|---|---|---|
| 1 | 前端每 5s 的心跳被当成**一轮对话** ✗（占回合、调模型、失败再发错误事件 ✓）→ 客户端把这些"凭空出现的新回合"判成缺口 ✓ → 重同步**清掉在飞回合的界面** ✗ | **native 路由没有 ping 分支** ✗（compat 那两条一直有 ✓） | `server.py`：当场回 `pong` ✓ + 单测"心跳到不了网关" ✓ |
| 2 | 失败那一轮**整轮静默** ✗（用户什么都看不到 ✓） | 失败时 V1 **无条件**发 `assistant.completed` ✓，而 `result` 里没有 `reply` ✗ → `message` 空串 ✗ → 前端"有终态且有文本"才渲染 ✓ | V1 失败改发 `recoverable.error` ✓ + 前端渲染 `turn-error` ✓ + 抽 `_emit_turn_terminal` 带 3 条单测 ✓ |
| 3 | 首轮失败查不出原因 ✗ | 网关只回异常**类名** ✓、堆栈被吞 ✗ | `logger.exception` ✓ → **一击点名**下一个根因 ✓✓ |
| 4 | **每轮起栈后第一条用例必红** ✗（看起来像"首轮有问题" ✗） | 替身 thread id `thr_1/thr_2…` **跨进程重来** ✗ × Java 绑定表持久 ✓ → `binding_thread_identity_conflict` ✗ | 替身 id 带上 pid ✓（**恢复保真** ✓：真实 codex 的 thread id 本就全局唯一 ✓） |
| 5 | 界面被**反复清空**（"消息发出去了、回合没了" ✗） | **老信封与 V1 混流** ✗：转换产物带常量代际 `local` ✗，reducer 当真代际采纳 ✓ → 真 V1 一到就判换代 ✓（A6 报告预言过 ✓） | reducer：本地占位 ↔ 真代际**两个方向**都直接采纳、不判缺口 ✓ + 4 条单测 ✓ |
| 6 | 放行**没落到**替身、白等 60s ✗（一度是"放行没落地"之谜 ✓） | `cleanGates` 会**先放行、再 reset** ✓，而 reset 把闸门**删掉** ✗ → 替身只认 `released` ✗ → 把"已清理"读成"没放行" ✓ | 控制服务回 `known` ✓ + 替身区分"不存在"与"没放行" ✓，不再空等 ✓ |

### 新增的**仪器**（这一轮最值钱的一半 ✓✓）

- **替身账本** ✓：`CODEX_BROWSER_FAKE_TRACE`（默认 `/tmp/codex-fake-runtime.log` ✓）——
  记 `turn_start / wait_for_release.* / finish_once` ✓。它的 stdout 被网关吞掉 ✗，
  在此之前"替身到底看到了什么"从外面看不见 ✓（本次凭它一次推翻了我自己的一条错判 ✓）。
- **帧→状态探针** ✓：控制台执行 `localStorage.setItem('zhiyuan.conversationTrace','1')` 再刷新 ✓，
  逐帧打印"是不是 V1 ✓ / 代际序号 ✓ / reducer 吃下没有 ✓ / 是否触发重同步 ✓"——
  F15/F11 的根因都是它一次点名的 ✓✓（默认关 ✓，每条帧一行会很吵 ✓）。
- 控制服务的 `rotate-epoch` ✓（存储换代的**唯一**可控注入点 ✓：用例在容器里够不到 Redis ✗）。

### 顺带修的测试侧问题

每用例会话**跨文件撞车** ✗（占位表挂 `globalThis` ✓——两个 spec 文件各有一份计数 ✓，
一次跑里同一会话被连了 3 次 ✓）；F15 不再把"坏输出"与"闸门时序"缠在一起 ✓；
F11 用**收尾型**放行 ✓（判据型那版仍留给只该有一轮的用例 ✓）；
探针窗口 200→900 字 ✗✓（本仓踩过一次的老坑 ✓：正好把要看的字段切掉 ✓）。

---

## 八、续作 2：写路径（F07/F08/F09/F13）的**地基**（2026-09-26 深夜）

**这一轮没有新增用例** ✓——补的是那四格**跑起来所需要的东西** ✓，外加把它"现在缺什么"钉成读数 ✓。

### 已就位并实测的三件

| 件 | 读数 |
|---|---|
| **契约栈可按 run 起在 `codex_write`** ✓ | `CODEX_LOCAL_GATEWAY_MODE` 覆盖开关 ✓（默认一个字节不变 ✓，形状与既有的 `CODEX_APP_SERVER_USER_INPUT_MODE` 一致 ✓）。实测：agent 起在 `codex_write` ✓、`health: {"status":"UP"}` ✓、而 **`MCP_MODE=readonly` 保持不变** ✓——写模式的语义是"**确认链**活着"✓，不是给模型开写工具 ✓（P2 的定义 ✓，别顺手一起改 ✗） |
| **替身会发提案** ✓ | 新场景 `proposal` ✓：终态正文带一个形状照 `contracts.py` 的 `proposalRequest` ✓（`proposalSource=user_goal` ✓、`goalType=exclude_scope` ✓、负向范围 ✓） |
| **场景参数通道** ✓ | 控制服务新增 `POST/GET /runs/{id}/scenario-params` ✓——替身自己拿不到的数据（最典型是提案的 `sourceVersionGuard` ✓）由测试喂 ✓ |

### F07 的探路读数（四条，都是这一轮抓到的 ✓）

1. **守门值就是 `data.version`** ✓：`/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=…`
   实测回 `{"data":{"…","version":0,…}}` ✓；
2. **那台会话是 `phase: profile_ready`** ✓ → **成功提案需要先有候选池/方案** ✗——
   与 `P2/REPORT.md` 第九轮"还差「成功 apply」需要会话先有候选池/方案（多回合铺垫）"✓ 完全对上 ✓；
3. 所以 F07/F08 的用例要**多轮铺垫** ✗，不是加个断言就行 ✓；
4. 前端**提案卡**（含确认/取消）✗ 仍缺——`conversationAction` 出站已存在 ✓，
   缺的是渲染与接线 ✓；P2 报告第九轮的原话就是"仅剩前端按真实结果更新确认卡片需浏览器" ✓。

**处置** ✓：探路用的临时用例**已撤** ✗（不在仓库里留半截用例假装覆盖 ✓——
那正是本仓反复强调的 ✗），读数与缺口的记档留在
`zhiyuan-web/tests/e2e/conversation.contract.spec.ts` 的注释里 ✓。
撤掉后全套回到 **11 passed / 0 failed** ✓✓。

### 两条环境教训（已写进记忆 ✓）

- **按端口清遗留时，认"父进程"别只认命令行** ✗✓：3201 上那个是 `next-server` **子进程** ✓，
  命令行里不含 `zhiyuan` ✓ → "只杀自家人"的规则**正确地**放过了它 ✓ → 新栈一直报"被占就拒" ✗。
  判据补了一条：**父进程**是 `next dev` 也算我们的 ✓。
- **磁盘 96%（剩 1.8G）** ✗：不是本仓的文件（`.runtime` 仅 43M ✓），但足以让 Java/MySQL
  写临时文件时出怪事 ✓（当天后端"起来就死"很可能与它有关 ✓）。跑很多轮 e2e 的日子先看一眼 `df -h` ✓。

### 八之补：探路结果（2026-09-27 上午）——**12 passed** ✓✓，并且**写模式无回归** ✓

**现在 12 条用例、在 `codex_write` 栈上跑也是 12 passed** ✓✓（`12 passed (33.6s)` ✓）——
即"模式开关"这一改**不动原有 11 条** ✓（这是它敢留的判据 ✓）。

新增的那条（`F07 提案草稿：模型产出能过契约，且这一轮正常收尾` ✓）断的是**真契约** ✓：
替身发的 `proposalRequest`（形状照 `contracts.py` 的 `ProposalRequest` ✓）必须过 `TurnOutput` 的校验 ✓。

**这一轮又抓到的两条（都有实测原文 ✓）**：

1. **`responseType: recommendation` 必须带 `artifactRefs`** ✓——否则整条被拒 ✓：
   实测 `output_schema_invalid: Value error, artifactRefs is required for recommendation/review output` ✓。
   而提案是由 **`proposalRequest` 字段**承载的 ✓，与响应类型无关 ✓ → 用 `text` 即可 ✓
   （替身注释里留了原文 ✓，免得下一个人再踩 ✓）。
2. **编译强依赖会话的 legacy 志愿数据** ✗：后端实测
   `PlanningStateController.prepareUserGoalFixProposals` → `PlanningStateService.loadLegacyPlanSource`
   → `VolunteerBizService.loadOriginalVolunteerData` → `AliOSSService.downloadFile` →
   **`NoSuchBucket`** ✗（本地栈的 OSS 是占位桶 ✓）。本地合成会话（900xxx）**没有这类文件** ✗
   → 所以 **`proposal.preview` 出不来** ✓、F07 的后半格（确认/取消 ✓）与 F08/F09/F13 都卡在它前面 ✓。
   **下一步（数据侧 ✓，配方有先例 ✓）**：照 P2 第九轮那套给用例会话铺一份 legacy 志愿数据 ✓
   （读法顺序 `_final.json` → `_temp.json` → 无后缀兜底 ✓，落盘在 `.local/codex-local/tmp` ✓）。

### 八之补 2：把提案推到"编译那一步" —— 四道关，全部**有实测原文** ✓（2026-09-27 中午）

从"替身发出提案草稿"走到"Java 编译器真的开始编译" ✓，一路被四道关拦下 ✓，
**每一道都是栈自己报出来的** ✓（没有猜 ✓）：

| # | 原文（栈自己说的） | 真因 | 处置 |
|---|---|---|---|
| 1 | `output_schema_invalid: Value error, artifactRefs is required for recommendation/review output` | 契约规则：`responseType` 是 recommendation/review 时**必须带 artifactRefs** | 替身改用 `text` ✓（提案由 `proposalRequest` 字段承载 ✓，与响应类型无关 ✓） |
| 2 | `NoSuchBucket` → `legacyPlanImport … reason=下载志愿数据文件失败` | 编译**先读会话的 legacy 志愿数据** ✓；本地栈 OSS 是占位桶 ✗ | 照 `VolunteerFilePathUtil` 的命名 `<tempDataPath>/session_volunteer_<id><后缀>.json` ✓ 铺一份 ✓ → 实测 `成功加载原始志愿数据 … 17350610 bytes` ✓ + `legacyPlanImport success … candidates=6236` ✓✓ |
| 3 | `pending revision conflict: current=1 expected=0` | 守门值喂成了**工作区 `version`** ✗（那是 0 ✓）；编译要的是**待确认修订号** ✓ | 探针改为喂观察值 ✓；正经验收**必须从状态里读** ✓ |
| 4 | `stale_state: proposal source version does not match the current snapshot` | 同一次编译还会拿它跟**快照版本**比 ✓——两个计数器都要对齐 ✓，而这条会话被今天十几次尝试**写脏了** ✗（pending 已是 1 ✓、快照还是 0 ✓） | 每条用例改用**干净会话** ✓ + 守门值**从状态读** ✓ |

**净结论（写给下一环 ✓）**：`proposal.preview` 出不来**不是链路断了** ✗——链路已经走到编译器里 ✓；
缺的是**用例侧的会话准备** ✓：① 一份 legacy 志愿数据（照命名铺 ✓，已验 ✓）；
② 干净的会话状态 ✓（每条用例自己的会话 ✓，别在同一台上反复试 ✓）；
③ 守门值**从状态里读**（不是常量 ✓）。这三件都在**数据/夹具**侧 ✓，**不动产品代码** ✓。

### 八之补 3：守门值**不在**工作区状态里（省下一轮搜索 ✓，2026-09-27）

四处翻过的结论，写给下一环 ✓：

- `GET /gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=…` ✓
  **免鉴权可达** ✓（可直接 curl ✓），但它的 `data` 里**只有** `version` ✓ 与
  `dataFreshnessState.dataVersion / latestDataVersion` ✓ —— **没有**任何 proposal / pending / revision 字段 ✗；
- 会话在铺了 legacy 志愿数据之后会推进到 **`phase: candidate_generated`** ✓（数据生效的旁证 ✓）；
- `"current=1"` 那个**待确认修订号** ✗ 在工作区状态里找不到 ✓ → 应在**待确认命令**那一侧 ✓
  （`PlanningStateController` 有 `/session/pending-command/execute` ✓，实体是
  `PendingPlanningCommandBizService` ✓——**下一轮从那里找** ✓，不要再翻工作区状态 ✗）。

**下一轮的三件（都在测试/数据侧 ✓，不动产品代码 ✓）**：
① 把待确认修订号**读出来**（起点：`PendingPlanningCommand*` ✓）→ 喂 `sourceVersionGuard` ✓；
② **每条用例一台干净会话** ✓（同一台反复试会把状态写脏 ✓：pending=1 而快照=0 ✓，两个计数器就对不上了 ✓）；
③ **铺 legacy 志愿数据**做成夹具能力 ✓（控制服务加一个 seed 端点 ✓，与 `rotate-epoch` 同形 ✓：
   它跑在宿主上 ✓，能写 `.local/codex-local/tmp/` ✓；命名照
   `VolunteerFilePathUtil: <tempDataPath>/session_volunteer_<id><后缀>.json` ✓，后缀 `""`/`_final`/`_temp`/… ✓）。

### 八之补 4：链路已经通到"编译成功"，缺的是**发射条件**（2026-09-27 下午，最后一处 ✓）

用**干净会话 + 铺好的数据 + `fill_to_count`** 跑 ✓，Java 侧实测：

```
14:14:53.277 接口请求开始 - URI: …/fix-proposals/user-goal/prepare ✓
14:14:53.287 prepareUserGoalFixProposals: tenantId=1, chatSessionId=900036, requestId=1:900036:… ✓
14:14:53.581 接口请求完成 - URI: …/prepare … 状态码: 200 ✓✓
14:14:53.637 接口请求完成 - URI: …/turn-snapshot … 状态码: 200 ✓   ← 编译后又拉了快照（pending 已在 ✓）
```

**即：提案编译成功 ✓、待确认已建 ✓、快照也重读过 ✓——但事件流里没有 `proposal.preview`** ✗，
而且**没有报错** ✗（若编译失败会像之前那样来一条 `proposal_preview_unavailable` ✓）。

**所以剩下的这一处不在环境/数据侧，也不在 Java 侧 ✓**：在**网关的发射条件** ✓——
读 `app/gateway/service.py` 里构造 `proposalPreview` 那段（约 1166–1243 行 ✓）：
它在什么条件下才把 preview 放进终态/发成事件 ✓（`allow_proposal`？某个 `response_type`？
还是"要等下一轮快照"？✓）。**下一轮从那里进去** ✓。

**这一轮把"用例侧的准备"全部做成了能力 ✓（都已实测 ✓，不动产品代码 ✓）**：
- 控制服务 **`POST /runs/{id}/seed-volunteer`** ✓（替代手工 cp ✓，命名照 `VolunteerFilePathUtil` ✓）；
- runner **透传 `ZHIYUAN_E2E_SESSION_SALT`** ✓ + 夹具**按 run 加盐取会话** ✓（"干净会话"从口头约定变成开关 ✓）；
- 替身的提案 `goalType` 改成 **`fill_to_count`** ✓（确认链只认这两种 ✓，P2 报告 283 行 ✓）。

### 八之补 5：**`proposal.preview` 出来了** ✓✓（2026-09-27 下午）—— 以及顺带暴露的下一处

**根因就在收尾那段里** ✓✓：网关**早就算好了** `proposalPreview`（`service.py`：编译 → 取
`proposals` → 放进结果 ✓），而 `_emit_turn_terminal` 只发 `assistant.completed` +
`turn.completed` ✗——**从不把它发成事件** ✗。所以症状是"编译 200 ✓、快照重读 ✓、事件流里
一条 preview 都没有 ✓、而且**不报错** ✓"（从外面看像"链路没走到" ✗）。
已修 ✓（成功分支里、答案之前发 `proposal.preview` ✓）+ 两条单测 ✓
（有预览才发 ✓、没有不许凭空发 ✓）。

**实测原文** ✓（写模式 + 干净会话 + 铺好数据 + `fill_to_count` ✓）：

```
14:24:51 900035 88 tool.progress
14:24:51 900035 89 proposal.preview {"strategy": "fill_missing_count", "dryRunResult": {…}} ✓✓
14:24:51 900035 90 assistant.completed ✓
14:24:51 900035 91 turn.completed ✓
```

**顺带暴露的下一处** ✗（同一跑里就看见了 ✓）：预览载荷的键是
`strategy` / `dryRunResult` / … ✓，而**前端白名单**只放
`proposalRef` / `diff` / `sourceVersion` / `expiresAt` ✗（`conversationEvents.mjs:33` ✓）——
两边键名对不上 ✓ → 到了页面会被 `sanitizeV1Payload` 过滤成 `{}` ✗ → **空卡** ✓。
**下一轮要做的两件（都是契约/前端侧 ✗，不再是环境或数据 ✗）**：
① 给 preview 事件定一份**双方一致的载荷** ✓（要么扩白名单 ✓、要么在网关侧映射成那四个键 ✓，
属设计口径 ✗）；② 前端**提案卡**（渲染 + 确认/取消 ✓）—— 之后 F07 后半与 F08/F09/F13 才谈得上 ✓。

### 八之补 6：**可确认的提案**出来了 ✓✓（2026-09-27 下午，本段收口）

两处一起修好之后 ✓，事件流里拿到的是**前端合同形状**的、**可确认**的提案：

```
14:31:47 conv:{1:900034}:stream seq 56
{"proposalRef": "ugp_539e3215ab98348f",
 "diff": {"title": "补齐到 80 个志愿的调整预览",
          "summary": "当前方案有 0 个志愿；本次将从符合已确认要求的候选中补入 80 个，达到 80 个。",
          "requiresConfirmation": true, "status": "ready"}}
```

**① 翻译归网关** ✓（产品侧 ✓）：Java 的预览字段名与前端白名单**对不上** ✗
（Java 给 `proposalId`/`title`/`summary`/`status`/`blockingReason`/`solverResult`… ✓，
白名单要 `proposalRef`/`diff`/`sourceVersion`/`expiresAt` ✗）→ 不翻译就被 `sanitizeV1Payload`
过滤成 `{}` ✓、页面拿到**空卡** ✓。
已修 ✓：`_proposal_preview_payload` 把 Java 形状翻成合同形状 ✓（`proposalRef` ← `proposalId` ✓；
`diff` 只带**给人看的那部分** ✓；求解器内部形状（digest / solverResult / dryRunResult ✗）**不进载荷** ✓——
它们对用户没意义，还会让载荷随求解器版本漂移 ✓）+ 一条映射单测 ✓。

**② 铺数据要裁小** ✓（夹具侧 ✓）：源文件 17MB / 6236 条 ✗ → 求解器撞复杂度上限 ✓
（实测 `blockingReason: canonical solver 输入超过 M1 受控复杂度上限` ✓）→ 提案是
`status: blocked` ✗（链路通、但**不可确认** ✓）。`seed-volunteer` 现在默认裁到 120 条 ✓
→ `status: ready` ✓ + `requiresConfirmation: true` ✓✓。

**至此这条链在契约层是完整的** ✓✓：替身发提案 ✓ → 过契约 ✓ → Java 编译 200 ✓ → 网关算预览 ✓
→ **翻译成合同形状** ✓ → **V1 事件发出** ✓ → 快照重读 ✓ → 提案 `ready` 且要确认 ✓。
**只剩前端** ✗：把这张卡画出来 + 确认/取消接线 ✓（`conversationAction` 出站早就有 ✓）——
之后 F07 后半（取消 ✓）与 F08/F09/F13 才谈得上 ✓。

### 八之补 7：**提案卡在浏览器里渲染出来了** ✓✓（2026-09-27 下午，这一段收口）

```
✓ F07 提案草稿：模型产出能过契约，且这一轮正常收尾 (2.3s)   ← 断言里含**卡** ✓
seq 33 proposal.preview {"proposalRef": "ugp_b19505df2be8315f",
   "diff": {"summary": "当前方案有 0 个志愿；本次将从符合已确认要求的候选中补入 80 个，达到 80 个。",
            "requiresConfirmation": true, "status": "ready", …}}
```

**这是会话里第二类"要用户动作"的卡** ✓✓：澄清卡问"你指哪一个" ✓，提案卡问"**这份调整要不要采纳**" ✓。
新增 `ProposalCard.tsx` ✓（`data-testid="proposal-card"` / `proposal-confirm` / `proposal-cancel` ✓；
三种状态分得开 ✓：`blocked` 只解释原因、**不给按钮** ✗ / 要确认 → 给按钮 ✓ / 其余只展示 ✓）
+ 在回合块里接线 ✓ + **出站复用既有那条 `conversationAction` 帧** ✓✓（不新造协议 ✓：
`confirm_proposal` / `cancel_proposal` + `expectedSourceVersion` + `intent: 'explicit'` ✓）。

**为让它可复现，夹具又补了两件** ✓（都在测试/数据侧 ✓）：
- 控制服务 **`POST /runs/{id}/reset-session`** ✓✓（清"干净会话"✓）——两处踩点都是实测原文：
  ① 只清 `pending_command` + `proposal_request` 不够 ✗（编译仍报 `pending revision conflict: current=1 expected=0` ✓）
  → 真正的"待确认修订号"在 **`assistant_chat_session_pending_confirmation`** ✓；
  ② 只清待确认也不够 ✗（卡出现了 ✓ 但状态是"无法执行" ✓、`blockingReasonCodes: ["solver_complexity_limit"]` ✓）
  → **候选池/快照在 `assistant_chat_session_extra_data`** ✓，不清它就还是从上一份（未裁剪的）数据建的 ✓。
- `seed-volunteer` **改成一贯写裁剪后的那份** ✓（不这样，早先手工铺过的大文件会留着 ✓ → 提案永远 `blocked` ✓）。

### 八之补 8：提案的**动作回包**通了；卡片与待确认的"身份/版本"还差一处收口 ⚠（2026-09-27 傍晚）

**这一段落地的两件（都是产品侧 ✓，各带单测 ✓）**：

1. **`conversationAction.result` 也从不发成事件** ✗→✓——与提案预览**同一个病** ✓：
   网关 `execute_action_and_refresh` 早把 `actionResult`（含 `actionStatus` ∈ {applied, cancelled} ✓）
   放进结果 ✓，而收尾那段不发 ✗ → 卡片永远停在"待确认" ✓（实测：点了"放弃" ✓，
   事件流里只有 `assistant.completed("操作已处理。")` ✓）。已修 ✓（键名照白名单 ✓；
   `workspaceVersion` 取外层 `snapshotVersion` ✓）。
2. **手拼出站帧踩了 schema** ✗→✓：`WSMessage.content` 是 **`str`** ✗（我塞了对象 ✓）→ 服务端
   **拒收且不记日志** ✗✓（症状：点"放弃"什么都没发生 ✓，agent 日志里只有握手 ✓）。
   已按本仓规矩**抽成纯函数** ✓ `buildPendingConfirmationFrame` ✓（`content: ''` ✓ +
   `type: 'pendingConfirmation'` ✓）+ 两条 node:test ✓。

**还差一处的收口 ⚠**（位置已定 ✓，不是谜 ✓）：卡片带去的 `proposalRef`/`sourceVersion`
与**待确认那一条**对不上 ✓ → 服务端判 `stale_state` ✗（`actionStatus: "stale_state"` ✓）。
对照读数（curl `turn-snapshot` 与 MySQL 两处原文 ✓）：

```
activeProposal.proposalRef = 00f9bf22-…（= pendingId ✓）   ← 卡片带的是编译器的 ugp_… ✗
activeProposal.revision    = 1                              ← 卡片带的是 0（编译前的值 ✗）
```

网关侧已经加了"用刷新后快照里的这两个值覆盖预览" ✓，且**日志证明它跑到了** ✓
（`proposal preview override: snapshot=ConversationTurnSnapshot active=dict
 attrs=['…','pendingId','proposalRef','revision','…']` ✓）——**但发出去的预览仍是 `ugp_…`** ✗
→ 说明**从 override 到 `result["proposalPreview"]` 之间还有一处**要走通 ✓
（下一轮就从那里读代码 ✓，一次能定位 ✓）。

**用例布局随之调整** ✓：F07 后半那条要求 `codex_write` 栈 ✗，已**单独成 project**（`write` ✓，
`grep: /F07 后半/` ✓），`contract` 项目用 `grepInvert` 把它排除 ✓——这样"栈起成了只读"
不会被读成"功能坏了" ✓，也不会把还没做完的写路径混进全绿的合同套件 ✓。

#### 八之补 8 之续：身份对上了，**版本语义**还差一处（2026-09-27 傍晚）

**已修并验证** ✓✓：`_proposal_preview_payload` 里 `proposalRef` 与 `proposalId` 的**优先级**
（写成 `proposalId` 优先 ✓ → 会把网关的覆盖**自己撤销掉** ✗；实测两处读数正是这么自洽的：
版本换成了 1 ✓、ref 却始终是 `ugp_…` ✓）。改成 `proposalRef` 优先 ✓ 之后，实测结果事件里
`proposalRef` = **`f05bc83a-…`（pendingId ✓）** ✓✓——身份这一半通了 ✓。

**还差一处的读数** ✗：状态仍是 `stale_state` ✗ → 说明卡片带的**版本**与服务端要的**不是同一个计数器** ✓：

```
喂 0（编译前的 sourceVersion）→ pending revision conflict: current=1 expected=0   ✗
喂 1（pending 的 revision）   → stale_state: proposal source version does not match the current snapshot  ✗
```

两次都红、且**互为镜像** ✓——即"待确认修订号"与"快照/计划版本"在**同一条会话上不相等** ✓，
而确认/放弃同时要过这两关 ✓。**下一轮从这里入手** ✓：读 Java 侧
`validatePlanChangeProposal`（`PendingPlanningCommandBizService` ✓）与
`RepairProposalApplyPolicy.validateUserGoalProposalForApply` ✓——**谁比的是哪个计数器** ✓，
以及"卡上该显示哪个" ✓（属设计口径 ✗：两处若注定不等 ✓，卡片就必须带**对的那一个** ✓）。

#### 八之补 8 之终：**F07 完整通过** ✓✓（2026-09-27 晚）

```
✓ [write] › F07 后半：放弃提案不改变正式内容 (2.7s)   ✓✓
```

**最后两处（都是"同一个东西的两个字段"搞混了 ✓✗）**：

1. **要覆盖的是快照的 `sourceVersion`，不是 `revision`** ✗✓——判据原文在
   `app/gateway/conversation_actions.py:139-152` ✓：拿 `activeProposal.sourceVersion`
   （或 `data.sourceVersion` / `data.sourceBackendVersion` ✓）与动作里的 `expectedSourceVersion` 相减 ✓；
   而 `revision` 是同文件 156 行起**另一处**用的 ✓。我上一轮覆盖成了 `revision` ✓ →
   "身份对了、版本错了" ✓✗（两次红互为镜像 ✓，正是它俩不等造成的 ✓）。
2. **动作回包落在另一轮上** ✗✓：网关为"采纳/放弃"这动作**另起一轮** ✓
   （`conversationAction.result` 挂在新回合 ✓），而卡片画在**提案那一轮**里 ✓ →
   卡片只读本回合就永远"待确认" ✓（实测：事件流里已经有 `actionStatus: "cancelled"` ✓、
   卡上还是"待确认" ✓）。已改成**按 `proposalRef` 跨回合找** ✓（取最后一条 ✓，
   同一张卡会先 `applying` 后 `applied` ✓）。

**至此这条链在浏览器里是完整的** ✓✓：替身发提案 ✓ → 过契约 ✓ → Java 编译 200 ✓ →
网关算预览 ✓ → 翻成合同形状 ✓ → **卡** ✓ → 点放弃 ✓ → 出站帧（纯函数 ✓）✓ →
网关两段式 ✓ → Java 取消 ✓ → **`actionStatus: "cancelled"` 事件** ✓ → 卡进终态、
按钮收起 ✓ → **正式内容与基线逐项一致** ✓✓（"取消不改变正式内容" ✓ 任务书原文 ✓）。

**两端复核** ✓：`contract` 项目 12 passed ✓（写路径那条由 `grepInvert` 排除 ✓）、
`write` 项目 1 passed ✓（起栈要 `CODEX_LOCAL_GATEWAY_MODE=codex_write` ✓）。

### 八之补 9：F08 的**双击不双写**成立 ✓✓；卡住的是"apply 本身还没成功" ⚠（2026-09-27 深夜）

**新增用例** ✓：`F08 确认：双击不双写，且 applied 后读得到 workspace` ✓（在 `write` project ✓）。

**已成立的那半** ✓✓（有原始读数 ✓）：**双击不会双写** ✓——两次点击只产生**一次** execute ✓：

```
15:58:20.184 pending/resolve 完成 200 ✓     ← 第 1 次点击：claim ✓
15:58:20.195 pending-command/execute 开始 ✓ → .256 完成 **200** ✓   ← **只此一次** ✓✓
15:58:20.258 pending/resolve 完成 200 ✓     ← 第 2 次点击的 claim（落在已执行完的 pending 上 ✓）
```

**还差的那半** ⚠：那一次 execute 的**响应体里是业务失败** ✗（两段 HTTP 都是 200 ✓，而网关按
"HTTP 成功 ≠ 执行成功" ✓ 如实报 `failed` ✓）→ 卡显示"**未生效**" ✓（**这正是设计要的**：
失败不许读成成功 ✓）。所以缺的**不在链路、也不在卡** ✗——是 **apply 本身在这条会话上没成功** ✓，
与 `P2-write-closed-loop` 报告自己挂着的那条**同源** ✓："还差「成功 apply」需要会话先有候选池/方案
（多回合铺垫）」✗。**下一轮从这里入手** ✓：读 execute 的响应体业务码（`conversation_actions._status` ✓
把它翻成状态 ✓）→ 对上 Java 侧的前置 ✓。

**顺带** ✓：`_execute_claimed_command` 现在会为每次 execute 打一行输入读数 ✓
（`proposalRef` / `dataKeys` / `operationId` ✓，一次一行不刷屏 ✓）——实测靠它一次排掉了
"operationId 没落进快照"这条假设 ✓（读数：`operationId='c5142518389d47f08b3cdb07d7f20baf'` ✓）。
