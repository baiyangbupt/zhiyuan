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
            "query_draft",
            "query_ordered",
            "query_candidates",
            "review_plan",
            "analyze_adjustment",
            "preview_compensation",
            "apply_compensation",
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

    def test_import_compensation_handlers(self):
        import app.handlers.compensation_handlers  # noqa: F401

    def test_import_generate_handler(self):
        import app.handlers.generate_handler  # noqa: F401

    def test_import_mutation_handlers(self):
        import app.handlers.mutation_handlers  # noqa: F401

    def test_import_shared(self):
        from app.handlers.shared import latest_user_text, summary_total, is_volunteer_id_like
        assert callable(latest_user_text)
        assert callable(summary_total)
        assert callable(is_volunteer_id_like)


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
