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


def test_policy_direct_returns_intent_preview_payload_message():
    decision = decide_tool_reply(
        ["preview_current_major_intent_confirmation"],
        [
            _tool_return(
                "preview_current_major_intent_confirmation",
                '{"status":"ready","reply_strategy":"preview_wait_confirm","message":"我先整理成待确认偏好。","items":[{"content":"偏好会计学","value":{"major_intents":{"level3":["会计学"]}}}]}',
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reply == "我先整理成待确认偏好。"


def test_policy_respects_continue_model_strategy_from_downgraded_intent_preview():
    decision = decide_tool_reply(
        ["preview_current_major_intent_confirmation"],
        [
            _tool_return(
                "preview_current_major_intent_confirmation",
                '{"status":"ready","analysisStage":"interest","reply_strategy":"continue_model","message":"先分析影响，不生成待确认卡片。"}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "explicit_continue_model"


def test_policy_keeps_readonly_career_explore_result_for_model_synthesis():
    decision = decide_tool_reply(
        ["analyze_current_career_direction"],
        [_tool_return("analyze_current_career_direction", "这轮只做分析，不会改动你的方案。")],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_explore_needs_model_synthesis"


def test_policy_keeps_readonly_major_intent_analysis_for_model_synthesis():
    decision = decide_tool_reply(
        ["analyze_current_major_interest"],
        [
            _tool_return(
                "analyze_current_major_interest",
                "**排除医学与护理的影响**\n医学和护理会收窄候选范围。\n\n**接受财会方向的影响**\n财会可以作为后续可接受方向先看。",
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_explore_needs_model_synthesis"
    assert decision.reply is None


def test_policy_keeps_readonly_region_intent_analysis_for_model_synthesis():
    decision = decide_tool_reply(
        ["analyze_current_region_interest"],
        [_tool_return("analyze_current_region_interest", "这轮只做地域影响分析，不会改动方案。")],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_explore_needs_model_synthesis"
    assert decision.reply is None


def test_policy_keeps_unrendered_readonly_explore_payload_for_model_summary():
    decision = decide_tool_reply(
        ["analyze_current_major_interest"],
        [_tool_return("analyze_current_major_interest", '{"status":"ok","items":[]}')],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_keeps_delegated_major_compare_for_model_synthesis():
    decision = decide_tool_reply(
        ["analyze_current_major_interest"],
        [
            _tool_return(
                "analyze_current_major_interest",
                (
                    '{"reply_strategy":"continue_model","analysis_kind":"major_compare",'
                    '"message":"专业对比事实：网络与新媒体 vs 跨境电子商务"}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "explicit_continue_model"


def test_policy_keeps_admission_policy_direct_payload_for_model_synthesis():
    decision = decide_tool_reply(
        ["answer_admission_policy_question"],
        [
            _tool_return(
                "answer_admission_policy_question",
                '{"reply_strategy":"direct_reply","summary":"这轮可以先按通用方法判断。"}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_keeps_admission_fit_match_direct_payload_for_model_synthesis():
    decision = decide_tool_reply(
        ["match_admission_rule_to_student"],
        [
            _tool_return(
                "match_admission_rule_to_student",
                '{"reply_strategy":"direct_reply","summary":"从已知规则看，目前还缺官方规则摘要。"}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_does_not_trust_explicit_direct_strategy_from_readonly_query_tool():
    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                '{"reply_strategy":"direct_blocking","summary":"当前没有命中结果，请换个条件。"}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reply is None


def test_policy_keeps_plan_query_alias_match_for_model_synthesis():
    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                "按当前方案里的院校简称“青城”匹配到青岛城市学院；原先可能冲突的地域条件没有参与这次院校命中。\n当前方案里共命中了 7 条符合“院校:青城、青岛城市学院”的志愿。",
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_result_needs_model_synthesis"
    assert decision.reply is None


def test_policy_keeps_plan_query_for_model_synthesis_after_prior_tools():
    class Deps:
        agent_observability = {
            "toolNameCounts": {
                "validate_major_subjects": 1,
                "query_volunteer_plan": 1,
            }
        }

    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                "当前方案里共命中了 10 条符合“院校标签:公办”的志愿。下面仅展示前 5 条示例。",
            )
        ],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_needs_model_synthesis_after_prior_tools"


def test_policy_keeps_plan_query_for_model_synthesis_even_when_successful():
    class Deps:
        agent_observability = {
            "toolInternalTimings": [
                {
                    "tool": "query_volunteer_plan",
                    "requestedScope": "plan",
                    "resolvedScope": "plan",
                    "status": "success",
                    "hasStructuredFilters": True,
                    "filterKeys": ["province_names"],
                }
            ]
        }

    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                "当前方案里共命中了 20 条符合“省份:江苏”的志愿。下面仅展示前 5 条示例。",
            )
        ],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_result_needs_model_synthesis"


def test_policy_keeps_empty_plan_query_for_model_synthesis_when_candidate_fails():
    class Deps:
        agent_observability = {
            "toolInternalTimings": [
                {
                    "tool": "query_volunteer_plan",
                    "status": "candidate_query_failed_after_plan_miss",
                }
            ]
        }

    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [_tool_return("query_volunteer_plan", "当前方案里还没有可查询的志愿。")],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_empty_or_failed_needs_model_synthesis"


def test_policy_keeps_empty_plan_query_for_model_synthesis_after_plan_miss_candidate_checked():
    class Deps:
        agent_observability = {
            "toolInternalTimings": [
                {
                    "tool": "query_volunteer_plan",
                    "status": "success_plan_miss_candidate_checked",
                }
            ]
        }

    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [_tool_return("query_volunteer_plan", "当前方案里暂时没有命中“广西”的志愿。")],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_empty_or_failed_needs_model_synthesis"


def test_policy_keeps_unstructured_empty_plan_query_for_model_synthesis():
    class Deps:
        agent_observability = {
            "toolInternalTimings": [
                {
                    "tool": "query_volunteer_plan",
                    "status": "success",
                    "hasStructuredFilters": False,
                }
            ]
        }

    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [_tool_return("query_volunteer_plan", "当前方案里暂时没有命中“省外是不是太多了”的志愿。")],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_plan_query_empty_or_failed_needs_model_synthesis"


def test_policy_direct_returns_structured_selection_block():
    decision = decide_tool_reply(
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
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
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
                '{"result_kind":"no_change","summary":"这条志愿已经在方案里，无需重复加入。"}',
            )
        ],
    )

    assert decision.strategy == "direct_reply"
    assert decision.reply == "这条志愿已经在方案里，无需重复加入。"


def test_policy_does_not_trust_explicit_direct_reply_from_structured_payload():
    decision = decide_tool_reply(
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
                (
                    '{"action_family":"query_state","result_kind":"status_overview",'
                    '"summary":"当前方案里共命中了 7 条和青岛城市学院相关的志愿。",'
                    '"reply_focus":["local_plan_query","current_state"],'
                    '"reply_strategy":"direct_reply"}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reply is None


def test_policy_keeps_plan_result_for_model_synthesis_after_explore_tool():
    class Deps:
        agent_observability = {
            "toolNameCounts": {
                "analyze_current_career_direction": 1,
                "structured_action_result": 1,
            }
        }

    decision = decide_tool_reply(
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
                (
                    '{"action_family":"review_plan","result_kind":"review_result",'
                    '"summary":"已完成方案审查，当前共检出 **风险 2 项、提醒 0 项**。",'
                    '"reply_focus":["review_result","risk_warning"]}'
                ),
            )
        ],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "prior_tool_facts_need_model_synthesis"


def test_policy_keeps_single_explore_tool_for_model_synthesis_despite_observability_current_count():
    class Deps:
        agent_observability = {"toolNameCounts": {"analyze_current_career_direction": 1}}

    decision = decide_tool_reply(
        ["analyze_current_career_direction"],
        [_tool_return("analyze_current_career_direction", "这轮只做分析，不会改动你的方案。")],
        Deps(),
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "read_only_explore_needs_model_synthesis"


def test_policy_keeps_structured_preview_for_model_summary():
    decision = decide_tool_reply(
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
                (
                    '{"result_kind":"preview_only","summary":"会把这个志愿移动到第3位。",'
                    '"reply_focus":["preview_only","confirmation_required"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reply is None


def test_policy_keeps_fix_proposal_preview_for_model_summary():
    decision = decide_tool_reply(
        ["generate_planning_fix_proposals"],
        [
            _tool_return(
                "generate_planning_fix_proposals",
                (
                    '{"result_kind":"fix_proposal_preview",'
                    '"summary":"已生成当前方案的调整预览：可确认后执行 1 项。",'
                    '"reply_focus":["fix_proposal_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_keeps_empty_fix_proposal_preview_for_model_summary():
    decision = decide_tool_reply(
        ["generate_planning_fix_proposals"],
        [
            _tool_return(
                "generate_planning_fix_proposals",
                (
                    '{"result_kind":"fix_proposal_preview",'
                    '"summary":"已查看当前方案的可处理建议，暂时没有需要自动处理的项目。",'
                    '"reply_focus":["fix_proposal_preview","empty_fix_proposal_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_keeps_general_error_for_model_summary():
    decision = decide_tool_reply(
        ["structured_action_result"],
        [
            _tool_return(
                "structured_action_result",
                '{"result_kind":"error","summary":"后端临时失败，请稍后重试。","reply_focus":["mutation_failed"]}',
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False


def test_policy_does_not_direct_return_multi_tool_turns():
    decision = decide_tool_reply(
        ["structured_action_result", "query_volunteer_plan"],
        [
            _tool_return(
                "structured_action_result",
                (
                    '{"result_kind":"error","summary":"我在当前方案里还没有唯一匹配到这条志愿。",'
                    '"reply_focus":["needs_volunteer_selection"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
