"""ConversationPhase 模型单元测试。"""

import pytest
from pydantic import ValidationError

from app.models.conversation_phase import (
    ConversationPhase,
    PendingConfirmation,
    PhaseState,
)


# ---------------------------------------------------------------------------
# PhaseState
# ---------------------------------------------------------------------------

class TestPhaseState:
    """PhaseState 枚举基本行为。"""

    def test_values(self):
        assert PhaseState.EXPLORE.value == "explore"
        assert PhaseState.INTENT_PREVIEWING.value == "intent_previewing"
        assert PhaseState.PLAN_IDLE.value == "plan_idle"
        assert PhaseState.PLAN_PREVIEWING.value == "plan_previewing"

    def test_from_string(self):
        assert PhaseState("explore") == PhaseState.EXPLORE
        assert PhaseState("plan_idle") == PhaseState.PLAN_IDLE


# ---------------------------------------------------------------------------
# PendingConfirmation
# ---------------------------------------------------------------------------

class TestPendingConfirmation:
    """PendingConfirmation 模型。"""

    def test_plan_mutation(self):
        pc = PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            preview_summary="将添加3个北京的志愿",
            execution_payload={"action_family": "add_units", "stage": "apply"},
        )
        assert pc.kind == "plan_mutation"
        assert pc.action_family == "add_units"
        assert pc.affected_scope == ""
        assert pc.created_turn == 0

    def test_intent_change(self):
        pc = PendingConfirmation(
            kind="intent_change",
            action_family="set_preference",
            preview_summary="设置专业偏好：计算机",
            execution_payload={"majors": ["计算机"]},
            created_turn=5,
        )
        assert pc.kind == "intent_change"
        assert pc.created_turn == 5

    def test_invalid_kind(self):
        with pytest.raises(ValidationError):
            PendingConfirmation(
                kind="invalid",
                action_family="add_units",
            )

# ---------------------------------------------------------------------------
# ConversationPhase — 状态转换
# ---------------------------------------------------------------------------

class TestConversationPhaseTransitions:
    """合法和非法状态转换。"""

    # 合法转换
    @pytest.mark.parametrize("from_state,to_state", [
        (PhaseState.EXPLORE, PhaseState.EXPLORE),
        (PhaseState.EXPLORE, PhaseState.INTENT_PREVIEWING),
        (PhaseState.EXPLORE, PhaseState.PLAN_IDLE),
        (PhaseState.INTENT_PREVIEWING, PhaseState.EXPLORE),
        (PhaseState.INTENT_PREVIEWING, PhaseState.PLAN_IDLE),
        (PhaseState.INTENT_PREVIEWING, PhaseState.PLAN_PREVIEWING),
        (PhaseState.PLAN_IDLE, PhaseState.PLAN_IDLE),
        (PhaseState.PLAN_IDLE, PhaseState.PLAN_PREVIEWING),
        (PhaseState.PLAN_IDLE, PhaseState.EXPLORE),
        (PhaseState.PLAN_PREVIEWING, PhaseState.PLAN_IDLE),
        (PhaseState.PLAN_PREVIEWING, PhaseState.EXPLORE),
    ])
    def test_valid_transitions(self, from_state, to_state):
        phase = ConversationPhase(state=from_state)
        assert phase.can_transition_to(to_state)
        phase.transition_to(to_state)
        assert phase.state == to_state

    # 非法转换
    @pytest.mark.parametrize("from_state,to_state", [
        (PhaseState.EXPLORE, PhaseState.PLAN_PREVIEWING),
        (PhaseState.PLAN_IDLE, PhaseState.INTENT_PREVIEWING),
        (PhaseState.PLAN_PREVIEWING, PhaseState.PLAN_PREVIEWING),
        (PhaseState.PLAN_PREVIEWING, PhaseState.INTENT_PREVIEWING),
    ])
    def test_invalid_transitions(self, from_state, to_state):
        phase = ConversationPhase(state=from_state)
        assert not phase.can_transition_to(to_state)
        with pytest.raises(ValueError, match="非法状态转换"):
            phase.transition_to(to_state)


# ---------------------------------------------------------------------------
# ConversationPhase — Pending 管理
# ---------------------------------------------------------------------------

