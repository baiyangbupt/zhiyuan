"""分析类 handler。

覆盖 action_family: analyze_adjustment, review_plan。
只读分析，不涉及方案变更副作用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.handlers.registry import register_handler
from app.handlers.query_handlers import (
    _get_planning_state_with_latest_profile,
    _compact_list_text,
)
from app.handlers.shared import summary_target_total, summary_total
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult
from app.tools.planning_workflow_tool import (
    _build_review_result_facts,
    _fix_proposal_facts,
)
from app.util.planning_state_compat import get_working_plan_summary
from app.util.internal_client import (
    generate_planning_fix_proposals as _generate_planning_fix_proposals_request,
    get_planning_ordered_plan as _get_planning_ordered_plan_request,
    get_working_plan as _get_working_plan_request,
    run_planning_review as _run_planning_review_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = 1


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _normalize_review_summary_for_user(summary: str) -> str:
    normalized = str(summary or "").strip()
    if "部分专业组主要依靠非意向专业托底" in normalized:
        return "部分专业组主要依靠非意向托底专业作为组内安全垫"
    if "存在专业组缺少组内安全垫专业" in normalized:
        return "部分专业组缺少组内安全垫专业"
    return normalized


def _issue_hit_plan_examples_text(items: list[dict[str, Any]] | None, *, limit: int = 2) -> str:
    snippets: list[str] = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        count_text = str(item.get("count_text") or "").strip()
        example_text = str(item.get("example_text") or "").strip()
        affected_items = [
            str(name or "").strip()
            for name in (item.get("items") or [])
            if str(name or "").strip()
        ]
        if not summary or not affected_items:
            continue
        prefix = summary
        if count_text:
            prefix = f"{summary}（{count_text}）"
        example_prefix = f"{example_text}：" if example_text else ""
        snippets.append(f"{prefix}：{example_prefix}{'；'.join(affected_items[:2])}")
    return "；".join(snippets)


def _adjustment_first_step_hint(facts: dict[str, Any]) -> str:
    for item in facts.get("review_issue_hit_plan_examples") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        affected_items = [
            str(name or "").strip()
            for name in (item.get("items") or [])
            if str(name or "").strip()
        ]
        if code == "high_tuition":
            return "如果你想直接开始，我建议先把整批高收费项替换成正常收费的志愿，保持 30 个总数不变。"
        if code == "cooperative_program":
            return "如果你想直接开始，我建议先把中外合作这批志愿整批替换掉，再看结构怎么补稳。"
        if code == "major_group_safety_intent_alignment" and affected_items:
            return (
                f"如果你想先从局部开始，我建议先确认这组非意向托底是否接受：{affected_items[0]}。"
                "这类专业通常是为了让组内最低专业录取率不低于专业组整体录取率、降低退档风险而保留下来的牺牲项，直接去掉前最好先看有没有同等安全垫可以替换。"
            )
        if code == "group_inner_safety_guard" and affected_items:
            return (
                f"如果你想先从局部开始，我建议先补这组的安全垫专业：{affected_items[0]}。"
                "组内至少要保留 1 个录取率不低于专业组整体录取率的专业，才能更稳地防退档。"
            )
        if code == "probability_gap" and affected_items:
            return f"如果你想先从局部开始，我建议先围绕这段梯度断层做替换预览：{affected_items[0]}。"
    return ""


def _candidate_supply_line(facts: dict[str, Any]) -> str:
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    if not supply:
        return ""
    summary = str(supply.get("summary") or "").strip()
    if summary:
        return summary
    shortages = [
        str(item or "").strip()
        for item in (supply.get("tier_shortages") or [])
        if str(item or "").strip()
    ]
    return "；".join(shortages[:2])


def _candidate_supply_missing_stable_or_protect(facts: dict[str, Any]) -> bool:
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    missing = {
        str(item or "").strip()
        for item in (supply.get("missing_supply_tiers") or [])
        if str(item or "").strip()
    }
    return bool({"稳", "保"} & missing)


async def _fetch_fix_proposal_facts(session_id: str) -> dict[str, Any]:
    try:
        proposal_result = await _generate_planning_fix_proposals_request(
            _DEFAULT_TENANT_ID, session_id
        )
        if proposal_result.get("code") != 0:
            return {}
        return _fix_proposal_facts(proposal_result.get("data") or {})
    except Exception:
        logger.warning("fetch fix proposal facts failed: session_id=%s", session_id, exc_info=True)
        return {}


_FIX_PROPOSAL_STATUS_LABELS = {
    "ready": "",
    "preview_only": "",
    "blocked": "",
    "info": "",
}

_FIX_PROPOSAL_STRATEGY_LABELS = {
    "replace_risk_items": "优先看替换",
    "remove_risk_items": "移除风险项",
    "fill_missing_count": "补足数量",
    "sort_by_probability": "按录取率重排",
    "rebalance_tier_ratio": "调整冲稳保结构",
    "fill_probability_gap": "补梯度断层",
    "add_safety_items": "补安全垫",
    "adjust_major_group_inner_safety": "调整组内安全垫",
    "cannot_satisfy": "",
}

_FIX_PROPOSAL_BLOCKING_GUIDANCE = {
    "candidate_pool_insufficient": "当前可选范围里没有足够合适的补位项，建议先放宽地域、专业或院校条件，或者接受当前数量风险",
    "safety_candidate_insufficient": "当前可选范围里缺少合适的保底选择，建议先放宽条件后重新审查，或手动保留现有提醒",
    "tier_candidate_insufficient": "目标冲稳保区间的可选项不足，建议先放宽筛选条件，再重新看比例是否能调整",
    "probability_gap_candidate_insufficient": "录取率断层中间缺少合适候选，建议先放宽条件，或手动检查相邻志愿顺序",
    "no_sort_or_replacement_candidate": "当前缺少可重排或可替换项，建议先人工查看相关志愿，再决定是否手动调整",
    "major_group_safety_candidate_insufficient": "专业组内缺少更稳的可补专业，建议你先人工确认是否保留这个专业组，或放宽专业范围后再试",
    "risk_item_unresolved_or_replacement_missing": "还没定位到明确的替换范围，建议先缩小到具体学校、专业组或志愿后再处理",
    "replacement_pair_missing": "当前方案已满，但还没有明确一进一出的替换配对",
    "volunteer_model_mismatch": "当前填报模式不适合这类组内处理",
    "risk_unit_unresolved": "还没定位到具体专业组，建议先点开审查详情确认是哪一组",
    "partial_major_group_safety_candidate_missing": "只有部分专业组找到了可补选择，其余部分建议你人工取舍或放宽专业范围后再试",
    "risk_item_unresolved": "还没定位到具体志愿，建议先在审查详情里确认对应条目",
    "safe_replacement_candidate_insufficient": "暂时没有同层次且风险更低的替换项，建议先人工查看是否接受降层次或放宽范围",
    "objective_validation_not_improved": "调整预览没有让本次关注的问题变好，不建议直接执行",
}


_TARGET_STRATEGY_REVIEW_CODES = {
    "replace_risk_items": {
        "high_tuition",
        "cooperative_program",
        "admission_limit",
        "special_enrollment",
    },
    "remove_risk_items": {
        "high_tuition",
        "cooperative_program",
        "admission_limit",
        "special_enrollment",
    },
    "sort_by_probability": {"probability_inversion"},
    "adjust_major_group_inner_safety": {
        "major_group_safety_intent_alignment",
        "group_inner_safety_guard",
    },
    "fill_probability_gap": {"probability_gap"},
    "rebalance_tier_ratio": {"tier_ratio"},
    "add_safety_items": {"safety_guard", "edge_score"},
    "fill_missing_count": {"count_validation"},
}


def _normalized_target_strategies(plan: PlanActionPlan) -> list[str]:
    result: list[str] = []
    for value in getattr(plan, "target_strategies", []) or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalized_target_issue_codes(plan: PlanActionPlan) -> list[str]:
    result: list[str] = []
    for value in getattr(plan, "target_issue_codes", []) or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalized_reply_focus(plan: PlanActionPlan) -> list[str]:
    result: list[str] = []
    for value in getattr(plan, "reply_focus", []) or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _review_codes_for_target_strategies(target_strategies: list[str]) -> set[str]:
    codes: set[str] = set()
    for strategy in target_strategies:
        codes.update(_TARGET_STRATEGY_REVIEW_CODES.get(strategy, set()))
    return codes


def _proposal_matches_target(
    proposal: dict[str, Any],
    *,
    target_strategies: set[str],
    target_issue_codes: set[str],
) -> bool:
    source_codes = {
        str(code or "").strip()
        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
        if str(code or "").strip()
    }
    if target_issue_codes:
        return bool(source_codes & target_issue_codes)
    strategy = str(proposal.get("strategy") or "").strip()
    return bool(strategy and strategy in target_strategies)


def _recount_fix_proposals(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    for proposal in proposals:
        status = str(proposal.get("status") or "").strip()
        strategy = str(proposal.get("strategy") or "").strip()
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        if strategy:
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
    return {
        "status_counts": status_counts,
        "strategy_counts": strategy_counts,
        "ready_count": status_counts.get("ready", 0),
        "preview_only_count": status_counts.get("preview_only", 0),
        "blocked_count": status_counts.get("blocked", 0),
        "total": len(proposals),
    }


def _filter_fix_proposal_facts_for_targets(
    fix_proposals: dict[str, Any],
    target_strategies: list[str],
    target_issue_codes: list[str] | None = None,
) -> dict[str, Any]:
    if not target_strategies and not target_issue_codes:
        return fix_proposals
    proposals = [
        proposal
        for proposal in (fix_proposals.get("proposals") or [])
        if isinstance(proposal, dict)
    ]
    target_strategy_set = set(target_strategies)
    normalized_issue_codes = [
        str(code or "").strip()
        for code in (target_issue_codes or [])
        if str(code or "").strip()
    ]
    target_issue_code_set = set(normalized_issue_codes) or _review_codes_for_target_strategies(target_strategies)
    matched = [
        proposal
        for proposal in proposals
        if _proposal_matches_target(
            proposal,
            target_strategies=target_strategy_set,
            target_issue_codes=target_issue_code_set,
        )
    ]
    if not matched:
        filtered = dict(fix_proposals)
        filtered["proposals"] = []
        filtered.update(_recount_fix_proposals([]))
        filtered["target_strategies"] = list(target_strategies)
        filtered["target_issue_codes"] = list(normalized_issue_codes or target_issue_code_set)
        filtered["target_match_empty"] = True
        return filtered
    filtered = dict(fix_proposals)
    filtered["proposals"] = matched
    filtered.update(_recount_fix_proposals(matched))
    filtered["target_strategies"] = list(target_strategies)
    filtered["target_issue_codes"] = list(normalized_issue_codes or target_issue_code_set)
    return filtered


def _filter_review_facts_for_targets(
    facts: dict[str, Any],
    target_strategies: list[str],
    target_issue_codes: list[str] | None = None,
) -> dict[str, Any]:
    if not target_strategies and not target_issue_codes:
        return facts
    normalized_issue_codes = [
        str(code or "").strip()
        for code in (target_issue_codes or [])
        if str(code or "").strip()
    ]
    target_review_codes = set(normalized_issue_codes) or _review_codes_for_target_strategies(target_strategies)
    if not target_review_codes:
        return facts
    filtered = dict(facts)
    examples = [
        item
        for item in (facts.get("issue_hit_plan_examples") or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip() in target_review_codes
    ]
    filtered["issue_hit_plan_examples"] = examples
    if isinstance(facts.get("fix_proposals"), dict):
        filtered["fix_proposals"] = _filter_fix_proposal_facts_for_targets(
            facts["fix_proposals"],
            target_strategies,
            normalized_issue_codes,
        )
    filtered["main_problems"] = [
        str(item.get("summary") or "").strip()
        for item in examples
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]
    filtered["hit_rules"] = [
        {"summary": item, "suggestion_types": []}
        for item in filtered["main_problems"]
    ]
    if not examples and normalized_issue_codes:
        filtered["target_match_empty"] = True
        filtered["summary_text"] = "当前审查里暂时没有看到你点名的这类提醒。"
        filtered["review_issue_hit_plan_examples"] = []
        filtered["candidate_supply"] = {}
    return filtered


def _normalize_fix_proposal_title_for_user(title: str) -> str:
    value = str(title or "").strip()
    if not value:
        return "处理建议"
    normalized = (
        value
        .replace("修复建议", "处理建议")
        .replace("修复", "处理")
        .replace("暂时无法自动处理", "")
        .replace("无法自动处理", "")
        .replace("暂不可用", "")
        .replace("不可用", "")
    )
    return normalized.rstrip("：:。；;，,").strip() or "处理建议"


def _normalize_fix_proposal_line_for_user(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = (
        value
        .replace("修复建议", "处理建议")
        .replace("修复预览", "处理预览")
        .replace("修复方案", "处理方案")
        .replace("自动修复", "自动处理")
        .replace("完整修复", "完整处理")
        .replace("组内修复", "组内处理")
        .replace("修复", "处理")
        .replace("暂不允许确认应用", "需要你先取舍后再处理")
        .replace("暂时无法自动修复", "建议你先人工查看或放宽条件后再试")
        .replace("暂不能自动处理", "建议你先人工查看或放宽条件后再试")
        .replace("候选池", "可选范围")
        .replace("放宽约束", "放宽报考条件")
        .replace("人工调整", "手动调整")
        .replace("cannot_satisfy", "")
        .replace("先作为处理方向参考", "")
    )
    internal_markers = {
        "cannot_satisfy",
        "blocked",
        "preview_only",
        "ready",
        "info",
    }
    if normalized in internal_markers:
        return ""
    return normalized.strip("。；;，, ：:").strip()


def _dedupe_fix_proposal_parts(parts: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        item = _normalize_fix_proposal_line_for_user(raw)
        if not item:
            continue
        key = re.sub(r"[，,。；;\s]+", "", item)
        key = key.replace("处理预览会改变专业组数量需要先人工确认取舍", "替换改变专业组数量")
        key = key.replace("替换预览会改变专业组数量需要先人工确认取舍", "替换改变专业组数量")
        key = key.replace("当前可用于规划的可选范围里部分专业组缺少可补入的组内安全垫专业", "缺少组内安全垫专业")
        key = key.replace("处理预览没有为目标专业组补足组内安全垫专业需要先人工确认取舍", "缺少组内安全垫专业")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _format_fix_proposal_change_counts(remove_count: int, add_count: int) -> str:
    parts: list[str] = []
    if remove_count > 0:
        parts.append(f"预计移出 {remove_count} 条")
    if add_count > 0:
        parts.append(f"补入 {add_count} 条")
    return "、".join(parts)


def _normalize_text_items(values: Any) -> list[str]:
    if isinstance(values, str):
        value = values.strip()
        return [value] if value else []
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _fix_proposal_blocking_guidance(proposal: dict[str, Any]) -> list[str]:
    codes = _normalize_text_items(proposal.get("blocking_reason_codes"))
    result: list[str] = []
    for shortage in proposal.get("candidate_shortages") or []:
        if not isinstance(shortage, dict):
            continue
        message = str(shortage.get("message") or "").strip()
        scope = str(shortage.get("scope") or "").strip()
        if not message:
            if scope == "capacity_or_replacement":
                message = "当前不是单纯缺候选，而是缺少完整一进一出的替换配对"
            elif scope == "objective_validation":
                message = "调整预览没有让本次关注的问题变好，不建议直接执行"
            elif scope == "hard_constraints":
                message = "已确认的报考条件收窄了可选范围，当前可用于补位的候选不足"
            else:
                message = "当前可用于规划的候选里目标候选不足"
        if message.startswith("处理边界："):
            message = message.removeprefix("处理边界：")
        if message and message not in result:
            result.append(message)
    for code in codes:
        text = _FIX_PROPOSAL_BLOCKING_GUIDANCE.get(code)
        if text and text not in result:
            result.append(text)
    return result


def _fix_proposal_blocking_hint(facts: dict[str, Any]) -> str:
    proposal_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = proposal_facts.get("proposals") or []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        if str(proposal.get("status") or "").strip() != "blocked":
            continue
        guidance = _fix_proposal_blocking_guidance(proposal)
        if guidance:
            return "遇到需要用户取舍或可替换志愿不足的处理建议时，要先用用户能理解的话说明为什么不能直接处理；不要承诺已经能直接补齐或直接替换。"
    return ""


def _fix_proposal_lines(facts: dict[str, Any], *, limit: int = 3) -> list[str]:
    proposal_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = proposal_facts.get("proposals") or []
    if not proposals:
        return []

    lines: list[str] = []
    for proposal in proposals[:limit]:
        if not isinstance(proposal, dict):
            continue
        title = _normalize_fix_proposal_title_for_user(str(proposal.get("title") or "处理建议").strip())
        status = str(proposal.get("status") or "").strip()
        strategy = str(proposal.get("strategy") or "").strip()
        status_label = _FIX_PROPOSAL_STATUS_LABELS.get(status, status or "待确认")
        strategy_label = _FIX_PROPOSAL_STRATEGY_LABELS.get(strategy, strategy)
        remove_count = int(proposal.get("remove_volunteer_count") or 0)
        add_count = int(proposal.get("add_volunteer_count") or 0)
        parts = [status_label] if status_label else []
        if strategy_label:
            parts.append(strategy_label)
        change_counts = _format_fix_proposal_change_counts(remove_count, add_count)
        if change_counts:
            parts.append(change_counts)
        action_summaries = [
            str(item or "").strip()
            for item in (proposal.get("action_summaries") or [])
            if str(item or "").strip()
        ]
        if action_summaries:
            parts.append(_normalize_fix_proposal_line_for_user("；".join(action_summaries[:2])))
        blocking_reason = str(proposal.get("blocking_reason") or "").strip()
        if blocking_reason:
            parts.append(_normalize_fix_proposal_line_for_user(blocking_reason))
        guidance = _fix_proposal_blocking_guidance(proposal)
        if guidance:
            parts.append(_normalize_fix_proposal_line_for_user(guidance[0]))
        warnings = [
            str(item or "").strip()
            for item in (proposal.get("warnings") or [])
            if str(item or "").strip()
        ]
        if warnings:
            parts.append(_normalize_fix_proposal_line_for_user(warnings[0]))
        details = _dedupe_fix_proposal_parts(parts)
        if details:
            lines.append(f"{title}：{'；'.join(details)}")
        else:
            lines.append(title)
    return lines


def _fix_proposal_summary_text(facts: dict[str, Any], *, limit: int = 2) -> str:
    lines = _fix_proposal_lines(facts, limit=limit)
    if not lines:
        return ""
    return "；".join(lines)


async def _fetch_ordered_or_working(
    planning_state: dict[str, Any], session_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """根据 planning_state 按优先级获取 ordered 或已加入方案详情。"""
    ordered_state: dict[str, Any] | None = None
    working_state: dict[str, Any] | None = None

    if ((planning_state.get("orderedPlanState") or {}).get("summary") or {}).get("total"):
        ordered_result = await _get_planning_ordered_plan_request(session_id)
        if ordered_result.get("code") == 0:
            ordered_state = ordered_result.get("data") or {}
    elif summary_total(get_working_plan_summary(planning_state)):
        working_result = await _get_working_plan_request(session_id)
        if working_result.get("code") == 0:
            working_state = working_result.get("data") or {}

    return ordered_state, working_state


def _build_review_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    normalized_problems = [
        _normalize_review_summary_for_user(item)
        for item in (facts.get("main_problems") or [])
    ]
    problems_text = _compact_list_text(normalized_problems)
    missing_stable_or_protect = _candidate_supply_missing_stable_or_protect(facts)
    fix_proposal_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    fix_proposals = fix_proposal_facts.get("proposals") if isinstance(fix_proposal_facts, dict) else []
    fix_proposal_total = len(fix_proposals) if isinstance(fix_proposals, list) else int(fix_proposal_facts.get("total") or 0)

    parts = [f"已完成方案审查，风险 {risk_count} 项，提醒 {warn_count} 项"]
    if problems_text:
        parts.append(f"主要问题是 {problems_text}")
    if fix_proposal_total > 0:
        parts.append(f"已整理 {fix_proposal_total} 个处理方向")

    reply_focus = ["review_result", "risk_warning"]
    if problems_text:
        reply_focus.append("main_problems")
    if facts.get("issue_hit_plan_examples"):
        reply_focus.append("issue_hit_plan_examples")
    if facts.get("candidate_supply"):
        reply_focus.append("candidate_supply")
    if fix_proposal_total > 0:
        reply_focus.append("fix_proposals")

    next_step_hints: list[str] = []
    if missing_stable_or_protect:
        next_step_hints.append("如果用户想补稳或保，先说明当前可用来补位的志愿不足，不要承诺能直接补入。")
    if risk_count == 0 and warn_count == 0:
        next_step_hints.append("如果用户只是确认当前是否稳定，可以明确说明目前没有明显风险或提醒。")
    if fix_proposal_total > 0:
        next_step_hints.append("涉及方案处理时，以 fix_proposals 为后端权威处理方向；需要用户取舍或仅供参考的建议不要承诺直接执行。")
    blocking_hint = _fix_proposal_blocking_hint(facts)
    if blocking_hint:
        next_step_hints.append(blocking_hint)
    return "；".join(parts) + "。", reply_focus, next_step_hints


def _build_adjustment_summary(facts: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    target_match_empty = bool(facts.get("target_match_empty"))
    summary_text = str(facts.get("summary_text") or "").strip()
    suggestion_counts = facts.get("suggestion_counts") or {}
    actionable_counts = facts.get("actionable_suggestion_counts") or {}
    has_actionable_suggestions = bool(facts.get("has_actionable_suggestions"))
    rule_summaries = [
        _normalize_review_summary_for_user(item.get("summary"))
        for item in (facts.get("hit_rules") or [])
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]
    example_summaries = [
        str(item.get("description") or item.get("title") or "").strip()
        for item in (facts.get("example_suggestions") or [])
        if isinstance(item, dict) and str(item.get("description") or item.get("title") or "").strip()
    ]
    review_issue_hit_plan_examples_text = _issue_hit_plan_examples_text(
        facts.get("review_issue_hit_plan_examples")
    )
    first_step_hint = _adjustment_first_step_hint(facts)
    candidate_supply_text = _candidate_supply_line(facts)
    missing_stable_or_protect = _candidate_supply_missing_stable_or_protect(facts)
    fix_proposal_text = _fix_proposal_summary_text(facts)

    parts: list[str] = []
    if target_match_empty:
        parts.append(summary_text or "当前审查里暂时没有看到你点名的这类提醒。")
    elif summary_text:
        parts.append(summary_text)
    elif rule_summaries:
        parts.append("；".join(rule_summaries[:2]))

    if has_actionable_suggestions:
        counts_text = (
            f"补充 {int(actionable_counts.get('add') or 0)} 条，"
            f"调序 {int(actionable_counts.get('reorder') or 0)} 条，"
            f"替换 {int(actionable_counts.get('replace') or 0)} 条，"
            f"移除 {int(actionable_counts.get('remove') or 0)} 条"
        )
        parts.append(f"当前可执行建议概览：{counts_text}")
    elif fix_proposal_text:
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        ready_count = int(fix_facts.get("ready_count") or 0)
        blocked_count = int(fix_facts.get("blocked_count") or 0)
        preview_only_count = int(fix_facts.get("preview_only_count") or 0)
        proposal_parts: list[str] = []
        if ready_count > 0:
            proposal_parts.append(f"{ready_count} 个方向可以先看预览")
        if blocked_count > 0:
            proposal_parts.append(f"{blocked_count} 个方向需要你先取舍范围")
        if preview_only_count > 0:
            proposal_parts.append(f"{preview_only_count} 个方向先作为参考")
        parts.append("我把可处理方向整理出来了" + (f"：{'，'.join(proposal_parts)}" if proposal_parts else "。"))
    else:
        counts_text = (
            f"补充建议 {int(suggestion_counts.get('add') or 0)} 条，"
            f"调序建议 {int(suggestion_counts.get('reorder') or 0)} 条，"
            f"替换建议 {int(suggestion_counts.get('replace') or 0)} 条，"
            f"移除建议 {int(suggestion_counts.get('remove') or 0)} 条"
        )
        parts.append(f"当前先拿到的是分析结论，不是可直接执行的调整清单：{counts_text}")
    if example_summaries:
        parts.append(f"可以优先关注：{'；'.join(example_summaries[:2])}")
    if not example_summaries and review_issue_hit_plan_examples_text:
        parts.append(f"如果先从减法入手，可优先查看：{review_issue_hit_plan_examples_text}")
    if candidate_supply_text and not target_match_empty:
        parts.append(f"候选供给：{candidate_supply_text}")
    if missing_stable_or_protect:
        parts.append("当前不能直接承诺补稳或补保，需要先看是否放宽筛选条件、降低地域/专业限制，或接受这份方案整体偏冲的风险")
    if not has_actionable_suggestions and first_step_hint and not target_match_empty:
        parts.append(first_step_hint)
    if fix_proposal_text:
        parts.append(f"处理建议：{fix_proposal_text}")
    if target_match_empty:
        parts.append("如果你想继续看其它风险，我可以再按当前审查结果逐项说明；如果你确认预算有限，也可以把高收费或中外合作作为后续排除条件重新看方案。")

    reply_focus = ["adjustment_analysis", "suggestion_counts"]
    if summary_text or rule_summaries:
        reply_focus.append("main_issues")
    if example_summaries:
        reply_focus.append("example_suggestions")
    if not example_summaries and review_issue_hit_plan_examples_text:
        reply_focus.append("review_issue_hit_plan_examples")
    if candidate_supply_text:
        reply_focus.append("candidate_supply")
    if fix_proposal_text:
        reply_focus.append("fix_proposals")

    next_step_hints: list[str] = []
    if target_match_empty:
        next_step_hints.append("用户点名的审查问题当前没有命中时，只说明没有看到这类提醒；不要转去解释其他审查问题。")
    if missing_stable_or_protect:
        next_step_hints.append("用户问补稳/保时，必须先说明候选池缺少对应供给，不要口头承诺可直接补入稳/保志愿。")
    if has_actionable_suggestions:
        next_step_hints.append(
            "如果用户想继续改方案，先把主要问题和建议方向讲清楚，再确认是否执行具体动作。"
        )
    else:
        next_step_hints.append(
            "如果用户要继续执行调整，不要直接承诺已能改方案；先说明当前只有分析结论，再收敛到可确认的局部替换、移除或重排。"
        )
        if first_step_hint:
            next_step_hints.append(
                "优先把用户引到当前系统已经能稳定执行的第一步动作，不要口头承诺整套更稳方案已经可直接执行。"
            )
    if fix_proposal_text:
        next_step_hints.append("优先按 fix_proposals 解释可处理方向；需要人工取舍或仅供参考的建议只说明原因和下一步选择，不要承诺应用。")
    blocking_hint = _fix_proposal_blocking_hint(facts)
    if blocking_hint:
        next_step_hints.append(blocking_hint)
    return "；".join(parts) + "。", reply_focus, next_step_hints


# ---------------------------------------------------------------------------
# Handler 实现
# ---------------------------------------------------------------------------


@register_handler("review_plan")
async def handle_review_plan(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    review_result = await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    fix_proposals = await _fetch_fix_proposal_facts(session_id)
    planning_state = await _get_planning_state_with_latest_profile(session_id)

    ordered_state, working_state = await _fetch_ordered_or_working(planning_state, session_id)

    review_state = review_result.get("data") or {} if review_result.get("code") == 0 else {}
    facts = _build_review_result_facts(
        review_state,
        planning_state=planning_state,
        ordered_state=ordered_state,
        working_state=working_state,
    )
    active_summary = (
        (ordered_state or {}).get("summary")
        or (working_state or {}).get("summary")
        or {}
    )
    facts["plan_total"] = summary_total(active_summary)
    facts["target_total"] = summary_target_total(active_summary)
    facts["tier_counts"] = active_summary.get("unitTierCounts") or active_summary.get("tierCounts") or {}
    if fix_proposals:
        facts["fix_proposals"] = fix_proposals
    target_strategies = _normalized_target_strategies(plan)
    target_issue_codes = _normalized_target_issue_codes(plan)
    requested_reply_focus = _normalized_reply_focus(plan)
    if target_strategies or target_issue_codes:
        facts = _filter_review_facts_for_targets(facts, target_strategies, target_issue_codes)
        facts["target_strategies"] = target_strategies
        facts["target_issue_codes"] = target_issue_codes
    if requested_reply_focus:
        facts["requested_reply_focus"] = requested_reply_focus
    review_summary, reply_focus, next_step_hints = _build_review_summary(facts)

    return PlanExecutionResult(
        applied=True,
        action_family="review_plan",
        stage=plan.stage,
        result_kind="review_result",
        executed_actions=[{"action": "review_plan"}],
        workspace_refresh_targets=["review"],
        context_summary=plan.context_summary,
        review_summary=review_summary,
        state_summary=review_summary,
        summary=review_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )


@register_handler("analyze_adjustment")
async def handle_analyze_adjustment(
    ctx: RunContext[RequestContext], plan: PlanActionPlan
) -> PlanExecutionResult:
    session_id = ctx.deps.sessionid
    review_result = await _run_planning_review_request(_DEFAULT_TENANT_ID, session_id)
    fix_proposals = await _fetch_fix_proposal_facts(session_id)
    planning_state = await _get_planning_state_with_latest_profile(session_id)

    ordered_state, working_state = await _fetch_ordered_or_working(planning_state, session_id)

    review_state = review_result.get("data") or {} if review_result.get("code") == 0 else {}
    review_facts = _build_review_result_facts(
        review_state,
        planning_state=planning_state,
        ordered_state=ordered_state,
        working_state=working_state,
    )
    main_problems = [
        _normalize_review_summary_for_user(item)
        for item in (review_facts.get("main_problems") or [])
        if str(item or "").strip()
    ]
    facts = {
        "summary_text": "当前方案主要需要关注：" + "；".join(main_problems[:3]) if main_problems else "当前方案暂时没有明显风险或提醒。",
        "hit_rules": [
            {"summary": item, "suggestion_types": []}
            for item in main_problems[:5]
        ],
        "suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
        "actionable_suggestion_counts": {"add": 0, "reorder": 0, "replace": 0, "remove": 0},
        "has_actionable_suggestions": False,
        "example_suggestions": [],
        "review_issue_hit_plan_examples": review_facts.get("issue_hit_plan_examples") or [],
        "intent_relation": review_facts.get("intent_relation") or {},
        "candidate_supply": review_facts.get("candidate_supply") or {},
        "data_freshness": review_facts.get("data_freshness") or {},
        "main_problems": main_problems,
        "risk_count": int(review_facts.get("risk_count") or 0),
        "warn_count": int(review_facts.get("warn_count") or 0),
    }
    if fix_proposals:
        facts["fix_proposals"] = fix_proposals
    target_strategies = _normalized_target_strategies(plan)
    target_issue_codes = _normalized_target_issue_codes(plan)
    requested_reply_focus = _normalized_reply_focus(plan)
    if target_strategies or target_issue_codes:
        facts = _filter_review_facts_for_targets(facts, target_strategies, target_issue_codes)
        facts["target_strategies"] = target_strategies
        facts["target_issue_codes"] = target_issue_codes
    if requested_reply_focus:
        facts["requested_reply_focus"] = requested_reply_focus
    state_summary, reply_focus, next_step_hints = _build_adjustment_summary(facts)

    return PlanExecutionResult(
        applied=True,
        action_family="analyze_adjustment",
        stage=plan.stage,
        result_kind="adjustment_analysis",
        workspace_refresh_targets=["ordered", "review"],
        context_summary=plan.context_summary,
        state_summary=state_summary,
        summary=state_summary,
        reply_focus=reply_focus,
        next_step_hints=next_step_hints,
        facts=facts,
    )
