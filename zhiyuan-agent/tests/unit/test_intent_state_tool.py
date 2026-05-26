"""Unit tests for intent_state_tool — verify profile merge, selection item generation,
fallback extraction, and selected-value merge behavior."""

import asyncio
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.ws import WSResponse
from app.schemas.user_profile import CityIntent, MajorIntent, SchoolIntent, UserProfile
from app.tools import intent_preview_tool as intent_preview_tool_module
from app.tools import intent_state_tool as intent_state_tool_module
from app.tools.explore_direction_tool import _is_public_service_aligned_item
from app.tools.intent_response_tool import (
    ExploreFollowupResult,
    IntentStateUpdateResult,
    render_explore_followup_result,
    render_intent_analysis_payload,
    render_intent_analysis_text,
    render_intent_state_update,
)
from app.tools.intent_preview_tool import (
    analyze_current_career_direction,
    analyze_current_interest,
    analyze_current_major_interest,
    analyze_current_region_interest,
    analyze_current_school_interest,
    preview_current_career_intent_confirmation,
    preview_current_intent_confirmation,
    preview_current_major_intent_confirmation,
    preview_current_region_intent_confirmation,
    preview_current_school_intent_confirmation,
    preview_interest_analysis_from_request,
)
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.intent_state_tool import (
    _apply_intents,
    _build_impact_preview_from_analysis,
    _build_preview_title,
    _build_plan_relation_analysis,
    _enrich_plan_relation_analysis_from_state,
    _build_single_turn_recovery_context,
    _build_proposed_profile,
    _recover_intents_from_context,
    _build_select_items,
    ANALYSIS_STAGE_CONFIRMED,
    ANALYSIS_STAGE_INTEREST,
    INTENT_CONFIRM_POPUP_TYPE,
    INTENT_MODE_CONSTRAINT,
    INTENT_MODE_PREFERENCE,
    analyze_volunteer_intent_change,
    apply_selected_intents,
    merge_selected_values,
    update_volunteer_intent_state,
)
from app.tools.intent_response_tool import (
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
)


async def _render_analysis(ctx, *args, **kwargs):
    major_intents = kwargs.get("major_intents") if "major_intents" in kwargs else (args[0] if len(args) > 0 else None)
    school_intents = kwargs.get("school_intents") if "school_intents" in kwargs else (args[1] if len(args) > 1 else None)
    city_intents = kwargs.get("city_intents") if "city_intents" in kwargs else (args[2] if len(args) > 2 else None)
    analysis_stage = kwargs.get("analysis_stage", ANALYSIS_STAGE_CONFIRMED)
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


async def _confirm_update(ctx):
    return json.loads(await update_volunteer_intent_state(ctx, action="confirm"))


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


async def _apply_selected(session_id: str, batch: str, selected_data: dict) -> dict:
    return parse_intent_state_update_result(
        await apply_selected_intents(
            session_id=session_id,
            batch=batch,
            selected_data=selected_data,
        )
    ).model_dump()


# ---------------------------------------------------------------------------
# Fixtures: a minimal current profile and mock code-enrichment lookups
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_profile():
    """A blank UserProfile with no existing intents."""
    return UserProfile()


@pytest.fixture
def existing_profile():
    """A UserProfile that already has some intents."""
    return UserProfile(
        major=MajorIntent(
            level2=["工学"], level2_emotion=["Strong"],
            level3=["软件工程"], level3_emotion=["Strong"],
        ),
        school=SchoolIntent(
            colleges=["北京大学"], colleges_emotion=["Strong"],
        ),
        city=CityIntent(
            province=["北京"], province_emotion=["Strong"],
        ),
    )


# Deterministic fake lookup maps so we don't depend on real data files
_FAKE_MAJOR_MAPS = (
    {"哲学": "1"},                      # level1
    {"哲学类": "2", "工学": "08"},       # level2
    {"哲学": "010101", "逻辑学": "010102", "软件工程": "080902"},  # level3
)

_FAKE_SCHOOL_MAP = {"北京大学": "1", "清华大学": "3"}

_FAKE_PROVINCE_CITY_MAPS = (
    {"北京": "110000", "安徽": "340000"},           # provinces
    {"合肥": "340100000000", "北京市": "110100"},    # cities
)


