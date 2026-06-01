"""Direction-oriented explore tools.

Handles exploratory analysis for direction-like user asks such as
"体制内适不适合" without mixing confirmation / intent-writing logic.
"""

from __future__ import annotations

import json
import logging
import asyncio
import re
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agent.context import RequestContext
from app.config import LLMConfig
from app.domain.career_planning import resolve_career_planning_policy
from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_LABEL_MAP,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    is_career_slot,
    normalize_career_slots,
    to_career_label,
)
from app.llm.client import LLMClient
from app.schemas.career_intent import CareerIntentResult
from app.tools.extraction_json import parse_extraction_json
from app.util.internal_client import get_planning_state, get_planning_workspace_state, query_planning_candidate_pool

logger = logging.getLogger(__name__)

INTENT_MODE_PREFERENCE = "preference"
ANALYSIS_STAGE_INTEREST = "interest"
_PUBLIC_SERVICE_EVIDENCE = {
    "schoolCategory": ["师范", "政法", "财经", "农林", "医药"],
    "majorName": ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"],
    "majorCategory": ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"],
    "majorDiscipline": ["法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思"],
}
_PUBLIC_SERVICE_TAG_EVIDENCE = ["师范", "政法", "财经", "农林", "医药", "部委院校", "公安", "警校"]
_STABLE_EMPLOYMENT_EVIDENCE = {
    "schoolNature": ["公办"],
    "schoolCategory": ["师范", "医药", "政法", "农林"],
    "majorName": ["师范", "教育", "护理", "医学", "药学", "法学", "行政管理"],
    "majorCategory": ["教育", "医学", "法学", "管理"],
}
_FURTHER_STUDY_TAG_EVIDENCE = ["保研", "双一流", "985", "211", "国重点", "省重点", "博士点", "硕士点", "升学率"]
_MARKET_EMPLOYMENT_EVIDENCE = {
    "schoolCategory": ["理工", "财经", "综合"],
    "majorName": ["计算机", "软件", "电子", "信息", "人工智能", "数据", "自动化", "通信", "金融", "会计", "审计", "市场营销", "电子商务", "数字媒体"],
    "majorCategory": ["计算机", "电子信息", "自动化", "金融", "工商管理", "电子商务", "新闻传播"],
    "majorDiscipline": ["工学", "经济学", "管理学"],
}
_MARKET_EMPLOYMENT_TAG_EVIDENCE = ["就业", "产业", "校企", "实习", "互联网", "金融", "人工智能", "大数据", "软件", "数字"]

_INTEREST_ACTIONS_PREFERENCE = [
    {
        "label": "先看看候选里有没有",
        "message": "先看看候选里有没有",
        "actionType": "candidate_query",
    },
    {
        "label": "看看现在这份方案合不合适",
        "message": "看看现在这份方案合不合适",
        "actionType": "plan_analyze",
    },
    {
        "label": "以后优先按这个方向看",
        "message": "以后优先按这个方向看",
        "actionType": "prefer_confirm",
    },
]

_direction_analysis_llm_client: LLMClient | None = None
_direction_analysis_agent: Agent[None, str] | None = None
_career_direction_resolver_agent: Agent[None, str] | None = None
_CAREER_DIRECTION_ROUTE_CACHE_ATTR = "_career_direction_route_decision_cache"
_GENERIC_DIRECTION_LLM_TIMEOUT_SECONDS = 90


class DirectionAnalysisDraft(BaseModel):
    summaryTitle: str = ""
    currentPlanFit: list[str] = Field(default_factory=list)
    currentPlanConflict: list[str] = Field(default_factory=list)
    candidateOpportunity: list[str] = Field(default_factory=list)
    nextActionHints: list[str] = Field(default_factory=list)
    planOverview: list[str] = Field(default_factory=list)


class CareerDirectionRouteDecision(CareerIntentResult):
    shouldAnalyze: bool = False
    reason: str = ""


def _contains_preference_keywords(values: list[str] | None, keywords: list[str]) -> list[str]:
    matched: list[str] = []
    for value in values or []:
        text = str(value or "")
        if any(keyword and keyword in text for keyword in keywords):
            matched.append(text)
    return matched


