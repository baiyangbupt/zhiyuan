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


def _proposal(data: dict) -> dict:
    proposal = data.get("composite_proposal")
    assert isinstance(proposal, dict)
    return proposal


def _proposal_goal(data: dict) -> dict:
    goal = _proposal(data).get("goal")
    assert isinstance(goal, dict)
    return goal


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


def test_plan_next_action_preserves_structured_school_rank_sort_field():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="按院校层次给当前方案排序",
                action_family="sort_ordered_plan",
                sort_field="schoolRank",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "sort_ordered_plan"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["filters"]["sort_field"] == "schoolRank"
    assert "院校层次" in data["preview_summary"]


def test_plan_next_action_requires_sort_field_for_sort_ordered_plan():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把北京的志愿往前挪一些可以吗",
                action_family="sort_ordered_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["requires_confirmation"] is False
    assert "sort_field" in data["missing_inputs"]
    assert data["atomic_actions"][0]["filters"].get("sort_field") is None


def test_plan_next_action_does_not_infer_sort_field_from_goal_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="这版按推荐系数重新排一下，先给我看会怎么动",
                action_family="sort_ordered_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["requires_confirmation"] is False
    assert "sort_field" in data["missing_inputs"]
    assert data["atomic_actions"][0]["filters"].get("sort_field") is None


def test_plan_next_action_downgrades_scoped_sort_to_query_ordered():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把北京的志愿往前挪一些可以吗",
                action_family="sort_ordered_plan",
                sort_field="finalScore",
                province_keyword="北京",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "apply"
    assert data["action_family"] == "query_ordered"
    assert data["requires_confirmation"] is False
    assert not data["should_rerun_review"]
    assert data["atomic_actions"][0]["filters"]["province_keyword"] == "北京"
    assert any("局部筛选范围" in line for line in data["rationale"])


def test_plan_next_action_supports_query_ordered_for_scoped_move_without_position():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把北京的志愿往前挪一些可以吗",
                action_family="query_ordered",
                province_keyword="北京",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "apply"
    assert data["action_family"] == "query_ordered"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"][0]["filters"]["province_keyword"] == "北京"
    assert data["should_rerun_review"] is False


def test_plan_next_action_exclude_program_type_builds_executable_remove_scope():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=48/48")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="中外合作的都排除掉，当前方案里有的话先移出去",
                action_family="remove_units",
                current_stage="preview",
                plan_goal_type="exclude_scope",
                plan_goal_confidence="high",
                goal_negative_scopes=[
                    {"entity_type": "program_type", "values": ["中外合作办学"]}
                ],
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "remove_units"
    assert data["missing_inputs"] == []
    assert data["requires_confirmation"] is True
    assert data["atomic_actions"][0]["filters"]["program_types"] == ["中外合作办学"]
    goal = _proposal_goal(data)
    assert goal["goal_type"] == "exclude_scope"
    assert goal["negative_scopes"] == [{"entity_type": "program_type", "values": ["中外合作办学"]}]


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


def test_plan_next_action_hydrates_add_units_school_major_ref_from_goal_entities():
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
    assert data["atomic_actions"][0]["volunteer_ids"] == []
    assert data["atomic_actions"][0]["filters"]["school_keyword"] == "河南农业大学"
    assert data["atomic_actions"][0]["filters"]["major_keyword"] == "建筑类"
    assert "河南农业大学的建筑类" in data["preview_summary"]
    assert any("河南农业大学" in line and "建筑类" in line for line in data["rationale"])


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


def test_plan_next_action_requires_structured_ordered_position_pair_when_args_missing():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=20/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="具体一点，先把第8个志愿移到第12位，只给我预览",
                action_family="move_ordered_unit",
            )
        )

    data = json.loads(result)
    assert data["stage"] == "analyze"
    assert data["action_family"] == "move_ordered_unit"
    assert set(data["missing_inputs"]) == {"unit_ids", "target_position"}
    assert data["atomic_actions"][0]["source_position"] is None
    assert data["atomic_actions"][0]["target_position"] is None


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


def test_plan_next_action_coerces_structured_unit_move_to_ordered_unit():
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
    assert data["stage"] == "preview"
    assert data["action_family"] == "move_ordered_unit"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["unit_ids"] == ["unit-3"]
    assert data["atomic_actions"][0]["target_position"] == 5


def test_plan_next_action_coerces_structured_position_move_to_ordered_unit():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=20/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把第5个挪到第2个看看影响",
                action_family="move_unit",
                source_position=5,
                target_position=2,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "move_ordered_unit"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["source_position"] == 5
    assert data["atomic_actions"][0]["target_position"] == 2


