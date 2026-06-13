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
from app.tools.intent_relation_tool import _item_matches_career_intents
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
    IntentSideEffectDecision,
    _major_relation_notes_from_latest_utterance,
    _normalize_region_area_polarity_payloads,
    _prune_generated_negative_complements_for_only_keep,
    _recover_polarity_major_intent_locally_from_latest_utterance,
    _recover_intents_from_context,
    _refine_major_boundary_mentions,
    _refine_major_intents_with_local_latest_utterance,
    _build_select_items,
    ANALYSIS_STAGE_CONFIRMED,
    ANALYSIS_STAGE_INTEREST,
    INTENT_CONFIRM_POPUP_TYPE,
    INTENT_MODE_CONSTRAINT,
    INTENT_MODE_PREFERENCE,
    analyze_volunteer_intent_change,
    apply_selected_intents,
    merge_selected_values,
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
        assert existing[0]["value"] == {"major_intents": {"level3": ["软件工程"]}}
        assert existing[1]["value"] == {"school_intents": {"colleges": ["北京大学"]}}
        assert existing[2]["value"] == {"city_intents": {"province": ["北京"]}}
        assert existing[0]["selected"] is False

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

    def test_existing_positive_major_with_negative_conflict_still_needs_confirmation(self):
        profile = UserProfile(
            major=MajorIntent(
                level2=["工商管理类"],
                negative_level2=["工商管理类"],
            )
        )

        items, existing = _build_select_items(
            profile,
            major_intents={"level2": ["工商管理类"]},
            school_intents=None,
            city_intents=None,
            batch="01",
        )

        assert existing == []
        assert items == [
            {
                "content": "将工商管理类从不优先或排除范围里重新纳入，后续专家推荐会更优先考虑它。",
                "value": {"major_intents": {"level2": ["工商管理类"]}},
                "selected": True,
            }
        ]

    def test_existing_negative_preference_can_upgrade_to_constraint_across_entities(self):
        profile = UserProfile(
            major=MajorIntent(negative_level3=["秘书学"]),
            school=SchoolIntent(negative_colleges=["南京大学"]),
            city=CityIntent(negative_province=["江苏"]),
        )

        items, existing = _build_select_items(
            profile,
            major_intents={"negative_level3": ["秘书学"]},
            school_intents={"negative_colleges": ["南京大学"]},
            city_intents={"negative_province": ["江苏"]},
            intent_mode=INTENT_MODE_CONSTRAINT,
            batch="01",
        )

        assert existing == []
        assert [item["value"] for item in items] == [
            {"major_intents": {"negative_level3": ["秘书学"]}},
            {"school_intents": {"negative_colleges": ["南京大学"]}},
            {"city_intents": {"negative_province": ["江苏"]}},
        ]
        assert all("明确不考虑" in item["content"] for item in items)

    def test_existing_positive_preference_can_upgrade_to_constraint_across_entities(self):
        profile = UserProfile(
            major=MajorIntent(level3=["法学"]),
            school=SchoolIntent(colleges=["北京大学"]),
            city=CityIntent(province=["北京"]),
        )

        items, existing = _build_select_items(
            profile,
            major_intents={"level3": ["法学"]},
            school_intents={"colleges": ["北京大学"]},
            city_intents={"province": ["北京"]},
            intent_mode=INTENT_MODE_CONSTRAINT,
            batch="01",
        )

        assert existing == []
        assert [item["value"] for item in items] == [
            {"major_intents": {"level3": ["法学"]}},
            {"school_intents": {"colleges": ["北京大学"]}},
            {"city_intents": {"province": ["北京"]}},
        ]
        assert all("明确要满足" in item["content"] for item in items)

    def test_existing_negative_preference_stays_existing_for_preference_mode(self):
        profile = UserProfile(city=CityIntent(negative_province=["江苏"]))

        items, existing = _build_select_items(
            profile,
            major_intents=None,
            school_intents=None,
            city_intents={"negative_province": ["江苏"]},
            intent_mode=INTENT_MODE_PREFERENCE,
            batch="01",
        )

        assert items == []
        assert existing[0]["value"] == {"city_intents": {"negative_province": ["江苏"]}}

    def test_constraint_state_hard_negative_stays_existing_for_constraint_mode(self, existing_profile):
        constraint_state = {
            "hardConstraints": {
                "mustExcludeMajors": ["法学类"],
                "mustExcludeSchools": ["南京大学"],
                "mustExcludeRegions": ["江苏"],
            }
        }

        items, existing = _build_select_items(
            existing_profile,
            major_intents={"negative_level3": ["法学"]},
            school_intents={"negative_colleges": ["南京大学"]},
            city_intents={"negative_province": ["江苏"]},
            intent_mode=INTENT_MODE_CONSTRAINT,
            batch="01",
            constraint_state=constraint_state,
        )

        assert items == []
        assert [item["value"] for item in existing] == [
            {"major_intents": {"negative_level3": ["法学"]}},
            {"school_intents": {"negative_colleges": ["南京大学"]}},
            {"city_intents": {"negative_province": ["江苏"]}},
        ]

    def test_constraint_state_soft_negative_can_upgrade_to_hard_constraint(self, empty_profile):
        constraint_state = {
            "softPreferences": {
                "avoidMajors": ["秘书学"],
                "avoidSchools": ["南京大学"],
                "avoidRegions": ["江苏"],
            }
        }

        items, existing = _build_select_items(
            empty_profile,
            major_intents={"negative_level3": ["秘书学"]},
            school_intents={"negative_colleges": ["南京大学"]},
            city_intents={"negative_province": ["江苏"]},
            intent_mode=INTENT_MODE_CONSTRAINT,
            batch="01",
            constraint_state=constraint_state,
        )

        assert existing == []
        assert [item["value"] for item in items] == [
            {"major_intents": {"negative_level3": ["秘书学"]}},
            {"school_intents": {"negative_colleges": ["南京大学"]}},
            {"city_intents": {"negative_province": ["江苏"]}},
        ]
        assert all("升级" in item["content"] or "明确不考虑" in item["content"] for item in items)

    def test_constraint_state_positive_strength_is_not_downgraded(self, empty_profile):
        constraint_state = {
            "hardConstraints": {
                "mustIncludeMajors": ["法学"],
                "mustIncludeSchools": ["北京大学"],
                "mustIncludeRegions": ["北京"],
            }
        }

        items, existing = _build_select_items(
            empty_profile,
            major_intents={"level3": ["法学"]},
            school_intents={"colleges": ["北京大学"]},
            city_intents={"province": ["北京"]},
            intent_mode=INTENT_MODE_PREFERENCE,
            batch="01",
            constraint_state=constraint_state,
        )

        assert items == []
        assert [item["value"] for item in existing] == [
            {"major_intents": {"level3": ["法学"]}},
            {"school_intents": {"colleges": ["北京大学"]}},
            {"city_intents": {"province": ["北京"]}},
        ]

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
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock(return_value='{"positive": {"province": [], "city": [], "area": []}, "negative": {"province": ["上海"], "city": []}}')),
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock(return_value='{"positive": {"level1": [], "level2": [], "level3": []}, "negative": {"level1": [], "level2": [], "level3": []}}')),
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value='{"colleges": [], "negative_colleges": []}')),
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock(return_value='{"positive": [], "negative": []}')),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        resp = await _render_analysis(ctx, None, None, None, "delete")

    assert "上海" in resp
    assert "点击采纳" in resp or "分析" in resp


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
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
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
async def test_analyze_intent_change_explicit_preference_does_not_downgrade_hard_negative(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="811",
            batch="01",
            chat_history=[{"role": "user", "content": "不去上海"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            city_intents={"negative_province": ["上海"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    assert payload["status"] == "ready"
    assert payload["intentMode"] == INTENT_MODE_CONSTRAINT
    assert payload["items"][0]["value"] == {"city_intents": {"negative_province": ["上海"]}}
    assert "明确不考虑" in payload["items"][0]["content"]


@pytest.mark.asyncio
async def test_analyze_intent_change_soft_negative_without_hit_returns_no_effect_notice(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="801",
            batch="01",
            chat_history=[{"role": "user", "content": "不太想去北京"}],
        )
    )

    save_cache_mock = AsyncMock()
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=save_cache_mock),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "",
                    "currentPlanFit": [],
                    "currentPlanConflict": ["暂时没有直接命中 北京 的志愿。"],
                    "candidateOpportunity": [],
                    "nextActionHints": [],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            city_intents={"negative_province": ["北京"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    assert payload["status"] == "empty"
    assert "不需要额外采纳" in payload["message"]
    assert "必须避开的报考条件" in payload["message"]
    save_cache_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_soft_negative_with_plan_conflict_stays_pending(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="802",
            batch="01",
            chat_history=[{"role": "user", "content": "不太想去江苏"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_cache_mock,
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "",
                    "currentPlanFit": [],
                    "currentPlanConflict": ["当前方案里命中了 20 条江苏相关志愿。"],
                    "candidateOpportunity": [],
                    "nextActionHints": [],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            city_intents={"negative_province": ["江苏"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            intent_mode=INTENT_MODE_PREFERENCE,
        )

    payload = json.loads(payload_text)
    assert payload["status"] == "ready"
    assert payload["intentMode"] == INTENT_MODE_PREFERENCE
    assert payload["items"][0]["value"] == {"city_intents": {"negative_province": ["江苏"]}}
    assert "不优先省份" in payload["items"][0]["content"]
    assert "明确不考虑" not in payload["items"][0]["content"]
    save_cache_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_hard_negative_region_defaults_to_constraint(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="803",
            batch="01",
            chat_history=[{"role": "user", "content": "不去北京"}],
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_cache_mock,
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "",
                    "currentPlanFit": [],
                    "currentPlanConflict": ["当前方案里命中了北京相关志愿。"],
                    "candidateOpportunity": [],
                    "nextActionHints": [],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            city_intents={"negative_province": ["北京"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        )

    payload = json.loads(payload_text)
    assert payload["status"] == "ready"
    assert payload["intentMode"] == INTENT_MODE_CONSTRAINT
    assert "明确不考虑" in payload["items"][0]["content"]
    save_cache_mock.assert_not_awaited()


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
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
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

    assert "先看影响" in resp
    assert "初步判断" not in resp
    assert "这次识别到的参考范围" in resp
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
async def test_preview_interest_analysis_from_request_uses_resolved_career_direction_slot():
    request_context = SimpleNamespace(
        sessionid="186b",
        batch="01",
        chat_history=[{"role": "user", "content": "稳定就业适不适合我"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=["stable_employment"])) as resolve_mock,
        patch(
            "app.tools.intent_preview_tool._preview_direction_analysis_from_request",
            new=AsyncMock(return_value="稳定就业方向分析"),
        ) as mock_preview,
    ):
        resp = await preview_interest_analysis_from_request(
            request_context,
            recovery_scope="career_preference",
        )

    resolve_mock.assert_awaited_once_with(request_context)
    mock_preview.assert_awaited_once_with(request_context, "stable_employment")
    assert resp == "稳定就业方向分析"


@pytest.mark.asyncio
async def test_preview_interest_analysis_from_request_uses_direction_comparison_for_multiple_career_slots():
    request_context = SimpleNamespace(
        sessionid="186c",
        batch="01",
        chat_history=[{"role": "user", "content": "稳定就业和读研哪个更适合"}],
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=["stable_employment", "further_study"])),
        patch(
            "app.tools.intent_preview_tool._preview_direction_comparison_from_request",
            new=AsyncMock(return_value="方向对比"),
        ) as comparison_mock,
        patch("app.tools.intent_preview_tool._preview_direction_analysis_from_request", new=AsyncMock()) as analysis_mock,
    ):
        resp = await preview_interest_analysis_from_request(
            request_context,
            recovery_scope="career_preference",
        )

    comparison_mock.assert_awaited_once_with(request_context, ["stable_employment", "further_study"])
    analysis_mock.assert_not_awaited()
    assert resp == "方向对比"


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


def test_analyze_current_major_interest_accepts_explicit_major_intents():
    from app.agent.context import RequestContext
    from app.schemas.tool_inputs import MajorIntentPreviewInput

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "物理不太好但选了物化地，计算机还现实吗"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(
            analyze_current_major_interest(
                ctx,
                major_intents=MajorIntentPreviewInput(level2=["计算机类"]),
            )
        )

    assert resp == "ok"
    mock_edit.assert_awaited_once_with(
        ctx,
        {"level2": ["计算机类"]},
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        recovery_scope="major",
        confirm_enabled=False,
        intent_mode=INTENT_MODE_PREFERENCE,
        persist_cache=False,
    )


def test_analyze_current_major_interest_delegates_two_concrete_majors_to_compare_tool():
    from app.agent.context import RequestContext

    progress_hints: list[str] = []

    async def on_progress(hint: str) -> None:
        progress_hints.append(hint)

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好"}],
        batch="01",
        progress_callback=on_progress,
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.compare_majors", new=AsyncMock(return_value="法学和财政学对比结果")) as compare_mock, \
            patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock()) as analyze_mock:
        resp = asyncio.run(analyze_current_major_interest(ctx))

    data = json.loads(resp)
    assert data["reply_strategy"] == "continue_model"
    assert data["analysis_kind"] == "major_compare"
    assert data["major_names"] == ["法学", "财政学"]
    assert data["message"] == "法学和财政学对比结果"
    assert progress_hints == ["正在对比这几个专业的差异..."]
    compare_mock.assert_awaited_once_with(ctx, "法学", "财政学")
    analyze_mock.assert_not_awaited()


def test_analyze_current_major_interest_keeps_multiple_major_mentions_on_interest_path():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "法学、财政学、审计学怎么排优先级"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.compare_majors", new=AsyncMock()) as compare_mock, \
            patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"继续由专业适配工具分析"}')) as analyze_mock:
        resp = asyncio.run(analyze_current_major_interest(ctx))

    assert resp == "继续由专业适配工具分析"
    compare_mock.assert_not_awaited()
    analyze_mock.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_analyze_intent_change_semantic_arbitration_downgrades_boundary_question(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="758",
            batch="01",
            chat_history=[{"role": "user", "content": "孩子不想当老师，师范是不是都别要"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="analysis_only",
                    confidence=0.91,
                    reason="用户在问师范和当老师的边界，不是要求直接记录排除。",
                )
            ),
        ) as classifier_mock,
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先帮你判断一下师范边界",
                    "currentPlanFit": ["先区分师范院校和师范专业。"],
                    "currentPlanConflict": [],
                    "candidateOpportunity": [],
                    "nextActionHints": ["如需记录，再明确告诉我。"],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"negative_level2": ["教育学类"]},
        )

    payload = json.loads(payload_text)
    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level2": ["教育学类"]}}
    assert ctx.deps.agent_observability["intentSideEffectDecision"]["decision"] == "analysis_only"
    classifier_mock.assert_awaited_once()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_semantic_arbitration_keeps_school_preference(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="759",
            batch="01",
            chat_history=[{"role": "user", "content": "华南理工这类学校能不能多看看"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="intent_preview",
                    confidence=0.88,
                    reason="用户希望后续多看这类院校。",
                )
            ),
        ) as classifier_mock,
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先整理院校偏好",
                    "currentPlanFit": [],
                    "currentPlanConflict": [],
                    "candidateOpportunity": [],
                    "nextActionHints": [],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            school_intents={"colleges": ["华南理工大学"]},
        )

    payload = json.loads(payload_text)
    assert payload["analysisStage"] == ANALYSIS_STAGE_CONFIRMED
    assert payload["items"][0]["value"] == {"school_intents": {"colleges": ["华南理工大学"]}}
    assert ctx.deps.agent_observability["intentSideEffectDecision"]["decision"] == "intent_preview"
    classifier_mock.assert_awaited_once()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_semantic_arbitration_downgrades_impact_first_request(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="760",
            batch="01",
            chat_history=[{"role": "user", "content": "医学护理这些别碰，财会还能接受，先看看影响"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="mixed_answer_then_ask",
                    confidence=0.9,
                    reason="用户要求先看影响，应先分析再询问是否记录。",
                )
            ),
        ) as classifier_mock,
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先看这个方向对方案的影响",
                    "currentPlanFit": ["财会类可以作为可接受方向继续看承接。"],
                    "currentPlanConflict": ["医学和护理需要检查当前方案是否已有相关条目。"],
                    "candidateOpportunity": [],
                    "nextActionHints": ["如果要记为后续参考，再明确确认。"],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={
                "level2": ["工商管理类", "财政学类", "金融学类"],
                "negative_level1": ["医学"],
                "negative_level2": ["护理学类"],
            },
        )

    payload = json.loads(payload_text)
    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert payload["items"]
    assert "记成" not in json.dumps(payload["items"], ensure_ascii=False)
    assert "更新为" not in json.dumps(payload["items"], ensure_ascii=False)
    assert ctx.deps.agent_observability["intentSideEffectDecision"]["decision"] == "mixed_answer_then_ask"
    classifier_mock.assert_awaited_once()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_semantic_arbitration_keeps_explicit_negative_major_preference(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="7601",
            batch="01",
            chat_history=[{"role": "user", "content": "不太想学秘书"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="analysis_only",
                    confidence=0.9,
                    reason="模型误判为只读分析。",
                )
            ),
        ) as classifier_mock,
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(return_value=["秘书学"])),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "",
                    "currentPlanFit": [],
                    "currentPlanConflict": ["当前方案里有秘书学相关志愿，需要确认后才会降低优先级。"],
                    "candidateOpportunity": [],
                    "nextActionHints": [],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            major_intents={"negative_level3": ["秘书学"]},
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            recovery_scope="major",
            confirm_enabled=True,
            persist_cache=False,
        )

    payload = json.loads(payload_text)
    assert payload["analysisStage"] == ANALYSIS_STAGE_CONFIRMED
    assert payload["status"] == "ready"
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level3": ["秘书学"]}}
    assert "不优先具体专业" in payload["items"][0]["content"]
    assert "偏好" not in payload["items"][0]["content"]
    assert ctx.deps.agent_observability["intentSideEffectDecision"]["honored"] is False
    classifier_mock.assert_awaited_once()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_region_intent_downgrade_keeps_preview_language_read_only(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="761",
            batch="01",
            chat_history=[{"role": "user", "content": "广西贵州内蒙这些要不要放，孩子有点排斥"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="mixed_answer_then_ask",
                    confidence=0.86,
                    reason="用户在问是否要放这些地区，应先解释取舍，再询问是否整理成确认卡片。",
                )
            ),
        ),
        patch(
            "app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state",
            new=AsyncMock(
                return_value={
                    "summaryTitle": "先看偏远地区取舍",
                    "currentPlanFit": [],
                    "currentPlanConflict": [],
                    "candidateOpportunity": ["这类地区可能提供部分保底机会。"],
                    "nextActionHints": ["如果要降低优先级，需要先生成确认卡片。"],
                }
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            city_intents={"negative_province": ["广西", "贵州", "内蒙古"]},
            recovery_scope="region",
        )

    payload = json.loads(payload_text)
    rendered = render_intent_analysis_payload(payload_text)
    payload_text_for_model = json.dumps(payload, ensure_ascii=False)

    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    values = [
        item["value"]["city_intents"]["negative_province"][0]
        for item in payload["items"]
    ]
    assert values == ["广西", "贵州", "内蒙古"]
    assert all("可整理成待确认" in item["content"] for item in payload["items"])
    assert "记成" not in payload_text_for_model
    assert "已经记录" not in payload_text_for_model
    assert "后面给你看方案时会尽量往后放" not in payload_text_for_model
    assert "列出来让你采纳" in rendered
    assert "采纳前不会生效" in rendered
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_region_intent_downgrade_ignores_recovered_entity_for_abstract_region_boundary(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="762",
            batch="01",
            chat_history=[{"role": "user", "content": "省外可以，但太偏的地方不想去"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._recover_intents_from_context",
            new=AsyncMock(return_value=(None, None, {"province": ["江苏"]}, None)),
        ) as recover_mock,
        patch(
            "app.tools.intent_state_tool._classify_intent_side_effect",
            new=AsyncMock(
                return_value=IntentSideEffectDecision(
                    decision="analysis_only",
                    confidence=0.9,
                    reason="用户在描述抽象地域边界，应先解释再询问是否记录。",
                )
            ),
        ),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            recovery_scope="region",
        )

    payload = json.loads(payload_text)
    rendered = render_intent_analysis_payload(payload_text)

    assert payload["status"] == "empty"
    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert payload["items"] == []
    assert "江苏" not in rendered
    assert "不会改动方案" in rendered
    assert "列出来让你采纳" in rendered
    assert ctx.deps.agent_observability["intentSideEffectDecision"]["honored"] is True
    recover_mock.assert_awaited_once()
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_region_intent_empty_recovery_returns_boundary_clarification(empty_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="763",
            batch="01",
            chat_history=[{"role": "user", "content": "省外可以，但太偏的地方不想去"}],
            enable_intent_side_effect_arbitration=True,
            agent_observability={},
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
        patch(
            "app.tools.intent_state_tool._recover_intents_from_context",
            new=AsyncMock(return_value=(None, None, None, None)),
        ) as recover_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=empty_profile)

        payload_text = await analyze_volunteer_intent_change(
            ctx,
            recovery_scope="region",
        )

    payload = json.loads(payload_text)
    rendered = render_intent_analysis_payload(payload_text)

    assert payload["status"] == "empty"
    assert payload["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert "不会改动方案" in rendered
    assert "省外" in rendered
    assert "偏远" in rendered
    recover_mock.assert_awaited_once()
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
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_mock,
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
    assert "当前情况" in resp
    assert "当前方案里已经有一部分在北京" in resp
    save_mock.assert_not_awaited()


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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
    )


def test_preview_current_major_intent_confirmation_wrapper_accepts_positive_level_aliases():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "会计审计这类还行，土木建筑那种别碰"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value='{"status":"empty","sessionId":"s1","message":"ok"}')) as mock_edit:
        resp = asyncio.run(
            preview_current_major_intent_confirmation(
                ctx,
                major_intents={
                    "positive_level2": ["工商管理类"],
                    "negative_level2": ["土木类", "建筑类"],
                },
            )
        )

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
    mock_edit.assert_awaited_once_with(
        ctx,
        {"level2": ["工商管理类"], "negative_level2": ["土木类", "建筑类"]},
        None,
        None,
        None,
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        career_intents=None,
        recovery_scope="major",
        confirm_enabled=True,
        intent_mode=None,
        constraint_intent_type=None,
    )


def test_preview_current_major_intent_confirmation_wrapper_keeps_structured_payload():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "想学网络与新媒体"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)
    payload = json.dumps(
        {
            "status": "ready",
            "sessionId": "s1",
            "title": "好的，我先把这次你提到的想法整理一下。",
            "items": [
                {
                    "content": "将网络与新媒体更新为偏好方向。",
                    "value": {"major_intents": {"level3": ["网络与新媒体"]}},
                    "selected": True,
                }
            ],
            "impactText": "当前方案里暂未看到特别贴近的志愿。",
        },
        ensure_ascii=False,
    )

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value=payload)):
        resp = asyncio.run(preview_current_major_intent_confirmation(ctx))

    data = json.loads(resp)
    assert data["status"] == "ready"
    assert data["reply_strategy"] == "preview_wait_confirm"
    assert data["items"][0]["value"] == {"major_intents": {"level3": ["网络与新媒体"]}}
    assert "点击采纳后生效" in data["message"]


