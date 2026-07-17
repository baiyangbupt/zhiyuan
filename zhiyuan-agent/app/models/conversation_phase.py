"""对话阶段状态机 + 统一待确认协议。

主状态源是后端 ``pendingConfirmation``。卡片确认是主入口；
短文本确认只作为 active pending 的兜底入口，必须经过服务端 pending
状态、类型和版本校验后才能执行意向或方案更新。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _planning_summary_version(planning_summary: Any) -> int:
    if planning_summary is None:
        return 0
    if isinstance(planning_summary, dict):
        return _as_int(planning_summary.get("version"))
    return _as_int(getattr(planning_summary, "version", 0))


class PhaseState(str, Enum):
    """对话阶段状态。

    状态转换规则：
    - EXPLORE → EXPLORE:               继续探索
    - EXPLORE → INTENT_PREVIEWING:     识别到偏好/约束意向
    - INTENT_PREVIEWING → EXPLORE:     用户拒绝意向变更
    - INTENT_PREVIEWING → PLAN_IDLE:   用户确认意向变更
    - EXPLORE → PLAN_IDLE:             直接进入方案讨论
    - PLAN_IDLE → PLAN_PREVIEWING:     产生了待确认的方案动作
    - PLAN_PREVIEWING → PLAN_IDLE:     用户确认/拒绝方案动作
    - PLAN_IDLE → EXPLORE:             从方案讨论回到探索
    - * → EXPLORE:                     任意阶段可回到探索

    注意：不强制线性流转，用户可在任意阶段切换话题。
    """

    EXPLORE = "explore"
    INTENT_PREVIEWING = "intent_previewing"
    PLAN_IDLE = "plan_idle"
    PLAN_PREVIEWING = "plan_previewing"


# 合法的状态转换（from_state → to_state）
_VALID_TRANSITIONS: set[tuple[PhaseState, PhaseState]] = {
    # Explore 内部循环
    (PhaseState.EXPLORE, PhaseState.EXPLORE),
    # Explore ↔ Intent
    (PhaseState.EXPLORE, PhaseState.INTENT_PREVIEWING),
    (PhaseState.INTENT_PREVIEWING, PhaseState.EXPLORE),
    # Intent → Plan
    (PhaseState.INTENT_PREVIEWING, PhaseState.PLAN_IDLE),
    # Explore → Plan（跳过 Intent 直接谈方案）
    (PhaseState.EXPLORE, PhaseState.PLAN_IDLE),
    # Plan 内部循环
    (PhaseState.PLAN_IDLE, PhaseState.PLAN_IDLE),
    (PhaseState.PLAN_IDLE, PhaseState.PLAN_PREVIEWING),
    (PhaseState.PLAN_PREVIEWING, PhaseState.PLAN_IDLE),
    # Plan → Explore（从方案讨论回到信息探索）
    (PhaseState.PLAN_IDLE, PhaseState.EXPLORE),
    (PhaseState.PLAN_PREVIEWING, PhaseState.EXPLORE),
    # Intent 也可直接进入 Explore
    (PhaseState.INTENT_PREVIEWING, PhaseState.PLAN_PREVIEWING),
}


class PendingConfirmation(BaseModel):
    """统一的待确认操作模型。

    一次只能有一个 pending，新 pending 会覆盖旧 pending。
    """

    # 后端 pendingConfirmation 的持久化 ID，用于新 pending 覆盖旧 pending 时
    # 建立 replacesPendingId 关系。
    pending_id: str = ""

    kind: Literal["intent_change", "plan_mutation", "plan_generation"]

    # 后端 pending 资源标识。确认执行时用于校验运行时投影与 Sandbox
    # 快照仍指向同一轮预览。
    pending_id: str = ""

    # 对应的 action_family
    # Intent: "set_preference" / "set_constraint" / "remove_preference"
    # Plan: "add_units" / "remove_units" / "generate_plan" 等
    action_family: str

    # 用户可见的预览摘要
    preview_summary: str = ""

    # 确认后执行所需的完整 payload
    # Intent: intent cache data
    # Plan: 4.0 结构化 pending payload
    execution_payload: dict[str, Any] = Field(default_factory=dict)

    # 影响范围描述（如 "涉及3个高收费志愿"）
    affected_scope: str = ""

    # 创建时的轮次号，用于过期判断
    created_turn: int = 0

    # 生成 preview 时的后端 planningState 版本，用于确认前版本漂移校验
    source_backend_version: int = 0

    # 复合目标/动作编排的解释性元信息。
    # 它只用于运行态上下文、预览说明和审计，不参与实际 apply 权限判断。
    composite_proposal: dict[str, Any] = Field(default_factory=dict)


class ConversationPhase(BaseModel):
    """对话阶段状态机。

    跟踪当前对话所处的阶段、待确认操作和版本信息。

    使用场景：
    - ActionResolver 根据 state 判断可用动作
    - 确认协议根据 pending 判断是否允许 apply
    - 版本乐观锁根据 last_backend_version 判断 stale

    新会话和历史恢复后的活动状态都由后端 active pendingConfirmation
    构建 ``conversation_phase.pending``。
    """

    state: PhaseState = PhaseState.EXPLORE
    pending: PendingConfirmation | None = None
    turn_count: int = 0
    last_backend_version: int = 0

    def can_transition_to(self, target: PhaseState) -> bool:
        """检查是否可以合法转换到目标状态。"""
        return (self.state, target) in _VALID_TRANSITIONS

    def transition_to(self, target: PhaseState) -> None:
        """转换到目标状态，非法转换抛 ValueError。"""
        if not self.can_transition_to(target):
            raise ValueError(
                f"非法状态转换: {self.state.value} → {target.value}"
            )
        self.state = target

    def set_pending(self, pending: PendingConfirmation) -> None:
        """设置待确认操作，同时切换到对应的 previewing 状态。"""
        self.pending = pending
        if pending.kind == "intent_change":
            self.state = PhaseState.INTENT_PREVIEWING
        elif pending.kind in {"plan_mutation", "plan_generation"}:
            self.state = PhaseState.PLAN_PREVIEWING

    def clear_pending(self) -> PendingConfirmation | None:
        """清除待确认操作，返回被清除的 pending（如果有的话）。"""
        cleared = self.pending
        self.pending = None
        # 回退到 idle 状态
        if self.state == PhaseState.PLAN_PREVIEWING:
            self.state = PhaseState.PLAN_IDLE
        elif self.state == PhaseState.INTENT_PREVIEWING:
            self.state = PhaseState.EXPLORE
        return cleared

    def is_pending_stale(self, current_turn: int, max_age: int = 3) -> bool:
        """检查 pending 是否已过期（超过 max_age 轮未确认）。"""
        if self.pending is None:
            return False
        return (current_turn - self.pending.created_turn) > max_age

    @classmethod
    def from_pending_confirmation(
        cls,
        pending_confirmation: PendingConfirmation | None = None,
        *,
        planning_summary: Any = None,
        turn_count: int = 0,
    ) -> "ConversationPhase":
        """Build phase state from the unified backend pendingConfirmation.

        This is the main path for live sessions and recovered history.
        """
        if pending_confirmation is None:
            state = PhaseState.PLAN_IDLE if planning_summary is not None else PhaseState.EXPLORE
            return cls(
                state=state,
                pending=None,
                turn_count=turn_count,
                last_backend_version=_planning_summary_version(planning_summary),
            )

        pending = pending_confirmation
        if pending.created_turn == 0 and turn_count > 0:
            pending = pending.model_copy(update={"created_turn": turn_count})
        state = (
            PhaseState.INTENT_PREVIEWING
            if pending.kind == "intent_change"
            else PhaseState.PLAN_PREVIEWING
        )
        last_backend_version = (
            pending.source_backend_version
            if pending.source_backend_version > 0
            else _planning_summary_version(planning_summary)
        )
        return cls(
            state=state,
            pending=pending,
            turn_count=turn_count,
            last_backend_version=last_backend_version,
        )
