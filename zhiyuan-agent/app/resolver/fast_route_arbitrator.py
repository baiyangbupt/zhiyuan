"""Unified arbitration for high-confidence dialog fast routes.

Fast routers should propose candidates, not independently own the turn.  This
module keeps latency optimizations behind a quality-first gate so ambiguous or
cross-domain user requests can fall back to the full agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal


FastRoutePath = Literal[
    "plan_fast_route",
    "plan_query_fast_route",
    "major_intent_fast_route",
    "major_compare_fast_route",
    "career_direction_fast_route",
    "region_safety_tradeoff_route",
]


_PATH_PRIORITY: dict[FastRoutePath, int] = {
    "plan_fast_route": 90,
    "plan_query_fast_route": 86,
    "major_intent_fast_route": 82,
    "major_compare_fast_route": 80,
    "career_direction_fast_route": 76,
    "region_safety_tradeoff_route": 74,
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
_ARBITRATION_SCORE_GAP_THRESHOLD = 8

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
    fixed_scenario: str = ""
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
            "fixedScenario": self.fixed_scenario,
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
        semantic_needed, semantic_reason = _semantic_arbitration_need(
            selected=self.selected,
            candidates=self.candidates,
            fallback_reason=self.fallback_reason,
        )
        return {
            "source": "fast_route_arbitrator",
            "selectedPath": self.selected_path,
            "selectedFixedScenario": self.selected.fixed_scenario if self.selected is not None else None,
            "fallbackReason": None if self.selected is not None else self.fallback_reason,
            "qualityFirst": True,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "semanticArbitrationNeeded": semantic_needed,
            "semanticArbitrationReason": semantic_reason,
            "semanticArbitrationCandidatePaths": [
                candidate.path for candidate in self.candidates if candidate.eligible
            ],
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


def _semantic_arbitration_need(
    *,
    selected: FastRouteCandidate | None,
    candidates: list[FastRouteCandidate],
    fallback_reason: str,
) -> tuple[bool, str | None]:
    """Decide whether semantic arbitration would be useful.

    This is observability-only.  It does not change the selected route.  The
    actual semantic LLM call remains shadow/non-blocking until route confusion
    data proves it is safer than the deterministic fast-route decision.
    """
    if not candidates:
        return False, None

    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        if fallback_reason == "quality_gate_blocked_fast_route":
            return True, "quality_gate_blocked_all_candidates"
        return False, None

    if selected is None:
        return False, None

    if selected.side_effect == "apply":
        return False, None

    low_confidence = [
        candidate for candidate in eligible
        if candidate.confidence and candidate.confidence != "high"
    ]
    if low_confidence:
        return True, "low_confidence_candidate"

    low_quality = [
        candidate for candidate in eligible
        if candidate.quality and candidate.quality != "high"
    ]
    if low_quality:
        return True, "low_quality_candidate"

    if len(eligible) <= 1:
        return False, None

    sorted_candidates = sorted(
        eligible,
        key=lambda candidate: (candidate.score, _PATH_PRIORITY[candidate.path]),
        reverse=True,
    )
    top, runner_up = sorted_candidates[0], sorted_candidates[1]
    if top.score - runner_up.score <= _ARBITRATION_SCORE_GAP_THRESHOLD:
        return True, "close_fast_route_candidates"

    scenes = {candidate.scene for candidate in eligible}
    if "intent" in scenes and ({"plan", "explore"} & scenes):
        return True, "mixed_intent_plan_or_explore_candidates"

    return False, None


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


def _plan_fixed_scenario(reason: str, action_family: str) -> str:
    by_reason = {
        "numeric_ordered_unit_move": "plan.numeric_ordered_unit_move_preview",
        "numeric_volunteer_move": "plan.numeric_volunteer_move_preview",
        "numeric_ordered_unit_remove": "plan.numeric_ordered_unit_remove_preview",
        "numeric_volunteer_remove": "plan.numeric_volunteer_remove_preview",
        "named_volunteer_move": "plan.named_volunteer_move_preview",
        "named_volunteer_remove": "plan.named_volunteer_remove_preview",
        "named_candidate_add": "plan.named_candidate_add_preview",
        "explicit_sort_dimension": "plan.explicit_sort_preview",
        "plan_safety_status_query": "plan.safety_status_readonly",
        "plan_risk_status_query": "plan.risk_status_readonly",
        "colloquial_adjustment_analysis": "plan.colloquial_adjustment_preview",
        "review_followup_adjustment_preview": "plan.review_issue_adjustment_preview",
        "review_followup_compensation_preview": "plan.review_issue_compensation_preview",
        "explicit_plan_review": "plan.explicit_review_readonly",
        "plan_status_query": "plan.status_overview_readonly",
    }
    if reason in by_reason:
        return by_reason[reason]
    if action_family in _PLAN_PREVIEW_ACTIONS:
        return ""
    if action_family in _PLAN_READONLY_ACTIONS:
        return ""
    return ""


def _plan_query_fixed_scenario(decision: Any, reason: str) -> str:
    if reason != "readonly_plan_candidate_local_query":
        return ""
    scope = str(_decision_attr(decision, "scope", "") or "plan_then_candidate")
    if scope not in {"plan", "candidate", "plan_then_candidate"}:
        scope = "plan_then_candidate"
    return f"plan_query.{scope}_local_lookup_readonly"


def _major_intent_fixed_scenario(decision: Any, reason: str) -> str:
    if reason != "catalog_major_intent":
        return ""
    intents = _decision_attr(decision, "major_intents", {}) or {}
    keys = set(intents.keys()) if isinstance(intents, dict) else set()
    has_negative = any(str(key).startswith("negative_") for key in keys)
    has_positive = any(not str(key).startswith("negative_") for key in keys)
    if has_positive and has_negative:
        return "intent.catalog_major_mixed_preview"
    if has_negative:
        return "intent.catalog_major_constraint_preview"
    return "intent.catalog_major_preference_preview"


def _fixed_scenario_for_candidate(
    *,
    path: FastRoutePath,
    decision: Any,
    action_family: str,
    reason: str,
) -> str:
    if path == "plan_fast_route":
        return _plan_fixed_scenario(reason, action_family)
    if path == "plan_query_fast_route":
        return _plan_query_fixed_scenario(decision, reason)
    if path == "major_intent_fast_route":
        return _major_intent_fixed_scenario(decision, reason)
    if path == "major_compare_fast_route":
        if reason == "exact_level3_major_compare":
            return "major_compare.exact_two_level3_readonly"
        if reason == "exact_three_level3_major_compare":
            return "major_compare.exact_three_level3_readonly"
        return ""
    if path == "career_direction_fast_route":
        return "career_direction.local_taxonomy_readonly_analysis" if reason == "local_career_direction_readonly_analysis" else ""
    if path == "region_safety_tradeoff_route":
        return "region_safety.structured_tradeoff_readonly" if reason == "region_safety_tradeoff_structured_analysis" else ""
    return ""


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
    fixed_scenario = _fixed_scenario_for_candidate(
        path=path,
        decision=decision,
        action_family=action_family,
        reason=reason,
    )
    blockers: list[str] = []
    quality = "high"
    if path == "plan_fast_route":
        blockers.extend(_plan_quality_blockers(text, decision))
    if not fixed_scenario:
        blockers.append("not_high_confidence_fixed_scenario")
    if blockers:
        quality = "insufficient"
    if path == "region_safety_tradeoff_route":
        quality = "high"
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
        fixed_scenario=fixed_scenario,
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
    region_safety_candidate_added = False

    if _matched(plan_fast_decision):
        action_family = str(_decision_attr(plan_fast_decision, "action_family", "") or "")
        plan_candidate = _candidate(
            path="plan_fast_route",
            decision=plan_fast_decision,
            scene="plan",
            action_family=action_family,
            side_effect=_plan_side_effect(action_family),
            text=prompt,
        )
        candidates.append(plan_candidate)
        if "region_safety_tradeoff_needs_full_analysis" in plan_candidate.blockers:
            candidates.append(
                _candidate(
                    path="region_safety_tradeoff_route",
                    decision=SimpleNamespace(
                        matched=True,
                        reason="region_safety_tradeoff_structured_analysis",
                        confidence="high",
                        action_family="analyze_region_safety_tradeoff",
                        user_goal=prompt,
                    ),
                    scene="explore",
                    action_family="analyze_region_safety_tradeoff",
                    side_effect="readonly",
                    text=prompt,
                )
            )
            region_safety_candidate_added = True

    if not region_safety_candidate_added and _is_region_safety_tradeoff_without_plan_scope(prompt):
        candidates.append(
            _candidate(
                path="region_safety_tradeoff_route",
                decision=SimpleNamespace(
                    matched=True,
                    reason="region_safety_tradeoff_structured_analysis",
                    confidence="high",
                    action_family="analyze_region_safety_tradeoff",
                    user_goal=prompt,
                ),
                scene="explore",
                action_family="analyze_region_safety_tradeoff",
                side_effect="readonly",
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
