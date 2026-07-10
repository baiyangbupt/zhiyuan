from __future__ import annotations

import re
from typing import Any


def _coerce_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _normalize_text_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else []
    if isinstance(values, list):
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result
    text = str(values).strip()
    return [text] if text else []


def _normalize_fix_proposal_user_line(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = (
        value.replace("修复建议", "处理建议")
        .replace("修复预览", "处理预览")
        .replace("修复方案", "处理方案")
        .replace("自动修复", "自动处理")
        .replace("修复", "处理")
        .replace("暂不允许确认应用", "需要你先取舍后再处理")
        .replace("暂不能自动处理", "建议你先人工查看或放宽条件后再试")
        .replace("候选池", "可选范围")
        .replace("放宽约束", "放宽报考条件")
        .replace("补充候选", "补充可选志愿")
        .replace("人工调整", "手动调整")
        .replace("cannot_satisfy", "")
        .replace("先作为处理方向参考", "")
        .replace("当前当前", "当前")
    )
    if normalized.strip() in {"blocked", "preview_only", "ready", "info"}:
        return ""
    return normalized.strip("。；;，, ：:").strip()


def _normalize_candidate_shortages(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        normalized = {
            "strategy": str(item.get("strategy") or "").strip(),
            "source_check_code": str(item.get("sourceCheckCode") or "").strip(),
            "scope": str(item.get("scope") or "").strip(),
            "reason_code": str(item.get("reasonCode") or "").strip(),
            "target_tier": str(item.get("targetTier") or "").strip(),
            "required_count": _coerce_non_negative_int(item.get("requiredCount")),
            "current_count": _coerce_non_negative_int(item.get("currentCount")),
            "shortage_count": _coerce_non_negative_int(item.get("shortageCount")),
            "available_count": _coerce_non_negative_int(item.get("availableCount")),
            "message": _normalize_fix_proposal_user_line(str(item.get("message") or "").strip()),
        }
        if any(normalized.values()):
            result.append(normalized)
    return result


def _fix_proposal_action_summary(action: dict[str, Any]) -> str:
    summary = str(action.get("summary") or "").strip()
    if summary:
        return summary
    action_type = str(action.get("actionType") or "").strip()
    if action_type == "replace_volunteers":
        pairs = action.get("replacementPairs") or []
        if pairs:
            return f"替换{len(pairs)}条风险志愿"
        return "替换风险志愿"
    if action_type == "remove_volunteers":
        count = len(action.get("volunteerIds") or action.get("removeVolunteerIds") or [])
        return f"移除{count}条风险志愿" if count else "移除风险志愿"
    if action_type == "fill_total_count":
        count = len(action.get("volunteerIds") or action.get("candidateVolunteerIds") or [])
        return f"补足{count}条志愿" if count else "补足志愿数量"
    return action_type or "修复动作"


def _normalize_replacement_pair(pair: dict[str, Any]) -> dict[str, str]:
    return {
        "fromUnitId": str(pair.get("fromUnitId") or pair.get("from_unit_id") or "").strip(),
        "fromVolunteerId": str(pair.get("fromVolunteerId") or pair.get("from_volunteer_id") or "").strip(),
        "toUnitId": str(pair.get("toUnitId") or pair.get("to_unit_id") or "").strip(),
        "toVolunteerId": str(pair.get("toVolunteerId") or pair.get("to_volunteer_id") or "").strip(),
    }


def _compact_fix_proposal_actions(actions: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for action in actions[:limit]:
        if not isinstance(action, dict):
            continue
        replacement_pairs = [
            normalized
            for pair in (action.get("replacementPairs") or action.get("replacement_pairs") or [])
            if isinstance(pair, dict)
            if (normalized := _normalize_replacement_pair(pair))
            if normalized["fromVolunteerId"] or normalized["fromUnitId"] or normalized["toVolunteerId"] or normalized["toUnitId"]
        ]
        compacted.append(
            {
                "actionType": str(action.get("actionType") or action.get("action_type") or "").strip(),
                "summary": _normalize_fix_proposal_user_line(str(action.get("summary") or "").strip()),
                "detail": _normalize_fix_proposal_user_line(str(action.get("detail") or "").strip()),
                "removeVolunteerIds": [
                    str(item or "").strip()
                    for item in (action.get("removeVolunteerIds") or action.get("remove_volunteer_ids") or [])
                    if str(item or "").strip()
                ][:5],
                "candidateVolunteerIds": [
                    str(item or "").strip()
                    for item in (action.get("candidateVolunteerIds") or action.get("candidate_volunteer_ids") or [])
                    if str(item or "").strip()
                ][:5],
                "replacementPairs": replacement_pairs[:5],
            }
        )
    return compacted


def _format_change_count_parts(remove_count: int, add_count: int) -> str:
    parts: list[str] = []
    if remove_count > 0:
        parts.append(f"移除{remove_count}条")
    if add_count > 0:
        parts.append(f"补入{add_count}条")
    return "、".join(parts)


def _clean_fix_apply_note(text: Any) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    if not any(marker in value for marker in _FIX_PREVIEW_BOUNDARY_MARKERS):
        return _normalize_fix_apply_user_text(value) or None
    parts = [part.strip(" ；;。") for part in re.split(r"[；;。]+", value) if part.strip(" ；;。")]
    kept = [part for part in parts if not any(marker in part for marker in _FIX_PREVIEW_BOUNDARY_MARKERS)]
    if not kept:
        return None
    return _normalize_fix_apply_user_text("；".join(kept)) or None


_FIX_PREVIEW_BOUNDARY_MARKERS = (
    "这是只读替换预览",
    "这是只读调整预览",
    "这是目标调整预览",
    "当前不会直接修改方案",
    "当前不会修改方案",
)


def _normalize_fix_apply_user_text(value: str) -> str:
    normalized = _normalize_fix_proposal_user_line(str(value or "").strip())
    if not normalized:
        return ""
    replacements = (
        ("已先形成", "本次已找到"),
        ("可参考替换", "可替换方案"),
        ("确认后会先处理已能处理的部分，剩余部分需要", "本次已处理能处理的部分；剩余部分还需要"),
        ("确认后会先处理已能处理的部分", "本次已处理能处理的部分"),
        ("确认后会按预览调整当前方案", "确认后会按这版预览调整当前方案"),
        ("已应用处理建议，并刷新当前方案状态", "已完成这次调整并刷新方案状态"),
        ("处理后仍存在相关风险或审查结果未刷新，需要继续检查", "调整后仍建议再看一次审查结果"),
        ("审查结果未刷新", "还需要再看一次审查结果"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"确认后会[^。；;]*", "", normalized)
    normalized = re.sub(r"确认后[^。；;]*", "", normalized)
    normalized = re.sub(r"[；;，, ]+$", "", normalized).strip()
    return normalized.strip("。；;，, ：:").strip()


def _fix_proposal_facts(proposal_state: dict[str, Any] | None) -> dict[str, Any]:
    state = proposal_state if isinstance(proposal_state, dict) else {}
    proposals = state.get("proposals") or []
    if not isinstance(proposals, list):
        proposals = []

    normalized: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "").strip()
        strategy = str(proposal.get("strategy") or "").strip()
        title = str(proposal.get("title") or strategy or "修复建议").strip()
        dry_run = proposal.get("dryRunResult") or {}
        if not isinstance(dry_run, dict):
            dry_run = {}
        warnings = [
            warning_text
            for item in (dry_run.get("warnings") or [])
            if (warning_text := _normalize_fix_proposal_user_line(str(item or "").strip()))
        ]
        actions = proposal.get("actions") or []
        if not isinstance(actions, list):
            actions = []
        item = {
            "proposal_id": str(proposal.get("proposalId") or "").strip(),
            "proposal_source": str(proposal.get("proposalSource") or state.get("proposalSource") or "review_check").strip(),
            "title": _normalize_fix_proposal_user_line(title) or title,
            "status": status,
            "strategy": strategy,
            "source_check_codes": [
                str(code or "").strip()
                for code in (proposal.get("sourceCheckCodes") or [])
                if str(code or "").strip()
            ],
            "requires_confirmation": bool(proposal.get("requiresConfirmation")),
            "summary": _normalize_fix_proposal_user_line(str(proposal.get("summary") or "").strip()),
            "impact": _normalize_fix_proposal_user_line(str(proposal.get("impact") or "").strip()),
            "blocking_reason": _normalize_fix_proposal_user_line(str(proposal.get("blockingReason") or "").strip()),
            "blocking_reason_codes": _normalize_text_list(proposal.get("blockingReasonCodes")),
            "candidate_shortages": _normalize_candidate_shortages(proposal.get("candidateShortages")),
            "action_summaries": [
                _fix_proposal_action_summary(action)
                for action in actions[:3]
                if isinstance(action, dict)
            ],
            "actions": _compact_fix_proposal_actions(actions),
            "dryRunObservation": dry_run,
            "remove_volunteer_count": _coerce_non_negative_int(dry_run.get("removeVolunteerCount")),
            "add_volunteer_count": _coerce_non_negative_int(dry_run.get("addVolunteerCount")),
            "remove_unit_count": _coerce_non_negative_int(dry_run.get("removeUnitCount")),
            "add_unit_count": _coerce_non_negative_int(dry_run.get("addUnitCount")),
            "warnings": warnings[:3],
        }
        normalized.append(item)
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        if strategy:
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

    return {
        "status": str(state.get("status") or "").strip(),
        "proposal_source": str(state.get("proposalSource") or "review_check").strip(),
        "source_version_guard": _coerce_non_negative_int(state.get("sourceVersionGuard")),
        "total": _coerce_non_negative_int(state.get("total") or len(normalized)),
        "status_counts": status_counts,
        "strategy_counts": strategy_counts,
        "proposals": normalized,
        "ready_count": status_counts.get("ready", 0),
        "preview_only_count": status_counts.get("preview_only", 0),
        "blocked_count": status_counts.get("blocked", 0),
    }


def _format_fix_proposal_apply_result(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").strip()
    report = result.get("repairReport") or {}
    if status != "applied":
        message = str(result.get("message") or "").strip()
        return message or "这次处理建议没有执行成功，请重新查看方案审查结果后再试。"
    title = _normalize_fix_apply_user_text(
        str(report.get("proposalTitle") or "")
        .strip()
        .replace("修复建议", "处理建议")
        .replace("修复", "处理")
        .replace("调整预览", "")
        .replace("处理预览", "")
    ).rstrip("的").strip()
    summary = _clean_fix_apply_note(report.get("proposalSummary"))
    impact = _clean_fix_apply_note(report.get("proposalImpact"))
    added = int(report.get("addedVolunteerCount") or 0)
    removed = int(report.get("removedVolunteerCount") or 0)
    post_passed = report.get("postValidationPassed")
    lines = ["已更新方案，并刷新当前方案状态。"]
    if title:
        lines.append(f"- 处理内容：{title}")
    if summary:
        lines.append(f"- 对应问题：{summary}")
    change_counts = _format_change_count_parts(removed, added)
    if change_counts:
        lines.append(f"- 调整结果：{change_counts}")
    if impact:
        lines.append(f"- 影响范围：{impact}")
    if post_passed is True:
        lines.append("- 检查结果：这次对应的问题已通过检查。")
    elif post_passed is False:
        lines.append("- 检查结果：还需要继续关注相关风险。")
    messages = [
        cleaned
        for item in (report.get("messages") or [])
        if (cleaned := _clean_fix_apply_note(item))
    ]
    if messages:
        lines.append(f"- 说明：{'；'.join(messages[:2])}")
    warnings = [
        cleaned
        for item in (report.get("warnings") or [])
        if (cleaned := _clean_fix_apply_note(item))
    ]
    if warnings:
        lines.append(f"- 需注意：{'；'.join(warnings[:2])}")
    return "\n".join(lines)
