# 原生问答生命周期修复 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, task-by-task. 本次没有获得并行代理授权，不派生代理，不新建分支或 worktree。

**Goal:** 原生问答结束后对称释放记录/索引，重复答案采用有界轻量回执，退出和重启隔离运行时代际，超时在原回合中断并观察终态后才回包。

**Architecture:** 保留 Broker、AppServerClient、Harness 与 composition 的既有分层。Client 提供同步生命周期/通知回调和不消费通知的临时 observer；Broker 管理问答和回答回执；composition 负责接线，Harness 负责 interrupt/terminal 协议。不会实现会话 lease 或 TTL 驱逐。

**Tech Stack:** Python 3.10+、asyncio、pytest、现有 fake app-server。

**Spec:** 用户在 `2026-10-16-session-lifecycle-discovery.md` 的第 1 批建议后明确同意推进。采用其中“问答清理与代际隔离”的边界，另外两批不在本次实现范围。

## Global Constraints

- 当前分支和工作区直接推进，保留用户原有前端产物和上轮调查记录。
- 不调用真实模型、不操作共享数据库、不重启在线服务、不改在线环境变量。
- 不翻转 `CODEX_DETACH_ON_CLOSE`，不实现会话回收、分布式 ownership 或 fencing。
- 先看到新测试失败，再修改对应应用代码；只用 fake clock、Event 和测试子进程验证。
- 提交需另行评估，计划不自动执行 git add/commit/push。

## Task 1: Broker 对称清理与回答回执

**Files:** 修改 `zhiyuan-agent/app/gateway/user_input.py`；新增 `zhiyuan-agent/tests/unit/test_user_input_lifecycle.py`。

**Interfaces:** 保留 `answer(key, request_id, response)` 与 `snapshot(key)`；新增可注入 `clock`、`answer_cache_max_entries=1024`、`answer_cache_ttl_seconds=600`。`start_runtime(generation)` 清理旧代际；`handle_notification(generation, notification)` 只处理原生 resolved 通知。

- [x] 添加失败回归：timeout/cancel/emitter failure 清理两份索引；答后完整记录立即释放；回执相同答案 accepted、异答案 conflict、错会话拒绝；回执 TTL/容量有界。
- [x] 运行：`PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/zhiyuan_hardening_pytest.py tests/unit/test_user_input_lifecycle.py -q`，确认失败来自当前保留行为或缺失接口。
- [x] 实现轻量 `_AnswerReceipt` 与 OrderedDict；按 `(generation, RPC ID 类型, RPC ID)` 关联索引；按 record 身份对称释放，避免旧 finally 删除后来复用 ID 的记录。
- [x] 添加并验证旧 generation 不可 resolve 新请求、int/string ID 不混淆、重复活动 ID 拒绝、配置非法值拒绝、可信 scope resolver 查不到时不回落模型参数。

代表性验收：

```python
await broker.answer(key, record.ui_request_id, answer)
assert broker._pending == {}
assert broker._by_rpc == {}
assert await broker.answer(key, record.ui_request_id, answer) == {"status": "accepted"}
```

## Task 2: Client 生命周期与迟到回包隔离

**Files:** 修改 `zhiyuan-agent/app/harness/client.py`；新增 `zhiyuan-agent/tests/unit/test_user_input_runtime_lifecycle.py`。

**Interfaces:** `set_runtime_handlers(on_started=..., on_exited=..., on_notification=...)`；只读使用 `runtime_generation`。`observe_notification(predicate)` 是同步 context manager，yield Future，不从 collector/backlog 取走通知。

- [x] 添加失败回归：fake 子进程 start/exit/restart 各触发正确 generation 回调；原生 pending 随退出失效；迟到旧代际 handler 不向新进程写 result 或 error。
- [x] 添加失败回归：observer 与原有消费者同时获得匹配终态；取消/退出后 observer 清理；旧 reader 不处理新进程状态。
- [x] 运行上述新测试，确认红灯，再实现同步回调、每次 start 的新 token、reader/handler 捕获 token 与写前复核。
- [x] reader finally 使等待者失败并取消/等待原生请求任务，确保 Broker finally 完成；回调不改变既有 JSON-RPC result/error 形状。

代表性验收：

```python
with client.observe_notification(predicate) as observed:
    client._route_notification(terminal)
    assert await observed == terminal
assert await client.wait_for_notification(predicate) == terminal
```

## Task 3: 超时终态观察与组合层接线

**Files:** 修改 `zhiyuan-agent/app/harness/codex.py`、`zhiyuan-agent/app/gateway/composition.py`；扩展上述测试与 `zhiyuan-agent/tests/integration/test_gateway_composition.py`。

**Interfaces:** `CodexAppServerHarness.interrupt_turn_and_wait(thread_id, turn_id)` 注册 observer 后发送 interrupt，再限时等待同 thread/turn 的 terminal。Broker record 分别保存原生 thread/turn 与 UI turn，不混用编号。

- [x] 添加失败回归：过期回调等待 interrupt 和 terminal；collector 仍能收到同一终态；中断失败传播，不静默当成正常答案。
- [x] 添加组合层失败回归：使用真实 Harness + fake app-server，验证 Broker generation 与 Client 一致，退出/重启/resolved 真正接通，过期回调不为空。
- [x] 实现接线。缺失可验证的 native thread/turn 时 fail closed，不猜“唯一会话”；不改变正常用户停止和 Java 事务语义。
- [x] 验证同答案重发、form/choice 原 RPC ID 回包、跨会话拒绝等旧契约仍通过。

## Task 4: 验证与交接

**Files:** 新增 `docs/superpowers/reviews/2026-10-16-user-input-lifecycle-handoff.md`，更新本计划状态。

- [x] 运行聚焦 Broker/Client/Harness/组合层/恢复/WS 问答回归，然后按风险扩大离线单元与集成测试；排除真实模型 e2e。
- [x] 复审代际切换、索引 identity guard、去重窗口、取消与 emitter 中断、通知不被抢走、退出收尾，确认无额外会话驱逐。
- [x] `git diff --check`，记录真实测试数量和限制，检查本批仅增加预期改动，保留原有用户产物。
- [x] 交付验证与提交建议，不把实现验证等同于线上模型验收。

最终证据：聚焦回归 55 passed、1 skipped；授权沙箱外离线单元/集成回归 2678 passed、21 skipped、33 deselected、23 warnings。原沙箱运行因禁止测试 socket 而终止，不计通过。详见 `docs/superpowers/reviews/2026-10-16-user-input-lifecycle-handoff.md`。未执行提交或部署。
