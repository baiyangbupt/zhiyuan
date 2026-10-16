# 会话引用登记与释放设计

日期：2026-10-16。代码基线：`796d691`。

## 状态与边界

用户已批准第 2 批的方向及代码审查后直接推进：单 worker 内共享会话生命周期协调器，覆盖排队、连接、后台动作、续接、读取和原生问答，先登记真实引用，不启用驱逐。2026-10-16 已核对实际调用边界，按本契约开始测试驱动实现。

沿用当前分支和工作区，不创建 worktree，不派生代理。文档及后续实现先保留在工作区，提交另行确认。不改动既有前端产物和此前未提交的调查/验收记录。

## 目标与非目标

本批目标是使所有可能跨越 `await`、任务排队或连接交替而访问会话内存的路径，都持有可追踪且对称释放的引用。引用必须来自已经验证的 `SessionKey(tenant_id, session_id)`，不能由模型自报身份授权。

不在本批实现：

- TTL/LRU、后台扫描、容量阈值、删除会话缓存或提前缩短幂等窗口。
- Java pending 的新鲜三态查询、业务 pending 的取消/消费、绑定/产物/事件的删除。
- 跨进程 ownership、分布式锁、故障接管或 fencing；本协调器只适用于一个事件循环内的单 worker。
- 改变现有 `CODEX_DETACH_ON_CLOSE`、投递连接选择、用户停止、动作事务或自动续接优先级。
- 部署、重启既有服务、真实模型调用、共享 Redis/Java/数据库写入。

本批不是内存回收完成的承诺。已有的会话缓存仍按原寿命保留；协调器的轻量空闲元数据也暂不驱逐。第 3 批实施前，不得依据引用数为零直接删除缓存。

## 路线选择

1. 各组件各自计数：接入改动较少，但无法可靠覆盖跨组件交接与所有连接，容易出现重复释放或短暂空窗，不采用。
2. 共享 `SessionLifecycle`：每个可信会话使用同一个 entry，通过独立 lease 记录持有者。业务锁、水位、回合和缓存仍留在原组件。本批采用这一最小增量方案。
3. 把锁、水位、缓存和分布式所有权同时迁入新会话对象：长期边界更集中，但扩大重构和故障面；本批不采用，不借引用登记改写业务模型。

## 一、协调器契约

新增 `app/gateway/session_lifecycle.py`，仅负责同步引用登记、释放和只读诊断，不调用业务组件，不等待 I/O，不创建扫描任务。

公开接口：

```python
class SessionLifecycle:
    def acquire(self, key: SessionKey, owner_kind: str) -> SessionLease: ...
    def inspect(self, key: SessionKey) -> SessionOwnershipSnapshot | None: ...

class SessionLease:
    def close(self) -> None: ...
    def __enter__(self) -> SessionLease: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...
```

`SessionLease` 表示单个持有者，不是时间到期的租约，也不具有互斥或重入锁语义。业务仍使用现有 admission gate 和会话锁。

每个 entry 保存：可信 key、不可复用的会话 entry generation、活动修订号、owner token 到固定类别的映射、最后释放后的 `idle_since`。不保存原始问题、答案、用户内容、Task 或 channel 对象。固定类别为 `admission`、`turn`、`connection`、`gateway_read`、`action`、`continuation`、`native_request` 和 `publish`。

不变量：

- `acquire` 在当前同步片段完成，返回不可转让给其他 key 的唯一 token；有效 acquire/release 都增加活动修订号。
- 非零引用时 `idle_since` 为 `None`；最后一个引用释放时才用可注入 monotonic clock 记录空闲起点。中间持有者释放不能使会话看起来空闲。
- `close` 幂等；重复 close 不改变计数、活动修订号或空闲时间。释放同时核对原 registry、entry 实例/generation 和 token，不允许旧句柄影响其他 entry。
- `inspect` 返回不可变快照，包含 generation、revision、按类别计数和空闲时间，不暴露 token，不创建 entry，不更新活动时间。
- App Server 重启不轮换 session entry generation，也不清空所有会话引用。只由真实结束的 native/turn 持有者释放，后台 Java 动作不因模型进程重启而失去保护。
- 本批不暴露 retire、evict、reset 或强制清空引用的生产接口，不为测试添加绕过保护的入口。

## 二、装配与兼容

`build_gateway_runtime` 创建唯一的协调器，注入 `GatewayService` 及原生请求生命周期边界。`server.py` 构造 `SessionRuntime` 时显式传入 `gateway.lifecycle`。生产必须验证 Gateway、Runtime 和原生请求边界使用同一实例，不能悄悄各建一份。

构造器新增可选的 `lifecycle` 参数，保持现有调用兼容。独立构造且没有运行时的组件可创建本地实例；同时传入真实 `session_runtime` 和 `lifecycle` 时必须同源，否则启动失败。测试 fake 不参与生产一致性承诺。

不新建模块级共享 registry；既有 broker 发布间接接线暂不重构。协调器寿命归本次 Gateway 应用实例所有。

## 三、持有者矩阵