def test_plan_next_action_coerces_structured_unit_remove_to_ordered_unit():
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
    assert data["stage"] == "preview"
    assert data["action_family"] == "remove_ordered_unit"
    assert data["missing_inputs"] == []
    assert data["atomic_actions"][0]["unit_ids"] == ["unit-3"]


def test_plan_next_action_builds_range_remove_ordered_unit_from_structured_scope():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=45/45")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把第40位之后的几个保删掉",
                action_family="remove_ordered_unit",
                source_position=40,
                position_scope="after",
                tier="保",
                limit=3,
            )
        )

    data = json.loads(result)
    assert data["stage"] == "preview"
    assert data["action_family"] == "remove_ordered_unit"
    assert data["missing_inputs"] == []
    action = data["atomic_actions"][0]
    assert action["source_position"] == 40
    assert action["position_scope"] == "after"
    assert action["filters"]["tier"] == "保"
    assert action["filters"]["limit"] == "3"


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


def test_plan_next_action_does_not_infer_plan_goal_from_user_goal_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留临床医学，其他都不要",
                action_family="replace_units",
                major_keyword="临床医学",
                tier="稳",
            )
        )

    data = json.loads(result)
    assert "goal" not in data
    assert "intent_updates" not in data
    assert "plan_actions" not in data
    assert data["composite_proposal"] is None
    assert data["action_family"] == "replace_units"


def test_plan_next_action_outputs_only_keep_plan_goal_metadata():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留临床医学，其他都不要",
                action_family="replace_units",
                plan_goal_type="only_keep_scope",
                major_keyword="临床医学",
                tier="稳",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    assert "goal" not in data
    assert "intent_updates" not in data
    assert "plan_actions" not in data
    assert goal["goal_type"] == "only_keep_scope"
    assert goal["target_scopes"] == [
        {"entity_type": "major", "values": ["临床医学"]}
    ]
    assert proposal["intent_updates"] == [
        {
            "intentMode": "constraint",
            "constraintIntentType": "only_keep",
            "targetScopes": [{"entity_type": "major", "values": ["临床医学"]}],
        }
    ]
    assert proposal["plan_actions"] == []
    reference_sources = {item["source"] for item in proposal["decision_references"]}
    assert {"explicit_user_goal", "confirmed_intent", "system_recommendation"}.issubset(reference_sources)
    explicit_ref = next(item for item in proposal["decision_references"] if item["source"] == "explicit_user_goal")
    assert explicit_ref["dimension"] == "target_scope"
    assert explicit_ref["weight_hint"] == "hard"
    assert explicit_ref["value"] == {"entity_type": "major", "values": ["临床医学"]}
    assert proposal["requires_confirmation"] is False
    assert data["stage"] == "analyze"


