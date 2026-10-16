"""A7：恢复判定的纯单测。

这里只钉两件事：**什么算"认得出的不可恢复"**、以及**归属怎么判**。
两者都是会出错的那一半——错在宽松处，一次权限错误会变成一次静默的身份替换。
"""
from __future__ import annotations

import sqlite3

import pytest

from app.gateway.thread_recovery import (
    CurrentBinding,
    ThreadRecovery,
    ThreadRecoveryError,
    is_not_resumable,
)
from app.gateway.ui_events import SessionKey
from app.harness.client import AppServerProtocolError


def test_no_rollout_is_recognised_as_not_resumable() -> None:
    """形状抄自实测：-32600 + "no rollout found for thread id <id>"。"""
    exc = AppServerProtocolError(
        -32600, "no rollout found for thread id 01a0c24c-423a-7151-a8df-55b9d08993b1"
    )

    assert is_not_resumable(exc) is True


def test_invalid_session_id_is_recognised_as_not_resumable() -> None:
    exc = AppServerProtocolError(
        -32600, "invalid session id: invalid character: expected an optional prefix of `urn:uuid:`"
    )

    assert is_not_resumable(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # 同样的消息、不同的 code：不认。code 和消息必须同时对得上，
        # 只认消息的话，将来某个上游把这句话挪到别的错误里就会误判。
        AppServerProtocolError(-32000, "no rollout found for thread id x"),
        # 认不出的失败一律不认。
        AppServerProtocolError(-32000, "thread cannot be resumed"),
        AppServerProtocolError(-32600, "permission denied"),
        TimeoutError("app server did not answer"),
        RuntimeError("connection reset"),
    ],
)
def test_everything_else_is_not_treated_as_rebuildable(exc: BaseException) -> None:
    assert is_not_resumable(exc) is False


def test_binding_ownership_is_checked_on_both_axes() -> None:
    binding = CurrentBinding(
        thread_id="thr-1", tenant_id="1", session_id="42", user_id="7"
    )

    assert binding.belongs_to(SessionKey(tenant_id="1", session_id="42")) is True
    # 同一个 sessionId、不同租户：必须判否，否则两个租户会共用一个 thread。
    assert binding.belongs_to(SessionKey(tenant_id="2", session_id="42")) is False
    assert binding.belongs_to(SessionKey(tenant_id="1", session_id="99")) is False


def test_binding_payload_without_a_thread_is_not_a_binding() -> None:
    assert CurrentBinding.from_payload({"chatSessionId": 42}) is None
    assert CurrentBinding.from_payload(None) is None
    assert CurrentBinding.from_payload("thr-1") is None


@pytest.mark.asyncio
async def test_a_failed_lookup_never_falls_through_to_creating_a_thread() -> None:
    """查询失败 ≠ 没有绑定：前者必须抛出去，不许新建。"""
    created: list[str] = []

    async def lookup(tenant_id: str, session_id: str):
        raise RuntimeError("backend down")

    async def create():
        created.append("called")
        return {"thread": {"id": "thr-new"}}

    recovery = ThreadRecovery(resume=lambda _: None, create=create, lookup=lookup)

    with pytest.raises(ThreadRecoveryError) as err:
        await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert err.value.code == "binding_lookup_failed"
    assert created == []


@pytest.mark.asyncio
async def test_a_recoverable_resume_failure_keeps_the_original_error() -> None:
    """认不出的 resume 失败：抛可恢复错误，不新建，且把原因带上。"""

    async def lookup(tenant_id: str, session_id: str):
        return {
            "code": 0,
            "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-old"},
        }

    async def resume(thread_id: str):
        raise AppServerProtocolError(-32000, "thread cannot be resumed")

    async def create():
        raise AssertionError("认不出的失败不许新建 thread")

    recovery = ThreadRecovery(resume=resume, create=create, lookup=lookup)

    with pytest.raises(ThreadRecoveryError) as err:
        await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert err.value.code == "thread_resume_failed"
    assert "thr-old" in str(err.value)


