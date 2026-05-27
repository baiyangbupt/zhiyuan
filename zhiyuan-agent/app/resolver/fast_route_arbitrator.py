"""Unified arbitration for high-confidence dialog fast routes.

Fast routers should propose candidates, not independently own the turn.  This
module keeps latency optimizations behind a quality-first gate so ambiguous or
cross-domain user requests can fall back to the full agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FastRoutePath = Literal[
    "plan_fast_route",
    "plan_query_fast_route",
    "major_intent_fast_route",
    "major_compare_fast_route",
    "career_direction_fast_route",
]


_PATH_PRIORITY: dict[FastRoutePath, int] = {
    "plan_fast_route": 90,
    "plan_query_fast_route": 86,
    "major_intent_fast_route": 82,
    "major_compare_fast_route": 80,
    "career_direction_fast_route": 76,
}

_PLAN_READONLY_ACTIONS = {"query_state", "review_plan"}
_PLAN_PREVIEW_ACTIONS = {
    "move_unit",
    "move_ordered_unit",
    "remove_units",
    "remove_ordered_unit",
    "add_units",
    "sort_ordered_plan",
    "preview_compensation",
    "analyze_adjustment",
}

_REGION_TRADEOFF_TOKENS = (
    "北京",
    "天津",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "成都",
    "武汉",
    "重庆",
    "西安",
    "省内",
    "省外",
    "外地",
    "本地",
    "城市",
    "地域",
    "地区",
    "想去",
)
_ADMISSION_SAFETY_TOKENS = (
    "没学上",
    "没书读",
    "滑档",
    "退档",
    "保底",
    "兜底",
    "托底",
    "安全",
    "风险",
    "冒险",
    "稳",
    "分数不算高",
    "分不高",
)
_EXPLICIT_PLAN_CONTEXT_TOKENS = ("方案", "志愿", "这版", "当前", "现在", "排序")


@dataclass(slots=True)
class FastRouteCandidate:
    path: FastRoutePath
    decision: Any
    scene: str
    action_family: str
    reason: str = ""
    confidence: str = ""
    side_effect: str = "readonly"
    quality: str = "high"
    score: int = 0
    blockers: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.blockers and self.quality != "insufficient"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "scene": self.scene,
            "actionFamily": self.action_family,
            "reason": self.reason,
            "confidence": self.confidence,
            "sideEffect": self.side_effect,
            "quality": self.quality,
            "score": self.score,
            "eligible": self.eligible,
            "blockers": list(self.blockers),
        }


@dataclass(slots=True)
class FastRouteArbitrationResult:
    selected: FastRouteCandidate | None = None
    candidates: list[FastRouteCandidate] = field(default_factory=list)
    fallback_reason: str = "no_fast_route_candidate"

    @property
    def selected_path(self) -> FastRoutePath | None:
        return self.selected.path if self.selected is not None else None

    def decision_for(self, path: FastRoutePath) -> Any | None:
        if self.selected is None or self.selected.path != path:
            return None
        return self.selected.decision

    def route_decision(self) -> dict[str, Any]:
        return {
            "source": "fast_route_arbitrator",
            "selectedPath": self.selected_path,
            "fallbackReason": None if self.selected is not None else self.fallback_reason,
            "qualityFirst": True,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


def _decision_attr(decision: Any, name: str, default: Any = None) -> Any:
    return getattr(decision, name, default)


def _matched(decision: Any | None) -> bool:
    return bool(decision is not None and _decision_attr(decision, "matched", False))


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _is_region_safety_tradeoff_without_plan_scope(text: str) -> bool:
    if not _contains_any(text, _REGION_TRADEOFF_TOKENS):
        return False
    if not _contains_any(text, _ADMISSION_SAFETY_TOKENS):
        return False
    return not _contains_any(text, _EXPLICIT_PLAN_CONTEXT_TOKENS)


def _plan_side_effect(action_family: str) -> str:
    if action_family in _PLAN_READONLY_ACTIONS:
        return "readonly"
    if action_family in _PLAN_PREVIEW_ACTIONS:
        return "preview_confirmation"
    return "unknown"


def _plan_quality_blockers(text: str, decision: Any) -> list[str]:
    reason = str(_decision_attr(decision, "reason", "") or "")
    action_family = str(_decision_attr(decision, "action_family", "") or "")
    if (
        action_family == "query_state"
        and reason == "plan_risk_status_query"
        and _is_region_safety_tradeoff_without_plan_scope(text)
    ):
        return ["region_safety_tradeoff_needs_full_analysis"]
    return []


def _candidate(
    *,
    path: FastRoutePath,
    decision: Any,
    scene: str,
    action_family: str,
    side_effect: str,
    text: str,
) -> FastRouteCandidate:
    reason = str(_decision_attr(decision, "reason", "") or "")
    confidence = str(_decision_attr(decision, "confidence", "") or "high")
    blockers: list[str] = []
    quality = "high"
    if path == "plan_fast_route":
        blockers.extend(_plan_quality_blockers(text, decision))
    if blockers:
        quality = "insufficient"
    score = _PATH_PRIORITY[path]
    if confidence == "high":
        score += 10
    if side_effect == "preview_confirmation":
        score += 4
    if blockers:
        score -= 100
    return FastRouteCandidate(
        path=path,
        decision=decision,
        scene=scene,
        action_family=action_family,
        reason=reason,
        confidence=confidence,
        side_effect=side_effect,
        quality=quality,
        score=score,
        blockers=blockers,
    )


def arbitrate_fast_route_candidates(
    text: str | None,
    *,
    plan_fast_decision: Any | None = None,
    plan_query_decision: Any | None = None,
    major_intent_decision: Any | None = None,
    major_compare_decision: Any | None = None,
    career_direction_decision: Any | None = None,
) -> FastRouteArbitrationResult:
    """Select one fast-route candidate using quality-first arbitration."""
    prompt = str(text or "")
    candidates: list[FastRouteCandidate] = []

    if _matched(plan_fast_decision):
        action_family = str(_decision_attr(plan_fast_decision, "action_family", "") or "")
        candidates.append(
            _candidate(
                path="plan_fast_route",
                decision=plan_fast_decision,
                scene="plan",
                action_family=action_family,
                side_effect=_plan_side_effect(action_family),
                text=prompt,
            )
        )
    if _matched(plan_query_decision):
        candidates.append(
            _candidate(
                path="plan_query_fast_route",
                decision=plan_query_decision,
                scene="plan",
                action_family="query_volunteer_plan",
                side_effect="readonly",
                text=prompt,
            )
        )
    if _matched(major_intent_decision):
        candidates.append(
            _candidate(
                path="major_intent_fast_route",
                decision=major_intent_decision,
                scene="intent",
                action_family="preview_major_intent",
                side_effect="pending_preview",
                text=prompt,
            )
        )
    if _matched(major_compare_decision):
        candidates.append(
            _candidate(
                path="major_compare_fast_route",
                decision=major_compare_decision,
                scene="explore",
                action_family="compare_majors",
                side_effect="readonly",
                text=prompt,
            )
        )
    if _matched(career_direction_decision):
        candidates.append(
            _candidate(
                path="career_direction_fast_route",
                decision=career_direction_decision,
                scene="explore",
                action_family="analyze_current_career_direction",
                side_effect="readonly",
                text=prompt,
            )
        )

    if not candidates:
        return FastRouteArbitrationResult(candidates=[], fallback_reason="no_fast_route_candidate")

    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return FastRouteArbitrationResult(
            candidates=candidates,
            fallback_reason="quality_gate_blocked_fast_route",
        )

    eligible.sort(key=lambda candidate: (candidate.score, _PATH_PRIORITY[candidate.path]), reverse=True)
    return FastRouteArbitrationResult(selected=eligible[0], candidates=candidates)