| 边界 | 获取时刻 | 释放时刻 | 必须保留的语义 |
| --- | --- | --- | --- |
| `SessionRuntime.submit` admission | 首次等待 admission gate 或事件存储之前 | 接受/拒绝/重复/冲突/异常/取消完成后 | 排队者也算持有者 |
| 接受的回合 Task | `create_task` 之前 | Task 完成回调，晚于 work 和请求状态收尾 | 释放不依赖协程已经启动 |
| detached 动作 Task | `detach_work` 创建 Task 之前 | Java 结果处理、终态入流与续接判定结束后 | 无 requestId 也登记，不占 active turn 位 |
| WS 接收器和 sender | 票据确认可信 key 后、首次 replay/等待之前 | handler 和 channel sender 的关闭收尾完成后 | 每条真实连接独立登记 |
| Gateway snapshot/binding/回合/控制调用 | 读取、加载或等待锁之前 | 最外层调用 finally | 私有调用由外层保护，公开入口独立可用 |
| 动作执行与刷新 | 权威状态读取/执行前 | 动作结果及刷新返回后 | 不能以刷新失败抹掉已生效结果 |
| 自动续接 | 用户水位取样之前已有外层 owner | 结果入流及全部续接判定结束后 | 从取样到判定不出现零引用空窗 |
| 原生问答 RPC | 验证方法、运行代际与 thread 绑定后、创建 handler Task 前 | handler 的结果/错误写回或退出取消收尾结束后 | 回答后不能在 RPC 写回前释放 |
| 独立 publish | 读取投递 channel 和等待事件 append 前 | append/emit 返回或失败后 | 入流失败的既有降级语义不变 |

### Task 的取消和交接

所有后台任务使用工厂形式创建 work，先取得 lease，再创建协程与 Task，并在同一个无 await 片段内登记 done callback。Task 创建失败需关闭尚未启动的协程并释放 lease，不能产生 never-awaited 警告。

done callback 是 Task owner 的最终释放点；即便 Task 在第一次执行前取消也能收尾。不得仅在任务协程内部写 finally。登记 owner 的同步路径失败时同样对称释放，不强行修改原任务的业务异常。

用户回合把工作转交 detached 动作时，先取得动作 lease，再让原回合退出；原回合的请求状态收尾和新动作可短暂重叠持有，不要求任何时刻引用数恰好为一。既有 `_pending_requests`、requestId 去重和 `DeferredRequest` 语义不变。

应用关闭时不因统一清零方便而取消或放弃已出站动作；沿用既有任务取消政策，引用随真实任务结束释放。不为本批新增动作强制超时或事务撤销。

## 四、连接与投递必须分开

native 和 compat handler 从票据取得可信 key 后登记 connection owner。首次消息可能延后，不能等到 `runtime.submit` 才登记。没有可信 key 的连接不登记任意客户端自报会话，也不得读取该会话的状态。

同一 channel 重复绑定同一个 key 幂等；不允许在未验证身份时把现有 owner 转给另一个 key。一个会话的旧、新两个真实连接同时存在时，必须各有一个 owner。

现有 `_channels` 仍只保留最新投递对象，detach 仍按对象身份判断。新增连接释放路径不得顺手改变 native 的 `_DETACH_ON_CLOSE` 行为；释放真实连接 owner 和是否摘除最新投递引用是两回事。

native 当前把 `_replay_on_connect` 放在 try/finally 外。接入时将 replay、sender 启动和 receive loop 放进同一释放范围；replay 抛错或被取消也必须关闭已创建的 channel 并释放 owner。handler 返回前，connection owner 必须持续覆盖 `channel.close()` 的 await，关闭异常也必须通过 finally 释放。

当开关仍保留关闭后的投递对象时，owner 为零也**不代表所有引用均已删除**。本批只准确记录真实连接，不把旧路由引用伪装成活连接。后续回收必须另行验证关闭投递对象的处理和事件落流语义。

## 五、Gateway 与续接

覆盖可独立调用的 `handle_turn`、snapshot 读取、`execute_action` / `execute_action_and_refresh`、两个 continuation 入口及 interrupt/steer。进入方法后先按服务端可信 key 取得 lease，再读取字典、增加用户水位、等待 loader 或锁。

不改现有锁键、加锁顺序、水位递增位置和续接 once-key。嵌套公开调用可各持有一个 lease，引用计数不是请求数，也不据此上报模型并发量。

正常用户回合的 Runtime Task owner 必须覆盖整个 work：包括 Gateway 返回、水位取样、终态入流以及后续 action/preview 续接。detached 动作的 owner 覆盖相同链路。Gateway 方法本身的 lease 不能替代这个外层保护。

直接调用 continuation 时，该方法独立持有 lease。传入的整数水位仍按当前契约解释；本批不删除水位，不引入 ABA 风险，也不宣称整数水位足以支持未来驱逐。第 3 批必须继续依赖连续外层引用，或将外部基线升级为 entry identity/generation 加水位的完整标记。

snapshot 读取失败仍按原策略处理。本批不把 `get_authoritative_snapshot` 的缓存回落当作新鲜权威查询，不产生“无 pending、可驱逐”的判定。

