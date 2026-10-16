# Session Reclaim Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; no delegation or new branch.

**Goal:** 给未来回收提供新鲜 pending 三态与活动二次复核，不做任何删除。

**Architecture:** 专用只读 GET 严格验证 HTTP/业务 envelope；独立预检器 inspect 共享 lifecycle，在异步查询前后比较不可变 stamp。composition 提供实例级装配但不自动执行检查。

**Tech Stack:** Python 3.10、asyncio、aiohttp、pytest，无新依赖。

**Spec:** `docs/superpowers/specs/2026-10-16-session-reclaim-preflight-design.md`。

## Global Constraints

- 不启用驱逐/TTL/LRU/扫描，不修改 pending、路由、缓存或幂等窗口。
- 不改 Java、线上配置，不重启服务，不用真实模型或共享 Redis/数据库。
- 保留原前端产物及调查文档；原计划不自动提交，用户随后同意独立提交，仅提交本批文件，不推送或部署。
- 修改只用 apply_patch，失败测试先行；离线测试只允许 fixture-owned 端口。

### Task 1: Pending Three-State Contract

Files: create `zhiyuan-agent/app/gateway/session_reclaim.py` and `zhiyuan-agent/tests/unit/test_session_reclaim_preflight.py`.
Interfaces: immutable `PendingObservation`; `PendingPresence`; response classification scoped to SessionKey。

- [x] 先写 null/active/applying/终态/未知/畸形/身份错配测试并确认缺少实现失败。
- [x] 最小实现三态，缺失字段和错误响应不得当作 absent。
- [x] 重跑验证状态边界（48 passed）。

### Task 2: Strict Read Transport

Files: modify `app/util/internal_client.py`; create `tests/integration/test_session_reclaim_transport.py` (relative to agent).
Interface: `load_pending_for_reclaim(*, tenant_id, session_id)`；HttpClient.get 的可选 require_success 默认 False。

- [x] fixture HTTP 测非 200 + code=0、畸形 JSON/错误 envelope、租户路径及 GET-only。
- [x] 新入口严格请求；旧 GET 保留行为；非法 ID 在联网前拒绝。
- [x] 重跑 transport 与既有 pending client/token/timeout 回归（123 passed，含三态）。

### Task 3: Asynchronous Preflight

Files: extend `app/gateway/session_reclaim.py` and its unit tests。
Interface: `await SessionReclaimPreflight.check(key, *, idle_seconds, timeout_seconds)` returns diagnostic candidate/blocked with stamp。

- [x] 先测 activity/revision 交错、预约重入、取消/超时、路由与 unknown、空闲起点不变。
- [x] 实现无 owner 的只读预检，finally 释放预约；候选不是删除许可。
- [x] 重跑生命周期与预检测试（91 passed）。

### Task 4: Composition And Verification

Files: modify `app/gateway/composition.py`; extend `tests/integration/test_gateway_composition.py`; create root review handoff。

- [x] 先测真实 composition 的共享 registry、缓存无关、未装配 Runtime 与残留路由阻止。
- [x] 接线只读检查器，无自动调用/扫描/配置开关（聚焦 192 passed、1 skipped）。
- [x] 聚焦、离线全量、diff review 与空白检查；记录结果及未解决的容量/跨进程风险（全量 2865 passed、21 skipped、33 deselected、23 warnings）。