@pytest.fixture(autouse=True)
def mock_code_lookups():
    """Patch the cached lookup functions so tests don't need real data files."""
    with (
        patch("app.util.code_enrichment._load_major_name_to_code_map", return_value=_FAKE_MAJOR_MAPS),
        patch("app.util.code_enrichment._load_school_name_to_id_map", return_value=_FAKE_SCHOOL_MAP),
        patch("app.util.code_enrichment._load_province_city_maps", return_value=_FAKE_PROVINCE_CITY_MAPS),
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildProposedProfileCodes:
    """Verify that _build_proposed_profile returns *_code fields."""

    def test_major_codes_added(self, empty_profile):
        result = _build_proposed_profile(
            empty_profile,
            major_intents={"level2": ["哲学类"], "level3": ["哲学", "逻辑学"]},
            school_intents=None,
            city_intents=None,
            batch="01",
        )
        assert result["major_intent"]["level2_code"] == ["2"]
        assert result["major_intent"]["level3_code"] == ["010101", "010102"]

    def test_school_codes_added(self, empty_profile):
        result = _build_proposed_profile(
            empty_profile,
            major_intents=None,
            school_intents={"colleges": ["北京大学", "清华大学"]},
            city_intents=None,
            batch="01",
        )
        assert result["college_info"]["values_code"] == ["1", "3"]

    def test_city_codes_added(self, empty_profile):
        result = _build_proposed_profile(
            empty_profile,
            major_intents=None,
            school_intents=None,
            city_intents={"province": ["北京", "安徽"], "city": ["合肥"]},
            batch="01",
        )
        assert result["city_info"]["province_code"] == ["110000", "340000"]
        assert result["city_info"]["city_code"] == ["340100000000"]

    def test_negative_codes_added(self, empty_profile):
        result = _build_proposed_profile(
            empty_profile,
            major_intents={"negative_level3": ["逻辑学"]},
            school_intents={"negative_colleges": ["清华大学"]},
            city_intents={"negative_province": ["安徽"]},
            batch="01",
        )
        assert result["negative_major_intent"]["level3_code"] == ["010102"]
        assert result["negative_college_info"]["values_code"] == ["3"]
        assert result["negative_city_info"]["province_code"] == ["340000"]

    def test_merge_preserves_existing_and_adds_codes(self, existing_profile):
        """When merging into an existing profile, codes cover both old and new names."""
        result = _build_proposed_profile(
            existing_profile,
            major_intents={"level3": ["哲学"]},   # add to existing ["软件工程"]
            school_intents={"colleges": ["清华大学"]},  # add to existing ["北京大学"]
            city_intents=None,
            batch="01",
        )
        # names: 软件工程 (existing) + 哲学 (new)
        assert result["major_intent"]["level3"] == ["软件工程", "哲学"]
        assert result["major_intent"]["level3_code"] == ["080902", "010101"]

        # schools: 北京大学 (existing) + 清华大学 (new)
        assert result["college_info"]["values"] == ["北京大学", "清华大学"]
        assert result["college_info"]["values_code"] == ["1", "3"]

    def test_no_intents_still_has_codes_from_existing(self, existing_profile):
        """Even with no new intents, existing names should get codes."""
        result = _build_proposed_profile(
            existing_profile,
            major_intents=None,
            school_intents=None,
            city_intents=None,
            batch="01",
        )
        # existing profile had 工学 in level2 and 软件工程 in level3
        assert result["major_intent"]["level2_code"] == ["08"]
        assert result["major_intent"]["level3_code"] == ["080902"]
        assert result["college_info"]["values_code"] == ["1"]
        assert result["city_info"]["province_code"] == ["110000"]


# ---------------------------------------------------------------------------
# Tests for _build_select_items (selective adoption)
# ---------------------------------------------------------------------------

class TestBuildSelectItems:
    """Verify that _build_select_items produces correct items/existing_items."""

    def test_all_new_intents(self, empty_profile):
        """All intents are new — should appear in items list."""
        items, existing = _build_select_items(
            empty_profile,
            major_intents={"level3": ["哲学", "逻辑学"]},
            school_intents={"colleges": ["北京大学"]},
            city_intents={"province": ["北京"]},
        )
        assert len(items) == 4
        assert len(existing) == 0
        # Each item should have content, value, selected=True
        for item in items:
            assert "content" in item
            assert "value" in item
            assert item["selected"] is True

    def test_all_existing_intents(self, existing_profile):
        """All intents already in profile — should appear in existing_items."""
        items, existing = _build_select_items(
            existing_profile,
            major_intents={"level3": ["软件工程"]},
            school_intents={"colleges": ["北京大学"]},
            city_intents={"province": ["北京"]},
        )
        assert len(items) == 0
        assert len(existing) == 3

    def test_mixed_new_and_existing(self, existing_profile):
        """Some new, some existing."""
        items, existing = _build_select_items(
            existing_profile,
            major_intents={"level3": ["软件工程", "哲学"]},  # 软件工程 exists, 哲学 is new
            school_intents=None,
            city_intents=None,
        )
        assert len(items) == 1  # 哲学
        assert len(existing) == 1  # 软件工程
        assert items[0]["value"] == {"major_intents": {"level3": ["哲学"]}}

    def test_negative_intents_wording(self, empty_profile):
        """Negative intents should describe exclusion / lower priority semantics."""
        items, existing = _build_select_items(
            empty_profile,
            major_intents={"negative_level3": ["医学"]},
            school_intents={"negative_colleges": ["某大学"]},
            city_intents=None,
        )
        assert len(items) == 2
        for item in items:
            assert "排除" in item["content"] or "降低" in item["content"]

    def test_no_intents_returns_empty(self, empty_profile):
        """No intents at all."""
        items, existing = _build_select_items(empty_profile, None, None, None)
        assert items == []
        assert existing == []

    def test_item_value_structure(self, empty_profile):
        """Value dict should use v3 naming convention with single-element lists."""
        items, _ = _build_select_items(
            empty_profile,
            major_intents=None,
            school_intents={"colleges": ["清华大学"]},
            city_intents={"province": ["安徽"], "negative_city": ["合肥"]},
        )
        values = [item["value"] for item in items]
        assert {"school_intents": {"colleges": ["清华大学"]}} in values
        assert {"city_intents": {"province": ["安徽"]}} in values
        assert {"city_intents": {"negative_city": ["合肥"]}} in values


def test_render_existing_only_intent_reply_uses_existing_reference_wording():
    text = render_intent_analysis_payload(
        json.dumps(
            {
                "status": "existing_only",
                "sessionId": "1",
                "intentMode": "constraint",
                "analysisStage": "confirmed",
                "existingItems": [
                    {"content": "当前已记录偏好具体专业：法学"},
                    {"content": "当前已记录排除具体专业：护理学"},
                ],
            },
            ensure_ascii=False,
        )
    )

    assert "当前已经在后续参考中" in text
    assert "不需要重复确认" in text
    assert "**已在参考**" in text
    assert "偏好具体专业：法学" in text
    assert "排除具体专业：护理学" in text
    assert "下一步" in text
    assert "待确认" not in text
    assert "当前已记录" not in text


# ---------------------------------------------------------------------------
# Tests for merge_selected_values
# ---------------------------------------------------------------------------

class TestMergeSelectedValues:
    """Verify merge_selected_values combines value dicts correctly."""

    def test_merge_different_categories(self):
        selected = [
            {"major_intents": {"level3": ["计算机科学与技术"]}},
            {"school_intents": {"colleges": ["北京大学"]}},
            {"city_intents": {"province": ["北京"]}},
        ]
        result = merge_selected_values(selected)
        assert result["major_intents"]["level3"] == ["计算机科学与技术"]
        assert result["school_intents"]["colleges"] == ["北京大学"]
        assert result["city_intents"]["province"] == ["北京"]

    def test_merge_same_category_different_keys(self):
        selected = [
            {"major_intents": {"level2": ["工学"]}},
            {"major_intents": {"level3": ["软件工程"]}},
        ]
        result = merge_selected_values(selected)
        assert result["major_intents"]["level2"] == ["工学"]
        assert result["major_intents"]["level3"] == ["软件工程"]

    def test_merge_same_key_deduplicates(self):
        selected = [
            {"major_intents": {"level3": ["哲学"]}},
            {"major_intents": {"level3": ["哲学"]}},  # duplicate
            {"major_intents": {"level3": ["逻辑学"]}},
        ]
        result = merge_selected_values(selected)
        assert result["major_intents"]["level3"] == ["哲学", "逻辑学"]

    def test_merge_empty_list(self):
        result = merge_selected_values([])
        assert result == {}

    def test_merge_negative_intents(self):
        selected = [
            {"major_intents": {"negative_level3": ["医学"]}},
            {"city_intents": {"negative_province": ["广东"]}},
        ]
        result = merge_selected_values(selected)
        assert result["major_intents"]["negative_level3"] == ["医学"]
        assert result["city_intents"]["negative_province"] == ["广东"]


@pytest.mark.asyncio
async def test_analyze_intent_change_recovers_empty_args_via_fallback_extraction(empty_profile):
    ctx = SimpleNamespace(deps=SimpleNamespace(sessionid="7", batch="01", chat_history=[{"role": "user", "content": "不想去上海"}]))

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value='{"province": [], "city": [], "area": []}')),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value='{"province": ["上海"], "city": [], "area": []}')),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value='{"level1": [], "level2": [], "level3": []}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        resp = await _render_analysis(ctx, None, None, None, "delete")

    assert "上海" in resp
    assert "确认" in resp or "分析" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_soft_negative_stays_preference(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="8",
            batch="01",
            chat_history=[{"role": "user", "content": "不太想去上海"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        resp = await _render_analysis(
            ctx,
            None,
            None,
            {"negative_province": ["上海"]},
            None,
        )

    assert "上海" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_interest_stage_returns_structured_analysis(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="81",
            batch="01",
            chat_history=[{"role": "user", "content": "我更想去北京"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        resp = await _render_analysis(
            ctx,
            None,
            None,
            {"province": ["北京"]},
            None,
            analysis_stage="interest",
        )

    assert "先帮你看一眼" in resp
    assert "下一步" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_interest_stage_without_confirm_returns_interest_preview(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="82",
            batch="01",
            chat_history=[{"role": "user", "content": "体制内适合我吗"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        resp = await _render_analysis(
            ctx,
            None,
            None,
            None,
            None,
            analysis_stage="interest",
            career_intents={"positive": ["system_public_service"]},
            confirm_enabled=False,
        )

    assert "体制内/考公导向" in resp
    assert "下一步" in resp


@pytest.mark.asyncio
async def test_preview_interest_analysis_from_request_routes_career_scope_to_direction_analysis():
    request_context = SimpleNamespace(
        sessionid="186",
        batch="01",
        chat_history=[{"role": "user", "content": "体制内适不适合我"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    with patch(
        "app.tools.intent_preview_tool._preview_direction_analysis_from_request",
        new=AsyncMock(return_value="方向分析"),
    ) as mock_preview:
        resp = await preview_interest_analysis_from_request(
            request_context,
            recovery_scope="career_preference",
        )

    mock_preview.assert_awaited_once_with(request_context, "system_public_service")
    assert resp == "方向分析"


@pytest.mark.asyncio
async def test_preview_interest_analysis_from_request_non_career_scope_still_uses_generic_preview():
    request_context = SimpleNamespace(
        sessionid="187",
        batch="01",
        chat_history=[{"role": "user", "content": "北京有哪些学校值得看"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )

    with patch(
        "app.tools.intent_preview_tool.analyze_volunteer_intent_change",
        new=AsyncMock(return_value='{"status":"empty","sessionId":"187","message":"通用兴趣分析"}'),
    ) as mock_edit:
        resp = await preview_interest_analysis_from_request(request_context)

    mock_edit.assert_awaited_once()
    assert resp == "通用兴趣分析"


def test_preview_interest_analysis_from_request_defaults_to_generic_recovery_scope():
    request_context = SimpleNamespace(
        sessionid="187b",
        batch="01",
        chat_history=[{"role": "user", "content": "看看北京还有没有更合适的"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )

    with patch(
        "app.tools.intent_preview_tool.analyze_volunteer_intent_change",
        new=AsyncMock(return_value='{"status":"empty","sessionId":"187b","message":"通用兴趣分析"}'),
    ) as mock_edit:
        resp = asyncio.run(preview_interest_analysis_from_request(request_context))

    mock_edit.assert_awaited_once_with(
        SimpleNamespace(deps=request_context),
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="generic",
        confirm_enabled=False,
        persist_cache=False,
    )
    assert resp == "通用兴趣分析"


def test_analyze_current_interest_wrapper_delegates_to_interest_stage_preview():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "更想去北京"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(
            analyze_current_interest(
                ctx,
                intent_mode=INTENT_MODE_PREFERENCE,
                recovery_scope="generic",
            )
        )

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="generic",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


def test_analyze_current_interest_wrapper_defaults_to_generic_recovery_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "北京的机会多一点吗"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(analyze_current_interest(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="generic",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


def test_analyze_current_school_interest_wrapper_uses_school_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "北京联合大学值不值得看"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(analyze_current_school_interest(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="school",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


def test_analyze_current_major_interest_wrapper_uses_major_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "计算机类值不值得继续看"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(analyze_current_major_interest(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="major",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


def test_analyze_current_region_interest_wrapper_uses_region_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "北京机会多不多"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(analyze_current_region_interest(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="region",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


@pytest.mark.asyncio
async def test_analyze_intent_change_major_fit_question_forces_read_only_interest_without_cache(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="756",
            batch="01",
            chat_history=[{"role": "user", "content": "电子信息工程适合我吗"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["电子信息工程"])),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先帮你看一眼",
                    "currentPlanFit": ["从当前选科和方案承接看，这个方向可以继续了解。"],
                    "currentPlanConflict": [],
                    "candidateOpportunity": ["候选里还有相近机会可继续展开。"],
                    "nextActionHints": ["如果你想继续深入，我可以再细看方案承接。"],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"level3": ["电子信息工程"]},
        )

    payload = json.loads(payload_text)
    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert "初步分析" in payload["title"]
    assert payload["items"][0]["value"] == {"major_intents": {"level3": ["电子信息工程"]}}
    save_mock.assert_not_awaited()


def test_analyze_intent_change_interest_stage_existing_preference_returns_analysis_preview():
    existing_profile = UserProfile(city=CityIntent(province=["北京"]))
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="10",
            batch="01",
            chat_history=[{"role": "user", "content": "北京的机会多一点吗"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先帮你看一眼",
                    "currentPlanFit": ["当前方案里已经有一部分在北京。"],
                    "currentPlanConflict": [],
                    "candidateOpportunity": ["候选里还有北京机会可继续看。"],
                    "nextActionHints": ["如果你愿意，我可以继续细看。"],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=existing_profile)

        resp = asyncio.run(
            _render_analysis(
                ctx,
                None,
                None,
                {"province": ["北京"]},
                None,
                analysis_stage=ANALYSIS_STAGE_INTEREST,
                confirm_enabled=False,
            )
        )

    assert "北京" in resp
    assert "现在比较贴近的部分" in resp


def test_analyze_current_career_direction_wrapper_uses_career_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "体制内适不适合我"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=["system_public_service"])),
        patch("app.tools.intent_preview_tool.preview_direction_analysis_from_request", new=AsyncMock(return_value="ok")) as mock_preview,
    ):
        resp = asyncio.run(analyze_current_career_direction(ctx))

    assert resp == "ok"
    mock_preview.assert_awaited_once_with(ctx.deps, "system_public_service")


def test_preview_current_intent_confirmation_wrapper_delegates_to_confirm_stage():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "不去上海"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(
            preview_current_intent_confirmation(
                ctx,
                intent_mode=INTENT_MODE_CONSTRAINT,
                recovery_scope="generic",
            )
        )

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="generic",
        confirm_enabled=True,
        intent_mode=INTENT_MODE_CONSTRAINT,
    )


def test_preview_current_major_intent_confirmation_wrapper_uses_major_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(preview_current_major_intent_confirmation(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="major",
        confirm_enabled=True,
        intent_mode=None,
    )


def test_preview_current_major_intent_confirmation_wrapper_passes_explicit_major_intents():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(
            preview_current_major_intent_confirmation(
                ctx,
                major_intents={"add": ["网络与新媒体"]},
            )
        )

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        {"level3": ["网络与新媒体"]},
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="major",
        confirm_enabled=True,
        intent_mode=None,
    )


@pytest.mark.asyncio
async def test_analyze_intent_change_accepts_interested_and_priority_major_aliases_without_fallback_extraction():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager", return_value=SimpleNamespace(get_current_profile=AsyncMock(return_value=MagicMock()))),
        patch("app.tools.intent_state_tool._build_select_items", return_value=([{"content": "ok", "value": {"major_intents": {"level3": ["网络与新媒体"]}}, "selected": True}], [])),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={"summaryTitle": "", "currentPlanFit": [], "currentPlanConflict": [], "candidateOpportunity": [], "nextActionHints": []})),
        patch("app.tools.intent_state_tool._build_impact_preview_from_analysis", return_value=""),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        payload = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"interested": ["网络与新媒体"], "priority": ["网络与新媒体"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            recovery_scope="major",
            confirm_enabled=True,
            persist_cache=False,
        )

    assert "网络与新媒体" in payload
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_accepts_include_major_alias_without_fallback_extraction():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "想学跨境电商"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager", return_value=SimpleNamespace(get_current_profile=AsyncMock(return_value=MagicMock()))),
        patch("app.tools.intent_state_tool._build_select_items", return_value=([{"content": "ok", "value": {"major_intents": {"level3": ["跨境电子商务"]}}, "selected": True}], [])),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={"summaryTitle": "", "currentPlanFit": [], "currentPlanConflict": [], "candidateOpportunity": [], "nextActionHints": []})),
        patch("app.tools.intent_state_tool._build_impact_preview_from_analysis", return_value=""),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        payload = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"include": ["跨境电商"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            recovery_scope="major",
            confirm_enabled=True,
            persist_cache=False,
        )

    assert "跨境电子商务" in payload
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_merges_with_existing_pending_cache():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "不想学审计"}],
        )
    )

    save_cache_mock = AsyncMock()
    with (
        patch("app.tools.intent_state_tool.ProfileManager", return_value=SimpleNamespace(get_current_profile=AsyncMock(return_value=MagicMock()))),
        patch("app.tools.intent_state_tool._build_select_items", return_value=([{"content": "ok", "value": {"major_intents": {"negative_level3": ["审计学"]}}, "selected": True}], [])),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={"summaryTitle": "", "currentPlanFit": [], "currentPlanConflict": [], "candidateOpportunity": [], "nextActionHints": []})),
        patch("app.tools.intent_state_tool._build_impact_preview_from_analysis", return_value=""),
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["审计学"])),
        patch(
            "app.tools.intent_state_tool.get_intent_change_cache",
            new=AsyncMock(return_value={"data": {"planEditCache": {"major_intents": {"level3": ["跨境电子商务"]}, "intent_mode": "preference"}}}),
        ),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=save_cache_mock),
    ):
        payload = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"exclude": ["审计"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            recovery_scope="major",
            confirm_enabled=True,
        )

    assert "审计学" in payload
    save_cache_mock.assert_awaited_once()
    saved_cache = save_cache_mock.await_args.args[1]
    assert saved_cache["major_intents"]["level3"] == ["跨境电子商务"]
    assert saved_cache["major_intents"]["negative_level3"] == ["审计学"]
    assert saved_cache["intent_mode"] == "constraint"


@pytest.mark.asyncio
async def test_recover_major_intent_from_context_uses_local_shortcut_for_fit_question():
    from app.agent.context import RequestContext

    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="57",
            chat_history=[{"role": "user", "content": "网络与新媒体适合我吗"}],
            batch="01",
        )
    )

    with (
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["网络与新媒体"])),
        patch("app.tools.intent_state_tool.get_major_codes_async", new=AsyncMock(return_value=["447"])),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        major_intents, school_intents, city_intents, career_intents = await intent_state_tool_module._recover_intents_from_context(
            ctx,
            recovery_scope="major",
        )

    assert major_intents == {"level3": ["网络与新媒体"]}
    assert school_intents is None
    assert city_intents is None
    assert career_intents is None
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recover_major_intent_from_recent_compare_context_for_anaphora_confirmation():
    from app.agent.context import RequestContext

    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="57",
            chat_history=[
                {"role": "user", "content": "网络与新媒体和跨境电子商务哪个更适合我"},
                {"role": "assistant", "content": "网络与新媒体更贴合你一些。"},
                {"role": "user", "content": "那两个方向都先作为偏好"},
            ],
            batch="01",
        )
    )

    async def _fake_resolve(names, level, batch):
        mapping = {
            ("网络与新媒体", "level3"): ["网络与新媒体"],
            ("跨境电子商务", "level3"): ["跨境电子商务"],
        }
        return mapping.get((names[0], level), [])

    async def _fake_codes(names, level, batch):
        mapping = {
            ("网络与新媒体", "level3"): ["447"],
            ("跨境电子商务", "level3"): ["448"],
        }
        return mapping.get((names[0], level), [])

    with (
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(side_effect=_fake_resolve)),
        patch("app.tools.intent_state_tool.get_major_codes_async", new=AsyncMock(side_effect=_fake_codes)),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        major_intents, school_intents, city_intents, career_intents = await intent_state_tool_module._recover_intents_from_context(
            ctx,
            recovery_scope="major",
        )

    assert major_intents == {"level3": ["网络与新媒体", "跨境电子商务"]}
    assert school_intents is None
    assert city_intents is None
    assert career_intents is None
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


def test_preview_current_school_intent_confirmation_wrapper_uses_school_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "想优先看北工大"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(preview_current_school_intent_confirmation(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="school",
        confirm_enabled=True,
        intent_mode=None,
    )


def test_preview_current_region_intent_confirmation_wrapper_uses_region_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "以后优先看北京"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(preview_current_region_intent_confirmation(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="region",
        confirm_enabled=True,
        intent_mode=None,
    )


def test_preview_current_career_intent_confirmation_wrapper_uses_career_scope():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "以后优先按体制内方向看"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(preview_current_career_intent_confirmation(ctx))

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        None,
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="career_preference",
        confirm_enabled=True,
        intent_mode=None,
    )


@pytest.mark.asyncio
async def test_preview_current_career_intent_confirmation_negative_request_preserves_career_exclusion_in_cache():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="1011",
            chat_history=[{"role": "user", "content": "现在不想进体制内了"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False))),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": [], "negative": ["system_public_service"]}, ensure_ascii=False))),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先帮你看一眼",
                    "currentPlanFit": [],
                    "currentPlanConflict": ["当前方案里先避开体制内/考公导向更合适。"],
                    "candidateOpportunity": [],
                    "nextActionHints": ["如果确认，我就按这个方向作为后续要求。"],
                }
            ),
        ),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        payload_text = await preview_current_career_intent_confirmation(ctx)

    assert "体制内/考公导向" in payload_text
    save_mock.assert_awaited_once()
    saved_args = save_mock.await_args.args
    assert saved_args[0] == 1011
    assert saved_args[1]["intent_mode"] == INTENT_MODE_CONSTRAINT
    assert saved_args[1]["career_intents"] == {"negative": ["system_public_service"]}


