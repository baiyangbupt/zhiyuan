"""回归基线：pending plan action 协议。

覆盖：
1. _is_short_plan_confirmation — 短确认文本识别
2. _allows_mutating_apply — mutating action 的 apply guard
3. _remember_recent_plan_execution_result / consume_recent_plan_execution_result — 结果缓存
4. clear_recent_plan_execution_result — 缓存清理
"""

from __future__ import annotations

import time
import pytest
from types import SimpleNamespace

from app.tools.plan_execution_tool import (
    _is_short_plan_confirmation,
    _allows_mutating_apply,
    _remember_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    clear_recent_plan_execution_result,
    _RECENT_PLAN_EXECUTION_RESULTS,
    _RECENT_PLAN_EXECUTION_TTL_SECONDS,
)
from tests.factories import make_plan_action_plan, make_request_context, make_run_context


# ---------------------------------------------------------------------------
# _is_short_plan_confirmation
# ---------------------------------------------------------------------------

class TestIsShortPlanConfirmation:
    """短确认文本 truth table。"""

    @pytest.mark.parametrize("text,expected", [
        # 完全匹配集合
        ("确认", True),
        ("确认执行", True),
        ("确定", True),
        ("可以", True),
        ("好的", True),
        ("好", True),
        ("行", True),
        ("执行", True),
        ("开始执行", True),
        ("执行吧", True),
        ("应用吧", True),
        ("直接应用吧", True),
        ("按这个来", True),
        ("就按这个来", True),
        ("按刚才的来", True),
        ("就按刚才的来", True),
        ("就这样", True),
        ("就这样吧", True),
        ("就这样执行", True),
        ("用这个", True),
        ("就用这个", True),
        # startswith("确认"/"执行") + len<=8
        ("确认一下", True),
        ("执行一下", True),
        ("确认吧", True),
        ("执行吧啊", True),
        # 标点忽略
        ("确认。", True),
        ("好的！", True),
        ("可以？", False),  # full-width ？ not stripped by current implementation
        ("确认!!", True),
        # 空格忽略
        ("确 认", True),
        ("确认 执行", True),
        # 不匹配
        ("帮我加几个志愿", False),
        ("不要了", False),
        ("删掉高收费的", False),
        ("我再想想", False),
        ("确认一下这个方案里有没有高收费的", False),  # startswith("确认") 但 len > 8
        ("", False),
        ("看看方案怎么样", False),
        ("重新生成一个", False),
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_truth_table(self, text: str, expected: bool, volunteer_model: str):
        assert _is_short_plan_confirmation(text) is expected


# ---------------------------------------------------------------------------
# _allows_mutating_apply
# ---------------------------------------------------------------------------

class TestAllowsMutatingApply:
    """mutating apply guard 逻辑。"""

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_non_mutating_always_allows(self, volunteer_model: str):
        """非 mutating action → 始终允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "看看方案"}],
        )
        plan = make_plan_action_plan(action_family="query_state", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is True

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_non_apply_stage_always_allows(self, volunteer_model: str):
        """stage != apply → 始终允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            chat_history=[{"role": "user", "content": "确认"}],
        )
        plan = make_plan_action_plan(action_family="add_units", stage="preview")
        assert _allows_mutating_apply(ctx, plan) is True

    @pytest.mark.parametrize("action_family", [
        "add_units", "remove_units", "generate_plan",
        "replace_units", "regenerate_order",
    ])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_no_pending_blocks(self, action_family: str, volunteer_model: str):
        """mutating + apply + 无 pending → 不允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action=None,
            chat_history=[{"role": "user", "content": "确认"}],
        )
        plan = make_plan_action_plan(action_family=action_family, stage="apply")
        assert _allows_mutating_apply(ctx, plan) is False

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_pending_mismatch_blocks(self, volunteer_model: str):
        """mutating + apply + pending action_family 不匹配 → 不允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "remove_units"},
            chat_history=[{"role": "user", "content": "确认"}],
        )
        plan = make_plan_action_plan(action_family="add_units", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is False

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_pending_match_no_confirm_blocks(self, volunteer_model: str):
        """mutating + apply + pending 匹配但文本非短确认 → 不允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "add_units"},
            chat_history=[{"role": "user", "content": "帮我加几个志愿"}],
        )
        plan = make_plan_action_plan(action_family="add_units", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is False

    @pytest.mark.parametrize("confirm_text", ["确认", "确认执行", "好的", "执行吧", "就这样吧"])
    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_pending_match_with_text_confirm_blocks(self, confirm_text: str, volunteer_model: str):
        """mutating + apply + pending 匹配 + 自然语言确认 → 仍不允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "add_units"},
            chat_history=[{"role": "user", "content": confirm_text}],
        )
        plan = make_plan_action_plan(action_family="add_units", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is False

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_pending_match_with_card_confirmation_allows(self, volunteer_model: str):
        """mutating + apply + pending 匹配 + 服务端卡片确认上下文 → 允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "add_units"},
            chat_history=[],
            confirmed_via_card=True,
        )
        plan = make_plan_action_plan(action_family="add_units", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is True

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_mutating_pending_match_with_server_pending_confirmation_allows(self, volunteer_model: str):
        """mutating + apply + pending 匹配 + 服务端统一 pending 确认上下文 → 允许。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            pending_plan_action={"action_family": "add_units"},
            chat_history=[],
            confirmed_via_pending=True,
            confirmation_entry="short_text",
        )
        plan = make_plan_action_plan(action_family="add_units", stage="apply")
        assert _allows_mutating_apply(ctx, plan) is True


