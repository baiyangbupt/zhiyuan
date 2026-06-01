from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, patch

from app.agent.context import RequestContext
from app.schemas.user_profile import UserProfile
from app.tools.plan_orchestration_tool import plan_next_action


def _ctx(session_id: str = "plan-1", init_profile: UserProfile | None = None) -> SimpleNamespace:
    return SimpleNamespace(deps=RequestContext(userid="u1", sessionid=session_id, init_profile=init_profile))


def _context_inputs(
    *,
    summary: str = "阶段=ordered；方案=20/30",
    target_count: int | None = None,
    draft_count: int = 20,
    ordered_count: int = 20,
    relation_lines: list[str] | None = None,
    review_issues: list[dict] | None = None,
) -> SimpleNamespace:
    inferred_target_count = target_count
    if inferred_target_count is None:
        match = __import__("re").search(r"方案=(\d+)/(\d+)", summary)
        inferred_target_count = int(match.group(2)) if match else ordered_count
    return SimpleNamespace(
        summary=summary,
        target_count=inferred_target_count,
        draft_count=draft_count,
        ordered_count=ordered_count,
        relation_lines=relation_lines or [],
        review_issues=review_issues or [],
        review_issue_summary_lines=[],
    )


def test_plan_next_action_builds_preview_for_add_units_without_confirmation():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30；偏好地域=北京",
                relation_lines=["- 当前方案里较贴近的有2个"],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把北京的两个放进去",
                action_family="add_units",
                volunteer_ids=["v1", "v2"],
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "add_units"
    assert data["requires_confirmation"] is True
    assert data["should_rerun_review"] is False
    assert "补入" in data["preview_summary"]


def test_plan_next_action_ignores_apply_stage_for_mutation_without_confirmation():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="按院校层次排序",
                action_family="sort_ordered_plan",
                current_stage="apply",
                sort_field="schoolRank",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "sort_ordered_plan"
    assert data["requires_confirmation"] is True
    assert data["should_rerun_review"] is False
    assert "院校层次" in data["preview_summary"]


def test_plan_next_action_allows_apply_stage_for_mutation_after_confirmation():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="按院校层次排序",
                action_family="sort_ordered_plan",
                current_stage="apply",
                sort_field="schoolRank",
                user_confirmed=True,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "apply"
    assert data["action_family"] == "sort_ordered_plan"
    assert data["requires_confirmation"] is True
    assert data["should_rerun_review"] is True


def test_plan_next_action_requires_add_units_selection_scope_when_no_ids():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="加几个进去",
                action_family="add_units",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["requires_confirmation"] is False
    assert data["missing_inputs"] == ["selection_scope"]


def test_plan_next_action_infers_add_units_school_major_ref_from_goal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=20/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把河南农业大学的建筑类加进来",
                action_family="add_units",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["volunteer_ids"] == ["河南农业大学的建筑类"]


def test_plan_next_action_requires_missing_inputs_for_move():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把这个往前提",
                action_family="move_unit",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert set(data["missing_inputs"]) == {"volunteer_id", "target_position"}


def test_plan_next_action_builds_preview_for_move_ordered_unit():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把第3个专业组移动到第5位",
                action_family="move_ordered_unit",
                unit_ids=["unit-3"],
                target_position=5,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "move_ordered_unit"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["unit_ids"] == ["unit-3"]
    assert data["atomic_actions"][0]["target_position"] == 5
    assert "整体移动指定专业组" in data["preview_summary"]


def test_plan_next_action_builds_preview_for_move_ordered_unit_position_ref():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=20/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把第3个专业组移动到第5位",
                action_family="move_ordered_unit",
                source_position=3,
                target_position=5,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "move_ordered_unit"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["unit_ids"] == []
    assert data["atomic_actions"][0]["source_position"] == 3
    assert data["atomic_actions"][0]["target_position"] == 5


def test_plan_next_action_requires_missing_inputs_for_move_ordered_unit():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把这个专业组往前提",
                action_family="move_ordered_unit",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert set(data["missing_inputs"]) == {"unit_ids", "target_position"}


def test_plan_next_action_does_not_coerce_major_group_move_by_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把这个专业组移动到第5位",
                action_family="move_unit",
                unit_ids=["unit-3"],
                target_position=5,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["action_family"] == "move_unit"
    assert "volunteer_id" in data["missing_inputs"]


def test_plan_next_action_does_not_coerce_major_group_remove_by_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="删除这个院校专业组",
                action_family="remove_units",
                unit_ids=["unit-3"],
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["action_family"] == "remove_units"
    assert data["missing_inputs"] == ["volunteer_ids"]


