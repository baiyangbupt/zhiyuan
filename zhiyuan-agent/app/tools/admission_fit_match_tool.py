"""Match official admission rules against the current student context."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext


FitVerdict = Literal["match", "risk", "not_match", "needs_info"]
FitDimension = Literal[
    "score_rank",
    "subjects",
    "physical_exam",
    "oral_exam",
    "eligibility",
    "budget",
]


def _score_detail_value(ctx: RunContext[RequestContext], attr: str) -> Any:
    score_detail = getattr(ctx.deps, "score_detail", None)
    return getattr(score_detail, attr, None) if score_detail is not None else None


def _student_subjects(ctx: RunContext[RequestContext]) -> list[str]:
    raw = _score_detail_value(ctx, "subject_list") or []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _append_check(
    checks: list[dict[str, Any]],
    *,
    dimension: str,
    verdict: FitVerdict,
    summary: str,
    evidence: list[str] | None = None,
    missing_fields: list[str] | None = None,
) -> None:
    checks.append(
        {
            "dimension": dimension,
            "verdict": verdict,
            "summary": summary,
            "evidence": evidence or [],
            "missing_fields": missing_fields or [],
        }
    )


def _overall_verdict(checks: list[dict[str, Any]]) -> FitVerdict:
    verdicts = {str(check.get("verdict") or "") for check in checks}
    if "not_match" in verdicts:
        return "not_match"
    if "risk" in verdicts:
        return "risk"
    if "needs_info" in verdicts:
        return "needs_info"
    return "match"


def _overall_summary(verdict: FitVerdict, *, school_name: str, major_name: str) -> str:
    target = " · ".join([item for item in [school_name, major_name] if item]) or "这个学校/专业"
    if verdict == "not_match":
        return f"{target}目前有明确不匹配项，不能只按录取概率判断。"
    if verdict == "risk":
        return f"{target}存在需要重点确认的风险项，可以继续看，但不宜当作确定可报。"
    if verdict == "needs_info":
        return f"{target}还缺关键信息，暂时只能给匹配框架，不能下最终结论。"
    return f"{target}在已提供规则和当前学生信息下没有发现明确冲突。"


def _render_user_reply(verdict: FitVerdict, checks: list[dict[str, Any]], *, school_name: str, major_name: str) -> str:
    lines = [_overall_summary(verdict, school_name=school_name, major_name=major_name), "", "逐项看："]
    for check in checks:
        lines.append(f"- {check['summary']}")
    if verdict in {"risk", "not_match", "needs_info"}:
        lines.append("")
        lines.append("下一步建议先补齐缺失项或核验官方章程，再决定是否放进方案。")
    else:
        lines.append("")
        lines.append("下一步还要结合录取概率、学费预算和方案位置判断是否值得冲。")
    return "\n".join(lines)


async def match_admission_rule_to_student(
    ctx: RunContext[RequestContext],
    school_name: str = "",
    major_name: str = "",
    rule_summary: str = "",
    rule_source_urls: list[str] | None = None,
    fit_dimensions: list[FitDimension] | None = None,
    required_subjects: list[str] | None = None,
    min_score: int = 0,
    max_rank: int = 0,
    student_rank: int = 0,
    forbidden_physical_conditions: list[str] | None = None,
    student_physical_conditions: list[str] | None = None,
    requires_oral_exam: bool | None = None,
    student_has_oral_exam: bool | None = None,
    requires_eligibility: bool | None = None,
    student_has_eligibility: bool | None = None,
    tuition_per_year: int = 0,
    budget_per_year: int = 0,
) -> str:
    """Match extracted official rule facts against the current student.

    Use this only after official school/province rules have been retrieved or
    otherwise provided. The model should pass structured facts extracted from
    those sources, not the raw web page text alone.
    """
    dimensions = [str(item or "").strip() for item in fit_dimensions or [] if str(item or "").strip()]
    if not dimensions:
        dimensions = ["subjects", "score_rank", "physical_exam", "oral_exam", "eligibility", "budget"]

    checks: list[dict[str, Any]] = []
    source_urls = [str(item or "").strip() for item in rule_source_urls or [] if str(item or "").strip()]

    if "subjects" in dimensions:
        student_subjects = _student_subjects(ctx)
        required = [str(item or "").strip() for item in required_subjects or [] if str(item or "").strip()]
        if required and student_subjects:
            missing_subjects = [item for item in required if item not in student_subjects]
            if missing_subjects:
                _append_check(
                    checks,
                    dimension="subjects",
                    verdict="not_match",
                    summary=f"选科不匹配：规则要求{'、'.join(required)}，当前选科为{'、'.join(student_subjects)}。",
                    evidence=source_urls,
                )
            else:
                _append_check(
                    checks,
                    dimension="subjects",
                    verdict="match",
                    summary=f"选科匹配：规则要求{'、'.join(required)}，当前选科已覆盖。",
                    evidence=source_urls,
                )
        elif required and not student_subjects:
            _append_check(
                checks,
                dimension="subjects",
                verdict="needs_info",
                summary=f"规则有选科要求（{'、'.join(required)}），但当前没有学生选科信息。",
                evidence=source_urls,
                missing_fields=["选科"],
            )
        else:
            _append_check(
                checks,
                dimension="subjects",
                verdict="needs_info",
                summary="暂未拿到明确选科要求，不能判断选科是否匹配。",
                missing_fields=["官方选科要求"],
            )

    if "score_rank" in dimensions:
        student_score = int(_score_detail_value(ctx, "total_score") or 0)
        if min_score and student_score:
            verdict: FitVerdict = "match" if student_score >= min_score else "risk"
            _append_check(
                checks,
                dimension="score_rank",
                verdict=verdict,
                summary=f"分数参考：当前总分{student_score}，规则/历史参考分{min_score}。",
                evidence=source_urls,
            )
        elif max_rank and student_rank:
            verdict = "match" if student_rank <= max_rank else "risk"
            _append_check(
                checks,
                dimension="score_rank",
                verdict=verdict,
                summary=f"位次参考：当前位次{student_rank}，规则/历史参考位次{max_rank}。",
                evidence=source_urls,
            )
        else:
            _append_check(
                checks,
                dimension="score_rank",
                verdict="needs_info",
                summary="还缺可比的位次/分数参考，不能判断录取适配。",
                missing_fields=["学生位次", "院校/专业近年位次或分数"],
            )

    if "physical_exam" in dimensions:
        forbidden = [str(item or "").strip() for item in forbidden_physical_conditions or [] if str(item or "").strip()]
        student_conditions = [
            str(item or "").strip() for item in student_physical_conditions or [] if str(item or "").strip()
        ]
        if forbidden and student_conditions:
            matched = [item for item in forbidden if item in student_conditions]
            verdict = "not_match" if matched else "match"
            summary = (
                f"体检限制冲突：学生存在{'、'.join(matched)}。"
                if matched
                else "体检限制未发现明确冲突。"
            )
            _append_check(checks, dimension="physical_exam", verdict=verdict, summary=summary, evidence=source_urls)
        elif forbidden:
            _append_check(
                checks,
                dimension="physical_exam",
                verdict="needs_info",
                summary=f"规则提到体检限制（{'、'.join(forbidden)}），但当前缺学生体检结论。",
                evidence=source_urls,
                missing_fields=["体检结论"],
            )

    if "oral_exam" in dimensions and requires_oral_exam is not None:
        if requires_oral_exam and student_has_oral_exam is False:
            _append_check(
                checks,
                dimension="oral_exam",
                verdict="not_match",
                summary="口试不匹配：规则要求英语口试，但学生当前未确认已参加或通过。",
                evidence=source_urls,
            )
        elif requires_oral_exam and student_has_oral_exam is None:
            _append_check(
                checks,
                dimension="oral_exam",
                verdict="needs_info",
                summary="规则要求英语口试，但当前缺口试状态。",
                evidence=source_urls,
                missing_fields=["英语口试状态"],
            )
        else:
            _append_check(
                checks,
                dimension="oral_exam",
                verdict="match",
                summary="口试要求未发现明确冲突。",
                evidence=source_urls,
            )

    if "eligibility" in dimensions and requires_eligibility is not None:
        if requires_eligibility and student_has_eligibility is False:
            _append_check(
                checks,
                dimension="eligibility",
                verdict="not_match",
                summary="资格不匹配：规则要求专项/定向等资格，但学生当前没有确认资格。",
                evidence=source_urls,
            )
        elif requires_eligibility and student_has_eligibility is None:
            _append_check(
                checks,
                dimension="eligibility",
                verdict="needs_info",
                summary="规则要求专项/定向等资格，但当前缺资格审核结果。",
                evidence=source_urls,
                missing_fields=["资格审核结果"],
            )
        else:
            _append_check(
                checks,
                dimension="eligibility",
                verdict="match",
                summary="资格要求未发现明确冲突。",
                evidence=source_urls,
            )

    if "budget" in dimensions:
        if tuition_per_year and budget_per_year:
            verdict = "match" if tuition_per_year <= budget_per_year else "risk"
            _append_check(
                checks,
                dimension="budget",
                verdict=verdict,
                summary=f"学费预算：学费约{tuition_per_year}元/年，预算上限{budget_per_year}元/年。",
                evidence=source_urls,
            )
        elif tuition_per_year:
            _append_check(
                checks,
                dimension="budget",
                verdict="needs_info",
                summary=f"已知学费约{tuition_per_year}元/年，但缺家庭可接受预算上限。",
                evidence=source_urls,
                missing_fields=["可接受学费上限"],
            )

    if not checks:
        _append_check(
            checks,
            dimension="general",
            verdict="needs_info",
            summary="还没有可匹配的结构化规则事实，需要先检索或抽取学校/专业要求。",
            missing_fields=["官方规则摘要"],
        )

    verdict = _overall_verdict(checks)
    reply = _render_user_reply(verdict, checks, school_name=school_name, major_name=major_name)
    return json.dumps(
        {
            "reply_strategy": "direct_reply",
            "result_kind": "admission_fit_match",
            "verdict": verdict,
            "school_name": school_name,
            "major_name": major_name,
            "rule_summary": rule_summary,
            "rule_source_urls": source_urls,
            "checks": checks,
            "summary": reply,
            "no_mutation": True,
        },
        ensure_ascii=False,
    )