@pytest.mark.asyncio
async def test_analyze_volunteer_intent_change_returns_structured_payload(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="5001",
            batch="01",
            chat_history=[{"role": "user", "content": "更想去北京"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)
        payload = json.loads(
            await analyze_volunteer_intent_change(
                ctx,
                city_intents={"province": ["北京"]},
                analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            )
        )

    assert payload["status"] == "ready"
    assert payload["intentMode"] == INTENT_MODE_PREFERENCE
    assert payload["items"]
    assert payload["items"][0]["value"] == {"city_intents": {"province": ["北京"]}}


@pytest.mark.asyncio
async def test_update_volunteer_intent_state_confirm_returns_structured_result():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="5002",
            batch="01",
            pending_intent_change=True,
        )
    )

    with (
        patch("app.tools.intent_state_tool.get_intent_change_cache", new=AsyncMock(return_value={"data": {"planEditCache": {"city_intents": {"province": ["北京"]}, "intent_mode": INTENT_MODE_PREFERENCE}}})),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock()) as state_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        result = json.loads(await update_volunteer_intent_state(ctx, action="confirm"))

    query_mock.assert_not_awaited()
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()
    assert result["action"] == "confirm"
    assert result["applied"] is True
    assert result["intentMode"] == INTENT_MODE_PREFERENCE
    assert "记下来了" in result["message"]