def test_preview_current_major_intent_confirmation_wrapper_marks_interest_stage_for_model_synthesis():
    from app.agent.context import RequestContext

    request_context = RequestContext(
        userid="u1",
        sessionid="s1",
        chat_history=[{"role": "user", "content": "医学护理这些别碰，财会还能接受，先看看影响"}],
        batch="01",
    )
    ctx = SimpleNamespace(deps=request_context)
    payload = json.dumps(
        {
            "status": "ready",
            "sessionId": "s1",
            "title": "先按这个方向看影响和边界。",
            "analysisStage": ANALYSIS_STAGE_INTEREST,
            "items": [
                {
                    "content": "排除医学",
                    "value": {"major_intents": {"negative_level1": ["医学"]}},
                    "selected": True,
                },
                {
                    "content": "偏好会计学",
                    "value": {"major_intents": {"level3": ["会计学"]}},
                    "selected": True,
                },
            ],
            "impactText": "医学方向会被避开，财会方向可继续看候选承接。",
        },
        ensure_ascii=False,
    )

    with patch("app.tools.intent_preview_tool.analyze_volunteer_intent_change", new=AsyncMock(return_value=payload)):
        resp = asyncio.run(preview_current_major_intent_confirmation(ctx))

    data = json.loads(resp)
    assert data["analysisStage"] == ANALYSIS_STAGE_INTEREST
    assert data["reply_strategy"] == "continue_model"
    assert "医学方向会被避开" in data["message"]