@pytest.mark.asyncio
async def test_a_missing_rollout_creates_a_new_thread() -> None:
    created: list[str] = []

    async def lookup(tenant_id: str, session_id: str):
        return {"code": 0, "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-old"}}

    async def resume(thread_id: str):
        raise AppServerProtocolError(-32600, f"no rollout found for thread id {thread_id}")

    async def create():
        created.append("thr-new")
        return {"thread": {"id": "thr-new"}}

    recovery = ThreadRecovery(resume=resume, create=create, lookup=lookup)

    thread_id = await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert thread_id == "thr-new"
    assert created == ["thr-new"]


@pytest.mark.asyncio
async def test_a_codex_that_returns_no_thread_id_is_an_error_not_an_empty_thread() -> None:
    async def create():
        return {"thread": {}}

    recovery = ThreadRecovery(resume=lambda _: None, create=create)

    with pytest.raises(ThreadRecoveryError) as err:
        await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert err.value.code == "thread_not_created"


def test_active_writer_is_a_lock_conflict_not_a_dead_thread() -> None:
    """实测形状：`-32600 thread <id> already has an active writer`。

    这条与 `no rollout found` 必须分开：前者是"等一等或重建"，后者是
    "这个 thread 确实没了"。混成一条的两种坏结局——当成永久损坏（会话从此
    不可用，实测就是这么发生的），或当成可以随便重建（把还能救的上下文丢掉）。
    """
    from app.gateway.thread_recovery import is_lock_conflict

    locked = AppServerProtocolError(-32600, "thread 01a0c27c-3176 already has an active writer")
    missing = AppServerProtocolError(-32600, "no rollout found for thread id 01a0c27c")

    assert is_lock_conflict(locked) is True
    assert is_not_resumable(locked) is False
    assert is_lock_conflict(missing) is False
    assert is_not_resumable(missing) is True


@pytest.mark.asyncio
async def test_a_transient_lock_is_waited_out() -> None:
    """第一次被占、第二次就拿到 → 沿用原 thread，不重建（上下文保住）。"""
    attempts = {"resume": 0}

    async def lookup(tenant_id: str, session_id: str):
        return {"code": 0, "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-old"}}

    async def resume(thread_id: str):
        attempts["resume"] += 1
        if attempts["resume"] == 1:
            raise AppServerProtocolError(-32600, f"thread {thread_id} already has an active writer")
        return {"thread": {"id": thread_id}}

    async def create():
        raise AssertionError("能在重试里拿到就不该重建")

    recovery = ThreadRecovery(resume=resume, create=create, lookup=lookup, backoff_seconds=0)

    thread_id = await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert thread_id == "thr-old"
    assert attempts["resume"] == 2


@pytest.mark.asyncio
async def test_a_permanent_lock_rebuilds_instead_of_killing_the_session() -> None:
    """退避之后仍被占用 → 重建。

    锁是跨进程存活的（kill -9 之后锁文件仍在，持有者会变成"当前进程自己"），
    所以"等它释放"不是一条路。重建丢的是模型侧对话记忆，业务状态在 Java。
    不重建的话，用户看到的是**每一轮**都"引擎不可用"。
    """
    created: list[str] = []

    async def lookup(tenant_id: str, session_id: str):
        return {"code": 0, "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-locked"}}

    async def resume(thread_id: str):
        raise AppServerProtocolError(-32600, f"thread {thread_id} already has an active writer")

    async def create():
        created.append("thr-new")
        return {"thread": {"id": "thr-new"}}

    recovery = ThreadRecovery(
        resume=resume, create=create, lookup=lookup, attempts=2, backoff_seconds=0
    )

    thread_id = await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert thread_id == "thr-new"
    assert created == ["thr-new"]