## 六、原生问答与完整 RPC 边界

仅在 Broker 内持有到 `_await_answer` 返回不够：成功答案已从 Broker 释放，但 Client 此时尚未完成原 RPC 的 `_write/drain`。

在 `AppServerClient` 提供可选的同步 request-lease factory，经 Harness 设置入口由 composition 注入。通用 Client 只依赖可关闭的 lease 协议，不导入 Gateway 类。factory 在 reader 创建 server-request Task 前执行，以同步可信 thread 查表取得 key；仅对已支持的问答方法登记，不改变未知 RPC 的原有行为。

获取失败必须以原 RPC ID 返回现有错误形状，不静默回空答案；不从模型元数据猜 key。factory 本身不能 await。旧代际请求在获取前和 handler 执行前都要复核，不得把旧任务绑定到新代际会话状态。

lease 在所属 protocol Task 的 done callback 释放，覆盖 handler、过期 interrupt/terminal 等待、result/error 写回和取消。Task 尚未启动就取消、任务创建失败、进程退出、resolved 通知、回包失败都应释放。

Broker 原有有界回答回执、完整记录清理及运行时代际逻辑保持不变；短期回答回执不另持有活跃 lease。生产 fake-stdio 测试验证真实组合接线，不能仅手工调用协调器冒充接入完成。

## 七、测试与验收

使用 fake clock、`asyncio.Event` 和 fixture 自建子进程/回环监听，不靠随机 sleep，不访问现有服务。沿用 Python 3.10+，不新增依赖或格式化工具；代码修改前先补可复现的失败测试。

必须覆盖：

1. 同租户会话嵌套 owner、不同租户同 sessionId、重复 close、快照只读以及最后释放才计空闲。
2. 等待 admission / 会话锁时引用非零，重复/冲突/拒绝/取消不泄漏；await 返回前始终保护读取到的 entry。
3. accepted/detached Task 创建前已登记，首次执行前取消仍归零，创建失败不泄漏或留下协程告警。
4. 没有 requestId 的 detached 动作被覆盖；转后台、结果入流和续接链路之间不出现引用为零的空窗。
5. 两条连接交叠时计数为二，重复 attach 不重复登记；旧连接关闭只释放自身，最新连接仍可投递。
6. native/compat 在首次消息前、replay 阻塞、replay 异常和 sender 关闭期间均按上述契约持有/释放；detach 开关两种状态都覆盖且原值不改。
7. snapshot/binding/动作 loader 异常、取消和刷新失败后引用对称，动作已生效的事件和返回语义不被改写。
8. 水位取样后插入新用户回合，续接按原逻辑让路；原任务在终态入流/续接判断前始终持有。
9. 原生答案在 `_write/drain` 被 Event 阻塞时仍有 native owner；取消、超时、resolved、退出与重启后只释放对应 Task，不抹除其他会话/后台动作 owner。
10. 组合层证明各组件共享同一 coordinator；错配启动失败；单组件测试默认构造兼容。观察 `inspect` 不制造活动。
11. 既有 admission、请求幂等、问答清理、动作/preview 续接、跨租户和 thread recovery 回归通过。缺固定二进制或测试 Redis 的 skip 单独报告，不算通过。

先跑本批聚焦测试，再扩大到 `tests/unit tests/integration -m 'not e2e'`；执行前检查 fixture 隔离。沙箱禁止测试 socket 时走授权重跑，不降低断言或连接线上补测。最终记录实际命令、通过/跳过数量和未覆盖的真实协议边界。

## 八、文件范围与交付判定

预计新增协调器及聚焦测试；修改 `gateway/session_runtime.py`、`gateway/service.py`、`gateway/composition.py`、`harness/client.py`、`harness/codex.py` 和 `server.py`，按入口扩展现有组合/连接/续接测试。不要以本批名义修改其他历史告警或 frontend 文件。

本批完成条件是持有者矩阵中的实际接线和取消边界均有行为测试、既有事件与事务语义保留，并通过本地差异复审。引用总数为零只是诊断事实，不是可回收授权。

后续第 3 批另行设计：新鲜 pending 三态预检、活动修订号二次复核、空闲 TTL/容量、关闭路由处理、删除时无 await 的原子边界，以及从持久 binding 恢复原 thread。没有完成这些条件前，不增加任何自动会话删除开关。

## 设计自检

- [x] 区分 session entry generation 与 App Server runtime generation。
- [x] 区分真实连接 owner 与最新投递对象，明确保留现有 detach 开关。
- [x] 覆盖 Task 首次执行前取消、创建失败与 detached 交接。
- [x] 连续保护水位取样、终态入流和续接判定，而不只包 Gateway 方法。
- [x] 将 native 引用延长到完整 RPC Task 结束，不以 Broker 回执代替。
- [x] 明确本批既不驱逐也不声称已解决内存增长，避免把计数误作业务权威。
- [x] 用户授权直接代码 review，确认无阻塞后已编写实现计划并推进测试先行的实现。
