from __future__ import annotations

import json
import logging
import os
import asyncio
import uuid
from importlib import metadata
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import CodexAppServerConfig, GatewayConfig, HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.data.message_store import message_store
from app.gateway.composition import build_gateway_runtime, bind_session_runtime
from app.gateway.access import AccessDenied, ConversationAccessGuard, TicketIdentity
from app.util import internal_client
from app.gateway.session_runtime import (
    ACCEPTED,
    BUSY,
    CONFLICT,
    DUPLICATE,
    ConnectionChannel,
    SessionRuntime,
)
from app.gateway.ui_events import SessionKey, resync_snapshot
from app.gateway.user_input import UserInputError
from app.harness.binding import ThreadBinding, generate_opaque_handle
from app.llm.client import LLMClient, configure_logfire
from app.schemas import WSMessage, WSResponse
from app.service import (
    ChatService,
    ChatServiceResponseEnvelope,
)

# 加载环境变量
load_dotenv()

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

_NON_PERSISTENT_USER_MESSAGE_TYPES = {"planEditSelect", "intentSelect", "pendingConfirmation"}
_CHAT_SERVICE_TIMEOUT_SECONDS = 180


def _build_legacy_chat_service(gateway_mode: str) -> ChatService | None:
    """Build the legacy stack only for modes that can route a turn to it."""
    if gateway_mode == "codex_readonly":
        return None
    llm_client = LLMClient()
    history_store = ChatHistoryStore(HistoryConfig().db_path)
    return ChatService(llm_client, history_store)


def _has_primary_reply_content(reply: object) -> bool:
    if isinstance(reply, WSResponse):
        return bool(str(reply.content or "").strip())
    return bool(str(reply or "").strip())


def _build_timeout_reply(user_prompt: str | None = None) -> str:
    prompt = str(user_prompt or "").strip()
    subject = f"你刚才问的是“{prompt[:60]}”。" if prompt else "你刚才的问题还没有处理完。"
    return (
        "这次分析耗时有点长，我先暂停在这里，避免你一直等不到回复。\n\n"
        f"{subject}这轮还没有拿到完整分析结果，也不会自动写入偏好或改动方案。"
        "你可以直接回复“继续分析这个问题”，或者把要求拆成更明确的一句，我会接着处理。"
    )


def _is_closed_send_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        'Cannot call "send" once a close message has been sent' in message
        or "WebSocket is not connected" in message
    )


async def _safe_send_json(ws: WebSocket, data: dict, *, context: str) -> bool:
    try:
        await ws.send_json(data)
        return True
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected before json send: context=%s", context)
        return False
    except RuntimeError as exc:
        if not _is_closed_send_runtime_error(exc):
            raise
        logger.info("WebSocket already closed before json send: context=%s", context)
        return False


async def _safe_send_text(ws: WebSocket, text: str, *, context: str) -> bool:
    try:
        await ws.send_text(text)
        return True
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected before text send: context=%s", context)
        return False
    except RuntimeError as exc:
        if not _is_closed_send_runtime_error(exc):
            raise
        logger.info("WebSocket already closed before text send: context=%s", context)
        return False