@pytest.mark.asyncio
async def test_update_volunteer_intent_state_confirm_prefers_phase_pending():
    from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="5004",
            batch="01",
            conversation_phase=ConversationPhase(
                state=PhaseState.INTENT_PREVIEWING,
                pending=PendingConfirmation(
                    kind="intent_change",
                    action_family="set_preference",
                    preview_summary="设置地域偏好",
                    execution_payload={
                        "city_intents": {"province": ["北京"]},
                        "intent_mode": INTENT_MODE_PREFERENCE,
                    },
                ),
            ),
        )
    )

    with (
        patch("app.tools.intent_state_tool.get_intent_change_cache", new=AsyncMock(return_value={"data": {"planEditCache": {"city_intents": {"province": ["上海"]}, "intent_mode": INTENT_MODE_PREFERENCE}}})),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock()) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()
        result = json.loads(await update_volunteer_intent_state(ctx, action="confirm"))

    assert result["applied"] is True
    assert result["intentMode"] == INTENT_MODE_PREFERENCE
    mock_pm.update_city_intent.assert_awaited_once()
    save_mock.assert_awaited_once()
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_volunteer_intent_state_confirm_requires_explicit_confirmation_utterance():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="5003",
            batch="01",
            chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        )
    )

    result = json.loads(await update_volunteer_intent_state(ctx, action="confirm"))

    assert result["action"] == "confirm"
    assert result["applied"] is False
    assert result["messageCode"] == "confirm_required"
    assert "待确认状态" in result["message"]


@pytest.mark.asyncio
async def test_analyze_intent_change_interest_career_intent_uses_single_direction_analysis():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="188",
            batch="01",
            chat_history=[{"role": "user", "content": "稳定就业适不适合我"}],
        )
    )
    with patch(
        "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
        new=AsyncMock(return_value="单方向分析"),
    ) as mock_preview:
        resp = await _render_analysis(
            ctx,
            career_intents={"positive": ["stable_employment"]},
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            confirm_enabled=False,
        )

    mock_preview.assert_awaited_once_with(ctx.deps, "stable_employment")
    assert resp == "单方向分析"


@pytest.mark.asyncio
async def test_analyze_intent_change_interest_multiple_career_intents_use_direction_comparison():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="189",
            batch="01",
            chat_history=[{"role": "user", "content": "更适合稳定就业还是深造"}],
        )
    )
    with patch(
        "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
        new=AsyncMock(return_value="多方向对比"),
    ) as mock_preview:
        resp = await _render_analysis(
            ctx,
            career_intents={"positive": ["stable_employment", "further_study"]},
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            confirm_enabled=False,
        )

    mock_preview.assert_awaited_once_with(ctx.deps, ["stable_employment", "further_study"])
    assert resp == "多方向对比"


@pytest.mark.asyncio
async def test_preview_direction_analysis_from_request_returns_explainer_text():
    from app.tools.intent_preview_tool import preview_direction_analysis_from_request

    request_context = SimpleNamespace(
        sessionid="84",
        batch="01",
        chat_history=[{"role": "user", "content": "体制内适合我吗"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "v1", "schoolNature": "公办", "schoolCategory": "师范"},
                    {"volunteerId": "v2", "schoolNature": "民办", "schoolCategory": "综合"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {"volunteerId": "v1", "schoolNature": "公办", "schoolCategory": "师范"},
                    {"volunteerId": "v3", "schoolNature": "公办", "schoolCategory": "政法"},
                ]
            },
        }
    }

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch(
            "app.tools.explore_direction_tool._generate_direction_analysis_content",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    model_dump=lambda: {
                        "summaryTitle": "模型生成的方向分析",
                        "currentPlanFit": ["更适合先结合个人特点判断，不急着直接改方案。"],
                        "currentPlanConflict": [],
                        "candidateOpportunity": ["候选里还有可以继续展开看的机会。"],
                        "nextActionHints": ["如果你愿意，我可以继续细看这个方向。"],
                    }
                )
            ),
        ),
    ):
        resp = await preview_direction_analysis_from_request(request_context, "system_public_service")

    assert "模型生成的方向分析" in resp


