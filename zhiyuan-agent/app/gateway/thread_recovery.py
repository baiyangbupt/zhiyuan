"""A7：Thread 恢复。

恢复的目的只有一个：**让用户上一轮说过的话还在**。Codex 的上下文长在原生
thread 里，Gateway 进程一重启，进程内那张 `_threads` 表就没了——如果这时直接
新建一个 thread，用户会得到一个"记得你叫张三，但不记得你刚才说了什么"的
对话，而且链路上不报任何错。

因此这里的规则是三条，不是一条：

1. 只有**查得到绑定**、且 resume **明确说"这个 thread 没有 rollout"**时，
   才允许新建。其余任何失败都不许落进新建分支。
2. 不能归因的失败（权限、配置、传输、超时）必须原样抛出去。把它降级成
   "thread 没了 → 建个新的"，等于用一次静默的身份替换盖掉一次鉴权失败：
   用户看不出区别，运维也看不出。
3. 业务隔离边界始终是 `(tenantId, chatSessionId)`。thread 是运行/审计身份，
   会随进程重启改变（台账 2026-09-13 裁决），两个租户的 sessionId 相同
   不构成"同一个人"。

真实二进制实测（`codex-cli 0.155.1`，源码 `5c5308f`，探针 2026-09-21）：

    thread/resume(没有 rollout 的 thread) → AppServerProtocolError(code=-32600,
        "no rollout found for thread id <id>", data=None)
    thread/resume(格式非法的 id)          → AppServerProtocolError(code=-32600,
        "invalid session id: …", data=None)
    thread/resume(刚 create、没跑过回合)  → 同上，**也是** no rollout found

最后一条是实测出来的、最容易写错的地方：新建完立刻 resume 会失败，因为
rollout 是跑回合时才落盘的。所以"刚建的 thread resume 不通"是正常现象，
不是损坏——但这也意味着**不能**用 resume 成功与否判断 thread 是否属于自己，
归属只能来自后端绑定表。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.gateway.ui_events import SessionKey
from app.harness.client import AppServerExited

logger = logging.getLogger(__name__)


class ThreadRecoveryError(RuntimeError):
    """恢复失败。`code` 是要写进事件/日志的稳定标识，不给人看。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def normalize_current_binding_payload(
    payload: Any, *, require_envelope: bool = False,
) -> Mapping[str, Any] | None:
    """严格解包远端响应；显式注入的本地查询也可返回裸绑定或 None。"""
    envelope_keys = {"code", "data", "error", "errors", "success", "failed"}
    if require_envelope or (
        isinstance(payload, Mapping) and envelope_keys.intersection(payload)
    ):
        if (
            not isinstance(payload, Mapping)
            or type(payload.get("code")) is not int
            or "data" not in payload
            or "error" in payload
            or "errors" in payload
            or ("success" in payload and payload["success"] is not True)
            or ("failed" in payload and payload["failed"] is not False)
        ):
            raise ThreadRecoveryError("binding_lookup_invalid", "invalid binding response envelope")
        if payload["code"] != 0:
            raise ThreadRecoveryError(
                "binding_lookup_failed", f"current binding lookup returned code={payload['code']}",
            )
        payload = payload["data"]
    if payload is not None and not isinstance(payload, Mapping):
        raise ThreadRecoveryError("binding_lookup_invalid", "invalid binding response data")
    if isinstance(payload, Mapping) and envelope_keys.intersection(payload):
        raise ThreadRecoveryError("binding_lookup_invalid", "nested binding response envelope")
    return payload


