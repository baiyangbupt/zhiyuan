"""Structured read-only analysis for region preference vs admission safety."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.agent.context import PlanningSummary, RequestContext
from app.util.display_text import brief_school_major_text


_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "京津": ("北京", "天津"),
    "京津冀": ("北京", "天津", "河北"),
    "北京天津": ("北京", "天津"),
    "北京": ("北京",),
    "天津": ("天津",),
    "上海": ("上海",),
    "广深": ("广东", "广州", "深圳"),
    "广州深圳": ("广东", "广州", "深圳"),
    "广东": ("广东",),
    "杭州": ("浙江", "杭州"),
    "浙江": ("浙江",),
    "江苏": ("江苏",),
    "南京": ("江苏", "南京"),
    "成都": ("四川", "成都"),
    "四川": ("四川",),
    "重庆": ("重庆",),
    "武汉": ("湖北", "武汉"),
    "湖北": ("湖北",),
    "西安": ("陕西", "西安"),
    "陕西": ("陕西",),
}
_TARGET_REGION_TOKENS = tuple(_REGION_ALIASES.keys())
_TIER_ORDER = {"冲": 0, "稳": 1, "保": 2}


def is_region_safety_tradeoff_candidate(route_decision: dict[str, Any] | None) -> bool:
    """Whether arbitration selected the structured region-safety route."""
    return str((route_decision or {}).get("selectedPath") or "") == "region_safety_tradeoff_route"


def render_region_safety_tradeoff_reply(
    user_text: str,
    planning_state: dict[str, Any] | None,
    request_context: RequestContext,
) -> str | None:
    """Render a user-facing read-only tradeoff analysis from planning facts.

    Returns None when the current state lacks enough plan facts; callers should
    then fall back to the full agent rather than emitting a thin answer.
    """
    plan_state = planning_state or {}
    ordered_state = plan_state.get("orderedPlanState") or {}
    ordered_items = _enrich_ordered_items_from_candidate_pool(
        [item for item in (ordered_state.get("items") or []) if isinstance(item, dict)],
        plan_state,
    )
    if not ordered_items:
        return None

    regions = _resolve_target_regions(user_text, request_context, plan_state)
    if not regions:
        return None

    summary = ordered_state.get("summary") or {}
    planning_summary = getattr(request_context, "planning_summary", None)
    total = _as_int(summary.get("unitTotal") or summary.get("total")) or _summary_total(planning_summary) or len(ordered_items)
    target = _as_int(summary.get("targetUnitCount") or summary.get("targetCount")) or _summary_target(planning_summary) or total
    tier_counts = _tier_counts(summary.get("unitTierCounts") or summary.get("tierCounts"), ordered_items, planning_summary)
    target_items = [item for item in ordered_items if _item_matches_region(item, regions)]
    non_target_items = [item for item in ordered_items if not _item_matches_region(item, regions)]
    safe_items = [item for item in ordered_items if _item_tier(item) == "保"]
    steady_or_safe_items = [item for item in ordered_items if _item_tier(item) in {"稳", "保"}]
    target_safe_items = [item for item in target_items if _item_tier(item) == "保"]
    target_steady_items = [item for item in target_items if _item_tier(item) in {"稳", "保"}]
    public_target_items = [item for item in target_items if _school_nature(item) == "公办"]
    private_target_items = [item for item in target_items if _school_nature(item) in {"民办", "独立学院"}]
    high_tuition_target_items = [item for item in target_items if _tuition(item) >= 20000]
    review_risks = _review_risk_summaries(plan_state)
    score_text = _student_score_text(request_context)
    region_text = "、".join(regions)

    lines: list[str] = []
    lines.append(f"你的担心是对的：想去{region_text}，但不能只按地域排，关键要看这块能不能承担保底。")
    if score_text:
        lines.append(f"\n结合{score_text}和当前方案，先把取舍摊开看：")
    else:
        lines.append("\n结合当前方案，先把取舍摊开看：")

    lines.append("\n**当前方案的安全底盘**")
    lines.append(f"- 已有方案 {total} / {target} 个；冲 {tier_counts.get('冲', 0)}、稳 {tier_counts.get('稳', 0)}、保 {tier_counts.get('保', 0)}。")
    if tier_counts.get("保", 0) <= 0:
        lines.append("- 目前保区为 0，这是最大风险：它不是“去不了目标城市”的问题，而是缺少真正兜底。")
    elif len(safe_items) < max(2, int(total * 0.15)):
        lines.append(f"- 保区只有 {len(safe_items)} 个，安全垫偏薄；如果分数线或热度波动，仍需要补厚保底。")
    else:
        lines.append(f"- 保区有 {len(safe_items)} 个，整体有一定安全垫，但还要看这些保底是否是你能接受的地区和学校。")
    if review_risks:
        lines.append(f"- 审查里也提示：{'；'.join(review_risks[:2])}。")

    lines.append(f"\n**{region_text}这块能不能当主线**")
    if target_items:
        lines.append(
            f"- 当前方案里命中{region_text}的有 {len(target_items)} 个，其中稳/保 {len(target_steady_items)} 个，保区 {len(target_safe_items)} 个。"
        )
        if public_target_items or private_target_items:
            nature_parts = []
            if public_target_items:
                nature_parts.append(f"公办 {len(public_target_items)} 个")
            if private_target_items:
                nature_parts.append(f"民办/独立学院 {len(private_target_items)} 个")
            lines.append(f"- 院校性质上，{region_text}命中项里" + "、".join(nature_parts) + "。")
        if high_tuition_target_items:
            lines.append(f"- 其中学费 2 万/年以上的有 {len(high_tuition_target_items)} 个，地域收益要和家庭预算一起看。")
        lines.append(f"- 代表样本：{_format_examples(target_items, limit=4)}。")
    else:
        lines.append(f"- 当前方案里没有明显命中{region_text}的志愿，说明这块更多是意向，不是现有方案的安全来源。")

    lines.append("\n**我的判断**")
    if not target_items:
        lines.append(f"- 如果孩子坚持{region_text}，需要先从候选里确认有没有可用学校；不能直接把它当作当前方案主线。")
    elif not target_safe_items:
        lines.append(f"- {region_text}可以保留为“想去”的方向，但当前不适合当保底。")
    else:
        lines.append(f"- {region_text}里已有保底项，可以保留一部分，但还要确认学校层次、专业和学费是否能接受。")
    if steady_or_safe_items:
        stable_examples = _format_examples(_sort_stable_examples(non_target_items or steady_or_safe_items), limit=3)
        if stable_examples:
            lines.append(f"- 真正负责“别没学上”的，应该优先看稳/保里的可接受学校，比如：{stable_examples}。")
    if private_target_items and not target_safe_items:
        lines.append("- 如果目标地区主要是民办或独立学院，风险不只在录取，还在四年总成本和后续升学/就业认可度。")

    lines.append("\n**下一步建议**")
    lines.append(f"- 可以保留少量{region_text}志愿满足地域诉求，但不要用它们承担兜底。")
    if tier_counts.get("保", 0) <= 0 or total < target:
        lines.append("- 更稳妥的动作是先补足保区，再决定目标地域志愿保留多少。")
    else:
        lines.append("- 如果不想现在改方案，可以先逐个确认稳/保学校是否真的能接受。")
    lines.append("- 我这轮只是帮你分析取舍，没有修改方案。你可以继续说“先补几个保底给我看看”，我再给调整预览。")
    return "\n".join(lines)


def _summary_total(summary: PlanningSummary | None) -> int:
    if summary is None:
        return 0
    return int(getattr(summary, "ordered_total", 0) or getattr(summary, "draft_total", 0) or 0)


def _summary_target(summary: PlanningSummary | None) -> int:
    if summary is None:
        return 0
    return int(getattr(summary, "ordered_target_total", 0) or getattr(summary, "draft_target_total", 0) or 0)


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_item_metadata(plan_item: dict[str, Any], candidate_item: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(candidate_item or {})
    for key, value in (plan_item or {}).items():
        if key == "majorItems" and isinstance(value, list):
            merged[key] = _merge_major_items(value, merged.get("majorItems"))
            continue
        if not _is_empty_value(value):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged or dict(plan_item or {})


def _merge_major_items(plan_majors: list[Any], candidate_majors: Any) -> list[Any]:
    if not isinstance(candidate_majors, list):
        return plan_majors
    candidate_by_id = {
        str(item.get("volunteerId")): item
        for item in candidate_majors
        if isinstance(item, dict) and item.get("volunteerId")
    }
    merged: list[Any] = []
    for plan_major in plan_majors:
        if not isinstance(plan_major, dict):
            merged.append(plan_major)
            continue
        candidate = candidate_by_id.get(str(plan_major.get("volunteerId") or ""))
        merged.append(_merge_item_metadata(plan_major, candidate))
    return merged


def _enrich_ordered_items_from_candidate_pool(
    ordered_items: list[dict[str, Any]],
    planning_state: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate_items = [
        item
        for item in ((planning_state.get("candidatePoolState") or {}).get("items") or [])
        if isinstance(item, dict)
    ]
    if not ordered_items or not candidate_items:
        return ordered_items

    candidate_by_volunteer_id = {
        str(item.get("volunteerId")): item
        for item in candidate_items
        if item.get("volunteerId")
    }
    candidate_by_unit_id = {
        str(item.get("unitId")): item
        for item in candidate_items
        if item.get("unitId")
    }
    return [
        _merge_item_metadata(
            item,
            candidate_by_volunteer_id.get(str(item.get("volunteerId") or ""))
            or candidate_by_unit_id.get(str(item.get("unitId") or "")),
        )
        for item in ordered_items
    ]


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _resolve_target_regions(
    user_text: str,
    request_context: RequestContext,
    planning_state: dict[str, Any],
) -> list[str]:
    text = str(user_text or "")
    regions: list[str] = []
    for token in _TARGET_REGION_TOKENS:
        if token in text:
            for region in _REGION_ALIASES[token]:
                _append_unique(regions, region)
    if regions:
        return regions

    for region in getattr(getattr(request_context, "planning_summary", None), "positive_regions", []) or []:
        _append_unique(regions, str(region))
    explicit = ((planning_state.get("profileState") or {}).get("explicitProfile") or {})
    for region in explicit.get("positiveRegions") or []:
        _append_unique(regions, str(region))
    init_profile = getattr(request_context, "init_profile", None)
    city = getattr(init_profile, "city", None)
    for region in getattr(city, "province", []) or []:
        _append_unique(regions, str(region))
    return regions[:3]


def _append_unique(values: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _tier_counts(raw_counts: Any, ordered_items: list[dict[str, Any]], summary: PlanningSummary | None) -> dict[str, int]:
    counts = {"冲": 0, "稳": 0, "保": 0}
    if isinstance(raw_counts, dict):
        for key in counts:
            counts[key] = _as_int(raw_counts.get(key))
    elif summary is not None and isinstance(getattr(summary, "tier_counts", None), dict):
        for key in counts:
            counts[key] = _as_int(summary.tier_counts.get(key))
    if not any(counts.values()):
        for item in ordered_items:
            tier = _item_tier(item)
            if tier in counts:
                counts[tier] += 1
    return counts


def _item_tier(item: dict[str, Any]) -> str:
    tier = str(item.get("tier") or item.get("majorTier") or "").strip()
    return tier if tier in {"冲", "稳", "保"} else ""


def _school_nature(item: dict[str, Any]) -> str:
    value = str(item.get("schoolNature") or "").strip()
    if value:
        return value
    for tag in [*(item.get("schoolBasicTags") or []), *(item.get("schoolRankTags") or [])]:
        text = str(tag or "")
        if "公办" in text:
            return "公办"
        if "民办" in text:
            return "民办"
        if "独立学院" in text:
            return "独立学院"
    return ""


def _tuition(item: dict[str, Any]) -> int:
    direct = _as_int(item.get("tuitionPerYear"))
    if direct > 0:
        return direct
    major_items = [major for major in item.get("majorItems") or [] if isinstance(major, dict)]
    values = [_as_int(major.get("tuitionPerYear")) for major in major_items]
    values = [value for value in values if value > 0]
    return max(values) if values else 0


def _item_matches_region(item: dict[str, Any], regions: list[str]) -> bool:
    province = str(item.get("provinceName") or "").strip()
    city = str(item.get("cityName") or "").strip()
    return any(region and (region in province or region in city) for region in regions)


def _review_risk_summaries(planning_state: dict[str, Any]) -> list[str]:
    summaries: list[str] = []
    review_state = planning_state.get("reviewState") or {}
    for check in review_state.get("checks") or []:
        if not isinstance(check, dict) or check.get("passed") is True:
            continue
        level = str(check.get("level") or "").strip()
        summary = str(check.get("summary") or "").strip()
        if summary and level in {"risk", "warn"}:
            _append_unique(summaries, summary)
    return summaries


def _student_score_text(request_context: RequestContext) -> str:
    detail = getattr(request_context, "score_detail", None)
    if detail is None:
        return ""
    parts: list[str] = []
    if getattr(detail, "province", ""):
        parts.append(str(detail.province))
    if getattr(detail, "total_score", 0):
        parts.append(f"{detail.total_score}分")
    return "".join(parts)


def _format_examples(items: list[dict[str, Any]], *, limit: int) -> str:
    examples: list[str] = []
    for item in _sort_examples(items):
        school = item.get("schoolName") or "未知院校"
        major = _first_major_name(item)
        label = brief_school_major_text(school, major, max_length=36)
        tier = _item_tier(item) or "未知"
        ratio = _format_ratio(item.get("admissionRatio") or item.get("schoolEnrollRatio"))
        nature = _school_nature(item)
        tuition = _tuition(item)
        parts = [f"{tier}", f"录取率{ratio}"]
        if nature:
            parts.append(nature)
        if tuition >= 20000:
            parts.append(f"学费{int(tuition / 10000)}万+/年")
        examples.append(f"{label}（{'，'.join(parts)}）")
        if len(examples) >= limit:
            break
    return "、".join(examples)


def _sort_examples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _TIER_ORDER.get(_item_tier(item), 9),
            -_ratio_value(item),
            _as_int(item.get("position")) or 9999,
        ),
    )


def _sort_stable_examples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stable = [item for item in items if _item_tier(item) in {"稳", "保"}]
    return sorted(
        stable,
        key=lambda item: (
            _TIER_ORDER.get(_item_tier(item), 9),
            -_ratio_value(item),
            0 if _school_nature(item) == "公办" else 1,
            _as_int(item.get("schoolRank")) or 99999,
        ),
    )


def _ratio_value(item: dict[str, Any]) -> float:
    try:
        return float(item.get("admissionRatio") or item.get("schoolEnrollRatio") or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_ratio(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric < 0:
        return "-"
    return f"{int(numeric)}%" if numeric.is_integer() else f"{numeric:.1f}%"


def _first_major_name(item: dict[str, Any]) -> str:
    direct = str(item.get("majorName") or "").strip()
    if direct:
        return direct
    for major in item.get("majorItems") or []:
        if isinstance(major, dict) and major.get("majorName"):
            return str(major.get("majorName"))
    return "未知专业"