def test_a_dead_runtime_is_its_own_class() -> None:
    """进程退出必须是**类型**，不是一句话。

    靠匹配 "app server exited" 这串英文，上游换个措辞就会退化成
    "认不出的失败 → 整个会话不可用"——实测中就是这么发生的。
    """
    from app.gateway.thread_recovery import is_runtime_exit
    from app.harness.client import AppServerExited

    assert is_runtime_exit(AppServerExited("app server exited")) is True
    assert is_runtime_exit(RuntimeError("app server exited")) is False
    assert is_runtime_exit(AppServerProtocolError(-32600, "no rollout found")) is False


@pytest.mark.asyncio
async def test_a_dead_runtime_is_restarted_then_rebuilt() -> None:
    """resume 把 runtime 打死时：重拉 → 重建。

    重拉是必需的：不重拉就撞在一个死进程上，新建也一样失败（实测中整个
    agent 就是这么废掉的）。重建也是必需的：重拉后再 resume 同一个 thread
    只会再打死一次。
    """
    from app.harness.client import AppServerExited

    events: list[str] = []

    async def lookup(tenant_id: str, session_id: str):
        return {"code": 0, "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-toxic"}}

    async def resume(thread_id: str):
        events.append("resume")
        raise AppServerExited("app server exited")

    async def create():
        events.append("create")
        return {"thread": {"id": "thr-fresh"}}

    async def restart():
        events.append("restart")

    recovery = ThreadRecovery(resume=resume, create=create, lookup=lookup, restart=restart)

    thread_id = await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert thread_id == "thr-fresh"
    # 顺序也是断言的一部分：先重拉，再新建。反过来的话新建会撞在死进程上。
    assert events == ["resume", "restart", "create"]


@pytest.mark.asyncio
async def test_a_dead_runtime_without_a_restart_hook_says_so() -> None:
    """harness 不支持重拉时，要明确说出来，不能假装恢复成功。"""
    from app.harness.client import AppServerExited

    async def lookup(tenant_id: str, session_id: str):
        return {"code": 0, "data": {"tenantId": tenant_id, "chatSessionId": session_id, "threadId": "thr-toxic"}}

    async def resume(thread_id: str):
        raise AppServerExited("app server exited")

    recovery = ThreadRecovery(resume=resume, create=lambda: {"thread": {"id": "x"}}, lookup=lookup)

    with pytest.raises(ThreadRecoveryError) as err:
        await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert err.value.code == "runtime_restart_unavailable"


# ── 两级恢复查询：后端过期 → 本地登记表兜底（2026-10-13 会话 10041981 真因） ──


@pytest.mark.asyncio
async def test_an_expired_backend_binding_falls_back_to_the_local_registry() -> None:
    """后端说"没有绑定"、本地登记表记得这个会话 → 用本地那份。

    后端那行按 `expires_at > now` 过滤，TTL 是分钟级；重启晚过 TTL 时它只会
    回 null——与"真新会话"不可区分。不兜底就是**静默新建**（模型侧历史全丢）。
    """
    from app.gateway.thread_recovery import compose_current_binding_lookup

    consulted: list[tuple[str, str]] = []

    class _Registry:
        def latest_for_session(self, tenant_id: str, session_id: str):
            consulted.append((tenant_id, session_id))
            return {"threadId": "thr-from-registry", "tenantId": tenant_id, "chatSessionId": session_id}

    async def backend(tenant_id: str, session_id: str):
        return None  # 后端过期行的形状：code=0 / data=null 已被 server.py 收敛成 None

    lookup = compose_current_binding_lookup(backend, _Registry())
    payload = await lookup("1", "42")

    assert payload == {"threadId": "thr-from-registry", "tenantId": "1", "chatSessionId": "42"}
    assert consulted == [("1", "42")]


