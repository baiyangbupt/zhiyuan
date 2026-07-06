"""Tests for user-facing thinking/progress hints."""

from __future__ import annotations

from app.agent.chat_agent import _TOOL_PROGRESS_HINTS


def test_legacy_plan_orchestration_progress_hints_are_not_registered():
    assert "collect_plan_context_inputs" not in _TOOL_PROGRESS_HINTS
    assert "plan_next_action" not in _TOOL_PROGRESS_HINTS
    assert "execute_plan_action" not in _TOOL_PROGRESS_HINTS


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