def _build_student_fit_fact(
    direction_slot: str,
    request_context: RequestContext,
    planning_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = getattr(request_context, "score_detail", None)
    profile = getattr(request_context, "init_profile", None)
    career_policy = resolve_career_planning_policy(score)
    latent_profile = (((planning_state or {}).get("profileState") or {}).get("latentProfile") or {})
    future_development = (latent_profile.get("futureDevelopment") or {}).get("careerTypes") or []

    positive_signals: list[str] = []
    caution_signals: list[str] = []

    subjects = score.subject_list if score else []
    preferred_majors = list((profile.major.level2 or [])) if profile else []
    negative_majors = list((profile.major.negative_level2 or [])) if profile else []
    preferred_provinces = list((profile.city.province or [])) if profile else []

    if subjects:
        positive_signals.append(f"你的当前选科是{'、'.join(subjects)}，这至少没有把这条方向直接挡住。")
    if career_policy.employment_first:
        caution_signals.append(career_policy.summary)
    if direction_slot in future_development:
        positive_signals.append(f"你当前的长期发展倾向里已经出现了“{to_career_label(direction_slot)}”，说明这不是完全游离的新想法。")

    if direction_slot == CAREER_SYSTEM_PUBLIC_SERVICE:
        aligned = _contains_preference_keywords(
            preferred_majors,
            ["法学", "教育", "师范", "汉语言", "中国语言", "行政管理", "公共管理", "政治学", "马克思"],
        )
        technical = _contains_preference_keywords(
            preferred_majors,
            ["计算机", "电子", "信息", "自动化", "软件", "数据", "人工智能", "通信"],
        )
        if aligned:
            positive_signals.append(f"你当前已经表现出对{ '、'.join(aligned[:2]) }这类方向的兴趣，这和体制内/考公路径是有承接关系的。")
        if technical:
            caution_signals.append(f"你现在的兴趣又明显偏向{ '、'.join(technical[:2]) }，所以更适合继续分清是看体制内技术岗，还是看更传统的考公对口路径。")
        if negative_majors and not aligned:
            caution_signals.append("如果你后面更看重体制内，需要同步确认自己是否接受与之更相关的专业路径，而不是只看岗位想象。")
    elif direction_slot == CAREER_STABLE_EMPLOYMENT:
        if preferred_majors:
            positive_signals.append(f"你当前已经有比较明确的专业兴趣（{ '、'.join(preferred_majors[:2]) }），这有助于继续判断哪些路径的就业确定性更高。")
        if negative_majors:
            caution_signals.append(f"你已经明确排斥{ '、'.join(negative_majors[:2]) }这类方向，所以后面看稳定就业时，不能只看稳定，还要看你自己是否愿意读。")
        positive_signals.append("稳定就业更适合拿来比较‘就业确定性、岗位稳定性和路径清晰度’，而不是只看一时热度。")
        if career_policy.employment_first:
            positive_signals.append("按你当前这个分数段，先把方向收敛到更容易就业、岗位需求更稳的专业线，会比先谈深造更务实。")
    elif direction_slot == CAREER_FURTHER_STUDY:
        if preferred_majors:
            positive_signals.append(f"你已经有在意的专业方向（{ '、'.join(preferred_majors[:2]) }），这有利于继续比较哪些路径更适合读研或长期深造。")
        if negative_majors:
            caution_signals.append(f"你已经排除了{ '、'.join(negative_majors[:2]) }这类方向，所以后面看深造时，也要注意别把升学通道和专业接受度割裂开。")
        positive_signals.append("深造方向更适合重点比较培养平台、升学通道和长期学习投入，而不只是看当前录取概率。")
        if career_policy.employment_first:
            caution_signals.append("以你当前这个分数段，现阶段不建议把“深造”当成优先目标；更合适的做法是先看毕业后的就业承接，再决定是否把升学作为后续增益。")
    elif direction_slot == CAREER_MARKET_EMPLOYMENT:
        market_aligned = _contains_preference_keywords(
            preferred_majors,
            ["计算机", "电子", "信息", "软件", "数据", "人工智能", "自动化", "通信", "金融", "会计", "审计", "电子商务", "数字媒体"],
        )
        if market_aligned:
            positive_signals.append(f"你当前关注的{ '、'.join(market_aligned[:2]) }，和企业就业、产业岗位、大城市机会的连接比较直接。")
        if preferred_provinces:
            positive_signals.append("市场化就业更依赖城市产业和实习机会，你已有地域倾向，后面可以把城市机会一起纳入比较。")
        positive_signals.append("市场化就业导向更适合比较行业机会、实习资源、岗位面和技能可迁移性，不只看学校层次。")
        if negative_majors:
            caution_signals.append(f"你已经明确排斥{ '、'.join(negative_majors[:2]) }这类方向，所以看企业就业时也要避开自己接受度低的专业线。")

    if preferred_provinces:
        positive_signals.append(f"你现在已有的地域倾向是{'、'.join(preferred_provinces)}，后面可以结合这些地域再看这条方向的真实机会。")

    if not positive_signals:
        positive_signals.append("这条方向不是不能看，但更适合先结合你的学科、兴趣和后续路径一起判断。")
    if not caution_signals:
        caution_signals.append("这一步更适合先看你本人是否值得重点了解，再看当前方案有没有承接。")

    return {
        "slot": direction_slot,
        "label": to_career_label(direction_slot),
        "positiveSignals": positive_signals[:4],
        "cautionSignals": caution_signals[:3],
    }


def _build_cache_data(
    career_intents: dict | None = None,
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> dict[str, Any]:
    cache: dict[str, Any] = {}
    if career_intents:
        cache["career_intents"] = career_intents
    cache["intent_mode"] = intent_mode
    return cache


def _format_text_sections(*sections: tuple[str, list[str] | None] | tuple[str, str | None]) -> str:
    blocks: list[str] = []
    for title, content in sections:
        if not content:
            continue
        display_title = f"**{title}**"
        if isinstance(content, list):
            lines = list(dict.fromkeys(str(line).strip() for line in content if str(line or "").strip()))
            if not lines:
                continue
            blocks.append(f"{display_title}\n" + "\n".join(f"- {line}" for line in lines))
        else:
            text = str(content).strip()
            if not text:
                continue
            blocks.append(f"{display_title}\n{text}")
    return "\n\n".join(blocks)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pick_first_positive_int(*values: Any) -> int:
    for value in values:
        number = _coerce_int(value)
        if number > 0:
            return number
    return 0


def _build_tier_counts_from_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items:
        tier = str(item.get("tier") or "").strip()
        if tier in {"冲", "稳", "保"}:
            counter[tier] += 1
    return {tier: counter.get(tier, 0) for tier in ("冲", "稳", "保")}


def _normalize_tier_counts(tier_counts: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, int]:
    if not tier_counts:
        return _build_tier_counts_from_items(items)
    return {
        "冲": _coerce_int(tier_counts.get("冲", tier_counts.get("sprint"))),
        "稳": _coerce_int(tier_counts.get("稳", tier_counts.get("safe"))),
        "保": _coerce_int(tier_counts.get("保", tier_counts.get("protect"))),
    }


def _format_tier_counts(tier_counts: dict[str, int]) -> str:
    return f"冲{tier_counts.get('冲', 0)} / 稳{tier_counts.get('稳', 0)} / 保{tier_counts.get('保', 0)}"


def _build_plan_overview_fact(
    planning_state: dict[str, Any],
    ordered_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not planning_state:
        return {}
    ordered_state = planning_state.get("orderedPlanState") or {}
    ordered_summary = ordered_state.get("summary") or {}
    candidate_state = planning_state.get("candidatePoolState") or {}
    review_state = planning_state.get("reviewState") or {}
    review_summary = review_state.get("summary") or {}
    review_checks = review_state.get("checks") or []
    current_total = _pick_first_positive_int(
        ordered_summary.get("unitTotal"),
        ordered_summary.get("total"),
        len(ordered_items),
    )
    target_total = _pick_first_positive_int(
        ordered_summary.get("targetUnitCount"),
        ordered_summary.get("targetCount"),
        candidate_state.get("requiredCount"),
        current_total,
    )
    tier_counts = _normalize_tier_counts(
        ordered_summary.get("unitTierCounts") or ordered_summary.get("tierCounts") or {},
        ordered_items,
    )
    risk_summaries: list[str] = []
    for check in review_checks:
        if check.get("passed") is True:
            continue
        summary = str(check.get("summary") or "").strip()
        if summary:
            risk_summaries.append(summary)
        if len(risk_summaries) >= 2:
            break
    return {
        "phase": planning_state.get("phase") or "",
        "currentTotal": current_total,
        "targetTotal": target_total,
        "tierCounts": tier_counts,
        "riskCount": _coerce_int(review_summary.get("riskCount")),
        "warnCount": _coerce_int(review_summary.get("warnCount")),
        "riskSummaries": risk_summaries,
    }


def _format_plan_overview_lines(plan_overview: dict[str, Any]) -> list[str]:
    current_total = _coerce_int(plan_overview.get("currentTotal"))
    if not plan_overview or current_total <= 0:
        return []
    target_total = _coerce_int(plan_overview.get("targetTotal"))
    tier_counts = plan_overview.get("tierCounts") or {}
    risk_count = _coerce_int(plan_overview.get("riskCount"))
    warn_count = _coerce_int(plan_overview.get("warnCount"))
    total_text = f"{current_total}/{target_total}" if target_total > 0 else str(current_total)
    lines = [f"当前方案已有 {total_text} 个志愿，冲稳保分布：{_format_tier_counts(tier_counts)}。"]
    lines.append(f"当前审查记录为风险 {risk_count} 项、提醒 {warn_count} 项；这轮只做方向承接分析，不会改动方案。")
    risk_summaries = [str(item).strip() for item in (plan_overview.get("riskSummaries") or []) if str(item or "").strip()]
    if risk_summaries:
        lines.append(f"需要留意的结构提醒：{'；'.join(risk_summaries[:2])}。")
    return lines


def _get_direction_analysis_llm_client() -> LLMClient:
    global _direction_analysis_llm_client
    if _direction_analysis_llm_client is None:
        _direction_analysis_llm_client = LLMClient(LLMConfig())
    return _direction_analysis_llm_client


def _get_direction_analysis_agent() -> Agent[None, str]:
    global _direction_analysis_agent
    if _direction_analysis_agent is None:
        _direction_analysis_agent = Agent(
            model=_get_direction_analysis_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿助手里的方向适配分析生成器。"
                "你的任务不是给出确定结论，而是基于提供的学生背景、初始画像、当前方案承接情况、候选机会样本，生成自然、克制、面向用户的分析。"
                "优先顺序：先看学生本人是否适合/值得重点了解，再看方案承接，最后再提候选机会。"
                "如果给了学生适配事实，必须优先吸收这些事实，不要把回答退化成学校/专业列表。"
                "不要把回答写成技术状态说明，不要复述系统字段名，不要输出代码块。"
                "可以引用给定的学校/专业样本，但不能编造未提供的样本。"
                "如果信息不足，要明确说明只是初步判断。"
                "输出 JSON，字段固定为：summaryTitle, currentPlanFit, currentPlanConflict, candidateOpportunity, nextActionHints。"
                "每个列表控制在 1 到 3 条，每条一句自然中文。"
            ),
        )
    return _direction_analysis_agent


def _get_career_direction_resolver_agent() -> Agent[None, str]:
    global _career_direction_resolver_agent
    if _career_direction_resolver_agent is None:
        _career_direction_resolver_agent = Agent(
            model=_get_direction_analysis_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿对话里的职业方向语义判定器。"
                "请根据用户最后一句话，同时判断两个信息。"
                "第一，识别它主要在询问或表达下面哪些方向："
                "system_public_service（体制内/考公/考编/公务员/事业单位/进编制/进体制）、"
                "stable_employment（稳定就业/求稳/工作稳定/抗风险）、"
                "further_study（读研/保研/深造/继续升学）、"
                "market_employment（企业就业/市场化就业/大城市就业/互联网或产业岗位/去企业发展）。"
                "这里允许识别探索性问题，不要求用户已经形成明确偏好。"
                "如果用户是在比较多个方向，可返回多个；如果完全无法判断，则返回空数组。"
                "第二，判断用户是否是在问‘我适合什么方向/更适合往哪条路走/先看哪类专业线’这类泛方向适配问题。"
                "泛方向适配强调先分析学生本人，再看当前方案承接；不是直接抽取学校、城市、具体专业意向，也不是方案增删改。"
                "如果用户已经明确提学校、城市、具体专业名称，或者明确要改方案、加志愿、删志愿、筛候选，就不要判成泛方向适配。"
                "只返回 JSON：{\"positive\": [...], \"negative\": [], \"shouldAnalyze\": true/false, \"reason\": \"...\"}。"
            ),
        )
    return _career_direction_resolver_agent


def _normalize_career_direction_route_decision(
    decision: CareerDirectionRouteDecision,
) -> CareerDirectionRouteDecision:
    return CareerDirectionRouteDecision(
        positive=normalize_career_slots(decision.positive),
        negative=normalize_career_slots(decision.negative),
        shouldAnalyze=bool(decision.shouldAnalyze),
        reason=decision.reason or "",
    )


def _empty_career_direction_route_decision() -> CareerDirectionRouteDecision:
    return CareerDirectionRouteDecision()


def _allow_explore_inner_llm(request_context: RequestContext) -> bool:
    return bool(getattr(request_context, "allow_explore_inner_llm", True))


async def resolve_career_direction_route(request_context: RequestContext) -> CareerDirectionRouteDecision:
    latest_user_text = _latest_user_text(request_context).strip()
    logger.info(
        "resolve_career_direction_route called: session_id=%s latest_user_text=%s",
        request_context.sessionid,
        latest_user_text,
    )
    if not latest_user_text:
        return _empty_career_direction_route_decision()

    cached = getattr(request_context, _CAREER_DIRECTION_ROUTE_CACHE_ATTR, None)
    if isinstance(cached, dict) and cached.get("latest_user_text") == latest_user_text:
        decision = cached.get("decision")
        if isinstance(decision, CareerDirectionRouteDecision):
            logger.info(
                "resolve_career_direction_route cache hit: session_id=%s should_analyze=%s slots=%s",
                request_context.sessionid,
                decision.shouldAnalyze,
                decision.positive,
            )
            return decision

    result = await _get_career_direction_resolver_agent().run(
        f"用户最后一句话：{latest_user_text}",
        model_settings={"temperature": 0},
    )
    parsed = parse_extraction_json(result.output, CareerDirectionRouteDecision)
    decision = _normalize_career_direction_route_decision(parsed)
    setattr(
        request_context,
        _CAREER_DIRECTION_ROUTE_CACHE_ATTR,
        {"latest_user_text": latest_user_text, "decision": decision},
    )
    return decision


async def resolve_career_direction_slots(request_context: RequestContext) -> list[str]:
    decision = await resolve_career_direction_route(request_context)
    logger.info(
        "resolve_career_direction_slots resolved: session_id=%s slots=%s should_analyze=%s",
        request_context.sessionid,
        decision.positive,
        decision.shouldAnalyze,
    )
    return list(decision.positive)


async def should_use_generic_direction_analysis(request_context: RequestContext) -> bool:
    decision = await resolve_career_direction_route(request_context)
    logger.info(
        "should_use_generic_direction_analysis resolved: session_id=%s should_analyze=%s slots=%s reason=%s",
        request_context.sessionid,
        decision.shouldAnalyze,
        decision.positive,
        decision.reason,
    )
    return bool(decision.shouldAnalyze)


def likely_generic_direction_question(text: str | None) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    generic_patterns = (
        "适合什么方向",
        "适合哪些方向",
        "适合哪个方向",
        "适合什么专业方向",
        "适合哪些专业方向",
        "往哪条路",
        "走哪条路",
        "什么方向适合我",
        "哪些方向适合我",
    )
    return any(pattern in normalized for pattern in generic_patterns)


def _contains_any_text(value: str | None, keywords: list[str]) -> bool:
    if not value:
        return False
    return any(keyword and keyword in str(value) for keyword in keywords)


def _contains_any_in_list(values: list[str] | None, keywords: list[str]) -> bool:
    if not values:
        return False
    return any(_contains_any_text(value, keywords) for value in values)


def _collect_text_evidence(item: dict[str, Any], evidence_map: dict[str, list[str]]) -> list[str]:
    evidence: list[str] = []
    for field, keywords in evidence_map.items():
        value = item.get(field)
        if _contains_any_text(value, keywords):
            evidence.append(f"{field}:{value}")
    return evidence


def _collect_tag_evidence(item: dict[str, Any], keywords: list[str]) -> list[str]:
    tag_fields = (
        "schoolRankTags",
        "schoolBasicTags",
        "schoolPopupTags",
        "majorRankTags",
        "majorPlanTags",
        "reasonCodes",
    )
    evidence: list[str] = []
    for field in tag_fields:
        values = item.get(field) or []
        matched = [value for value in values if _contains_any_text(value, keywords)]
        if matched:
            evidence.append(f"{field}:{'、'.join(matched[:3])}")
    return evidence


def _direction_alignment_evidence(item: dict[str, Any], direction_slot: str) -> list[str]:
    if not item:
        return []
    if direction_slot == CAREER_SYSTEM_PUBLIC_SERVICE:
        return (
            _collect_text_evidence(item, _PUBLIC_SERVICE_EVIDENCE)
            + _collect_tag_evidence(item, _PUBLIC_SERVICE_TAG_EVIDENCE)
        )
    if direction_slot == CAREER_STABLE_EMPLOYMENT:
        return (
            _direction_alignment_evidence(item, CAREER_SYSTEM_PUBLIC_SERVICE)
            + _collect_text_evidence(item, _STABLE_EMPLOYMENT_EVIDENCE)
        )
    if direction_slot == CAREER_FURTHER_STUDY:
        return _collect_tag_evidence(item, _FURTHER_STUDY_TAG_EVIDENCE)
    if direction_slot == CAREER_MARKET_EMPLOYMENT:
        return (
            _collect_text_evidence(item, _MARKET_EMPLOYMENT_EVIDENCE)
            + _collect_tag_evidence(item, _MARKET_EMPLOYMENT_TAG_EVIDENCE)
        )
    return []


def _evidence_text(evidence: list[str]) -> str:
    return "；".join(str(item or "") for item in evidence)


def _evidence_has_field(evidence: list[str], *fields: str) -> bool:
    prefixes = tuple(f"{field}:" for field in fields)
    return any(str(item or "").startswith(prefixes) for item in evidence)


def _direction_evidence_score(item: dict[str, Any], direction_slot: str) -> int:
    evidence = _direction_alignment_evidence(item, direction_slot)
    if not evidence:
        return 0
    text = _evidence_text(evidence)
    score = len(evidence)
    if direction_slot == CAREER_FURTHER_STUDY:
        for marker in ("保研", "硕士点", "博士点", "双一流", "985", "211", "国重点"):
            if marker in text:
                score += 8
        if "升学率" in text:
            score += 5
        if "省重点" in text:
            score += 2
    elif direction_slot == CAREER_SYSTEM_PUBLIC_SERVICE:
        if _evidence_has_field(evidence, "majorName", "majorCategory", "majorDiscipline"):
            score += 8
        for marker, weight in (
            ("公安", 8),
            ("警校", 8),
            ("部委院校", 7),
            ("政法", 6),
            ("师范", 5),
            ("财经", 3),
            ("农林", 1),
            ("医药", 1),
        ):
            if marker in text:
                score += weight
    elif direction_slot == CAREER_STABLE_EMPLOYMENT:
        if _evidence_has_field(evidence, "majorName", "majorCategory", "majorDiscipline"):
            score += 6
        if "公办" in text:
            score += 2
        for marker, weight in (("师范", 5), ("医药", 4), ("政法", 4), ("农林", 2)):
            if marker in text:
                score += weight
    elif direction_slot == CAREER_MARKET_EMPLOYMENT:
        if _evidence_has_field(evidence, "majorName", "majorCategory", "majorDiscipline"):
            score += 7
        for marker, weight in (
            ("计算机", 7),
            ("软件", 7),
            ("人工智能", 7),
            ("大数据", 6),
            ("金融", 5),
            ("会计", 5),
            ("审计", 5),
            ("就业", 4),
            ("实习", 4),
            ("产业", 3),
        ):
            if marker in text:
                score += weight
    return score


def _rank_direction_matches(items: list[dict[str, Any]], direction_slot: str) -> list[dict[str, Any]]:
    indexed = list(enumerate(items))
    return [
        item
        for _, item in sorted(
            indexed,
            key=lambda pair: (_direction_evidence_score(pair[1], direction_slot), -pair[0]),
            reverse=True,
        )
    ]


def _is_public_service_aligned_item(item: dict[str, Any]) -> bool:
    return bool(_direction_alignment_evidence(item, CAREER_SYSTEM_PUBLIC_SERVICE))


def _is_stable_employment_aligned_item(item: dict[str, Any]) -> bool:
    return bool(_direction_alignment_evidence(item, CAREER_STABLE_EMPLOYMENT))


def _is_further_study_aligned_item(item: dict[str, Any]) -> bool:
    return bool(_direction_alignment_evidence(item, CAREER_FURTHER_STUDY))


def _is_market_employment_aligned_item(item: dict[str, Any]) -> bool:
    return bool(_direction_alignment_evidence(item, CAREER_MARKET_EMPLOYMENT))


def _item_matches_direction_slot(item: dict[str, Any], direction_slot: str) -> bool:
    if direction_slot == CAREER_SYSTEM_PUBLIC_SERVICE:
        return _is_public_service_aligned_item(item)
    if direction_slot == CAREER_STABLE_EMPLOYMENT:
        return _is_stable_employment_aligned_item(item)
    if direction_slot == CAREER_FURTHER_STUDY:
        return _is_further_study_aligned_item(item)
    if direction_slot == CAREER_MARKET_EMPLOYMENT:
        return _is_market_employment_aligned_item(item)
    return False


def _format_candidate_brief(item: dict[str, Any]) -> str:
    school_name = item.get("schoolName") or "未知院校"
    major_name = item.get("majorName") or "未知专业"
    major_name = re.split(r"[（(]", str(major_name), maxsplit=1)[0].strip() or str(item.get("majorName") or "未知专业")
    tier = item.get("tier") or "未知"
    province_name = item.get("provinceName") or ""
    return f"{school_name}-{major_name}（{tier}{f'/{province_name}' if province_name else ''}）"


def _format_brief_examples(examples: list[str], limit: int = 2) -> str:
    return "、".join(str(item).strip() for item in examples[:limit] if str(item or "").strip())


def _direction_plan_fit_lines(direction_fact: dict[str, Any]) -> list[str]:
    label = str(direction_fact.get("label") or "这个方向")
    count = _coerce_int(direction_fact.get("orderedMatchCount"))
    examples = _format_brief_examples(direction_fact.get("orderedExamples") or [])
    if count <= 0:
        return [f"如果只看当前方案，“{label}”的直接承接还不明显，后续若要强化这条路，需要从候选里再补贴近项。"]
    if examples:
        return [f"如果只看当前方案，和“{label}”更贴近的大约有 {count} 个志愿，代表样本有：{examples}。"]
    return [f"如果只看当前方案，和“{label}”更贴近的大约有 {count} 个志愿。"]


def _direction_candidate_opportunity_lines(direction_fact: dict[str, Any]) -> list[str]:
    label = str(direction_fact.get("label") or "这个方向")
    count = _coerce_int(direction_fact.get("candidateOpportunityCount"))
    examples = _format_brief_examples(direction_fact.get("candidateExamples") or [])
    if count <= 0:
        return [f"候选里暂时没有看到和“{label}”特别密集、且尚未进入方案的新机会。"]
    if examples:
        return [f"候选里和“{label}”更相关、但还没进方案的大约还有 {count} 个机会，代表样本有：{examples}。"]
    return [f"候选里和“{label}”更相关、但还没进方案的大约还有 {count} 个机会。"]


def _extract_direction_label_from_item(item: dict[str, Any]) -> str | None:
    for key in ("majorCategory", "majorDiscipline", "majorName"):
        value = item.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return None


def _collect_direction_groups(
    items: list[dict[str, Any]],
    *,
    exclude_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        volunteer_id = item.get("volunteerId")
        if exclude_ids and volunteer_id and volunteer_id in exclude_ids:
            continue
        label = _extract_direction_label_from_item(item)
        if not label:
            continue
        group = groups.setdefault(
            label,
            {"count": 0, "examples": [], "sampleNames": set()},
        )
        group["count"] += 1
        sample_name = item.get("majorName") or ""
        if sample_name and sample_name not in group["sampleNames"] and len(group["examples"]) < 2:
            group["sampleNames"].add(sample_name)
            group["examples"].append(_format_candidate_brief(item))
    return groups


def _latest_user_text(request_context: RequestContext) -> str:
    history = request_context.chat_history or []
    for message in reversed(history):
        if message.get("role") == "user" and message.get("content"):
            return str(message.get("content"))
    return ""


async def _emit_progress(request_context: RequestContext, hint: str) -> None:
    callback = getattr(request_context, "progress_callback", None)
    if not callback:
        return
    try:
        await callback(hint)
    except Exception:
        logger.debug("generic direction progress callback failed", exc_info=True)


def _build_request_context_summary(request_context: RequestContext) -> list[str]:
    parts: list[str] = []
    score = getattr(request_context, "score_detail", None)
    career_policy = resolve_career_planning_policy(score)
    if score:
        parts.append(
            f"学生基础信息：省份={score.province}；分数={score.total_score}；选科={'、'.join(score.subject_list or []) or '未知'}；性别={score.sex or '未知'}；模式={score.volunteer_model}"
        )
        parts.append(f"职业路径规划规则：score_band={career_policy.score_band}；employment_first={'yes' if career_policy.employment_first else 'no'}；规则摘要={career_policy.summary}")
    profile = getattr(request_context, "init_profile", None)
    if profile:
        parts.append(
            "初始画像摘要："
            f"意向专业大类={','.join(profile.major.level2 or []) or '无'}；"
            f"排除专业大类={','.join(profile.major.negative_level2 or []) or '无'}；"
            f"意向省份={','.join(profile.city.province or []) or '无'}；"
            f"排除省份={','.join(profile.city.negative_province or []) or '无'}"
        )
    planning = getattr(request_context, "planning_summary", None)
    if planning:
        parts.append(
            "当前方案摘要："
            f"phase={planning.phase or 'unknown'}；ordered_total={planning.ordered_total}；draft_total={planning.draft_total}；"
            f"review_risk={planning.review_risk_count}；review_warn={planning.review_warn_count}"
        )
    return parts


def _build_generic_student_fit_fact(
    request_context: RequestContext,
    planning_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = getattr(request_context, "score_detail", None)
    profile = getattr(request_context, "init_profile", None)
    career_policy = resolve_career_planning_policy(score)
    latent_profile = (((planning_state or {}).get("profileState") or {}).get("latentProfile") or {})
    future_development = (latent_profile.get("futureDevelopment") or {}).get("careerTypes") or []

    positive_signals: list[str] = []
    caution_signals: list[str] = []

    subjects = list(score.subject_list or []) if score else []
    strength_subjects = list((profile.strength_subjects or [])) if profile else []
    preferred_major_level1 = list((profile.major.level1 or [])) if profile else []
    preferred_major_level2 = list((profile.major.level2 or [])) if profile else []
    negative_major_level2 = list((profile.major.negative_level2 or [])) if profile else []
    preferred_provinces = list((profile.city.province or [])) if profile else []

    if subjects:
        positive_signals.append(f"你的当前选科是{'、'.join(subjects)}，所以更适合先从这些学科能承接的专业线里找方向。")
    if strength_subjects:
        positive_signals.append(f"你自己更擅长或更有把握的是{'、'.join(strength_subjects[:2])}，这能帮助后面继续缩小方向范围。")
    if preferred_major_level2:
        positive_signals.append(f"你已经明确对{'、'.join(preferred_major_level2[:3])}这类方向有兴趣，这比完全从零猜方向更可靠。")
    elif preferred_major_level1:
        positive_signals.append(f"你已经表现出对{'、'.join(preferred_major_level1[:2])}这类门类的偏好，可以优先围绕它们继续细分。")
    if preferred_provinces:
        positive_signals.append(f"你当前还有地域倾向（{'、'.join(preferred_provinces[:2])}），后面筛方向时也要结合地域机会一起看。")
    if future_development:
        positive_signals.append(f"你当前的长期发展倾向里已经有{'、'.join(future_development[:2])}，所以方向判断也不能只看专业名字。")
    if career_policy.employment_first:
        caution_signals.append(career_policy.summary)
        positive_signals.append("在当前这个分数段，先把方向往更容易就业、岗位需求更明确的专业线收，比先追求深造想象更稳妥。")

    if negative_major_level2:
        caution_signals.append(f"你已经明显排斥{'、'.join(negative_major_level2[:2])}这类方向，所以后面不能只按热门程度来判断。")
    caution_signals.append("这一步更适合先判断你本人更值得重点看哪几条专业线，再看当前方案有没有承接。")

    if not positive_signals:
        positive_signals.append("你现在的显式偏好还不算多，所以这一步更适合先做一个初步方向判断，再决定要不要继续收窄。")

    return {
        "slot": "generic_direction_fit",
        "label": "泛方向适配分析",
        "positiveSignals": positive_signals[:4],
        "cautionSignals": caution_signals[:3],
    }


def _build_generic_direction_facts(
    request_context: RequestContext,
    ordered_items: list[dict[str, Any]],
    candidate_items: list[dict[str, Any]],
    ordered_ids: set[str],
) -> list[dict[str, Any]]:
    profile = getattr(request_context, "init_profile", None)
    preferred_labels = [str(label).strip() for label in ((profile.major.level2 or []) if profile else []) if str(label).strip()]

    ordered_groups = _collect_direction_groups(ordered_items)
    candidate_groups = _collect_direction_groups(candidate_items, exclude_ids=ordered_ids)
    all_labels = set(preferred_labels) | set(ordered_groups.keys()) | set(candidate_groups.keys())

    label_scores: Counter[str] = Counter()
    for label in all_labels:
        label_scores[label] += ordered_groups.get(label, {}).get("count", 0) * 3
        label_scores[label] += candidate_groups.get(label, {}).get("count", 0)
        if label in preferred_labels:
            label_scores[label] += 6

    facts: list[dict[str, Any]] = []
    for label, _ in label_scores.most_common(4):
        ordered_group = ordered_groups.get(label, {})
        candidate_group = candidate_groups.get(label, {})
        reasons: list[str] = []
        if label in preferred_labels:
            reasons.append("这类方向已经在你的初始兴趣里出现过。")
        if ordered_group.get("count"):
            reasons.append(f"当前方案里已经有 {ordered_group['count']} 个相关志愿。")
        if candidate_group.get("count"):
            reasons.append(f"候选里还有 {candidate_group['count']} 个相关机会没进方案。")
        if not reasons:
            reasons.append("这条方向暂时更多是结合你的整体情况和已有线索做初步判断。")
        facts.append(
            {
                "slot": label,
                "label": label,
                "orderedMatchCount": ordered_group.get("count", 0),
                "candidateMatchCount": candidate_group.get("count", 0),
                "orderedExamples": ordered_group.get("examples", [])[:2],
                "candidateExamples": candidate_group.get("examples", [])[:2],
                "evidence": reasons[:3],
            }
        )
    return facts


async def _generate_generic_direction_analysis_content(
    request_context: RequestContext,
    student_fit_fact: dict[str, Any],
    direction_facts: list[dict[str, Any]],
) -> DirectionAnalysisDraft:
    latest_user_text = _latest_user_text(request_context)
    prompt_parts = [
        f"当前用户原话：{latest_user_text or '无'}",
        *_build_request_context_summary(request_context),
        "学生适配事实：",
        json.dumps([student_fit_fact], ensure_ascii=False),
        "方向候选事实：",
        json.dumps(direction_facts, ensure_ascii=False),
        (
            "生成要求："
            "这是泛方向问题，先分析学生本人当前更值得重点看的专业方向，再看当前方案承接，最后再提候选机会。"
            "不要把回答退化成学校名单或单纯的方案复读。"
            "如果事实不足，要明确这是初步判断。"
            "可以提到 2 到 4 类方向，但不要机械编号，也不要写成长清单。"
        ),
    ]
    result = await _get_direction_analysis_agent().run(
        "\n".join(prompt_parts),
        model_settings={"temperature": 0},
    )
    return parse_extraction_json(result.output, DirectionAnalysisDraft)


def _build_direction_slot_fact(
    direction_slot: str,
    ordered_items: list[dict[str, Any]],
    candidate_items: list[dict[str, Any]],
    ordered_ids: set[str],
) -> dict[str, Any]:
    ordered_matches = [
        item for item in ordered_items if _item_matches_direction_slot(item, direction_slot)
    ]
    candidate_matches = [
        item
        for item in candidate_items
        if item.get("volunteerId") not in ordered_ids and _item_matches_direction_slot(item, direction_slot)
    ]
    ordered_examples = _rank_direction_matches(ordered_matches, direction_slot)[:3]
    candidate_examples = _rank_direction_matches(candidate_matches, direction_slot)[:3]
    return {
        "slot": direction_slot,
        "label": to_career_label(direction_slot),
        "orderedMatchCount": len(ordered_matches),
        "candidateOpportunityCount": len(candidate_matches),
        "orderedExamples": [_format_candidate_brief(item) for item in ordered_examples],
        "candidateExamples": [_format_candidate_brief(item) for item in candidate_examples],
        "evidenceExamples": [
            {
                "item": _format_candidate_brief(item),
                "evidence": _direction_alignment_evidence(item, direction_slot)[:3],
            }
            for item in (ordered_examples + candidate_examples)[:3]
        ],
    }


def _build_direction_interest_analysis(
    direction_slot: str,
    *,
    student_fit_fact: dict[str, Any],
    ordered_match_count: int,
    ordered_total: int,
    candidate_match_count: int,
) -> dict[str, Any]:
    direction_label = to_career_label(direction_slot)
    fit_points: list[str] = [
        f"我先不急着替你下结论，而是结合你自己的情况，看看“{direction_label}”这条路值不值得重点看。"
    ]
    fit_points.extend(student_fit_fact.get("positiveSignals") or [])
    conflict_points: list[str] = list(student_fit_fact.get("cautionSignals") or [])
    opportunity_points: list[str] = []
    next_action_hints: list[str] = [
        "如果你愿意，我可以继续按这条方向帮你看看现在这份方案承接得够不够。",
        "你也可以先去看候选里还有没有更贴近这条方向的机会。",
        "如果你想把“自己到底更适合哪类方向”看得更细一点，后面也可以结合 MBTI 和霍兰德职业兴趣测评再继续收一层。",
    ]

    if ordered_total <= 0:
        fit_points.append("你现在还没有成型的排序方案，所以这一步更适合先看方向本身，再决定要不要往这个方向收口。")
    elif ordered_match_count > 0:
        fit_points.append(f"当前方案里已经有一部分内容能承接这条方向，大约有 {ordered_match_count} 个志愿相对更贴近。")
    else:
        conflict_points.append("当前方案里直接贴近这条方向的承接还不算明显，如果后面真要往这边收口，可能还需要继续补看。")

    if candidate_match_count > 0:
        opportunity_points.append(f"候选里还有一些更贴近这条方向的机会，粗看大约有 {candidate_match_count} 个可以继续深挖。")
    else:
        opportunity_points.append("候选里暂时没看到特别密集的新机会，所以更适合先判断这条方向是不是你真的想长期优先考虑。")

    if direction_slot == CAREER_SYSTEM_PUBLIC_SERVICE:
        fit_points.append("这类方向通常更看重院校性质、专业方向和未来职业路径的稳定性，不是单看某一所学校或某一个专业名字。")
    elif direction_slot == CAREER_STABLE_EMPLOYMENT:
        fit_points.append("这类方向更看重就业确定性、岗位稳定性和路径清晰度，不能只看一时热度。")
    elif direction_slot == CAREER_FURTHER_STUDY:
        fit_points.append("这类方向更看重院校培养环境、升学条件和后续深造通道，不只是看当前录取概率。")
    elif direction_slot == CAREER_MARKET_EMPLOYMENT:
        fit_points.append("这类方向更看重城市产业、实习机会、岗位面和技能可迁移性，不只是看学校层次。")

    return {
        "stage": ANALYSIS_STAGE_INTEREST,
        "summaryTitle": f"先帮你判断一下，“{direction_label}”是不是值得重点看",
        "currentPlanFit": fit_points,
        "currentPlanConflict": conflict_points,
        "candidateOpportunity": opportunity_points,
        "nextActionHints": next_action_hints,
    }


def _build_impact_preview_from_analysis(analysis: dict[str, Any]) -> str:
    lines: list[str] = [f"{analysis.get('summaryTitle', '结合当前方案给你的提醒')}："]
    section_map = (
        ("currentPlanFit", "初步判断"),
        ("currentPlanConflict", "需要补充留意"),
        ("candidateOpportunity", "可以继续展开看的方向"),
        ("nextActionHints", "如果继续了解"),
    )
    for key, title in section_map:
        items = list(dict.fromkeys(str(item).strip() for item in (analysis.get(key) or []) if str(item or "").strip()))
        if not items:
            continue
        lines.append(f"  {title}：")
        for item in items:
            lines.append(f"  - {item}")
    return "\n".join(lines)


async def _generate_direction_analysis_content(
    request_context: RequestContext,
    student_fit_facts: list[dict[str, Any]],
    direction_facts: list[dict[str, Any]],
) -> DirectionAnalysisDraft:
    latest_user_text = _latest_user_text(request_context)
    prompt_parts = [
        f"当前用户原话：{latest_user_text or '无'}",
        *_build_request_context_summary(request_context),
        "学生适配事实：",
        json.dumps(student_fit_facts, ensure_ascii=False),
        "方向分析事实：",
        json.dumps(direction_facts, ensure_ascii=False),
        (
            "生成要求："
            "先结合学生本人的情况，判断这些方向是更适合深入了解、暂时保留还是当前关联一般；"
            "再补充当前方案承接情况；"
            "最后再点到候选里的潜在机会。"
            "不要只盯着方案和学校名单。"
            "如果是多方向，允许比较多个方向，不要默认只有两个。"
        ),
    ]
    result = await _get_direction_analysis_agent().run(
        "\n".join(prompt_parts),
        model_settings={"temperature": 0},
    )
    return parse_extraction_json(result.output, DirectionAnalysisDraft)


async def preview_direction_analysis_from_request(
    request_context: RequestContext,
    direction_slot: str,
) -> str:
    session_id = request_context.sessionid
    logger.info(
        "preview_direction_analysis_from_request called: session_id=%s direction_slot=%s",
        session_id,
        direction_slot,
    )

    ordered_match_count = 0
    ordered_total = 0
    candidate_match_count = 0
    ordered_items: list[dict[str, Any]] = []
    candidate_items: list[dict[str, Any]] = []
    ordered_ids: set[str] = set()
    planning_state: dict[str, Any] = {}
    try:
        planning_state_resp = await get_planning_state(session_id)
        planning_state = (planning_state_resp or {}).get("data") or {}
        ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items")) or []
        candidate_items = ((planning_state.get("candidatePoolState") or {}).get("items")) or []
        ordered_total = len(ordered_items)
        ordered_ids = {item.get("volunteerId") for item in ordered_items if item.get("volunteerId")}
        ordered_match_count = sum(1 for item in ordered_items if _item_matches_direction_slot(item, direction_slot))
        candidate_match_count = sum(
            1
            for item in candidate_items
            if item.get("volunteerId") not in ordered_ids and _item_matches_direction_slot(item, direction_slot)
        )
    except Exception:
        logger.warning(
            "Preview direction analysis failed to inspect planning state: session_id=%s direction_slot=%s",
            session_id,
            direction_slot,
            exc_info=True,
        )

    student_fit_fact = _build_student_fit_fact(direction_slot, request_context, planning_state)
    analysis = _build_direction_interest_analysis(
        direction_slot,
        student_fit_fact=student_fit_fact,
        ordered_match_count=ordered_match_count,
        ordered_total=ordered_total,
        candidate_match_count=candidate_match_count,
    )
    plan_overview = _build_plan_overview_fact(planning_state, ordered_items)
    plan_overview_lines = _format_plan_overview_lines(plan_overview)
    direction_fact = _build_direction_slot_fact(direction_slot, ordered_items, candidate_items, ordered_ids)
    fit_lines = _direction_plan_fit_lines(direction_fact)
    opportunity_lines = _direction_candidate_opportunity_lines(direction_fact)
    analysis["planOverview"] = plan_overview_lines
    analysis["currentPlanFit"] = list(analysis.get("currentPlanFit") or []) + fit_lines
    analysis["candidateOpportunity"] = list(analysis.get("candidateOpportunity") or []) + opportunity_lines
    if _allow_explore_inner_llm(request_context):
        try:
            generated = await _generate_direction_analysis_content(
                request_context,
                [student_fit_fact],
                [
                    {
                        "planOverview": plan_overview,
                        "direction": direction_fact,
                    }
                ],
            )
            analysis.update(generated.model_dump())
            analysis["planOverview"] = plan_overview_lines
            analysis["currentPlanFit"] = fit_lines + list(analysis.get("currentPlanFit") or [])
            analysis["candidateOpportunity"] = opportunity_lines + list(analysis.get("candidateOpportunity") or [])
        except Exception:
            logger.warning(
                "Generate direction analysis content failed, falling back to template: session_id=%s direction_slot=%s",
                session_id,
                direction_slot,
                exc_info=True,
            )
    else:
        logger.info(
            "Skip direction analysis inner LLM generation: session_id=%s direction_slot=%s",
            session_id,
            direction_slot,
        )

    return _format_text_sections(
        ("分析结论", [f"你提到的“{to_career_label(direction_slot)}”，我先帮你做了一个初步判断。"]),
        ("当前方案概况", analysis.get("planOverview")),
        ("当前判断", _build_impact_preview_from_analysis(analysis)),
        ("下一步", ["如果你愿意把它记成后续偏好，我可以再按这个方向继续帮你看方案。"]),
    )


async def preview_generic_direction_analysis_from_request(
    request_context: RequestContext,
) -> str:
    session_id = request_context.sessionid
    logger.info(
        "preview_generic_direction_analysis_from_request called: session_id=%s latest_user_text=%s",
        session_id,
        _latest_user_text(request_context).strip(),
    )
    await _emit_progress(request_context, "正在读取你的成绩、选科和已记录的偏好...")
    ordered_items: list[dict[str, Any]] = []
    candidate_items: list[dict[str, Any]] = []
    ordered_ids: set[str] = set()
    planning_state: dict[str, Any] = {}
    try:
        await _emit_progress(request_context, "正在对照你当前的方案和候选机会...")
        planning_state_resp = await get_planning_workspace_state(session_id)
        planning_state = (planning_state_resp or {}).get("data") or {}
        ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items")) or []
        ordered_ids = {item.get("volunteerId") for item in ordered_items if item.get("volunteerId")}
        candidate_resp = await query_planning_candidate_pool(
            1,
            session_id,
            page=1,
            page_size=80,
            sort_field="finalScore",
            sort_order="desc",
        )
        candidate_items = ((candidate_resp or {}).get("data") or {}).get("items") or []
    except Exception:
        logger.warning(
            "Preview generic direction analysis failed to inspect planning state: session_id=%s",
            session_id,
            exc_info=True,
        )

    student_fit_fact = _build_generic_student_fit_fact(request_context, planning_state)
    direction_facts = _build_generic_direction_facts(
        request_context,
        ordered_items,
        candidate_items,
        ordered_ids,
    )
    analysis: dict[str, Any] = {
        "stage": ANALYSIS_STAGE_INTEREST,
        "summaryTitle": "我先结合你的情况，判断一下现在更值得优先看的方向",
        "currentPlanFit": list(student_fit_fact.get("positiveSignals") or []),
        "currentPlanConflict": list(student_fit_fact.get("cautionSignals") or []),
        "candidateOpportunity": [],
        "nextActionHints": [
            "如果你愿意，我可以继续顺着其中一个方向往下看具体学校和专业机会。",
            "如果你现在更关心自己到底适合哪条路，后面也可以结合 MBTI 和霍兰德职业兴趣测评再细看。",
        ],
    }
    for fact in direction_facts[:3]:
        label = fact.get("label") or "该方向"
        ordered_count = fact.get("orderedMatchCount") or 0
        candidate_count = fact.get("candidateMatchCount") or 0
        if ordered_count > 0:
            analysis["currentPlanFit"].append(f"从当前方案看，“{label}”已经有一定承接，大约有 {ordered_count} 个相关志愿。")
        if candidate_count > 0:
            analysis["candidateOpportunity"].append(f"候选里和“{label}”相关、还没进方案的机会大约还有 {candidate_count} 个。")
    if _allow_explore_inner_llm(request_context):
        try:
            await _emit_progress(request_context, "正在把这些线索整理成适合你的方向建议...")
            generated = await asyncio.wait_for(
                _generate_generic_direction_analysis_content(
                    request_context,
                    student_fit_fact,
                    direction_facts[:3],
                ),
                timeout=_GENERIC_DIRECTION_LLM_TIMEOUT_SECONDS,
            )
            analysis.update(generated.model_dump())
        except Exception:
            logger.warning(
                "Generate generic direction analysis content failed, falling back to template: session_id=%s",
                session_id,
                exc_info=True,
            )
    else:
        logger.info(
            "Skip generic direction inner LLM generation: session_id=%s",
            session_id,
        )
    return _format_text_sections(
        ("分析结论", ["你这句更像是在问自己现阶段更适合优先看哪类方向，我先按这个思路帮你做个初步判断。"]),
        ("当前判断", _build_impact_preview_from_analysis(analysis)),
        ("下一步", list(analysis.get("nextActionHints") or [])),
    )


async def preview_direction_comparison_from_request(
    request_context: RequestContext,
    direction_slots: list[str],
) -> str:
    session_id = request_context.sessionid
    logger.info(
        "preview_direction_comparison_from_request called: session_id=%s direction_slots=%s",
        session_id,
        direction_slots,
    )
    normalized_slots = normalize_career_slots(direction_slots)
    if len(normalized_slots) < 2:
        return await preview_direction_analysis_from_request(
            request_context,
            normalized_slots[0] if normalized_slots else CAREER_SYSTEM_PUBLIC_SERVICE,
        )

    planning_state_resp = await get_planning_state(session_id)
    planning_state = (planning_state_resp or {}).get("data") or {}
    ordered_items = ((planning_state.get("orderedPlanState") or {}).get("items")) or []
    candidate_items = ((planning_state.get("candidatePoolState") or {}).get("items")) or []
    ordered_ids = {item.get("volunteerId") for item in ordered_items if item.get("volunteerId")}

    fit_points: list[str] = []
    opportunity_points: list[str] = []
    labels = [to_career_label(slot) for slot in normalized_slots]
    direction_facts = [
        _build_direction_slot_fact(slot, ordered_items, candidate_items, ordered_ids)
        for slot in normalized_slots
    ]
    for fact in direction_facts:
        fit_points.extend(_direction_plan_fit_lines(fact))
        opportunity_points.extend(_direction_candidate_opportunity_lines(fact))

    plan_overview_lines = _format_plan_overview_lines(_build_plan_overview_fact(planning_state, ordered_items))
    analysis = {
        "stage": ANALYSIS_STAGE_INTEREST,
        "summaryTitle": f"我先帮你把“{'”和“'.join(labels)}”放在一起看一眼",
        "planOverview": plan_overview_lines,
        "currentPlanFit": ["这类问题更适合先看你本人更适合哪条路径，再看当前方案更偏向哪一边。"] + fit_points,
        "currentPlanConflict": [],
        "candidateOpportunity": opportunity_points,
        "nextActionHints": [
            "如果你愿意，我可以接着单独展开其中一个方向，专门看它和你当前方案到底有多匹配。",
            "如果你现在主要卡在“自己更适合哪类路径”，后面也可以结合 MBTI 和霍兰德职业兴趣测评再细看。",
        ],
    }
    student_fit_facts = [
        _build_student_fit_fact(slot, request_context, planning_state)
        for slot in normalized_slots
    ]
    for fit_fact in student_fit_facts:
        analysis["currentPlanFit"].extend((fit_fact.get("positiveSignals") or [])[:1])
        analysis["currentPlanConflict"].extend((fit_fact.get("cautionSignals") or [])[:1])
    if _allow_explore_inner_llm(request_context):
        try:
            generated = await _generate_direction_analysis_content(
                request_context,
                student_fit_facts,
                direction_facts,
            )
            analysis.update(generated.model_dump())
            analysis["planOverview"] = plan_overview_lines
            if direction_facts:
                analysis["currentPlanFit"] = fit_points + list(analysis.get("currentPlanFit") or [])
                analysis["candidateOpportunity"] = opportunity_points + list(analysis.get("candidateOpportunity") or [])
        except Exception:
            logger.warning(
                "Generate direction comparison content failed, falling back to template: session_id=%s direction_slots=%s",
                session_id,
                normalized_slots,
                exc_info=True,
            )
    else:
        logger.info(
            "Skip direction comparison inner LLM generation: session_id=%s direction_slots=%s",
            session_id,
            normalized_slots,
        )

    return _format_text_sections(
        ("分析结论", ["先给你一个方向判断，这轮只做分析，不会改动方案。"]),
        ("当前方案概况", analysis.get("planOverview")),
        ("当前判断", _build_impact_preview_from_analysis(analysis)),
        ("下一步", ["如果你愿意，我可以接着单独展开其中一个方向，再看它和当前方案到底有多匹配。"]),
    )
