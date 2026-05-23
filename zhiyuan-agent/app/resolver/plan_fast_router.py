"""High-confidence Plan fast router.

This module only recognizes tightly structured, low-ambiguity plan requests.
It does not generate user-facing replies and never applies mutating actions
directly; matched mutations still go through Plan preview and confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_MOVE_ORDERED_UNIT_RE = re.compile(
    r"把第(\d+)(?:个)?(?:专业组|志愿组|组)(?:移到|移动到|挪到|调整到|改到|放到)第(\d+)(?:个)?(?:专业组|位置|位|组)?"
)
_MOVE_UNIT_RE = re.compile(
    r"把第(\d+)(?:个|条)?志愿(?:移到|移动到|挪到|调整到|改到|放到)第(\d+)(?:个|条)?(?:志愿|位置|位)?"
)
_REMOVE_ORDERED_UNIT_RE = re.compile(r"(?:删除|删掉|去掉|移除)第(\d+)(?:个)?(?:专业组|志愿组|组)")
_REMOVE_UNIT_RE = re.compile(r"(?:删除|删掉|去掉|移除)第(\d+)(?:个|条)?志愿")

_PLAN_STATUS_PATTERNS = (
    "看看现在的方案",
    "看看当前方案",
    "当前方案怎么样",
    "现在方案怎么样",
    "方案怎么样",
    "方案情况",
    "方案有了么",
    "方案有了吗",
)

_SORT_DIMENSIONS = {
    "录取率": "admissionRatio",
    "院校层次": "schoolRank",
    "学校层次": "schoolRank",
    "院校排名": "schoolRank",
    "学校排名": "schoolRank",
    "推荐系数": "finalScore",
    "推荐分": "finalScore",
}


@dataclass(slots=True)
class PlanFastRouteDecision:
    matched: bool = False
    action_family: str = ""
    user_goal: str = ""
    reason: str = ""
    confidence: str = ""
    volunteer_ids: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)
    source_position: int | None = None
    target_position: int | None = None

    def route_decision(self) -> dict[str, Any]:
        if not self.matched:
            return {
                "source": "plan_fast_route",
                "matched": False,
                "confidence": "none",
                "route": "plan",
                "fallbackReason": self.reason or "no_high_confidence_plan_pattern",
            }
        return {
            "source": "plan_fast_route",
            "matched": True,
            "confidence": self.confidence or "high",
            "route": "plan",
            "actionFamily": self.action_family,
            "reason": self.reason,
        }


def _compact(text: str | None) -> str:
    return _SPACE_RE.sub("", str(text or "").strip())


def _looks_like_sort_request(compact_text: str) -> bool:
    if not any(token in compact_text for token in ("排序", "重排", "排一下", "排一排")):
        return False
    return any(token in compact_text for token in _SORT_DIMENSIONS)


def _looks_like_review_request(compact_text: str) -> bool:
    if "审查" not in compact_text and "检查" not in compact_text:
        return False
    return "方案" in compact_text or len(compact_text) <= 10


def _looks_like_status_request(compact_text: str) -> bool:
    if any(pattern in compact_text for pattern in _PLAN_STATUS_PATTERNS):
        return True
    return (
        "方案" in compact_text
        and any(token in compact_text for token in ("结构化", "结论", "情况", "状态", "概览"))
        and not any(token in compact_text for token in ("排序", "移动", "删除", "去掉", "加入", "加进", "审查", "检查"))
    )


def resolve_plan_fast_route(text: str | None) -> PlanFastRouteDecision:
    """Resolve a high-confidence plan request without invoking the main model."""
    original = str(text or "").strip()
    compact_text = _compact(original)
    if not compact_text:
        return PlanFastRouteDecision(reason="empty_prompt")

    if match := _MOVE_ORDERED_UNIT_RE.search(compact_text):
        source_position = int(match.group(1))
        target_position = int(match.group(2))
        return PlanFastRouteDecision(
            matched=True,
            action_family="move_ordered_unit",
            user_goal=original,
            reason="numeric_ordered_unit_move",
            confidence="high",
            source_position=source_position,
            target_position=target_position,
        )

    if match := _MOVE_UNIT_RE.search(compact_text):
        source_position = int(match.group(1))
        target_position = int(match.group(2))
        return PlanFastRouteDecision(
            matched=True,
            action_family="move_unit",
            user_goal=original,
            reason="numeric_volunteer_move",
            confidence="high",
            volunteer_ids=[f"@{source_position}"],
            source_position=source_position,
            target_position=target_position,
        )

    if match := _REMOVE_ORDERED_UNIT_RE.search(compact_text):
        source_position = int(match.group(1))
        return PlanFastRouteDecision(
            matched=True,
            action_family="remove_ordered_unit",
            user_goal=original,
            reason="numeric_ordered_unit_remove",
            confidence="high",
            source_position=source_position,
        )

    if match := _REMOVE_UNIT_RE.search(compact_text):
        source_position = int(match.group(1))
        return PlanFastRouteDecision(
            matched=True,
            action_family="remove_units",
            user_goal=original,
            reason="numeric_volunteer_remove",
            confidence="high",
            volunteer_ids=[f"@{source_position}"],
            source_position=source_position,
        )

    if _looks_like_sort_request(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="sort_ordered_plan",
            user_goal=original,
            reason="explicit_sort_dimension",
            confidence="high",
        )

    if _looks_like_review_request(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="review_plan",
            user_goal=original,
            reason="explicit_plan_review",
            confidence="high",
        )

    if _looks_like_status_request(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="query_state",
            user_goal=original,
            reason="plan_status_query",
            confidence="high",
        )

    return PlanFastRouteDecision(reason="no_high_confidence_plan_pattern")