def test_interest_stage_major_analysis_renders_concrete_impact_boundaries():
    from app.tools.intent_response_tool import render_intent_analysis_payload

    payload = json.dumps(
        {
            "status": "ready",
            "sessionId": "s1",
            "title": "你提到的这个方向，我先结合你现在的情况做个初步分析。",
            "analysisStage": ANALYSIS_STAGE_INTEREST,
            "items": [
                {
                    "content": "偏好会计学",
                    "value": {"major_intents": {"level3": ["会计学"]}},
                    "selected": True,
                },
                {
                    "content": "排除医学",
                    "value": {"major_intents": {"negative_level1": ["医学"]}},
                    "selected": True,
                },
            ],
            "impactText": "我先帮你看看，这个要求和你现在的方案是否有冲突，以及还有没有合适的可选机会。",
        },
        ensure_ascii=False,
    )

    rendered = render_intent_analysis_payload(payload)

    assert "避开 医学" in rendered
    assert "会计学" in rendered
    assert "确认前它只是分析口径" in rendered
    assert "当前方案里已有相关志愿" in rendered


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
            persist_cache=True,
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
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as extract_polarity_mock,
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
    extract_polarity_mock.assert_not_awaited()
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recover_major_intent_from_context_recovers_mixed_polarity_locally_without_llm():
    from app.agent.context import RequestContext

    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="57",
            chat_history=[{"role": "user", "content": "医学护理这些别碰，财会还能接受，先看看影响"}],
            batch="01",
        )
    )

    with (
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as extract_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        major_intents, school_intents, city_intents, career_intents = await intent_state_tool_module._recover_intents_from_context(
            ctx,
            recovery_scope="major",
        )

    assert major_intents == {
        "negative_level1": ["医学"],
        "negative_level3": ["护理学"],
        "level3": ["会计学", "财务管理", "审计学"],
    }
    assert school_intents is None
    assert city_intents is None
    assert career_intents is None
    extract_polarity_mock.assert_not_awaited()
    extract_major_mock.assert_not_awaited()
    extract_negative_mock.assert_not_awaited()


def test_local_major_recovery_keeps_positive_tendency_and_negative_constraint():
    payload = _recover_polarity_major_intent_locally_from_latest_utterance(
        "我倾向法学和财政学但护理不要",
        "01",
    )

    assert payload == {
        "level3": ["法学", "财政学"],
        "negative_level3": ["护理学"],
    }


def test_refine_major_intents_dedupes_same_name_across_levels():
    payload = _refine_major_intents_with_local_latest_utterance(
        {"level3": ["法学", "财政学"], "negative_level3": ["护理学"]},
        latest_utterance="我倾向法学和财政学但护理不要",
        batch="01",
        recovery_scope="major",
    )

    assert payload == {
        "level3": ["法学", "财政学"],
        "negative_level3": ["护理学"],
    }


def test_build_select_items_dedupes_same_major_name_across_levels():
    profile = SimpleNamespace(
        major=SimpleNamespace(
            level1=[],
            level2=[],
            level3=[],
            negative_level1=[],
            negative_level2=[],
            negative_level3=[],
        ),
        school=SimpleNamespace(colleges=[], negative_colleges=[]),
        city=SimpleNamespace(province=[], city=[], negative_province=[], negative_city=[]),
    )

    items, existing_items = _build_select_items(
        profile,
        {"level1": ["法学"], "level3": ["法学", "财政学"], "negative_level3": ["护理学"]},
        None,
        None,
    )

    assert existing_items == []
    assert [item["value"] for item in items] == [
        {"major_intents": {"level3": ["法学"]}},
        {"major_intents": {"level3": ["财政学"]}},
        {"major_intents": {"negative_level3": ["护理学"]}},
    ]


def test_refine_major_intents_replaces_model_overexpanded_payload_with_local_latest_utterance():
    existing = {
        "negative_level1": ["医学"],
        "negative_level3": [
            "护理学",
            "助产学",
            "口腔医学",
            "临床医学",
            "预防医学",
            "药学",
            "中药学",
            "医学检验技术",
            "医学影像技术",
            "康复治疗学",
            "中西医临床医学",
            "针灸推拿学",
            "基础医学",
        ],
    }

    refined = _refine_major_intents_with_local_latest_utterance(
        existing,
        latest_utterance="医学护理这些别碰，财会还能接受，先看看影响",
        batch="01",
        recovery_scope="major",
    )

    assert refined == {
        "negative_level1": ["医学"],
        "negative_level3": ["护理学"],
        "level3": ["会计学", "财务管理", "审计学"],
    }


@pytest.mark.asyncio
async def test_recover_major_intent_from_context_recovers_common_major_abbreviations_locally():
    from app.agent.context import RequestContext

    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="57",
            chat_history=[{"role": "user", "content": "土木别要，计科可以"}],
            batch="01",
        )
    )

    with (
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as extract_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as extract_major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as extract_negative_mock,
    ):
        major_intents, school_intents, city_intents, career_intents = await intent_state_tool_module._recover_intents_from_context(
            ctx,
            recovery_scope="major",
        )

    assert major_intents == {
        "negative_level3": ["土木工程"],
        "level3": ["计算机科学与技术"],
    }
    assert school_intents is None
    assert city_intents is None
    assert career_intents is None
    extract_polarity_mock.assert_not_awaited()
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
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as extract_polarity_mock,
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
    extract_polarity_mock.assert_not_awaited()
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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
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

    resp_payload = json.loads(resp)
    assert resp_payload["status"] == "empty"
    assert resp_payload["message"] == "ok"
    assert resp_payload["reply_strategy"] == "preview_wait_confirm"
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
        constraint_intent_type=None,
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
    save_mock.assert_not_awaited()
    payload = json.loads(payload_text)
    assert payload["intentMode"] == INTENT_MODE_CONSTRAINT
    assert payload["items"][0]["value"] == {"career_intents": {"negative": ["system_public_service"]}}


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

    assert "方向判断" in resp
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
async def test_handle_intent_select_interest_candidate_query_prefers_pending_confirmation():
    pending_payload = {
        "data": {
            "pendingConfirmation": {
                "status": "active",
                "kind": "intent_change",
                "executionPayload": {
                    "intentMode": "preference",
                    "merged": {
                        "city_intents": {"province": ["北京"]},
                    },
                },
            }
        }
    }
    legacy_cache_payload = {
        "data": {
            "planEditCache": {
                "city_intents": {"province": ["上海"]},
                "intent_mode": "preference",
            }
        }
    }

    with (
        patch("app.tools.explore_followup_tool.get_pending_confirmation", new=AsyncMock(return_value=pending_payload)),
        patch("app.tools.explore_followup_tool.get_intent_change_cache", new=AsyncMock(return_value=legacy_cache_payload)) as legacy_cache_mock,
        patch("app.tools.explore_followup_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}})),
        patch("app.tools.explore_followup_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 88}})) as query_mock,
    ):
        resp = await _render_followup(
            session_id="91",
            batch="01",
            action_type="candidate_query",
        )

    assert "88" in resp
    legacy_cache_mock.assert_not_awaited()
    assert query_mock.await_args.kwargs["province_names"] == ["北京"]


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
async def test_analyze_intent_change_existing_negative_preference_can_upgrade_to_constraint(existing_profile):
    existing_profile.city.negative_province = ["安徽"]
    existing_profile.city.negative_province_emotion = ["Strong"]
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="9",
            batch="01",
            chat_history=[{"role": "user", "content": "不去安徽"}],
            planning_summary=SimpleNamespace(constraint_state={}),
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
    assert "点击采纳后生效" in resp
    assert "排除省份：安徽" in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_hard_constraint_in_constraint_state_returns_existing(existing_profile):
    existing_profile.city.negative_province = ["安徽"]
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="9",
            batch="01",
            chat_history=[{"role": "user", "content": "不去安徽"}],
            planning_summary=SimpleNamespace(
                constraint_state={"hardConstraints": {"mustExcludeRegions": ["安徽"]}},
            ),
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
            {"negative_province": ["安徽"]},
            None,
        )

    assert "当前已记录的明确排除省份要求：安徽" in resp
    assert "点击采纳后生效" not in resp


@pytest.mark.asyncio
async def test_analyze_intent_change_existing_preference_returns_helpful_text(existing_profile):
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="10",
            batch="01",
            chat_history=[{"role": "user", "content": "想去北京"}],
            planning_summary=SimpleNamespace(constraint_state={}),
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

    assert "当前已经在报考参考" in resp
    assert "已经记下" not in resp
    assert "现在这份方案" in resp
    assert "专家优选组合" not in resp
    assert "暂时不用重复更新" not in resp
    assert "只保留这个方向" not in resp


def test_build_impact_preview_uses_plan_relation_wording_for_preference():
    text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_PREFERENCE)
    )

    assert text == ""
    assert "新进入优选" not in text
    assert "移出优选" not in text


