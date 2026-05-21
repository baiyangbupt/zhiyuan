"""对话阶段状态机 + 统一待确认协议。

替代现有的双轨 pending 机制：
- Intent 层的 pending_intent_change: bool + planEditCache（先转换为 PendingConfirmation）
- Plan 层的 pending_plan_action: dict + _is_short_plan_confirmation

统一为 PendingConfirmation 模型，一个字段覆盖两种待确认场景。

兼容策略：
- 旧 pending_plan_action dict 可通过 PendingConfirmation.from_legacy_plan_action() 转换
- 旧 pending_intent_change bool 可通过 PendingConfirmation.from_legacy_intent_change() 转换
- Phase 3 正式切换前，新旧字段并存
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

    替代现有的：
    - pending_plan_action: dict（Plan 层）
    - pending_intent_change: bool + planEditCache（Intent 层）

    一次只能有一个 pending，新 pending 会覆盖旧 pending。
    """

    kind: Literal["intent_change", "plan_mutation"]

    # 对应的 action_family
    # Intent: "set_preference" / "set_constraint" / "remove_preference"
    # Plan: "add_units" / "remove_units" / "generate_plan" 等
    action_family: str

    # 用户可见的预览摘要
    preview_summary: str = ""

    # 确认后执行所需的完整 payload
    # Intent: intent cache data
    # Plan: PlanActionPlan dict（stage 替换为 apply）
    execution_payload: dict[str, Any] = Field(default_factory=dict)

    # 影响范围描述（如 "涉及3个高收费志愿"）
    affected_scope: str = ""

    # 创建时的轮次号，用于过期判断
    created_turn: int = 0

    # 生成 preview 时的后端 planningState 版本，用于确认前版本漂移校验
    source_backend_version: int = 0

    @classmethod
    def from_legacy_plan_action(cls, legacy: dict) -> PendingConfirmation | None:
        """从旧格式 pending_plan_action dict 转换。

        旧格式：{"action_family": ..., "summary": ..., "plan_payload": str|dict}
        """
        if not legacy or not isinstance(legacy, dict):
            return None
        action_family = legacy.get("action_family", "")
        if not action_family:
            return None
        raw_payload = legacy.get("plan_payload", {})
        if isinstance(raw_payload, str):
            import json
            try:
                raw_payload = json.loads(raw_payload) if raw_payload.strip() else {}
            except Exception:
                raw_payload = {}
        payload_version = raw_payload.get("planning_version") if isinstance(raw_payload, dict) else 0
        created_turn = _as_int(legacy.get("created_turn"))
        source_backend_version = _as_int(
            legacy.get("source_backend_version")
            or legacy.get("planning_version")
            or payload_version
        )
        return cls(
            kind="plan_mutation",
            action_family=action_family,
            preview_summary=legacy.get("summary", ""),
            execution_payload=raw_payload if isinstance(raw_payload, dict) else {},
            affected_scope=legacy.get("affected_scope", ""),
            created_turn=created_turn,
            source_backend_version=source_backend_version,
        )

    @classmethod
    def from_legacy_intent_change(
        cls,
        intent_cache: dict | None = None,
        action_family: str = "set_preference",
    ) -> PendingConfirmation | None:
        """从旧格式 intent change cache 转换。"""
        if not intent_cache:
            return None
        return cls(
            kind="intent_change",
            action_family=action_family,
            preview_summary=intent_cache.get("summary", ""),
            execution_payload=intent_cache,
        )

    def to_legacy_plan_action(self) -> dict:
        """转回旧格式，兼容现有消费方。"""
        return {
            "action_family": self.action_family,
            "summary": self.preview_summary,
            "plan_payload": self.execution_payload,
            "affected_scope": self.affected_scope,
            "created_turn": self.created_turn,
            "source_backend_version": self.source_backend_version,
        }


class ConversationPhase(BaseModel):
    """对话阶段状态机。

    跟踪当前对话所处的阶段、待确认操作和版本信息。

    使用场景：
    - ActionResolver 根据 state 判断可用动作
    - 确认协议根据 pending 判断是否允许 apply
    - 版本乐观锁根据 last_backend_version 判断 stale

    兼容策略：
    - Phase 3 之前，该模型不会被注入到 RequestContext
    - 从旧字段推断初始值：
      - pending_plan_action 非空 → PLAN_PREVIEWING
      - pending_intent_confirmation 非空 → INTENT_PREVIEWING
      - planning_summary 非空 → PLAN_IDLE
      - 否则 → EXPLORE
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
        elif pending.kind == "plan_mutation":
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
    def from_legacy_context(
        cls,
        pending_plan_action: dict | None = None,
        pending_intent_confirmation: PendingConfirmation | None = None,
        pending_intent_change: bool = False,
        planning_summary: Any = None,
        turn_count: int = 0,
    ) -> ConversationPhase:
        """从旧的 RequestContext 字段推断初始状态。

        兼容现有会话：无需一次性迁移所有 session 数据。
        """
        pending: PendingConfirmation | None = None
        state = PhaseState.EXPLORE

        if pending_plan_action and isinstance(pending_plan_action, dict):
            pending = PendingConfirmation.from_legacy_plan_action(pending_plan_action)
            if pending is not None and pending.created_turn == 0 and turn_count > 0:
                pending = pending.model_copy(update={"created_turn": turn_count})
            state = PhaseState.PLAN_PREVIEWING
        elif pending_intent_confirmation is not None:
            pending = pending_intent_confirmation
            if pending.created_turn == 0 and turn_count > 0:
                pending = pending.model_copy(update={"created_turn": turn_count})
            state = PhaseState.INTENT_PREVIEWING
        elif pending_intent_change:
            pending = PendingConfirmation(
                kind="intent_change",
                action_family="set_preference",
                preview_summary="（从旧格式恢复的意向变更）",
                created_turn=turn_count,
            )
            state = PhaseState.INTENT_PREVIEWING
        elif planning_summary is not None:
            state = PhaseState.PLAN_IDLE

        if pending is not None and pending.source_backend_version > 0:
            last_backend_version = pending.source_backend_version
        else:
            last_backend_version = _planning_summary_version(planning_summary)

        return cls(
            state=state,
            pending=pending,
            turn_count=turn_count,
            last_backend_version=last_backend_version,
        )