def compose_current_binding_lookup(
    backend: Callable[[str, str], Any],
    registry: Any | None = None,
) -> Callable[[str, str], Any]:
    """两级恢复查询：后端（权威）优先，本地登记表兜底。

    **为什么需要兜底**（2026-10-13 实测，会话 10041981）：后端绑定行带
    `expires_at`（登记 TTL 默认 900 秒），而"查当前绑定"这条路按
    `expires_at > now` 过滤。进程重启若晚于最后一次登记 + TTL，查询只会
    回 `null`——与"真新会话"**不可区分** → `load_or_resume` 静默新建 thread
    → 用户得到"历史都在、模型却看不见"的对话（19:07 与 19:23 两次都栽在
    这条路上：行分别 18:50:19 登记（19:05:19 过期）、19:07:18 登记
    （19:22:18 过期），而查询发生在 19:07:17 / 19:23:41）。

    本地登记表（`ThreadBindingRegistry`）由本进程每回合无条件写、没有 TTL，
    它记得"这个会话最后用过的 thread"。只在后端说"没有绑定"时用它，且它
    只回答"找回哪个 thread"——拿回 thread 后 `backend_binding_loader` 会
    重新登记，后端那行的 handle 与 expires_at 随之刷新（自愈）。

    纪律与原查询一致：后端查询失败、本地查询失败都**抛**（由调用方判成
    可恢复错误），不许降级成"没有绑定"——那就是拿一次故障换一次上下文丢失。
    只有可信的无绑定回答才可兜底；错误和畸形响应在查询边界直接拒绝，
    后端故障不许被一次本地命中盖掉。
    """

    async def lookup(tenant_id: str, session_id: str) -> Any:
        payload = await _maybe_await(backend(tenant_id, session_id))
        data = normalize_current_binding_payload(payload)
        if data is not None or registry is None:
            return payload
        try:
            fallback = registry.latest_for_session(str(tenant_id), str(session_id))
        except Exception as exc:  # noqa: BLE001 —— 分类逻辑就在下面
            raise ThreadRecoveryError(
                "binding_registry_lookup_failed",
                f"local binding registry lookup failed: {exc}",
            ) from exc
        if fallback is not None:
            # 留痕：这轮走的是兜底恢复（后端行大概已过期）。没有这行日志，
            # "这轮为什么恢复了 / 为什么没恢复"只能靠猜。
            logger.warning(
                "current binding lookup returned none for tenant=%s session=%s; "
                "falling back to the local registry thread %s (the backend row is "
                "probably expired, its TTL is minutes)",
                tenant_id,
                session_id,
                fallback.get("threadId"),
            )
        return fallback

    return lookup


# 只有这两类允许落到"重建"分支。依据见模块开头的实测记录：
# 都是 -32600（JSON-RPC invalid request）+ 一句能认出来的话。
# 单靠 code 不够——把任何 -32600 都当成"thread 没了"，会把将来某个
# 同样用 -32600 的权限错误也吞掉。
NOT_RESUMABLE_CODE = -32600
NOT_RESUMABLE_MARKERS = ("no rollout found", "invalid session id")

# 第二类**已知**的 resume 失败：thread 已经被别的写者占用。实测形状（同上二进制）：
#   thread/resume(已被占用的 thread) → AppServerProtocolError(code=-32600,
#       "thread <id> already has an active writer", data=None)
# 与"没有 rollout"的区别很重要：这个**不是永久状态**，但**也不会自己好**——
# 实测占用者是**当前进程自己的 codex**（第一次 resume 失败后写锁没还），
# 而且写锁跨进程存活（kill -9 之后锁文件仍在）。所以：先退避重试几次，
# 仍被占就重建。丢的是模型侧对话记忆，业务状态在 Java，不受影响。
LOCK_CONFLICT_MARKERS = ("already has an active writer",)
DEFAULT_RESUME_ATTEMPTS = 3
DEFAULT_RESUME_BACKOFF_SECONDS = 1.5


def is_not_resumable(exc: BaseException) -> bool:
    """这个 resume 失败是否**明确**表示"这个 thread 恢复不了"。

    判据是实测出来的形状，不是猜的：code 与消息必须同时对上。
    对不上的一律返回 False——宁可不重建，也不能重建错了。
    """
    if getattr(exc, "code", None) != NOT_RESUMABLE_CODE:
        return False
    message = str(exc)
    return any(marker in message for marker in NOT_RESUMABLE_MARKERS)


def is_lock_conflict(exc: BaseException) -> bool:
    """这个 resume 失败是否只是"thread 正被占用"。

    它必须与 `is_not_resumable` 分开：前者是"等一等或重建"，后者是
    "这个 thread 确实没了"。混成一条会让"锁被占"要么被当成永久损坏
    （会话从此不可用），要么被当成可以随便重建（把还能救的上下文丢掉）。
    """
    if getattr(exc, "code", None) != NOT_RESUMABLE_CODE:
        return False
    message = str(exc)
    return any(marker in message for marker in LOCK_CONFLICT_MARKERS)


def is_runtime_exit(exc: BaseException) -> bool:
    """原生 runtime 在本次调用里退出了。

    与上面两类都不同：thread 可能有救，但**进程没了**，而进程不会自己复活。
    处置是"重拉 runtime，然后重建"——重拉之后再去 resume 同一个 thread，
    实测只会再打死一次。
    """
    return isinstance(exc, AppServerExited)