def test_render_intent_analysis_text_uses_light_markdown_sections():
    text = render_intent_analysis_text(
        title="我整理一下这个想法。",
        impact_text="**结合当前方案给你的提醒**\n\n**还可以再看看的机会**\n- 上海建桥学院(01)-网络与新媒体",
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_PREFERENCE,
        items=[{"content": "将网络与新媒体更新为偏好方向。"}],
    )

    assert text.startswith("**点击采纳后生效**")
    assert "\n\n**影响**\n" in text
    assert "上海建桥学院(01)-网络与新媒体" in text
    assert "还可以再看看的机会" not in text
    assert "\n\n**下一步**\n" not in text


def test_render_intent_analysis_text_hides_internal_major_levels():
    text = render_intent_analysis_text(
        title="好的，我先把这次你提到的想法整理一下。",
        impact_text="这些内容现在还只是待确认。",
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_PREFERENCE,
        existing_items=[
            {"content": "当前已有参考偏好专业（level3）：会计学"},
            {"content": "当前已有参考排除专业（level2）：护理学类"},
        ],
    )

    assert "level2" not in text
    assert "level3" not in text
    assert "当前已记录的报考参考" in text
    assert "当前已记录的报考参考偏好具体专业：会计学" in text
    assert "当前已记录的报考参考排除专业类：护理学类" in text


def test_local_major_recovery_does_not_force_teacher_track_into_intent_preview():
    payload = _recover_polarity_major_intent_locally_from_latest_utterance(
        "孩子不想当老师，师范是不是都别要",
        "01",
    )

    assert payload is None


def test_major_relation_notes_from_latest_utterance_explains_named_child_under_negative_parent():
    notes = _major_relation_notes_from_latest_utterance(
        {"negative_level1": ["医学"], "negative_level3": ["护理学"]},
        "医学护理都别碰，但中医到底算不算",
        "01",
    )

    assert any("中医学属于医学门类" in note for note in notes)


def test_intent_side_effect_decision_accepts_text_confidence():
    decision = IntentSideEffectDecision.model_validate(
        {"decision": "analysis_only", "confidence": "high", "reason": "边界分析"}
    )

    assert decision.confidence == 0.9


