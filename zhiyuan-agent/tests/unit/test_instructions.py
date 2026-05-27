"""指令模块化测试。

验证 app/agent/instructions/ 各模块的输出正确性。
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from app.agent.context import (
    PlanningSummary,
    RequestContext,
    ScoreDetail,
    has_pending_intent_confirmation,
    resolve_pending_confirmation,
    resolve_pending_plan_payload_text,
)
from app.agent.instructions.identity import build_identity
from app.agent.instructions.planning_context import build_planning_context
from app.agent.instructions.pending_context import build_pending_context
from app.agent.instructions.style_rules import build_style_rules
from app.agent.instructions.tool_dispatch_rules import build_tool_dispatch_rules
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.plan_query_tool import query_volunteer_plan
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

    def test_conversation_phase_without_pending_blocks_legacy_fallback(self):
        """一旦 phase 已注入，就只认 phase.pending，不再回退旧字段。"""
        from app.models.conversation_phase import ConversationPhase, PhaseState

        deps = _make_deps(pending={
            "action_family": "generate_plan",
            "summary": "旧格式待确认",
            "plan_payload": {"stage": "apply"},
        })
        deps.pending_intent_change = True
        deps.conversation_phase = ConversationPhase(state=PhaseState.PLAN_IDLE)

        assert resolve_pending_confirmation(deps) is None
        assert resolve_pending_plan_payload_text(deps) == ""
        assert not has_pending_intent_confirmation(deps)

    def test_resolve_pending_confirmation_prefers_phase(self):
        from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState

        deps = _make_deps(pending={"action_family": "old"})
        deps.conversation_phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="删除2个志愿",
                execution_payload={"stage": "apply", "action_family": "remove_units"},
            ),
        )

        pending = resolve_pending_confirmation(deps)

        assert pending is not None
        assert pending.action_family == "remove_units"
        assert json.loads(resolve_pending_plan_payload_text(deps))["action_family"] == "remove_units"

    def test_has_pending_intent_confirmation_reads_legacy_flag(self):
        deps = _make_deps()
        deps.pending_intent_change = True

        assert has_pending_intent_confirmation(deps)


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

    def test_candidate_add_refs_are_plan_mutations(self):
        result = build_tool_dispatch_rules()
        assert "add_units" in result
        assert "用户原始引用" in result
        assert "广西师大统计" in result
        assert "不要改走学校/分数线 Explore 分析" in result

    def test_school_major_move_and_remove_refs_are_plan_mutations(self):
        result = build_tool_dispatch_rules()
        assert "青岛电影学院的新闻学" in result
        assert "move_unit" in result
        assert "target_position" in result
        assert "query_volunteer_plan" in result
        assert "remove_units" in result
        assert "唯一性校验" in result

    def test_major_choice_questions_should_not_use_plan_local_lookup(self):
        result = build_tool_dispatch_rules()

        assert "财会、法学、新媒体哪个更不容易踩坑" in result
        assert "不要调用 `query_volunteer_plan`" in result
        assert "取舍判断" in result

    def test_plan_tool_docs_say_refs_do_not_need_pre_query(self):
        assert "不适合在移动/删除前作为“定位 ID”的前置步骤" in (query_volunteer_plan.__doc__ or "")
        assert "不应为了定位而先调用 query_volunteer_plan" in (plan_next_action.__doc__ or "")


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