@dataclass(frozen=True)
class CurrentBinding:
    """后端记着的、本会话当前有效的绑定。"""

    thread_id: str
    tenant_id: str
    session_id: str
    user_id: str = ""
    allowed_capabilities: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: Any) -> "CurrentBinding | None":
        """把 `/thread-binding/current` 的 data 解析成绑定。

        认不出来就返回 None（= 没有绑定），但**不抛**：这个函数的调用方
        拿不到绑定时的动作是"新建"，而"后端返回了看不懂的东西"不该被
        当成"没有绑定"——所以解析失败由调用方按错误处理，见 `load_or_resume`。
        """
        if not isinstance(payload, Mapping):
            return None
        thread_id = payload.get("threadId")
        tenant_id = _binding_scope_id(payload.get("tenantId"))
        session_id = _binding_scope_id(payload.get("chatSessionId"))
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or thread_id != thread_id.strip()
            or tenant_id is None
            or session_id is None
        ):
            return None
        capabilities = payload.get("allowedCapabilities") or ()
        if isinstance(capabilities, str):
            capabilities = [item for item in capabilities.split(",") if item]
        return cls(
            thread_id=thread_id,
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=str(payload.get("userId") or ""),
            allowed_capabilities=frozenset(str(item) for item in capabilities),
        )

    def belongs_to(self, key: SessionKey) -> bool:
        """归属核验：身份必须完整，且同时匹配租户与会话。"""
        return (
            bool(self.tenant_id and self.session_id)
            and self.tenant_id == str(key.tenant_id)
            and self.session_id == str(key.session_id)
        )


def _binding_scope_id(value: Any) -> str | None:
    if type(value) not in (str, int):
        return None
    normalized = str(value)
    if (
        not normalized.isascii()
        or not normalized.isdecimal()
        or normalized.startswith("0")
        or len(normalized) > 19
        or (len(normalized) == 19 and normalized > "9223372036854775807")
    ):
        return None
    return normalized


