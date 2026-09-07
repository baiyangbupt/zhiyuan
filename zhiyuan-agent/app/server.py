from __future__ import annotations

import json
import logging
import asyncio
import uuid
from importlib import metadata
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import GatewayConfig, HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.data.message_store import message_store
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

    llm_client = LLMClient()
    db_path = HistoryConfig().db_path
    history_store = ChatHistoryStore(db_path)
    app.state.chat_service = ChatService(llm_client, history_store)
    gateway_config = GatewayConfig()
    app.state.gateway_mode = gateway_config.mode
    # A production GatewayService is injected by the deployment composition
    # after trusted binding and Codex sidecar wiring are available.  Keeping
    # this unset preserves the fully compatible legacy path by default and
    # fails closed when codex mode is configured without those dependencies.
    app.state.gateway_service = None
    if gateway_config.mode != "legacy":
        logger.warning(
            "GATEWAY_MODE=%s requested but no trusted GatewayService was injected; using legacy path",
            gateway_config.mode,
        )
    logger.info("ChatService initialized")
    yield


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
    while True:
        try:
            raw = await ws.receive_json()
            msg = WSMessage.model_validate(raw)
        except (json.JSONDecodeError, ValidationError):
            if not await _safe_send_text(
                ws,
                WSResponse(type="error", session_id="", content="消息格式错误").model_dump_json(),
                context="gateway.invalid_message",
            ):
                return
            continue

        turn_id = str(raw.get("turnId") or raw.get("turn_id") or uuid.uuid4())
        tenant_id = str(getattr(ws.app.state, "gateway_tenant_id", ""))
        try:
            result = await gateway.handle_turn(
                tenant_id=tenant_id,
                session_id=msg.session_id,
                user_id=msg.user_id,
                turn_id=turn_id,
                content=msg.content,
            )
        except Exception:
            logger.exception("Gateway turn failed: session_id=%s turn_id=%s", msg.session_id, turn_id)
            result = {
                "reply": "当前对话引擎暂时不可用，请稍后重试。",
                "events": [],
                "error": "gateway_failure",
            }

        for event in result.get("events", []):
            event_type = str(event.get("type") or "planning.status")
            try:
                event_response = WSResponse(
                    type=event_type,
                    session_id=msg.session_id,
                    content=json.dumps(event, ensure_ascii=False),
                )
            except ValidationError:
                event_response = WSResponse(
                    type="recoverable.error",
                    session_id=msg.session_id,
                    content=json.dumps({"type": "recoverable.error", "message": "事件格式错误"}, ensure_ascii=False),
                )
            if not await _safe_send_text(
                ws, event_response.model_dump_json(), context="gateway.event"
            ):
                return

        response_type = "recoverable.error" if result.get("error") else "reply"
        response_content = result.get("reply") or ""
        if response_type == "recoverable.error":
            response_content = json.dumps(
                {"type": response_type, "message": response_content}, ensure_ascii=False
            )
        response = WSResponse(
            type=response_type,
            session_id=msg.session_id,
            content=str(response_content),
        )
        if not await _safe_send_text(ws, response.model_dump_json(), context="gateway.reply"):
            return


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
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
    await ws.accept()
    logger.info("WebSocket connection accepted (compat protocol) tenant=%s bot=%s", tenant_id, bot_id)
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
