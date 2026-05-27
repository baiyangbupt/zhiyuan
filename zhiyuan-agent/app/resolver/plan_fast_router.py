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
    r"把第(\d+)(?:个)?(?:专业组|志愿组|组)(?:往前|往后)?(?:移到|移动到|挪到|调整到|改到|放到)第(\d+)(?:个)?(?:专业组|位置|位|组)?"
)
_MOVE_UNIT_RE = re.compile(
    r"把第(\d+)(?:个|条)?志愿(?:往前|往后)?(?:移到|移动到|挪到|调整到|改到|放到)第(\d+)(?:个|条)?(?:志愿|位置|位)?"
)
_REMOVE_ORDERED_UNIT_RE = re.compile(r"(?:删除|删掉|去掉|移除)第(\d+)(?:个)?(?:专业组|志愿组|组)")
_REMOVE_UNIT_RE = re.compile(r"(?:删除|删掉|去掉|移除)第(\d+)(?:个|条)?志愿")
_MOVE_NAMED_UNIT_RE = re.compile(
    r"把(.+?)(?:往前|往后)?(?:移到|移动到|挪到|调整到|改到|放到)第(\d+)(?:个|条)?(?:志愿|位置|位)?"
)
_REMOVE_NAMED_UNIT_PREFIX_RE = re.compile(r"^(?:删除|删掉|去掉|移除)(.+)$")
_REMOVE_NAMED_UNIT_SUFFIX_RE = re.compile(r"^把(.+?)(?:删除|删掉|去掉|移除)$")
_ADD_NAMED_UNIT_RE = re.compile(
    r"^(?:把)?(.+?)(?:如果在候选里|若在候选里|在候选里)?[，,。；;]*(?:就)?(?:加入方案|加入当前方案|加进方案|加到方案|加入志愿|加进志愿|加到志愿|加进来|加入进来)$"
)

_PLAN_STATUS_PATTERNS = (
    "看看现在的方案",
    "看看当前方案",
    "当前方案怎么样",
    "现在方案怎么样",
    "方案怎么样",
    "方案咋样",
    "这方案咋样",
    "这个方案咋样",
    "这套方案咋样",
    "这版咋样",
    "这个方案好不好",
    "这套方案好不好",
    "方案情况",
    "方案有了么",
    "方案有了吗",
)

_PLAN_RISK_STATUS_ANCHORS = (
    "方案",
    "志愿",
    "排序",
    "这版",
    "这个方案",
    "当前",
    "现在",
    "分数",
    "北京",
    "天津",
)

_PLAN_RISK_STATUS_TOKENS = (
    "太冲",
    "冲太多",
    "冲得多",
    "冲多了",
    "风险大",
    "风险高",
    "风险",
    "稳不稳",
    "够不够稳",
    "够稳",
    "安全吗",
    "安全不安全",
    "说人话",
    "看不懂",
    "靠谱吗",
    "靠不靠谱",
    "冒险",
    "太冒险",
    "预算",
    "学费",
    "中外合作",
)

_PLAN_RISK_STATUS_MUTATION_TOKENS = (
    "改",
    "调整",
    "优化",
    "移动",
    "删除",
    "去掉",
    "加入",
    "加进",
    "补齐",
    "补满",
    "执行",
    "确认",
    "按",
    "排序",
    "重排",
)

_PLAN_RISK_STATUS_READONLY_CANCEL_TOKENS = (
    "先别改",
    "别改",
    "不要改",
    "不改",
    "先别动",
    "别动",
    "不要动",
    "先不动",
)

_REVIEW_FOLLOWUP_STRONG_CONTEXT_TOKENS = (
    "最严重",
    "审查",
    "风险",
    "提醒",
    "本省保底",
    "保底不足",
    "保底不够",
    "冲稳保",
    "缺口",
    "数量不足",
    "数量缺口",
    "断层",
    "倒挂",
    "限报",
    "高收费",
    "中外合作",
    "专项",
    "托底",
    "安全垫",
    "边缘分",
)

_REVIEW_FOLLOWUP_WEAK_CONTEXT_TOKENS = (
    "问题",
    "优先",
    "保底",
)

_REVIEW_FOLLOWUP_ANCHOR_TOKENS = (
    "针对",
    "刚才",
    "上面",
    "上述",
    "这个",
    "当前",
    "解决",
    "处理",
)

_ADJUSTMENT_PREVIEW_TOKENS = (
    "调整预览",
    "调整建议",
    "优化建议",
    "处理建议",
    "解决建议",
    "补齐预览",
    "补满预览",
    "先给预览",
    "给我预览",
    "先给我一版",
    "给我一版",
    "预览",
    "怎么调",
    "怎么调整",
    "怎么优化",
    "怎么处理",
    "怎么解决",
)

