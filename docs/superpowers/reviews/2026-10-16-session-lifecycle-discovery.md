# 会话安全回收：只读调查与建议

日期：2026-10-16。基线：`bedc026`，分支 `wip/2026-09-28-p2-write-loop-green`。

## 范围与状态

本轮承接可信产物 SQLite 账本和前端生产构建/浏览器验收，调查 Gateway 会话对象的安全回收条件。**没有实施会话驱逐，没有修改应用代码、在线配置或业务状态。** 本文件是调查记录与待批准建议，不是已经批准的实现 spec。

检查清单：

- [x] 核对基线、工作区和既有交接记录。
- [x] 追踪回合、连接、后台动作、原生问答、续接与缓存引用。
- [x] 用离线纯内存探针验证现有保留行为和不能直接复用的判定接口。
- [x] 比较回收路线并提出分批顺序。
- [ ] 确认下一批边界，形成正式设计与测试计划。
- [ ] 实现、回归验证、复审，再评估提交。

保留用户原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/`，以及上一轮尚未提交的 Web 验收记录。本轮没有提交、推送、部署、服务重启、真实模型调用或共享数据库写入，也没有读取在线服务的待确认卡来做实验。

## 结论

可信产物持久化的前置条件已经具备，但**当前尚不具备直接按 TTL 删除会话字典的安全条件**。需要先修问答对象清理，再补跨组件的生命周期引用登记，最后接入只回收空闲会话的策略。

需要区分三类情况：

1. **已确认的保留问题**：部分会话字典无淘汰；问答记录及反向索引未对称清理；native 路由默认不摘除关闭连接的登记。
2. **现有正常语义，不能误判成空闲**：无 requestId 的 detached 动作；已回答记录用于重复作答判定；只登记最新投递连接；业务待确认卡需要等待用户。
3. **引入简单回收后才会出现的风险**：锁等待者被拆到两把锁、水位重置造成 ABA、清掉 thread 反查身份、异步查询期间删掉重新活跃的会话。这些不是当前已发生的驱逐缺陷，因为目前还没有该驱逐机制。

## 离线证据

临时材料：`/tmp/zhiyuan-session-lifecycle.ZkWiat/probe.py` 和同目录 `observations.json`。脚本是一次性调查探针，不作为生产代码或正式回归测试交付。

运行命令：

```bash
PYTHONPATH=/root/dev/zhiyuan/zhiyuan-agent PYTHONDONTWRITEBYTECODE=1 \
  /root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python \
  /tmp/zhiyuan-session-lifecycle.ZkWiat/probe.py
