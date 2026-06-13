"""PlanningStateSync 单元测试。

验证版本乐观锁、pending 过期和执行前 guard 逻辑。
"""

from __future__ import annotations

import pytest

from app.models.conversation_phase import (
    ConversationPhase,
    PendingConfirmation,
    PhaseState,
)
from app.sync.state_sync import (
    PlanningStateSync,
    StaleCause,
    StateChangeEvent,
    VersionCheckResult,
)
from tests.factories import make_planning_summary


@pytest.fixture
def sync():
    return PlanningStateSync(max_pending_age=3)


# ---------------------------------------------------------------------------
# check_version
# ---------------------------------------------------------------------------


class TestCheckVersion:
    def test_none_phase_returns_current(self, sync):
        summary = make_planning_summary(version=5)
        result = sync.check_version(None, summary)
        assert result.is_current is True

    def test_none_summary_returns_current(self, sync):
        phase = ConversationPhase(last_backend_version=3)
        result = sync.check_version(phase, None)
        assert result.is_current is True

    def test_first_turn_version_zero_is_current(self, sync):
        phase = ConversationPhase(last_backend_version=0)
        summary = make_planning_summary(version=5)
        result = sync.check_version(phase, summary)
        assert result.is_current is True
        assert result.drift == 0

    def test_same_version_is_current(self, sync):
        phase = ConversationPhase(last_backend_version=5)
        summary = make_planning_summary(version=5)
        result = sync.check_version(phase, summary)
        assert result.is_current is True
        assert result.drift == 0

    def test_remote_ahead_detects_drift(self, sync):
        phase = ConversationPhase(last_backend_version=3)
        summary = make_planning_summary(version=7)
        result = sync.check_version(phase, summary)
        assert result.is_current is False
        assert result.drift == 4
        assert result.local_version == 3
        assert result.remote_version == 7

    def test_remote_behind_detects_negative_drift(self, sync):
        phase = ConversationPhase(last_backend_version=10)
        summary = make_planning_summary(version=8)
        result = sync.check_version(phase, summary)
        assert result.is_current is False
        assert result.drift == -2


# ---------------------------------------------------------------------------
# invalidate_if_stale
# ---------------------------------------------------------------------------


class TestInvalidateIfStale:
    def test_no_phase_not_stale(self, sync):
        event = sync.invalidate_if_stale(None, current_turn=5, planning_summary=None)
        assert event.is_stale is False

    def test_no_pending_not_stale(self, sync):
        phase = ConversationPhase(state=PhaseState.PLAN_IDLE)
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=None)
        assert event.is_stale is False

    def test_version_mismatch_invalidates(self, sync):
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=3,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                preview_summary="添加5个志愿",
                created_turn=4,
            ),
        )
        summary = make_planning_summary(version=5)
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is True
        assert event.cause == StaleCause.VERSION_MISMATCH
        assert event.should_clear_pending is True
        assert event.should_refresh_context is True
        assert "3" in event.message
        assert "5" in event.message

    def test_turn_expired_invalidates(self, sync):
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=5,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="移除高收费志愿",
                created_turn=1,
            ),
        )
        summary = make_planning_summary(version=5)
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is True
        assert event.cause == StaleCause.TURN_EXPIRED
        assert event.should_clear_pending is True
        assert event.should_refresh_context is False

    def test_within_age_not_stale(self, sync):
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=5,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                preview_summary="添加",
                created_turn=3,
            ),
        )
        summary = make_planning_summary(version=5)
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is False

    def test_version_zero_skips_version_check(self, sync):
        """last_backend_version=0 时不做版本比较（首次加载）。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=0,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                preview_summary="添加",
                created_turn=4,
            ),
        )
        summary = make_planning_summary(version=10)
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is False

    def test_version_priority_over_turn(self, sync):
        """版本漂移优先于轮次超时判断。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=2,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="移除",
                created_turn=0,
            ),
        )
        summary = make_planning_summary(version=5)
        event = sync.invalidate_if_stale(phase, current_turn=10, planning_summary=summary)
        assert event.cause == StaleCause.VERSION_MISMATCH


# ---------------------------------------------------------------------------
# pre_execute_guard
# ---------------------------------------------------------------------------


