"""High-confidence readonly plan/candidate local query router.

This router only recognizes local lookup questions over the current plan or
candidate pool. It does not generate final replies, create pending actions,
refresh workspace cards, or mutate plans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.data.major_data import (
    associate_level2_labels,
    associate_level3_labels,
    bachelor_level2_labels,
    bachelor_level3_labels,
)
from app.data.school_data import associate_school_set, bachelor_school_set


PlanQueryFastScope = Literal["plan", "candidate", "plan_then_candidate"]

_SPACE_RE = re.compile(r"\s+")

_PLAN_SCOPE_TOKENS = (
    "当前方案",
    "方案里",
    "排序方案",
    "已加入方案",
    "现在这版方案",
    "当前这版方案",
)
_CANDIDATE_SCOPE_TOKENS = (
    "候选里",
    "候选中",
    "候选池",
    "还有什么",
    "还有哪些",
    "还能报",
    "还能选",
    "可选",
    "其他机会",
    "别的机会",
)
_READONLY_QUERY_TOKENS = (
    "有没有",
    "有无",
    "是否有",
    "是不是有",
    "是不是还有",
    "几个",
    "多少",
    "相关",
    "看看",
    "看下",
    "查一下",
    "查下",
    "判断一下",
    "判断下",
)
_MUTATION_TOKENS = (
    "加入方案",
    "加进方案",
    "加到方案",
    "加入志愿",
    "加进志愿",
    "删除",
    "删掉",
    "去掉",
    "移除",
    "移动",
    "移到",
    "挪到",
    "调整到",
    "排序",
    "重排",
    "替换",
    "换成",
    "补齐",
    "补满",
    "补几个",
    "还差",
    "生成方案",
    "重新生成",
    "审查",
    "检查方案",
    "确认",
    "执行",
)
_EXPLORE_OR_SCORE_TOKENS = (
    "哪个更适合",
    "哪个适合",
    "哪个好",
    "哪个更好",
    "怎么选",
    "对比",
    "比较",
    "差异",
    "适不适合",
    "值不值得",
    "体制内",
    "稳定就业",
    "考公",
    "考编",
    "分数线",
    "录取分",
    "近三年",
    "历年",
)
_READONLY_CANCEL_TOKENS = (
    "先不要改方案",
    "不要改方案",
    "不改方案",
    "别改方案",
    "先只分析",
    "只分析",
)


@dataclass(slots=True)
class PlanQueryFastRouteDecision:
    matched: bool = False
    query: str = ""
    scope: PlanQueryFastScope = "plan_then_candidate"
    school_keywords: list[str] = field(default_factory=list)
    major_keywords: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: str = ""

    def tool_args(self) -> dict[str, Any]:
        args: dict[str, Any] = {
            "query": self.query,
            "scope": self.scope,
        }
        if self.school_keywords:
            args["school_keywords"] = list(self.school_keywords)
        if self.major_keywords:
            args["major_keywords"] = list(self.major_keywords)
        if self.school_keywords and self.major_keywords:
            args["match_mode"] = "and"
        return args

    def route_decision(self) -> dict[str, Any]:
        if not self.matched:
            return {
                "source": "plan_query_fast_route",
                "matched": False,
                "confidence": "none",
                "route": "plan",
                "fallbackReason": self.reason or "no_high_confidence_plan_query_pattern",
            }
        return {
            "source": "plan_query_fast_route",
            "matched": True,
            "confidence": self.confidence or "high",
            "route": "plan",
            "actionFamily": "query_volunteer_plan",
            "reason": self.reason,
            "scope": self.scope,
        }


def _compact(text: str | None) -> str:
    return _SPACE_RE.sub("", str(text or "").strip())


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _strip_readonly_cancel_tokens(text: str) -> str:
    stripped = text
    for token in _READONLY_CANCEL_TOKENS:
        stripped = stripped.replace(token, "")
    return stripped


def _has_mutation_semantics(compact_text: str) -> bool:
    return _contains_any(_strip_readonly_cancel_tokens(compact_text), _MUTATION_TOKENS)


def _resolve_scope(compact_text: str) -> PlanQueryFastScope:
    if _contains_any(compact_text, _CANDIDATE_SCOPE_TOKENS):
        return "candidate"
    if _contains_any(compact_text, _PLAN_SCOPE_TOKENS):
        return "plan"
    return "plan_then_candidate"


def _labels_for_batch(batch: str | None) -> tuple[set[str], set[str], set[str]]:
    if batch == "02":
        return associate_school_set, associate_level2_labels, associate_level3_labels
    return bachelor_school_set, bachelor_level2_labels, bachelor_level3_labels


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _find_label_mentions(compact_text: str, labels: set[str]) -> list[str]:
    matches = [label for label in labels if len(label) >= 2 and label in compact_text]
    matches.sort(key=lambda item: (-len(item), compact_text.find(item), item))
    selected: list[str] = []
    occupied_spans: list[tuple[int, int]] = []
    for label in matches:
        start = compact_text.find(label)
        if start < 0:
            continue
        end = start + len(label)
        if any(not (end <= old_start or start >= old_end) for old_start, old_end in occupied_spans):
            continue
        selected.append(label)
        occupied_spans.append((start, end))
    selected.sort(key=lambda item: compact_text.find(item))
    return selected


def _find_major_mentions(compact_text: str, level2_labels: set[str], level3_labels: set[str]) -> list[str]:
    labels = set(level2_labels) | set(level3_labels)
    labels.update(label[:-1] for label in level3_labels if label.endswith("学") and len(label) > 2)
    labels.update(f"{label[:-2]}类" for label in level2_labels if label.endswith("学类") and len(label) > 3)
    return _find_label_mentions(compact_text, labels)


def _query_has_readonly_semantics(compact_text: str, *, has_entity: bool, scope: PlanQueryFastScope) -> bool:
    if _contains_any(compact_text, _READONLY_QUERY_TOKENS):
        return True
    if scope != "plan_then_candidate" and has_entity:
        return True
    return False


def resolve_plan_query_fast_route(
    text: str | None,
    *,
    batch: str | None = None,
) -> PlanQueryFastRouteDecision:
    """Resolve readonly local plan/candidate lookup requests."""
    original = str(text or "").strip()
    compact_text = _compact(original)
    if not compact_text:
        return PlanQueryFastRouteDecision(reason="empty_prompt")
    if _has_mutation_semantics(compact_text):
        return PlanQueryFastRouteDecision(reason="mutation_semantics")
    if _contains_any(compact_text, _EXPLORE_OR_SCORE_TOKENS):
        return PlanQueryFastRouteDecision(reason="explore_or_score_semantics")

    scope = _resolve_scope(compact_text)
    school_labels, level2_labels, level3_labels = _labels_for_batch(batch)
    school_keywords: list[str] = []
    major_keywords: list[str] = []

    for school in _find_label_mentions(compact_text, school_labels):
        _append_unique(school_keywords, school)

    major_lookup_text = compact_text
    for school in school_keywords:
        major_lookup_text = major_lookup_text.replace(school, " " * len(school))
    for major in _find_major_mentions(major_lookup_text, level2_labels, level3_labels):
        _append_unique(major_keywords, major)

    has_entity = bool(school_keywords or major_keywords)
    if not _query_has_readonly_semantics(compact_text, has_entity=has_entity, scope=scope):
        return PlanQueryFastRouteDecision(reason="missing_readonly_query_semantics")
    if scope == "plan_then_candidate" and not has_entity:
        return PlanQueryFastRouteDecision(reason="missing_local_query_entity")

    return PlanQueryFastRouteDecision(
        matched=True,
        query=original,
        scope=scope,
        school_keywords=school_keywords,
        major_keywords=major_keywords,
        reason="readonly_plan_candidate_local_query",
        confidence="high",
    )
