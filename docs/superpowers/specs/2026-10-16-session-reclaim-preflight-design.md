# 会话回收只读预检设计

日期：2026-10-16；基线：`eb63dbf`。用户已同意继续按前批建议推进；本批仅实现 pending 新鲜性与安全回收条件预检，不实现或启用驱逐。

## 范围与代码审查

这是已批准回收路线中的前置边界，不是 TTL/LRU 策略。保留现有工作区，不创建分支、不派生代理；不改 Java、不重启服务、不调用真实模型或共享数据库、不增加线上开关。本批变更先留工作区，提交另行确认。

审查源码确认：

- `ConversationSnapshotService.fillActiveProposal` 只投影 active，applying 被省略；即使不吃缓存，空 activeProposal 也不是 pending 可安全回收的证据。
- Java `GET /inner/chat/{tenantId}/session/pending` 直接按租户/会话读取专用资源；正常无记录是 code=0、data=null，有记录带 chatSessionId/status/revision/pendingId。active 和 applying 均必须保留。
- PendingConfirmationBizService 的已知终态为 applied/cancelled/expired。未知新状态或结构不完整应保留，而非猜测已完成。
- Python 通用 HTTP GET 在非 200 时仍返回 JSON，且异常返回字典。预检必须同时验证 HTTP 成功与业务 envelope，不能把错误字典或 code=False 当作成功。

路线比较：复用 Gateway 权威快照会漏 applying 且可能回落旧缓存，不采用；新增 Java 端点或跨进程锁扩大范围，不采用；采用专用 pending GET 的严格只读适配与单 worker 内异步前后复核。

## 三态与传输

新模块 `app/gateway/session_reclaim.py` 定义不可变 PendingObservation 与固定三态 present/absent/unknown。

- 每次检查必须调用 loader，不读 Gateway 缓存、不缓存三态结果。
- 只有 HTTP 200、整型 code=0、显式存在 data 字段且没有失败标记的响应可继续解析；null 确认 absent。
- 非空 data 必须含匹配请求的 chatSessionId、非空 pendingId、正整型 revision、已知 status。可选 tenantId 若存在也必须匹配；缺失或错配为 unknown。
- active/applying 为 present；applied/cancelled/expired 为 absent；未知状态、错误、超时和畸形响应为 unknown。
- null 响应无法回显身份，可信边界是服务端构造的租户路径与会话参数；不假装已完成 Java 端跨进程原子校验。
- `internal_client.load_pending_for_reclaim` 仅 GET，校验生产所需的正整数租户/会话 ID。为 HttpClient.get 添加可选 require_success，默认关闭以保持旧调用行为；本入口强制开启。
- 诊断结果不携带完整 pending/学生信息，只含可信 key、三态和固定原因码。

## 预检状态机

`SessionReclaimPreflight(lifecycle, pending_loader, route_retained)`；`await check(key, *, idle_seconds, timeout_seconds)`。idle 和超时由调用者显式提供且必须正数、有限，不暗中设定回收策略。

1. 仅 inspect 已有 entry；无 entry 不创建，无 owner 且 idle 达阈值才候选。检查不 acquire/release owner、不刷新 revision 或空闲时间。
2. 一个 key 只允许一个异步 pending 预检；预约单独保存在检查器，不能阻挡用户 acquire。重入返回 check_in_progress；不同租户同号不互相阻挡。
3. 有残留投递路由或运行时不可确认则阻止本次预检；不自动 detach、不改变 CODEX_DETACH_ON_CLOSE。
4. 带显式超时调用新鲜 loader，查询期间允许真实活动正常进入。
5. 返回后同步复核 entry key/generation/revision/owner/idle_since 以及路由；即使活动已结束又归零，revision 变化也放弃本次结果。
6. 仅在本次 pending=absent、原 entry 完全未改变且无路由时返回 candidate；其余返回 blocked 和固定原因。异常/超时 fail closed；调用者取消原样抛出，finally 释放检查预约。

candidate **不是删除许可或可跨 await 使用的票据**。本批不暴露删除/reset/扫描接口、不修改缓存和幂等台账。未来必须在无 await 的最终边界重新验证 stamp，并单独完成恢复与回收设计；不能保存 candidate 后异步直接删除。

composition 将预检器挂到 Gateway 应用实例，使用同一 lifecycle 和真实 Runtime 的路由查表；运行时尚未装配时返回未知并阻止。没有自动调用者、诊断 HTTP 端点、扫描任务或新的生产网络请求；只有显式调用 check 才查询后端。没有扫描，因此本批不引入后台重试或退避任务。

## 验收

- 三态覆盖 null、所有已知状态、未知/缺字段/错租户/错会话/假成功/错误结构；对真实 fixture HTTP 验证非 200 不能借 code=0 绕过。
- Event 控制查询期间重新活跃、活跃后又归零、两检查重叠、取消和超时；假时钟验证 idle 不被检查刷新；不靠随机 sleep。
- applying 不以过期 claim 或空快照放行；不调用 pending resolve/cancel，不清理路由、不删除任何会话缓存。
- production composition 接线可实际调用，证明未走快照缓存；Runtime 未装配及保留关闭路由时 fail closed。
- 聚焦后执行离线 unit/integration 非 e2e 全量，专用 Redis/真实二进制 skip 不计通过。
