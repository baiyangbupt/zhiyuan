"""Planning 状态同步 — 版本乐观锁与 pending 过期管理。

职责：
- 比较 session 缓存的 last_backend_version 与后端当前 version
- 检测 pending 是否因版本变化或超时而失效
- 执行前二次校验，阻止在 stale 状态下执行 mutating action

设计原则：
- 只做判断和标记，不直接执行后端调用
- 所有副作用通过返回 StateChangeEvent 传递给调用方
- 向后兼容：没有 ConversationPhase 时优雅降级
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent.context import PlanningSummary, RequestContext
    from app.models.conversation_phase import ConversationPhase

logger = logging.getLogger(__name__)


class StaleCause(str, Enum):
    """导致状态失效的原因。"""

    VERSION_MISMATCH = "version_mismatch"
    TURN_EXPIRED = "turn_expired"
    PHASE_CHANGED = "phase_changed"


@dataclass
class StateChangeEvent:
    """状态变化事件，通知调用方需要执行的操作。"""

    is_stale: bool = False
    cause: StaleCause | None = None
    old_version: int = 0
    new_version: int = 0
    message: str = ""
    should_clear_pending: bool = False
    should_refresh_context: bool = False


@dataclass
class VersionCheckResult:
    """版本检查结果。"""

    is_current: bool = True
    local_version: int = 0
    remote_version: int = 0
    drift: int = 0


class PlanningStateSync:
    """Planning 状态同步管理器。

    典型使用流程：
    1. handle_message 开始时调用 check_version → 记录是否有漂移
    2. 如有 pending，调用 invalidate_if_stale → 检查是否应清除
    3. 执行 mutating action 前调用 pre_execute_guard → 最终拦截

    Usage:
        sync = PlanningStateSync()
        version_result = sync.check_version(phase, planning_summary)
        if phase.pending:
            event = sync.invalidate_if_stale(phase, current_turn, planning_summary)
            if event.should_clear_pending:
                phase.clear_pending()
        # 执行前
        guard_event = sync.pre_execute_guard(phase, planning_summary, action_family)
        if guard_event.is_stale:
            return blocked_response(guard_event.message)
    """

    def __init__(self, *, max_pending_age: int = 3) -> None:
        self._max_pending_age = max_pending_age

    def check_version(
        self,
        phase: ConversationPhase | None,
        planning_summary: PlanningSummary | None,
    ) -> VersionCheckResult:
        """比较本地缓存版本与后端最新版本。

        Returns:
            VersionCheckResult 表示版本是否一致及漂移量。
        """
        if phase is None or planning_summary is None:
            return VersionCheckResult(is_current=True)

        local_version = phase.last_backend_version
        remote_version = planning_summary.version

        if local_version == 0:
            return VersionCheckResult(
                is_current=True,
                local_version=local_version,
                remote_version=remote_version,
                drift=0,
            )

        drift = remote_version - local_version
        is_current = drift == 0

        if not is_current:
            logger.info(
                "Version drift detected: local=%d remote=%d drift=%d",
                local_version,
                remote_version,
                drift,
            )

        return VersionCheckResult(
            is_current=is_current,
            local_version=local_version,
            remote_version=remote_version,
            drift=drift,
        )

    def invalidate_if_stale(
        self,
        phase: ConversationPhase | None,
        current_turn: int,
        planning_summary: PlanningSummary | None,
    ) -> StateChangeEvent:
        """检查 pending 是否因版本漂移或超时而失效。

        检查顺序：
        1. 版本漂移 → 如果后端版本变了，说明有其他操作修改了方案
        2. 轮次超时 → 超过 max_pending_age 轮未确认
        """
        if phase is None or phase.pending is None:
            return StateChangeEvent(is_stale=False)

        # 检查版本漂移
        if planning_summary is not None and phase.last_backend_version > 0:
            if planning_summary.version > phase.last_backend_version:
                msg = (
                    f"方案已被其他操作更新（版本 {phase.last_backend_version}"
                    f" → {planning_summary.version}），上一轮的预览已失效"
                )
                logger.info(
                    "Pending invalidated by version mismatch: %s → %s",
                    phase.last_backend_version,
                    planning_summary.version,
                )
                return StateChangeEvent(
                    is_stale=True,
                    cause=StaleCause.VERSION_MISMATCH,
                    old_version=phase.last_backend_version,
                    new_version=planning_summary.version,
                    message=msg,
                    should_clear_pending=True,
                    should_refresh_context=True,
                )

        # 检查轮次超时
        if phase.is_pending_stale(current_turn, max_age=self._max_pending_age):
            msg = (
                f"上一轮的操作预览已超过 {self._max_pending_age} 轮未确认，已自动失效"
            )
            logger.info(
                "Pending invalidated by turn expiry: created=%d current=%d max_age=%d",
                phase.pending.created_turn,
                current_turn,
                self._max_pending_age,
            )
            return StateChangeEvent(
                is_stale=True,
                cause=StaleCause.TURN_EXPIRED,
                message=msg,
                should_clear_pending=True,
                should_refresh_context=False,
            )

        return StateChangeEvent(is_stale=False)

    def pre_execute_guard(
        self,
        phase: ConversationPhase | None,
        planning_summary: PlanningSummary | None,
        action_family: str,
    ) -> StateChangeEvent:
        """执行前二次校验 — 在 mutating action apply 之前调用。

        仅对 mutating actions 生效，query/analyze 类不拦截。
        """
        _MUTATING_FAMILIES = {
            "generate_plan",
            "add_units",
            "remove_units",
            "move_unit",
            "move_ordered_unit",
            "remove_ordered_unit",
            "replace_units",
            "sort_ordered_plan",
            "regenerate_order",
            "apply_compensation",
        }

        if action_family not in _MUTATING_FAMILIES:
            return StateChangeEvent(is_stale=False)

        if phase is None or planning_summary is None:
            return StateChangeEvent(is_stale=False)

        # 版本乐观锁：如果 local > 0 且 remote 已变化，拦截
        if phase.last_backend_version > 0:
            if planning_summary.version > phase.last_backend_version:
                msg = (
                    f"方案状态已变更（版本 {phase.last_backend_version}"
                    f" → {planning_summary.version}），请重新确认操作"
                )
                return StateChangeEvent(
                    is_stale=True,
                    cause=StaleCause.VERSION_MISMATCH,
                    old_version=phase.last_backend_version,
                    new_version=planning_summary.version,
                    message=msg,
                    should_clear_pending=True,
                    should_refresh_context=True,
                )

        return StateChangeEvent(is_stale=False)

    def update_version(
        self,
        phase: ConversationPhase | None,
        planning_summary: PlanningSummary | None,
    ) -> None:
        """同步本地版本号到最新后端版本。

        在每次成功获取 planning_summary 后调用。
        """
        if phase is None or planning_summary is None:
            return
        phase.last_backend_version = planning_summary.version
