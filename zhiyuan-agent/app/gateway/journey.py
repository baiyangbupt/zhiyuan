"""J1 旅程派生：只读 Java 快照的 `journey` 块，不落库、不写业务状态。

边界（设计 §4）：
- Java 是事实的生产者；本模块只消费，不根据 staleFlags 的 null/非 null 重新推导。
- `statePhase` 在模型输出前可算；`taskIntent` 在模型输出后按确定性映射派生。
- `available_actions` 只做提示；网关不据此拒绝输出。
- `planned` 动作永不进入可用集合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# 固定动作目录。新增动作必须先在这里登记状态，fixture 校验器与提示词共用。
ACTION_STATUS: dict[str, str] = {
    "query_plan": "implemented",
    "query_facts": "implemented",
    "compare": "implemented",
    "explain_fit": "implemented",
    "recommend_candidates": "implemented",
    "review_plan": "implemented",       # 人工审查技能；不声称有审查产物
    "set_preference": "partial",        # scope/学费/排除/同档 priority_rules；风险姿态/目标优先级 J6
    "add_units": "implemented",         # EXPAND（纯加入）
    "replace_units": "implemented",     # add_units + addPolicy=replace（等量替换）
    "remove_units": "implemented",      # 精确移除，其他条目不动
    "move_units": "implemented",        # 单条/单组移动，集合不变
    "add_units_by_scope": "implemented",
    "fill_to_count": "implemented",
    "interpret_admission": "implemented",
    "update_score": "implemented",
    "update_career": "implemented",
    "confirm": "implemented",
    "cancel": "implemented",
    "regenerate": "planned",
    "undo": "planned",
    "rollback": "planned",
}

IMPLEMENTED_ACTIONS = frozenset(
    action for action, status in ACTION_STATUS.items() if status == "implemented"
)
PLANNED_ACTIONS = frozenset(
    action for action, status in ACTION_STATUS.items() if status == "planned"
)

# 会创建 pending/写草稿的动作；applying 时全部拒绝。
WRITE_ACTIONS = frozenset(
    {
        "add_units",
        "replace_units",
        "remove_units",
        "move_units",
        "add_units_by_scope",
        "fill_to_count",
        "set_preference",
        "update_score",
        "update_career",
    }
)

META_ACTIONS = frozenset({"wait", "continue_task", "clarify"})

STATE_PHASES = ("discover", "explore", "candidates", "build")
JOURNEY_PHASES = STATE_PHASES + ("verify", "review", "interpret", "adjust")


@dataclass(frozen=True)
class BlockedAction:
    action: str
    reason_code: str
    unblock: str


@dataclass
class JourneyContext:
    state_phase: str
    task_intent: str | None = None
    planning_stage: str | None = None
    has_profile: bool = False
    profile_missing: list[str] = field(default_factory=list)
    has_candidates: bool = False
    candidate_entry_count: int = 0
    candidate_source_version: int | None = None
    has_plan: bool = False
    plan_entry_count: int = 0
    ordered_entry_count: int = 0
    plan_interpretable: bool = False
    selection_target_count: int | None = None
    selection_current_count: int = 0
    plan_version: int | None = None
    plan_content_digest: str | None = None
    candidate_freshness: str = "absent"
    plan_freshness: str = "absent"
    plan_adjustment_stale: bool = False
    review_freshness: str = "absent"
    refresh_requirement: str = "none"
    review_source_version: int | None = None
    review_stale: bool = False
    tier_quota_goal: bool = False
    stale: bool = False
    stale_reason: str | None = None
    pending_status: str | None = None
    available_actions: list[str] = field(default_factory=list)
    blocked_actions: list[BlockedAction] = field(default_factory=list)
    recommended_next: str | None = None
    manual_review_digest: str | None = None
    manual_review_current: bool = False
    has_open_task: bool = False

    @property
    def phase(self) -> str:
        return self.task_intent or self.state_phase


def from_snapshot(
    snapshot: Any,
    *,
    manual_review_digest: str | None = None,
    has_open_task: bool = False,
) -> JourneyContext | None:
    """从 Java `journey` 块派生；旧快照没有块时返回 None（行为与今天一致）。"""
    raw = getattr(snapshot, "journey", None)
    if not isinstance(raw, Mapping):
        return None

    has_profile = _as_bool(raw.get("hasProfile"))
    has_candidates = _as_bool(raw.get("hasCandidates"))
    has_plan = _as_bool(raw.get("hasPlan"))
    plan_digest = _as_str(raw.get("planContentDigest"))
    manual_review_current = bool(
        manual_review_digest and plan_digest and manual_review_digest == plan_digest
    )
    candidate_freshness = _as_str(raw.get("candidateFreshness")) or "absent"
    plan_freshness = _as_str(raw.get("planFreshness")) or "absent"
    review_freshness = _as_str(raw.get("reviewFreshness")) or "absent"
    refresh_requirement = _as_str(raw.get("refreshRequirement")) or "none"
    if refresh_requirement == "none":
        # 旧 Java 没有 refreshRequirement 时的有界回落；只按组件 freshness 推。
        if candidate_freshness != "fresh":
            refresh_requirement = "candidates"
        elif plan_freshness != "fresh":
            refresh_requirement = "plan"
        elif review_freshness != "fresh":
            refresh_requirement = "review"

    context = JourneyContext(
        state_phase=derive_state_phase(
            has_profile=has_profile,
            has_candidates=has_candidates,
            has_plan=has_plan,
        ),
        planning_stage=_as_str(getattr(snapshot, "planning_stage", None)),
        has_profile=has_profile,
        profile_missing=_as_str_list(raw.get("profileMissing")),
        has_candidates=has_candidates,
        candidate_entry_count=_as_int(raw.get("candidateEntryCount")) or 0,
        candidate_source_version=_as_int(raw.get("candidateSourceVersion")),
        has_plan=has_plan,
        plan_entry_count=_as_int(raw.get("planEntryCount")) or 0,
        ordered_entry_count=_as_int(raw.get("orderedEntryCount")) or 0,
        plan_interpretable=_as_bool(raw.get("planInterpretable")),
        selection_target_count=_as_int(raw.get("selectionTargetCount")),
        selection_current_count=_as_int(raw.get("selectionCurrentCount")) or 0,
        plan_version=_as_int(raw.get("planVersion")),
        plan_content_digest=plan_digest,
        candidate_freshness=candidate_freshness,
        plan_freshness=plan_freshness,
        plan_adjustment_stale=_as_bool(raw.get("planAdjustmentStale")),
        review_freshness=review_freshness,
        refresh_requirement=refresh_requirement,
        review_source_version=_as_int(raw.get("reviewSourceVersion")),
        review_stale=_as_bool(raw.get("reviewStale")),
        tier_quota_goal=_as_bool(raw.get("tierQuotaGoal")),
        stale=_as_bool(raw.get("stale")),
        stale_reason=_as_str(raw.get("staleReasonCode")) or _as_str(raw.get("staleMessage")),
        pending_status=_as_str(raw.get("pendingStatus")),
        manual_review_digest=manual_review_digest,
        manual_review_current=manual_review_current,
        has_open_task=has_open_task,
    )
    context.blocked_actions = blocked_actions(context)
    context.available_actions = available_actions(context)
    context.recommended_next = recommended_next(context)
    return context


def derive_state_phase(*, has_profile: bool, has_candidates: bool, has_plan: bool) -> str:
    if not has_profile:
        return "discover"
    if has_plan:
        return "build"
    if not has_candidates:
        return "explore"
    return "candidates"


def derive_task_intent(
    output: Any,
    tool_names: list[str] | tuple[str, ...],
    state_phase: str,
) -> str | None:
    """模型输出后的确定性映射；不读用户文本、不猜关键词。"""
    tools = {str(name) for name in (tool_names or []) if name}
    response_type = str(getattr(output, "response_type", "") or "")
    if "planning.interpret_admission" in tools:
        return "interpret"
    if response_type == "review":
        return "review"
    if response_type == "fact" or tools & {
        "recommendation.compare_candidates",
        "recommendation.explain_fit",
    }:
        return "verify"
    if state_phase == "build" and _has_write_draft(output):
        return "adjust"
    return None


def turn_journey_result(
    snapshot: Any,
    output: Any,
    tool_names: list[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    context = from_snapshot(snapshot)
    if context is None:
        return None
    task_intent = derive_task_intent(output, tool_names, context.state_phase)
    return {
        "statePhase": context.state_phase,
        "taskIntent": task_intent,
        "phase": task_intent or context.state_phase,
    }


def blocked_actions(context: JourneyContext) -> list[BlockedAction]:
    """按设计 §4.5 的顺序判定；每个动作只保留第一条命中的原因。"""
    blocked: dict[str, BlockedAction] = {}

    def block(actions: tuple[str, ...] | list[str], reason: str, unblock: str) -> None:
        for action in actions:
            blocked.setdefault(action, BlockedAction(action, reason, unblock))

    if context.pending_status == "applying":
        block(
            sorted(WRITE_ACTIONS | {"confirm", "cancel"}),
            "pending_applying",
            "等当前变更出结果，再继续",
        )
    if not context.has_plan:
        block(
            [
                "add_units",
                "replace_units",
                "remove_units",
                "move_units",
                "add_units_by_scope",
                "interpret_admission",
                "review_plan",
            ],
            "no_plan",
            "先排出一版方案（可先补足到目标数量），再解读/加入",
        )
    if context.has_plan and not context.plan_interpretable:
        block(
            ["interpret_admission", "review_plan"],
            "plan_not_ordered",
            "先把草稿排成正式顺序（生成 ordered 方案），再解读/审查",
        )
    if not context.has_candidates:
        block(
            ["add_units", "replace_units", "add_units_by_scope", "fill_to_count"],
            "candidate_source_unavailable",
            "先生成或刷新候选池",
        )
    if context.candidate_freshness == "stale":
        block(
            ["add_units", "replace_units", "add_units_by_scope", "fill_to_count"],
            "candidate_stale",
            "先按新成绩/条件刷新候选池，再基于新候选调整",
        )
    if context.plan_freshness == "stale":
        block(
            ["add_units", "replace_units", "add_units_by_scope"],
            "plan_stale",
            "先按当前条件重算方案（可用“补足到目标数量”），再加入",
        )
    if context.tier_quota_goal:
        block(
            ["add_units", "replace_units", "remove_units", "add_units_by_scope"],
            "tier_quota_goal",
            "先调整冲稳保配额，再加入、替换或移除",
        )
    if (
        context.selection_target_count is not None
        and context.selection_target_count != context.selection_current_count
    ):
        block(
            ["add_units", "replace_units", "remove_units", "add_units_by_scope"],
            "target_count_mismatch",
            "先补齐/调整到已确认目标数量，再加入或移除",
        )
    return list(blocked.values())


def available_actions(context: JourneyContext) -> list[str]:
    actions = [
        "query_plan",
        "query_facts",
        "compare",
        "explain_fit",
        "set_preference",
        "update_score",
        "update_career",
    ]
    if context.has_profile:
        actions.append("recommend_candidates")
    if context.plan_interpretable:
        actions.extend(["review_plan", "interpret_admission"])
    if context.has_candidates and context.candidate_freshness == "fresh":
        actions.append("fill_to_count")
    if context.has_plan:
        actions.append("remove_units")
    if context.plan_interpretable:
        actions.append("move_units")
    if (
        context.has_plan
        and context.has_candidates
        and context.candidate_freshness == "fresh"
        and context.plan_freshness == "fresh"
    ):
        actions.extend(["add_units", "replace_units", "add_units_by_scope"])
    if context.pending_status == "active":
        actions.extend(["confirm", "cancel"])
    blocked = {item.action for item in blocked_actions(context)}
    return [action for action in actions if action not in blocked]


def recommended_next(context: JourneyContext) -> str:
    if context.pending_status == "applying":
        return "wait"
    if context.pending_status == "active":
        return "confirm"
    if not context.has_profile:
        return "update_score"
    # 新鲜度是安全信号：候选/方案过期时，未完成任务也要先刷新再继续，
    # 不能把旧候选上的任务草稿直接“继续”。
    if (
        context.refresh_requirement == "candidates"
        or context.candidate_freshness != "fresh"
    ):
        return "recommend_candidates"
    if context.refresh_requirement == "plan" or not context.plan_interpretable:
        return "fill_to_count"
    if context.has_open_task:
        return "continue_task"
    if context.refresh_requirement == "review":
        if context.manual_review_current:
            return "interpret_admission" if context.plan_interpretable else "wait"
        return "review_plan"
    if context.plan_interpretable:
        return "interpret_admission"
    return "wait"


def context_text(context: JourneyContext) -> str:
    """有界注入块：阶段/事实/新鲜度/正式方案/人工审查/动作/建议/planVersion。"""
    profile = "完整" if context.has_profile else "缺 " + "、".join(context.profile_missing or ["未知"])
    lines = [
        "【当前旅程】",
        f"阶段：{context.phase}",
        (
            f"事实：画像{profile}；候选池 {context.candidate_entry_count} 条；"
            f"方案 {context.plan_entry_count} 条；"
            f"待确认：{context.pending_status or '无'}"
        ),
        (
            f"新鲜度：候选 {context.candidate_freshness}；"
            f"方案 {context.plan_freshness}；"
            f"规则审查 {context.review_freshness}；"
            f"刷新要求 {context.refresh_requirement}"
        ),
        "新鲜度口径：以本块为准；staleFlags/staleMessage 是兼容字段，不据此判断规则审查是否新鲜。",
        *(
            [
                f"结构信号：planAdjustmentStale=true；规则审查={context.review_freshness}。"
                "结构调整不等于规则审查过期，以规则审查新鲜度为准。"
            ]
            if context.plan_adjustment_stale
            else []
        ),
        (
            f"正式方案：{'可解读（' + str(context.ordered_entry_count) + ' 条 ordered）' if context.plan_interpretable else '尚不可解读（需要 ordered 方案）'}"
        ),
        (
            "本版人工审查："
            + ("已看过，与当前方案内容一致" if context.manual_review_current else "未看过")
        ),
        "可用动作：" + ("、".join(context.available_actions) or "无"),
        "未支持动作：" + "、".join(sorted(PLANNED_ACTIONS)) + "（不得声称已执行）",
    ]
    if context.blocked_actions:
        lines.append(
            "阻断："
            + "；".join(
                f"{item.action}（{item.unblock}）" for item in context.blocked_actions
            )
        )
    if context.recommended_next:
        lines.append(f"建议下一步：{context.recommended_next}")
    if context.plan_version is not None:
        lines.append(
            f"方案版本：{context.plan_version}"
            f"（调用 planning.interpret_admission 时 planVersion 必须用 {context.plan_version}）"
        )
    if context.stale and context.stale_reason:
        lines.append(f"数据提示：{context.stale_reason}；先核对再基于旧结果下结论。")
    if context.has_open_task:
        lines.append("未完成任务：有（先按任务页继续，不要另起一套默认建议）。")
    return "\n".join(lines)


def _has_write_draft(output: Any) -> bool:
    return any(
        getattr(output, name, None) is not None
        for name in ("proposal_request", "score_update_request", "career_update_request")
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, str)]
