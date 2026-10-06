from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.gateway.ui_events import TOOL_LABELS


UNKNOWN_TOOL_TOKEN = "domain"
UNKNOWN_TOOL_LABEL = "正在处理查询"


def _text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def adapt_notification(notification: Mapping[str, Any], ui_turn_id: str) -> list[dict[str, Any]]:
    """把一条原生通知翻译成**未编号**的展示事件。

    这是一个白名单过滤器，不是转换器：只有明确列举的形状会出去，其余一律丢弃。
    被丢弃的里面有一类值得点名——reasoning（`item/reasoning/textDelta`）是模型的
    内部推理，永不外发。

    `item/agentMessage/delta` 自 2026-10-06 起**开始流式发送** ✓（此前被整类丢弃 ✗，
    理由是"它是尚未闭合的 TurnOutput JSON" ✓）。裁决（任务书）是：
    · 它是**可丢弃的提示事件** ✓——丢一条不影响正确性 ✓，终态才是权威 ✓；
    · 因此原样流出的 JSON 片段（如 `{"message": "…`）只用于降低首字延迟感知 ✓，
      前端在 `assistant.completed` 到达时**整段替换**为解析后的答案 ✓；
    · 合流/节流由 `_progress_emitter` 负责 ✓（≥64 字符或 ≥80ms 一次 ✓，见 `service.py` ✓）。
    载荷形状 `{chunk, itemId?}` ✓（最小形状 ✓；`itemId` 缺省不填 ✓——替身就不带它 ✓）。
    （`ui_turn_id` 不入 payload：编号与 turn 归属是调用方 envelope 的职责，
    不在这里从原生 turnId 覆盖。）
    """
    if not isinstance(notification, Mapping):
        return []
    method = str(notification.get("method") or "")
    params = notification.get("params")
    if not isinstance(params, Mapping):
        params = {}

    if method in {"item/agentMessage/delta", "agentMessage/delta"}:
        chunk = _text(params, "delta", "text", "content")
        if not chunk:
            return []
        payload: dict[str, Any] = {"chunk": chunk}
        item_id = _text(params, "itemId", "item_id")
        if item_id:
            payload["itemId"] = item_id
        return [{"type": "assistant.delta", "payload": payload}]

    if method in {"item/started", "item/completed"}:
        item = params.get("item")
        if not isinstance(item, Mapping) or item.get("type") != "mcpToolCall":
            return []
        tool = _text(item, "tool")
        known = tool in TOOL_LABELS
        if method == "item/started":
            status = "started"
        else:
            status = "failed" if _text(item, "status") == "failed" else "completed"
        return [
            {
                "type": "tool.progress",
                "payload": {
                    "itemId": _text(item, "id"),
                    # 未知工具只给统一占位：名字本身可能带业务信息（学校、专业），
                    # 而"这个工具我们没见过"不是用户需要知道的事。
                    "tool": tool if known else UNKNOWN_TOOL_TOKEN,
                    "status": status,
                    "label": TOOL_LABELS.get(tool, UNKNOWN_TOOL_LABEL),
                },
            }
        ]

    # 终态（turn.completed / assistant.completed）**不在这里产生**：
    # 它们必须携带经过业务校验的 executionStatus 与 toolStatus，只能由
    # 回合 worker 发一次。适配器再发一份就变成设计明令禁止的"两份终态"。
    return []


def adapt_codex_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Convert Codex notifications into the stable, user-visible event set."""
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if item_type in {"item/agentMessage/delta", "agentMessage/delta", "assistant.delta"}:
        # 形状与 live 那条路**同一份** ✓（`adapt_notification` 的 delta 分支 ✓）：
        # `{chunk, itemId?}` ✓。此前这里是老形状 `content` ✗（V1 白名单模型没有这个
        # 字段 ✓，到前端会被整条丢掉 ✓）——统一成 payload 形状后，两条路的产物一致 ✓，
        # 前端只需要认一种 ✓。
        chunk = _text(item, "delta", "text", "content")
        if not chunk:
            return None
        payload: dict[str, Any] = {"chunk": chunk}
        item_id = _text(item, "itemId", "item_id")
        if item_id:
            payload["itemId"] = item_id
        return {"type": "assistant.delta", "payload": payload}
    if item_type in {"turn/completed", "item/agentMessage/completed", "assistant.completed"}:
        # **形状按 V1 白名单来** ✓✓（那是契约本身 ✓）：前端 `assistant.completed` 的载荷键是
        # `message/responseType/executionStatus/limitations` ✓（`conversationEvents.mjs:35` ✓）。
        # 先前这里给的是 `content` ✗——V1 模型**没有这个字段** ✗，于是它被丢掉 ✓：
        # 答案文本到了、形状对不上 ✓（实测：帧到了、UI 渲染不出答案 ✓）。
        # 老 UI 不受影响 ✓：它的答案走 `reply` 帧 ✓（`_native_reply_frame` ✓），不看这条事件 ✓。
        return {
            "type": "assistant.completed",
            "payload": {
                "message": _text(item, "message", "text", "content"),
                "responseType": "text",
                "executionStatus": "completed",
                "limitations": [],
            },
        }
    if item_type in {"mcpToolCall", "item/mcpToolCall", "mcp_tool_call"}:
        status = _text(item, "status") or "completed"
        return {"type": "planning.status", "status": status}
    if item_type in {"evidence.updated", "evidenceUpdated"}:
        evidence_ids = item.get("evidenceIds") or item.get("evidence_ids") or []
        safe_ids = [value for value in evidence_ids if isinstance(value, str)]
        return {"type": "evidence.updated", "evidenceIds": safe_ids}
    if item_type in {"recommendation.card", "recommendationCard"}:
        artifact_id = _text(item, "artifactId", "artifact_id")
        return {"type": "recommendation.card", "artifactId": artifact_id} if artifact_id else None
    return None