@pytest.mark.asyncio
async def test_a_backend_binding_is_never_overridden_by_the_local_registry() -> None:
    """后端是权威：它给了绑定就不许再看本地那份（本地可能更旧）。"""

    from app.gateway.thread_recovery import compose_current_binding_lookup

    class _Registry:
        def latest_for_session(self, tenant_id: str, session_id: str):  # pragma: no cover
            raise AssertionError("后端有绑定的时候不该查本地表")

    async def backend(tenant_id: str, session_id: str):
        return {"threadId": "thr-backend", "tenantId": tenant_id, "chatSessionId": session_id}

    lookup = compose_current_binding_lookup(backend, _Registry())

    assert (await lookup("1", "42"))["threadId"] == "thr-backend"


@pytest.mark.asyncio
async def test_a_local_registry_lookup_failure_is_not_a_missing_binding() -> None:
    """本地查不了 ≠ 没有绑定：照旧抛出去，由调用方判成可恢复错误。

    降级成"没有绑定"与后端查询失败降级的后果一模一样：一次故障换一次上下文丢失。
    """

    from app.gateway.thread_recovery import compose_current_binding_lookup

    class _Registry:
        def latest_for_session(self, tenant_id: str, session_id: str):
            raise sqlite3.OperationalError("no such table: codex_thread_binding_registry")

    async def backend(tenant_id: str, session_id: str):
        return None

    lookup = compose_current_binding_lookup(backend, _Registry())

    with pytest.raises(ThreadRecoveryError) as err:
        await lookup("1", "42")

    assert err.value.code == "binding_registry_lookup_failed"


@pytest.mark.asyncio
async def test_without_a_local_registry_the_backend_answer_stands() -> None:
    """没配本地登记表（legacy / 没路径）时行为与从前一致：None 就是 None。"""

    from app.gateway.thread_recovery import compose_current_binding_lookup

    async def backend(tenant_id: str, session_id: str):
        return None

    assert await compose_current_binding_lookup(backend, None)("1", "42") is None


@pytest.mark.asyncio
async def test_a_backend_error_envelope_is_not_masked_by_the_local_registry() -> None:
    """后端回 `code != 0`（"查不了"）：查询边界拒绝，不许兜底。

    后端故障被一次本地命中盖掉，等于把一次真实故障做成"看起来恢复了"——
    与把故障降级成"没有绑定"是同一类错误，只是方向相反。
    """

    from app.gateway.thread_recovery import compose_current_binding_lookup

    class _Registry:
        def latest_for_session(self, tenant_id: str, session_id: str):  # pragma: no cover
            raise AssertionError("后端说'查不了'时不许查本地表")

    async def backend(tenant_id: str, session_id: str):
        return {"code": 500, "msg": "backend down", "data": None}

    lookup = compose_current_binding_lookup(backend, _Registry())

    with pytest.raises(ThreadRecoveryError) as err:
        await lookup("1", "42")
    assert err.value.code == "binding_lookup_failed"

    async def resume(thread_id: str):
        raise AssertionError("不该走到 resume")

    async def create():  # pragma: no cover
        raise AssertionError("不该走到新建")

    recovery = ThreadRecovery(resume=resume, create=create, lookup=lookup)
    with pytest.raises(ThreadRecoveryError) as err:
        await recovery.load_or_resume(SessionKey(tenant_id="1", session_id="42"))

    assert err.value.code == "binding_lookup_failed"


@pytest.mark.asyncio
async def test_an_expired_backend_envelope_falls_back_to_the_local_registry() -> None:
    """信封形状的 null（`{"code":0,"data":null}`，测里后端替身的原样回包）也走兜底。"""

    from app.gateway.thread_recovery import compose_current_binding_lookup

    class _Registry:
        def latest_for_session(self, tenant_id: str, session_id: str):
            return {"threadId": "thr-local", "tenantId": tenant_id, "chatSessionId": session_id}

    async def backend(tenant_id: str, session_id: str):
        return {"code": 0, "data": None}

    lookup = compose_current_binding_lookup(backend, _Registry())

    assert (await lookup("1", "42"))["threadId"] == "thr-local"
