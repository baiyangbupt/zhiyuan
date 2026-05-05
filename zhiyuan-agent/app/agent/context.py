from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from app.models.conversation_phase import ConversationPhase
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
    draft_total: int = 0
    draft_target_total: int = 0
    ordered_total: int = 0
    ordered_target_total: int = 0
    review_warn_count: int = 0
    review_risk_count: int = 0
    risk_summaries: list[str] = field(default_factory=list)
    pending_action_count: int = 0
    pending_action_summaries: list[str] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=dict)
    sample_schools: list[str] = field(default_factory=list)
    positive_regions: list[str] = field(default_factory=list)
    positive_majors: list[str] = field(default_factory=list)

    @classmethod
    def from_backend_state(cls, data: dict | None) -> "PlanningSummary | None":
        """从 backend planningState 响应提炼出 agent 可用摘要。"""
        if not data:
            return None

        review_state = data.get("reviewState") or {}
        checks = review_state.get("checks") or []
        pending_actions = data.get("pendingActions") or []

        risk_summaries: list[str] = []
        for check in checks:
            if check.get("passed") is True:
                continue
            summary = check.get("summary")
            if summary:
                risk_summaries.append(summary)
            if len(risk_summaries) >= 2:
                break

        pending_action_summaries: list[str] = []
        for action in pending_actions[:2]:
            summary = action.get("summary")
            if summary:
                pending_action_summaries.append(summary)

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

        return cls(
            phase=data.get("phase") or "",
            version=data.get("version") or 0,
            candidate_target_total=((data.get("candidatePoolState") or {}).get("requiredCount") or 0),
            draft_total=((data.get("draftPlanState") or {}).get("summary") or {}).get("unitTotal")
            or ((data.get("draftPlanState") or {}).get("summary") or {}).get("total")
            or 0,
            draft_target_total=((data.get("draftPlanState") or {}).get("summary") or {}).get("targetUnitCount")
            or ((data.get("draftPlanState") or {}).get("summary") or {}).get("targetCount")
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
            pending_action_count=len(pending_actions),
            pending_action_summaries=pending_action_summaries,
            tier_counts=tier_counts,
            sample_schools=seen_schools,
            positive_regions=positive_regions[:5],
            positive_majors=positive_majors[:5],
        )


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
    pending_plan_action: dict | None = None  # 上一轮待确认的 Plan 动作摘要与 apply payload (deprecated, 用 conversation_phase.pending)
    pending_intent_change: bool = False  # 当前轮开始前是否已有待确认的 Intent 变更 (deprecated, 用 conversation_phase.pending)
    conversation_phase: ConversationPhase | None = None  # Phase 3 新增：统一对话阶段状态
    progress_callback: Callable[[str], Awaitable[None]] | None = None