def test_refine_major_intents_supplements_model_omitted_major_alias():
    refined = _refine_major_intents_with_local_latest_utterance(
        {"level3": ["会计学"], "negative_level3": ["土木工程"]},
        latest_utterance="会计审计还行，土木别要",
        batch="01",
        recovery_scope="major",
    )

    assert refined == {"level3": ["会计学", "审计学"], "negative_level3": ["土木工程"]}


def test_refine_major_intents_keeps_concrete_major_when_parent_was_not_explicit():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level2": ["土木类"], "negative_level3": ["土木工程"]},
        latest_utterance="我倾向会计学和审计学，但土木工程不要",
        batch="01",
    )

    assert refined == {"negative_level3": ["土木工程"]}


def test_refine_major_intents_restores_explicit_accounting_when_model_only_returned_parent():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level2": ["工商管理类"]},
        latest_utterance="不学会计",
        batch="01",
    )

    assert refined == {"negative_level3": ["会计学"]}


def test_refine_major_intents_drops_non_catalog_parent_when_explicit_children_exist():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {
            "level2": ["会计类"],
            "level3": ["会计学", "审计学"],
            "negative_level3": ["土木工程"],
        },
        latest_utterance="我倾向会计学和审计学，但土木工程不要",
        batch="01",
    )

    assert refined == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程"],
    }


def test_refine_major_intents_drops_non_catalog_level2_fragment_from_broad_alias():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {
            "negative_level2": ["土木类", "建筑"],
            "negative_level3": ["土木工程", "建筑学"],
        },
        latest_utterance="会计审计这类还行，土木建筑那种别碰",
        batch="01",
    )

    assert refined == {
        "negative_level2": ["土木类"],
        "negative_level3": ["土木工程", "建筑学"],
    }


def test_refine_major_intents_restores_explicit_economics_finance_when_model_returned_same_discipline_parent():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level2": ["经济学类"]},
        latest_utterance="不学经济与金融",
        batch="01",
    )

    assert refined == {"negative_level3": ["经济与金融"]}


def test_refine_major_intents_restores_explicit_business_administration_when_model_returned_parent():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level2": ["工商管理类"]},
        latest_utterance="不想学工商管理",
        batch="01",
    )

    assert refined == {"negative_level3": ["工商管理"]}


def test_refine_major_intents_rebuckets_catalog_category_when_model_used_wrong_level():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level3": ["工商管理类"]},
        latest_utterance="不想学工商管理类",
        batch="01",
    )

    assert refined == {"negative_level2": ["工商管理类"]}


def test_refine_major_intents_drops_inferred_discipline_from_concrete_major():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {
            "negative_level1": ["工学"],
            "negative_level2": ["土木类"],
            "negative_level3": ["土木工程"],
        },
        latest_utterance="我倾向会计学和审计学，但土木工程不要",
        batch="01",
    )

    assert refined == {"negative_level3": ["土木工程"]}


def test_refine_major_intents_drops_inferred_discipline_without_level2_child():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level1": ["工学"], "negative_level3": ["土木工程"]},
        latest_utterance="我倾向会计学和审计学，但土木工程不要",
        batch="01",
    )

    assert refined == {"negative_level3": ["土木工程"]}


def test_refine_major_intents_keeps_broad_parent_when_parent_was_explicit():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level2": ["土木类"], "negative_level3": ["土木工程"]},
        latest_utterance="土木建筑那种别碰",
        batch="01",
    )

    assert refined == {"negative_level2": ["土木类"], "negative_level3": ["土木工程"]}


def test_refine_major_intents_keeps_explicit_discipline():
    refined = intent_state_tool_module._refine_major_intents_by_explicit_mentions(
        {"negative_level1": ["工学"], "negative_level3": ["土木工程"]},
        latest_utterance="工学都不要",
        batch="01",
    )

    assert refined == {"negative_level3": ["土木工程"], "negative_level1": ["工学"]}


@pytest.mark.asyncio
async def test_analyze_intent_change_prunes_overbroad_parent_and_upgrades_existing_negative_constraint():
    profile = UserProfile(
        major=MajorIntent(
            level3=["会计学", "审计学"],
            negative_level3=["土木工程"],
        )
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="77",
            batch="01",
            chat_history=[{"role": "user", "content": "我倾向会计学和审计学，但土木工程不要"}],
            enable_intent_side_effect_arbitration=False,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(side_effect=lambda names, level, batch: names)),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={})),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_cache_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=profile)

        payload = json.loads(
            await analyze_volunteer_intent_change(
                ctx,
                major_intents={
                    "level3": ["会计学", "审计学"],
                    "negative_level1": ["工学"],
                    "negative_level2": ["土木类"],
                    "negative_level3": ["土木工程"],
                },
                recovery_scope="major",
            )
        )

    assert payload["status"] == "ready"
    assert [item["value"] for item in payload["items"]] == [
        {"major_intents": {"negative_level3": ["土木工程"]}},
    ]
    assert "会计学" in json.dumps(payload["existingItems"], ensure_ascii=False)
    assert "审计学" in json.dumps(payload["existingItems"], ensure_ascii=False)
    assert "土木工程" not in json.dumps(payload["existingItems"], ensure_ascii=False)
    assert "工学" not in json.dumps(payload, ensure_ascii=False)
    assert "土木类" not in json.dumps(payload, ensure_ascii=False)
    save_cache_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_intent_change_existing_children_do_not_create_generic_parent_pending():
    profile = UserProfile(
        major=MajorIntent(
            level3=["会计学", "审计学"],
            negative_level3=["土木工程"],
        )
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            sessionid="77",
            batch="01",
            chat_history=[{"role": "user", "content": "我倾向会计学和审计学，但土木工程不要"}],
            planning_summary=SimpleNamespace(
                constraint_state={"hardConstraints": {"mustExcludeMajors": ["土木工程"]}},
            ),
            enable_intent_side_effect_arbitration=False,
        )
    )

    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.resolve_major_names_async", new=AsyncMock(side_effect=lambda names, level, batch: names)),
        patch("app.tools.intent_state_tool._enrich_plan_relation_analysis_from_state", new=AsyncMock(return_value={})),
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()) as save_cache_mock,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.get_current_profile = AsyncMock(return_value=profile)

        payload = json.loads(
            await analyze_volunteer_intent_change(
                ctx,
                major_intents={
                    "level2": ["会计类"],
                    "negative_level3": ["土木工程"],
                },
                recovery_scope="major",
            )
        )

    assert payload["status"] == "existing_only"
    assert payload["items"] == []
    existing_text = json.dumps(payload["existingItems"], ensure_ascii=False)
    assert "会计学" in existing_text
    assert "审计学" in existing_text
    assert "土木工程" in existing_text
    assert "会计类" not in json.dumps(payload, ensure_ascii=False)
    save_cache_mock.assert_not_awaited()


def test_local_major_recovery_expands_broad_alias_for_user_facing_intent_analysis():
    payload = _recover_polarity_major_intent_locally_from_latest_utterance(
        "医学护理这些别碰，财会还能接受，先看看影响",
        "01",
    )

    assert payload == {
        "level3": ["会计学", "财务管理", "审计学"],
        "negative_level1": ["医学"],
        "negative_level3": ["护理学"],
    }


def test_render_intent_analysis_text_explains_tcm_boundary_under_medical_constraint():
    text = render_intent_analysis_text(
        title="好的，我先把这次你提到的要求整理一下。",
        impact_text="",
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_CONSTRAINT,
        items=[
            {"content": "把医学记成明确不考虑的内容。", "value": {"major_intents": {"negative_level1": ["医学"]}}},
            {"content": "把中医学类记成明确不考虑的内容。", "value": {"major_intents": {"negative_level2": ["中医学类"]}}},
        ],
    )

    assert "中医学类属于医学门类" in text
    assert "点击采纳后生效" in text


def test_render_intent_interest_text_explains_teacher_track_boundary():
    text = render_intent_analysis_text(
        title="我先帮你判断一下这个范围。",
        impact_text="",
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        intent_mode=INTENT_MODE_CONSTRAINT,
        items=[
            {"content": "把教育学类记成明确不考虑的内容。", "value": {"major_intents": {"negative_level2": ["教育学类"]}}},
        ],
    )

    assert "师范院校里的非师范专业不等于都要排除" in text
    assert "这次识别到的参考范围" in text
    assert "待确认内容" not in text


def test_render_intent_interest_text_explains_region_tradeoff_boundary():
    text = render_intent_analysis_text(
        title="你提到的这个方向，我先结合你现在的情况做个初步分析。",
        impact_text="",
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        intent_mode=INTENT_MODE_PREFERENCE,
        items=[
            {"content": "可整理成待确认偏好。", "value": {"city_intents": {"negative_province": ["广西"]}}},
            {"content": "可整理成待确认偏好。", "value": {"city_intents": {"negative_province": ["贵州"]}}},
            {"content": "可整理成待确认偏好。", "value": {"city_intents": {"negative_province": ["内蒙古"]}}},
        ],
    )

    assert "暂不优先考虑 广西、贵州、内蒙古" in text
    assert "就读体验和家庭距离顾虑" in text
    assert "保底空间可能变少" in text
    assert "不要一刀切" in text
    assert "列出来让你采纳" in text
    assert "采纳前不会生效" in text
    assert "待确认内容" not in text
    assert "当前情况" not in text