@pytest.mark.asyncio
async def test_preview_direction_comparison_from_request_returns_compare_text():
    from app.tools.intent_preview_tool import preview_direction_comparison_from_request

    request_context = SimpleNamespace(
        sessionid="85",
        batch="01",
        chat_history=[{"role": "user", "content": "更适合深造还是就业"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "v1", "schoolRankTags": ["保研"]},
                    {"volunteerId": "v2", "schoolNature": "公办", "schoolCategory": "师范"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {"volunteerId": "v1", "schoolRankTags": ["保研"]},
                    {"volunteerId": "v2", "schoolNature": "公办", "schoolCategory": "师范"},
                    {"volunteerId": "v3", "schoolNature": "公办", "schoolCategory": "政法"},
                ]
            },
        }
    }

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch(
            "app.tools.explore_direction_tool._generate_direction_analysis_content",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    model_dump=lambda: {
                        "summaryTitle": "模型生成的双方向分析",
                        "currentPlanFit": ["先看人和方向的匹配，再看现有方案承接。"],
                        "currentPlanConflict": [],
                        "candidateOpportunity": ["候选里还有补充空间。"],
                        "nextActionHints": ["可以继续单独展开其中一个方向。"],
                    }
                )
            ),
        ),
    ):
        resp = await preview_direction_comparison_from_request(
            request_context,
            ["further_study", "stable_employment"],
        )

    assert "方向对比分析" in resp
    assert "模型生成的双方向分析" in resp


@pytest.mark.asyncio
async def test_preview_direction_comparison_from_request_supports_multiple_slots():
    from app.tools.intent_preview_tool import preview_direction_comparison_from_request

    request_context = SimpleNamespace(
        sessionid="85",
        batch="01",
        chat_history=[{"role": "user", "content": "更适合深造、稳定就业还是体制内"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "v1", "schoolRankTags": ["保研"]},
                    {"volunteerId": "v2", "schoolNature": "公办", "schoolCategory": "师范"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {"volunteerId": "v1", "schoolRankTags": ["保研"]},
                    {"volunteerId": "v2", "schoolNature": "公办", "schoolCategory": "师范"},
                    {"volunteerId": "v3", "schoolNature": "公办", "schoolCategory": "政法"},
                ]
            },
        }
    }

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch(
            "app.tools.explore_direction_tool._generate_direction_analysis_content",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    model_dump=lambda: {
                        "summaryTitle": "模型生成的多方向分析",
                        "currentPlanFit": ["可以把多个方向一起放进个人发展偏好里看。"],
                        "currentPlanConflict": [],
                        "candidateOpportunity": ["候选里分别有不同方向的延展机会。"],
                        "nextActionHints": ["下一步可以单独展开最在意的方向。"],
                    }
                )
            ),
        ),
    ):
        resp = await preview_direction_comparison_from_request(
            request_context,
            ["further_study", "stable_employment", "system_public_service"],
        )

    assert "模型生成的多方向分析" in resp
    assert "候选里分别有不同方向的延展机会" in resp


@pytest.mark.asyncio
async def test_handle_intent_select_interest_candidate_query_returns_text_only():
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
        patch("app.tools.explore_followup_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}})),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 88}})),
    ):
        resp = await _render_followup(
            session_id="91",
            batch="01",
            action_type="candidate_query",
        )

    assert "88" in resp


@pytest.mark.asyncio
async def test_handle_intent_select_interest_plan_analyze_returns_interest_preview(empty_profile):
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
        patch("app.tools.explore_followup_tool.execute_plan_action", new=AsyncMock(return_value='{"summary":"当前判断：可以继续优化方案。","state_summary":"当前判断：可以继续优化方案。"}')) as exec_mock,
    ):
        resp = await _render_followup(
            session_id="92",
            batch="01",
            action_type="plan_analyze",
        )

    assert "当前判断" in resp
    plan_mock.assert_awaited_once()
    exec_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_intent_select_interest_prefer_confirm_returns_confirm_preview(empty_profile):
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
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)
        resp = await _render_followup(
            session_id="93",
            batch="01",
            action_type="prefer_confirm",
        )

    assert "北京" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_existing_constraint_still_returns_candidate_action(existing_profile):
    existing_profile.city.negative_province = ["安徽"]
    existing_profile.city.negative_province_emotion = ["Strong"]
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="9",
            batch="01",
            chat_history=[{"role": "user", "content": "不去安徽"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 88}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=existing_profile)

        resp = await _render_analysis(
            ctx,
            None,
            None,
            {"negative_province": ["安徽"]},
            None,
        )

    assert "安徽" in resp
    assert "排除省份：安徽" in resp
    assert "不需要重复确认" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_existing_preference_returns_helpful_text(existing_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="10",
            batch="01",
            chat_history=[{"role": "user", "content": "想去北京"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=existing_profile)

        resp = await _render_analysis(
            ctx,
            None,
            None,
            {"province": ["北京"]},
            None,
        )

    assert "当前已经在后续参考中" in resp
    assert "不需要重复确认" in resp
    assert "现在这份方案" in resp
    assert "专家优选组合" not in resp
    assert "暂时不用重复更新" not in resp


def test_build_impact_preview_uses_plan_relation_wording_for_preference():
    text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_PREFERENCE)
    )

    assert "**结合当前方案给你的提醒**" in text
    assert "结合当前方案给你的提醒" in text
    assert "现在比较贴近的部分" in text
    assert "还可以再看看的机会" in text
    assert "新进入优选" not in text
    assert "移出优选" not in text


def test_render_intent_analysis_text_uses_light_markdown_sections():
    text = render_intent_analysis_text(
        title="我整理一下这个想法。",
        impact_text="**结合当前方案给你的提醒**\n\n**还可以再看看的机会**\n- 上海建桥学院(01)-网络与新媒体",
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_PREFERENCE,
        items=[{"content": "确认后，将把网络与新媒体作为后续优先参考的专业方向。"}],
    )

    assert text.startswith("**分析结论**")
    assert "\n\n**当前判断**\n" not in text
    assert "\n\n**结合当前方案给你的提醒**\n" in text
    assert "**还可以再看看的机会**" in text
    assert "\n\n**下一步**\n" in text


def test_intent_candidate_messages_do_not_use_left_right_layout_wording():
    followup_text = render_explore_followup_result(
        ExploreFollowupResult(
            actionType="candidate_query",
            sessionId="style-1",
            messageCode="candidate_query",
            filteredTotal=24,
            baseTotal=3000,
        )
    )
    update_text = render_intent_state_update(
        IntentStateUpdateResult(
            action="confirm",
            sessionId="style-2",
            messageCode="constraint_applied",
            filteredTotal=128,
            baseTotal=3200,
        )
    )
    preview_text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_CONSTRAINT)
    )

    combined = "\n".join([followup_text, update_text, preview_text])
    assert "右侧" not in combined
    assert "左侧" not in combined
    assert "候选结果" in followup_text
    assert "候选结果" in update_text
    assert "还可以再看看的机会" in preview_text
    assert "下一步建议" in preview_text


def test_render_intent_state_update_summarizes_confirmed_preference_items():
    text = render_intent_state_update(
        IntentStateUpdateResult(
            action="confirm",
            sessionId="style-3",
            messageCode="preference_applied",
            merged={
                "major_intents": {"level3": ["法学", "财政学"], "negative_level3": ["护理学"]},
                "city_intents": {"province": ["北京"], "negative_city": ["上海"]},
                "career_intents": {"positive": ["system_public_service"]},
            },
        )
    )

    assert "本次确认内容" in text
    assert "偏好专业：法学、财政学" in text
    assert "排除专业：护理学" in text
    assert "偏好地域：北京" in text
    assert "排除地域：上海" in text
    assert "发展方向：体制内/考公导向" in text
    assert "- 后续使用：" in text
    assert "- 下一步：" in text
    assert "不会直接改动当前方案顺序" in text


