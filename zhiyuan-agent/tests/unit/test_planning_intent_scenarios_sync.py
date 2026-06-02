"""Sync-wrapper scenario tests for intent-state flows that affect plan/candidate state."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.user_profile import UserProfile
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_analysis_payload,
    render_intent_state_update,
)
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_INTEREST,
    INTENT_MODE_CONSTRAINT,
    INTENT_MODE_PREFERENCE,
    _apply_intents,
    analyze_volunteer_intent_change,
    apply_selected_intents,
    update_volunteer_intent_state,
)


def _ctx(session_id: str = "1001") -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid=session_id,
            batch="01",
            chat_history=[],
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )


async def _render_analysis(ctx, *args, **kwargs) -> str:
    return render_intent_analysis_payload(await analyze_volunteer_intent_change(ctx, *args, **kwargs))


async def _render_followup(*, session_id: str, batch: str, action_type: str) -> str:
    return render_explore_followup_result(
        parse_explore_followup_result(
            await handle_interest_analysis_action_result(
                session_id=session_id,
                batch=batch,
                action_type=action_type,
            )
        )
    )


async def _render_apply_selected(*, session_id: str, batch: str, selected_data: dict) -> str:
    return render_intent_state_update(
        parse_intent_state_update_result(
            await apply_selected_intents(
                session_id=session_id,
                batch=batch,
                selected_data=selected_data,
            )
        )
    )


def test_intent_scenario_interest_stage_preference_returns_interest_text_with_next_steps():
    ctx = _ctx("1002")
    ctx.deps.chat_history = [{"role": "user", "content": "我更想去北京"}]

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
        resp = asyncio.run(
            _render_analysis(
                ctx,
                city_intents={"province": ["北京"]},
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                confirm_enabled=False,
            )
        )

    assert "初步判断" in resp
    assert "下一步" in resp


def test_intent_scenario_interest_stage_major_preference_also_returns_interest_text():
    ctx = _ctx("1022")
    ctx.deps.chat_history = [{"role": "user", "content": "想看看计算机"}]

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
        resp = asyncio.run(
            _render_analysis(
                ctx,
                major_intents={"level2": ["计算机类"]},
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                confirm_enabled=False,
            )
        )

    assert "初步判断" in resp
    assert "计算机类" in resp


def test_intent_scenario_confirmed_preference_returns_text_without_candidate_requery():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock()) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = asyncio.run(
            _apply_intents(
                session_id="1003",
                batch="01",
                merged={"city_intents": {"negative_province": ["上海"]}},
                intent_mode=INTENT_MODE_PREFERENCE,
            )
        )

    query_mock.assert_awaited_once()
    assert query_mock.await_args.kwargs["sort_field"] == "finalScore"
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()
    assert resp.applied is True
    assert "已确认" in resp.message
    assert "后续报考参考" in resp.message
    assert "现在这份方案" in resp.message


def test_intent_scenario_confirmed_career_negative_preference_removes_latent_profile_label():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(
                return_value={
                    "data": {
                        "profileState": {
                            "latentProfile": {
                                "futureDevelopment": {"careerTypes": ["读研", "体制内/考公导向", "稳定就业"]}
                            }
                        }
                    }
                }
            ),
        ) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = asyncio.run(
            _apply_intents(
                session_id="1033",
                batch="01",
                merged={"career_intents": {"negative": ["system_public_service"]}},
                intent_mode=INTENT_MODE_PREFERENCE,
            )
        )

    assert resp.applied is True
    assert "已确认" in resp.message
    assert "后续报考参考" in resp.message
    query_mock.assert_awaited_once()
    assert query_mock.await_args.kwargs["sort_field"] == "finalScore"
    state_mock.assert_awaited_once()
    latent_mock.assert_awaited_once_with(
        1033,
        future_development={"careerTypes": ["读研", "稳定就业"]},
    )


def test_intent_scenario_confirmed_constraint_returns_candidate_text():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 64}})),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = asyncio.run(
            _apply_intents(
                session_id="1004",
                batch="01",
                merged={"city_intents": {"negative_province": ["北京"]}},
                intent_mode=INTENT_MODE_CONSTRAINT,
            )
        )

    assert resp.filteredTotal == 64
    assert resp.baseTotal == 3200


def test_intent_scenario_interest_followup_candidate_query_with_city_preference_returns_text():
    cache_payload = {
        "data": {
            "planEditCache": {
                "city_intents": {"province": ["北京"]},
                "intent_mode": INTENT_MODE_PREFERENCE,
            }
        }
    }

    with (
        patch("app.tools.explore_followup_tool.get_intent_change_cache", new=AsyncMock(return_value=cache_payload)),
        patch("app.tools.explore_followup_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}})),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 96}})),
    ):
        resp = asyncio.run(
            _render_followup(
                session_id="1044",
                batch="01",
                action_type="candidate_query",
            )
        )

    assert "96" in resp
    assert "3200" in resp


def test_intent_scenario_handle_select_plan_analyze_returns_confirmed_analysis_text():
    cache_payload = {
        "data": {
            "planEditCache": {
                "career_intents": {"positive": ["system_public_service"]},
                "intent_mode": "preference",
            }
        }
    }

    with (
        patch("app.tools.explore_followup_tool.get_intent_change_cache", new=AsyncMock(return_value=cache_payload)),
        patch("app.tools.explore_followup_tool.plan_next_action", new=AsyncMock(return_value='{"stage":"apply","action_family":"analyze_adjustment"}')) as plan_mock,
        patch("app.tools.explore_followup_tool.execute_plan_action", new=AsyncMock(return_value='{"summary":"当前判断：当前方案可继续优化。","state_summary":"当前判断：当前方案可继续优化。"}')) as exec_mock,
    ):
        resp = asyncio.run(
            _render_followup(
                session_id="1005",
                batch="01",
                action_type="plan_analyze",
            )
        )

    assert "当前判断" in resp
    plan_mock.assert_awaited_once()
    exec_mock.assert_awaited_once()


def test_intent_scenario_handle_select_prefer_confirm_returns_confirm_text():
    cache_payload = {
        "data": {
            "planEditCache": {
                "city_intents": {"province": ["北京"]},
                "intent_mode": "preference",
            }
        }
    }

    with (
        patch("app.tools.explore_followup_tool.get_intent_change_cache", new=AsyncMock(return_value=cache_payload)),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = asyncio.run(
            _render_followup(
                session_id="1006",
                batch="01",
                action_type="prefer_confirm",
            )
        )

    assert "待确认内容" in resp
    assert "点击卡片采纳" in resp


def test_intent_scenario_handle_select_constraint_returns_candidate_query_text():
    selected_data = {
        "message_id": 1007,
        "selected": [{"city_intents": {"negative_province": ["上海"]}}],
    }
    message_content = {
        "intentMode": INTENT_MODE_CONSTRAINT,
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["上海"]}}}],
    }

    with (
        patch(
            "app.tools.intent_state_tool.get_message_by_id",
            new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
        ),
        patch("app.tools.intent_state_tool.update_message", new=AsyncMock()),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 128}})),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = asyncio.run(_render_apply_selected(session_id="1007", batch="01", selected_data=selected_data))

    assert "128" in resp


def test_intent_scenario_handle_select_on_already_clicked_message_short_circuits():
    selected_data = {
        "message_id": 1007,
        "selected": [{"city_intents": {"negative_province": ["上海"]}}],
    }
    message_content = {
        "intentMode": INTENT_MODE_CONSTRAINT,
        "clickable": False,
        "clicked": True,
        "items": [{"value": {"city_intents": {"negative_province": ["上海"]}}}],
    }

    with (
        patch(
            "app.tools.intent_state_tool.get_message_by_id",
            new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}}),
        ),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = asyncio.run(_render_apply_selected(session_id="1007", batch="01", selected_data=selected_data))

    assert resp == "该消息不可再点击。"


def test_intent_scenario_confirm_intent_change_with_career_preference_updates_latent_profile_only_after_confirm():
    ctx = SimpleNamespace(deps=SimpleNamespace(sessionid="1008", batch="01", pending_intent_change=True))

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
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        resp = json.loads(asyncio.run(update_volunteer_intent_state(ctx, action="confirm")))

    assert resp["applied"] is True
    assert "已确认" in resp["message"]
    assert "后续报考参考" in resp["message"]
    query_mock.assert_awaited_once()
    assert query_mock.await_args.kwargs["sort_field"] == "finalScore"
    state_mock.assert_awaited_once()
    latent_mock.assert_awaited_once_with(
        1008,
        future_development={"careerTypes": ["读研", "体制内/考公导向"]},
    )
