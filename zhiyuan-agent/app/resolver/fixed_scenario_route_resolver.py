"""Validate LLM fixed-scenario router output before fast-route execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.major_data import (
    associate_level2_labels,
    associate_level3_labels,
    bachelor_level2_labels,
    bachelor_level3_labels,
)
from app.domain.career_slots import CAREER_SLOT_VALUES, normalize_career_slots
from app.models.semantic_router import FixedScenarioRouteFrame, FixedScenarioRouteResult
from app.resolver.career_direction_fast_router import CareerDirectionFastRouteDecision
from app.resolver.major_compare_fast_router import MajorCompareFastRouteDecision
from app.resolver.major_intent_fast_router import MajorIntentFastRouteDecision
from app.util.code_enrichment import _resolve_local_major_name_alias


@dataclass(slots=True)
class FixedScenarioResolvedRoutes:
    major_intent_decision: MajorIntentFastRouteDecision | None = None
    major_compare_decision: MajorCompareFastRouteDecision | None = None
    career_direction_decision: CareerDirectionFastRouteDecision | None = None
    route_decision: dict[str, Any] | None = None


def resolve_fixed_scenario_routes(
    route_result: FixedScenarioRouteResult | None,
    *,
    batch: str | None = None,
    min_confidence: float = 0.82,
) -> FixedScenarioResolvedRoutes:
    """Convert a high-confidence fixed-scenario LLM frame into local decisions.

    The LLM frame is treated as an untrusted classifier.  It may only create
    fast-route candidates after local catalog/taxonomy validation succeeds.
    """
    if route_result is None or not route_result.enabled:
        return FixedScenarioResolvedRoutes(route_decision={"enabled": False, "status": "disabled"})
    route_decision: dict[str, Any] = {
        "enabled": True,
        "status": route_result.status,
        "durationMs": route_result.durationMs,
        "promptChars": route_result.promptChars,
    }
    if route_result.status != "success" or route_result.frame is None:
        route_decision.update(
            {
                "selectedFixedScenario": None,
                "fallbackReason": route_result.errorType or route_result.status,
                "errorMessage": route_result.errorMessage[:200] if route_result.errorMessage else "",
            }
        )
        return FixedScenarioResolvedRoutes(route_decision=route_decision)

    frame = route_result.frame
    route_decision.update(
        {
            "source": "fixed_scenario_llm_router",
            "fixedScenario": frame.fixedScenario,
            "sideEffect": frame.sideEffect,
            "confidence": frame.confidence,
            "ambiguity": list(frame.ambiguity),
            "missingInfo": list(frame.missingInfo),
            "mustFallbackReason": frame.mustFallbackReason,
            "reason": frame.reason,
        }
    )
    blocker = _frame_blocker(frame, min_confidence=min_confidence)
    if blocker:
        route_decision.update({"selectedFixedScenario": None, "fallbackReason": blocker})
        return FixedScenarioResolvedRoutes(route_decision=route_decision)

    if frame.fixedScenario == "major_compare.readonly":
        decision, reason = _resolve_major_compare(frame, batch=batch)
        route_decision.update({"selectedFixedScenario": frame.fixedScenario, "fallbackReason": reason})
        return FixedScenarioResolvedRoutes(
            major_compare_decision=decision,
            route_decision=route_decision,
        )

    if frame.fixedScenario == "major_intent.preview":
        decision, reason = _resolve_major_intent(frame, batch=batch)
        route_decision.update({"selectedFixedScenario": frame.fixedScenario, "fallbackReason": reason})
        return FixedScenarioResolvedRoutes(
            major_intent_decision=decision,
            route_decision=route_decision,
        )

    if frame.fixedScenario == "career_direction.readonly":
        decision, reason = _resolve_career_direction(frame)
        route_decision.update({"selectedFixedScenario": frame.fixedScenario, "fallbackReason": reason})
        return FixedScenarioResolvedRoutes(
            career_direction_decision=decision,
            route_decision=route_decision,
        )

    route_decision.update({"selectedFixedScenario": None, "fallbackReason": "no_fixed_scenario"})
    return FixedScenarioResolvedRoutes(route_decision=route_decision)


def _frame_blocker(frame: FixedScenarioRouteFrame, *, min_confidence: float) -> str:
    if frame.fixedScenario == "none":
        return frame.mustFallbackReason or "no_fixed_scenario"
    if frame.sideEffect == "apply":
        return "apply_side_effect_not_allowed"
    if frame.confidence < min_confidence:
        return "low_confidence"
    if frame.ambiguity:
        return "ambiguous_fixed_scenario"
    if frame.missingInfo:
        return "missing_fixed_scenario_info"
    if frame.mustFallbackReason:
        return frame.mustFallbackReason
    return ""


def _label_sets(batch: str | None) -> tuple[set[str], set[str]]:
    if batch == "02":
        return associate_level2_labels, associate_level3_labels
    return bachelor_level2_labels, bachelor_level3_labels


def _resolve_major_name(name: str, labels: set[str]) -> str | None:
    cleaned = str(name or "").strip()
    if not cleaned:
        return None
    if cleaned in labels:
        return cleaned
    return _resolve_local_major_name_alias(cleaned, {label: label for label in labels})


def _resolve_major_names(names: list[str], labels: set[str]) -> list[str]:
    resolved: list[str] = []
    for name in names:
        value = _resolve_major_name(name, labels)
        if value and value not in resolved:
            resolved.append(value)
    return resolved


def _resolve_major_compare(
    frame: FixedScenarioRouteFrame,
    *,
    batch: str | None,
) -> tuple[MajorCompareFastRouteDecision | None, str | None]:
    if frame.sideEffect != "readonly":
        return None, "major_compare_requires_readonly"
    _, level3_labels = _label_sets(batch)
    major_names = _resolve_major_names(frame.entities.majorNames, level3_labels)
    if len(major_names) not in {2, 3}:
        return None, f"validated_major_count_{len(major_names)}"
    reason = "exact_level3_major_compare" if len(major_names) == 2 else "exact_three_level3_major_compare"
    return (
        MajorCompareFastRouteDecision(
            matched=True,
            major_name1=major_names[0],
            major_name2=major_names[1],
            major_names=major_names,
            reason=reason,
            confidence="high",
        ),
        None,
    )


def _resolve_major_intent(
    frame: FixedScenarioRouteFrame,
    *,
    batch: str | None,
) -> tuple[MajorIntentFastRouteDecision | None, str | None]:
    if frame.sideEffect != "preview":
        return None, "major_intent_requires_preview"
    level2_labels, level3_labels = _label_sets(batch)
    positive = _build_intent_buckets(frame.entities.positiveMajorNames, level2_labels, level3_labels)
    negative = _build_intent_buckets(frame.entities.negativeMajorNames, level2_labels, level3_labels)
    major_intents: dict[str, list[str]] = {}
    if positive["level2"]:
        major_intents["level2"] = positive["level2"]
    if positive["level3"]:
        major_intents["level3"] = positive["level3"]
    if negative["level2"]:
        major_intents["negative_level2"] = negative["level2"]
    if negative["level3"]:
        major_intents["negative_level3"] = negative["level3"]
    if not major_intents:
        return None, "no_validated_major_intent_entities"
    intent_mode = "constraint" if any(key.startswith("negative_") for key in major_intents) else "preference"
    return (
        MajorIntentFastRouteDecision(
            matched=True,
            major_intents=major_intents,
            intent_mode=intent_mode,
            reason="catalog_major_intent",
            confidence="high",
        ),
        None,
    )


def _build_intent_buckets(
    names: list[str],
    level2_labels: set[str],
    level3_labels: set[str],
) -> dict[str, list[str]]:
    buckets = {"level2": [], "level3": []}
    for name in names:
        level2 = _resolve_major_name(name, level2_labels)
        if level2:
            if level2 not in buckets["level2"]:
                buckets["level2"].append(level2)
            continue
        level3 = _resolve_major_name(name, level3_labels)
        if level3 and level3 not in buckets["level3"]:
            buckets["level3"].append(level3)
    return buckets


def _resolve_career_direction(
    frame: FixedScenarioRouteFrame,
) -> tuple[CareerDirectionFastRouteDecision | None, str | None]:
    if frame.sideEffect != "readonly":
        return None, "career_direction_requires_readonly"
    slots = normalize_career_slots(frame.entities.careerDirections)
    if not slots:
        label_to_slot = {
            "体制内": "system_public_service",
            "考公": "system_public_service",
            "考编": "system_public_service",
            "稳定就业": "stable_employment",
            "稳定": "stable_employment",
            "读研": "further_study",
            "考研": "further_study",
            "深造": "further_study",
        }
        slots = normalize_career_slots([label_to_slot.get(value, value) for value in frame.entities.careerDirections])
    if not slots or any(slot not in CAREER_SLOT_VALUES for slot in slots):
        return None, "no_validated_career_direction_slot"
    return (
        CareerDirectionFastRouteDecision(
            matched=True,
            direction_slots=slots,
            reason="local_career_direction_readonly_analysis",
            confidence="high",
        ),
        None,
    )
