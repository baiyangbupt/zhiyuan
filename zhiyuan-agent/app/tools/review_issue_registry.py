from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

ReviewIssueScopeKind = Literal["item_removal", "structural", "informational"]


@dataclass(frozen=True)
class ReviewIssueRule:
    code: str
    label: str
    scope_kind: ReviewIssueScopeKind
    default_action_family: str | None


_REVIEW_ISSUE_RULES: dict[str, ReviewIssueRule] = {
    "high_tuition": ReviewIssueRule(
        code="high_tuition",
        label="高收费",
        scope_kind="item_removal",
        default_action_family="remove_units",
    ),
    "cooperative_program": ReviewIssueRule(
        code="cooperative_program",
        label="中外合作",
        scope_kind="item_removal",
        default_action_family="remove_units",
    ),
    "admission_limit": ReviewIssueRule(
        code="admission_limit",
        label="限报条件",
        scope_kind="item_removal",
        default_action_family="remove_units",
    ),
    "special_enrollment": ReviewIssueRule(
        code="special_enrollment",
        label="特殊类型招生",
        scope_kind="item_removal",
        default_action_family="remove_units",
    ),
    "probability_inversion": ReviewIssueRule(
        code="probability_inversion",
        label="概率倒挂",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "probability_gap": ReviewIssueRule(
        code="probability_gap",
        label="梯度断层",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "ratio_distribution": ReviewIssueRule(
        code="ratio_distribution",
        label="冲稳保配比",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "safety_guard": ReviewIssueRule(
        code="safety_guard",
        label="本省保底不足",
        scope_kind="structural",
        default_action_family="preview_compensation",
    ),
    "count_validation": ReviewIssueRule(
        code="count_validation",
        label="数量缺口",
        scope_kind="structural",
        default_action_family="preview_compensation",
    ),
    "edge_score": ReviewIssueRule(
        code="edge_score",
        label="边缘分",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "major_group_safety_intent_alignment": ReviewIssueRule(
        code="major_group_safety_intent_alignment",
        label="非意向托底",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "group_inner_safety_guard": ReviewIssueRule(
        code="group_inner_safety_guard",
        label="组内安全垫不足",
        scope_kind="structural",
        default_action_family="analyze_adjustment",
    ),
    "plan_update_notice": ReviewIssueRule(
        code="plan_update_notice",
        label="招生计划更新提示",
        scope_kind="informational",
        default_action_family=None,
    ),
    "adjustment_notice": ReviewIssueRule(
        code="adjustment_notice",
        label="调剂风险提示",
        scope_kind="informational",
        default_action_family=None,
    ),
}


def get_review_issue_rule(code: str | None) -> ReviewIssueRule | None:
    return _REVIEW_ISSUE_RULES.get(str(code or "").strip())


def review_issue_label(code: str | None, summary: str | None = None) -> str:
    rule = get_review_issue_rule(code)
    if rule:
        return rule.label
    text = str(summary or code or "").strip()
    return text or str(code or "").strip() or "审查问题"


def review_issue_scope_kind(code: str | None) -> ReviewIssueScopeKind:
    rule = get_review_issue_rule(code)
    if rule:
        return rule.scope_kind
    return "structural"


def review_issue_default_action_family(code: str | None) -> str | None:
    rule = get_review_issue_rule(code)
    return rule.default_action_family if rule else None


def review_issue_supported_action_families(code: str | None) -> list[str]:
    scope_kind = review_issue_scope_kind(code)
    if scope_kind == "item_removal":
        return ["remove_units", "replace_units"]
    if scope_kind == "structural":
        default_action = review_issue_default_action_family(code)
        return [default_action] if default_action else ["analyze_adjustment"]
    return []


def _ordered_unit_id_for_item(item: dict[str, Any]) -> str:
    volunteer_id = str(item.get("volunteerId") or "").strip()
    if volunteer_id:
        separator = volunteer_id.find("_")
        if separator > 0:
            return volunteer_id[:separator]
        return volunteer_id
    return str(item.get("schoolName") or "").strip()


def _format_plan_item_brief(item: dict[str, Any]) -> str:
    school_name = str(item.get("schoolName") or "").strip()
    major_name = str(item.get("majorName") or "").strip()
    if not major_name:
        major_items = item.get("majorItems") or []
        if major_items:
            first_major = major_items[0] if isinstance(major_items[0], dict) else {}
            major_name = str(first_major.get("majorName") or "").strip()
    text = school_name
    if school_name and major_name:
        text = f"{school_name}-{major_name}"
    elif major_name:
        text = major_name
    position = item.get("position")
    if position is not None and str(position).strip():
        text = f"{text}@{position}"
    return text


def build_review_issue_scopes(
    checks: list[dict[str, Any]],
    plan_items: list[dict[str, Any]] | None,
    *,
    limit_checks: int | None = None,
    only_failed: bool = True,
    include_affected_ids: bool = False,
) -> list[dict[str, Any]]:
    item_by_id = {
        str(item.get("volunteerId") or "").strip(): item
        for item in (plan_items or [])
        if str(item.get("volunteerId") or "").strip()
    }
    scopes: list[dict[str, Any]] = []
    for check in checks or []:
        if only_failed and check.get("passed") is True:
            continue
        code = str(check.get("code") or "").strip()
        summary = str(check.get("summary") or "").strip()
        if not code:
            continue
        if not summary:
            summary = review_issue_label(code)
        affected_volunteer_ids = []
        seen_volunteer_ids: set[str] = set()
        for volunteer_id in (check.get("affectedVolunteerIds") or []):
            normalized = str(volunteer_id or "").strip()
            if not normalized or normalized in seen_volunteer_ids:
                continue
            seen_volunteer_ids.add(normalized)
            affected_volunteer_ids.append(normalized)
        affected_unit_ids = []
        seen_unit_ids: set[str] = set()
        for unit_id in (check.get("affectedUnitIds") or []):
            normalized = str(unit_id or "").strip()
            if not normalized or normalized in seen_unit_ids:
                continue
            seen_unit_ids.add(normalized)
            affected_unit_ids.append(normalized)
        if not affected_unit_ids:
            for volunteer_id in affected_volunteer_ids:
                item = item_by_id.get(volunteer_id)
                if not item:
                    continue
                unit_id = _ordered_unit_id_for_item(item)
                if not unit_id or unit_id in seen_unit_ids:
                    continue
                seen_unit_ids.add(unit_id)
                affected_unit_ids.append(unit_id)
        sample_items: list[str] = []
        for volunteer_id in affected_volunteer_ids:
            item = item_by_id.get(volunteer_id)
            if not item:
                continue
            sample_items.append(_format_plan_item_brief(item))
            if len(sample_items) >= 2:
                break
        scope = {
            "code": code,
            "label": review_issue_label(code, summary),
            "summary": summary,
            "level": str(check.get("level") or "").strip(),
            "scope_kind": review_issue_scope_kind(code),
            "default_action_family": review_issue_default_action_family(code),
            "supported_action_families": review_issue_supported_action_families(code),
            "affected_unit_count": len(affected_unit_ids),
            "affected_volunteer_count": len(affected_volunteer_ids),
            "sample_items": sample_items,
            "suggested_action": str(check.get("suggestedAction") or "").strip(),
            "scope_fingerprint": hashlib.sha1(
                "|".join(
                    [
                        code,
                        summary,
                        ",".join(affected_unit_ids),
                        ",".join(affected_volunteer_ids),
                    ]
                ).encode("utf-8")
            ).hexdigest()[:16],
        }
        if include_affected_ids:
            scope["affected_unit_ids"] = affected_unit_ids
            scope["affected_volunteer_ids"] = affected_volunteer_ids
        scopes.append(scope)
        if limit_checks is not None and len(scopes) >= limit_checks:
            break
    return scopes


def summarize_review_issue_scope(issue: dict[str, Any]) -> str:
    label = str(issue.get("label") or issue.get("code") or "issue").strip()
    unit_count = int(issue.get("affected_unit_count") or 0)
    volunteer_count = int(issue.get("affected_volunteer_count") or 0)
    if unit_count > 0 or volunteer_count > 0:
        return f"{label}({unit_count}u/{volunteer_count}v)"
    return label