def test_render_intent_interest_text_strips_nested_impact_heading():
    text = render_intent_analysis_text(
        title="你提到的这个要求，我先结合你现在的情况做个初步分析。",
        impact_text=(
            "**先帮你看一眼**\n"
            "\n**初步判断**\n"
            "- 我先帮你看看这个要求和你现在的方案是否有冲突。"
        ),
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        intent_mode=INTENT_MODE_CONSTRAINT,
        items=[
            {"content": "把医学记成明确不考虑的内容。", "value": {"major_intents": {"negative_level1": ["医学"]}}},
            {"content": "把会计学更新为偏好方向。", "value": {"major_intents": {"level3": ["会计学"]}}},
        ],
    )

    assert text.count("**先看影响**") == 1
    assert "初步判断" not in text
    assert "先帮你看一眼" not in text
    assert "先按这个方向看影响和边界" in text
    assert "待确认内容" not in text


def test_render_intent_interest_text_prefers_structured_impact_analysis():
    text = render_intent_analysis_text(
        title="你提到的这个方向，我先结合你现在的情况做个初步分析。",
        impact_text=(
            "先看影响和边界：\n"
            "- 这轮会重点看当前方案里是否已有贴近方向，以及候选里还有哪些值得继续关注的机会。\n"
            "可以继续展开看的方向：\n"
            "- 方案外如果还有更贴近这个方向的候选机会，也会一起作为补充参考。\n"
            "如果继续了解：\n"
            "- 如果你愿意把它当成偏好，我可以继续帮你看现在的方案哪里比较贴近、哪里还能补强。"
        ),
        analysis_stage=ANALYSIS_STAGE_INTEREST,
        intent_mode=INTENT_MODE_PREFERENCE,
        items=[
            {"content": "可整理成待确认偏好。", "value": {"major_intents": {"negative_level1": ["医学"]}}},
            {"content": "可整理成待确认偏好。", "value": {"major_intents": {"negative_level3": ["护理学"]}}},
        ],
        impact_analysis={
            "currentPlanFit": ["护理学属于医学门类；如果确认排除医学，这个具体专业也会一并避开。"],
            "currentPlanConflict": [],
            "candidateOpportunity": [],
            "nextActionHints": ["如果你愿意把它当成偏好，我可以继续帮你看现在的方案哪里比较贴近。"],
        },
    )

    assert "护理学属于医学门类" in text
    assert "可以继续展开看的方向" not in text
    assert "如果继续了解" not in text
    assert "这轮会重点看当前方案里是否已有贴近方向" not in text
    assert "如果你愿意把它当成偏好" not in text


def test_render_intent_analysis_text_replaces_generic_impact_placeholder_for_confirmed_preview():
    text = render_intent_analysis_text(
        title="好的，我先把这次你提到的要求整理一下。你可以勾选想采纳的内容后点击【采纳】。",
        impact_text=(
            "**结合当前方案给你的提醒**\n\n"
            "**现在比较贴近的部分**\n"
            "- 我先帮你看看，这个要求和你现在的方案是否有冲突，以及还有没有合适的可选机会。\n\n"
            "**还可以再看看的机会**\n"
            "- 我也会顺手看看，方案外还有没有更贴近这个方向的机会。\n\n"
            "**下一步建议**\n"
            "- 下一步更适合继续看看这份方案和你的想法有多匹配，或者直接让我给你调整建议。"
        ),
        analysis_stage=ANALYSIS_STAGE_CONFIRMED,
        intent_mode=INTENT_MODE_CONSTRAINT,
        items=[
            {"content": "将工商管理类更新为偏好方向。", "value": {"major_intents": {"level2": ["工商管理类"]}}},
            {"content": "把医学记成明确不考虑的内容。", "value": {"major_intents": {"negative_level1": ["医学"]}}},
        ],
    )

    assert "点击【采纳】" not in text
    assert "我先帮你看看" not in text
    assert "我也会顺手看看" not in text
    assert "继续看看这份方案和你的想法有多匹配" not in text
    assert "这些内容只有点击采纳后才会生效" not in text
    assert "偏好专业类：工商管理类" in text


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
    assert "后续推荐、方案检查和调整" in update_text
    assert "128" not in update_text
    assert "3200" not in update_text
    assert preview_text == ""


def test_render_intent_state_update_summarizes_confirmed_major_intents():
    text = render_intent_state_update(
        IntentStateUpdateResult(
            action="apply",
            sessionId="style-3",
            messageCode="constraint_applied",
            merged={
                "major_intents": {
                    "level1": ["法学"],
                    "level3": ["法学", "财政学"],
                    "negative_level3": ["护理学"],
                }
            },
        )
    )

    assert "本次内容：偏好专业：法学、财政学；排除专业：护理学" in text
    assert "偏好专业门类：法学" not in text
    assert "需要改当前方案时，会先给你看预览" in text


def test_build_impact_preview_uses_interest_stage_summary_when_requested():
    text = _build_impact_preview_from_analysis(
        _build_plan_relation_analysis(INTENT_MODE_PREFERENCE, "interest")
    )

    assert text == ""
    assert "现在比较贴近的部分" not in text
    assert "我先帮你看看" not in text
    assert "顺手看看" not in text


def test_build_preview_title_uses_explore_wording_for_interest_stage():
    title = _build_preview_title(None, INTENT_MODE_PREFERENCE, ANALYSIS_STAGE_INTEREST)

    assert "初步分析" in title
    assert "记成你的偏好" not in title
    assert "勾选" not in title


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
        "currentPlanFit": [],
        "currentPlanConflict": [],
        "candidateOpportunity": [],
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


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_explains_zero_current_fit_and_sprint_only_region_supply():
    base_analysis = _build_plan_relation_analysis(INTENT_MODE_PREFERENCE)
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "ordered-1", "schoolName": "浙江工商大学", "majorName": "法学", "provinceName": "浙江", "tier": "冲"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": f"nanjing-{idx}",
                        "schoolName": f"南京示例学院{idx}",
                        "majorName": "法学",
                        "provinceName": "江苏",
                        "cityName": "南京",
                        "tier": "冲",
                    }
                    for idx in range(1, 4)
                ]
                + [
                    {
                        "volunteerId": "ordered-1",
                        "schoolName": "浙江工商大学",
                        "majorName": "法学",
                        "provinceName": "浙江",
                        "tier": "冲",
                    }
                ]
            },
        }
    }

    with patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "128",
            base_analysis,
            intent_mode=INTENT_MODE_PREFERENCE,
            major_intents=None,
            school_intents=None,
            city_intents={"city": ["南京"]},
        )

    assert "暂时没有直接贴近 南京 的志愿" in analysis["currentPlanFit"][0]
    assert "大约还有 3 个，分布是 冲3" in "\n".join(analysis["candidateOpportunity"])
    assert "不能解决稳/保缺口" in "\n".join(analysis["candidateOpportunity"])


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_explains_negative_region_has_no_current_or_candidate_hit():
    base_analysis = _build_plan_relation_analysis(INTENT_MODE_CONSTRAINT)
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "ordered-1", "schoolName": "浙江工商大学", "majorName": "法学", "provinceName": "浙江", "tier": "冲"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {"volunteerId": "candidate-1", "schoolName": "南京示例学院", "majorName": "法学", "provinceName": "江苏", "cityName": "南京", "tier": "冲"},
                ]
            },
        }
    }

    with patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "128",
            base_analysis,
            intent_mode=INTENT_MODE_CONSTRAINT,
            major_intents=None,
            school_intents=None,
            city_intents={"negative_province": ["内蒙古"]},
        )

    assert "暂时没有直接命中 内蒙古 的志愿" in analysis["currentPlanConflict"][0]
    assert "候选里也暂时没有直接命中 内蒙古" in "\n".join(analysis["candidateOpportunity"])