class _CompatConnectionRegistry:
    """Tracks the latest compat WebSocket per chat session for reconnect handoff."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_session_id(session_id: object) -> str:
        return str(session_id or "").strip()

    async def register(self, session_id: object, ws: WebSocket) -> str:
        normalized = self._normalize_session_id(session_id)
        if not normalized:
            return ""
        async with self._lock:
            self._connections[normalized] = ws
        return normalized

    async def unregister(self, session_id: object, ws: WebSocket) -> None:
        normalized = self._normalize_session_id(session_id)
        if not normalized:
            return
        async with self._lock:
            if self._connections.get(normalized) is ws:
                self._connections.pop(normalized, None)

    async def send_json(
        self,
        session_id: object,
        data: dict,
        *,
        context: str,
        exclude_ws: WebSocket | None = None,
    ) -> bool:
        normalized = self._normalize_session_id(session_id)
        if not normalized:
            return False
        async with self._lock:
            latest_ws = self._connections.get(normalized)
        if latest_ws is None or latest_ws is exclude_ws:
            return False

        ok = await _safe_send_json(latest_ws, data, context=context)
        if not ok:
            await self.unregister(normalized, latest_ws)
        return ok


_compat_connections = _CompatConnectionRegistry()


async def _safe_send_compat_json(
    ws: WebSocket,
    session_id: object,
    data: dict,
    *,
    context: str,
) -> bool:
    if await _safe_send_json(ws, data, context=context):
        return True

    forwarded = await _compat_connections.send_json(
        session_id,
        data,
        context=f"{context}.active_connection",
        exclude_ws=ws,
    )
    if forwarded:
        logger.info(
            "Forwarded compat websocket message to active connection: session_id=%s context=%s",
            session_id,
            context,
        )
    return forwarded


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 配置 Logfire（必须在创建 Agent 之前）
    configure_logfire()
    logger.info("Logfire configured")

    gateway_config = GatewayConfig()
    codex_config = CodexAppServerConfig()
    app.state.gateway_mode = gateway_config.mode
    app.state.chat_service = _build_legacy_chat_service(gateway_config.mode)

    binding_handles: dict[str, tuple[str, datetime]] = {}
    binding_ttl_seconds = codex_config.binding_ttl_seconds
    binding_registry = None
    if codex_config.binding_registry_path:
        from app.mcp_server.context import ThreadBindingRegistry

        binding_registry = ThreadBindingRegistry(codex_config.binding_registry_path)

    async def backend_binding_loader(
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        thread_id: str,
        allowed_capabilities: list[str],
        admission_mode: str,
        snapshot_version: int | None = None,
        **kwargs,
    ) -> ThreadBinding:
        del kwargs
        from app.util.internal_client import (
            register_codex_thread_binding,
            resolve_codex_thread_binding,
        )

        try:
            numeric_tenant = int(tenant_id)
            numeric_session = int(session_id)
            numeric_user = int(user_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("binding_identity_must_be_numeric") from exc

        cached_binding = binding_handles.get(thread_id)
        now = datetime.now(timezone.utc)
        if cached_binding is None or cached_binding[1] <= now + timedelta(seconds=60):
            handle = generate_opaque_handle()
            expires_at_datetime = now + timedelta(seconds=binding_ttl_seconds)
            expires_at = expires_at_datetime.isoformat().replace("+00:00", "Z")
            registration = await register_codex_thread_binding(
                numeric_tenant,
                {
                    "chatSessionId": numeric_session,
                    "userId": numeric_user,
                    "threadId": thread_id,
                    "handle": handle,
                    "allowedCapabilities": list(allowed_capabilities),
                    "expiresAt": expires_at,
                },
            )
            if (registration or {}).get("code") not in (None, 0):
                raise RuntimeError("binding_registration_failed")
            binding_handles[thread_id] = (handle, expires_at_datetime)
        else:
            handle, expires_at_datetime = cached_binding
            expires_at = expires_at_datetime.isoformat().replace("+00:00", "Z")

        capability = next(iter(allowed_capabilities), "catalog_read")
        resolved = await resolve_codex_thread_binding(
            numeric_tenant,
            {
                "chatSessionId": numeric_session,
                "threadId": thread_id,
                "handle": handle,
                "capability": capability,
            },
        )
        data = (resolved or {}).get("data") or {}
        if (resolved or {}).get("code") not in (None, 0) or not data:
            raise RuntimeError("binding_resolution_failed")
        binding = ThreadBinding(
            thread_id=str(data.get("threadId") or thread_id),
            tenant_id=str(numeric_tenant),
            session_id=str(data.get("chatSessionId") or numeric_session),
            user_id=str(data.get("userId") or numeric_user),
            allowed_capabilities=frozenset(data.get("allowedCapabilities") or allowed_capabilities),
            expires_at=expires_at_datetime,
            admission_mode=admission_mode,
            opaque_handle=handle,
            snapshot_version=snapshot_version,
        )
        if binding_registry is not None:
            binding_registry.store(binding, expires_at=expires_at)
        return binding

    async def snapshot_loader(*, tenant_id: str, session_id: str, skill: str | None = None):
        from app.util.internal_client import get_conversation_turn_snapshot

        return await get_conversation_turn_snapshot(tenant_id, session_id, skill)

    async def evidence_verifier(*, tenant_id, chat_session_id, evidence_ids, thread_id=None):
        """P1c-2：把本回合引用的证据全量提交 Java 台账核验。

        失败**抛**（`verify_evidence` 里把 http_client 那种"失败也返回 dict"的形状
        转成了异常）——调用方按"核验不可用 → 整轮硬失败"处置，不放行。
        """
        from app.util.internal_client import verify_evidence

        return await verify_evidence(
            tenant_id, chat_session_id, evidence_ids, thread_id=thread_id
        )

    async def current_binding_loader(tenant_id: str, session_id: str):
        """A7：进程重启后靠它找回这个会话该用的 thread。

        查不到绑定返回 None（新建），查询**失败**则抛出去由 ThreadRecovery
        判成可恢复错误——把失败当"没有绑定"会把一次后端故障变成一次上下文丢失。
        """
        from app.util.internal_client import get_current_codex_thread_binding

        response = await get_current_codex_thread_binding(tenant_id, session_id)
        if not isinstance(response, dict):
            raise RuntimeError("binding_lookup_invalid_response")
        if response.get("code") not in (None, 0):
            raise RuntimeError("binding_lookup_failed")
        return response.get("data")

    gateway_runtime = await build_gateway_runtime(
        gateway_config,
        legacy=app.state.chat_service,
        message_store=message_store,
        binding_loader=getattr(app.state, "gateway_binding_loader", backend_binding_loader),
        snapshot_loader=getattr(app.state, "gateway_snapshot_loader", snapshot_loader),
        current_binding_loader=getattr(
            app.state, "gateway_current_binding_loader", current_binding_loader
        ),
        evidence_verifier=getattr(app.state, "gateway_evidence_verifier", evidence_verifier),
        codex_config=codex_config,
    )
    app.state.gateway_runtime = gateway_runtime
    app.state.gateway_service = gateway_runtime.gateway if gateway_runtime else None
    # 回合放后台跑，接收器才有空处理"停止"——在 receive_json 里 await 整轮的话，
    # 用户点停止时那条控制消息正排在一个还没跑完的回合后面。
    # 事件存储：配置了 URL 才有。没有它时事件不带编号，
    # 断线恢复这条路径**不可用**——这一点在事件上看得出来（没有 streamEpoch）。
    app.state.event_store = _build_event_store()
    if gateway_runtime is not None:
        runtime = SessionRuntime(
            interrupt_impl=gateway_runtime.gateway.interrupt_codex_turn,
            steer_impl=gateway_runtime.gateway.steer_codex_turn,
        )
        # 回填给 gateway：回合开始时它要把原生回合号绑上来，
        # 否则"停止"永远找不到目标（返回 unavailable，用户看到的是"不支持"）。
        gateway_runtime.gateway.session_runtime = runtime
        bind_session_runtime(runtime)  # 让 broker 的卡片有地方可推
        app.state.session_runtime = runtime
    else:
        app.state.session_runtime = None
    logger.info("ChatService initialized")
    try:
        yield
    finally:
        if getattr(app.state, "session_runtime", None) is not None:
            await app.state.session_runtime.cancel_all()
        if gateway_runtime is not None:
            await gateway_runtime.close()


app = FastAPI(title="高考志愿填报 Agent", lifespan=lifespan)


def _agent_version() -> str:
    try:
        return metadata.version("zhiyuan-agent")
    except metadata.PackageNotFoundError:
        return "unknown"


@app.get("/health")
@app.get("/gaotu-assistant-agent/health")
async def health_check():
    return {
        "status": "UP",
        "service": "zhiyuan-agent",
        "version": _agent_version(),
    }


async def _handle_ws_loop(ws: WebSocket, service: ChatService):
    """V3 原生协议的 WebSocket 消息处理循环。"""
    while True:
        try:
            data = await ws.receive_json()
            msg = WSMessage.model_validate(data)
            logger.info(
                "Received message: session_id=%s user_id=%s content=%s",
                msg.session_id, msg.user_id, msg.content
            )
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Invalid message format: %s", e)
            resp = WSResponse(
                type="error",
                session_id="",
                content="消息格式错误",
            )
            if not await _safe_send_text(ws, resp.model_dump_json(), context="v3.invalid_message"):
                return
            continue

        if msg.type not in _NON_PERSISTENT_USER_MESSAGE_TYPES:
            try:
                await message_store.save_user_message(
                    chat_session_id=msg.session_id,
                    content=msg.content,
                )
            except Exception:
                logger.exception(
                    "Failed to persist inbound websocket message: session_id=%s",
                    msg.session_id,
                )

        followup_responses: list[WSResponse] = []
        resp: WSResponse | None = None
        try:
            if msg.type in {"planEditSelect", "intentSelect"}:
                reply = await service.handle_intent_select(
                    session_id=msg.session_id,
                    user_id=msg.user_id,
                    content=msg.content,
                )
            elif msg.type == "pendingConfirmation":
                reply = await service.handle_pending_confirmation(
                    session_id=msg.session_id,
                    user_id=msg.user_id,
                    content=msg.content,
                )
            else:
                # 构造进度回调：推送 thinking 消息到前端
                async def on_progress(hint: str, _sid: str = msg.session_id) -> None:
                    thinking = WSResponse(type="thinking", session_id=_sid, content=hint)
                    await _safe_send_text(ws, thinking.model_dump_json(), context="v3.progress")

                reply = await asyncio.wait_for(
                    service.handle_message(
                        session_id=msg.session_id,
                        user_id=msg.user_id,
                        content=msg.content,
                        on_progress=on_progress,
                    ),
                    timeout=_CHAT_SERVICE_TIMEOUT_SECONDS,
                )
            # 提取 followup（方案操作后的工作区刷新通知）
            if isinstance(reply, ChatServiceResponseEnvelope):
                followup_responses = list(reply.followups or [])
                reply = reply.primary

            if _has_primary_reply_content(reply):
                # 如果 reply 已经是 WSResponse（如 card 类型），直接使用
                if isinstance(reply, WSResponse):
                    resp = reply
                else:
                    resp = WSResponse(
                        type="reply",
                        session_id=msg.session_id,
                        content=reply,
                    )
                logger.info(
                    "Sending reply: session_id=%s type=%s content_len=%d",
                    msg.session_id, resp.type, len(resp.content),
                )
        except asyncio.TimeoutError:
            logger.exception(
                "handle_message timed out: session_id=%s timeout_seconds=%s",
                msg.session_id,
                _CHAT_SERVICE_TIMEOUT_SECONDS,
            )
            resp = WSResponse(
                type="reply",
                session_id=msg.session_id,
                content=_build_timeout_reply(msg.content),
            )
        except Exception as e:
            logger.exception("handle_message failed: %s", str(e))
            resp = WSResponse(
                type="error",
                session_id=msg.session_id,
                content="处理消息时出错，请稍后重试",
            )
        if resp is not None:
            if not await _safe_send_text(ws, resp.model_dump_json(), context="v3.reply"):
                return
            if resp.type != "error":
                try:
                    await message_store.save_agent_message(
                        chat_session_id=resp.session_id,
                        ws_type=resp.type,
                        content=resp.content,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist outbound websocket message: session_id=%s type=%s",
                        resp.session_id,
                        resp.type,
                    )

        for followup in followup_responses:
            if followup.type not in {"planningWorkspaceAction", "pendingConfirmationCard"}:
                continue
            try:
                content_obj = json.loads(followup.content)
            except (json.JSONDecodeError, TypeError):
                content_obj = {"type": followup.type, "title": followup.content}
            try:
                await message_store.save_agent_message(
                    chat_session_id=msg.session_id,
                    ws_type=followup.type,
                    content=json.dumps(content_obj, ensure_ascii=False),
                )
            except Exception:
                logger.exception(
                    "Failed to persist v3 followup card: session_id=%s type=%s",
                    msg.session_id, followup.type,
                )
            followup_data = {"type": followup.type, "content": content_obj, "end": True}
            if not await _safe_send_json(ws, followup_data, context="v3.followup"):
                return


async def _handle_gateway_ws_loop(ws: WebSocket, gateway) -> None:
    """Serve stable Gateway events while retaining the v3 WebSocket envelope."""
    runtime = getattr(ws.app.state, "session_runtime", None)
    # 统一约定：队列里放 **dict**，序列化由各路由自己做。
    # 混着放字符串和 dict 会得到 "the JSON object must be str ... not dict"——
    # 一个只在某条路由上出现的错，很难从"控制消息没反应"这个现象倒推回来。
    channel = ConnectionChannel(
        lambda frame: _safe_send_text(ws, _as_text(frame), context="gateway.event"),
        frame_builder=_native_event_frame,
        store=getattr(ws.app.state, "event_store", None),
        on_overflow=lambda: _close_slow_consumer(ws, "native"),
    )
    # 补发要在 `start()` **之前**入队：队列是 FIFO、发送器只有一个，
    # 于是"先补发、后实时"由队列顺序保证，不靠时序假设。
    await _replay_on_connect(ws, runtime, channel)
    channel.start()
    try:
        await _native_gateway_loop(ws, gateway, runtime, channel)
    finally:
        # 连接关了就**摘掉它** ✓✓：不摘的话，这条会话的"当前连接"还是这条死连接 ✗——
        # 而回合的进度与终态走的是"会话当前连接" ✓（见 `_session_emitter` ✓）：事件会发进
        # 死 socket ✗，并且按**那条连接绑的会话**入库 ✗（实测：一条用例的进度落进了
        # 别的会话的流里 ✗，那条会话的页面于是什么都不显示 ✓）。
        # compat 路由早就这么摘了 ✓（见 `_handle_gateway_compat_ws_loop` ✓），native 这条漏了 ✗。
        session_key = getattr(channel, "session_key", None)
        if runtime is not None and session_key is not None and _DETACH_ON_CLOSE:
            runtime.detach_connection(session_key, channel)
        await channel.close()


def _resume_session_key(ws: WebSocket) -> SessionKey | None:
    """补发用的会话键 = **票据里那条会话**，不是 URL 里说的那条。

    票据是**按会话签发**的（`TicketIdentity.session_id` 来自换票响应）。URL 里
    点名另一条会话时，既不补发、也不照它建键——否则"拿 A 的票读 B 的事件"
    就是一条跨会话泄漏。不一致时留一条 warning，让人看得见。
    """
    identity = getattr(ws.state, "identity", None)
    tenant_id = str(getattr(identity, "tenant_id", "") or "")
    granted = str(getattr(identity, "session_id", "") or "").strip()
    asked = str(
        ws.query_params.get("chatSessionId") or ws.query_params.get("sessionId") or ""
    ).strip()
    if not tenant_id or not granted:
        return None
    if asked and asked != granted:
        logger.warning(
            "conversation replay refused: session mismatch (asked=%s granted=%s)", asked, granted
        )
        return None
    return SessionKey(tenant_id=tenant_id, session_id=granted)


async def _replay_on_connect(ws: WebSocket, runtime: object, channel) -> None:
    """断线连上时的补发——**有游标补尾巴、没游标补当前回合**。

    两类断线要的东西不一样：
    · 刷新 → 页面状态被清掉、**没有**游标 → 只能补"还在跑的那一回合"；
    · 短暂断线但页面还活着 → 游标在手，要的是"我漏掉的那几条"
      （可能包含**已经结束**的回合的终态——那正是"补当前回合"补不到的）。
    两条路都由 `event_store.replay` 的同一套语义兜底（代际不符/窗口被裁 → resync）。
    """
    store = getattr(ws.app.state, "event_store", None)
    if store is None or runtime is None:
        return
    key = _resume_session_key(ws)
    if key is None:
        return
    epoch = str(ws.query_params.get("epoch") or "").strip()
    since = str(ws.query_params.get("since") or "").strip()
    if epoch and since.isdigit():
        await _replay_tail(store, runtime, channel, key, epoch, int(since))
        return
    await _replay_active_turn(store, runtime, channel, key)


async def _replay_tail(store, runtime, channel, key: SessionKey, epoch: str, since: int) -> None:
    """按游标补 `since` 之后那一段——游标就是客户端的去重键 `(代际, 序号)`。"""
    channel.bind_session(key)
    turn = runtime.active_turn(key)
    if turn is not None:
        # envelope 的回合号要带上；下一条消息到达时会按那条消息再绑一次。
        channel.bind_turn(turn.ui_turn_id)
    runtime.attach_connection(key, channel)
    events = await store.replay(key, epoch, after=since)
    if events is None:
        # 游标用不了（代际变了 / 窗口被裁 / 游标超前）：这**就是** resync 那一格的用途。
        # 代际给**当前**那个——给客户端手上那个旧的，会让它继续按另一条时间线走。
        watermark = await store.watermark(key)
        await channel.emit_frame(
            resync_snapshot(
                session_id=key.session_id,
                turn_id=turn.ui_turn_id if turn is not None else "",
                stream_epoch=str(await store.current_epoch(key) or ""),
                baseline={"reason": "cursor_unusable", "lastSequence": watermark},
            )
        )
        return
    for event in events:
        await channel.emit_frame(event.model_dump(by_alias=True))


async def _replay_active_turn(store, runtime, channel, key: SessionKey) -> None:
    """把**还在跑的那一回合**补出来（刷新那条路：客户端手上没有游标）。

    只补**当前回合**：已结束的回合落在消息历史里，一起补会让同一个回合在页面上
    出现两次（F10 的 ② 钉的就是这条）。

    两条顺序都不能反（两条补发路径都遵守）：
    1. `session.resync` 在前、补事件在后——反了的话补出来的序号会撞上客户端
       旧基线，被判成缺口 → 永久 resync；
    2. **先登记连接、再读存储**——这中间的实时事件会同时进队列与重放列表
       （客户端按 (代际, 序号) 去重）；先读后登记则会**丢**那条。这套合同里
       "缺口只允许 resync"（A6 不变量），所以宁可重、不可丢。
    """
    turn = runtime.active_turn(key)
    if turn is None:
        return
    epoch = await store.current_epoch(key)
    if epoch is None:
        # 回合在跑、流里却一条都没有：补不出东西，不如不补（也不假装 resync 过）。
        return
    channel.bind_session(key)
    channel.bind_turn(turn.ui_turn_id)
    runtime.attach_connection(key, channel)
    events = await store.replay(key, epoch, after=0)
    watermark = await store.watermark(key)
    if events is None:
        # 补不出来（代际对不上 / 窗口被裁过）：**这**才是 resync 那一格的用途——
        # 把基线重置到水位线，客户端按消息历史重建（它收到这条会去对齐列表）。
        await channel.emit_frame(
            resync_snapshot(
                session_id=key.session_id,
                turn_id=turn.ui_turn_id,
                stream_epoch=epoch,
                baseline={"reason": "window_gone", "lastSequence": watermark},
            )
        )
        return
    # 补得出来就**只补事件、不发 resync**：reducer 的首帧无条件采纳代际与序号，
    # 后面的事件按 +1 连续接上；先发 resync 会把基线设到水位线，反而把补出来的
    # 事件整段判成重复而丢掉（`conversationSession.mjs` 的 resync 分支）。
    for event in events:
        if event.turn_id == turn.ui_turn_id:
            await channel.emit_frame(event.model_dump(by_alias=True))


async def _native_gateway_loop(ws: WebSocket, gateway, runtime, channel) -> None:
    while True:
        try:
            raw = await ws.receive_json()
            msg = WSMessage.model_validate(raw)
        except WebSocketDisconnect:
            # 客户端断开是**正常结束**，不是错误：它一天要发生几百次。
            # 当成异常往上抛会让每次正常关页都在日志里留下一条 error。
            return
        except (json.JSONDecodeError, ValidationError):
            if not await _safe_send_text(
                ws,
                WSResponse(type="error", session_id="", content="消息格式错误").model_dump_json(),
                context="gateway.invalid_message",
            ):
                return
            continue

        # **心跳要当场回** ✓✓：前端每 5s 发一条 `inputType=ping` ✓，而这条路上原本**没有任何
        # 分支接它** ✗ → 它被当成**一轮对话**跑 ✗（每条心跳占一个回合 ✓、真调一次模型 ✓、
        # 失败了再发一条 `recoverable.error` + `turn.completed` ✓）。
        # 后果不止是浪费 ✓✗：客户端会收到一批"凭空出现的新回合" ✓ → 判成缺口 ✓ →
        # 触发重同步、**把在飞回合的界面丢掉** ✗（实测：一轮用例里心跳每 5s 清一次回合块 ✓，
        # 表现成"发消息后回合块不出现" ✓，两条用例因此红 ✓）。
        # compat 那两条路一直都当场回 pong ✓（`_compat_gateway_loop` 与老 compat ✓），
        # 只有 native 这条漏了 ✗。
        if str(raw.get("inputType") or "text") == "ping":
            pong: dict[str, Any] = {"type": "pong"}
            if raw.get("timestamp") is not None:
                pong["timestamp"] = raw["timestamp"]
            if not await _safe_send_text(
                ws, json.dumps(pong, ensure_ascii=False), context="gateway.pong"
            ):
                return
            continue

        turn_id = str(raw.get("turnId") or raw.get("turn_id") or uuid.uuid4())
        tenant_id = str(msg.tenant_id or getattr(ws.app.state, "gateway_tenant_id", "")).strip()
        if not tenant_id:
            response = WSResponse(
                type="recoverable.error",
                session_id=msg.session_id,
                content=json.dumps(
                    {"type": "recoverable.error", "message": "缺少 tenantId，无法执行本轮对话。"},
                    ensure_ascii=False,
                ),
            )
            if not await _safe_send_text(ws, response.model_dump_json(), context="gateway.tenant_missing"):
                return
            continue

        if await _handle_control_message(ws, raw, runtime, tenant_id, channel):
            continue

        key = SessionKey(tenant_id=tenant_id, session_id=str(msg.session_id))
        # **终态与进度都走会话域** ✓✓：一个回合的收尾可能发生在**重连之后** ✓
        #（F10 的刷新 ✓），发到"当初那条连接"上就是永远收不到 ✗（见 `_session_emitter` ✓）。
        emit = _session_emitter(runtime, channel, key)

        async def work(msg=msg, turn_id=turn_id, tenant_id=tenant_id) -> None:
            result = await _run_native_turn(gateway, msg, tenant_id, turn_id, emit)
            await _emit_turn_terminal(
                emit=emit, channel=channel, result=result, session_id=msg.session_id
            )

        # 编号事件要写会话与回合号：它们是 envelope 的必填字段。
        channel.bind_session(key)
        channel.bind_turn(turn_id)
        if runtime is not None:
            # 卡片要推给这个会话的当前连接；不登记的话 broker 只能干等。
            runtime.attach_connection(key, channel)
            verdict = await runtime.submit(
                key,
                client_request_id=str(raw.get("clientRequestId") or turn_id),
                ui_turn_id=turn_id,
                work=work,
            )
        else:
            verdict = ACCEPTED
            await work()
        if verdict == DUPLICATE:
            pass
        elif verdict == BUSY:
            await channel.emit_frame(
                WSResponse(
                    type="recoverable.error",
                    session_id=str(msg.session_id),
                    content=json.dumps(
                        {"type": "recoverable.error", "message": "当前回合还在进行，请先等它结束或点停止。"},
                        ensure_ascii=False,
                    ),
                ).model_dump()
            )
        elif verdict == CONFLICT:
            await channel.emit_frame(
                WSResponse(
                    type="recoverable.error",
                    session_id=str(msg.session_id),
                    content=json.dumps(
                        {"type": "recoverable.error", "message": "同一请求编号对应了不同内容，请重新发起。"},
                        ensure_ascii=False,
                    ),
                ).model_dump()
            )
        continue


def _session_emitter(runtime: object, channel, key: SessionKey):
    """把事件发到**这个会话当前的连接**；没有当前连接时才退回本连接的通道。

    为什么不能只用本连接的通道：一个回合的收尾可能发生在**重连之后**（F10 的刷新）
    ——那时"这条消息当初那条连接"已经关了，往上发就是永远收不到（实测：刷新后放行
    闸门，终态 20 秒到不了，而它其实已经写进事件流了）。`SessionRuntime.publish`
    就是为这件事存在的：它发给该会话**当前**的那一条连接。
    """

    async def emit(event: dict[str, Any]) -> None:
        if runtime is not None and await runtime.publish(key, event):
            return
        await channel.emit(event)

    return emit


def _proposal_preview_payload(preview: Mapping[str, Any]) -> dict[str, Any]:
    """把 Java 的提案预览**翻译成前端合同里的形状** ✓✓（白名单那四个键 ✓）。

    `ui_events.py` 开头那句就是这个意思 ✓："下游只认白名单里的类型，任何原生形状里的
    额外字段都到不了前端" ✓——**翻译归网关** ✓，不该让前端去认 Java 的字段名 ✗。
    实测两边键名对不上 ✓：Java 给的是 `proposalId` / `title` / `summary` / `status` /
    `blockingReason` / … ✓，而白名单要的是 `proposalRef` / `diff` / `sourceVersion` / `expiresAt` ✗
    → 不翻译的话页面拿到的是**空卡** ✓（`sanitizeV1Payload` 会把它过滤成 `{}` ✓）。
    """
    payload: dict[str, Any] = {}
    # **`proposalRef` 优先** ✓✓：网关会把它**换成待确认那一条的 ref** ✓（= `pendingId` ✓，
    # 确认/放弃时服务端拿它核对 ✓）；而 Java 的预览里**同时**带着 `proposalId`（编译器的
    # `ugp_…` ✗）。写成 `proposalId` 优先的话 ✓，网关的覆盖会被**自己这一行**撤销 ✓✗
    #（实测：版本换成了 1 ✓、ref 却始终是 `ugp_…` ✓——两处读数正是这么来的 ✓）。
    ref = preview.get("proposalRef") or preview.get("proposalId")
    if ref:
        payload["proposalRef"] = str(ref)
    if preview.get("sourceVersion") is not None:
        payload["sourceVersion"] = preview["sourceVersion"]
    if preview.get("expiresAt"):
        payload["expiresAt"] = preview["expiresAt"]
    # `diff` 承载**给人看的那部分** ✓（标题/摘要/状态/阻断原因/受影响范围 ✓）——
    # 求解器内部形状（digest / solverResult / dryRunResult 一类）**不进这里** ✗：
    # 它们对用户没有意义，而且会让载荷随求解器版本漂移 ✓。
    payload["diff"] = {
        key: preview[key]
        for key in (
            "title",
            "summary",
            "status",
            "strategy",
            "blockingReason",
            "blockingReasonCodes",
            "requiresConfirmation",
            "affectedUnitIds",
            "candidateShortages",
        )
        if preview.get(key) is not None
    }
    return payload


async def _emit_turn_terminal(*, emit, channel, result: dict, session_id: str) -> None:
    """回合收尾：V1 发事件 ✓、老信封发帧 ✓；**失败走可恢复错误** ✓✓。

    **终态也要走 V1 通道** ✓✓——这是 C4 真栈追出来的最后一格 ✓：替身的 `turn/completed`
    会被 collect 循环**消费**掉 ✓（不经过 `_notification_to_event` ✗，实测：帧里从未出现
    `assistant.completed` ✓），于是答案**只**以老信封的 `reply` 出来 ✗ → 新 UI 的 reducer
    （只认 V1 ✓）看不到答案 ✓。所以**两条都发** ✓：老 UI 靠 `reply` ✓、新 UI 靠 V1 终态 ✓；
    非 V1 帧会被新 reducer 判否 ✓，不会重复渲染 ✓。载荷键照前端白名单 ✓（`conversationEvents.mjs:35-36` ✓）。

    **失败那一支不能发空答案** ✗✓：失败时 `result` 里根本没有 `reply` ✗ → `message` 是空串 ✗ →
    前端的渲染条件是"有终态**且**有答案文本" ✓ → 用户那边**什么都不显示** ✗✗（实测：F15 的
    "模型格式坏"整轮静默 ✓，页面快照里连错误字样都没有 ✓）。老信封那条路本来就有
    `recoverable.error` 的映射 ✓（`_native_reply_frame` ✓，判据同样是 `result.get("error")` ✓）——
    V1 这条漏了 ✗，两条路不对称 ✓。
    """
    if not channel.uses_v1:
        # compat 路由服务的是老 UI ✓：给它发 V1 事件是噪声 ✗。
        # 判据是"这条连接有没有事件存储" ✓（`ConnectionChannel.uses_v1` ✓）。
        await channel.emit_frame(_native_reply_frame(result, session_id))
        return
    error_code = result.get("error")
    if error_code:
        await emit({
            "type": "recoverable.error",
            "payload": {
                # 键名照前端白名单 ✓（`conversationEvents.mjs:37` 只放 `code`/`message` ✓）。
                "code": str(error_code),
                "message": _RECOVERABLE_TURN_FAILURE,
            },
        })
    else:
        # **提案预览要发成事件** ✓✓：网关**早就算好了**它 ✓（`service.py` 里编译 → `proposalPreview` ✓，
        # 实测 `prepare … 状态码: 200` ✓ + 快照重读 ✓），只是这里**没人把它发出去** ✗——
        # 于是页面上永远看不到提案卡 ✓（事件流里一条 `proposal.preview` 都没有 ✓、
        # 而且**不会报错** ✓，所以从外面看像"链路没走到" ✗）。
        # 键名照前端白名单 ✓（`conversationEvents.mjs:33` 只放
        # `proposalRef` / `diff` / `sourceVersion` / `expiresAt` ✓）。
        # **采纳/放弃的结果也要发成事件** ✓✓——与提案预览**同一个病** ✗✓：
        # 网关早把它算好了 ✓（`execute_action_and_refresh` 返回 `actionResult` ✓，含
        # `actionStatus` ∈ {applied, cancelled} ✓），而这里不发的话 ✓，前端那张卡永远停在
        # "待确认" ✗（实测：点了放弃 ✓，事件流里只有 `assistant.completed("操作已处理。")` ✓，
        # 一条 `conversationAction.result` 都没有 ✓）。
        # 键名照前端白名单 ✓（`conversationEvents.mjs:34`：proposalRef / actionStatus /
        # newStateVersion / workspaceVersion ✓）；`workspaceVersion` 在**外层**的
        # `snapshotVersion` 里 ✓（白名单没有 actualChanges/code/message 的位置 ✗，不带 ✓）。
        action_result = result.get("actionResult")
        if isinstance(action_result, Mapping) and action_result:
            action_payload = {
                key: action_result[key]
                for key in ("proposalRef", "actionStatus", "newStateVersion")
                if action_result.get(key) is not None
            }
            if result.get("snapshotVersion") is not None:
                action_payload["workspaceVersion"] = result["snapshotVersion"]
            await emit({"type": "conversationAction.result", "payload": action_payload})
        proposal_preview = result.get("proposalPreview")
        if isinstance(proposal_preview, Mapping) and proposal_preview:
            await emit({
                "type": "proposal.preview",
                "payload": _proposal_preview_payload(proposal_preview),
            })
        await emit({
            "type": "assistant.completed",
            "payload": {
                "message": str(result.get("reply") or ""),
                "responseType": "text",
                "executionStatus": "completed",
                "limitations": [],
            },
        })
    await emit({
        "type": "turn.completed",
        "payload": {
            "executionStatus": "completed",
            "toolStatus": "completed",
            "runtimeStatus": "native",
        },
    })
    await channel.emit_frame(_native_reply_frame(result, session_id))


async def _run_native_turn(gateway, msg, tenant_id: str, turn_id: str, emit) -> dict:
    try:
        if msg.conversation_action is not None:
            snapshot = await gateway.get_current_snapshot(
                tenant_id=tenant_id, session_id=str(msg.session_id)
            )
            if snapshot is None:
                return {"error": "conversation_snapshot_unavailable", "events": []}
            result = await gateway.execute_action_and_refresh(
                tenant_id=tenant_id,
                session_id=msg.session_id,
                action=msg.conversation_action,
                snapshot=snapshot,
            )
            result["reply"] = "操作已处理。"
            result["events"] = []
            return result
        return await gateway.handle_turn(
            tenant_id=tenant_id,
            session_id=msg.session_id,
            user_id=msg.user_id,
            turn_id=turn_id,
            content=msg.content,
            emit=emit,
        )
    except Exception:
        logger.exception("Gateway turn failed: session_id=%s turn_id=%s", msg.session_id, turn_id)
        return {
            "reply": "当前对话引擎暂时不可用，请稍后重试。",
            "events": [],
            "error": "gateway_failure",
        }


def _native_event_frame(event: dict) -> dict:
    """把一个 v1 事件包成 v3 信封。

    `WSResponse.type` 是一个**冻结的旧 Literal**，新事件名塞进去会被它自己拒绝
    （实测：tool.progress 直接触发 ValidationError，前端收到的是"事件格式错误"）。
    所以这里把 v1 事件映射到旧信封已有的类型上，而不是去放宽那个 Literal——
    放宽会让所有老客户端收到它们解析不了的帧。
    """
    payload = event.get("payload") or {}
    return WSResponse(
        type=_LEGACY_FRAME_TYPE.get(str(event.get("type")), "planning.status"),
        session_id=str(payload.get("sessionId") or event.get("sessionId") or ""),
        content=json.dumps(
            {
                "type": event.get("type"),
                "stage": payload.get("status"),
                "message": payload.get("label") or "",
                "itemId": payload.get("itemId"),
                "clarification": payload.get("clarification"),
                "requestId": payload.get("requestId"),
            },
            ensure_ascii=False,
        ),
    ).model_dump()


# v1 事件 → 旧信封里已有的类型。没有对应项的一律走 planning.status（旧前端把它
# 当"正在处理中"的进度提示渲染，不会误解成答案）。
_LEGACY_FRAME_TYPE = {
    "tool.progress": "planning.status",
    "turn.phase": "planning.status",
    "understanding.preview": "thinking",
    "clarification.requested": "card",
    "proposal.preview": "card",
    "conversationAction.result": "planningWorkspaceAction",
    "recoverable.error": "recoverable.error",
}


def _native_reply_frame(result: dict, session_id) -> str:
    response_type = "recoverable.error" if result.get("error") else "reply"
    response_content = result.get("reply") or ""
    if result.get("actionResult") is not None:
        response_content = json.dumps(
            {
                "type": "conversationAction.result",
                "message": response_content,
                "actionResult": result["actionResult"],
                "snapshotVersion": result.get("snapshotVersion"),
            },
            ensure_ascii=False,
        )
    elif result.get("proposalPreview") is not None:
        response_content = json.dumps(
            {
                "type": "proposal.preview",
                "message": response_content,
                "proposalPreview": result["proposalPreview"],
                "snapshotVersion": result.get("snapshotVersion"),
            },
            ensure_ascii=False,
        )
    if response_type == "recoverable.error":
        response_content = json.dumps(
            {"type": response_type, "message": response_content}, ensure_ascii=False
        )
    return WSResponse(
        type=response_type,
        session_id=session_id,
        content=str(response_content),
    ).model_dump()


async def _handle_gateway_compat_ws_loop(
    ws: WebSocket, gateway, tenant_id: str, bot_id: str
) -> None:
    """Translate the legacy agent-plus envelope into Gateway turns.

    The compatibility route remains intentionally thin: Gateway owns turn
    execution and persistence, while this adapter only handles ping and the
    field-name differences expected by the existing frontend.
    """
    del bot_id
    runtime = getattr(ws.app.state, "session_runtime", None)
    session_key = None
    channel = ConnectionChannel(
        lambda frame: _safe_send_json(ws, _as_mapping(frame), context="compat.gateway.event"),
        frame_builder=_compat_event_frame,
        store=getattr(ws.app.state, "event_store", None),
        on_overflow=lambda: _close_slow_consumer(ws, "compat"),
    )
    channel.start()
    try:
        await _compat_gateway_loop(ws, gateway, tenant_id, runtime, channel)
    finally:
        if runtime is not None:
            for key in list(getattr(runtime, "_channels", {})):
                runtime.detach_connection(key, channel)
        await channel.close()


def _as_text(frame) -> str:
    return frame if isinstance(frame, str) else json.dumps(frame, ensure_ascii=False)


def _as_mapping(frame) -> dict:
    if isinstance(frame, dict):
        return frame
    parsed = json.loads(frame)
    if not isinstance(parsed, dict):
        raise ValueError("compat_frame_must_be_an_object")
    return parsed


# 回合失败时给用户看的话 ✓：与 `_run_native_turn` 兜底那条**同一句** ✓——
# 两处文案不一致的话，"同一类失败"在两条路上会长得不一样 ✓。
_RECOVERABLE_TURN_FAILURE = "当前对话引擎暂时不可用，请稍后重试。"

# 连接关闭时是否**摘掉**它（`detach_connection`）✓——**待裁决，默认关** ✗✓。
# 开着的理由：不摘的话，这条会话的"当前连接"还是这条死连接 ✗，而回合的进度与终态走的是
# "会话当前连接" ✓（`_session_emitter` ✓）——事件会发进死 socket ✗。
# 关着的理由（实测）：打开之后全套开始**发飘** ✗——同一批用例两轮结果不同 ✓
# （test4/F12 在"回合块没出现"上红 ✓，账本里成对出现 60s 超时 ✗），而它们的改动面
# 与那两处无关 ✓。所以先按"一次只动一个变量"退回来 ✓，等把飘的机理查清再决定 ✓。
_DETACH_ON_CLOSE = os.environ.get("CODEX_DETACH_ON_CLOSE", "0") == "1"

_CONTROL_FAILURE_TEXT = {
    "no_active_turn": "这个回合已经结束了，可以直接发新消息。",
    "turn_mismatch": "这条补充或停止不对应当前进行中的回合。",
    "unavailable": "当前引擎不支持停止或补充。",
}


async def _handle_control_message(ws, raw, runtime, tenant_id, channel) -> bool:
    """控制消息在**接收器里就地处理**，不排进回合队列。

    这正是"接收器不能被回合堵住"的意义所在：用户点停止时，那条消息必须
    立刻被读到并处理，而不是排在还没跑完的回合后面。
    返回 True 表示这条已处理完，不该再走回合分支。
    """
    message_type = str(raw.get("type") or "")
    if message_type == "clarificationAnswer":
        return await _handle_clarification_answer(ws, raw, tenant_id, channel)
    if message_type not in {"turnInterrupt", "turnSteer"}:
        return False
    session_id = str(raw.get("sessionId") or "").strip()
    turn_id = str(raw.get("turnId") or raw.get("turn_id") or "")
    if runtime is None or not session_id:
        await channel.emit_frame(
            {
                "type": "recoverable.error",
                "content": _CONTROL_FAILURE_TEXT["unavailable"],
                "end": False,
            }
        )
        return True
    key = SessionKey(tenant_id=str(tenant_id), session_id=session_id)
    if message_type == "turnInterrupt":
        outcome = await runtime.interrupt(key, turn_id)
        ack_type = "turn.interrupt"
    else:
        outcome = await runtime.steer(key, turn_id, str(raw.get("content") or ""))
        ack_type = "turn.steer"
    status = str(outcome.get("status"))
    if status in _CONTROL_FAILURE_TEXT:
        # 不能假装"收到了"：回合可能已经结束，用户需要知道这条没生效。
        await channel.emit_frame(
            {"type": "recoverable.error", "content": _CONTROL_FAILURE_TEXT[status], "end": False}
        )
    else:
        await channel.emit_frame({"type": ack_type, "content": "", "end": False})
    return True


async def _handle_clarification_answer(ws, raw, tenant_id, channel) -> bool:
    """把用户的作答送回 broker，由它用**原来的 rpc id** 回给 Codex。"""
    broker = getattr(getattr(ws.app.state, "gateway_service", None), "user_input_broker", None)
    if broker is None:
        await channel.emit_frame(
            {"type": "recoverable.error", "content": "当前引擎不支持回答这张卡。", "end": False}
        )
        return True
    answer = raw.get("clarificationAnswer") or {}
    request_id = str(answer.get("requestId") or "")
    key = SessionKey(tenant_id=str(tenant_id), session_id=str(raw.get("sessionId") or ""))
    try:
        outcome = await broker.answer(key, request_id, answer)
    except PermissionError:
        # 跨会话作答是越权：拒绝，并且不告诉对方"那张卡存在"。
        await channel.emit_frame(
            {"type": "recoverable.error", "content": "这张卡不属于当前会话。", "end": False}
        )
        return True
    except UserInputError as exc:
        await channel.emit_frame(
            {"type": "recoverable.error", "content": f"答案未被接受：{exc.code}", "end": False}
        )
        return True
    status = str(outcome.get("status"))
    if status in {"unknown_request", "already_answered"}:
        await channel.emit_frame(
            {"type": "recoverable.error", "content": "这张卡已失效，请以最新一轮为准。", "end": False}
        )
    elif status == "conflict":
        await channel.emit_frame(
            {"type": "recoverable.error", "content": "同一张卡收到了不同答案，请刷新后重试。", "end": False}
        )
    else:
        await channel.emit_frame({"type": "clarification.resolved", "content": "", "end": False})
    return True


def _build_access_guard() -> ConversationAccessGuard:
    """票据守卫。来源白名单与 Java 侧同源，不做通配。

    白名单来自配置而不是写死：本地与测试域名是两个不同的来源，
    写死一个会让另一个环境**悄悄拒掉所有连接**。
    """
    origins = tuple(
        item.strip()
        for item in (os.environ.get("CODEX_WS_ALLOWED_ORIGINS") or "").split(",")
        if item.strip()
    ) or ("http://127.0.0.1:3201",)
    return ConversationAccessGuard(internal_client.consume_ws_ticket, allowed_origins=origins)


async def _verify_conversation_access(ws: WebSocket):
    """在 **accept 之前**校验票据。

    先 accept 再校验等于先开了一条匿名通道——连接建立了、消息能发了，
    再关掉只是"事后补票"。
    """
    guard = getattr(ws.app.state, "conversation_access_guard", None)
    if guard is None:
        guard = _build_access_guard()
        ws.app.state.conversation_access_guard = guard
    try:
        return await guard.verify(
            ws.query_params.get("ticket"),
            ws.headers.get("origin"),
        )
    except AccessDenied as denied:
        # 未 accept 时 close：ASGI 会把它变成握手拒绝，而不是一条已建立的连接。
        await ws.close(code=4401 if denied.status == 401 else 4403)
        logger.info("conversation handshake rejected: %s", denied.reason)
        return None


def _build_event_store():
    """按配置建事件存储。没配置就回 None——**不退回进程内存**：

    进程内的"事件流"在重启后是另一条时间线，客户端拿旧 cursor 去接会静默错位。
    """
    from app.config import ConversationEventStoreConfig

    config = ConversationEventStoreConfig()
    if not config.redis_url:
        return None
    from app.gateway.event_store import RedisEventStore

    return RedisEventStore(
        config.redis_url,
        ttl_seconds=config.ttl_seconds,
        max_events=config.max_events,
        max_event_bytes=config.max_event_bytes,
    )


async def _close_slow_consumer(ws: WebSocket, route: str) -> None:
    """慢消费者：关掉这条连接，让它重连后 resume，而不是拖住模型 reader。"""
    logger.warning("closing slow websocket consumer on %s route", route)
    try:
        await ws.close()
    except Exception:  # 关闭失败没有补救手段，也不该掩盖原始原因
        pass


async def _compat_gateway_loop(ws, gateway, tenant_id: str, runtime, channel) -> None:
    while True:
        try:
            raw = await ws.receive_json()
        except WebSocketDisconnect:
            return
        except (json.JSONDecodeError, TypeError):
            await _safe_send_json(
                ws,
                {"type": "error", "content": "消息格式错误", "end": True},
                context="compat.gateway.invalid_message",
            )
            continue

        if str(raw.get("inputType") or "text") == "ping":
            pong = {"type": "pong"}
            if "timestamp" in raw:
                pong["timestamp"] = raw["timestamp"]
            if not await _safe_send_json(ws, pong, context="compat.gateway.pong"):
                return
            continue

        if await _handle_control_message(ws, raw, runtime, tenant_id, channel):
            continue

        session_id = str(raw.get("sessionId") or "").strip()
        user_id = str(raw.get("userId") or "").strip()
        content = raw.get("content", "")
        action = raw.get("conversationAction")
        if action is None and isinstance(content, dict):
            raw_action = str(content.get("action") or "").strip().lower()
            if raw_action in {"confirm", "accept", "apply", "cancel", "reject"}:
                action = {
                    "actionType": "confirm_proposal"
                    if raw_action in {"confirm", "accept", "apply"}
                    else "cancel_proposal",
                    "proposalRef": content.get("proposalRef") or content.get("pendingId"),
                    "expectedSourceVersion": content.get("expectedSourceVersion")
                    or content.get("sourceVersion"),
                    "intent": "explicit",
                }
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        if not session_id or not user_id or not str(content).strip() and action is None:
            await _safe_send_json(
                ws,
                {"type": "error", "content": "消息格式错误", "end": True},
                context="compat.gateway.validation_error",
            )
            continue

        turn_id = str(raw.get("turnId") or raw.get("turn_id") or uuid.uuid4())
        key = SessionKey(tenant_id=str(tenant_id), session_id=session_id)

        async def work() -> None:
            try:
                result = await _run_compat_turn(
                    gateway,
                    action,
                    tenant_id,
                    session_id,
                    user_id,
                    turn_id,
                    content,
                    channel=channel,
                )
            except Exception:
                logger.exception(
                    "Gateway compat turn failed: tenant=%s session=%s turn=%s",
                    tenant_id,
                    session_id,
                    turn_id,
                )
                result = {
                    "error": "gateway_failure",
                    "reply": "当前对话引擎暂时不可用，请稍后重试。",
                }
            # 终态走**同一条队列**：直接写 socket 会和事件抢，
            # 结果就是前端先看到答案、后看到"正在查询"。
            await channel.emit_frame(_compat_reply_frame(result))

        channel.bind_session(key)
        channel.bind_turn(turn_id)
        if runtime is not None:
            runtime.attach_connection(key, channel)
            verdict = await runtime.submit(
                key,
                client_request_id=str(raw.get("clientRequestId") or turn_id),
                ui_turn_id=turn_id,
                work=work,
            )
        else:
            verdict = ACCEPTED
            await work()
        if verdict == DUPLICATE:
            # 同 id 同内容是重发：不重跑，也不报错——对方上次多半只是没收到回包。
            pass
        elif verdict == BUSY:
            # 不排队、不取消上一轮：用户的诉求不能被后一句话悄悄作废。
            await channel.emit_frame(
                {
                    "type": "recoverable.error",
                    "content": "当前回合还在进行，请先等它结束或点停止。",
                    "end": False,
                }
            )
        elif verdict == CONFLICT:
            await channel.emit_frame(
                {
                    "type": "recoverable.error",
                    "content": "同一请求编号对应了不同内容，请重新发起。",
                    "end": False,
                }
            )
        continue


async def _run_compat_turn(
    gateway, action, tenant_id, session_id, user_id, turn_id, content, channel=None
):
    if action is not None:
        snapshot = await gateway.get_current_snapshot(
            tenant_id=str(tenant_id), session_id=session_id
        )
        if snapshot is None:
            return {
                "error": "conversation_snapshot_unavailable",
                "reply": "当前确认内容已失去上下文，请重新生成预览。",
            }
        result = await gateway.execute_action_and_refresh(
            tenant_id=str(tenant_id),
            session_id=session_id,
            action=action,
            snapshot=snapshot,
        )
        result["reply"] = "操作已处理。"
        return result
    kwargs = {}
    if channel is not None:
        kwargs["emit"] = channel.emit
    return await gateway.handle_turn(
        tenant_id=str(tenant_id),
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        content=str(content),
        **kwargs,
    )


def _compat_event_frame(event: dict) -> dict:
    """compat 侧没有类型白名单，但**帧形状**必须与终态一致（type/content/end），
    否则老前端会在自己的解析器里漏掉它。"""
    return {
        "type": str(event.get("type") or "planning.status"),
        "content": json.dumps(event.get("payload") or {}, ensure_ascii=False),
        "end": False,
    }


def _compat_reply_frame(result: dict) -> dict:
    """把回合结果拼成 compat 的终态帧。形状与改动前逐字一致。"""
    response_type = "error" if result.get("error") else "text"
    response_content = result.get("reply") or ""
    if result.get("actionResult") is not None:
        response_content = json.dumps(
            {
                "type": "conversationAction.result",
                "message": response_content,
                "actionResult": result["actionResult"],
                "snapshotVersion": result.get("snapshotVersion"),
            },
            ensure_ascii=False,
        )
    elif result.get("proposalPreview") is not None:
        response_content = json.dumps(
            {
                "type": "proposal.preview",
                "message": response_content,
                "proposalPreview": result["proposalPreview"],
                "snapshotVersion": result.get("snapshotVersion"),
            },
            ensure_ascii=False,
        )
    return {"type": response_type, "content": str(response_content), "end": True}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    identity = await _verify_conversation_access(ws)
    if identity is None:
        return
    await ws.accept()
    ws.state.identity = identity
    logger.info("WebSocket connection accepted (v3 protocol)")
    gateway = getattr(ws.app.state, "gateway_service", None)
    if gateway is not None:
        await _handle_gateway_ws_loop(ws, gateway)
        return
    service: ChatService = ws.app.state.chat_service
    try:
        await _handle_ws_loop(ws, service)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")


# ── 兼容 agent-plus 前端协议 ──────────────────────────────────────
# 前端连接路径: /gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do
# 入站格式:  {"sessionId": "...", "userId": "...", "content": "...", "inputType": "text|ping|planEditSelect|intentDetectSelect|intentSelect|pendingConfirmation"}
# 出站格式:  前端 onMessage 只检查 type!="pong" 后触发 fetchMessageList，
#           实际渲染走消息存储，所以响应格式不关键。

_INPUT_TYPE_MAP = {
    "text": "chat",
    "planEditSelect": "planEditSelect",
    "intentDetectSelect": "intentSelect",
    "intentSelect": "intentSelect",
    "pendingConfirmation": "pendingConfirmation",
}


@app.websocket("/gaotu-assistant-agent/plus/chat/{tenant_id}/bot/{bot_id}/do")
async def ws_chat_compat(ws: WebSocket, tenant_id: str, bot_id: str):
    """兼容 agent-plus 前端协议的 WebSocket 端点。

    将 plus 格式的消息（sessionId/userId/content/inputType）转换为 v3 格式
    （session_id/user_id/content/type），然后复用同一套处理逻辑。
    """
    identity = await _verify_conversation_access(ws)
    if identity is None:
        return
    # 路径里的 tenant/bot 是**客户端给的**：与票据不符即拒。
    # 不校验的话，任何持票用户都能把请求打到别的租户上。
    if str(tenant_id) != identity.tenant_id or (
        identity.bot_id is not None and str(bot_id) != identity.bot_id
    ):
        await ws.close(code=4403)
        logger.info("conversation handshake rejected: path identity mismatch")
        return
    await ws.accept()
    ws.state.identity = identity
    logger.info("WebSocket connection accepted (compat protocol)")
    gateway = getattr(ws.app.state, "gateway_service", None)
    if gateway is not None:
        await _handle_gateway_compat_ws_loop(ws, gateway, tenant_id, bot_id)
        return
    service: ChatService = ws.app.state.chat_service
    registered_session_id = await _compat_connections.register(
        ws.query_params.get("chatSessionId") or ws.query_params.get("sessionId"),
        ws,
    )
    try:
        while True:
            try:
                raw = await ws.receive_json()
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Invalid JSON from compat ws: %s", e)
                continue

            input_type = raw.get("inputType", "text")

            # 心跳
            if input_type == "ping":
                pong = {"type": "pong"}
                if "timestamp" in raw:
                    pong["timestamp"] = raw["timestamp"]
                if not await _safe_send_json(ws, pong, context="compat.pong"):
                    return
                continue

            # 转换为 v3 WSMessage 格式
            raw_content = raw.get("content", "")
            # 选择确认类消息时前端 content 是 object，需要序列化为字符串
            if isinstance(raw_content, dict):
                raw_content = json.dumps(raw_content, ensure_ascii=False)

            v3_data = {
                "session_id": str(raw.get("sessionId", "")),
                "user_id": raw.get("userId", ""),
                "content": raw_content,
                "type": _INPUT_TYPE_MAP.get(input_type, "chat"),
            }

            try:
                msg = WSMessage.model_validate(v3_data)
            except ValidationError as e:
                logger.warning("Compat message validation failed: %s", e)
                if not await _safe_send_json(ws, {"type": "error", "content": "消息格式错误", "end": True}, context="compat.validation_error"):
                    return
                continue

            if msg.session_id and msg.session_id != registered_session_id:
                if registered_session_id:
                    await _compat_connections.unregister(registered_session_id, ws)
                registered_session_id = await _compat_connections.register(msg.session_id, ws)

            if msg.type not in _NON_PERSISTENT_USER_MESSAGE_TYPES:
                try:
                    await message_store.save_user_message(
                        chat_session_id=msg.session_id,
                        content=msg.content,
                    )
                except Exception:
                    logger.exception("Failed to persist inbound compat message: session_id=%s", msg.session_id)

            followup_responses: list[WSResponse] = []
            resp_data: dict | None = None
            already_saved = False
            try:
                if msg.type in {"planEditSelect", "intentSelect"}:
                    reply = await service.handle_intent_select(
                        session_id=msg.session_id,
                        user_id=msg.user_id,
                        content=msg.content,
                    )
                elif msg.type == "pendingConfirmation":
                    reply = await service.handle_pending_confirmation(
                        session_id=msg.session_id,
                        user_id=msg.user_id,
                        content=msg.content,
                    )
                else:
                    # 构造进度回调：推送 thinking 消息（compat 格式）
                    async def on_progress_compat(hint: str, _sid: str = msg.session_id) -> None:
                        await _safe_send_compat_json(
                            ws,
                            _sid,
                            {"type": "thinking", "content": hint, "end": False},
                            context="compat.progress",
                        )

                    reply = await asyncio.wait_for(
                        service.handle_message(
                            session_id=msg.session_id,
                            user_id=msg.user_id,
                            content=msg.content,
                            on_progress=on_progress_compat,
                        ),
                        timeout=_CHAT_SERVICE_TIMEOUT_SECONDS,
                    )
                if isinstance(reply, ChatServiceResponseEnvelope):
                    followup_responses = list(reply.followups or [])
                    reply = reply.primary

                if not _has_primary_reply_content(reply):
                    resp_data = None
                    already_saved = True
                elif isinstance(reply, WSResponse):
                    # 转换为前端期望的格式(类似2.0版本)
                    resp_type = reply.type
                    if resp_type in {
                        "interestAnalysisPopup",
                        "planEditSelectPopup",
                        "intentDetectSelectPopup",
                        "intentConfirmPopup",
                        "pendingConfirmationCard",
                    }:
                        # content 是 JSON 字符串，解析为对象
                        try:
                            content_obj = json.loads(reply.content)
                        except (json.JSONDecodeError, TypeError):
                            content_obj = {"type": resp_type, "title": reply.content}

                        # plus 流程：先存 CARD → 拿到 message_id → 注入 → 再发前端
                        try:
                            mid = await message_store.save_agent_message(
                                chat_session_id=msg.session_id,
                                ws_type=resp_type,
                                content=json.dumps(content_obj, ensure_ascii=False),
                            )
                            if mid:
                                content_obj["message_id"] = mid
                        except Exception:
                            logger.exception(
                                "Failed to persist intent confirmation popup message: session_id=%s",
                                msg.session_id,
                            )
                        resp_data = {"type": resp_type, "content": content_obj, "end": True}
                        already_saved = True
                    elif resp_type == "planningWorkspaceAction":
                        try:
                            content_obj = json.loads(reply.content)
                        except (json.JSONDecodeError, TypeError):
                            content_obj = {"type": "planningWorkspaceAction", "title": reply.content}

                        try:
                            await message_store.save_agent_message(
                                chat_session_id=msg.session_id,
                                ws_type="planningWorkspaceAction",
                                content=json.dumps(content_obj, ensure_ascii=False),
                            )
                        except Exception:
                            logger.exception(
                                "Failed to persist planningWorkspaceAction message: session_id=%s",
                                msg.session_id,
                            )
                        resp_data = {"type": "planningWorkspaceAction", "content": content_obj, "end": True}
                        already_saved = True
                    elif resp_type == "card":
                        resp_data = {"type": "text", "content": reply.content, "end": True}
                        already_saved = False
                    else:
                        resp_data = {"type": "text", "content": reply.content, "end": True}
                        already_saved = False
                else:
                    resp_data = {"type": "text", "content": reply, "end": True}
                    already_saved = False

                if resp_data is not None:
                    logger.info(
                        "Sending compat reply: session_id=%s type=%s",
                        msg.session_id, resp_data.get("type"),
                    )
                else:
                    logger.info(
                        "Skipping empty compat primary reply: session_id=%s followups=%d",
                        msg.session_id,
                        len(followup_responses),
                    )
            except asyncio.TimeoutError:
                logger.exception(
                    "handle_message timed out (compat): session_id=%s timeout_seconds=%s",
                    msg.session_id,
                    _CHAT_SERVICE_TIMEOUT_SECONDS,
                )
                resp_data = {"type": "text", "content": _build_timeout_reply(msg.content), "end": True}
                already_saved = False
            except Exception as e:
                logger.exception("handle_message failed (compat): %s", str(e))
                resp_data = {"type": "error", "content": "处理消息时出错，请稍后重试", "end": True}
                already_saved = False

            if resp_data is not None and resp_data.get("type") != "error" and not already_saved:
                try:
                    ws_type = resp_data.get("type", "reply")
                    content_val = resp_data.get("content", "")
                    # save_agent_message expects string content
                    if isinstance(content_val, dict):
                        content_str = json.dumps(content_val, ensure_ascii=False)
                    else:
                        content_str = content_val
                    await message_store.save_agent_message(
                        chat_session_id=msg.session_id,
                        ws_type=ws_type,
                        content=content_str,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist outbound compat message: session_id=%s",
                        msg.session_id,
                    )

            if resp_data is not None:
                if not await _safe_send_compat_json(ws, msg.session_id, resp_data, context="compat.reply"):
                    return

            for followup in followup_responses:
                if followup.type not in {"planningWorkspaceAction", "pendingConfirmationCard"}:
                    continue
                try:
                    content_obj = json.loads(followup.content)
                except (json.JSONDecodeError, TypeError):
                    content_obj = {"type": followup.type, "title": followup.content}

                try:
                    await message_store.save_agent_message(
                        chat_session_id=msg.session_id,
                        ws_type=followup.type,
                        content=json.dumps(content_obj, ensure_ascii=False),
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist followup card message: session_id=%s type=%s",
                        msg.session_id, followup.type,
                    )

                logger.info(
                    "Sending compat followup: session_id=%s type=%s title=%s",
                    msg.session_id, followup.type, content_obj.get("title"),
                )
                if not await _safe_send_compat_json(
                    ws,
                    msg.session_id,
                    {"type": followup.type, "content": content_obj, "end": True},
                    context="compat.followup",
                ):
                    return
    except WebSocketDisconnect:
        logger.info("Compat WebSocket client disconnected tenant=%s", tenant_id)
    finally:
        if registered_session_id:
            await _compat_connections.unregister(registered_session_id, ws)