def test_intent_preview_major_labels_do_not_expose_internal_levels(empty_profile):
    items, existing_items = _build_select_items(
        empty_profile,
        major_intents={"level3": ["法学"], "negative_level3": ["护理学"]},
        school_intents=None,
        city_intents=None,
    )

    text = "\n".join(item["content"] for item in [*items, *existing_items])
    assert "level3" not in text
    assert "专业方向" in text


def test_intent_preview_items_use_conditional_wording_before_confirmation(empty_profile):
    items, _ = _build_select_items(
        empty_profile,
        major_intents={"level3": ["法学"], "negative_level3": ["护理学"]},
        school_intents={"colleges": ["北京大学"], "negative_colleges": ["清华大学"]},
        city_intents={"province": ["北京"], "negative_city": ["上海"]},
        career_intents={"positive": ["system_public_service"], "negative": ["high_pressure_sales"]},
        intent_mode=INTENT_MODE_CONSTRAINT,
    )

    text = "\n".join(item["content"] for item in items)
    assert text.count("确认后") == len(items)
    assert "确认后，将把法学作为后续优先参考的专业方向" in text
    assert "确认后，将把护理学作为明确不考虑的内容" in text
    assert "后面看候选和方案时都会按这个要求来" not in text
    assert "记成明确不考虑" not in text


def test_render_intent_state_update_summarizes_confirmed_constraint_items():
    text = render_intent_state_update(
        IntentStateUpdateResult(
            action="confirm",
            sessionId="style-4",
            messageCode="constraint_applied",
            filteredTotal=128,
            baseTotal=3200,
            merged={"school_intents": {"negative_colleges": ["北京大学"]}},
        )
    )

    assert "本次确认内容" in text
    assert "排除院校：北京大学" in text
    assert "后续查看候选和方案时会按这条要求作为参考" in text
    assert "- 候选结果：按当前要求查看时约 128 个，整体候选约 3200 个。" in text
    assert "候选展示会按这条要求更新" not in text


def test_build_impact_preview_uses_interest_stage_summary_when_requested():
    text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_PREFERENCE, "interest")
    )

    assert "先帮你看一眼" in text
    assert "如果继续了解" in text
    assert "现在比较贴近的部分" not in text


def test_build_preview_title_uses_explore_wording_for_interest_stage():
    title = _build_preview_title(None, INTENT_MODE_PREFERENCE, ANALYSIS_STAGE_INTEREST)

    assert "初步分析" in title
    assert "记成你的偏好" not in title
    assert "勾选" not in title


def test_build_preview_title_uses_pending_boundary_without_candidate_tightening():
    title = _build_preview_title(None, INTENT_MODE_CONSTRAINT, ANALYSIS_STAGE_CONFIRMED)

    assert "确认前不会正式生效" in title
    assert "不会直接改动当前方案" in title
    assert "卡片" not in title
    assert "候选结果收紧" not in title
    assert "专家推荐" not in title


def test_render_intent_analysis_text_drops_generic_impact_placeholders():
    text = render_intent_analysis_text(
        title="好的，我先把这次你提到的想法整理一下。确认后我会按这个思路继续帮你看方案和给建议。",
        impact_text=(
            "**结合当前方案给你的提醒**\n\n"
            "**现在比较贴近的部分**\n"
            "- 我先帮你看看，现在这份方案里有没有贴近这个方向的内容，以及还有哪些值得继续关注的机会。\n\n"
            "**还可以再看看的机会**\n"
            "- 我也会顺手看看，方案外还有没有更贴近这个方向的机会。\n\n"
            "**下一步建议**\n"
            "- 下一步更适合继续看看这份方案和你的想法有多匹配，或者直接让我给你调整建议。"
        ),
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_PREFERENCE,
        items=[{"content": "确认后，将把网络与新媒体作为后续优先参考的专业方向。"}],
    )

    assert "结合当前方案给你的提醒" not in text
    assert "我先帮你看看" not in text
    assert "顺手看看" not in text
    assert "这次识别到的可采纳内容" in text
    assert "网络与新媒体" in text


def test_public_service_alignment_does_not_match_generic_public_undergraduate():
    item = {
        "schoolNature": "公办",
        "schoolLevel": "本科",
        "schoolCategory": "理工",
        "majorName": "计算机科学与技术",
        "majorCategory": "计算机类",
        "majorDiscipline": "工学",
        "schoolRankTags": [],
        "schoolBasicTags": [],
        "schoolPopupTags": [],
        "majorRankTags": [],
        "majorPlanTags": [],
    }

    assert _is_public_service_aligned_item(item) is False


def test_public_service_alignment_matches_policy_oriented_major():
    item = {
        "schoolNature": "公办",
        "schoolLevel": "本科",
        "schoolCategory": "理工",
        "majorName": "行政管理",
        "majorCategory": "公共管理类",
        "majorDiscipline": "管理学",
        "schoolRankTags": [],
        "schoolBasicTags": [],
        "schoolPopupTags": [],
        "majorRankTags": [],
        "majorPlanTags": [],
    }

    assert _is_public_service_aligned_item(item) is True


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_uses_current_plan_and_candidate_opportunities():
    base_analysis = {
        "stage": "confirmed",
        "summaryTitle": "方案关联分析",
        "currentPlanFit": ["我先帮你看看，现在这份方案里有没有贴近这个方向的内容，以及还有哪些值得继续关注的机会。"],
        "currentPlanConflict": [],
        "candidateOpportunity": ["我也会顺手看看，方案外还有没有更贴近这个方向的机会。"],
        "nextActionHints": [],
    }
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "v1"},
                    {"volunteerId": "v2"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "v1",
                        "schoolName": "北京大学",
                        "majorName": "计算机科学与技术",
                        "provinceName": "北京",
                        "tier": "冲",
                        "majorCategory": "计算机类",
                    },
                    {
                        "volunteerId": "v2",
                        "schoolName": "上海大学",
                        "majorName": "金融学",
                        "provinceName": "上海",
                        "tier": "稳",
                    },
                    {
                        "volunteerId": "v3",
                        "schoolName": "北京工业大学",
                        "majorName": "软件工程",
                        "provinceName": "北京",
                        "tier": "稳",
                        "majorCategory": "计算机类",
                    },
                ]
            },
        }
    }

    with (
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
    ):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "22",
            base_analysis,
            intent_mode=INTENT_MODE_PREFERENCE,
            major_intents={"level2": ["计算机类"]},
            school_intents=None,
            city_intents={"province": ["北京"], "negative_province": ["上海"]},
        )

    assert "北京大学" in analysis["currentPlanFit"][0]
    assert "上海大学" in analysis["currentPlanConflict"][0]
    assert "北京工业大学" in analysis["candidateOpportunity"][0]
    assert "1 个" in analysis["candidateOpportunity"][-1]
    assert not any("我先帮你看看" in item for item in analysis["currentPlanFit"])
    assert not any("顺手看看" in item for item in analysis["candidateOpportunity"])