```

探针执行退出码为 0，10 项观察断言得到确认。只创建 fake loader、内存 Gateway/Runtime/Broker、Future 和任务；未启动应用。进入探针业务逻辑前安装 audit hook，禁止 socket connect/bind、子进程和 SQLite 连接。预期日志中的 `synthetic snapshot loader outage` 是人为注入的查询失败，不是在线告警。

| 观察 | 实际结果 | 能说明什么 |
| --- | --- | --- |
| 100 个 legacy 会话，回合缓存上限 2 | 回合缓存 2，锁 100，水位 100 | 回合缓存有界不等于会话生命周期有界 |
| 只读取 100 个会话快照 | 快照 100，working set 100，锁 0 | 仅围绕 `handle_turn` 做回收登记会漏掉公共读取路径 |
| 权威快照 loader 抛异常 | `get_authoritative_snapshot` 仍返回旧缓存，且缓存无 active proposal | 该接口不能提供“本次成功确认没有待确认卡”的证明 |
| 无 requestId 的 detached 动作等待 Event | active turn、pending requests、channels 都为空，detached 任务仍为 1 | 这三项为空不能证明会话可回收 |
| 旧连接被新连接替换，然后摘掉新连接 | 当前投递登记为空，不会自动关闭旧连接 | `_channels` 不是全部连接持有者；这里只探测登记表，没有打开 WebSocket |
| 成功回答后重复同答案 | accepted；可见卡片 0，完整记录 1，反向索引 1 | 空卡片快照不等于没有问答保留状态 |
| 问答超时 | pending 0，反向索引 1 | timeout 清理不对称 |
| 取消等待答案的任务 | future cancelled，pending 1，反向索引 1，可见卡片仍为 1 | 取消会留下已不能作答、TTL 内却仍可展示的记录 |
| 调用 `expire_runtime` | pending 0，反向索引 1 | runtime 清理也不对称 |
| 用不同 generation 调用 `resolve_native` | 当前记录仍被移除 | helper 未核对 generation；这是直接 helper 探针，未证明在线存在通知误路由 |

这些结果不是吞吐、RSS、真实模型或真实数据库测试，不据此宣称线上已经内存溢出或已经发生跨代串答。

## 已确认的问题与边界

### 1. 会话字典没有统一寿命

`zhiyuan-agent/app/gateway/service.py:1202` 的 `_threads`、`_snapshots`、`_working_sets`、`_session_locks`、`_user_turn_seq` 没有统一空闲淘汰机制。`handle_turn` 在取锁前增加用户水位，锁和水位即使在 legacy 模式也会留下；`get_current_snapshot` 还会在没有回合、没有会话锁时创建快照和 working set。

不能把所有 map 都列为同一类泄漏：

- `_turn_cache` 已有 1024 条/3600 秒上限，见 `service.py:1170`、`service.py:1830`。
- `_continued_actions` 已有 2048 条上限，见 `service.py:625`、`service.py:2165`。
- `SessionRuntime` 的活动回合/任务释放以及 admission gate 的等待者计数已有清理，见 `session_runtime.py:362`、`session_runtime.py:471`。
- Harness 请求有 finally 清理，通知 backlog 有 1024 条和时间裁剪，server-request tasks 有完成回调，见 `harness/client.py:17`、`harness/client.py:157`、`harness/client.py:199`、`harness/client.py:265`。这些进程级结构不应交给会话驱逐器随意清空。
- MCP 只读 runner 每次请求构建，内部缓存受调用预算限制，见 `mcp_server/server.py:543`、`mcp_server/tools_readonly.py:432`，不是与 Gateway 会话字典同寿命的全局会话缓存。
- legacy `app/service.py:6637` 的 `_usage_trackers` 是另一条长期保留路径，涉及 usage 查询语义；不应在本批顺手删除或并入 Gateway 回收。

### 2. 原生问答清理与运行时代际还未闭环

`gateway/user_input.py:219` 的 timeout 只删 `_pending`，不删 `_by_rpc`；取消没有相应 finally 清理。`answer` 保留完整记录以接受相同答案重发，但没有独立的轻量有界去重台账。`snapshot` 只过滤回答状态和 TTL，不过滤已取消的 future。

`resolve_native`、`expire_runtime` 虽存在，但在 `app/` 内未找到生产调用点。`gateway/composition.py:151` 创建 broker 时只生成一次 generation，`gateway/service.py:1549` 的 runtime restart 没有更新 broker generation。`harness/client.py:304` 在底层退出时取消原生请求任务，取消路径因此是实际集成边界，不只是手工调用 helper 才存在的情况。

`resolve_native` 忽略传入 generation，RPC 反向索引只按 `str(id)` 编码；接通知前必须明确运行时代际和 ID 类型语义，不能直接把目前未接线的 helper 当成安全接口使用。

另一个现存接线缺口：broker 的 `_on_expired` 支持先中断原生回合，但生产组合层未传入该回调，`app/` 内也未找到后续设置。是否以及如何满足“超时中断并等终态”的既有契约，需要在问答清理批次中核实与覆盖，不能靠会话回收代替。

### 3. 当前投递连接不是连接生命周期

`gateway/session_runtime.py:296` 只记最新连接，并按实例身份摘除，避免旧连接关闭时误摘新连接；这个投递约定应保留。但旧接收器未必立即退出，不能用当前连接表项计数代替全部真实连接的 lease。

额外静态确认：`server.py:1655` 的 `CODEX_DETACH_ON_CLOSE` 默认值是 `0`，native 关闭路径 `server.py:638` 受它控制，随后会关闭 channel 的 sender，却可能保留 runtime 当前连接引用。compat 的 `server.py:1626` 则始终按 channel 身份摘除。此处确认的是**源码默认行为**，未检查在线进程实际环境，不断言在线一定使用默认值。

原注释记录了此前开启开关后出现的测试抖动，因此不建议直接翻转默认值“修内存”。生命周期登记要独立于投递表；关闭连接释放 owner、关闭后终态仍先入事件存储、重连转投最新 channel，应分别回归后再裁定开关行为。

### 4. “权威快照”接口具有业务回落，不适合驱逐判定

`gateway/service.py:1328` 的刷新失败只告警；`service.py:1597` 的 `get_authoritative_snapshot` 随后可能返回旧缓存。这是目前动作路径的既有退化策略，不在本轮改动，但若回收器据此认定“没有待确认卡”，会把查询失败误判为空闲。

Java `ConversationSnapshotService.java:142` 从 `getCurrent` 读取 active pending，投影到 `activeProposal`。回收检查应区分 **有待确认 / 本次成功查询确认无待确认 / 未知**。仅第二种允许继续判定；异常、结构/会话身份不匹配、回落旧缓存都属于未知并保留。不能为了回收调用 pending resolve/cancel。

## 持有者矩阵

| 持有者 | 当前入口/引用 | 必须覆盖的生命周期 |
| --- | --- | --- |
| WebSocket 接收器与 sender | `server.py:613`、`server.py:1604`；多处 replay/attach | 票据确定可信 key 后、第一次异步重放前登记；关闭时按连接 token 释放，不以是否仍是最新连接为准 |
| admission 与排队回合 | `session_runtime.py:362`、`session_runtime.py:431` | 等 admission/会话锁之前即登记，拒绝、异常、取消均释放 |
| Gateway 回合与状态读取 | `service.py:1573`、`service.py:1597`、`service.py:1781` | loader、binding 恢复、工作集读写及锁等待期间均持有 |
| 动作与收尾 | `session_runtime.py:247`、`server.py:1394`、`service.py:1644` | 创建 detached task 前登记；有无 requestId 均计入；覆盖 Java 调用、结果入流及可能续接 |
| 原生问答 | `user_input.py:165`，scope 由 `service.py:1238` 反查 `_threads` | 登记到原生请求真正结束；回答后短期去重不再持有整个活跃请求 |
| 自动续接 | `server.py:890`、`server.py:1422`；`service.py:1849`、`service.py:2008` | 从水位取样到终态和续接判定连续持有，不允许中间释放后再取回新 entry |
| 后端待确认业务卡 | Java active pending | 新鲜权威查询确认为空之前保留；查询未知也保留 |

任务 owner 要在 `create_task` 前登记，且任务在第一次执行前就取消时也必须释放；只把 finally 写进尚未启动的协程不够。连接的 replay 和消息循环可能重复 attach，同一连接/同一 key 的登记需幂等，切换 key 需有明确转移语义。

## 方案比较

| 路线 | 评价 |
| --- | --- |
| 给各字典分别加 TTL/LRU，靠 lock.locked/active/channel 判断 | 改动少但不安全；锁等待者、无 ID 动作、多连接、原生卡片、水位 ABA 都无法被完整覆盖，否决 |
| 单 worker 内共享会话生命周期协调器 | **推荐**；按 `SessionKey(tenant, session)` 管理同一 entry 的 generation、锁、水位、owner token、空闲时间与回收预检；可分批接入，不必同时重写所有业务状态模型 |
| 分布式 session ownership + fencing | 多 worker 最终需要，但涉及外部协议、故障接管与写事务屏障；本批不实现，也不以进程内锁冒充分布式安全 |

推荐路线的必要约束，仍待正式设计批准：

- 所有访问先取得 entry 的 lease，再等锁/loader；不能仅检查锁的 locked 状态。沿用 admission gate 先计数后等待的思路。
- entry 实例/generation 与用户水位一起识别续接基线，或用完整连续 lease 保证水位不会在途中被回收重置。不能单独删除 `_user_turn_seq` 后让旧整数与新会话巧合相等。
- 空闲时间从最后一个真实 owner 释放开始；回收扫描本身不刷新活跃时间，否则会永远延长自己的 TTL。
- 扫描先选择候选，执行不吃缓存的待确认查询；await 返回后再次比较 entry 身份、generation、活动修订号、owner 数及空闲时刻。预检预约和用户 owner 分开；新活动可以正常进入并使本次驱逐放弃。
- 单 event loop 内最终复核到删除不再 await；两个扫描不得同时处理同一候选。查询失败保留并退避，避免后端故障时扫描风暴。
- 此查询与其他进程的 Java 写入不是原子操作；安全边界仍是“只删除可恢复的内存，不删除业务权威”。待确认状态在重入时必须从 Java 恢复，不能把内存是否存在当成业务事实。
- 删除目标仅为确认可重建的 `_threads`/snapshot/working set/lock/watermark 及协调器空闲 entry。未关闭的投递对象和后台任务不是可丢缓存，必须先完成各自释放。
- 不删除本地 `ThreadBindingRegistry`、Codex rollout、可信产物 SQLite 台账、Java pending/规划状态、Redis 请求回执/事件流。也不提前删除有界回合缓存或续接去重台账，避免缩短现有幂等窗口。
- 重入继续走 `ThreadRecovery` 和持久化 binding 查找，正常情况 resume 原 thread。后端不可用不可假装新会话；既有 rollout 丢失等明确告警的重建策略保留，不增加“缓存没了就静默新建”。
- 活跃连接、动作、澄清和待确认业务卡可长期保留，所以容量只能是**空闲缓存目标**，不是全进程内存的硬上限；不能强驱逐活跃会话满足指标。

可讨论的初始参数是 idle TTL 30 分钟、空闲缓存目标 1024，配置受校验且可关闭。它们只是建议，不是当前实现、产品需求或已经批准的默认值。首期仍限定单 worker。

## 建议分批顺序

1. **问答生命周期小批次**：对称清理 pending/反向索引；取消后不展示不可答卡；将回答去重改为独立有界记录；核实退出/重启/超时接线及 generation，保留同答案 accepted、异答案 conflict、跨会话拒绝。先做 fake harness 与内存测试，不调用真实模型。
2. **owner/lease 接入批次**：协调器、排队任务、所有连接、snapshot/binding、detached 与续接连续持有。先验证引用登记，不开启驱逐；单独查清 native 连接摘除开关的抖动与投递语义。
3. **空闲回收批次**：新鲜 pending 三态检查、TTL/LRU、异步预检二次复核、原 thread 恢复和可观测计数。离线验证后再决定何时打开策略，不能借本轮调查直接改在线配置。

正式验收至少覆盖：等待锁时扫描；无 requestId 的 detached；新旧连接交叠；task 未启动即取消；超时/取消/退出的双索引清理；回答去重与错租户；跨代重复 RPC ID；水位取样后新用户输入；查询返回前会话重新活跃；pending 有/无/未知；回收后 resume 原 thread；不同租户同 sessionId；压力下空闲 entry 达到目标而活跃 entry 不强驱逐；事件与回执在回收后仍可补发和查重。

并发测试用 Event 和 fake clock 控制交错，不靠随机 sleep。会话回收的通过标准不是简单的“字典变小”，而是所有安全引用均受保护、权威和幂等不受损、重入可恢复。

## 本轮交付判断

本轮可交付的是调查记录与 10 项离线观察，不是问题已经修复的结论。没有运行全套回归，也没有把此前测试结果当成本轮结果。Web 的生产构建和离线浏览器验收已在上一轮记录，不重复列为未完成项。

建议下一步先批准并推进第 1 批，再逐步接 owner/lease 与空闲回收；不要把三批揉成一次未经验证的大改。本轮不执行 git add/commit，待批准边界与后续验证后再按职责评估提交。