class TestConversationPhasePending:
    """Pending 操作管理。"""

    def test_set_pending_plan_mutation(self):
        phase = ConversationPhase(state=PhaseState.PLAN_IDLE)
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
        )
        phase.set_pending(pending)
        assert phase.state == PhaseState.PLAN_PREVIEWING
        assert phase.pending is pending

    def test_set_pending_intent_confirmation(self):
        phase = ConversationPhase(state=PhaseState.EXPLORE)
        pending = PendingConfirmation(
            kind="intent_change",
            action_family="set_preference",
        )
        phase.set_pending(pending)
        assert phase.state == PhaseState.INTENT_PREVIEWING
        assert phase.pending is pending

    def test_clear_pending_from_plan_previewing(self):
        phase = ConversationPhase(state=PhaseState.PLAN_PREVIEWING)
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="generate_plan",
        )
        phase.pending = pending

        cleared = phase.clear_pending()
        assert cleared is pending
        assert phase.pending is None
        assert phase.state == PhaseState.PLAN_IDLE

    def test_clear_pending_from_intent_previewing(self):
        phase = ConversationPhase(state=PhaseState.INTENT_PREVIEWING)
        pending = PendingConfirmation(
            kind="intent_change",
            action_family="set_constraint",
        )
        phase.pending = pending

        cleared = phase.clear_pending()
        assert cleared is pending
        assert phase.pending is None
        assert phase.state == PhaseState.EXPLORE

    def test_clear_pending_when_none(self):
        phase = ConversationPhase(state=PhaseState.EXPLORE)
        cleared = phase.clear_pending()
        assert cleared is None
        assert phase.state == PhaseState.EXPLORE

    def test_is_pending_stale_false_when_no_pending(self):
        phase = ConversationPhase()
        assert not phase.is_pending_stale(current_turn=10)

    def test_is_pending_stale_within_window(self):
        phase = ConversationPhase()
        phase.pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            created_turn=5,
        )
        # 差值 = 7 - 5 = 2, max_age=3, 不过期
        assert not phase.is_pending_stale(current_turn=7, max_age=3)

    def test_is_pending_stale_expired(self):
        phase = ConversationPhase()
        phase.pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            created_turn=5,
        )
        # 差值 = 9 - 5 = 4, max_age=3, 过期
        assert phase.is_pending_stale(current_turn=9, max_age=3)

    def test_is_pending_stale_boundary(self):
        """刚好在边界上：差值 == max_age 不过期。"""
        phase = ConversationPhase()
        phase.pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            created_turn=5,
        )
        # 差值 = 8 - 5 = 3, max_age=3, 不过期（>3 才过期）
        assert not phase.is_pending_stale(current_turn=8, max_age=3)

    def test_new_pending_overwrites_old(self):
        """新 pending 覆盖旧 pending。"""
        phase = ConversationPhase(state=PhaseState.PLAN_IDLE)
        old = PendingConfirmation(kind="plan_mutation", action_family="add_units")
        phase.set_pending(old)

        new = PendingConfirmation(kind="plan_mutation", action_family="remove_units")
        phase.set_pending(new)

        assert phase.pending is new
        assert phase.pending.action_family == "remove_units"


# ---------------------------------------------------------------------------
# ConversationPhase — 统一 pendingConfirmation 入口
# ---------------------------------------------------------------------------

class TestConversationPhaseFromPendingConfirmation:
    """从后端 active pendingConfirmation 投影运行态。"""

    def test_without_pending_uses_planning_idle(self):
        phase = ConversationPhase.from_pending_confirmation(
            None,
            planning_summary={"phase": "ordered", "version": 11},
            turn_count=5,
        )

        assert phase.state == PhaseState.PLAN_IDLE
        assert phase.pending is None
        assert phase.turn_count == 5
        assert phase.last_backend_version == 11

    def test_plan_pending_uses_unified_pending_without_legacy_dict(self):
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="apply_fix_proposal",
            preview_summary="处理高收费志愿",
            execution_payload={"proposalId": "fp-1", "sourceVersionGuard": 12},
            source_backend_version=12,
            composite_proposal={"goal": {"goal_type": "reduce_risk"}},
        )

        phase = ConversationPhase.from_pending_confirmation(
            pending,
            planning_summary={"phase": "reviewed", "version": 9},
            turn_count=4,
        )

        assert phase.state == PhaseState.PLAN_PREVIEWING
        assert phase.pending is not None
        assert phase.pending is not pending
        assert phase.pending.created_turn == 4
        assert phase.pending.action_family == "apply_fix_proposal"
        assert phase.pending.execution_payload["proposalId"] == "fp-1"
        assert phase.pending.composite_proposal == {"goal": {"goal_type": "reduce_risk"}}
        assert phase.last_backend_version == 12

    def test_intent_pending_uses_intent_previewing(self):
        pending = PendingConfirmation(
            kind="intent_change",
            action_family="apply_selected_intents",
            preview_summary="采纳地域想法",
            execution_payload={"merged": {"city_intents": {"province": ["北京"]}}},
        )

        phase = ConversationPhase.from_pending_confirmation(
            pending,
            planning_summary={"phase": "ordered", "version": 8},
            turn_count=2,
        )

        assert phase.state == PhaseState.INTENT_PREVIEWING
        assert phase.pending is not None
        assert phase.pending.kind == "intent_change"
        assert phase.pending.created_turn == 2
        assert phase.last_backend_version == 8


# ---------------------------------------------------------------------------
# ConversationPhase — 序列化
# ---------------------------------------------------------------------------

class TestConversationPhaseSerialization:
    """序列化/反序列化。"""

    def test_model_dump_roundtrip(self):
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="replace_units",
                preview_summary="替换志愿",
                execution_payload={"ids": ["v1"]},
                created_turn=3,
                composite_proposal={"goal": {"goal_type": "reduce_risk"}},
            ),
            turn_count=5,
            last_backend_version=42,
        )
        data = phase.model_dump()
        restored = ConversationPhase.model_validate(data)
        assert restored.state == PhaseState.PLAN_PREVIEWING
        assert restored.pending.action_family == "replace_units"
        assert restored.pending.composite_proposal == {"goal": {"goal_type": "reduce_risk"}}
        assert restored.turn_count == 5
        assert restored.last_backend_version == 42

    def test_json_roundtrip(self):
        phase = ConversationPhase(
            state=PhaseState.EXPLORE,
            turn_count=0,
        )
        json_str = phase.model_dump_json()
        restored = ConversationPhase.model_validate_json(json_str)
        assert restored.state == PhaseState.EXPLORE
        assert restored.pending is None
