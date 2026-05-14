"""指令模块化测试。

验证 app/agent/instructions/ 各模块的输出正确性。
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from app.agent.context import RequestContext, ScoreDetail, PlanningSummary
from app.agent.instructions.identity import build_identity
from app.agent.instructions.planning_context import build_planning_context
from app.agent.instructions.pending_context import build_pending_context
from app.agent.instructions.style_rules import build_style_rules
from app.agent.instructions.tool_dispatch_rules import build_tool_dispatch_rules
from app.agent.instructions.assembler import build_instructions


def _make_deps(
    *,
    score: bool = False,
    profile: bool = False,
    planning: bool = False,
    pending: dict | None = None,
    history: list | None = None,
) -> RequestContext:
    """构造测试用 RequestContext。"""
    score_detail = None
    if score:
        score_detail = ScoreDetail(
            province="北京",
            total_score=650,
            subject_list=["物理", "化学", "生物"],
            sex="男",
        )

    init_profile = None
    if profile:
        init_profile = MagicMock()
        init_profile.strength_subjects = ["物理", "数学"]
        init_profile.major.level2 = ["计算机科学与技术"]
        init_profile.major.negative_level2 = []
        init_profile.city.province = ["北京", "上海"]

    planning_summary = None
    if planning:
        planning_summary = PlanningSummary(
            phase="ordered",
            draft_total=50,
            ordered_total=50,
            review_risk_count=2,
            review_warn_count=3,
            risk_summaries=["高收费志愿3项", "概率倒挂1项"],
            pending_action_count=1,
            pending_action_summaries=["建议移除高收费项"],
        )

    return RequestContext(
        userid="test_user",
        sessionid="test_session",
        score_detail=score_detail,
        init_profile=init_profile,
        planning_summary=planning_summary,
        pending_plan_action=pending,
        chat_history=history,
    )


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_basic_role(self):
        deps = _make_deps()
        result = build_identity(deps)
        assert "孙成老师" in result
        assert "志愿填报" in result

    def test_with_score(self):
        deps = _make_deps(score=True)
        result = build_identity(deps)
        assert "北京" in result
        assert "650" in result
        assert "物理" in result

    def test_with_profile(self):
        deps = _make_deps(profile=True)
        result = build_identity(deps)
        assert "计算机科学与技术" in result
        assert "优势学科" in result
        assert "无需重复询问" in result


# ---------------------------------------------------------------------------
# planning_context
# ---------------------------------------------------------------------------

class TestPlanningContext:
    def test_empty_when_no_planning(self):
        deps = _make_deps()
        assert build_planning_context(deps) == ""

    def test_with_planning_state(self):
        deps = _make_deps(planning=True)
        result = build_planning_context(deps)
        assert "用户当前方案已有 50 个志愿" in result
        assert "50" in result
        assert "风险 2 项" in result
        assert "高收费" in result
        assert "待处理建议" in result


# ---------------------------------------------------------------------------
# pending_context
# ---------------------------------------------------------------------------

class TestPendingContext:
    def test_empty_when_no_pending(self):
        deps = _make_deps()
        assert build_pending_context(deps) == ""

    def test_with_legacy_pending(self):
        pending = {
            "action_family": "generate_plan",
            "user_goal": "生成方案",
            "summary": "将生成一版方案",
            "plan_payload": {"stage": "apply"},
        }
        deps = _make_deps(pending=pending)
        result = build_pending_context(deps)
        assert "generate_plan" in result
        assert "execute_plan_action" in result

    def test_with_conversation_phase_pending(self):
        """新 conversation_phase.pending 优先于旧 pending_plan_action。"""
        from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState
        deps = _make_deps(pending={"action_family": "old"})
        deps.conversation_phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                preview_summary="将补入3个志愿",
                affected_scope="涉及北京地区",
            ),
        )
        result = build_pending_context(deps)
        assert "add_units" in result
        assert "将补入3个志愿" in result
        assert "old" not in result  # 旧格式被覆盖


# ---------------------------------------------------------------------------
# style_rules
# ---------------------------------------------------------------------------

class TestStyleRules:
    def test_not_empty(self):
        result = build_style_rules()
        assert len(result) > 100
        assert "回复风格" in result


# ---------------------------------------------------------------------------
# tool_dispatch_rules
# ---------------------------------------------------------------------------

class TestToolDispatchRules:
    def test_not_empty(self):
        result = build_tool_dispatch_rules()
        assert len(result) > 200
        assert "Explore" in result
        assert "Intent" in result
        assert "Plan" in result


# ---------------------------------------------------------------------------
# assembler — full integration
# ---------------------------------------------------------------------------

class TestAssembler:
    def _make_ctx(self, deps):
        """模拟 RunContext[RequestContext]。"""
        ctx = MagicMock()
        ctx.deps = deps
        return ctx

    def test_minimal_assembly(self):
        deps = _make_deps()
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "孙成老师" in result
        assert "Explore" in result
        assert "回复风格" in result

    def test_full_assembly(self):
        pending = {
            "action_family": "remove_units",
            "user_goal": "删除高收费",
            "summary": "将删除3个志愿",
            "plan_payload": {"ids": ["v1"]},
        }
        deps = _make_deps(score=True, profile=True, planning=True, pending=pending)
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        # 所有段落都存在
        assert "650" in result
        assert "ordered" in result
        assert "remove_units" in result
        assert "Explore" in result
        assert "回复风格" in result

    def test_first_turn_guidance(self):
        deps = _make_deps(history=[])  # empty history → first turn
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "起手阶段" in result

    def test_no_first_turn_guidance(self):
        deps = _make_deps(history=[{"role": "user"}, {"role": "assistant"}])
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "起手阶段" not in result

    def test_instructions_shorter_than_old(self):
        """新指令应显著短于旧版 ~175 行。"""
        deps = _make_deps(score=True, profile=True, planning=True)
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        lines = result.split("\n")
        # 旧版大约 175 行，新版目标 <120 行（考虑完整注入场景）
        assert len(lines) < 150
