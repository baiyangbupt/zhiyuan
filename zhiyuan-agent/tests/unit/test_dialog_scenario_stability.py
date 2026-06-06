"""Scenario-style dialog stability tests.

These tests intentionally use sync wrappers around async entry points so they
can run even when pytest-asyncio is unavailable in the local venv.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.user_profile import UserProfile
from app.tools import intent_preview_tool as intent_preview_tool_module
from app.tools.intent_preview_tool import (
    analyze_current_career_direction,
    analyze_current_interest,
    preview_current_intent_confirmation,
    preview_interest_analysis_from_request,
)
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    render_explore_followup_result,
    render_intent_analysis_payload,
)
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_INTEREST,
    INTENT_CONFIRM_POPUP_TYPE,
    INTENT_MODE_CONSTRAINT,
    INTENT_MODE_PREFERENCE,
    analyze_volunteer_intent_change,
    update_volunteer_intent_state,
)


def _run(coro):
    return asyncio.run(coro)


async def _render_analysis(ctx, *args, **kwargs):
    major_intents = kwargs.get("major_intents")
    school_intents = kwargs.get("school_intents")
    city_intents = kwargs.get("city_intents")
    analysis_stage = kwargs.get("analysis_stage", None)
    career_intents = kwargs.get("career_intents")
    confirm_enabled = kwargs.get("confirm_enabled", True)
    recovery_scope = kwargs.get("recovery_scope")
    intent_mode = kwargs.get("intent_mode", INTENT_MODE_PREFERENCE)

    if (
        analysis_stage == ANALYSIS_STAGE_INTEREST
        and not confirm_enabled
        and not major_intents
        and not school_intents
        and not city_intents
        and career_intents
    ):
        direction_slots = [slot for slot in (career_intents.get("positive") or []) if slot]
        if len(direction_slots) > 1:
            return await intent_preview_tool_module.preview_direction_comparison_from_request(ctx.deps, direction_slots)
        if len(direction_slots) == 1:
            return await intent_preview_tool_module.preview_direction_analysis_from_request(ctx.deps, direction_slots[0])

    if recovery_scope == "career_preference" and not major_intents and not school_intents and not city_intents:
        return await preview_current_intent_confirmation(
            ctx,
            intent_mode=intent_mode,
            recovery_scope=recovery_scope,
        )

    return render_intent_analysis_payload(await analyze_volunteer_intent_change(ctx, *args, **kwargs))


def _render_followup_result(result_text: str) -> str:
    return render_explore_followup_result(parse_explore_followup_result(result_text))


def test_dialog_scenario_explore_query_does_not_silently_fallback_to_intent_recovery():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="301",
            batch="01",
            chat_history=[{"role": "user", "content": "北京有哪些学校"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
    ):
        resp = _run(
            _render_analysis(
                ctx,
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                confirm_enabled=False,
            )
        )

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    assert "还没准确整理出可调整的报考意向" in resp


def test_dialog_scenario_soft_negative_region_stays_preference_not_constraint():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="302",
            batch="01",
            chat_history=[{"role": "user", "content": "不太想去上海"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                city_intents={"negative_province": ["上海"]},
            )
        )

    assert "上海" in resp


def test_dialog_scenario_hard_constraint_city_recovery_builds_constraint_confirm_preview():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="303",
            batch="01",
            chat_history=[{"role": "user", "content": "不想去上海"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value='{"province": ["上海"], "city": [], "area": []}')),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value='{"positive": [], "negative": []}')),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(_render_analysis(ctx, edit_flag="delete"))

    assert "上海" in resp
    assert "要求" in resp or "确认" in resp or "采纳" in resp


def test_dialog_scenario_career_fit_question_stays_interest_analysis_not_direct_state_write():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="304",
            batch="01",
            chat_history=[{"role": "user", "content": "体制内适合我吗"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                career_intents={"positive": ["system_public_service"]},
                confirm_enabled=False,
            )
        )

    assert "体制内/考公导向" in resp
    assert "下一步" in resp


def test_dialog_scenario_career_interest_preview_routes_to_direction_analysis_path():
    request_context = SimpleNamespace(
        sessionid="305",
        batch="01",
        chat_history=[{"role": "user", "content": "体制内适不适合我"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    with patch(
        "app.tools.intent_preview_tool._preview_direction_analysis_from_request",
        new=AsyncMock(return_value="方向分析"),
    ) as mock_preview, patch(
        "app.tools.intent_preview_tool._resolve_career_direction_slots",
        new=AsyncMock(return_value=["system_public_service"]),
    ) as resolve_mock:
        resp = _run(
            preview_interest_analysis_from_request(
                request_context,
                recovery_scope="career_preference",
            )
        )

    resolve_mock.assert_awaited_once_with(request_context)
    mock_preview.assert_awaited_once_with(request_context, "system_public_service")
    assert resp == "方向分析"


def test_dialog_scenario_stable_employment_explore_keeps_student_fit_and_next_step():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="305b",
            batch="01",
            chat_history=[{"role": "user", "content": "稳定就业值不值得优先考虑"}],
            score_detail=SimpleNamespace(
                province="北京",
                total_score=612,
                subject_list=["物理", "化学", "生物"],
                sex="女",
                volunteer_model="majorGroup",
            ),
            init_profile=SimpleNamespace(
                major=SimpleNamespace(level2=["计算机类"], negative_level2=["土木类"]),
                city=SimpleNamespace(province=["北京"], negative_province=[]),
            ),
            planning_summary=SimpleNamespace(
                phase="reviewed",
                ordered_total=30,
                draft_total=30,
                review_warn_count=1,
                review_risk_count=0,
            ),
        )
    )
    with (
        patch(
            "app.tools.intent_preview_tool._resolve_career_direction_slots",
            new=AsyncMock(return_value=["stable_employment"]),
        ),
        patch(
            "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
            new=AsyncMock(
                return_value=(
                    "分析结论\n- 我先帮你看了一眼稳定就业这条路。\n\n"
                    "当前判断\n先帮你判断一下，“稳定就业导向”是不是值得重点看：\n"
                    "  初步判断：\n"
                    "  - 你的当前选科是物理、化学、生物，这至少没有把这条方向直接挡住。\n"
                    "  - 稳定就业更适合拿来比较就业确定性、岗位稳定性和路径清晰度，而不是只看一时热度。\n\n"
                    "下一步\n- 如果你愿意，我可以继续按这条方向帮你看看现在这份方案承接得够不够。"
                )
            ),
        ) as mock_preview,
    ):
        resp = _run(analyze_current_career_direction(ctx))

    mock_preview.assert_awaited_once_with(ctx.deps, "stable_employment")
    assert "你的当前选科是物理、化学、生物" in resp
    assert "稳定就业更适合拿来比较就业确定性、岗位稳定性和路径清晰度" in resp
    assert "下一步" in resp


def test_dialog_scenario_career_tool_delegates_major_mentions_to_major_interest():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="306b",
            batch="01",
            chat_history=[{"role": "user", "content": "当前方案对财会方向承接怎么样"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with patch(
        "app.tools.intent_preview_tool.analyze_current_major_interest",
        new=AsyncMock(return_value="财会方向承接分析"),
    ) as major_mock:
        resp = _run(analyze_current_career_direction(ctx))

    major_mock.assert_awaited_once_with(ctx)
    assert resp == "财会方向承接分析"


def test_dialog_scenario_career_tool_delegates_inferred_stable_major_mentions_to_major_interest():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="306c",
            batch="01",
            chat_history=[{"role": "user", "content": "当前方案对财会方向承接怎么样"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with patch(
        "app.tools.intent_preview_tool.analyze_current_major_interest",
        new=AsyncMock(return_value="财会方向承接分析"),
    ) as major_mock:
        resp = _run(analyze_current_career_direction(ctx, career_directions=["stable_employment"]))

    major_mock.assert_awaited_once_with(ctx)
    assert resp == "财会方向承接分析"


def test_dialog_scenario_career_compare_explore_keeps_comparison_not_plan_listing():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="304b",
            batch="01",
            chat_history=[{"role": "user", "content": "读研、稳定就业、体制内我到底更适合哪个"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch(
            "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
            new=AsyncMock(
                return_value=(
                    "分析结论\n- 先给你一个方向判断，这轮只做分析，不会改动方案。\n\n"
                    "当前判断\n- 这类问题更适合先看你本人更适合哪条路径，再看当前方案更偏向哪一边。\n"
                    "- 深造看培养平台，稳定就业看岗位确定性，体制内看专业和院校属性。\n\n"
                    "下一步\n- 如果你愿意，我可以接着单独展开其中一个方向，再看它和当前方案到底有多匹配。"
                )
            ),
        ) as comparison_mock,
        patch(
            "app.tools.intent_preview_tool._resolve_career_direction_slots",
            new=AsyncMock(return_value=["further_study", "stable_employment", "system_public_service"]),
        ),
    ):
        resp = _run(analyze_current_career_direction(ctx))

    comparison_mock.assert_awaited_once()
    assert "方向判断" in resp
    assert "先看你本人更适合哪条路径" in resp
    assert "下一步" in resp


def test_dialog_scenario_career_explore_can_naturally_offer_professional_assessment_hint():
    request_context = SimpleNamespace(
        sessionid="305c",
        batch="01",
        chat_history=[{"role": "user", "content": "我这个人到底更适合体制内还是读研"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    with (
        patch(
            "app.tools.intent_preview_tool._preview_direction_comparison_from_request",
            new=AsyncMock(
                return_value=(
                    "分析结论\n- 我先帮你看一眼体制内和读研这两条路。\n\n"
                    "当前判断\n- 这一步更适合先看你本人是否值得重点了解，再看当前方案有没有承接。\n\n"
                    "下一步\n- 如果你想把这件事看得更细一点，也可以后面结合 MBTI 和霍兰德职业兴趣测评再继续收一层。"
                )
            ),
        ),
        patch(
            "app.tools.intent_preview_tool._resolve_career_direction_slots",
            new=AsyncMock(return_value=["system_public_service", "further_study"]),
        ),
    ):
        resp = _run(
            preview_interest_analysis_from_request(
                request_context,
                recovery_scope="career_preference",
            )
        )

    assert "MBTI" in resp
    assert "霍兰德" in resp


def test_dialog_scenario_generic_direction_question_via_interest_tool_routes_to_personal_analysis():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="305d",
            batch="01",
            chat_history=[{"role": "user", "content": "我适合什么方向"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=[])),
        patch("app.tools.intent_preview_tool._should_use_generic_direction_analysis", new=AsyncMock(return_value=True)),
        patch(
            "app.tools.intent_preview_tool._preview_generic_direction_analysis_from_request",
            new=AsyncMock(return_value="先结合你的情况看方向"),
        ) as preview_mock,
    ):
        resp = _run(analyze_current_career_direction(ctx))

    assert resp == "先结合你的情况看方向"
    preview_mock.assert_awaited_once_with(ctx.deps)


def test_dialog_scenario_generic_direction_question_via_career_tool_falls_back_to_generic_direction_analysis():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="305e",
            batch="01",
            chat_history=[{"role": "user", "content": "以后更适合走哪条路"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=[])),
        patch("app.tools.intent_preview_tool._should_use_generic_direction_analysis", new=AsyncMock(return_value=True)),
        patch(
            "app.tools.intent_preview_tool._preview_generic_direction_analysis_from_request",
            new=AsyncMock(return_value="我先按泛方向适配给你做判断"),
        ) as preview_mock,
    ):
        resp = _run(analyze_current_career_direction(ctx))

    assert resp == "我先按泛方向适配给你做判断"
    preview_mock.assert_awaited_once_with(ctx.deps)


def test_dialog_scenario_confirm_tool_requires_card_click_for_career_preference():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="306",
            batch="01",
            pending_intent_change=True,
        )
    )

    with (
        patch(
            "app.tools.intent_state_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "career_intents": {"positive": ["system_public_service"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"profileState": {"latentProfile": {"futureDevelopment": {"careerTypes": ["读研"]}}}}}),
        ) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = json.loads(_run(update_volunteer_intent_state(ctx, action="confirm")))["message"]

    assert isinstance(resp, str)
    assert "确认卡片" in resp
    query_mock.assert_not_awaited()
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()


def test_dialog_scenario_interest_followup_candidate_query_for_career_returns_text_not_workspace_action():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with patch(
        "app.tools.explore_followup_tool.get_intent_change_cache",
        new=AsyncMock(
            return_value={
                "data": {
                    "planEditCache": {
                        "intent_mode": INTENT_MODE_PREFERENCE,
                        "career_intents": {"positive": ["system_public_service"]},
                    }
                }
            }
        ),
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="307",
                batch="01",
                action_type="candidate_query",
            )
        )

    assert isinstance(resp, str)
    assert "暂时没法直接在候选区筛出一批固定结果" in _render_followup_result(resp)


def test_dialog_scenario_interest_followup_candidate_query_has_structured_result():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "city_intents": {"province": ["北京"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.explore_followup_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3000}}}})),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 120}})),
    ):
        result = parse_explore_followup_result(
            _run(
                handle_interest_analysis_action_result(
                    session_id="3071",
                    batch="01",
                    action_type="candidate_query",
                )
            )
        )

    assert result.handled is True
    assert result.messageCode == "candidate_query"
    assert result.intentMode == INTENT_MODE_PREFERENCE
    assert result.candidateFilters == {
        "provinceNames": ["北京"],
        "negativeProvinceNames": [],
        "cityNames": [],
        "negativeCityNames": [],
        "schoolKeywords": [],
        "negativeSchoolKeywords": [],
        "majorKeywords": [],
        "negativeMajorKeywords": [],
        "schoolTags": [],
        "negativeSchoolTags": [],
        "majorTags": [],
        "negativeMajorTags": [],
    }
    assert result.filteredTotal == 120
    assert result.baseTotal == 3000


def test_dialog_scenario_interest_followup_plan_analyze_reuses_cached_intent_and_returns_confirmed_analysis():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "city_intents": {"province": ["北京"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.explore_followup_tool.plan_next_action", new=AsyncMock(return_value='{"stage":"apply","action_family":"analyze_adjustment"}')) as plan_mock,
        patch("app.tools.explore_followup_tool.execute_plan_action", new=AsyncMock(return_value='{"summary":"当前判断：可以先补强保区。","state_summary":"当前判断：可以先补强保区。"}')) as exec_mock,
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="308",
                batch="01",
                action_type="plan_analyze",
            )
        )

    assert "当前判断" in _render_followup_result(resp)
    plan_mock.assert_awaited_once()
    exec_mock.assert_awaited_once()


def test_dialog_scenario_major_preference_candidate_query_uses_major_keyword_filter():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "major_intents": {"level3": ["网络与新媒体"]},
                        }
                    }
                }
            ),
        ),
        patch(
            "app.tools.explore_followup_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3000}}}}),
        ),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 24}})) as query_mock,
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="3081",
                batch="01",
                action_type="candidate_query",
            )
        )

    result = parse_explore_followup_result(resp)
    assert result.handled is True
    assert result.candidateFilters["majorKeywords"] == ["网络与新媒体"]
    assert result.filteredTotal == 24
    assert query_mock.await_args.kwargs["major_keywords"] == ["网络与新媒体"]


def test_dialog_scenario_major_preference_plan_analyze_reuses_plan_chain_not_intent_preview():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "major_intents": {"level3": ["网络与新媒体"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.explore_followup_tool.plan_next_action", new=AsyncMock(return_value='{"stage":"apply","action_family":"analyze_adjustment"}')) as plan_mock,
        patch("app.tools.explore_followup_tool.execute_plan_action", new=AsyncMock(return_value='{"summary":"当前判断：网络与新媒体承接还可以继续优化。"}')) as exec_mock,
        patch("app.tools.intent_state_tool.analyze_volunteer_intent_change", new=AsyncMock()) as intent_mock,
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="3082",
                batch="01",
                action_type="plan_analyze",
            )
        )

    assert "网络与新媒体承接" in _render_followup_result(resp)
    plan_mock.assert_awaited_once()
    exec_mock.assert_awaited_once()
    intent_mock.assert_not_awaited()


def test_dialog_scenario_interest_followup_prefer_confirm_goes_to_confirm_chain_not_direct_candidate_refresh():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    expected = "好的，我记下来了。"

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "career_intents": {"positive": ["system_public_service"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"309","message":"好的，我记下来了。"}')) as edit_mock,
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="309",
                batch="01",
                action_type="prefer_confirm",
            )
        )

    assert _render_followup_result(resp) == expected
    kwargs = edit_mock.await_args.kwargs
    assert kwargs["analysis_stage"] == "confirmed"
    assert kwargs["confirm_enabled"] is True
    assert kwargs["career_intents"] == {"positive": ["system_public_service"]}


def test_dialog_scenario_after_plan_discussion_user_adds_preference_still_gets_preference_confirm_preview():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="310",
            batch="01",
            chat_history=[
                {"role": "user", "content": "现在这份方案稳不稳"},
                {"role": "assistant", "content": "我先帮你看了下，整体还可以。"},
                {"role": "user", "content": "后面更想去北京"},
            ],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                city_intents={"province": ["北京"]},
            )
        )

    assert "北京" in resp


def test_dialog_scenario_after_plan_discussion_user_adds_constraint_updates_candidate_view_only_after_confirm():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="311",
            batch="01",
            pending_intent_change=True,
        )
    )

    with (
        patch(
            "app.tools.intent_state_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_CONSTRAINT,
                            "city_intents": {"negative_province": ["上海"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}}),
        ),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 128}})) as query_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = json.loads(_run(update_volunteer_intent_state(ctx, action="confirm")))["message"]

    assert "确认卡片" in resp
    query_mock.assert_not_awaited()


def test_dialog_scenario_career_attitude_reversal_recovery_uses_latest_user_turn_only():
    from app.tools.intent_state_tool import _recover_intents_from_context

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="312",
            chat_history=[
                {"role": "user", "content": "之前我还想进体制"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "现在不想进体制内了"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    async def _assert_single_turn(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "现在不想进体制内了"}]
        return json.dumps({"positive": [], "negative": ["system_public_service"]}, ensure_ascii=False)

    with (
        patch("app.tools.career_intent_tool.extract_career_intent", side_effect=_assert_single_turn),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value='{"province": [], "city": []}')),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
    ):
        major, school, city, career = _run(_recover_intents_from_context(ctx, recovery_scope="career_preference"))

    assert major is None
    assert school is None
    assert city is None
    assert career == {"negative": ["system_public_service"]}


def test_dialog_scenario_city_attitude_reversal_recovery_uses_latest_user_turn_only():
    from app.tools.intent_state_tool import _recover_intents_from_context

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="313",
            chat_history=[
                {"role": "user", "content": "一开始想去上海"},
                {"role": "assistant", "content": "明白"},
                {"role": "user", "content": "现在不想去上海了"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    async def _assert_negative_city(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "现在不想去上海了"}]
        return json.dumps({"province": ["上海"], "city": [], "area": []}, ensure_ascii=False)

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", side_effect=_assert_negative_city),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value='{"positive": [], "negative": []}')),
    ):
        major, school, city, career = _run(_recover_intents_from_context(ctx))

    assert major is None
    assert school is None
    assert city == {"negative_province": ["上海"]}
    assert career is None


def test_dialog_scenario_mixed_utterance_explore_plus_future_preference_still_supports_interest_stage_preview():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="314",
            batch="01",
            chat_history=[{"role": "user", "content": "先看看有没有适合进体制的，后面也可以优先按这个方向看"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                career_intents={"positive": ["system_public_service"]},
                confirm_enabled=False,
            )
        )

    assert "体制内/考公导向" in resp
    assert "下一步" in resp


def test_dialog_scenario_mixed_city_explore_and_constraint_keeps_constraint_confirmation_explicit():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="315",
            batch="01",
            chat_history=[{"role": "user", "content": "先看看北京有没有合适的，但上海就不要了"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                city_intents={"province": ["北京"], "negative_province": ["上海"]},
            )
        )

    assert "北京" in resp
    assert "上海" in resp


def test_dialog_scenario_reject_intent_change_clears_pending_cache():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="316",
        )
    )

    with patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as cache_mock:
        resp = json.loads(_run(update_volunteer_intent_state(ctx, action="reject")))["message"]

    assert "已取消本次意向调整" in resp
    cache_mock.assert_awaited_once_with(316, {})


def test_dialog_scenario_reject_then_confirm_does_not_apply_anything():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="317",
            batch="01",
            chat_history=[{"role": "user", "content": "确认"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.get_intent_change_cache", new=AsyncMock(return_value={"data": {"planEditCache": {}}})),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = json.loads(_run(update_volunteer_intent_state(ctx, action="confirm")))["message"]

    assert "确认卡片" in resp
    latent_mock.assert_not_awaited()
    query_mock.assert_not_awaited()


def test_dialog_scenario_hedged_soft_negative_city_stays_preference():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="318",
            batch="01",
            chat_history=[{"role": "user", "content": "要不还是别去上海了吧"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                city_intents={"negative_province": ["上海"]},
            )
        )

    assert "上海" in resp


def test_dialog_scenario_hedged_career_statement_stays_interest_analysis_before_confirm():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="319",
            batch="01",
            chat_history=[{"role": "user", "content": "体制内也不是不行，可以先看看"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                career_intents={"positive": ["system_public_service"]},
                confirm_enabled=False,
            )
        )

    assert "体制内/考公导向" in resp
    assert "下一步" in resp


def test_dialog_scenario_second_confirm_preview_does_not_write_legacy_cache():
    ctx_first = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="320",
            batch="01",
            chat_history=[{"role": "user", "content": "想去北京"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )
    ctx_second = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="320",
            batch="01",
            chat_history=[{"role": "user", "content": "不去上海"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value='{"province": ["上海"], "city": [], "area": []}')),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value='{"positive": [], "negative": []}')),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        _run(_render_analysis(ctx_first, city_intents={"province": ["北京"]}))
        _run(_render_analysis(ctx_second, edit_flag="delete"))

    assert save_mock.await_count == 0


def test_dialog_scenario_confirm_tool_ignores_latest_legacy_cache():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="321",
            batch="01",
            pending_intent_change=True,
        )
    )

    with (
        patch(
            "app.tools.intent_state_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_CONSTRAINT,
                            "city_intents": {"negative_province": ["上海"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 1000}}}}),
        ),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 88}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = json.loads(_run(update_volunteer_intent_state(ctx, action="confirm")))["message"]

    assert "确认卡片" in resp


def test_dialog_scenario_explicit_intent_mode_overrides_structural_fallback():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="322",
            batch="01",
            chat_history=[{"role": "user", "content": "不去上海"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                city_intents={"negative_province": ["上海"]},
                intent_mode=INTENT_MODE_PREFERENCE,
            )
        )

    assert "上海" in resp


def test_dialog_scenario_interest_followup_constrain_confirm_passes_cached_intent_mode_downstream():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    expected = "我已经按你的要求更新好了。"

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_CONSTRAINT,
                            "city_intents": {"negative_province": ["上海"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"323","message":"我已经按你的要求更新好了。"}')) as edit_mock,
    ):
        resp = _run(
            handle_interest_analysis_action_result(
                session_id="323",
                batch="01",
                action_type="constrain_confirm",
            )
        )

    assert _render_followup_result(resp) == expected
    kwargs = edit_mock.await_args.kwargs
    assert kwargs["intent_mode"] == INTENT_MODE_CONSTRAINT
    assert kwargs["confirm_enabled"] is True


def test_dialog_scenario_major_category_preference_preview_does_not_write_legacy_cache():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="324",
            batch="01",
            chat_history=[{"role": "user", "content": "后面想重点看看计算机和电子信息方向"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                major_intents={"level2": ["计算机类", "电子信息类"]},
            )
        )

    assert "计算机类" in resp
    assert "电子信息类" in resp
    save_mock.assert_not_awaited()


def test_dialog_scenario_explicit_major_exclusion_recovers_as_constraint_from_latest_turn():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="325",
            batch="01",
            chat_history=[
                {"role": "user", "content": "之前也看过护理"},
                {"role": "assistant", "content": "可以"},
                {"role": "user", "content": "绝对不学医了"},
            ],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    async def _assert_latest_negative_major(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "绝对不学医了"}]
        return json.dumps({"level1": ["医学"], "level2": ["临床医学类"], "level3": []}, ensure_ascii=False)

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", side_effect=_assert_latest_negative_major),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value='{"positive": [], "negative": []}')),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(_render_analysis(ctx, edit_flag="delete"))

    assert "医学" in resp
    save_mock.assert_not_awaited()


def test_dialog_scenario_school_named_preference_stays_intent_preview_not_candidate_refresh():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="326",
            batch="01",
            chat_history=[{"role": "user", "content": "华南理工这类学校能不能多看看"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                school_intents={"colleges": ["华南理工大学"]},
            )
        )

    assert "华南理工大学" in resp
    query_mock.assert_not_awaited()
    save_mock.assert_not_awaited()


def test_dialog_scenario_interest_followup_candidate_query_with_major_category_returns_major_filters_only():
    from app.tools.explore_followup_tool import handle_interest_analysis_action_result

    with (
        patch(
            "app.tools.explore_followup_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_PREFERENCE,
                            "major_intents": {"level1": ["工学"], "level2": ["计算机类"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.explore_followup_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 2400}}}})),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 96}})) as query_mock,
    ):
        result = parse_explore_followup_result(
            _run(
                handle_interest_analysis_action_result(
                    session_id="327",
                    batch="01",
                    action_type="candidate_query",
                )
            )
        )

    assert result.messageCode == "candidate_query"
    assert result.candidateFilters["majorTags"] == ["工学"]
    assert result.candidateFilters["majorKeywords"] == ["计算机类"]
    assert result.candidateFilters["provinceNames"] == []
    assert result.filteredTotal == 96
    query_kwargs = query_mock.await_args.kwargs
    assert query_kwargs["major_tags"] == ["工学"]
    assert query_kwargs["major_keywords"] == ["计算机类"]


def test_dialog_scenario_confirm_tool_does_not_output_negative_major_filters():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="328",
            batch="01",
            pending_intent_change=True,
        )
    )

    with (
        patch(
            "app.tools.intent_state_tool.get_intent_change_cache",
            new=AsyncMock(
                return_value={
                    "data": {
                        "planEditCache": {
                            "intent_mode": INTENT_MODE_CONSTRAINT,
                            "major_intents": {"negative_level1": ["医学"], "negative_level2": ["临床医学类"]},
                        }
                    }
                }
            ),
        ),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 1800}}}}),
        ),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 150}})) as query_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        result = json.loads(_run(update_volunteer_intent_state(ctx, action="confirm")))

    assert result["applied"] is False
    assert result["messageCode"] == "confirm_required"
    assert "确认卡片" in result["message"]
    query_mock.assert_not_awaited()


def test_dialog_scenario_biology_interest_and_far_region_requirement_can_coexist_in_preview():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="329",
            batch="01",
            chat_history=[{"role": "user", "content": "生物工程可以看看，但太远的地方就算了"}],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = _run(
            _render_analysis(
                ctx,
                major_intents={"level2": ["生物工程类"]},
                city_intents={"negative_province": ["新疆", "黑龙江"]},
                intent_mode=INTENT_MODE_CONSTRAINT,
            )
        )

    assert "生物工程" in resp
    assert "新疆" in resp
    assert "黑龙江" in resp
    save_mock.assert_not_awaited()
