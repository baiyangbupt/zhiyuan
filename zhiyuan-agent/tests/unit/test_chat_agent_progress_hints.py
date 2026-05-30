"""Tests for user-facing thinking/progress hints."""

from __future__ import annotations

from app.agent.chat_agent import _TOOL_PROGRESS_HINTS


def test_plan_progress_hints_use_user_facing_language():
    assert _TOOL_PROGRESS_HINTS["collect_plan_context_inputs"] == "正在读取你的方案、偏好和审查结果..."
    assert _TOOL_PROGRESS_HINTS["plan_next_action"] == "正在读取当前方案并整理这次请求..."
    assert _TOOL_PROGRESS_HINTS["execute_plan_action"] == "正在处理你的方案，请稍等..."


def test_progress_hints_do_not_expose_internal_terms():
    forbidden_terms = [
        "action",
        "payload",
        "stage",
        "phase",
        "volunteerId",
        "工具",
        "执行方案动作",
        "规划当前方案动作",
        "方案相关状态",
    ]

    for tool_name, hint in _TOOL_PROGRESS_HINTS.items():
        for term in forbidden_terms:
            assert term not in hint, f"{tool_name} exposes internal term {term!r}: {hint}"
