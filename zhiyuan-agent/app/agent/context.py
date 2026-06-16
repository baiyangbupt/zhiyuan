from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.util.planning_state_compat import get_working_plan_summary

if TYPE_CHECKING:
    from app.models.conversation_phase import ConversationPhase, PendingConfirmation
    from app.schemas.user_profile import UserProfile


@dataclass
class ScoreDetail:
    """学生高考成绩详情。"""

    province: str  # 学生高考的省份
    total_score: int  # 学生高考总分
    subject_list: list[str]  # 学生的选科列表
    sex: str  # 学生性别
    volunteer_model: str = "major"  # "major" | "majorGroup"


@dataclass
class PlanningSummary:
    """planningState 的轻量摘要，供 agent 指令层消费。"""

    phase: str = ""
    version: int = 0
    candidate_target_total: int = 0
    working_total: int = 0
    working_target_total: int = 0
    draft_total: int = 0
    draft_target_total: int = 0
    ordered_total: int = 0
    ordered_target_total: int = 0
    review_warn_count: int = 0
    review_risk_count: int = 0
    risk_summaries: list[str] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=dict)
    sample_schools: list[str] = field(default_factory=list)
    positive_regions: list[str] = field(default_factory=list)
    positive_majors: list[str] = field(default_factory=list)
    constraint_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_backend_state(cls, data: dict | None) -> "PlanningSummary | None":
        """从 backend planningState 响应提炼出 agent 可用摘要。"""
        if not data:
            return None

        review_state = data.get("reviewState") or {}
        checks = review_state.get("checks") or []

        risk_summaries: list[str] = []
        for check in checks:
            if check.get("passed") is True:
                continue
            summary = check.get("summary")
            if summary:
                risk_summaries.append(summary)
            if len(risk_summaries) >= 2:
                break

        ordered_state = data.get("orderedPlanState") or {}
        ordered_summary = ordered_state.get("summary") or {}
        tier_counts = ordered_summary.get("unitTierCounts") or ordered_summary.get("tierCounts") or {}

        ordered_items = ordered_state.get("items") or []
        seen_schools: list[str] = []
        for item in ordered_items:
            school = item.get("schoolName") or ""
            if school:
                clean = school.rstrip("第01234567890组").strip()
                if clean and clean not in seen_schools:
                    seen_schools.append(clean)
                    if len(seen_schools) >= 5:
                        break

        profile_state = data.get("profileState") or {}
        explicit = profile_state.get("explicitProfile") or {}
        positive_regions = explicit.get("positiveRegions") or []
        positive_majors = explicit.get("positiveMajors") or []

        working_plan_summary = get_working_plan_summary(data)
        return cls(
            phase=data.get("phase") or "",
            version=data.get("version") or 0,
            candidate_target_total=((data.get("candidatePoolState") or {}).get("requiredCount") or 0),
            working_total=working_plan_summary.get("unitTotal")
            or working_plan_summary.get("total")
            or 0,
            working_target_total=working_plan_summary.get("targetUnitCount")
            or working_plan_summary.get("targetCount")
            or ((data.get("candidatePoolState") or {}).get("requiredCount") or 0),
            ordered_total=((data.get("orderedPlanState") or {}).get("summary") or {}).get("unitTotal")
            or ((data.get("orderedPlanState") or {}).get("summary") or {}).get("total")
            or 0,
            ordered_target_total=((data.get("orderedPlanState") or {}).get("summary") or {}).get("targetUnitCount")
            or ((data.get("orderedPlanState") or {}).get("summary") or {}).get("targetCount")
            or ((data.get("candidatePoolState") or {}).get("requiredCount") or 0),
            review_warn_count=((review_state.get("summary") or {}).get("warnCount") or 0),
            review_risk_count=((review_state.get("summary") or {}).get("riskCount") or 0),
            risk_summaries=risk_summaries,
            tier_counts=tier_counts,
            sample_schools=seen_schools,
            positive_regions=positive_regions[:5],
            positive_majors=positive_majors[:5],
            constraint_state=data.get("constraintState") or {},
        )

    def __post_init__(self) -> None:
        if self.working_total <= 0 and self.draft_total > 0:
            self.working_total = self.draft_total
        elif self.draft_total <= 0 and self.working_total > 0:
            self.draft_total = self.working_total
        if self.working_target_total <= 0 and self.draft_target_total > 0:
            self.working_target_total = self.draft_target_total
        elif self.draft_target_total <= 0 and self.working_target_total > 0:
            self.draft_target_total = self.working_target_total


@dataclass
class RequestContext:
    """请求上下文，包含 userid 和 sessionid。"""

    userid: str
    sessionid: str
    chat_history: list[dict] | None = None  # 完整对话历史
    batch: str | None = None  # "01"=本科, 其他=专科
    score_detail: ScoreDetail | None = None  # 学生高考成绩详情
    init_profile: UserProfile | None = None  # flowconfig 预填的意向数据
    planning_summary: PlanningSummary | None = None  # planningState 轻量摘要
    conversation_phase: ConversationPhase | None = None  # Phase 3 新增：统一对话阶段状态
    progress_callback: Callable[[str], Awaitable[None]] | None = None
    allow_explore_inner_llm: bool = True  # 正式聊天主链路可关闭 Explore 工具内二次生成，由主模型统一组织最终回复
    enable_intent_side_effect_arbitration: bool = False  # 主链路用于拦截误触发的意向待确认副作用
    recent_intent_analysis: dict[str, Any] | None = None  # 最近一次 Intent 工具结构化结果，供指代追问恢复上下文
    agent_observability: dict[str, Any] = field(default_factory=dict)  # 本轮 Agent 节点耗时与失败定位信息
    confirmed_via_card: bool = False  # 服务端确认卡片点击链路，方案 apply 只能由该结构化上下文放行
    confirmed_via_pending: bool = False  # 服务端统一 pending 确认链路，包含卡片点击和短文本兜底
    confirmation_entry: str = ""  # "card" | "short_text"，仅用于审计和执行链路观测
    stale_pending_notice: str = ""  # 本轮开始时失效的待确认操作提示，供模型重新生成预览而不是复述旧确认


def resolve_pending_confirmation(deps: Any) -> "PendingConfirmation | None":
    """Resolve the active pending confirmation from unified state."""
    phase = getattr(deps, "conversation_phase", None)
    if phase is not None:
        return getattr(phase, "pending", None)
    return None


def resolve_pending_plan_payload_text(deps: Any) -> str:
    """Return the confirmable plan payload as JSON text, if any."""
    phase = getattr(deps, "conversation_phase", None)
    if phase is not None:
        pending = getattr(phase, "pending", None)
        if pending is not None and pending.kind == "plan_mutation":
            payload = pending.execution_payload
            if isinstance(payload, str):
                return payload
            if isinstance(payload, dict):
                return json.dumps(payload, ensure_ascii=False)
        return ""

    return ""


def has_pending_intent_confirmation(deps: Any) -> bool:
    """Whether the current session is waiting for intent confirmation."""
    phase = getattr(deps, "conversation_phase", None)
    if phase is not None:
        pending = getattr(phase, "pending", None)
        return bool(pending is not None and pending.kind == "intent_change")

    pending = resolve_pending_confirmation(deps)
    if pending is not None:
        return pending.kind == "intent_change"
    return False
