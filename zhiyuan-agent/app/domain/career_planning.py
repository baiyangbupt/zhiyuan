"""Career-planning policy helpers shared by Explore direction analysis."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.context import ScoreDetail


@dataclass(frozen=True)
class CareerPlanningPolicy:
    score_band: str
    employment_first: bool
    summary: str


def resolve_career_planning_policy(score_detail: ScoreDetail | None) -> CareerPlanningPolicy:
    """Return a coarse career-planning policy for exploratory direction analysis.

    This is intentionally lightweight and only guides Explore-stage advice.
    It does not act as a hard constraint for downstream planning execution.
    """
    if not score_detail:
        return CareerPlanningPolicy(
            score_band="unknown",
            employment_first=False,
            summary="当前没有完整分数信息，职业路径判断先不额外施加分段规则。",
        )

    total_score = int(score_detail.total_score or 0)
    volunteer_model = (score_detail.volunteer_model or "").strip()

    if total_score <= 520 or volunteer_model == "major" and total_score <= 560:
        return CareerPlanningPolicy(
            score_band="low_or_mid",
            employment_first=True,
            summary="当前分数段更适合优先保证就业确定性，选学校和专业时先看就业承接，不把深造当第一目标。",
        )

    if total_score <= 580:
        return CareerPlanningPolicy(
            score_band="mid",
            employment_first=True,
            summary="当前分数段可以保留长期发展想法，但方向判断上仍应先看就业质量和落地性，再谈读研深造。",
        )

    return CareerPlanningPolicy(
        score_band="high",
        employment_first=False,
        summary="当前分数段可以同时兼顾就业与深造，不需要在 Explore 阶段默认压制升学路径。",
    )