@pytest.mark.asyncio
async def test_enrich_plan_relation_analysis_drops_generic_placeholders_when_negative_region_has_current_hit():
    base_analysis = _build_plan_relation_analysis(INTENT_MODE_CONSTRAINT)
    planning_state = {
        "data": {
            "orderedPlanState": {
                "items": [
                    {"volunteerId": "tj-1"},
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "tj-1",
                        "schoolName": "天津师范大学",
                        "majorName": "英语",
                        "provinceName": "天津",
                        "tier": "冲",
                    }
                ]
            },
        }
    }

    with patch("app.tools.intent_relation_tool.get_planning_state", new=AsyncMock(return_value=planning_state)):
        analysis = await _enrich_plan_relation_analysis_from_state(
            "128",
            base_analysis,
            intent_mode=INTENT_MODE_CONSTRAINT,
            major_intents=None,
            school_intents=None,
            city_intents={"negative_province": ["天津"]},
        )

    text = "\n".join(
        analysis.get("currentPlanFit", [])
        + analysis.get("currentPlanConflict", [])
        + analysis.get("candidateOpportunity", [])
    )
    assert "天津师范大学" in text
    assert "这轮会重点看" not in text
    assert "方案外如果还有" not in text


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
    assert payload["items"][0]["value"] == {"major_intents": {"level3": ["跨境电子商务"]}}
    save_mock.assert_not_awaited()
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
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level3": ["审计学"]}}
    save_mock.assert_not_awaited()
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
    assert payload["items"][0]["value"] == {"major_intents": {"negative_level3": ["会计学"]}}
    save_mock.assert_not_awaited()
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

    assert text == ""
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

    async def _assert_single_turn_city_polarity(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps(
            {
                "positive": {"province": [], "city": [], "area": []},
                "negative": {"province": ["北京"], "city": []},
            },
            ensure_ascii=False,
        )

    async def _assert_single_turn_major_polarity(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps(
            {
                "positive": {"level1": [], "level2": [], "level3": []},
                "negative": {"level1": [], "level2": [], "level3": []},
            },
            ensure_ascii=False,
        )

    async def _assert_single_turn_school(recovery_ctx):
        assert recovery_ctx.deps.chat_history == [{"role": "user", "content": "不去北京"}]
        return json.dumps({"colleges": [], "negative_colleges": []}, ensure_ascii=False)

    with (
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", side_effect=_assert_single_turn_city_polarity),
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", side_effect=_assert_single_turn_major_polarity),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", side_effect=_assert_single_turn_school),
    ):
        major, school, city, career = await _recover_intents_from_context(ctx)

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
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
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock(return_value=json.dumps({"positive": {"province": [], "city": [], "area": []}, "negative": {"province": [], "city": []}}, ensure_ascii=False))),
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock(return_value=json.dumps({"positive": {"level1": [], "level2": [], "level3": []}, "negative": {"level1": [], "level2": [], "level3": []}}, ensure_ascii=False))),
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
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="career_preference")

    city_polarity_mock.assert_not_awaited()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_polarity_mock.assert_not_awaited()
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
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="school")

    school_mock.assert_awaited_once()
    city_polarity_mock.assert_not_awaited()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_polarity_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school == {"colleges": ["北京联合大学"]}
    assert city is None
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_school_scope_redirects_region_like_school_value():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "仅保留江苏的学校"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock(return_value=json.dumps({"colleges": ["江苏"], "negative_colleges": []}, ensure_ascii=False))) as school_mock,
        patch(
            "app.tools.city_intent_tool.extract_city_intents_with_polarity",
            new=AsyncMock(
                return_value=json.dumps(
                    {
                        "positive": {"province": ["江苏"], "city": [], "area": []},
                        "negative": {"province": [], "city": []},
                    },
                    ensure_ascii=False,
                )
            ),
        ) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="school")

    school_mock.assert_awaited_once()
    city_polarity_mock.assert_not_awaited()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_polarity_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school is None
    assert city == {"province": ["江苏"]}
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
        patch(
            "app.tools.major_intent_tool.extract_major_intents_with_polarity",
            new=AsyncMock(
                return_value=json.dumps(
                    {
                        "positive": {"level1": [], "level2": ["计算机类"], "level3": []},
                        "negative": {"level1": [], "level2": [], "level3": []},
                    },
                    ensure_ascii=False,
                )
            ),
        ) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="major")

    major_polarity_mock.assert_awaited_once()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    city_polarity_mock.assert_not_awaited()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major == {"level2": ["计算机类"]}
    assert school is None
    assert city is None
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_major_scope_falls_back_when_combined_extractor_fails():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "法学可以，护理不要"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.intent_state_tool._recover_major_intent_from_recent_context", new=AsyncMock(return_value=None)),
        patch("app.tools.intent_state_tool._recover_major_intent_locally_from_latest_utterance", new=AsyncMock(return_value=None)),
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock(side_effect=ValueError("bad json"))) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": ["法学类"], "level3": []}, ensure_ascii=False))) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock(return_value=json.dumps({"level1": [], "level2": ["护理学类"], "level3": []}, ensure_ascii=False))) as negative_major_mock,
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="major")

    major_polarity_mock.assert_awaited_once()
    major_mock.assert_awaited_once()
    negative_major_mock.assert_awaited_once()
    city_polarity_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major == {"level2": ["法学类"], "negative_level2": ["护理学类"]}
    assert school is None
    assert city is None
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_uses_recent_existing_only_payload_when_latest_turn_has_no_entities():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[
                {"role": "user", "content": "先不确认，看看这个偏好会影响当前方案吗"},
            ],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
            recent_intent_analysis={
                "status": "existing_only",
                "sessionId": "s1",
                "items": [],
                "existingItems": [
                    {
                        "content": "当前已有参考偏好具体专业：会计学",
                        "value": {"major_intents": {"level3": ["会计学"]}},
                    },
                    {
                        "content": "当前已有参考排除具体专业：土木工程",
                        "value": {"major_intents": {"negative_level3": ["土木工程"]}},
                    },
                ],
            },
        )
    )

    with (
        patch("app.tools.intent_state_tool._recover_major_intent_from_recent_context", new=AsyncMock(return_value=None)),
        patch("app.tools.intent_state_tool._recover_major_intent_locally_from_latest_utterance", new=AsyncMock(return_value=None)),
        patch(
            "app.tools.major_intent_tool.extract_major_intents_with_polarity",
            new=AsyncMock(
                return_value=json.dumps(
                    {
                        "positive": {"level1": [], "level2": [], "level3": []},
                        "negative": {"level1": [], "level2": [], "level3": []},
                    },
                    ensure_ascii=False,
                )
            ),
        ),
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="major")

    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    city_polarity_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major == {"level3": ["会计学"], "negative_level3": ["土木工程"]}
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
        patch(
            "app.tools.city_intent_tool.extract_city_intents_with_polarity",
            new=AsyncMock(
                return_value=json.dumps(
                    {
                        "positive": {"province": ["北京"], "city": [], "area": []},
                        "negative": {"province": [], "city": []},
                    },
                    ensure_ascii=False,
                )
            ),
        ) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock()) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock()) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="region")

    city_polarity_mock.assert_awaited_once()
    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    major_polarity_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school is None
    assert city == {"province": ["北京"]}
    assert career is None


@pytest.mark.asyncio
async def test_recover_intents_from_context_region_scope_falls_back_when_combined_extractor_fails():
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            userid="u1",
            sessionid="s1",
            chat_history=[{"role": "user", "content": "北京可以，上海不去"}],
            batch="01",
            score_detail=None,
            init_profile=None,
            planning_summary=None,
        )
    )

    with (
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock(side_effect=ValueError("bad json"))) as city_polarity_mock,
        patch("app.tools.city_intent_tool.extract_city_intent", new=AsyncMock(return_value=json.dumps({"province": ["北京"], "city": [], "area": []}, ensure_ascii=False))) as city_mock,
        patch("app.tools.city_intent_tool.extract_negative_city_intent", new=AsyncMock(return_value=json.dumps({"province": ["上海"], "city": []}, ensure_ascii=False))) as negative_city_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
        patch("app.tools.career_intent_tool.extract_career_intent", new=AsyncMock()) as career_mock,
    ):
        major, school, city, career = await _recover_intents_from_context(ctx, recovery_scope="region")

    city_polarity_mock.assert_awaited_once()
    city_mock.assert_awaited_once()
    negative_city_mock.assert_awaited_once()
    major_polarity_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    career_mock.assert_not_awaited()
    assert major is None
    assert school is None
    assert city == {"province": ["北京"], "negative_province": ["上海"]}
    assert career is None


@pytest.mark.asyncio
async def test_handle_intent_select_constraint_applies_without_candidate_filters_action():
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
        patch("app.tools.intent_state_tool.update_planning_constraint_state", new=AsyncMock(return_value={"code": 0})) as constraint_state_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 128}})) as query_mock,
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = (await _apply_selected("7", "01", selected_data))["message"]

    assert "已采纳" in resp
    assert "排除地域：上海" in resp
    assert "128" not in resp
    assert "候选大约" not in resp
    stale_mock.assert_awaited_once_with(7, INTENT_MODE_CONSTRAINT)
    constraint_state_mock.assert_awaited_once_with(
        "7",
        intent_mode=INTENT_MODE_CONSTRAINT,
        major_preferences=None,
        school_preferences=None,
        region_preferences={"positive": [], "negative": ["上海"]},
    )
    query_mock.assert_awaited_once()
    assert query_mock.await_args.kwargs["sort_field"] == "finalScore"