@pytest.mark.asyncio
async def test_analyze_intent_change_normalizes_major_add_alias_and_matches_nested_candidates():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        )
    )
    planning_state = {
        "data": {
            "orderedPlanState": {"items": []},
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "c1",
                        "schoolName": "上海建桥学院(01)",
                        "provinceName": "上海",
                        "tier": "稳",
                        "majorItems": [
                            {
                                "majorName": "网络与新媒体",
                                "majorCategory": "新闻传播学类",
                            }
                        ],
                    },
                    {
                        "volunteerId": "c2",
                        "school_name": "福州大学至诚学院(第001组)",
                        "province_name": "福建",
                        "level": "保",
                        "majors": [
                            {
                                "major_name": "网络与新媒体",
                                "subCategoryName": "新闻传播学类",
                            }
                        ],
                    },
                ]
            },
        }
    }

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"add": ["网络与新媒体"]},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    assert payload["status"] == "ready"
    assert payload["items"][0]["value"] == {"major_intents": {"level3": ["网络与新媒体"]}}
    assert "上海建桥学院(01)-网络与新媒体" in payload["impactText"]
    assert "福州大学至诚学院(第001组)-网络与新媒体" in payload["impactText"]
    assert "暂时没看到" not in payload["impactText"]
    assert "2 个" in payload["impactText"]


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_prioritizes_fit_examples_by_existing_region_preferences():
    base_analysis = _build_plan_relation_analysis(INTENT_MODE_PREFERENCE)
    planning_state = {
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveRegions": ["上海", "浙江"],
                }
            },
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "wuhan-1"},
                    {"volunteerId": "zhejiang-1"},
                    {"volunteerId": "shanghai-1"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "wuhan-1",
                        "schoolName": "武汉传媒学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "湖北",
                        "tier": "稳",
                    },
                    {
                        "volunteerId": "zhejiang-1",
                        "schoolName": "浙江越秀外国语学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "浙江",
                        "tier": "稳",
                    },
                    {
                        "volunteerId": "shanghai-1",
                        "schoolName": "上海建桥学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "上海",
                        "tier": "保",
                    },
                ]
            },
        }
    }

    with patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "57",
            base_analysis,
            intent_mode=INTENT_MODE_PREFERENCE,
            major_intents={"level3": ["网络与新媒体"]},
            school_intents=None,
            city_intents=None,
        )

    fit_text = analysis["currentPlanFit"][0]
    assert fit_text.index("上海建桥学院第01组") < fit_text.index("浙江越秀外国语学院第01组")
    assert fit_text.index("浙江越秀外国语学院第01组") < fit_text.index("武汉传媒学院第01组")


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_prioritizes_candidate_opportunities_by_existing_region_preferences():
    base_analysis = _build_plan_relation_analysis(INTENT_MODE_PREFERENCE)
    planning_state = {
        "data": {
            "profileState": {
                "explicitProfile": {
                    "positiveRegions": ["上海", "江西"],
                }
            },
            "orderedPlanState": {"items": []},
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "wuhan-1",
                        "schoolName": "武汉东湖学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "湖北",
                        "tier": "稳",
                    },
                    {
                        "volunteerId": "jiangxi-1",
                        "schoolName": "江西软件职业技术大学第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "江西",
                        "tier": "保",
                    },
                    {
                        "volunteerId": "shanghai-1",
                        "schoolName": "上海建桥学院第01组",
                        "majorName": "网络与新媒体",
                        "provinceName": "上海",
                        "tier": "保",
                    },
                ]
            },
        }
    }

    with patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "57",
            base_analysis,
            intent_mode=INTENT_MODE_PREFERENCE,
            major_intents={"level3": ["网络与新媒体"]},
            school_intents=None,
            city_intents=None,
        )

    opportunity_text = analysis["candidateOpportunity"][0]
    assert opportunity_text.index("上海建桥学院第01组") < opportunity_text.index("江西软件职业技术大学第01组")
    assert opportunity_text.index("江西软件职业技术大学第01组") < opportunity_text.index("武汉东湖学院第01组")


@pytest.mark.asyncio
async def test_analyze_intent_change_normalizes_cross_border_ecommerce_alias_and_matches_guangzhou_candidate():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "想学跨境电商"}],
        )
    )
    planning_state = {
        "data": {
            "orderedPlanState": {"items": []},
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "gz1",
                        "schoolName": "广州工商学院(201)",
                        "provinceName": "广东",
                        "tier": "保",
                        "majorItems": [
                            {
                                "majorName": "跨境电子商务",
                                "majorCategory": "电子商务类",
                            }
                        ],
                    },
                    {
                        "volunteerId": "hk1",
                        "schoolName": "海口经济学院",
                        "provinceName": "海南",
                        "tier": "保",
                        "majorName": "国际经济与贸易（跨境电商方向）",
                    },
                ]
            },
        }
    }

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["跨境电子商务"])),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"add": ["跨境电商"]},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    cached = save_mock.await_args.args[1]
    assert payload["items"][0]["value"] == {"major_intents": {"level3": ["跨境电子商务"]}}
    assert cached["major_intents"] == {"level3": ["跨境电子商务"]}
    assert "跨境电商" not in payload["impactText"]
    assert "广州工商学院(201)-跨境电子商务" in payload["impactText"]


@pytest.mark.asyncio
async def test_analyze_intent_change_normalizes_audit_alias_and_includes_fourth_conflict_candidate():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "不想学审计"}],
        )
    )
    audit_items = [
        ("广州新华学院第01组", "广东东莞", "稳"),
        ("武昌工学院第01组", "湖北", "稳"),
        ("青岛工学院第01组", "山东", "保"),
        ("广东白云学院第01组", "广东广州", "保"),
    ]
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": f"audit-{index}",
                        "schoolName": school,
                        "provinceName": province,
                        "tier": tier,
                        "majorItems": [{"majorName": "审计学", "majorCategory": "工商管理类"}],
                    }
                    for index, (school, province, tier) in enumerate(audit_items)
                ]
            },
            "candidatePoolState": {"items": []},
        }
    }

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["审计学"])),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"remove": ["审计"]},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    cached = save_mock.await_args.args[1]
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level3": ["审计学"]}}
    assert cached["major_intents"] == {"negative_level3": ["审计学"]}
    assert "审计学" in payload["impactText"]
    assert "广东白云学院第01组-审计学" in payload["impactText"]
    assert "审计）" not in payload["impactText"]


@pytest.mark.asyncio
async def test_analyze_intent_change_normalizes_accounting_alias_from_user_dialog():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="57",
            batch="01",
            chat_history=[{"role": "user", "content": "不想学会计"}],
        )
    )
    accounting_items = [
        ("南宁学院第01组", "广西", "冲"),
        ("滇池学院第01组", "云南杨林校区", "冲"),
        ("昆明理工大学津桥学院第01组", "云南", "冲"),
        ("湖北恩施学院第02组", "湖北", "稳"),
        ("广州商学院第01组", "广东", "稳"),
    ]
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": f"accounting-{index}",
                        "schoolName": school,
                        "provinceName": province,
                        "tier": tier,
                        "majorItems": [{"majorName": "会计学", "majorCategory": "工商管理类"}],
                    }
                    for index, (school, province, tier) in enumerate(accounting_items)
                ]
            },
            "candidatePoolState": {"items": []},
        }
    }

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["会计学"])),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"remove": ["会计"]},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    cached = save_mock.await_args.args[1]
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level3": ["会计学"]}}
    assert cached["major_intents"] == {"negative_level3": ["会计学"]}
    assert "南宁学院第01组-会计学" in payload["impactText"]
    assert "广州商学院第01组-会计学" in payload["impactText"]


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_falls_back_to_ordered_items_when_candidate_map_missing():
    base_analysis = {
        "stage": "confirmed",
        "summaryTitle": "方案关联分析",
        "currentPlanFit": [],
        "currentPlanConflict": [],
        "candidateOpportunity": [],
        "nextActionHints": [],
    }
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": "v1",
                        "schoolName": "北京联合大学",
                        "majorName": "软件工程",
                        "provinceName": "北京",
                        "tier": "冲",
                        "majorCategory": "计算机类",
                    },
                    {
                        "volunteerId": "v2",
                        "schoolName": "上海理工大学",
                        "majorName": "金融学",
                        "provinceName": "上海",
                        "tier": "稳",
                    },
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "v3",
                        "schoolName": "北京工业大学",
                        "majorName": "计算机科学与技术",
                        "provinceName": "北京",
                        "tier": "稳",
                        "majorCategory": "计算机类",
                    },
                ]
            },
        }
    }

    with (
        patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
    ):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "23",
            base_analysis,
            intent_mode=INTENT_MODE_PREFERENCE,
            major_intents={"level2": ["计算机类"]},
            school_intents=None,
            city_intents={"province": ["北京"], "negative_province": ["上海"]},
        )

    assert "北京联合大学" in analysis["currentPlanFit"][0]
    assert "上海理工大学" in analysis["currentPlanConflict"][0]
    assert "北京工业大学" in analysis["candidateOpportunity"][0]


def test_build_impact_preview_uses_plan_relation_wording_for_constraint():
    text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_CONSTRAINT)
    )

    assert "现在比较贴近的部分" in text
    assert "还可以再看看的机会" in text
    assert "下一步建议" in text
    assert "专家推荐" not in text


def test_build_single_turn_recovery_context_uses_latest_user_message_only():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "我想去广东"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "不去北京"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    single_turn_ctx = _build_single_turn_recovery_context(ctx)

    assert single_turn_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]