def test_plan_next_action_does_not_call_backend_user_goal_proposal_preview():
    context = _context_inputs(summary="阶段=ordered；方案=30/30")
    ctx = _ctx()
    ctx.deps.planning_summary = SimpleNamespace(version=7)
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=context),
    ):
        result = asyncio.run(
            plan_next_action(
                ctx,
                user_goal="只保留临床医学，其他都不要",
                action_family="replace_units",
                plan_goal_type="only_keep_scope",
                major_keyword="临床医学",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    assert proposal["goal"]["goal_type"] == "only_keep_scope"
    assert proposal["intent_updates"][0]["constraintIntentType"] == "only_keep"
    assert "linked_fix_proposals" not in proposal
    assert not any("后端只读调整预览" in line for line in proposal["tradeoffs"])


def test_plan_next_action_resolves_structured_major_scope_alias():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留计科",
                action_family="replace_units",
                plan_goal_type="only_keep_scope",
                major_keyword="计科",
                tier="稳",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    resolution = goal["entity_resolutions"][0]
    assert resolution["raw_text"] == "计科"
    assert resolution["entity_type"] == "major"
    assert resolution["canonical_name"] == "计算机科学与技术"
    assert resolution["canonical_level"] == "level3"
    assert resolution["ambiguity"] == "none"
    assert goal["target_scopes"] == [
        {"entity_type": "major", "values": ["计算机科学与技术"]}
    ]
    assert proposal["intent_updates"][0]["targetScopes"] == [
        {"entity_type": "major", "values": ["计算机科学与技术"]}
    ]
    assert proposal["intent_updates"][0]["constraintIntentType"] == "only_keep"


def test_plan_next_action_blocks_ambiguous_major_scope_before_intent_update():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留财会",
                action_family="replace_units",
                plan_goal_type="only_keep_scope",
                major_keyword="财会",
                tier="稳",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    resolution = goal["entity_resolutions"][0]
    names = {item["canonical_name"] for item in resolution["matched_candidate_items"]}
    assert resolution["ambiguity"] == "multiple_match"
    assert {"工商管理类", "会计学", "财务管理", "审计学"}.issubset(names)
    assert goal["needs_clarification"] is True
    assert proposal["intent_updates"] == []
    assert proposal["feasibility"] == "needs_clarification"
    assert proposal["requires_confirmation"] is False
    assert any("财会" in line and "需要先确认" in line for line in proposal["impact_summary"])


def test_plan_next_action_resolves_structured_region_scope_alias():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="不要内蒙",
                action_family="remove_units",
                plan_goal_type="exclude_scope",
                province_keyword="内蒙",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    resolution = goal["entity_resolutions"][0]
    assert resolution["entity_type"] == "region"
    assert resolution["canonical_name"] == "内蒙古"
    assert resolution["canonical_level"] == "province"
    assert resolution["ambiguity"] == "none"
    assert proposal["intent_updates"][0]["negativeScopes"] == [
        {"entity_type": "region", "values": ["内蒙古"]}
    ]


def test_plan_next_action_resolves_structured_school_scope_alias():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="优先广西师大",
                action_family="query_ordered",
                plan_goal_type="prefer_scope",
                school_keyword="广西师大",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    resolution = goal["entity_resolutions"][0]
    assert resolution["entity_type"] == "school"
    assert resolution["canonical_name"] == "广西师范大学"
    assert resolution["ambiguity"] == "none"
    assert proposal["intent_updates"][0]["targetScopes"] == [
        {"entity_type": "school", "values": ["广西师范大学"]}
    ]
    assert proposal["intent_updates"][0]["intentMode"] == "preference"


def test_plan_next_action_constraint_type_maps_to_must_include_goal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="方案里必须有临床医学",
                action_family="add_units",
                constraint_intent_type="must_have",
                major_keyword="临床医学",
                tier="稳",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    assert _proposal_goal(data)["goal_type"] == "must_include_scope"
    assert proposal["intent_updates"][0]["constraintIntentType"] == "must_have"
    assert proposal["feasibility"] == "ready"
    assert proposal["requires_confirmation"] is True
    assert proposal["post_apply_validation_plan"]
    assert data["stage"] == "preview"
    assert data["action_family"] == "add_units"


def test_plan_next_action_builds_composite_add_action_for_must_include_goal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="方案里必须有计科",
                action_family="analyze_adjustment",
                constraint_intent_type="must_have",
                major_keyword="计科",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    assert goal["goal_type"] == "must_include_scope"
    assert goal["target_scopes"] == [
        {"entity_type": "major", "values": ["计算机科学与技术"]}
    ]
    assert data["atomic_actions"] == []
    assert proposal["plan_actions"][0]["action_type"] == "add_units"
    assert proposal["plan_actions"][0]["filters"]["major_keyword"] == "计算机科学与技术"
    assert proposal["plan_actions"][0]["filters"]["limit"] == "1"


def test_plan_next_action_marks_plan_goal_needing_clarification_without_intent_update():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留这些方向",
                action_family="replace_units",
                plan_goal_type="only_keep_scope",
                tier="稳",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    assert goal["goal_type"] == "only_keep_scope"
    assert goal["needs_clarification"] is True
    assert proposal["intent_updates"] == []
    assert proposal["feasibility"] == "needs_clarification"
    assert proposal["requires_confirmation"] is False
    assert any("请补充要调整的专业" in line for line in data["rationale"])


def test_plan_next_action_outputs_exclude_scope_composite_proposal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="不要江苏",
                action_family="remove_units",
                plan_goal_type="exclude_scope",
                province_keyword="江苏",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    assert goal["goal_type"] == "exclude_scope"
    assert goal["negative_scopes"] == [
        {"entity_type": "region", "values": ["江苏"]}
    ]
    assert proposal["intent_updates"][0]["negativeScopes"] == [
        {"entity_type": "region", "values": ["江苏"]}
    ]
    assert proposal["goal"]["negative_scopes"] == goal["negative_scopes"]


def test_plan_next_action_builds_composite_remove_action_for_exclude_goal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="不要内蒙",
                action_family="analyze_adjustment",
                plan_goal_type="exclude_scope",
                province_keyword="内蒙",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    goal = _proposal_goal(data)
    assert goal["negative_scopes"] == [
        {"entity_type": "region", "values": ["内蒙古"]}
    ]
    assert data["atomic_actions"] == []
    assert proposal["plan_actions"][0]["action_type"] == "remove_units"
    assert proposal["plan_actions"][0]["filters"]["province_keyword"] == "内蒙古"
    assert proposal["plan_actions"][0]["filters"]["limit"] == "5"


def test_plan_next_action_only_keep_does_not_generate_unvalidated_inverse_delete_action():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(return_value=_context_inputs(summary="阶段=ordered；方案=30/30")),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="只保留计科",
                action_family="analyze_adjustment",
                plan_goal_type="only_keep_scope",
                major_keyword="计科",
            )
        )

    data = json.loads(result)
    proposal = _proposal(data)
    assert _proposal_goal(data)["goal_type"] == "only_keep_scope"
    assert proposal["intent_updates"][0]["constraintIntentType"] == "only_keep"
    assert proposal["plan_actions"] == []
    assert any("反向范围校验" in line for line in proposal["tradeoffs"])
    assert proposal["requires_confirmation"] is False


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