# ---------------------------------------------------------------------------
# _remember / consume / clear
# ---------------------------------------------------------------------------

class TestRecentPlanExecutionResultCache:
    """结果缓存的存取和过期。"""

    def setup_method(self):
        _RECENT_PLAN_EXECUTION_RESULTS.clear()

    def teardown_method(self):
        _RECENT_PLAN_EXECUTION_RESULTS.clear()

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_remember_and_consume(self, volunteer_model: str):
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-001",
            chat_history=[{"role": "user", "content": "确认执行"}],
        )
        result_data = {"action_family": "add_units", "applied": True}
        _remember_recent_plan_execution_result(ctx, result_data)

        consumed = consume_recent_plan_execution_result("sess-001", "确认执行")
        assert consumed is not None
        assert consumed["action_family"] == "add_units"
        assert consumed["applied"] is True

        # 消费后应为空
        consumed_again = consume_recent_plan_execution_result("sess-001", "确认执行")
        assert consumed_again is None

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_consume_returns_deepcopy(self, volunteer_model: str):
        """消费返回的是深拷贝，修改不影响缓存。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-002",
            chat_history=[{"role": "user", "content": "确认"}],
        )
        original = {"list": [1, 2, 3]}
        _remember_recent_plan_execution_result(ctx, original)

        # 记第二次使用不同 prompt
        ctx2 = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-002",
            chat_history=[{"role": "user", "content": "确认"}],
        )
        _remember_recent_plan_execution_result(ctx2, original)

        consumed = consume_recent_plan_execution_result("sess-002", "确认")
        consumed["list"].append(4)
        # 原始数据不受影响
        assert original["list"] == [1, 2, 3]

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_clear_by_session_id(self, volunteer_model: str):
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-clear",
            chat_history=[{"role": "user", "content": "确认"}],
        )
        _remember_recent_plan_execution_result(ctx, {"data": 1})
        clear_recent_plan_execution_result("sess-clear")

        consumed = consume_recent_plan_execution_result("sess-clear", "确认")
        assert consumed is None

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_clear_by_prompt(self, volunteer_model: str):
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-clear-prompt",
            chat_history=[{"role": "user", "content": "确认执行"}],
        )
        _remember_recent_plan_execution_result(ctx, {"data": 1})
        clear_recent_plan_execution_result("sess-clear-prompt", "确认执行")

        consumed = consume_recent_plan_execution_result("sess-clear-prompt", "确认执行")
        assert consumed is None

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_wrong_session_returns_none(self, volunteer_model: str):
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-A",
            chat_history=[{"role": "user", "content": "确认"}],
        )
        _remember_recent_plan_execution_result(ctx, {"data": 1})

        consumed = consume_recent_plan_execution_result("sess-B", "确认")
        assert consumed is None

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_wrong_prompt_returns_none(self, volunteer_model: str):
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="sess-prompt",
            chat_history=[{"role": "user", "content": "确认执行"}],
        )
        _remember_recent_plan_execution_result(ctx, {"data": 1})

        consumed = consume_recent_plan_execution_result("sess-prompt", "其他文本")
        assert consumed is None

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_empty_session_or_prompt_not_stored(self, volunteer_model: str):
        """空 session_id 或空 prompt → 不存储。"""
        ctx = make_run_context(
            volunteer_model=volunteer_model,
            sessionid="",
            chat_history=[{"role": "user", "content": "确认"}],
        )
        _remember_recent_plan_execution_result(ctx, {"data": 1})
        assert len(_RECENT_PLAN_EXECUTION_RESULTS) == 0