@pytest.mark.asyncio
async def test_recover_intents_from_context_uses_latest_user_message_only():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "我想去广东"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "不去北京"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    async def _assert_single_turn_city(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False)

    async def _assert_single_turn_negative_city(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"province": ["北京"], "city": []}, ensure_ascii=False)

    async def _assert_single_turn_major(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False)

    async def _assert_single_turn_negative_major(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False)

    async def _assert_single_turn_school(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False)

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", side_effect=_assert_single_turn_city),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", side_effect=_assert_single_turn_negative_city),
        patch("app.tools.major_intent_tool.extract_major_intent", side_effect=_assert_single_turn_major),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", side_effect=_assert_single_turn_negative_major),
        patch("app.tools.school_intent_tool.extract_school_intent", side_effect=_assert_single_turn_school),
    ):
        major, school, city, career = await _recover_intents_from_context(ctx)

    assert major is None
    assert school is None
    assert city == {"negative_province": ["北京"]}
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_extracts_career_intent_from_latest_message():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "之前先看看学校"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "想去体制内"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": ["system_public_service"], "negative": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False))),
    ):
        major, school, city, career = await _recover_intents_from_context(ctx)

    assert major is None
    assert school is None
    assert city is None
    assert career == {"positive": ["system_public_service"]}


@pytest.mark.asyncio
async def test_recover_intents_from_context_career_scope_skips_city_major_school_extractors():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "想进体制"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": ["system_public_service"], "negative": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="career_preference")

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    assert major is None
    assert school is None
    assert city is None
    assert career == {"positive": ["system_public_service"]}


@pytest.mark.asyncio
async def test_recover_intents_from_context_school_scope_only_uses_school_extractor():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "看看北京联合大学"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": ["北京联合大学"], "negative_colleges": []}, ensure_ascii=False))) as school_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="school")

    school_mock.assert_awaited_once()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school == {"colleges": ["北京联合大学"]}
    assert city is None
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_major_scope_only_uses_major_extractors():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "看看计算机类"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": ["计算机类"], "level3": []}, ensure_ascii=False))) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))) as negative_major_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="major")

    major_mock.assert_awaited_once()
    negative_major_mock.assert_awaited_once()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major == {"level2": ["计算机类"]}
    assert school is None
    assert city is None
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_region_scope_only_uses_city_extractors():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "看看北京的机会"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": ["北京"], "city": [], "area": []}, ensure_ascii=False))) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False))) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="region")

    city_mock.assert_awaited_once()
    negative_city_mock.assert_awaited_once()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school is None
    assert city == {"province": ["北京"]}
    assert career is None


@pytest.mark.asyncio
async def test_handle_intent_select_constraint_returns_candidate_filters_action():
    selected_data = {
        "message_id": 1001,
        "selected": [{"city_intents": {"negative_province": ["上海"]}}],
    }
    message_content = {
        "intentMode": INTENT_MODE_CONSTRAINT,
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["上海"]}}}],
    }

    with (
        patch("app.tools.intent_state_tool.get_message_by_id", new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}})),
        patch("app.tools.intent_state_tool.update_message", new=AsyncMock()),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 128}})) as query_mock,
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = (await _apply_selected("7", "01", selected_data))["message"]

    assert "128" in resp
    assert "128" in resp
    query_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_constraint_intents_updates_candidate_filters_without_regenerating_candidate_pool():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 64}})),
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = await _apply_intents(
            session_id="12",
            batch="01",
            merged={"city_intents": {"negative_province": ["北京"]}},
            intent_mode=INTENT_MODE_CONSTRAINT,
        )

    assert resp.filteredTotal == 64
    assert resp.baseTotal == 3200
    assert resp.candidateFilters["negativeProvinceNames"] == ["北京"]
    assert "专家优选组合" not in resp.message
    assert "不符合这条要求的地方" in resp.message


@pytest.mark.asyncio
async def test_apply_preference_intents_returns_text_without_candidate_requery():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock()) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = await _apply_intents(
            session_id="13",
            batch="01",
            merged={"city_intents": {"negative_province": ["北京"]}},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    query_mock.assert_not_awaited()
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()
    assert resp.applied is True
    assert resp.intentMode == INTENT_MODE_PREFERENCE
    assert "记下来了" in resp.message
    assert "现在这份方案" in resp.message
    assert "专家优选组合" not in resp.message


@pytest.mark.asyncio
async def test_apply_preference_career_intent_updates_planning_latent_profile():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch(
            "app.tools.intent_state_tool.get_planning_state",
            new=AsyncMock(return_value={"data": {"profileState": {"latentProfile": {"futureDevelopment": {"careerTypes": ["读研"]}}}}}),
        ) as state_mock,
        patch("app.tools.intent_state_tool.update_planning_latent_profile", new=AsyncMock()) as latent_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = await _apply_intents(
            session_id="13",
            batch="01",
            merged={"career_intents": {"positive": ["system_public_service"]}},
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    query_mock.assert_not_awaited()
    state_mock.assert_awaited_once()
    latent_mock.assert_awaited_once_with(
        13,
        future_development={"careerTypes": ["读研", "体制内/考公导向"]},
    )
    assert resp.applied is True
    assert "记下来了" in resp.message


@pytest.mark.asyncio
async def test_analyze_intent_change_builds_preview_for_career_intent_recovery():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="23",
            chat_history=[{"role": "user", "content": "想去体制内"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False))),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": ["system_public_service"], "negative": []}, ensure_ascii=False))),
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = await _render_analysis(ctx)

    assert "体制内/考公导向" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_career_scope_avoids_general_extractors():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="24",
            chat_history=[{"role": "user", "content": "想进体制"}],
            batch="01",
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
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": ["system_public_service"], "negative": []}, ensure_ascii=False))) as career_mock,
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=UserProfile())
        resp = await _render_analysis(ctx, recovery_scope="career_preference")

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_awaited_once()
    assert "体制内/考公导向" in resp


@pytest.mark.asyncio
async def test_recover_intents_from_context_uses_career_extractor_negative_result():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "不想进体制内"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value=json.dumps({"positive": [], "negative": ["system_public_service"]}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": [], "area": []}, ensure_ascii=False))),
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": [], "city": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": [], "level3": []}, ensure_ascii=False))),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False))),
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="career_preference")

    assert major is None
    assert school is None
    assert city is None
    assert career == {"negative": ["system_public_service"]}


@pytest.mark.asyncio
async def test_analyze_intent_change_interest_stage_without_scope_does_not_trigger_fallback_recovery():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="25",
            chat_history=[{"role": "user", "content": "看看北京有哪些学校"}],
            batch="01",
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
        resp = await _render_analysis(
            ctx,
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            confirm_enabled=False,
        )

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    assert "还没准确整理出可调整的报考意向" in resp


@pytest.mark.asyncio
async def test_confirm_intent_change_with_career_intent_updates_latent_profile():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="31",
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

        resp = await _confirm_update(ctx)

    assert resp["applied"] is True
    assert "记下来了" in resp["message"]
    query_mock.assert_not_awaited()
    state_mock.assert_awaited_once()
    latent_mock.assert_awaited_once_with(
        31,
        future_development={"careerTypes": ["读研", "体制内/考公导向"]},
    )


@pytest.mark.asyncio
async def test_handle_intent_select_preference_does_not_regenerate_candidate_pool():
    selected_data = {
        "message_id": 1002,
        "selected": [{"city_intents": {"negative_province": ["上海"]}}],
    }
    message_content = {
        "intentMode": INTENT_MODE_PREFERENCE,
        "clickable": True,
        "clicked": False,
        "items": [{"value": {"city_intents": {"negative_province": ["上海"]}}}],
    }

    with (
        patch("app.tools.intent_state_tool.get_message_by_id", new=AsyncMock(return_value={"data": {"content": json.dumps(message_content, ensure_ascii=False)}})),
        patch("app.tools.intent_state_tool.update_message", new=AsyncMock()),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock()) as query_mock,
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = (await _apply_selected("7", "01", selected_data))["message"]

    assert isinstance(resp, str)
    assert "记下来了" in resp
    query_mock.assert_not_awaited()