def test_plan_next_action_keeps_broad_replacement_first_issue_as_review_plan():
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
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
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
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["requires_confirmation"] is False
    assert data["missing_inputs"] == []
    assert data["atomic_actions"] == []


def test_plan_next_action_respects_structured_high_tuition_remove_request():
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
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
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
                user_goal="有没有高收费风险",
                action_family="remove_units",
                review_issue_code="high_tuition",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "remove_units"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True
    assert data["atomic_actions"][0]["review_issue_target"]["code"] == "high_tuition"


def test_plan_next_action_downgrades_unscoped_high_tuition_replace_to_review():
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
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
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
                user_goal="高收费多吗",
                action_family="replace_units",
                review_issue_code="high_tuition",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_recover_missing_high_tuition_issue_from_goal_text():
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
                    },
                    {
                        "code": "probability_inversion",
                        "label": "概率倒挂",
                        "scope_kind": "structural",
                        "default_action_family": "analyze_adjustment",
                        "affected_unit_count": 2,
                        "affected_volunteer_count": 2,
                        "scope_fingerprint": "issue-inversion-1",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把太贵的那几个先去掉看看",
                action_family="review_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["requires_confirmation"] is False
    assert data["missing_inputs"] == []
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_recover_review_issue_when_model_chooses_fix_proposal_preview_without_code():
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
                user_goal="把太贵的那几个先去掉看看",
                action_family="preview_fix_proposal",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_fix_proposal"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["missing_inputs"] == []
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_recover_high_tuition_when_replace_lacks_issue_code():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=94/96；风险=3；提醒=5",
                draft_count=94,
                ordered_count=94,
                review_issues=[
                    {
                        "code": "high_tuition",
                        "label": "高收费",
                        "scope_kind": "item_removal",
                        "default_action_family": "remove_units",
                        "affected_unit_count": 30,
                        "affected_volunteer_count": 76,
                        "scope_fingerprint": "issue-high-3",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把太贵的那几个先去掉看看",
                action_family="replace_units",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "replace_units"
    assert data["stage"] == "analyze"
    assert data["requires_confirmation"] is False
    assert "volunteer_ids" in data["missing_inputs"]
    assert "replacement_scope" in data["missing_inputs"]


def test_plan_next_action_does_not_recover_registered_issue_from_goal_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=ordered；方案=30/30；尚未审查",
                draft_count=30,
                ordered_count=30,
                review_issues=[],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把太贵的那几个先去掉看看",
                action_family="review_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_recover_high_tuition_from_model_rewritten_goal():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=94/96；风险=3；提醒=5",
                draft_count=94,
                ordered_count=94,
                review_issues=[
                    {
                        "code": "ratio_distribution",
                        "label": "冲稳保配比",
                        "scope_kind": "structural",
                        "default_action_family": "analyze_adjustment",
                    },
                    {
                        "code": "high_tuition",
                        "label": "高收费",
                        "scope_kind": "item_removal",
                        "default_action_family": "remove_units",
                        "affected_unit_count": 3,
                        "affected_volunteer_count": 5,
                        "scope_fingerprint": "issue-high-2",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把当前方案里学费太高的志愿去掉",
                action_family="review_plan",
                review_issue_scope_mode="full_issue",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["atomic_actions"] == []


def test_plan_next_action_keeps_fee_question_as_review_when_user_says_do_not_change_plan():
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
                user_goal="太贵的是哪些，先别改方案",
                action_family="review_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_recover_cooperative_program_issue_from_goal_text():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=4",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "high_tuition",
                        "label": "高收费",
                        "scope_kind": "item_removal",
                        "default_action_family": "remove_units",
                        "affected_unit_count": 9,
                        "affected_volunteer_count": 20,
                        "scope_fingerprint": "issue-high-1",
                    },
                    {
                        "code": "cooperative_program",
                        "label": "中外合作",
                        "scope_kind": "item_removal",
                        "default_action_family": "remove_units",
                        "affected_unit_count": 3,
                        "affected_volunteer_count": 8,
                        "scope_fingerprint": "issue-coop-1",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="把中外合作那批先移出去看看",
                action_family="review_plan",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "review_plan"
    assert data["stage"] == "review"
    assert data["atomic_actions"] == []


def test_plan_next_action_does_not_promote_cooperative_program_text_scope_to_review_issue():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=4",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "cooperative_program",
                        "label": "中外合作",
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
                        "affected_unit_count": 3,
                        "affected_volunteer_count": 8,
                        "scope_fingerprint": "issue-coop-1",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="中外合作的都排除掉，当前方案里有的话先移出去",
                action_family="remove_units",
                source_major_names=["中外合作"],
                major_keyword="中外合作",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "remove_units"
    assert data["stage"] == "preview"
    assert data["requires_confirmation"] is True
    assert data["atomic_actions"][0]["source_major_names"] == ["中外合作"]
    assert data["atomic_actions"][0].get("review_issue_target") is None
    assert not any("不按具体专业或院校名处理" in line for line in data["rationale"])


def test_plan_next_action_does_not_promote_high_tuition_tag_to_review_issue_without_code():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=4",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "high_tuition",
                        "label": "高收费",
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
                        "affected_unit_count": 3,
                        "affected_volunteer_count": 8,
                        "scope_fingerprint": "issue-high-1",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="高收费的都移出去",
                action_family="remove_units",
                major_tags=["高收费"],
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "remove_units"
    assert data["stage"] == "preview"
    assert data["atomic_actions"][0]["filters"]["major_tags"] == '["高收费"]'
    assert data["atomic_actions"][0].get("review_issue_target") is None


def test_plan_next_action_explicit_review_issue_code_still_uses_review_scope():
    with patch(
        "app.tools.plan_orchestration_tool._collect_plan_context_inputs_model",
        new=AsyncMock(
            return_value=_context_inputs(
                summary="阶段=reviewed；方案=30/30；风险=0；提醒=4",
                draft_count=30,
                ordered_count=30,
                review_issues=[
                    {
                        "code": "cooperative_program",
                        "label": "中外合作",
                        "scope_kind": "item_replacement",
                        "default_action_family": "review_plan",
                        "affected_unit_count": 3,
                        "affected_volunteer_count": 8,
                        "scope_fingerprint": "issue-coop-1",
                    },
                ],
            )
        ),
    ):
        result = asyncio.run(
            plan_next_action(
                _ctx(),
                user_goal="处理审查里的中外合作提醒",
                action_family="remove_units",
                review_issue_code="cooperative_program",
                review_issue_scope_mode="full_issue",
                user_confirmed=False,
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "remove_units"
    assert data["stage"] == "preview"
    assert data["atomic_actions"][0]["review_issue_target"]["code"] == "cooperative_program"
    assert data["atomic_actions"][0]["review_issue_target"]["scope_mode"] == "full_issue"


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
                        "default_action_family": "preview_fix_proposal",
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
    assert data["action_family"] == "preview_fix_proposal"
    assert data["stage"] == "apply"
    assert data["requires_confirmation"] is False
    assert data["atomic_actions"] == []


def test_plan_next_action_keeps_safety_guard_fix_proposal_preview_when_plan_is_filled():
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
                        "default_action_family": "preview_fix_proposal",
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
                action_family="preview_fix_proposal",
                review_issue_code="safety_guard",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_fix_proposal"
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
                action_family="preview_fix_proposal",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_fix_proposal"
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
                        "default_action_family": "preview_fix_proposal",
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
                action_family="preview_fix_proposal",
                review_issue_code="count_validation",
            )
        )

    data = json.loads(result)
    assert data["action_family"] == "preview_fix_proposal"
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
