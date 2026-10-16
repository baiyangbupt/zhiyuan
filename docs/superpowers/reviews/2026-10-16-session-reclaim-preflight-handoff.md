# 会话回收只读预检：实现与审查交接

日期：2026-10-16。基线：`eb63dbf`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 结论与边界

上一批引用登记已独立提交为 `eb63dbf`。本批实现新鲜 pending 三态与回收前只读复核；用户随后同意独立提交，提交状态以 git log 为准，未推送、未部署。代码由当前执行者直接审查，不声称经过独立 reviewer。

**没有启用任何会话删除、TTL/LRU、扫描或自动回收。** 不修改 Java、pending 消费/状态流转、缓存、路由或幂等窗口；不改变 `CODEX_DETACH_ON_CLOSE`，不加线上开关，不重启业务服务。

## 审查发现与修复

| 风险 | 本批处置 |
| --- | --- |
| Java 快照只投影 active，空 activeProposal 隐藏 applying | 从专用 pending GET 读取，每次 check 发起新查询，完全不复用 Gateway 快照 |
| 通用 GET 对非 200 仍透传 JSON，错误体可能伪装 code=0/data=null | 新 loader 显式 require_success；非 200 统一失败，旧调用行为不变 |
| code=False、缺失 data、身份错配、未知状态可能被当作无 pending | 严格 envelope、必填字段、请求身份与类型校验；无法确认一律 unknown |
| pending 查询期间会话重新活跃，甚至活跃后立即归零 | await 后比较 key/generation/revision/owners/idle_since；任一变化均阻止 |
| 所有引用归零后仍保留已关闭投递路由 | 查询前后查真实 Runtime 的路由；保留路由或 Runtime 不可确认均阻止，不自动 detach |
| 同会话重入检查重复查询，或检查本身刷新空闲时钟 | 独立 in-flight 预约，不获取 owner、不创建 lifecycle entry；finally 释放预约 |

## 实现契约

- `session_reclaim.py` 提供不可变三态 observation 和诊断结果；不保留 pendingId、claimToken、学生数据、原始异常内容或完整后端 payload。
- HTTP 200 且实际整型 code=0、显式 data、没有失败标记才可分类。null 为 absent；非空数据必须匹配会话及可选租户，具有非空 pendingId、正整型 revision 和已知状态。
- active/applying 为 present；applied/cancelled/expired 为 absent；其他状态或不完整响应为 unknown。过期 claim 不放行 applying。
- `load_pending_for_reclaim` 只发 GET；仅此新入口要求规范正 Long ID（最大 9223372036854775807），非法 ID 在联网前拒绝。既有 pending helper 不改。
- `SessionReclaimPreflight.check` 要求调用方显式指定正有限 idle_seconds/timeout_seconds；仅 inspect 已有 entry，不记录策略默认值，不缓存 pending 观察。
- 同 key 预约冲突直接 blocked；其他租户和真实活动不等待预约。取消原样传播；超时/异常返回 unknown 并清理预约。
- composition 在 Gateway 实例挂接 `reclaim_preflight`，共享现有 lifecycle，惰性查该 Gateway 的真实 Runtime。不新增自动调用者、HTTP 诊断入口或定时任务。

**candidate 只是本次诊断，不是删除许可，不能保存后跨 await/进程拿来删除。** 未来回收还需在无 await 的最终边界重新验证 stamp，并单独评审恢复、清理顺序、幂等窗口和多进程协调。

## 验证记录

- 三态、异步预检与 composition 的首次执行分别因缺失模块、类和实例属性失败，随后最小实现通过。
- 严格传输测试在本机临时 HTTP fixture 观察真实请求与响应；HTTP 201/重定向/鉴权失败/限流/服务失败均不能伪装 absence，旧 GET 保留原行为。
- Event 控制 activity/revision、重入、跨租户、取消与路由交错；假时钟验证检查不刷新 idle。超时用受控等待的 fixture loader，不接真实服务。
- 聚焦回归：**192 passed、1 skipped，1.10 秒**。skip 为未安装的固定 Codex App Server 二进制。
- 最终离线全量：**2865 passed、21 skipped、33 deselected、23 warnings，65.32 秒，退出码 0**。相对基线增加 134 项通过。
- 用户同意提交后重新运行同一离线全量：**2865 passed、21 skipped、33 deselected、23 warnings，65.24 秒，退出码 0**；日志 `/tmp/zhiyuan-session-reclaim-precommit.log`。
- 21 个 skip 为 19 个需要专用 `CODEX_TEST_REDIS_URL` 的测试和 2 个缺少固定 Codex 二进制的测试，不计为通过。23 个 warning 为原有 Pydantic usage 弃用及同步测试 asyncio 标记，与本批无关。
- 本批 diff 直接审查未发现阻塞项；现有文件 `git diff --check` 及新文件 `git diff --no-index --check` 均无空白错误。没有执行真实模型、共享 Redis/数据库或生产端到端验证。

离线全量从 `zhiyuan-agent` 执行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  timeout --signal=TERM --kill-after=10s 300s \
  .venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
  tests/unit tests/integration -m 'not e2e' -q -rs \
  -o faulthandler_timeout=30
```

测试入口只允许本次 fixture 创建的 loopback listener，不调用现有业务服务、共享 Redis/数据库或真实模型。全量日志：`/tmp/zhiyuan-session-reclaim-preflight-full.log`。

## 剩余风险与下一批

- 内存容量问题尚未解决：lifecycle entry、会话快照、thread/recovery 状态、Runtime 台账等仍保留。本批刻意不以不完整恢复能力换取表面内存下降。
- pending 与 ownership 的判断仅代表本 worker 此刻；其他 worker 或检查后的新活动仍可发生，不能据此推导分布式空闲。
- 保留的关闭路由会持续阻止 candidate；应先单独明确重连、投递恢复及安全 detach 契约，而非在预检里偷偷清除。
- 下一步先评审会话状态恢复和逐类清理清单，验证重连、重复请求/动作、确认链续接不受影响，再考虑受控驱逐；不要直接接入删除任务。

既有前端构建产物与前序调查文档不纳入本批修改或提交。
