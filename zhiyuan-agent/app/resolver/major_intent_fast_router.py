"""High-confidence major intent preview router.

This router only turns explicit catalog-backed major preference / exclusion
utterances into structured intent-preview input. It does not generate a final
reply, apply preferences, refresh candidates, or mutate plans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.data.major_data import (
    associate_level2_labels,
    associate_level3_labels,
    bachelor_level2_labels,
    bachelor_level3_labels,
)


_SPACE_RE = re.compile(r"\s+")

_COMPARE_OR_READONLY_TOKENS = (
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
    "只分析",
    "先分析",
    "先只分析",
    "不要记偏好",
    "不记偏好",
    "别记偏好",
    "不要记下来",
    "不记下来",
    "别记下来",
)

_PLAN_MUTATION_TOKENS = (
    "改方案",
    "调整方案",
    "加入方案",
    "加进方案",
    "加到方案",
    "加入志愿",
    "加进志愿",
    "加到志愿",
    "删除志愿",
    "删掉志愿",
    "移动",
    "移到",
    "排序",
    "重排",
)

_POSITIVE_INTENT_TOKENS = (
    "倾向",
    "偏好",
    "喜欢",
    "想学",
    "想读",
    "想报",
    "优先看",
    "优先考虑",
    "优先",
    "重点看",
    "记成偏好",
    "记偏好",
    "记录偏好",
    "加入偏好",
    "作为偏好",
    "考虑",
    "可以",
)

_NEGATIVE_INTENT_TOKENS = (
    "不要",
    "别要",
    "不想",
    "不考虑",
    "不看",
    "不选",
    "不报",
    "排除",
    "避开",
    "别选",
    "别报",
    "尽量避开",
)

_CLAUSE_SEPARATORS = "，,。.!！?？；;、但"

_QUESTION_TOKENS = ("可以吗", "可不可以", "能不能", "行不行", "好吗", "好不好")

_HIGH_CONFIDENCE_MAJOR_ABBREVIATIONS: dict[str, str] = {
    "土木": "土木工程",
}


@dataclass(slots=True)
class _MajorMention:
    level: str
    name: str
    surface: str
    start: int
    end: int


@dataclass(slots=True)
class MajorIntentFastRouteDecision:
    matched: bool = False
    major_intents: dict[str, list[str]] = field(default_factory=dict)
    intent_mode: str = "preference"
    reason: str = ""
    confidence: str = ""

    def route_decision(self) -> dict[str, Any]:
        if not self.matched:
            return {
                "source": "major_intent_fast_route",
                "matched": False,
                "confidence": "none",
                "route": "intent",
                "fallbackReason": self.reason or "no_high_confidence_major_intent_pattern",
            }
        return {
            "source": "major_intent_fast_route",
            "matched": True,
            "confidence": self.confidence or "high",
            "route": "intent",
            "actionFamily": "preview_major_intent",
            "reason": self.reason,
            "intentMode": self.intent_mode,
            "majorIntents": self.major_intents,
        }


def _compact(text: str | None) -> str:
    return _SPACE_RE.sub("", str(text or "").strip())


def _labels_for_batch(batch: str | None) -> tuple[set[str], set[str]]:
    if batch == "02":
        return associate_level2_labels, associate_level3_labels
    return bachelor_level2_labels, bachelor_level3_labels


def _build_surface_map(labels: set[str], *, level: str) -> dict[str, str]:
    surfaces: dict[str, list[str]] = {}
    for label in labels:
        if len(label) < 2:
            continue
        surfaces.setdefault(label, []).append(label)
        if level == "level3" and label.endswith("学") and len(label) > 2:
            surfaces.setdefault(label[:-1], []).append(label)
        if level == "level3":
            alias = label.replace("电子商务", "电商")
            if alias != label:
                surfaces.setdefault(alias, []).append(label)
        if level == "level2" and label.endswith("学类") and len(label) > 3:
            surfaces.setdefault(f"{label[:-2]}类", []).append(label)

    surface_map = {
        surface: standards[0]
        for surface, standards in surfaces.items()
        if len(set(standards)) == 1
    }
    if level == "level3":
        for surface, standard in _HIGH_CONFIDENCE_MAJOR_ABBREVIATIONS.items():
            if standard in labels:
                surface_map.setdefault(surface, standard)
    return surface_map


def _find_mentions(compact_text: str, *, batch: str | None) -> list[_MajorMention]:
    level2_labels, level3_labels = _labels_for_batch(batch)
    surface_entries: list[tuple[str, str, str]] = []
    surface_entries.extend(
        (surface, standard, "level2")
        for surface, standard in _build_surface_map(level2_labels, level="level2").items()
    )
    surface_entries.extend(
        (surface, standard, "level3")
        for surface, standard in _build_surface_map(level3_labels, level="level3").items()
    )
    surface_entries.sort(key=lambda item: (-len(item[0]), item[2], item[0]))

    mentions: list[_MajorMention] = []
    occupied_spans: list[tuple[int, int]] = []
    for surface, standard, level in surface_entries:
        search_from = 0
        while True:
            start = compact_text.find(surface, search_from)
            if start < 0:
                break
            end = start + len(surface)
            search_from = start + 1
            if level == "level3" and end < len(compact_text) and compact_text[end] == "类":
                continue
            if any(not (end <= old_start or start >= old_end) for old_start, old_end in occupied_spans):
                continue
            mentions.append(
                _MajorMention(
                    level=level,
                    name=standard,
                    surface=surface,
                    start=start,
                    end=end,
                )
            )
            occupied_spans.append((start, end))

    mentions.sort(key=lambda item: (item.start, -(item.end - item.start), item.name))
    return mentions


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _clause_for_mention(compact_text: str, mention: _MajorMention) -> str:
    start = mention.start
    while start > 0 and compact_text[start - 1] not in _CLAUSE_SEPARATORS:
        start -= 1
    end = mention.end
    while end < len(compact_text) and compact_text[end] not in _CLAUSE_SEPARATORS:
        end += 1
    return compact_text[start:end]


def _append_unique(bucket: list[str], value: str) -> None:
    if value and value not in bucket:
        bucket.append(value)


def _nearest_token_distance(text: str, mention: _MajorMention, tokens: tuple[str, ...]) -> int | None:
    distances: list[int] = []
    for token in tokens:
        search_from = 0
        while True:
            pos = text.find(token, search_from)
            if pos < 0:
                break
            search_from = pos + 1
            if pos >= mention.end:
                distances.append(pos - mention.end)
            else:
                distances.append(mention.start - (pos + len(token)))
    return min(distances) if distances else None


def resolve_major_intent_fast_route(
    text: str | None,
    *,
    batch: str | None = None,
) -> MajorIntentFastRouteDecision:
    """Resolve explicit major preference / exclusion requests."""
    compact_text = _compact(text)
    if not compact_text:
        return MajorIntentFastRouteDecision(reason="empty_prompt")
    if _contains_any(compact_text, _COMPARE_OR_READONLY_TOKENS):
        return MajorIntentFastRouteDecision(reason="readonly_or_compare_semantics")
    if _contains_any(compact_text, _QUESTION_TOKENS):
        return MajorIntentFastRouteDecision(reason="readonly_question_semantics")
    if _contains_any(compact_text, _PLAN_MUTATION_TOKENS):
        return MajorIntentFastRouteDecision(reason="plan_mutation_semantics")
    if not _contains_any(compact_text, _POSITIVE_INTENT_TOKENS + _NEGATIVE_INTENT_TOKENS):
        return MajorIntentFastRouteDecision(reason="missing_explicit_intent_semantics")

    mentions = _find_mentions(compact_text, batch=batch)
    if not mentions:
        return MajorIntentFastRouteDecision(reason="no_catalog_major_match")

    major_intents: dict[str, list[str]] = {}
    for mention in mentions:
        clause = _clause_for_mention(compact_text, mention)
        is_negative = _contains_any(clause, _NEGATIVE_INTENT_TOKENS)
        is_positive = _contains_any(clause, _POSITIVE_INTENT_TOKENS)
        if is_negative and is_positive:
            negative_distance = _nearest_token_distance(compact_text, mention, _NEGATIVE_INTENT_TOKENS)
            positive_distance = _nearest_token_distance(compact_text, mention, _POSITIVE_INTENT_TOKENS)
            if negative_distance is not None and positive_distance is not None:
                is_negative = negative_distance <= positive_distance
                is_positive = positive_distance < negative_distance
        if not is_negative and not is_positive:
            continue
        key = f"negative_{mention.level}" if is_negative else mention.level
        _append_unique(major_intents.setdefault(key, []), mention.name)

    if not major_intents:
        return MajorIntentFastRouteDecision(reason="no_major_with_local_intent_semantics")

    intent_mode = "constraint" if any(key.startswith("negative_") for key in major_intents) else "preference"
    return MajorIntentFastRouteDecision(
        matched=True,
        major_intents=major_intents,
        intent_mode=intent_mode,
        reason="catalog_major_intent",
        confidence="high",
    )