@pytest.mark.asyncio
async def test_apply_constraint_intents_marks_stale_without_candidate_filtering():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.update_planning_constraint_state", new=AsyncMock(return_value={"code": 0})) as constraint_state_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"total": 64}})) as query_mock,
        patch("app.tools.intent_state_tool.get_planning_state", new=AsyncMock(return_value={"data": {"candidatePoolState": {"summary": {"total": 3200}}}})) as state_mock,
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

    stale_mock.assert_awaited_once_with(12, INTENT_MODE_CONSTRAINT)
    constraint_state_mock.assert_awaited_once_with(
        "12",
        intent_mode=INTENT_MODE_CONSTRAINT,
        major_preferences=None,
        school_preferences=None,
        region_preferences={"positive": [], "negative": ["北京"]},
    )
    query_mock.assert_awaited_once()
    assert query_mock.await_args.kwargs["sort_field"] == "finalScore"
    state_mock.assert_not_awaited()
    assert resp.filteredTotal is None
    assert resp.baseTotal is None
    assert resp.candidateFilters is None
    assert "专家优选组合" not in resp.message
    assert "不符合这条条件的志愿" in resp.message


@pytest.mark.asyncio
async def test_apply_mixed_constraint_intents_syncs_positive_soft_and_negative_hard():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.update_planning_constraint_state", new=AsyncMock(return_value={"code": 0})) as constraint_state_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"code": 0, "data": {"total": 1}})),
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = await _apply_intents(
            session_id="14",
            batch="01",
            merged={
                "major_intents": {
                    "level3": ["会计学", "审计学"],
                    "negative_level3": ["土木工程"],
                }
            },
            intent_mode=INTENT_MODE_CONSTRAINT,
        )

    stale_mock.assert_awaited_once_with(14, INTENT_MODE_CONSTRAINT)
    assert constraint_state_mock.await_count == 2
    first_call = constraint_state_mock.await_args_list[0]
    second_call = constraint_state_mock.await_args_list[1]
    assert first_call.args == ("14",)
    assert first_call.kwargs == {
        "intent_mode": INTENT_MODE_PREFERENCE,
        "major_preferences": {"positive": ["会计学", "审计学"], "negative": []},
        "school_preferences": None,
        "region_preferences": None,
    }
    assert second_call.args == ("14",)
    assert second_call.kwargs == {
        "intent_mode": INTENT_MODE_CONSTRAINT,
        "major_preferences": {"positive": [], "negative": ["土木工程"]},
        "school_preferences": None,
        "region_preferences": None,
    }
    assert resp.applied is True
    assert resp.intentMode == INTENT_MODE_CONSTRAINT
    assert resp.recommendationRefresh["constraintStateSynced"] is True


@pytest.mark.asyncio
async def test_apply_preference_intents_refreshes_recommendation_overlay_without_candidate_regeneration():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.update_planning_constraint_state", new=AsyncMock(return_value={"code": 0})) as constraint_state_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"code": 0, "data": {"total": 1}})) as query_mock,
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

    query_mock.assert_awaited_once()
    stale_mock.assert_awaited_once_with(13, INTENT_MODE_PREFERENCE)
    constraint_state_mock.assert_awaited_once_with(
        "13",
        intent_mode=INTENT_MODE_PREFERENCE,
        major_preferences=None,
        school_preferences=None,
        region_preferences={"positive": [], "negative": ["北京"]},
    )
    state_mock.assert_not_awaited()
    latent_mock.assert_not_awaited()
    assert resp.applied is True
    assert resp.intentMode == INTENT_MODE_PREFERENCE
    assert resp.recommendationRefresh == {
        "triggered": True,
        "success": True,
        "mode": "overlay_best_effort",
        "staleMarked": True,
        "constraintStateSynced": True,
    }
    assert "已采纳" in resp.message
    assert "后续推荐和专家优选" in resp.message
    assert "现在这份方案" in resp.message
    assert "专家优选组合" not in resp.message


@pytest.mark.asyncio
async def test_apply_preference_career_intent_updates_planning_latent_profile():
    with (
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
        patch("app.tools.intent_state_tool.save_intent_change_cache", new=AsyncMock()),
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"code": 0, "data": {"total": 1}})) as query_mock,
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

    query_mock.assert_awaited_once()
    stale_mock.assert_awaited_once_with(13, INTENT_MODE_PREFERENCE)
    state_mock.assert_awaited_once()
    latent_mock.assert_awaited_once_with(
        13,
        future_development={"careerTypes": ["读研", "体制内/考公导向"]},
    )
    assert resp.applied is True
    assert "已采纳" in resp.message
    assert "后续推荐和专家优选" in resp.message


def test_career_relation_matching_uses_each_direction_slot_not_only_public_service():
    market_item = {
        "schoolName": "北京工业大学",
        "schoolCategory": "理工",
        "majorName": "计算机科学与技术",
        "majorCategory": "计算机类",
        "majorRankTags": ["就业面较宽"],
    }
    further_study_item = {
        "schoolName": "北京交通大学",
        "schoolRankTags": ["211", "保研"],
        "majorName": "数学与应用数学",
    }
    public_service_item = {
        "schoolName": "北京师范大学",
        "schoolCategory": "师范",
        "majorName": "法学",
    }

    assert _item_matches_career_intents(market_item, {"positive": ["market_employment"]}) == (True, False)
    assert _item_matches_career_intents(further_study_item, {"positive": ["further_study"]}) == (True, False)
    assert _item_matches_career_intents(public_service_item, {"positive": ["market_employment"]}) == (False, False)
    assert _item_matches_career_intents(market_item, {"negative": ["market_employment"]}) == (False, True)


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
        patch("app.tools.city_intent_tool.extract_city_intents_with_polarity", new=AsyncMock()) as city_polarity_mock,
        patch("app.tools.major_intent_tool.extract_major_intent", new=AsyncMock()) as major_mock,
        patch("app.tools.major_intent_tool.extract_negative_major_intent", new=AsyncMock()) as negative_major_mock,
        patch("app.tools.major_intent_tool.extract_major_intents_with_polarity", new=AsyncMock()) as major_polarity_mock,
        patch("app.tools.school_intent_tool.extract_school_intent", new=AsyncMock()) as school_mock,
    ):
        resp = await _render_analysis(
            ctx,
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            confirm_enabled=False,
        )

    city_mock.assert_not_awaited()
    negative_city_mock.assert_not_awaited()
    city_polarity_mock.assert_not_awaited()
    major_mock.assert_not_awaited()
    negative_major_mock.assert_not_awaited()
    major_polarity_mock.assert_not_awaited()
    school_mock.assert_not_awaited()
    assert "还没准确整理出可调整的报考意向" in resp


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
        patch("app.tools.intent_state_tool.update_planning_constraint_state", new=AsyncMock(return_value={"code": 0})) as constraint_state_mock,
        patch("app.tools.intent_state_tool.mark_planning_intent_change_stale", new=AsyncMock(return_value={"code": 0})) as stale_mock,
        patch("app.tools.intent_state_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"code": 0, "data": {"total": 1}})) as query_mock,
        patch("app.tools.intent_state_tool.ProfileManager") as mock_pm_cls,
    ):
        mock_pm = mock_pm_cls.return_value
        mock_pm.update_city_intent = AsyncMock()
        mock_pm.update_major_intent = AsyncMock()
        mock_pm.update_school_intent = AsyncMock()

        resp = (await _apply_selected("7", "01", selected_data))["message"]

    assert isinstance(resp, str)
    assert "已采纳" in resp
    assert "后续推荐和专家优选" in resp
    stale_mock.assert_awaited_once_with(7, INTENT_MODE_PREFERENCE)
    constraint_state_mock.assert_awaited_once_with(
        "7",
        intent_mode=INTENT_MODE_PREFERENCE,
        major_preferences=None,
        school_preferences=None,
        region_preferences={"positive": [], "negative": ["上海"]},
    )
    query_mock.assert_awaited_once()


def test_only_keep_major_payload_prunes_model_generated_negative_complement():
    pruned = _prune_generated_negative_complements_for_only_keep(
        {
            "level3": ["电气工程及其自动化", "大气科学"],
            "negative_level1": ["哲学", "经济学", "工学", "医学"],
        },
        latest_utterance="只要电气和气象，其他方向都不要",
        batch="01",
    )

    assert pruned == {"level3": ["电气工程及其自动化", "大气科学"]}


def test_only_keep_major_payload_keeps_explicit_negative_scope():
    pruned = _prune_generated_negative_complements_for_only_keep(
        {
            "level1": ["医学"],
            "negative_level1": ["工学", "理学"],
        },
        latest_utterance="不考虑工科，只考虑医学类",
        batch="01",
    )

    assert pruned == {"level1": ["医学"], "negative_level1": ["工学"]}


def test_region_area_normalization_uses_extractor_polarity_not_user_phrase_rules():
    positive, negative = _normalize_region_area_polarity_payloads(
        {
            "province": ["浙江", "上海", "湖南", "湖北", "江西", "福建", "云南", "贵州", "四川", "重庆", "广东", "广西", "海南", "江苏", "安徽"],
            "city": [],
            "area": ["南方"],
        },
        {
            "province": ["黑龙江", "吉林", "辽宁", "内蒙古", "新疆", "西藏", "青海", "甘肃", "宁夏", "陕西", "山西", "山东", "河北", "北京", "天津"],
            "city": [],
            "area": ["北方"],
        },
        latest_utterance="孩子就想去南方，北方先别考虑",
    )

    assert positive == {"area": ["南方"]}
    assert negative == {"negative_area": ["北方"]}
