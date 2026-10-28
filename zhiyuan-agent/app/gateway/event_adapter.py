from __future__ import annotations

import json

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
    """Forward progress only; model prose stays private until Gateway validation.

    A rejected answer cannot retract prose already displayed in a browser.
    The business turn worker emits authoritative assistant.completed.
    """
    if not isinstance(notification, Mapping):
        return []
    method = str(notification.get("method") or "")
    params = notification.get("params")
    if not isinstance(params, Mapping):
        params = {}

    if method in {"item/agentMessage/delta", "agentMessage/delta"}:
        return []

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
        events = [
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
        if method == "item/completed" and tool == "planning.interpret_admission":
            interpretation = _interpretation_event(item)
            if interpretation is not None:
                events.append(interpretation)
        return events

    # 终态（turn.completed / assistant.completed）**不在这里产生**：
    # 它们必须携带经过业务校验的 executionStatus 与 toolStatus，只能由
    # 回合 worker 发一次。适配器再发一份就变成设计明令禁止的"两份终态"。
    return []


def adapt_codex_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Convert Codex notifications into the stable, user-visible event set."""
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if item_type in {
        "item/agentMessage/delta", "agentMessage/delta", "assistant.delta",
        "turn/completed", "item/agentMessage/completed", "assistant.completed",
    }:
        return None
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


def _interpretation_event(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """从 `planning.interpret_admission` 的工具结果里抽**有界摘要**。

    不发完整 path/evidenceRefs：45 条方案的 path 能到几十 KB，而 16KB 是事件
    硬上限；卡片只需要"哪条情景、什么条件、落在哪一条"。完整结果仍在工具
    结果/正文里，前端不按 ref 取明细。
    """
    data = _interpretation_data(item)
    if not isinstance(data, Mapping):
        return None
    status = str(data.get("status") or "")
    if status not in {"completed", "no_plan"}:
        return None
    payload: dict[str, Any] = {
        "status": status,
        "planVersion": data.get("planVersion"),
        "admissionMode": data.get("admissionMode"),
        "safetyCoverage": data.get("safetyCoverage"),
        "dataCompletenessBand": data.get("dataCompletenessBand"),
        "tierCoverage": data.get("tierCoverage"),
        "ratioCoverage": data.get("ratioCoverage"),
        "dataCompleteness": data.get("dataCompleteness"),
        "orderAnomaly": data.get("orderAnomaly"),
        "tierSequence": data.get("tierSequence"),
        "tierSequenceStatus": data.get("tierSequenceStatus"),
        "userOrderRespected": data.get("userOrderRespected"),
        "baseLanding": _scenario_summary(data.get("baseLanding")),
        "scenarios": [
            summary
            for summary in (
                _scenario_summary(scenario)
                for scenario in (data.get("scenarios") or [])[:4]
            )
            if summary is not None
        ],
        "caveats": [
            str(caveat)[:200]
            for caveat in (data.get("caveats") or [])[:6]
            if str(caveat).strip()
        ],
        # J5.2：带 hard/soft 分组的 bounded caveat；旧生产者没有该字段时前端回退扁平 caveats。
        "caveatDetails": [
            {
                "text": str(item.get("text") or "")[:200],
                "level": "hard" if str(item.get("level") or "") == "hard" else "soft",
                "code": str(item.get("code") or "") or None,
            }
            for item in (data.get("caveatDetails") or [])[:5]
            if isinstance(item, Mapping) and str(item.get("text") or "").strip()
        ],
    }
    return {"type": "interpretation.preview", "payload": payload}


def _interpretation_data(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    result = item.get("result")
    if not isinstance(result, Mapping):
        return None
    structured = result.get("structuredContent")
    if not isinstance(structured, Mapping):
        structured = result.get("structured_content")
    if isinstance(structured, Mapping):
        data = structured.get("data")
        return data if isinstance(data, Mapping) else structured
    # 兼容只回 content 文本的 MCP 实现：文本本身是 JSON。
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, Mapping):
                continue
            text = block.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, Mapping):
                data = parsed.get("data")
                return data if isinstance(data, Mapping) else parsed
    return None


def _scenario_summary(scenario: Any) -> dict[str, Any] | None:
    if not isinstance(scenario, Mapping):
        return None
    landing = scenario.get("landingEntry")
    landing_summary = None
    if isinstance(landing, Mapping):
        landing_summary = {
            key: landing.get(key)
            for key in ("level", "id", "position", "schoolName", "majorName", "pathTier")
            if landing.get(key) is not None
        }
    return {
        "scenarioId": scenario.get("scenarioId"),
        "label": scenario.get("label"),
        "structureStatus": scenario.get("structureStatus"),
        "condition": scenario.get("condition"),
        "landingEntry": landing_summary,
        # drivers 里可能带“校线录取率=56”这类证据值：卡面只讲结构，
        # 不把录取率数字放到用户眼前（容易被读成录取概率）。
        "drivers": [
            text
            for text in (
                _safe_ratio_free_text(driver) for driver in (scenario.get("drivers") or [])
            )
            if text
        ][:3],
        "caveats": [
            str(caveat)[:160]
            for caveat in (scenario.get("caveats") or [])[:3]
            if str(caveat).strip()
        ],
    }


def _safe_ratio_free_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "录取率" in text or "ratio" in lowered or "%" in text:
        return ""
    return text[:160]