class TestPreExecuteGuard:
    def test_non_mutating_action_passes(self, sync):
        phase = ConversationPhase(last_backend_version=1)
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(phase, summary, "query_state")
        assert event.is_stale is False

    def test_analyze_action_passes(self, sync):
        phase = ConversationPhase(last_backend_version=1)
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(phase, summary, "analyze_adjustment")
        assert event.is_stale is False

    def test_review_action_passes(self, sync):
        phase = ConversationPhase(last_backend_version=1)
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(phase, summary, "review_plan")
        assert event.is_stale is False

    @pytest.mark.parametrize("action_family", [
        "generate_plan",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "remove_ordered_unit",
        "replace_units",
        "sort_ordered_plan",
        "regenerate_order",
    ])
    def test_mutating_action_blocked_on_version_drift(self, sync, action_family):
        phase = ConversationPhase(last_backend_version=3)
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(phase, summary, action_family)
        assert event.is_stale is True
        assert event.cause == StaleCause.VERSION_MISMATCH
        assert event.should_clear_pending is True

    @pytest.mark.parametrize("action_family", [
        "generate_plan",
        "add_units",
        "remove_units",
        "move_ordered_unit",
        "remove_ordered_unit",
    ])
    def test_mutating_action_passes_when_version_current(self, sync, action_family):
        phase = ConversationPhase(last_backend_version=5)
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(phase, summary, action_family)
        assert event.is_stale is False

    def test_version_zero_passes(self, sync):
        """首次加载 version=0 不阻止执行。"""
        phase = ConversationPhase(last_backend_version=0)
        summary = make_planning_summary(version=10)
        event = sync.pre_execute_guard(phase, summary, "add_units")
        assert event.is_stale is False

    def test_none_phase_passes(self, sync):
        summary = make_planning_summary(version=5)
        event = sync.pre_execute_guard(None, summary, "add_units")
        assert event.is_stale is False

    def test_none_summary_passes(self, sync):
        phase = ConversationPhase(last_backend_version=3)
        event = sync.pre_execute_guard(phase, None, "add_units")
        assert event.is_stale is False


# ---------------------------------------------------------------------------
# update_version
# ---------------------------------------------------------------------------


class TestUpdateVersion:
    def test_updates_local_version(self, sync):
        phase = ConversationPhase(last_backend_version=0)
        summary = make_planning_summary(version=7)
        sync.update_version(phase, summary)
        assert phase.last_backend_version == 7

    def test_none_phase_noop(self, sync):
        summary = make_planning_summary(version=5)
        sync.update_version(None, summary)

    def test_none_summary_noop(self, sync):
        phase = ConversationPhase(last_backend_version=3)
        sync.update_version(phase, None)
        assert phase.last_backend_version == 3

    def test_repeated_updates(self, sync):
        phase = ConversationPhase(last_backend_version=0)
        sync.update_version(phase, make_planning_summary(version=1))
        assert phase.last_backend_version == 1
        sync.update_version(phase, make_planning_summary(version=3))
        assert phase.last_backend_version == 3


# ---------------------------------------------------------------------------
# Integration: check + invalidate + guard 组合
# ---------------------------------------------------------------------------


class TestFullCycle:
    def test_normal_flow_no_stale(self, sync):
        """正常流程：版本一致，pending 未过期。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=5,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                created_turn=4,
            ),
            turn_count=5,
        )
        summary = make_planning_summary(version=5)

        version_result = sync.check_version(phase, summary)
        assert version_result.is_current is True

        stale_event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert stale_event.is_stale is False

        guard_event = sync.pre_execute_guard(phase, summary, "add_units")
        assert guard_event.is_stale is False

    def test_concurrent_modification_flow(self, sync):
        """并发修改流程：前端操作导致版本变化。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=3,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="移除5个志愿",
                created_turn=4,
            ),
            turn_count=5,
        )
        summary = make_planning_summary(version=5)

        version_result = sync.check_version(phase, summary)
        assert version_result.is_current is False
        assert version_result.drift == 2

        stale_event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert stale_event.is_stale is True
        assert stale_event.should_clear_pending is True

        # 调用方应清除 pending
        phase.clear_pending()
        assert phase.pending is None
        assert phase.state == PhaseState.PLAN_IDLE

        # 更新本地版本
        sync.update_version(phase, summary)
        assert phase.last_backend_version == 5

    def test_timeout_flow(self, sync):
        """超时流程：用户多轮未确认。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            last_backend_version=5,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="generate_plan",
                created_turn=1,
            ),
            turn_count=5,
        )
        summary = make_planning_summary(version=5)

        stale_event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert stale_event.is_stale is True
        assert stale_event.cause == StaleCause.TURN_EXPIRED

        phase.clear_pending()
        assert phase.state == PhaseState.PLAN_IDLE
