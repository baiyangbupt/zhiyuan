"""集成测试：结构化 ActionResolver 合同。

历史上该文件用于比较 ActionResolver 与旧
``_normalize_adjustment_action_family`` 的中文关键词改写结果。
3.0.3 起运行时不再从 ``user_goal`` 做动作归一化；同一动作必须由
IntentFrame / tool 参数中的结构化字段决定。本文件保留原文件名，
但测试目标改为验证新合同，避免旧字符串匹配重新回到主路径。
"""

from __future__ import annotations

import pytest

from app.handlers import HANDLER_REGISTRY
from app.models.intent_frame import IntentFrame, ScopeSpec, TargetSpec
from app.resolver.action_resolver import ActionResolver
from app.tools.plan_orchestration_tool import _normalize_adjustment_action_family
from tests.factories import make_plan_context_inputs


resolver = ActionResolver()

HAS_PLAN = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)
NO_PLAN = make_plan_context_inputs(draft_count=0, ordered_count=0, target_count=30)
NOT_FILLED = make_plan_context_inputs(draft_count=20, ordered_count=20, target_count=30)
FILLED = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)


def _frame(
    verb: str,
    *,
    topic: str = "general",
    task_layer: str = "plan",
    **kwargs,
) -> IntentFrame:
    target_kwargs = {}
    scope_kwargs = {}
    frame_kwargs = {}
    for key in (
        "volunteer_refs",
        "unit_refs",
        "school_names",
        "major_names",
        "region_names",
        "review_issue_code",
        "source_position",
        "position",
        "career_types",
    ):
        if key in kwargs:
            target_kwargs[key] = kwargs.pop(key)
    for key in (
        "tier",
        "province",
        "school_tags",
        "major_tags",
        "school_keyword",
        "major_keyword",
        "limit",
        "sort_field",
        "preserve_count",
        "is_review_issue_batch",
    ):
        if key in kwargs:
            scope_kwargs[key] = kwargs.pop(key)
    for key in ("is_confirmation_of_previous", "raw_utterance"):
        if key in kwargs:
            frame_kwargs[key] = kwargs.pop(key)
    return IntentFrame(
        task_layer=task_layer,
        topic=topic,
        verb=verb,
        target=TargetSpec(**target_kwargs),
        scope=ScopeSpec(**scope_kwargs),
        **frame_kwargs,
    )


@pytest.mark.parametrize(
    "action_family,user_goal",
    [
        ("generate_plan", "怎么优化当前方案"),
        ("preview_compensation", "补几个更稳的"),
        ("regenerate_order", "保持总数不变，把保区提上来"),
        ("regenerate_order", "按院校层次排"),
        ("remove_units", "删掉高收费"),
        ("replace_units", "把高收费换成正常收费"),
    ],
)
@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_legacy_normalization_import_is_passthrough(
    action_family: str,
    user_goal: str,
    volunteer_model: str,
):
    assert _normalize_adjustment_action_family(action_family, user_goal, HAS_PLAN) == action_family


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_sort_requires_structured_sort_field(volunteer_model: str):
    text_only = resolver.resolve(
        _frame("reorder", raw_utterance="按院校层次排"),
        HAS_PLAN,
    )
    assert text_only.action_family == "regenerate_order"

    structured = resolver.resolve(
        _frame("reorder", sort_field="schoolRank", raw_utterance="按院校层次排"),
        HAS_PLAN,
    )
    assert structured.action_family == "sort_ordered_plan"
    assert structured.action.sort_field == "schoolRank"
    assert structured.stage == "preview"
    assert structured.requires_confirmation is True


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_ordered_unit_move_requires_structured_source_or_unit_id(volunteer_model: str):
    text_only = resolver.resolve(
        _frame("move", raw_utterance="把第3个专业组移到第5位"),
        HAS_PLAN,
    )
    assert text_only.action_family == "move_unit"
    assert "volunteer_id" in text_only.missing_inputs
    assert "target_position" in text_only.missing_inputs

    by_position = resolver.resolve(
        _frame(
            "move",
            source_position=3,
            position=5,
            raw_utterance="把第3个专业组移到第5位",
        ),
        HAS_PLAN,
    )
    assert by_position.action_family == "move_ordered_unit"
    assert by_position.action.source_position == 3
    assert by_position.action.target_position == 5
    assert by_position.missing_inputs == []

    by_unit_id = resolver.resolve(
        _frame("move", unit_refs=["unit-3"], position=5),
        HAS_PLAN,
    )
    assert by_unit_id.action_family == "move_ordered_unit"
    assert by_unit_id.missing_inputs == []


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_ordered_unit_remove_requires_structured_source_or_unit_id(volunteer_model: str):
    text_only = resolver.resolve(
        _frame("remove", raw_utterance="删除第3个专业组"),
        HAS_PLAN,
    )
    assert text_only.action_family == "remove_units"
    assert "volunteer_ids" in text_only.missing_inputs

    by_position = resolver.resolve(
        _frame("remove", source_position=3, raw_utterance="删除第3个专业组"),
        HAS_PLAN,
    )
    assert by_position.action_family == "remove_ordered_unit"
    assert by_position.action.source_position == 3
    assert by_position.missing_inputs == []

    by_unit_id = resolver.resolve(_frame("remove", unit_refs=["unit-3"]), HAS_PLAN)
    assert by_unit_id.action_family == "remove_ordered_unit"
    assert by_unit_id.missing_inputs == []


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_review_issue_action_uses_structured_issue_code(volunteer_model: str):
    text_only = resolver.resolve(
        _frame("remove", raw_utterance="删掉高收费"),
        HAS_PLAN,
    )
    assert text_only.action_family == "remove_units"
    assert text_only.review_issue_override is False
    assert "volunteer_ids" in text_only.missing_inputs

    with_code = resolver.resolve(
        _frame("remove", review_issue_code="high_tuition", raw_utterance="删掉高收费"),
        HAS_PLAN,
    )
    assert with_code.action_family == "remove_units"
    assert with_code.missing_inputs == []
    assert with_code.action.review_issue.code == "high_tuition"

    structural = resolver.resolve(
        _frame("remove", review_issue_code="probability_inversion"),
        HAS_PLAN,
    )
    assert structural.action_family == "analyze_adjustment"
    assert structural.review_issue_override is True


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_replacement_capacity_preflight_requires_structured_preserve_count(volunteer_model: str):
    text_only = resolver.resolve(
        _frame("replace", volunteer_refs=["v1"], tier="保", raw_utterance="替换后数量别少"),
        HAS_PLAN,
    )
    assert text_only.action_family == "replace_units"
    assert text_only.action.replacement_filters.preserve_count is False

    structured = resolver.resolve(
        _frame("replace", volunteer_refs=["v1"], tier="保", preserve_count=True),
        HAS_PLAN,
    )
    assert structured.action_family == "replace_units"
    assert structured.action.replacement_filters.preserve_count is True


