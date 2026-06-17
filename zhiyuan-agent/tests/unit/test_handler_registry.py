"""Handler registry 单元测试。

验证注册表机制和 handler 包结构。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.handlers import HANDLER_REGISTRY, HandlerFunc
from app.handlers.registry import register_handler
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult


class TestRegistry:
    """注册表基本行为。"""

    def test_registry_is_dict(self):
        assert isinstance(HANDLER_REGISTRY, dict)

    def test_handler_func_type_alias(self):
        """HandlerFunc 是 Callable。"""
        assert HandlerFunc is not None

    def test_register_handler_decorator(self):
        """@register_handler 正确注册函数。"""
        # 注册一个临时 handler
        @register_handler("_test_action_family")
        async def _test_handler(ctx, plan):
            return PlanExecutionResult(
                applied=True,
                action_family="_test_action_family",
                stage="apply",
            )

        assert "_test_action_family" in HANDLER_REGISTRY
        assert HANDLER_REGISTRY["_test_action_family"] is _test_handler

        # 清理
        del HANDLER_REGISTRY["_test_action_family"]

    def test_register_handler_returns_original(self):
        """decorator 返回原函数。"""

        @register_handler("_test_passthrough")
        async def my_handler(ctx, plan):
            pass

        assert my_handler.__name__ == "my_handler"
        del HANDLER_REGISTRY["_test_passthrough"]

    def test_unregistered_family_not_in_registry(self):
        """未注册的 action_family 不在 registry 中。"""
        assert "nonexistent_family" not in HANDLER_REGISTRY

    def test_handler_registry_matches_active_plan_actions(self):
        expected = {
            "query_state",
            "query_ordered",
            "query_candidates",
            "review_plan",
            "analyze_adjustment",
            "preview_fix_proposal",
            "generate_plan",
            "add_units",
            "remove_units",
            "move_unit",
            "replace_units",
            "regenerate_order",
            "sort_ordered_plan",
            "move_ordered_unit",
            "remove_ordered_unit",
        }
        assert expected.issubset(HANDLER_REGISTRY)
        assert "pin_unit" not in HANDLER_REGISTRY
        assert "unpin_unit" not in HANDLER_REGISTRY


class TestHandlerPackageImports:
    """验证 handler 子模块可正常导入。"""

    def test_import_query_handlers(self):
        import app.handlers.query_handlers  # noqa: F401

    def test_import_analysis_handlers(self):
        import app.handlers.analysis_handlers  # noqa: F401

    def test_import_fix_proposal_handlers(self):
        import app.handlers.fix_proposal_handlers  # noqa: F401

    def test_import_generate_handler(self):
        import app.handlers.generate_handler  # noqa: F401

    def test_import_mutation_handlers(self):
        import app.handlers.mutation_handlers  # noqa: F401

    def test_import_shared(self):
        from app.handlers.shared import latest_user_text, summary_total, is_volunteer_id_like
        assert callable(latest_user_text)
        assert callable(summary_total)
        assert callable(is_volunteer_id_like)


class TestAnalysisHandlerTargetFiltering:
    """Structured target strategy filtering for review/repair facts."""

    def test_filter_fix_proposals_by_target_strategy_and_recounts(self):
        from app.handlers.analysis_handlers import _filter_fix_proposal_facts_for_targets

        facts = {
            "ready_count": 1,
            "blocked_count": 2,
            "preview_only_count": 0,
            "total": 3,
            "proposals": [
                {
                    "proposal_id": "fp_sort",
                    "status": "ready",
                    "strategy": "sort_by_probability",
                    "source_check_codes": ["probability_inversion"],
                },
                {
                    "proposal_id": "fp_fee",
                    "status": "blocked",
                    "strategy": "replace_risk_items",
                    "source_check_codes": ["high_tuition", "cooperative_program"],
                },
                {
                    "proposal_id": "fp_gap",
                    "status": "blocked",
                    "strategy": "fill_probability_gap",
                    "source_check_codes": ["probability_gap"],
                },
            ],
        }

        filtered = _filter_fix_proposal_facts_for_targets(facts, ["replace_risk_items"])

        assert [item["proposal_id"] for item in filtered["proposals"]] == ["fp_fee"]
        assert filtered["ready_count"] == 0
        assert filtered["blocked_count"] == 1
        assert filtered["total"] == 1

    def test_filter_fix_proposals_prefers_target_issue_codes_over_broad_strategy(self):
        from app.handlers.analysis_handlers import _filter_fix_proposal_facts_for_targets

        facts = {
            "ready_count": 1,
            "blocked_count": 2,
            "total": 3,
            "proposals": [
                {
                    "proposal_id": "fp_gap",
                    "status": "ready",
                    "strategy": "replace_risk_items",
                    "source_check_codes": ["probability_gap"],
                },
                {
                    "proposal_id": "fp_safety",
                    "status": "blocked",
                    "strategy": "replace_risk_items",
                    "source_check_codes": ["major_group_safety_intent_alignment"],
                },
                {
                    "proposal_id": "fp_fee",
                    "status": "blocked",
                    "strategy": "replace_risk_items",
                    "source_check_codes": ["high_tuition", "cooperative_program"],
                },
            ],
        }

        filtered = _filter_fix_proposal_facts_for_targets(
            facts,
            ["replace_risk_items"],
            ["high_tuition", "cooperative_program"],
        )

        assert [item["proposal_id"] for item in filtered["proposals"]] == ["fp_fee"]
        assert filtered["ready_count"] == 0
        assert filtered["blocked_count"] == 1
        assert filtered["total"] == 1

    def test_filter_review_facts_keeps_matching_issue_examples(self):
        from app.handlers.analysis_handlers import _filter_review_facts_for_targets

        facts = {
            "issue_hit_plan_examples": [
                {"code": "probability_gap", "summary": "录取率梯度断层"},
                {"code": "high_tuition", "summary": "高收费"},
            ],
            "fix_proposals": {
                "proposals": [
                    {
                        "proposal_id": "fp_gap",
                        "status": "blocked",
                        "strategy": "fill_probability_gap",
                        "source_check_codes": ["probability_gap"],
                    },
                    {
                        "proposal_id": "fp_fee",
                        "status": "blocked",
                        "strategy": "replace_risk_items",
                        "source_check_codes": ["high_tuition"],
                    },
                ],
            },
        }

        filtered = _filter_review_facts_for_targets(facts, ["replace_risk_items"], ["high_tuition"])

        assert [item["code"] for item in filtered["issue_hit_plan_examples"]] == ["high_tuition"]
        assert [item["proposal_id"] for item in filtered["fix_proposals"]["proposals"]] == ["fp_fee"]

    def test_filter_review_facts_empty_target_does_not_fall_back_to_other_issues(self):
        from app.handlers.analysis_handlers import _filter_review_facts_for_targets

        facts = {
            "summary_text": "当前方案主要需要关注：录取率梯度断层；非意向托底",
            "main_problems": ["录取率梯度断层", "非意向托底"],
            "hit_rules": [
                {"summary": "录取率梯度断层"},
                {"summary": "非意向托底"},
            ],
            "issue_hit_plan_examples": [
                {"code": "probability_gap", "summary": "录取率梯度断层"},
                {"code": "major_group_safety_intent_alignment", "summary": "非意向托底"},
            ],
            "review_issue_hit_plan_examples": [
                {"code": "probability_gap", "summary": "录取率梯度断层"},
            ],
            "candidate_supply": {"summary": "候选池共 402 个"},
            "fix_proposals": {
                "proposals": [
                    {
                        "proposal_id": "fp_gap",
                        "status": "preview_only",
                        "strategy": "fill_probability_gap",
                        "source_check_codes": ["probability_gap"],
                    },
                    {
                        "proposal_id": "fp_safety",
                        "status": "blocked",
                        "strategy": "adjust_major_group_inner_safety",
                        "source_check_codes": ["major_group_safety_intent_alignment"],
                    },
                ],
            },
        }

        filtered = _filter_review_facts_for_targets(
            facts,
            ["replace_risk_items"],
            ["high_tuition", "cooperative_program"],
        )

        assert filtered["target_match_empty"] is True
        assert filtered["issue_hit_plan_examples"] == []
        assert filtered["review_issue_hit_plan_examples"] == []
        assert filtered["candidate_supply"] == {}
        assert filtered["main_problems"] == []
        assert filtered["fix_proposals"]["proposals"] == []

    def test_filter_review_facts_treats_matching_fix_proposal_as_target_hit(self):
        from app.handlers.analysis_handlers import _filter_review_facts_for_targets

        facts = {
            "summary_text": "当前方案暂时没有明显风险或提醒。",
            "main_problems": [],
            "hit_rules": [],
            "issue_hit_plan_examples": [],
            "candidate_supply": {"summary": "候选池共 431 个，冲120 / 稳130 / 保181"},
            "fix_proposals": {
                "proposals": [
                    {
                        "proposal_id": "fp_fee",
                        "status": "blocked",
                        "title": "处理高收费",
                        "strategy": "replace_risk_items",
                        "source_check_codes": ["high_tuition"],
                    }
                ],
            },
        }

        filtered = _filter_review_facts_for_targets(
            facts,
            ["replace_risk_items"],
            ["high_tuition"],
        )

        assert filtered.get("target_match_empty") is not True
        assert filtered["main_problems"] == ["处理高收费"]
        assert filtered["hit_rules"] == [{"summary": "处理高收费", "suggestion_types": []}]
        assert "处理高收费" in filtered["summary_text"]
        assert filtered["candidate_supply"] == facts["candidate_supply"]
        assert [item["proposal_id"] for item in filtered["fix_proposals"]["proposals"]] == ["fp_fee"]


class TestSharedUtils:
    """shared.py 工具函数。"""

    def test_latest_user_text_from_history(self):
        from app.handlers.shared import latest_user_text
        ctx = MagicMock()
        ctx.deps.chat_history = [
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "第二句"},
        ]
        assert latest_user_text(ctx) == "第二句"

    def test_latest_user_text_empty(self):
        from app.handlers.shared import latest_user_text
        ctx = MagicMock()
        ctx.deps.chat_history = []
        assert latest_user_text(ctx) == ""

    def test_summary_total(self):
        from app.handlers.shared import summary_total
        assert summary_total({"unitTotal": 50}) == 50
        assert summary_total({"total": 30}) == 30
        assert summary_total(None) == 0
        assert summary_total({}) == 0

    def test_summary_target_total(self):
        from app.handlers.shared import summary_target_total
        assert summary_target_total({"targetUnitCount": 96}) == 96
        assert summary_target_total({"targetCount": 96}) == 96
        assert summary_target_total(None) == 0

    def test_is_volunteer_id_like(self):
        from app.handlers.shared import is_volunteer_id_like
        assert is_volunteer_id_like("abc123_def.456:789-0")
        assert not is_volunteer_id_like("")
        assert not is_volunteer_id_like("包含中文")
        assert not is_volunteer_id_like("has space")
