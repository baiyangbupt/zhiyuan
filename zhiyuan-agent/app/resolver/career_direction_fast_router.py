"""High-confidence readonly career-direction analysis router.

This router only recognizes explicit readonly career-direction asks that can
be resolved by the local career taxonomy. Intent writing and plan mutations
still fall back to the main ChatAgent and confirmation flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.career_slots import resolve_career_slots_locally, to_career_labels


_SPACE_RE = re.compile(r"\s+")

_STRONG_READONLY_ANALYSIS_TOKENS = (
    "承接",
    "适不适合",
    "适合",
    "合适",
    "分析",
    "匹配",
    "对照",
)

_PLAN_CONTEXT_TOKENS = (
    "当前方案",
    "现在方案",
    "方案",
)

_WEAK_ANALYSIS_TOKENS = (
    "怎么样",
    "怎么",
    "看看",
    "看一下",
)

_GENERIC_DIRECTION_PATTERNS = (
    "适合什么方向",
    "适合哪些方向",
    "适合哪个方向",
    "适合什么专业方向",
    "适合哪些专业方向",
    "什么方向适合我",
    "哪些方向适合我",
    "往哪条路",
    "走哪条路",
)

_INTENT_OR_MUTATION_TOKENS = (
    "记偏好",
    "记成偏好",
    "记下来",
    "记录下来",
    "记录偏好",
    "作为偏好",
    "加入偏好",
    "写入偏好",
    "以后优先",
    "后续优先",
    "优先按",
    "按这个改",
    "按这个方向改",
    "按体制内",
    "按稳定就业",
    "按读研",
    "改方案",
    "调整方案",
    "加进方案",
    "加入方案",
    "加到方案",
    "删掉",
    "删除",
    "去掉",
    "移动",
    "移到",
    "排序",
    "重排",
    "确认",
)

_READONLY_CANCEL_TOKENS = (
    "先只分析",
    "只分析",
    "先分析",
    "先看看",
    "不要记偏好",
    "不记偏好",
    "别记偏好",
    "不要记下来",
    "不记下来",
    "别记下来",
    "不要改方案",
    "不改方案",
    "别改方案",
    "先不要改方案",
    "不要调整方案",
    "不调整方案",
    "别调整方案",
)


@dataclass(slots=True)
class CareerDirectionFastRouteDecision:
    matched: bool = False
    direction_slots: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: str = ""

    def route_decision(self) -> dict[str, Any]:
        if not self.matched:
            return {
                "source": "career_direction_fast_route",
                "matched": False,
                "confidence": "none",
                "route": "explore",
                "fallbackReason": self.reason or "no_high_confidence_career_direction_pattern",
            }
        return {
            "source": "career_direction_fast_route",
            "matched": True,
            "confidence": self.confidence or "high",
            "route": "explore",
            "actionFamily": "analyze_current_career_direction",
            "reason": self.reason,
            "directionSlots": list(self.direction_slots),
            "directionLabels": to_career_labels(self.direction_slots),
        }


def _compact(text: str | None) -> str:
    return _SPACE_RE.sub("", str(text or "").strip())


def _has_readonly_analysis_semantics(compact_text: str) -> bool:
    if any(token in compact_text for token in _STRONG_READONLY_ANALYSIS_TOKENS):
        return True
    return (
        any(token in compact_text for token in _PLAN_CONTEXT_TOKENS)
        and any(token in compact_text for token in _WEAK_ANALYSIS_TOKENS)
    )


def _is_generic_direction_question(compact_text: str) -> bool:
    return any(pattern in compact_text for pattern in _GENERIC_DIRECTION_PATTERNS)


def _has_intent_or_mutation_token(compact_text: str) -> bool:
    remaining = compact_text
    for token in _READONLY_CANCEL_TOKENS:
        remaining = remaining.replace(token, "")
    return any(token in remaining for token in _INTENT_OR_MUTATION_TOKENS)


def resolve_career_direction_fast_route(text: str | None) -> CareerDirectionFastRouteDecision:
    """Resolve high-confidence readonly career-direction analysis requests."""
    compact_text = _compact(text)
    if not compact_text:
        return CareerDirectionFastRouteDecision(reason="empty_prompt")
    if _is_generic_direction_question(compact_text):
        return CareerDirectionFastRouteDecision(reason="generic_direction_question")
    if not _has_readonly_analysis_semantics(compact_text):
        return CareerDirectionFastRouteDecision(reason="missing_readonly_analysis_semantics")
    if _has_intent_or_mutation_token(compact_text):
        return CareerDirectionFastRouteDecision(reason="intent_or_mutation_semantics")

    direction_slots = resolve_career_slots_locally(compact_text)
    if not direction_slots:
        return CareerDirectionFastRouteDecision(reason="no_local_career_direction_slot")
    return CareerDirectionFastRouteDecision(
        matched=True,
        direction_slots=direction_slots,
        reason="local_career_direction_readonly_analysis",
        confidence="high",
    )