_COLLOQUIAL_ADJUSTMENT_ANCHORS = (
    "方案",
    "这版",
    "当前",
    "现在",
)

_COLLOQUIAL_ADJUSTMENT_TOKENS = (
    "调稳",
    "稳点",
    "稳一点",
    "更稳",
    "别太冒险",
    "降低风险",
    "不冒险",
)

_ADJUSTMENT_PREVIEW_BOUNDARY_TOKENS = (
    "先给我看看会怎么动",
    "先看看会怎么动",
    "看看会怎么动",
    "看会怎么动",
    "先给我看会怎么动",
    "先给我看看",
    "先看看",
    "先看下",
    "预览",
)

_COMPENSATION_PREVIEW_TOKENS = (
    "补齐",
    "补满",
    "补稳",
    "差几个",
    "数量缺口",
    "数量不足",
    "保底",
    "本省保底",
    "兜底",
)

_SORT_DIMENSIONS = {
    "录取率": "admissionRatio",
    "院校层次": "schoolRank",
    "学校层次": "schoolRank",
    "院校排名": "schoolRank",
    "学校排名": "schoolRank",
    "好学校": "schoolRank",
    "推荐系数": "finalScore",
    "推荐分": "finalScore",
}

_NAMED_MUTATION_BLOCK_TOKENS = (
    "不要改方案",
    "不改方案",
    "别改方案",
    "先只分析",
    "只分析",
    "看看",
    "看下",
    "有没有",
    "是否",
    "是不是",
    "对比",
    "比较",
    "怎么选",
    "哪个更",
    "哪个好",
    "分数线",
    "录取分",
    "近三年",
    "历年",
    "审查",
    "检查",
    "排序",
    "重排",
    "替换",
    "换成",
    "补齐",
    "补满",
    "补几个",
    "再补",
    "然后",
    "偏好",
    "意向",
)

_GENERIC_NAMED_REF_TOKENS = (
    "这个",
    "这些",
    "那几个",
    "刚才",
    "上面",
    "下面",
    "风险",
    "问题",
    "相关",
    "全部",
    "所有",
    "一批",
    "几个",
    "冲档",
    "稳档",
    "保底",
)

_REF_SEPARATORS = ("以及", "并且", "、", "，", ",", "；", ";")


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
    filters: dict[str, Any] = field(default_factory=dict)

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
    if not any(token in compact_text for token in ("排序", "重排", "排一下", "排一排", "排下")):
        return False
    return any(token in compact_text for token in _SORT_DIMENSIONS)


def _infer_sort_field(compact_text: str) -> str | None:
    matched: list[tuple[int, int, str]] = []
    for token, field in _SORT_DIMENSIONS.items():
        pos = compact_text.find(token)
        if pos >= 0:
            matched.append((pos, -len(token), field))
    if not matched:
        return None
    matched.sort()
    return matched[0][2]


def _looks_like_review_request(compact_text: str) -> bool:
    if "审查" not in compact_text and "检查" not in compact_text:
        return False
    return "方案" in compact_text or len(compact_text) <= 10


def _review_followup_adjustment_action_family(compact_text: str) -> str | None:
    has_adjustment_preview = any(token in compact_text for token in _ADJUSTMENT_PREVIEW_TOKENS)
    if not has_adjustment_preview:
        return None
    has_strong_review_context = any(token in compact_text for token in _REVIEW_FOLLOWUP_STRONG_CONTEXT_TOKENS)
    has_anchored_weak_context = (
        any(token in compact_text for token in _REVIEW_FOLLOWUP_WEAK_CONTEXT_TOKENS)
        and any(token in compact_text for token in _REVIEW_FOLLOWUP_ANCHOR_TOKENS)
    )
    if not has_strong_review_context and not has_anchored_weak_context:
        return None
    if any(token in compact_text for token in _COMPENSATION_PREVIEW_TOKENS):
        return "preview_compensation"
    return "analyze_adjustment"


def _looks_like_colloquial_adjustment_analysis(compact_text: str) -> bool:
    if not any(anchor in compact_text for anchor in _COLLOQUIAL_ADJUSTMENT_ANCHORS):
        return False
    if not any(token in compact_text for token in _COLLOQUIAL_ADJUSTMENT_TOKENS):
        return False
    return any(token in compact_text for token in _ADJUSTMENT_PREVIEW_BOUNDARY_TOKENS)


def _looks_like_status_request(compact_text: str) -> bool:
    if any(pattern in compact_text for pattern in _PLAN_STATUS_PATTERNS):
        return True
    return (
        "方案" in compact_text
        and any(token in compact_text for token in ("结构化", "结论", "情况", "状态", "概览"))
        and not any(token in compact_text for token in ("排序", "移动", "删除", "去掉", "加入", "加进", "审查", "检查"))
    )