@pytest.mark.parametrize(
    "verb,expected_family",
    [
        ("query", "query_state"),
        ("review", "review_plan"),
        ("generate", "generate_plan"),
        ("analyze", "analyze_adjustment"),
        ("compensate", "preview_compensation"),
        ("add", "add_units"),
        ("remove", "remove_units"),
        ("move", "move_unit"),
        ("replace", "replace_units"),
        ("reorder", "regenerate_order"),
    ],
)
@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_direct_structured_verb_mapping(verb: str, expected_family: str, volunteer_model: str):
    extra = {}
    if verb == "query":
        extra["topic"] = "plan"
    if verb == "add":
        extra["tier"] = "稳"
    if verb in {"remove", "replace", "move"}:
        extra["volunteer_refs"] = ["v1"]
    if verb == "move":
        extra["position"] = 3
    if verb == "replace":
        extra["tier"] = "保"

    context = NOT_FILLED if verb == "compensate" else HAS_PLAN
    result = resolver.resolve(_frame(verb, **extra), context)
    assert result.action_family == expected_family


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_compensation_normalization_uses_structured_context_and_scope(volunteer_model: str):
    unfilled_stable = resolver.resolve(_frame("compensate", tier="保"), NOT_FILLED)
    assert unfilled_stable.action_family == "add_units"
    assert unfilled_stable.normalization_applied == "preview_compensation → add_units"

    filled = resolver.resolve(_frame("compensate"), FILLED)
    assert filled.action_family == "analyze_adjustment"
    assert filled.normalization_applied == "preview_compensation → analyze_adjustment"


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_pin_unpin_are_compatible_but_not_executable(volunteer_model: str):
    for verb, family in [("pin", "pin_unit"), ("unpin", "unpin_unit")]:
        result = resolver.resolve(_frame(verb, volunteer_refs=["v1"]), HAS_PLAN)
        assert result.action_family == family
        assert result.stage == "blocked"
        assert result.requires_confirmation is False
        assert family not in HANDLER_REGISTRY


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_plan_dependent_actions_still_require_existing_plan(volunteer_model: str):
    review = resolver.resolve(_frame("review"), NO_PLAN)
    assert review.action_family == "review_plan"
    assert "existing_plan" in review.missing_inputs
    assert review.stage == "analyze"

    generate = resolver.resolve(_frame("generate"), NO_PLAN)
    assert generate.action_family == "generate_plan"
    assert "existing_plan" not in generate.missing_inputs
    assert generate.stage == "preview"
