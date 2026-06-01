"""回归基线：plan action 不再通过 user_goal 文本做二次归一化。

历史版本的 `_normalize_adjustment_action_family` 会根据中文关键词把
generate/regenerate/compensation 等动作改写成 analyze/add/replace。
3.0.3 起这类决策必须由结构化 IntentFrame 或显式工具参数完成；
该函数仅作为旧 import 兼容 shim。
"""

from __future__ import annotations

import pytest

from app.tools.plan_orchestration_tool import _normalize_adjustment_action_family
from tests.factories import make_plan_context_inputs


HAS_PLAN = make_plan_context_inputs(draft_count=30, ordered_count=30, target_count=30)


@pytest.mark.parametrize(
    "action_family,user_goal",
    [
        ("generate_plan", "怎么优化当前方案"),
        ("generate_plan", "更稳一点"),
        ("preview_compensation", "补几个更稳的"),
        ("preview_compensation", "先给我一版"),
        ("regenerate_order", "保持总数不变，把保区提上来"),
        ("regenerate_order", "怎么优化方案"),
        ("regenerate_order", "重新排一下"),
        ("remove_units", "删掉高收费"),
        ("replace_units", "把高收费换成正常收费"),
        ("sort_ordered_plan", "按院校层次排"),
    ],
)
@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_normalization_shim_passthrough(action_family: str, user_goal: str, volunteer_model: str):
    assert _normalize_adjustment_action_family(action_family, user_goal, HAS_PLAN) == action_family


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_normalization_shim_strips_action_family(volunteer_model: str):
    assert _normalize_adjustment_action_family("  query_state  ", "更稳一点", HAS_PLAN) == "query_state"


@pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
def test_normalization_shim_keeps_empty_action_family(volunteer_model: str):
    assert _normalize_adjustment_action_family("", "更稳一点", HAS_PLAN) == ""
