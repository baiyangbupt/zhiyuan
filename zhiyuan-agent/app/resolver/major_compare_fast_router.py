"""High-confidence readonly major comparison router.

This router only recognizes exact level-3 major names from the local catalog.
Ambiguous names, abbreviations and major-category comparisons still fall back
to the main ChatAgent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.data.major_data import associate_level3_labels, bachelor_level3_labels


_SPACE_RE = re.compile(r"\s+")

_COMPARE_TOKENS = (
    "哪个更适合",
    "哪个适合",
    "哪个更好",
    "哪个好",
    "哪个更稳",
    "哪个更推荐",
    "更适合",
    "更稳妥",
    "怎么选",
    "对比",
    "比较",
    "差异",
)

_INTENT_OR_MUTATION_TOKENS = (
    "记偏好",
    "记成偏好",
    "记下来",
    "记录偏好",
    "加入偏好",
    "写入偏好",
    "按这个改",
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
)

_READONLY_CANCEL_TOKENS = (
    "先只分析",
    "只分析",
    "先分析",
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
)


@dataclass(slots=True)
class MajorCompareFastRouteDecision:
    matched: bool = False
    major_name1: str = ""
    major_name2: str = ""
    reason: str = ""
    confidence: str = ""

    def route_decision(self) -> dict[str, Any]:
        if not self.matched:
            return {
                "source": "major_compare_fast_route",
                "matched": False,
                "confidence": "none",
                "route": "explore",
                "fallbackReason": self.reason or "no_high_confidence_major_compare_pattern",
            }
        return {
            "source": "major_compare_fast_route",
            "matched": True,
            "confidence": self.confidence or "high",
            "route": "explore",
            "actionFamily": "compare_majors",
            "reason": self.reason,
            "majorNames": [self.major_name1, self.major_name2],
        }


def _compact(text: str | None) -> str:
    return _SPACE_RE.sub("", str(text or "").strip())


def _level3_labels_for_batch(batch: str | None) -> set[str]:
    return associate_level3_labels if batch == "02" else bachelor_level3_labels


def _has_intent_or_mutation_token(compact_text: str) -> bool:
    remaining = compact_text
    for token in _READONLY_CANCEL_TOKENS:
        remaining = remaining.replace(token, "")
    return any(token in remaining for token in _INTENT_OR_MUTATION_TOKENS)


def _matched_level3_majors(compact_text: str, labels: set[str]) -> list[str]:
    matches = [label for label in labels if len(label) >= 2 and label in compact_text]
    matches.sort(key=lambda value: (-len(value), compact_text.find(value), value))
    selected: list[str] = []
    occupied_spans: list[tuple[int, int]] = []
    for label in matches:
        start = compact_text.find(label)
        if start < 0:
            continue
        end = start + len(label)
        if end < len(compact_text) and compact_text[end] == "类":
            continue
        if any(not (end <= old_start or start >= old_end) for old_start, old_end in occupied_spans):
            continue
        selected.append(label)
        occupied_spans.append((start, end))
    selected.sort(key=lambda value: compact_text.find(value))
    return selected


def resolve_major_compare_fast_route(
    text: str | None,
    *,
    batch: str | None = None,
) -> MajorCompareFastRouteDecision:
    """Resolve exact two-major readonly comparison requests."""
    compact_text = _compact(text)
    if not compact_text:
        return MajorCompareFastRouteDecision(reason="empty_prompt")
    if not any(token in compact_text for token in _COMPARE_TOKENS):
        return MajorCompareFastRouteDecision(reason="missing_compare_semantics")
    if _has_intent_or_mutation_token(compact_text):
        return MajorCompareFastRouteDecision(reason="intent_or_mutation_semantics")

    majors = _matched_level3_majors(compact_text, _level3_labels_for_batch(batch))
    if len(majors) != 2:
        return MajorCompareFastRouteDecision(reason=f"matched_major_count_{len(majors)}")
    return MajorCompareFastRouteDecision(
        matched=True,
        major_name1=majors[0],
        major_name2=majors[1],
        reason="exact_two_level3_major_compare",
        confidence="high",
    )
