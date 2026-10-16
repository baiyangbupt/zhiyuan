# Session Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Execute inline in the existing workspace; no delegation or new branch.

**Goal:** 在单 worker 内准确登记跨异步边界的会话持有者，不启用缓存淘汰。

**Architecture:** 应用实例共享同步 SessionLifecycle；独立 lease 覆盖任务、连接、Gateway 调用及原生请求响应写回。保留既有锁、水位、请求状态和断线投递语义。

**Tech Stack:** Python 3.10、asyncio、pytest；无新依赖。

**Spec:** `docs/superpowers/specs/2026-10-16-session-ownership-design.md`

## Global Constraints

- 不做 TTL/LRU、缓存删除、pending 消费、分布式锁或新线上开关。
- 不改变 CODEX_DETACH_ON_CLOSE、动作事务、续接优先级及现有取消政策。
- 不调用真实模型、共享 Redis/Java/数据库，不重启服务、不部署、不推送。
- 保留原工作区前端产物和调查文档；不自动提交。
- 用 apply_patch 修改；先失败测试再实现；验证仅使用隔离离线测试。

## Review Findings

- native replay 位于 try/finally 外，异常和取消必须进入连接收尾。
- `_channels` 只是最新路由，不能当作所有连接的引用表；连接 lease 归 channel，关闭发送器后释放。
- Broker 回答完成早于 RPC write/drain；lease 必须在 Client reader 调度前获取，Task done 后释放。
- 排队 admission、未启动即取消的 Task、无 requestId 的 detached action 均需要独立保护。
- late-bound Gateway/Runtime 必须验证同源；重启模型不能清空后台 Java 动作引用。

### Task 1: Coordinator

Files: create `zhiyuan-agent/app/gateway/session_lifecycle.py`, `zhiyuan-agent/tests/unit/test_session_lifecycle.py`.
Interface: `SessionLifecycle.acquire(key, owner_kind) -> SessionLease`; `inspect(key) -> immutable snapshot | None`；idempotent close/context manager。

- [x] 用假时钟验证多 owner、租户隔离、不可变诊断、幂等释放、无驱逐。
- [x] 运行测试确认缺少模块而失败；最小实现后重跑。

### Task 2: Runtime And Tasks

Files: modify `app/gateway/session_runtime.py`; create `tests/unit/test_session_runtime_ownership.py` (paths relative to zhiyuan-agent).

- [x] 先测排队取消、调度前获取、未启动取消、调度失败、无 ID detached、publish 等待及连接重叠。
- [x] 接入共享 lifecycle；done callback 释放；channel.close 最终释放真实连接。
- [x] 运行新测试及 request_admission 回归。

### Task 3: Gateway Boundaries

Files: modify `app/gateway/service.py`; create `tests/unit/test_gateway_session_ownership.py`.

- [x] 先测读取、动作、回合锁等待、续接、控制等待及错误/取消释放。
- [x] 保护公共异步入口；校验 Runtime 同源；不移动用户水位和续接 once-key。
- [x] 回归动作和预览续接、thread recovery。

### Task 4: Protocol And Connection Wiring

Files: modify `app/harness/client.py`, `app/harness/codex.py`, `app/gateway/composition.py`, `app/server.py`; extend composition/native lifecycle tests and connection tests.

- [x] 测真实 fake-stdio 请求回答后 write/drain 仍持有、错误/进程退出释放及未知方法不变。
- [x] Client 接可选同步 lease factory；composition 按可信 thread 解析；不导入 Gateway 到通用 Client。
- [x] server 显式共享 registry；票据 key 在首次 await 前绑定；replay/start/loop 全部进入 finally。
- [x] 测 native/compat 关闭、重连、replay 失败及取消；保留路由开关语义。

### Task 5: Verification And Handoff

- [x] 运行新增及相关回归，再运行 tests/unit tests/integration -m 'not e2e' 离线全量。
- [x] 检查 git diff --check、取消路径、身份边界和变更范围。
- [x] 写本批 handoff，记录证据与剩余风险；明确尚未实现内存回收，不自动提交。

Test runner (agent cwd): `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/zhiyuan_hardening_pytest.py <test paths> -q -rs`。