def test_plan_next_action_public_actions_do_not_expose_pin_unpin():
    action_literal = get_type_hints(plan_next_action)["action_family"]
    assert "pin_unit" not in action_literal.__args__
    assert "unpin_unit" not in action_literal.__args__


def test_plan_next_action_query_candidates_executes_as_read_only_apply():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=20/30",
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="看看北京有哪些学校",
                action_family="query_candidates",
                province_keyword="北京",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"][0]["action_type"] == "query_candidates"
    assert data["atomic_actions"][0]["filters"]["province_keyword"] == "北京"


def test_plan_next_action_query_state_executes_as_read_only_apply_by_default():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=2",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="方案有了么",
                action_family="query_state",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["should_rerun_review"] is False


def test_plan_next_action_builds_preview_for_generate_plan_without_confirmation():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=profile_ready；方案=0/30；偏好地域=北京",
                draft_count=0,
                ordered_count=0,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="直接生成一版方案",
                action_family="generate_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "generate_plan"
    assert data["requires_confirmation"] is True
    assert data["should_rerun_review"] is False
    assert "生成一版方案" in data["preview_summary"]


def test_plan_next_action_builds_preview_for_replace_units_without_confirmation():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=30/30；偏好地域=北京",
                draft_count=30,
                ordered_count=30,
                relation_lines=["- 当前方案里有2个与偏好冲突"],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把这两个换成北京的",
                action_family="replace_units",
                volunteer_ids=["old-1", "old-2"],
                province_keyword="北京",
                limit=2,
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "replace_units"
    assert data["requires_confirmation"] is True
    assert data["should_rerun_review"] is False
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["volunteer_ids"] == ["old-1", "old-2"]
    assert data["atomic_actions"][0]["filters"]["province_keyword"] == "北京"
    assert "移出指定志愿" in data["preview_summary"]


def test_plan_next_action_passes_structured_replace_source_major_names():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=30/30",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把会计审计换成新媒体",
                action_family="replace_units",
                volunteer_ids=["南宁学院第01组-会计学", "广州新华学院第01组-审计学"],
                source_major_names=["会计学", "审计学"],
                major_keyword="网络与新媒体",
                limit=5,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "replace_units"
    assert data["atomic_actions"][0]["source_major_names"] == ["会计学", "审计学"]
    assert data["atomic_actions"][0]["filters"]["major_keyword"] == "网络与新媒体"


def test_plan_next_action_coerces_broad_item_removal_issue_to_remove_units():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=3",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "high_tuition",
                        "label": "高收费",
                        "scope_kind": "item_removal",
                        "default_action_family": "remove_units",
                        "affected_unit_count": 13,
                        "affected_volunteer_count": 44,
                        "scope_fingerprint": "issue-high-1",
                    }
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="先处理高收费",
                action_family="replace_units",
                review_issue_code="high_tuition",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "remove_units"
    assert data["stage"] == "preview"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["review_issue_target"]["code"] == "high_tuition"
    assert data["atomic_actions"][0]["review_issue_target"]["scope_mode"] == "full_issue"
    assert "整批高收费项" in data["preview_summary"]


def test_plan_next_action_coerces_structural_review_issue_to_default_action():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=28/30；风险=1；提醒=2",
                draft_count=28,
                ordered_count=28,
                review_issues=[
                    {
                        "code": "count_validation",
                        "label": "数量缺口",
                        "scope_kind": "structural",
                        "default_action_family": "preview_compensation",
                        "affected_unit_count": 0,
                        "affected_volunteer_count": 0,
                        "scope_fingerprint": "issue-gap-1",
                    }
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="先处理数量不足",
                action_family="remove_units",
                review_issue_code="count_validation",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_compensation"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_coerces_filled_safety_guard_compensation_request_to_adjustment_analysis():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "safety_guard",
                        "label": "本省保底不足",
                        "scope_kind": "structural",
                        "default_action_family": "preview_compensation",
                        "affected_unit_count": 0,
                        "affected_volunteer_count": 0,
                        "scope_fingerprint": "issue-safety-1",
                    }
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="帮我补几个更稳的",
                action_family="preview_compensation",
                review_issue_code="safety_guard",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_compensation"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_patch_abstract_stability_wording_by_string():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=94/96；风险=3；提醒=2",
                target_count=96,
                draft_count=94,
                ordered_count=94,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="就按别太冒险的思路把这版调稳点，先给我看看会怎么动",
                action_family="preview_compensation",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_compensation"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_keeps_explicit_reorder_request_as_regenerate_order():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="帮我顺一下",
                action_family="regenerate_order",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "regenerate_order"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True