def _looks_like_colloquial_risk_status_request(compact_text: str) -> bool:
    if not any(anchor in compact_text for anchor in _PLAN_RISK_STATUS_ANCHORS):
        return False
    if not any(token in compact_text for token in _PLAN_RISK_STATUS_TOKENS):
        return False
    remaining = compact_text
    for token in _PLAN_RISK_STATUS_READONLY_CANCEL_TOKENS:
        remaining = remaining.replace(token, "")
    return not any(token in remaining for token in _PLAN_RISK_STATUS_MUTATION_TOKENS)


def _looks_like_safety_status_question(compact_text: str) -> bool:
    if not any(token in compact_text for token in ("保底", "保区", "兜底", "托底", "安全垫")):
        return False
    if not any(token in compact_text for token in ("够不够", "够吗", "足不足", "是否足够", "够了么", "够没", "够")):
        return False
    return not any(
        token in compact_text
        for token in (
            "补齐",
            "补满",
            "补几个",
            "加入",
            "加进",
            "调整",
            "怎么调",
            "预览",
            "执行",
            "确认",
        )
    )


def _sanitize_named_ref(ref: str | None) -> str:
    text = str(ref or "").strip()
    text = text.strip(" ：:，,。.!！?？；;「」『』（）()[]【】")
    for prefix in ("当前方案里的", "当前方案里", "方案里的", "方案里", "候选里的", "候选里"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text.strip(" ：:，,。.!！?？；;「」『』（）()[]【】")


def _is_specific_named_ref(ref: str) -> bool:
    text = _sanitize_named_ref(ref)
    if len(text) < 3:
        return False
    if re.fullmatch(r"第?\d+(?:个|条)?(?:志愿|专业组|组|位置|位)?", text):
        return False
    if any(token in text for token in _GENERIC_NAMED_REF_TOKENS):
        return False
    if any(token in text for token in _REF_SEPARATORS):
        return False
    return True


def _looks_like_compound_or_non_plan_named_mutation(compact_text: str) -> bool:
    return any(token in compact_text for token in _NAMED_MUTATION_BLOCK_TOKENS)


def _resolve_named_mutation(compact_text: str, original: str) -> PlanFastRouteDecision | None:
    if _looks_like_compound_or_non_plan_named_mutation(compact_text):
        return None

    if match := _MOVE_NAMED_UNIT_RE.search(compact_text):
        ref = _sanitize_named_ref(match.group(1))
        if _is_specific_named_ref(ref):
            target_position = int(match.group(2))
            return PlanFastRouteDecision(
                matched=True,
                action_family="move_unit",
                user_goal=original,
                reason="named_volunteer_move",
                confidence="high",
                volunteer_ids=[ref],
                target_position=target_position,
            )

    remove_match = _REMOVE_NAMED_UNIT_PREFIX_RE.search(compact_text) or _REMOVE_NAMED_UNIT_SUFFIX_RE.search(compact_text)
    if remove_match:
        ref = _sanitize_named_ref(remove_match.group(1))
        if _is_specific_named_ref(ref):
            return PlanFastRouteDecision(
                matched=True,
                action_family="remove_units",
                user_goal=original,
                reason="named_volunteer_remove",
                confidence="high",
                volunteer_ids=[ref],
            )

    if match := _ADD_NAMED_UNIT_RE.search(compact_text):
        ref = _sanitize_named_ref(match.group(1))
        if _is_specific_named_ref(ref):
            return PlanFastRouteDecision(
                matched=True,
                action_family="add_units",
                user_goal=original,
                reason="named_candidate_add",
                confidence="high",
                volunteer_ids=[ref],
            )

    return None


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

    if named_decision := _resolve_named_mutation(compact_text, original):
        return named_decision

    if _looks_like_sort_request(compact_text):
        sort_field = _infer_sort_field(compact_text)
        return PlanFastRouteDecision(
            matched=True,
            action_family="sort_ordered_plan",
            user_goal=original,
            reason="explicit_sort_dimension",
            confidence="high",
            filters={"sort_field": sort_field} if sort_field else {},
        )

    if _looks_like_safety_status_question(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="query_state",
            user_goal=original,
            reason="plan_safety_status_query",
            confidence="high",
        )

    if _looks_like_colloquial_risk_status_request(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="query_state",
            user_goal=original,
            reason="plan_risk_status_query",
            confidence="high",
        )

    if _looks_like_colloquial_adjustment_analysis(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family="analyze_adjustment",
            user_goal=original,
            reason="colloquial_adjustment_analysis",
            confidence="high",
        )

    if adjustment_action_family := _review_followup_adjustment_action_family(compact_text):
        return PlanFastRouteDecision(
            matched=True,
            action_family=adjustment_action_family,
            user_goal=original,
            reason=(
                "review_followup_compensation_preview"
                if adjustment_action_family == "preview_compensation"
                else "review_followup_adjustment_preview"
            ),
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
