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

    # --- Legacy 转换 ---

    def test_from_legacy_plan_action_valid(self):
        legacy = {
            "action_family": "generate_plan",
            "summary": "将生成一版方案",
            "plan_payload": {"action_family": "generate_plan", "stage": "apply"},
            "affected_scope": "涉及全部志愿",
        }
        pc = PendingConfirmation.from_legacy_plan_action(legacy)
        assert pc is not None
        assert pc.kind == "plan_mutation"
        assert pc.action_family == "generate_plan"
        assert pc.preview_summary == "将生成一版方案"
        assert pc.affected_scope == "涉及全部志愿"

    def test_from_legacy_plan_action_empty(self):
        assert PendingConfirmation.from_legacy_plan_action({}) is None
        assert PendingConfirmation.from_legacy_plan_action(None) is None

    def test_from_legacy_plan_action_no_family(self):
        assert PendingConfirmation.from_legacy_plan_action({"summary": "x"}) is None

    def test_from_legacy_intent_change_valid(self):
        cache = {
            "summary": "设置地域偏好",
            "cities": ["北京"],
        }
        pc = PendingConfirmation.from_legacy_intent_change(cache, "set_preference")
        assert pc is not None
        assert pc.kind == "intent_change"
        assert pc.action_family == "set_preference"
        assert pc.execution_payload == cache

    def test_from_legacy_intent_change_none(self):
        assert PendingConfirmation.from_legacy_intent_change(None) is None
        assert PendingConfirmation.from_legacy_intent_change({}) is None

    def test_to_legacy_plan_action(self):
        pc = PendingConfirmation(
            kind="plan_mutation",
            action_family="remove_units",
            preview_summary="将删除2个志愿",
            execution_payload={"ids": ["v1", "v2"]},
            affected_scope="涉及2个志愿",
        )
        legacy = pc.to_legacy_plan_action()
        assert legacy["action_family"] == "remove_units"
        assert legacy["summary"] == "将删除2个志愿"
        assert legacy["plan_payload"] == {"ids": ["v1", "v2"]}
        assert legacy["affected_scope"] == "涉及2个志愿"

    def test_roundtrip_legacy_plan(self):
        """Legacy → PendingConfirmation → Legacy 往返。"""
        original = {
            "action_family": "replace_units",
            "summary": "替换高收费志愿",
            "plan_payload": {"remove_ids": ["v1"], "filters": {"tier": "稳"}},
            "affected_scope": "涉及1个高收费志愿",
        }
        pc = PendingConfirmation.from_legacy_plan_action(original)
        assert pc is not None
        restored = pc.to_legacy_plan_action()
        assert restored["action_family"] == original["action_family"]
        assert restored["summary"] == original["summary"]
        assert restored["plan_payload"] == original["plan_payload"]
        assert restored["affected_scope"] == original["affected_scope"]


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

    def test_set_pending_intent_change(self):
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
# ConversationPhase — Legacy 转换
# ---------------------------------------------------------------------------

class TestConversationPhaseFromLegacy:
    """从旧格式推断初始状态。"""

    def test_empty_legacy(self):
        phase = ConversationPhase.from_legacy_context()
        assert phase.state == PhaseState.EXPLORE
        assert phase.pending is None

    def test_with_pending_plan_action(self):
        legacy = {
            "action_family": "generate_plan",
            "summary": "生成方案",
            "plan_payload": {},
        }
        phase = ConversationPhase.from_legacy_context(
            pending_plan_action=legacy,
            turn_count=3,
        )
        assert phase.state == PhaseState.PLAN_PREVIEWING
        assert phase.pending is not None
        assert phase.pending.kind == "plan_mutation"
        assert phase.pending.action_family == "generate_plan"
        assert phase.turn_count == 3

    def test_with_pending_plan_action_source_version(self):
        legacy = {
            "action_family": "generate_plan",
            "summary": "生成方案",
            "plan_payload": {
                "stage": "preview",
                "planning_version": 7,
            },
        }
        phase = ConversationPhase.from_legacy_context(
            pending_plan_action=legacy,
            planning_summary={"version": 3},
            turn_count=3,
        )

        assert phase.state == PhaseState.PLAN_PREVIEWING
        assert phase.pending is not None
        assert phase.pending.source_backend_version == 7
        assert phase.pending.created_turn == 3
        assert phase.last_backend_version == 7
        legacy_roundtrip = phase.pending.to_legacy_plan_action()
        assert legacy_roundtrip["source_backend_version"] == 7
        assert legacy_roundtrip["created_turn"] == 3

    def test_with_pending_intent_change(self):
        phase = ConversationPhase.from_legacy_context(
            pending_intent_change=True,
            turn_count=2,
        )
        assert phase.state == PhaseState.INTENT_PREVIEWING
        assert phase.pending is not None
        assert phase.pending.kind == "intent_change"
        assert phase.pending.created_turn == 2

    def test_with_pending_intent_confirmation(self):
        legacy_cache = {
            "summary": "设置地域偏好",
            "city_intents": {"province": ["北京"]},
            "intent_mode": "preference",
        }
        phase = ConversationPhase.from_legacy_context(
            pending_intent_confirmation=PendingConfirmation.from_legacy_intent_change(legacy_cache),
            turn_count=4,
        )
        assert phase.state == PhaseState.INTENT_PREVIEWING
        assert phase.pending is not None
        assert phase.pending.kind == "intent_change"
        assert phase.pending.execution_payload == legacy_cache
        assert phase.pending.created_turn == 4

    def test_with_planning_summary(self):
        phase = ConversationPhase.from_legacy_context(
            planning_summary={"phase": "ordered", "count": 30},
        )
        assert phase.state == PhaseState.PLAN_IDLE
        assert phase.pending is None

    def test_with_planning_summary_version(self):
        phase = ConversationPhase.from_legacy_context(
            planning_summary={"phase": "ordered", "count": 30, "version": 9},
        )
        assert phase.state == PhaseState.PLAN_IDLE
        assert phase.pending is None
        assert phase.last_backend_version == 9

    def test_priority_plan_over_intent(self):
        """pending_plan_action 优先于 pending_intent_change。"""
        legacy = {
            "action_family": "add_units",
            "summary": "添加",
            "plan_payload": {},
        }
        phase = ConversationPhase.from_legacy_context(
            pending_plan_action=legacy,
            pending_intent_change=True,
        )
        assert phase.state == PhaseState.PLAN_PREVIEWING
        assert phase.pending.kind == "plan_mutation"


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
            ),
            turn_count=5,
            last_backend_version=42,
        )
        data = phase.model_dump()
        restored = ConversationPhase.model_validate(data)
        assert restored.state == PhaseState.PLAN_PREVIEWING
        assert restored.pending.action_family == "replace_units"
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