class ThreadRecovery:
    """`load_or_resume` 的全部输入都是注入的，所以它在测试里不需要真实 Codex。"""

    def __init__(
        self,
        *,
        resume: Callable[[str], Any],
        create: Callable[[], Any],
        lookup: Callable[[str, str], Any] | None = None,
        restart: Callable[[], Any] | None = None,
        attempts: int = DEFAULT_RESUME_ATTEMPTS,
        backoff_seconds: float = DEFAULT_RESUME_BACKOFF_SECONDS,
    ) -> None:
        self._resume = resume
        self._create = create
        self._restart = restart
        # lookup(tenantId, chatSessionId) —— 位置参数，返回后端响应或 None。
        self._lookup = lookup
        self._attempts = max(0, int(attempts))
        self._backoff = max(0.0, float(backoff_seconds))

    async def load_or_resume(self, key: SessionKey, snapshot: Any = None) -> str:
        """返回这个会话该用的 threadId。算法固定，没有旁路。"""
        del snapshot  # 恢复本身不读快照；快照由 Gateway 在这之后注入本回合。
        binding = await self._load_binding(key)
        if binding is not None:
            if not binding.belongs_to(key):
                # 后端按 (tenant, session) 查出来的东西不属于这个 (tenant, session)：
                # 这是数据问题，不是"没绑定"。重建会把问题掩盖掉。
                raise ThreadRecoveryError(
                    "binding_ownership_mismatch",
                    f"binding {binding.thread_id} does not belong to the requested session",
                )
            try:
                await _maybe_await(self._resume(binding.thread_id))
                logger.info("thread %s resumed; keeping the model-side context", binding.thread_id)
                return binding.thread_id
            except Exception as exc:  # noqa: BLE001 —— 分类逻辑就在下面
                if is_runtime_exit(exc):
                    # 进程被这次 resume 打死了（实测：resume 某些坏 thread 会让
                    # codex 直接退出）。先重拉 runtime——不重拉的话，接下来的
                    # 新建也只会撞在一个死进程上，整个 agent 跟着废。
                    # 然后**重建**：重拉后再 resume 同一个 thread 只会再死一次。
                    logger.warning(
                        "app server exited while resuming thread %s; restarting runtime "
                        "and rebuilding (model-side context is lost, business state is not)",
                        binding.thread_id,
                    )
                    await self._restart_runtime()
                    return await self._create_thread()
                if is_not_resumable(exc):
                    # 这条以前是**静默**的，于是"这一轮到底走了哪条恢复分支"
                    # 只能靠推断（自愈那次就是这样）。三条分支各留一条日志，
                    # 诊断才不用回头猜。级别是 WARNING、措辞含"context is lost"：
                    # 这是**唯一**允许丢模型侧历史的分支（rollout 确实没了），
                    # "用户发现它忘了刚说过的话"必须在日志里一眼可见（与另两条
                    # 重建分支同一口径）。
                    logger.warning(
                        "thread %s is not resumable (%s); rebuilding "
                        "(model-side context is lost, business state is not)",
                        binding.thread_id,
                        exc,
                    )
                    return await self._create_thread()
                if is_lock_conflict(exc) and await self._retry_locked(binding.thread_id):
                    logger.info("thread %s was locked; acquired after backoff", binding.thread_id)
                    return binding.thread_id
                if not is_lock_conflict(exc):
                    raise ThreadRecoveryError(
                        "thread_resume_failed",
                        f"resume failed for thread {binding.thread_id}: {exc}",
                    ) from exc
                # 退避之后仍被占用：**重建**。丢的是模型侧的对话记忆，
                # 业务状态在 Java（快照、Pending、证据），一样都不会少。
                # 这条日志很重要：否则"用户发现它忘了刚才说过的话"这件事
                # 在链路上没有痕迹，只能靠猜。
                logger.warning(
                    "thread %s still locked after %d attempts; rebuilding "
                    "(model-side context is lost, business state is not)",
                    binding.thread_id,
                    self._attempts,
                )
        return await self._create_thread()

    async def _restart_runtime(self) -> None:
        if self._restart is None:
            raise ThreadRecoveryError(
                "runtime_restart_unavailable",
                "app server exited and this harness cannot be restarted",
            )
        await _maybe_await(self._restart())

    async def _retry_locked(self, thread_id: str) -> bool:
        """被占用时退避重试。返回是否最终拿到。"""
        for _ in range(self._attempts):
            await asyncio.sleep(self._backoff)
            try:
                await _maybe_await(self._resume(thread_id))
                return True
            except Exception as exc:  # noqa: BLE001
                if not is_lock_conflict(exc):
                    raise ThreadRecoveryError(
                        "thread_resume_failed",
                        f"resume failed for thread {thread_id}: {exc}",
                    ) from exc
        return False

    async def _load_binding(self, key: SessionKey) -> CurrentBinding | None:
        if self._lookup is None:
            # 没配后端查询（本地最小栈）时，"没有绑定"是配置事实，不是运行时
            # 故障——这条路径下新建是正确动作。
            return None
        try:
            payload = await _maybe_await(self._lookup(str(key.tenant_id), str(key.session_id)))
        except Exception as exc:  # noqa: BLE001
            # 查询失败 ≠ 没有绑定。在这里新建，等于把一次后端故障变成
            # 一次上下文丢失。
            raise ThreadRecoveryError(
                "binding_lookup_failed", f"current binding lookup failed: {exc}"
            ) from exc
        data = normalize_current_binding_payload(payload)
        if data is None:
            return None
        binding = CurrentBinding.from_payload(data)
        if binding is None:
            raise ThreadRecoveryError(
                "binding_lookup_invalid", "current binding payload is not a usable binding"
            )
        return binding

    async def _create_thread(self) -> str:
        created = await _maybe_await(self._create())
        thread_id = _thread_id_from(created)
        if not thread_id:
            raise ThreadRecoveryError(
                "thread_not_created", "codex did not return a thread id"
            )
        return thread_id


def _thread_id_from(created: Any) -> str:
    if isinstance(created, Mapping):
        thread = created.get("thread")
        if isinstance(thread, Mapping):
            return str(thread.get("id") or "")
        return str(created.get("id") or "")
    return ""


def _maybe_await(value: Any) -> Any:
    """既收协程也收普通值。

    注入进来的替身大多是同步的，而真实实现是异步的；这里多一个 `await` 与否
    不该由每个调用点分别决定。
    """
    if inspect.isawaitable(value):
        return value
    return _Immediate(value)


class _Immediate:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self) -> Any:
        async def _run() -> Any:
            return self.value

        return _run().__await__()


__all__ = [
    "CurrentBinding",
    "DEFAULT_RESUME_ATTEMPTS",
    "DEFAULT_RESUME_BACKOFF_SECONDS",
    "LOCK_CONFLICT_MARKERS",
    "NOT_RESUMABLE_CODE",
    "NOT_RESUMABLE_MARKERS",
    "ThreadRecovery",
    "ThreadRecoveryError",
    "compose_current_binding_lookup",
    "is_lock_conflict",
    "is_not_resumable",
    "normalize_current_binding_payload",
]
