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


def test_policy_direct_returns_readonly_major_intent_analysis_result():
    decision = decide_tool_reply(
        ["analyze_current_major_interest"],
        [
            _tool_return(
                "analyze_current_major_interest",
                "**排除医学与护理的影响**\n医学和护理会收窄候选范围。\n\n**接受财会方向的影响**\n财会可以作为后续可接受方向先看。",
            )
        ],
    )

    assert decision.strategy == "direct_reply"
    assert decision.should_return_directly is True
    assert decision.reason == "read_only_intent_analysis_result"
    assert "医学和护理会收窄候选范围" in decision.reply


def test_policy_direct_returns_readonly_region_intent_analysis_result():
    decision = decide_tool_reply(
        ["analyze_current_region_interest"],
        [_tool_return("analyze_current_region_interest", "这轮只做地域影响分析，不会改动方案。")],
    )

    assert decision.strategy == "direct_reply"
    assert decision.should_return_directly is True
    assert decision.reason == "read_only_intent_analysis_result"


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


def test_policy_direct_returns_plan_query_alias_match_to_avoid_model_reinterpretation():
    decision = decide_tool_reply(
        ["query_volunteer_plan"],
        [
            _tool_return(
                "query_volunteer_plan",
                "按当前方案里的院校简称“青城”匹配到青岛城市学院；原先可能冲突的地域条件没有参与这次院校命中。\n当前方案里共命中了 7 条符合“院校:青城、青岛城市学院”的志愿。",
            )
        ],
    )

    assert decision.strategy == "direct_reply"
    assert decision.should_return_directly is True
    assert decision.reason == "plan_query_alias_match_result"
    assert "青岛城市学院" in (decision.reply or "")


def test_policy_keeps_plan_query_for_model_synthesis_after_prior_tools():
    class Deps:
        agent_observability = {
            "toolNameCounts": {
                "plan_next_action": 1,
                "execute_plan_action": 1,
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


def test_policy_keeps_structured_status_overview_for_model_synthesis():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"query_state","result_kind":"status_overview",'
                    '"summary":"方案已经有了，目前有 45/45 个志愿。\\n- 梯度分布：冲18 / 稳13 / 保14。",'
                    '"reply_focus":["current_state","count_target","tier_distribution"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "structured_status_overview_needs_model_synthesis"
    assert decision.reply is None


def test_policy_keeps_structured_review_result_for_model_synthesis():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"review_plan","result_kind":"review_result",'
                    '"summary":"已完成方案审查，当前共检出 **风险 3 项、提醒 5 项**。\\n'
                    '### 主要问题\\n1. 冲区占比过高。",'
                    '"reply_focus":["review_result","risk_warning","direct_review_reply"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "continue_model"
    assert decision.should_return_directly is False
    assert decision.reason == "structured_review_result_needs_model_synthesis"
    assert decision.reply is None


def test_policy_keeps_plan_result_for_model_synthesis_after_explore_tool():
    class Deps:
        agent_observability = {
            "toolNameCounts": {
                "analyze_current_career_direction": 1,
                "execute_plan_action": 1,
            }
        }

    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"review_plan","result_kind":"review_result",'
                    '"summary":"已完成方案审查，当前共检出 **风险 2 项、提醒 0 项**。",'
                    '"reply_focus":["review_result","risk_warning","direct_review_reply"]}'
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


def test_policy_direct_returns_confirmation_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"add_units","result_kind":"preview_only",'
                    '"summary":"会把河南农业大学-建筑类加入当前方案。需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","confirmation_required"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_add_preview"
    assert "确认后" in (decision.reply or "")


def test_policy_direct_returns_review_issue_batch_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"remove_units","result_kind":"preview_only",'
                    '"summary":"已定位到当前方案里当前审查命中的高收费：共 30 个专业组，涉及 76 条志愿。需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","review_issue_batch_scope"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_review_issue_batch_preview"
    assert "高收费" in (decision.reply or "")


def test_policy_direct_returns_sort_ordered_plan_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"action_family":"sort_ordered_plan","result_kind":"preview_only",'
                    '"summary":"会按推荐系数重新排序当前方案，推荐系数高的排在前面。需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","sort_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_sort_preview"
    assert "推荐系数" in (decision.reply or "")


def test_policy_direct_returns_unit_position_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"preview_only","summary":"会整体移动第 4 个专业组到第 2 个专业组位置。'
                    '需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","confirmation_required","unit_position_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_position_preview"


def test_policy_direct_returns_volunteer_position_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"preview_only","summary":"预览如下：\\n\\n- 志愿：青岛城市学院 · 国际经济与贸易\\n'
                    '- 当前位置：当前第 36 位\\n- 目标位置：第 3 位\\n'
                    '- 影响：确认后会调整方案顺序。需要你确认后才会执行。",'
                    '"reply_focus":["preview_only","volunteer_position_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_position_preview"


def test_policy_direct_returns_compensation_preview():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"compensation_preview",'
                    '"summary":"当前可先看的补齐建议共有 1 项动作，预计补入 2 个志愿。",'
                    '"reply_focus":["compensation_preview"]}'
                ),
            )
        ],
    )

    assert decision.strategy == "preview_wait_confirm"
    assert decision.should_return_directly is True
    assert decision.reason == "structured_compensation_preview"


def test_policy_keeps_empty_compensation_preview_for_model_summary():
    decision = decide_tool_reply(
        ["execute_plan_action"],
        [
            _tool_return(
                "execute_plan_action",
                (
                    '{"result_kind":"compensation_preview",'
                    '"summary":"这轮没有拿到可直接执行的调稳补齐预览。",'
                    '"reply_focus":["compensation_preview","empty_compensation_preview"]}'
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
