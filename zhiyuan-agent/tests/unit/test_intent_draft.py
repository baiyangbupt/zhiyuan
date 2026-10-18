"""Batch A1：完整意图草稿 / 待确认变更集契约。

只验证契约与归一化，不接模型、不写状态；重点是“复合要求不被丢掉”。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.gateway.intent_draft import IntentDraft, build_change_set


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "composite_requests.json"


def _load_cases() -> dict[str, dict]:
    return {item["id"]: item["draft"] for item in json.loads(FIXTURES.read_text("utf-8"))}


def _draft(case_id: str) -> IntentDraft:
    return IntentDraft.model_validate(_load_cases()[case_id])


def test_composite_add_scope_tuition_keeps_all_requirements():
    draft = _draft("composite_add_scope_tuition")

    change_set = build_change_set(draft)

    assert change_set.status == "needs_constraints_first"
    assert [op.kind for op in change_set.operations] == ["constrain", "add"]
    assert {s.scope_type for s in change_set.operations[0].scopes} == {"region", "tuition"}
    assert len(change_set.operations[1].targets) == 2
    joined = " ".join(change_set.unresolved)
    assert "risk_posture" in joined
    assert "有效期" in joined


def test_pure_add_is_ready_and_atomic():
    change_set = build_change_set(_draft("pure_add"))

    assert change_set.status == "ready"
    assert [op.kind for op in change_set.operations] == ["add"]
    assert change_set.atomic is True
    assert change_set.unresolved == []


def test_scope_only_is_ready():
    change_set = build_change_set(_draft("scope_only"))

    assert change_set.status == "ready"
    assert [op.kind for op in change_set.operations] == ["constrain"]
    assert change_set.atomic is True


def test_ambiguous_scope_goes_to_clarification_without_dropping_target():
    draft = _draft("ambiguous_scope")

    change_set = build_change_set(draft)

    assert change_set.status == "needs_clarification"
    assert change_set.operations == []
    assert change_set.unresolved == ["scope:太远指哪些地区"]
    # 目标仍在草稿里；澄清不是丢弃
    assert len(draft.targets) == 1


def test_multiple_mutations_need_negotiation_not_silent_composite():
    change_set = build_change_set(_draft("add_and_remove"))

    assert change_set.status == "needs_negotiation"
    assert {op.kind for op in change_set.operations} == {"add", "remove"}
    assert change_set.atomic is False
    assert change_set.unsupported_actions == []


def test_readonly_action_does_not_create_write_change_set():
    change_set = build_change_set(_draft("readonly_query"))

    assert change_set.status == "ready"
    assert change_set.operations == []
    assert change_set.atomic is True


def test_add_without_targets_is_clarification():
    draft = IntentDraft(
        source_turn_id="t-x",
        user_text="加几条",
        goal_family="plan_mutation",
        action="add",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_clarification"
    assert "缺少明确目标" in " ".join(change_set.unresolved)


def test_risk_posture_is_never_silently_applied():
    draft = IntentDraft(
        source_turn_id="t-y",
        user_text="稳妥点，加 A 大学计算机",
        goal_family="plan_mutation",
        action="add",
        targets=[{"school_name": "A大学", "major_name": "计算机"}],
        risk_posture="steady",
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert any("risk_posture" in item for item in change_set.unresolved)
    assert all(op.kind != "risk_posture" for op in change_set.operations)


def test_conflicting_scope_values_are_preserved_for_negotiation():
    draft = IntentDraft(
        source_turn_id="t-z",
        user_text="只看省内但又想冲北京",
        goal_family="preference",
        action="constrain",
        scopes=[
            {"scope_type": "region", "name": "省内", "strength": "only"},
            {"scope_type": "region", "name": "北京", "strength": "must"},
        ],
        validity="session_future",
    )

    change_set = build_change_set(draft)

    # 不在这里做业务冲突裁决；但两条 scope 都必须进入变更集，不能静默丢一条
    assert len(change_set.operations[0].scopes) == 2
    assert change_set.status == "ready"


def test_model_goal_aliases_are_normalized_to_plan_commands():
    draft = IntentDraft(
        source_turn_id="t-alias",
        user_text="补到 50 条",
        goal_family="plan_mutation",
        action="fill_to_count",
        count=50,
        validity="this_adjustment",
    )
    change_set = build_change_set(draft)
    assert change_set.status == "ready"
    assert [op.kind for op in change_set.operations] == ["fill"]
    assert change_set.operations[0].count == 50

    composite = IntentDraft(
        source_turn_id="t-alias-2",
        user_text="加 A，学费三万内",
        goal_family="plan_mutation",
        action="add_units",
        targets=[{"school_name": "A大学", "major_name": "计算机"}],
        scopes=[{"scope_type": "tuition", "name": "30000", "strength": "must"}],
        validity="unknown",
    )
    composite_set = build_change_set(composite)
    assert composite_set.status == "needs_constraints_first"
    assert [op.kind for op in composite_set.operations] == ["constrain", "add"]


def test_fill_with_requirements_is_not_marked_ready_atomic():
    draft = IntentDraft(
        source_turn_id="t-fill-req",
        user_text="补到 50 条，以电气为主",
        goal_family="plan_mutation",
        action="fill_to_count",
        count=50,
        requirements=[
            {"kind": "include", "domain": "major", "key": "major", "values": ["电气"], "minCount": 30}
        ],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_constraints_first"
    assert change_set.atomic is False
    assert [op.kind for op in change_set.operations] == ["constrain", "fill"]
    assert change_set.operations[0].requirements[0].min_count == 30
    assert change_set.operations[1].requirements[0].min_count == 30
    assert change_set.operations[1].count == 50


def test_ready_change_sets_are_always_atomic():
    cases = [
        IntentDraft(
            source_turn_id="t-r1", user_text="加 A",
            goal_family="plan_mutation", action="add",
            targets=[{"school_name": "A大学", "major_name": "计算机"}],
            validity="this_adjustment",
        ),
        IntentDraft(
            source_turn_id="t-r2", user_text="只看省内",
            goal_family="preference", action="constrain",
            scopes=[{"scope_type": "region", "name": "省内", "strength": "only"}],
            validity="session_future",
        ),
    ]
    for draft in cases:
        change_set = build_change_set(draft)
        assert change_set.status == "ready"
        assert change_set.atomic is True
        assert len(change_set.operations) <= 1


def test_constrain_with_additional_mutation_is_staged_not_ready():
    draft = IntentDraft(
        source_turn_id="t-constrain-remove",
        user_text="只看省内，并删掉 B",
        goal_family="plan_mutation",
        action="constrain",
        additional_mutations=["remove"],
        scopes=[{"scope_type": "region", "name": "省内", "strength": "only"}],
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_constraints_first"
    assert change_set.atomic is False
    assert [op.kind for op in change_set.operations] == ["constrain", "remove"]
    assert change_set.operations[1].targets[0].school_name == "B大学"
    assert change_set.unsupported_actions == []


def test_tuition_constraint_with_replace_fill_mechanics_is_ready_atomic():
    draft = IntentDraft(
        source_turn_id="t-tuition-mechanics",
        user_text="把本会话的学费上限设为每年6000元，超出的替换掉、补足总数",
        goal_family="plan_mutation",
        action="set_tuition_cap_and_preview",
        additional_mutations=["replace", "fill"],
        scopes=[{"scopeType": "tuition", "values": ["6000"], "strength": "must"}],
        validity="session_future",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert [op.kind for op in change_set.operations] == ["constrain"]
    assert change_set.operations[0].scopes[0].scope_type == "tuition"
    assert change_set.unsupported_actions == []


def test_replace_over_budget_action_normalizes_to_constraint():
    draft = IntentDraft(
        source_turn_id="t-over-budget",
        user_text="把学费超过6000的条目换掉，总数不变",
        goal_family="plan_mutation",
        action="replace_over_budget_keep_total",
        additional_mutations=["replace", "fill"],
        scopes=[{"scopeType": "tuition", "values": ["6000"], "strength": "must"}],
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert [op.kind for op in change_set.operations] == ["constrain"]


def test_constraint_with_named_targets_and_replace_still_needs_negotiation():
    draft = IntentDraft(
        source_turn_id="t-targeted-constraint",
        user_text="把学费上限设为6000，并把 A 换成 B",
        goal_family="plan_mutation",
        action="tuition_budget_scope",
        additional_mutations=["replace"],
        targets=[{"schoolName": "学校A", "majorName": "专业A"}],
        scopes=[{"scopeType": "tuition", "values": ["6000"], "strength": "must"}],
    )

    change_set = build_change_set(draft)

    # 带点名目标的约束 + 结构动作：不是纯约束命令能原子完成的，先约束再动作。
    assert change_set.status == "needs_constraints_first"
    assert change_set.atomic is False
    assert [op.kind for op in change_set.operations] == ["constrain", "replace"]


def test_add_units_by_scope_is_ready_atomic_with_scopes_as_filters():
    draft = IntentDraft(
        source_turn_id="t-add-scope",
        user_text="再加六条安徽的院校，学费不超过 6000",
        goal_family="plan_mutation",
        action="add_units_by_scope",
        count=6,
        scopes=[
            {"scopeType": "region", "values": ["安徽"], "strength": "must"},
            {"scopeType": "tuition", "values": ["6000"], "strength": "must"},
        ],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert [op.kind for op in change_set.operations] == ["add"]
    assert change_set.operations[0].count == 6
    assert {scope.scope_type for scope in change_set.operations[0].scopes} == {"region", "tuition"}


def test_add_units_by_scope_without_count_asks_for_clarification():
    draft = IntentDraft(
        source_turn_id="t-add-scope-no-count",
        user_text="再加一些安徽的院校",
        goal_family="plan_mutation",
        action="add_units_by_scope",
        scopes=[{"scopeType": "region", "values": ["安徽"], "strength": "must"}],
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_clarification"
    assert change_set.atomic is False
    assert "新增数量" in change_set.unresolved[0]


def test_standalone_remove_is_supported() -> None:
    draft = IntentDraft(
        source_turn_id="t-remove-standalone",
        user_text="删掉 B",
        goal_family="plan_mutation",
        action="remove",
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert change_set.unsupported_actions == []
    assert [op.kind for op in change_set.operations] == ["remove"]


def test_move_units_is_a_supported_structural_operation() -> None:
    draft = IntentDraft(
        source_turn_id="t-move",
        user_text="把 B 放到第一",
        goal_family="plan_mutation",
        action="move_units",
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert change_set.unsupported_actions == []
    assert [op.kind for op in change_set.operations] == ["move"]


@pytest.mark.parametrize("action", ["undo", "rollback"])
def test_raw_planned_action_names_do_not_fall_into_readonly_ready(action: str) -> None:
    draft = IntentDraft(
        source_turn_id=f"t-{action}",
        user_text="调整方案",
        goal_family="plan_mutation",
        action=action,
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "blocked"
    assert change_set.atomic is False
    assert change_set.operations == []
    assert change_set.unsupported_actions == [action]


def test_replace_units_is_a_supported_structural_operation() -> None:
    draft = IntentDraft(
        source_turn_id="t-replace",
        user_text="换掉 B 大学计算机",
        goal_family="plan_mutation",
        action="replace_units",
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert change_set.unsupported_actions == []
    assert [op.kind for op in change_set.operations] == ["replace"]


def test_replace_without_targets_needs_clarification() -> None:
    draft = IntentDraft(
        source_turn_id="t-replace-empty",
        user_text="换掉几条",
        goal_family="plan_mutation",
        action="replace",
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_clarification"
    assert change_set.operations == []
    assert any("换入目标" in item for item in change_set.unresolved)


def test_remove_primary_with_constraints_keeps_staged_constraint_step() -> None:
    draft = IntentDraft(
        source_turn_id="t-remove-with-constraint",
        user_text="只看省内，并删掉 B",
        goal_family="plan_mutation",
        action="remove",
        scopes=[{"scope_type": "region", "name": "省内", "strength": "only"}],
        targets=[{"school_name": "B大学", "major_name": "计算机"}],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "needs_constraints_first"
    assert change_set.atomic is False
    assert [op.kind for op in change_set.operations] == ["constrain", "remove"]
    assert change_set.unsupported_actions == []


def test_prioritize_within_tier_is_implemented_not_planned_reorder() -> None:
    draft = IntentDraft(
        source_turn_id="t-prioritize",
        user_text="同档里北京优先",
        goal_family="preference",
        action="prioritize_within_tier",
        priority_rules=[
            {"domain": "region", "key": "province", "values": ["北京"]}
        ],
        validity="this_adjustment",
    )

    change_set = build_change_set(draft)

    assert change_set.status == "ready"
    assert change_set.atomic is True
    assert [op.kind for op in change_set.operations] == ["constrain"]
    assert change_set.unsupported_actions == []