def test_plan_next_action_does_not_coerce_stability_wording_from_regenerate():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="按更稳的思路帮我弄一版",
                action_family="regenerate_order",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "regenerate_order"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True


def test_plan_next_action_does_not_coerce_optimize_wording_from_regenerate():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="那你直接按这个思路帮我弄一版",
                action_family="regenerate_order",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "regenerate_order"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True


def test_plan_next_action_does_not_coerce_adjustment_wording_from_generate_when_plan_exists():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="按更稳的思路帮我弄一版",
                action_family="generate_plan",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "generate_plan"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True


def test_plan_next_action_requires_replace_units_remove_and_replacement_scope():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=30/30",
                draft_count=30,
                ordered_count=30,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="换掉这几个",
                action_family="replace_units",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["requires_confirmation"] is False
    assert set(data["missing_inputs"]) == {"volunteer_ids", "replacement_scope"}


def test_plan_next_action_infers_replace_scope_from_init_profile_when_only_target_is_given():
    init_profile = UserProfile.model_validate(
        {
            "major": {
                "level2": ["计算机类", "电子信息类", "自动化类"],
            }
        }
    )
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=45/45；当前有1个偏好冲突",
                draft_count=45,
                ordered_count=45,
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(init_profile=init_profile),
                user_goal="把广西师范大学的生物科学换掉",
                action_family="replace_units",
                volunteer_ids=["广西师范大学006专业组-生物科学"],
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["missing_inputs"] == []
    assert json.loads(data["atomic_actions"][0]["filters"]["major_tags"]) == ["计算机类", "电子信息类", "自动化类"]
    assert any("默认按当前已记录的专业意向补入候选" in item for item in data["rationale"])


def test_plan_next_action_requires_existing_plan_for_review_adjustment_and_add():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=profile_ready；方案=0/50",
                draft_count=0,
                ordered_count=0,
            )
        ),
    ):
        review_result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="哪里还不合理",
                action_family="review_plan",
            )
        )
        add_result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="帮我补几个更稳的",
                action_family="add_units",
                tier="稳",
                limit=3,
            )
        )

    review_data = json.loads(review_result)
    add_data = json.loads(add_result)
    assert review_data["stage"] == "analyze"
    assert review_data["missing_inputs"] == ["existing_plan"]
    assert "先生成一版基础方案" in " ".join(review_data["rationale"])
    assert add_data["stage"] == "analyze"
    assert "existing_plan" in add_data["missing_inputs"]


def test_plan_next_action_keeps_compensation_preview_without_string_filter_inference():
    init_profile = UserProfile.model_validate(
        {
            "major": {
                "level2": ["计算机类", "电子信息类", "自动化类"],
            }
        }
    )
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
                return_value=_context_inputs(
                    summary="阶段=reviewed；方案=17/30；风险=2；提醒=3",
                    target_count=30,
                    draft_count=17,
                    ordered_count=17,
                    relation_lines=[],
                    review_issues=[
                        {
                            "code": "count_validation",
                            "label": "数量缺口",
                            "scope_kind": "structural",
                        "default_action_family": "preview_compensation",
                        "affected_unit_count": 0,
                        "affected_volunteer_count": 0,
                        "scope_fingerprint": "issue-gap-2",
                    }
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(init_profile=init_profile),
                user_goal="先给我一版真正更稳的可确认预览",
                action_family="preview_compensation",
                review_issue_code="count_validation",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_compensation"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_coerce_structural_rebalance_goal_to_replace_preview():
    init_profile = UserProfile.model_validate(
        {
            "major": {
                "level2": ["计算机类", "电子信息类", "自动化类"],
            }
        }
    )
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                target_count=30,
                draft_count=30,
                ordered_count=30,
                relation_lines=[],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(init_profile=init_profile),
                user_goal="别动总数，给我一版能把保区从 4 提到 8 以上的可确认预览",
                action_family="regenerate_order",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "regenerate_order"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True


def test_plan_next_action_does_not_coerce_structural_rebalance_when_goal_uses_keep_total_alias():
    init_profile = UserProfile.model_validate(
        {
            "major": {
                "level2": ["计算机类", "电子信息类", "自动化类"],
            }
        }
    )
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=2；提醒=3",
                target_count=30,
                draft_count=30,
                ordered_count=30,
                relation_lines=[],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(init_profile=init_profile),
                user_goal="保持总数 30 不变，把保区提到 8 以上",
                action_family="regenerate_order",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "regenerate_order"
    assert data["stage"] == "preview"
