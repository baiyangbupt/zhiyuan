"""Read-only admission policy/process consultation orchestration."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.config import BochaSearchConfig


ConsultationScope = Literal[
    "general_policy",
    "province_policy",
    "school_rule",
    "school_user_fit",
    "plan_policy_impact",
    "missing_info",
]

RuleDomain = Literal[
    "general",
    "score_batch",
    "application_process",
    "eligibility",
    "physical_exam",
    "oral_exam",
    "subject_requirement",
    "transfer_major",
    "tuition_budget",
    "admission_fit",
]

SourceStrategy = Literal[
    "auto",
    "web_official",
    "province_official",
    "school_brochure",
    "province_and_school",
    "profile_match",
    "plan_impact",
]

FitDimension = Literal[
    "score_rank",
    "subjects",
    "physical_exam",
    "oral_exam",
    "eligibility",
    "budget",
    "major_interest",
    "region_interest",
    "plan_position",
]


def _score_detail_value(ctx: RunContext[RequestContext], attr: str) -> Any:
    score_detail = getattr(ctx.deps, "score_detail", None)
    return getattr(score_detail, attr, None) if score_detail is not None else None


def _context_province(ctx: RunContext[RequestContext], explicit_province: str = "") -> str:
    return str(explicit_province or _score_detail_value(ctx, "province") or "").strip()


def _context_subjects(ctx: RunContext[RequestContext]) -> list[str]:
    raw = _score_detail_value(ctx, "subject_list")
    if not raw:
        return []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _context_has_score(ctx: RunContext[RequestContext]) -> bool:
    return bool(_score_detail_value(ctx, "total_score"))


def _normalize_fit_dimensions(values: list[FitDimension] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _source_strategy(scope: ConsultationScope, domain: RuleDomain, requested: SourceStrategy) -> SourceStrategy:
    if requested != "auto":
        return requested
    if scope == "general_policy":
        return "web_official"
    if scope == "province_policy":
        return "province_official"
    if scope == "school_rule":
        return "school_brochure"
    if scope == "school_user_fit":
        if domain in {"score_batch", "application_process", "eligibility", "oral_exam"}:
            return "province_and_school"
        return "profile_match"
    if scope == "plan_policy_impact":
        return "plan_impact"
    return "web_official"


def _required_sources(strategy: SourceStrategy, *, province: str, school_name: str, year: int) -> list[str]:
    year_text = f"{year}年" if year else "当年"
    province_target = f"{province}省级考试院" if province else "所在省省级考试院"
    school_target = school_name or "目标院校"
    if strategy == "web_official":
        return [f"教育部/阳光高考/省考试院等官方公开来源（{year_text}优先）"]
    if strategy == "province_official":
        return [f"{province_target}{year_text}政策、批次线、一分一段或资格审核通知"]
    if strategy == "school_brochure":
        return [f"{school_target}{year_text}招生章程、招生简章、招生办通知或转专业办法"]
    if strategy == "province_and_school":
        return [
            f"{province_target}{year_text}政策、批次线、一分一段或资格审核通知",
            f"{school_target}{year_text}招生章程、招生简章、专业备注或收费说明",
        ]
    if strategy == "profile_match":
        return [f"{school_target}{year_text}招生章程、专业备注、收费说明或转专业办法", "当前学生成绩、选科、体检、资格和预算信息"]
    if strategy == "plan_impact":
        return ["当前方案/候选数据", "相关省级政策或院校招生章程"]
    return []


def _missing_fields(
    scope: ConsultationScope,
    domain: RuleDomain,
    ctx: RunContext[RequestContext],
    *,
    province: str,
    school_name: str,
    major_name: str,
    fit_dimensions: list[str],
) -> list[str]:
    missing: list[str] = []
    if scope in {"province_policy", "school_user_fit", "plan_policy_impact"} and not province:
        missing.append("高考省份")
    if scope in {"school_rule", "school_user_fit"} and not school_name:
        missing.append("目标院校")
    if domain in {"subject_requirement", "physical_exam", "oral_exam", "transfer_major", "tuition_budget"} and not major_name:
        missing.append("目标专业或专业组")
    if scope == "school_user_fit":
        if ("score_rank" in fit_dimensions or domain in {"score_batch", "admission_fit"}) and not _context_has_score(ctx):
            missing.append("总分和位次")
        if ("subjects" in fit_dimensions or domain == "subject_requirement") and not _context_subjects(ctx):
            missing.append("选科")
        if "physical_exam" in fit_dimensions or domain == "physical_exam":
            missing.append("体检结论")
        if "oral_exam" in fit_dimensions or domain == "oral_exam":
            missing.append("英语口试状态")
        if "eligibility" in fit_dimensions or domain == "eligibility":
            missing.append("专项/定向等资格审核结果")
        if "budget" in fit_dimensions or domain == "tuition_budget":
            missing.append("可接受学费上限")
    if scope == "missing_info":
        if not province:
            missing.append("高考省份")
        if not _context_has_score(ctx):
            missing.append("总分")
        missing.extend(
            [
                "位次或一分一段位置",
                "目标批次线",
                "体检受限项",
                "英语口试/专项计划等资格",
                "地域、专业、院校偏好和排除项",
                "家庭预算与可接受学费上限",
            ]
        )
    deduped: list[str] = []
    for item in missing:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _domain_label(domain: RuleDomain) -> str:
    return {
        "general": "报考规则",
        "score_batch": "分数、位次和批次线",
        "application_process": "填报流程",
        "eligibility": "资格条件",
        "physical_exam": "体检限制",
        "oral_exam": "英语口试",
        "subject_requirement": "选科要求",
        "transfer_major": "转专业",
        "tuition_budget": "学费预算",
        "admission_fit": "录取适配",
    }.get(domain, "报考规则")


def _render_score_batch() -> str:
    return (
        "分数、排名/位次和批次线要分开看：分数受试卷难度影响，排名/位次更接近真实竞争位置；批次线决定批次边界，不能直接替代院校和专业的录取位次。"
        "批次线出来前可以用模考排名和往年一分一段做预案，出分后必须用官方一分一段、批次线和当年招生计划重算。"
        "方案里重点看录取概率、近三年位次/分数、招生计划变化，以及冲稳保梯度。"
    )


def _render_eligibility() -> str:
    return (
        "资格限制类问题不能只靠口头描述判断。专项计划要看实施区域、户籍、学籍、报名审核和公示结果；农村户口不等于一定有专项资格。"
        "体检、色弱、视力、口试、选科等限制，还要逐条核对目标专业或专业组备注。没有通过资格审核或官方明确限制的，不能当成可用志愿。"
    )


def _render_school_rule(school_name: str) -> str:
    school_part = school_name or "目标院校"
    return (
        f"{school_part}相关问题要先找到该校当年的招生章程、招生简章、招生办通知或校内办法。"
        "转专业通常看大一成绩排名、课程成绩、是否挂科、接收名额、目标专业考核，以及是否允许跨学院或转入热门专业。"
        "收费、培养地点、中外合作、单列专业、体检和专业备注也都属于学校侧规则，不能只按通用经验下结论。"
    )


def _render_tuition() -> str:
    return (
        "学校好但学费高，可以作为冲刺选择，但要把它从录取风险扩展成四年成本风险：学费、住宿、生活费、中外合作额外费用、家庭现金流都要算。"
        "方案里可以少量放冲区或稳区，但保区要保留符合家庭预算、学费可承受、专业也能接受的选择。民办、中外合作、校企合作和单列专业要重点看收费标准和能否转专业。"
    )


def _render_application_process() -> str:
    return (
        "流程类问题先判断影响点：能不能填、什么时候填、填后怎么投档录取、后续能否调整。"
        "征集志愿、退档、投档比例、平行志愿顺序、服从调剂等都要以所在省当年录取规则为准。"
        "如果问题会影响当前方案，需要再读取方案里的学校、专业组、批次和风险分布。"
    )


def _render_missing_info(ctx: RunContext[RequestContext], *, province: str) -> str:
    subject_text = "、".join(_context_subjects(ctx)) or "还未确认"
    score_text = str(_score_detail_value(ctx, "total_score") or "还未确认")
    province_text = province or "还未确认"
    return (
        "现在要把判断做准，最需要补这些信息：\n"
        f"1. 基础成绩：省份（{province_text}）、总分（{score_text}）、位次或一分一段位置、选科（{subject_text}）。\n"
        "2. 批次边界：目标批次线、是否压线、是否考虑本科和专科兜底。\n"
        "3. 资格限制：体检受限项、英语口试、专项计划、是否有定向或单列资格。\n"
        "4. 选择偏好：地域、专业、院校层次、不能接受的专业或城市。\n"
        "5. 家庭诉求：可接受学费上限、是否接受民办/中外合作/校企合作。\n"
        "6. 方案目标：更重视学校层次、专业确定性、就业稳定，还是保底安全。"
    )


def _render_domain_framework(
    scope: ConsultationScope,
    domain: RuleDomain,
    ctx: RunContext[RequestContext],
    *,
    province: str,
    school_name: str,
) -> str:
    if scope == "missing_info":
        return _render_missing_info(ctx, province=province)
    if domain == "score_batch":
        return _render_score_batch()
    if domain in {"eligibility", "physical_exam", "oral_exam", "subject_requirement"}:
        return _render_eligibility()
    if domain == "tuition_budget":
        return _render_tuition()
    if domain == "transfer_major" or scope in {"school_rule", "school_user_fit"}:
        return _render_school_rule(school_name)
    if domain == "application_process":
        return _render_application_process()
    return (
        "这类问题先区分通用规则、省级政策、学校章程和个人适配。通用规则可以先给判断框架；"
        "涉及具体省份、具体学校、具体专业或当前学生能不能填时，需要进一步核验官方来源和学生信息。"
    )


def _scope_prefix(scope: ConsultationScope) -> str:
    return {
        "general_policy": "这是通用报考规则/流程咨询。",
        "province_policy": "这是省级政策或资格咨询。",
        "school_rule": "这是具体学校/专业规则咨询。",
        "school_user_fit": "这是学校或专业与当前学生的适配性判断。",
        "plan_policy_impact": "这个问题需要结合规则和方案位置一起判断。",
        "missing_info": "这是信息完整度检查。",
    }.get(scope, "这是报考规则咨询。")


def _next_step_line(scope: ConsultationScope, strategy: SourceStrategy, missing_fields: list[str]) -> str:
    if scope == "plan_policy_impact":
        return "下一步需要读取当前方案或候选数据，再判断哪些志愿受影响。"
    if scope == "school_user_fit":
        if missing_fields:
            return "下一步先补齐缺失信息，再把学校章程里的规则和学生情况逐项匹配。"
        return "下一步可以把学校章程里的选科、体检、收费、转专业等规则和当前学生信息逐项匹配。"
    if strategy in {"province_official", "school_brochure", "province_and_school", "profile_match"}:
        return "下一步要核验对应官方材料，不要只按经验下最终结论。"
    if strategy == "web_official":
        return "下一步如需精确到年份和省份，应检索官方来源后再确认。"
    return "下一步可以补充省份、学校、专业或方案上下文，我再按对应范围判断。"


async def answer_admission_policy_question(
    ctx: RunContext[RequestContext],
    question: str,
    consultation_scope: ConsultationScope = "general_policy",
    rule_domain: RuleDomain = "general",
    source_strategy: SourceStrategy = "auto",
    fit_dimensions: list[FitDimension] | None = None,
    province: str = "",
    school_name: str = "",
    major_name: str = "",
    year: int = 0,
) -> str:
    """Classify and answer read-only admission policy/process questions.

    This tool is an orchestration entry for three levels:
    1. general policy/process questions that can use official web search,
    2. school-specific rule questions that require school brochures/notices,
    3. school/program-to-student fit questions that require matching official
       rules against the student's score, rank, subjects, physical exam,
       eligibility, budget and/or current plan.

    The current implementation does not perform live web/RAG lookup. It returns
    a source-aware framework, required source types, missing fields and matching
    requirements so the main agent does not misroute these questions into
    intent mutation or plan status queries.
    """
    normalized_scope: ConsultationScope = consultation_scope or "general_policy"
    normalized_domain: RuleDomain = rule_domain or "general"
    resolved_province = _context_province(ctx, province)
    resolved_school = str(school_name or "").strip()
    resolved_major = str(major_name or "").strip()
    resolved_fit_dimensions = _normalize_fit_dimensions(fit_dimensions)
    resolved_strategy = _source_strategy(normalized_scope, normalized_domain, source_strategy or "auto")
    sources = _required_sources(resolved_strategy, province=resolved_province, school_name=resolved_school, year=year)
    source_lookup_required = resolved_strategy in {
        "web_official",
        "province_official",
        "school_brochure",
        "province_and_school",
        "profile_match",
    }
    source_lookup_available = source_lookup_required and bool(BochaSearchConfig().api_key)
    missing = _missing_fields(
        normalized_scope,
        normalized_domain,
        ctx,
        province=resolved_province,
        school_name=resolved_school,
        major_name=resolved_major,
        fit_dimensions=resolved_fit_dimensions,
    )
    framework = _render_domain_framework(
        normalized_scope,
        normalized_domain,
        ctx,
        province=resolved_province,
        school_name=resolved_school,
    )
    source_line = "需要核验的来源：" + "；".join(sources) if sources else "这轮可以先按通用方法判断。"
    missing_line = f"还缺：{'、'.join(missing)}。" if missing else "当前可先给判断框架。"
    next_step = _next_step_line(normalized_scope, resolved_strategy, missing)
    summary = (
        f"{_scope_prefix(normalized_scope)}\n\n"
        f"{framework}\n\n"
        f"{source_line}\n"
        f"{missing_line}\n"
        f"{next_step}"
    )
    payload = {
        "reply_strategy": (
            "continue_model"
            if (source_lookup_required and source_lookup_available) or normalized_scope == "plan_policy_impact"
            else "direct_reply"
        ),
        "result_kind": "admission_policy_consultation",
        "question": question,
        "consultation_scope": normalized_scope,
        "rule_domain": normalized_domain,
        "domain_label": _domain_label(normalized_domain),
        "source_strategy": resolved_strategy,
        "source_lookup_required": source_lookup_required,
        "source_lookup_available": source_lookup_available,
        "required_sources": sources,
        "official_source_hint": "；".join(sources),
        "fit_required": normalized_scope == "school_user_fit",
        "fit_dimensions": resolved_fit_dimensions,
        "plan_lookup_required": normalized_scope == "plan_policy_impact",
        "province": resolved_province,
        "school_name": resolved_school,
        "major_name": resolved_major,
        "year": year or None,
        "missing_fields": missing,
        "no_mutation": True,
        "summary": summary,
    }
    return json.dumps(payload, ensure_ascii=False)
