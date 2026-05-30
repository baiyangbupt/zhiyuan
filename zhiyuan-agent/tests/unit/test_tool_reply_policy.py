from __future__ import annotations

from pydantic_ai.messages import ToolReturnPart

from app.agent.tool_reply_policy import decide_tool_reply


def _tool_return(tool_name: str, content: str) -> ToolReturnPart:
    return ToolReturnPart(
        tool_name=tool_name,
        content=content,
        tool_call_id=f"{tool_name}-call",
    )


def test_policy_direct_returns_intent_preview_tool_text():
    decision = decide_tool_reply(
        ["preview_current_major_intent_confirmation"],
        [_tool_return("preview_current_major_intent_confirmation", "我先整理成待确认偏好。")],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reply == "我先整理成待确认偏好。"


def test_policy_direct_returns_explicit_strategy_from_any_tool():
    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                '{"reply_strategy":"direct_blocking","summary":"当前没有命中结果，请换个条件。"}',
            )
        ],
    )

    assert decision.strategy == "direct_blocking"
    assert decision.should_return_directly is True
    assert decision.reply == "当前没有命中结果，请换个条件。"


def test_policy_direct_returns_structured_plan_selection_block():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"error","summary":"我在当前方案里还没有唯一匹配到这条志愿。",'
                    '"reply_focus":["missing_inputs","needs_volunteer_selection"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "direct_blocking"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_blocking_result"


def test_policy_direct_returns_no_change_result_without_retry():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                '{"result_kind":"no_change","summary":"这条志愿已经在方案里，无需重复加入。"}',
            )
        ],
    )

    assert decision.strategy == "direct_reply"
    assert decision.reply == "这条志愿已经在方案里，无需重复加入。"


def test_policy_keeps_normal_preview_for_model_summary():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"preview_only","summary":"会把这个志愿移动到第3位。",'
                    '"reply_focus":["preview_only","confirmation_required"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_keeps_general_error_for_model_summary():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                '{"result_kind":"error","summary":"后端临时失败，请稍后重试。","reply_focus":["mutation_failed"]}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_does_not_direct_return_multi_tool_turns():
    decision = decide_tool_reply(
        ["execute_plan_action", "query_volunteer_plan"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"error","summary":"我在当前方案里还没有唯一匹配到这条志愿。",'
                    '"reply_focus":["needs_volunteer_selection"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
