"""Intent preview wrappers built on top of core intent analysis tools."""

from __future__ import annotations

import json
import logging
import contextlib
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.domain.major_entity_resolver import resolve_major_mentions_from_text
from app.schemas.tool_inputs import (
    CareerIntentPreviewInput,
    CityIntentPreviewInput,
    MajorIntentPreviewInput,
    SchoolIntentPreviewInput,
)
from app.tools.explore_direction_tool import (
    likely_generic_direction_question as _likely_generic_direction_question,
    preview_generic_direction_analysis_from_request as _preview_generic_direction_analysis_from_request,
    preview_direction_analysis_from_request as _preview_direction_analysis_from_request,
    preview_direction_comparison_from_request as _preview_direction_comparison_from_request,
    resolve_career_direction_slots as _resolve_career_direction_slots,
    should_use_generic_direction_analysis as _should_use_generic_direction_analysis,
)
from app.domain.career_slots import CAREER_SLOT_VALUES, CAREER_STABLE_EMPLOYMENT, normalize_career_slots
from app.tools.intent_response_tool import parse_intent_analysis_payload, render_intent_analysis_payload
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    ANALYSIS_STAGE_INTEREST,
    INTENT_MODE_PREFERENCE,
    analyze_volunteer_intent_change,
)
from app.tools.major_compare_tool import compare_majors

logger = logging.getLogger(__name__)
IntentMode = Literal["preference", "constraint"]
ConstraintIntentType = Literal["default", "only_keep", "must_have"]


def _session_id(request_context: RequestContext) -> str:
    return str(getattr(request_context, "sessionid", "") or getattr(request_context, "session_id", ""))


def _payload_from_model(model_cls: type[BaseModel], value: BaseModel | dict | None) -> dict | None:
    if value is None:
        return None
    model = value if isinstance(value, model_cls) else model_cls.model_validate(value)
    payload = model.model_dump()
    normalized = {key: item for key, item in payload.items() if item}
    return normalized or None


def _latest_user_text(request_context: RequestContext) -> str:
    for message in reversed(request_context.chat_history or []):
        if message.get("role") == "user" and message.get("content"):
            return str(message.get("content") or "").strip()
    return ""


async def _emit_progress_hint(request_context: RequestContext, hint: str) -> None:
    callback = getattr(request_context, "progress_callback", None)
    if callback is None:
        return
    with contextlib.suppress(Exception):
        await callback(hint)


def _resolved_major_names_from_latest_text(request_context: RequestContext) -> list[str]:
    mentions = resolve_major_mentions_from_text(_latest_user_text(request_context), request_context.batch or "01")
    names: list[str] = []
    for mention in mentions:
        if mention.level != "level3":
            continue
        name = str(mention.canonical_name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _has_major_mentions_in_latest_text(request_context: RequestContext) -> bool:
    return bool(resolve_major_mentions_from_text(_latest_user_text(request_context), request_context.batch or "01"))


def _has_explicit_career_language(text: str) -> bool:
    career_markers = (
        "稳定就业",
        "求稳",
        "就业稳定",
        "工作稳定",
        "抗风险",
        "体制内",
        "考公",
        "考编",
        "公务员",
        "事业编",
        "读研",
        "深造",
        "升学",
        "企业就业",
        "市场化就业",
        "大城市就业",
    )
    return any(marker in str(text or "") for marker in career_markers)


def _render_structured_preview_tool_payload(payload_text: str) -> str:
    """Keep preview tool returns structured while preserving the user-facing text.

    Direct tool-reply policy reads the ``message`` field for display. Persisted
    history keeps the full payload so later follow-up questions can recover the
    exact intent values from ``items`` / ``existingItems`` instead of guessing
    from natural-language assistant text.
    """
    rendered = render_intent_analysis_payload(payload_text)
    try:
        payload = parse_intent_analysis_payload(payload_text)
    except Exception:
        return rendered
    data = payload.model_dump()
    data["reply_strategy"] = "continue_model" if payload.analysisStage == ANALYSIS_STAGE_INTEREST else "preview_wait_confirm"
    data["message"] = rendered
    return json.dumps(data, ensure_ascii=False)


async def analyze_current_interest(
    ctx: RunContext[RequestContext],
    intent_mode: str = INTENT_MODE_PREFERENCE,
    recovery_scope: str | None = "generic",
    major_intents: MajorIntentPreviewInput | None = None,
) -> str:
    """Read-only Explore analysis for interest / fit questions.

    Use this for questions that ask whether a direction, school, major, or region
    is suitable or worth understanding first. This path must not create pending
    intent state or ask the user to confirm a preference update.
    """
    return render_intent_analysis_payload(
        await analyze_volunteer_intent_change(
            ctx,
            _payload_from_model(MajorIntentPreviewInput, major_intents),
            None,
            None,
            None,
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            recovery_scope=recovery_scope,
            confirm_enabled=False,
            intent_mode=intent_mode,
            persist_cache=False,
        )
    )


async def analyze_current_interest_profile(
    ctx: RunContext[RequestContext],
) -> str:
    """Read-only integrated Explore analysis for broad student profile questions.

    Use this when the user describes several interests, disliked directions, job
    preferences, income/stability/communication expectations, or a loose career
    picture in one turn. This tool is meant to gather one comprehensive analysis
    instead of repeatedly calling career and major Explore tools. After this
    tool returns, synthesize the final answer from its result; do not call
    another Explore tool in the same turn unless the user asks a separate,
    narrowly scoped follow-up.
    """
    return await _preview_generic_direction_analysis_from_request(ctx.deps)


async def analyze_current_school_interest(
    ctx: RunContext[RequestContext],
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> str:
    """Read-only Explore analysis for school fit questions."""
    return await analyze_current_interest(
        ctx,
        intent_mode=intent_mode,
        recovery_scope="school",
    )


async def analyze_current_major_interest(
    ctx: RunContext[RequestContext],
    major_intents: MajorIntentPreviewInput | None = None,
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> str:
    """Read-only Explore analysis for major fit questions like “电子信息工程适合我吗”.

    Use this when the user is only asking whether a major or major category fits
    them. Do not use this for two-option or multi-option major comparison; use
    `compare_majors` / `compare_major_options` for those cases. Do not use it
    to write new preferences into pending intent state.
    If the user states mixed positive/negative major preferences without asking
    to first see impact, boundary, pros/cons, or risks, use
    `preview_current_major_intent_confirmation` instead.
    If the user already clearly names the target major/category being analyzed,
    pass it in `major_intents` so the tool does not need to infer from unrelated
    context such as weak subjects or excluded directions.
    """
    resolved_major_names = _resolved_major_names_from_latest_text(ctx.deps)
    if len(resolved_major_names) == 2:
        await _emit_progress_hint(ctx.deps, "正在对比这几个专业的差异...")
        comparison = await compare_majors(ctx, resolved_major_names[0], resolved_major_names[1])
        return json.dumps(
            {
                "reply_strategy": "continue_model",
                "analysis_kind": "major_compare",
                "major_names": resolved_major_names,
                "message": comparison,
            },
            ensure_ascii=False,
        )
    return await analyze_current_interest(
        ctx,
        intent_mode=intent_mode,
        recovery_scope="major",
        major_intents=major_intents,
    )


async def analyze_current_region_interest(
    ctx: RunContext[RequestContext],
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> str:
    """Read-only Explore analysis for region fit questions."""
    return await analyze_current_interest(
        ctx,
        intent_mode=intent_mode,
        recovery_scope="region",
    )


async def analyze_current_career_direction(
    ctx: RunContext[RequestContext],
    career_directions: list[Literal[*CAREER_SLOT_VALUES]] | None = None,
    generic_direction: bool = False,
) -> str:
    """Read-only Explore analysis for career direction tradeoffs.

    Args:
        ctx: request context.
        career_directions: Optional normalized direction slots. Pass these when
            the current utterance already clearly names the direction(s), e.g.
            system_public_service for 考公/考编/体制内, stable_employment for
            求稳/稳定就业, further_study for 读研/深造, market_employment for
            企业就业/大城市就业/市场化就业. If omitted, the tool falls back
            to semantic slot resolution.
        generic_direction: Set true when the utterance is clearly asking for a
            broad direction framework, e.g. 先看大方向 / 出分前先定方向 /
            我适合什么方向. This skips the tool's internal route resolver.
    """
    latest_user_text = ""
    for message in reversed(ctx.deps.chat_history or []):
        if message.get("role") == "user" and message.get("content"):
            latest_user_text = str(message.get("content") or "")
            break
    direction_slots = normalize_career_slots(list(career_directions or []))
    has_major_mentions = _has_major_mentions_in_latest_text(ctx.deps)
    if direction_slots:
        if (
            has_major_mentions
            and direction_slots == [CAREER_STABLE_EMPLOYMENT]
            and not _has_explicit_career_language(latest_user_text)
        ):
            logger.info(
                "analyze_current_career_direction: session_id=%s delegating_stable_employment_major_mentions_to_major_interest",
                _session_id(ctx.deps),
            )
            return await analyze_current_major_interest(ctx)
        logger.info(
            "analyze_current_career_direction: session_id=%s using_explicit_direction_slots=%s",
            _session_id(ctx.deps),
            direction_slots,
        )
    elif has_major_mentions:
        logger.info(
            "analyze_current_career_direction: session_id=%s delegating_to_major_interest_for_major_mentions",
            _session_id(ctx.deps),
        )
        return await analyze_current_major_interest(ctx)
    else:
        if generic_direction or _likely_generic_direction_question(latest_user_text):
            try:
                direction_slots = await _resolve_career_direction_slots(ctx.deps)
            except Exception:
                logger.warning(
                    "analyze_current_career_direction: career slot resolve failed before generic fallback: session_id=%s",
                    _session_id(ctx.deps),
                    exc_info=True,
                )
                direction_slots = []
        else:
            direction_slots = await _resolve_career_direction_slots(ctx.deps)
    logger.info(
        "analyze_current_career_direction: session_id=%s direction_slots=%s",
        _session_id(ctx.deps),
        direction_slots,
    )
    if len(direction_slots) > 1:
        return await preview_direction_comparison_from_request(ctx.deps, direction_slots)
    if len(direction_slots) == 1:
        return await preview_direction_analysis_from_request(ctx.deps, direction_slots[0])
    if generic_direction or _likely_generic_direction_question(latest_user_text):
        logger.info(
            "analyze_current_career_direction: session_id=%s using_generic_direction_analysis=%s",
            _session_id(ctx.deps),
            "explicit" if generic_direction else "local",
        )
        return await _preview_generic_direction_analysis_from_request(ctx.deps)
    try:
        if await _should_use_generic_direction_analysis(ctx.deps):
            logger.info(
                "analyze_current_career_direction: session_id=%s using_generic_direction_analysis=true",
                _session_id(ctx.deps),
            )
            return await _preview_generic_direction_analysis_from_request(ctx.deps)
    except Exception:
        pass
    return "我还没完全判断出你更想看的发展方向。你可以更明确一点，比如体制内、稳定就业，或者以后更想读研。"


async def preview_interest_analysis_from_request(
    request_context: RequestContext,
    recovery_scope: str | None = "generic",
) -> str:
    normalized_scope = (recovery_scope or "").strip().lower()
    logger.info(
        "preview_interest_analysis_from_request: session_id=%s recovery_scope=%s normalized_scope=%s",
        _session_id(request_context),
        recovery_scope,
        normalized_scope,
    )
    if normalized_scope == "career_preference":
        try:
            direction_slots = await _resolve_career_direction_slots(request_context)
            if len(direction_slots) > 1:
                return await _preview_direction_comparison_from_request(request_context, direction_slots)
            if len(direction_slots) == 1:
                return await _preview_direction_analysis_from_request(request_context, direction_slots[0])
        except Exception:
            logger.warning(
                "preview_interest_analysis_from_request career slot resolve failed, falling back to system_public_service: session_id=%s",
                _session_id(request_context),
                exc_info=True,
            )
        return await _preview_direction_analysis_from_request(
            request_context,
            "system_public_service",
        )
    if normalized_scope == "generic":
        try:
            if await _should_use_generic_direction_analysis(request_context):
                return await _preview_generic_direction_analysis_from_request(request_context)
        except Exception:
            pass

    ctx = SimpleNamespace(deps=request_context)
    return render_intent_analysis_payload(
        await analyze_volunteer_intent_change(
            ctx,
            None,
            None,
            None,
            None,
            analysis_stage=ANALYSIS_STAGE_INTEREST,
            recovery_scope=recovery_scope,
            confirm_enabled=False,
            persist_cache=False,
        )
    )


async def preview_current_intent_confirmation(
    ctx: RunContext[RequestContext],
    major_intents: MajorIntentPreviewInput | None = None,
    school_intents: SchoolIntentPreviewInput | None = None,
    city_intents: CityIntentPreviewInput | None = None,
    career_intents: CareerIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
    constraint_intent_type: ConstraintIntentType | None = None,
    recovery_scope: str | None = None,
) -> str:
    """High-level Intent preview from the current utterance.

    Use this when the user is explicitly stating a new long-term preference or
    requirement that should be confirmed before being applied. Prefer the
    theme-specific wrappers below when the topic is already clear.
    If you already know the explicit structured intent from the current turn,
    pass it in directly so the tool can skip another extraction round.
    """
    return _render_structured_preview_tool_payload(
        await analyze_volunteer_intent_change(
            ctx,
            _payload_from_model(MajorIntentPreviewInput, major_intents),
            _payload_from_model(SchoolIntentPreviewInput, school_intents),
            _payload_from_model(CityIntentPreviewInput, city_intents),
            None,
            analysis_stage=ANALYSIS_STAGE_CONFIRMED,
            career_intents=_payload_from_model(CareerIntentPreviewInput, career_intents),
            recovery_scope=recovery_scope,
            confirm_enabled=True,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
    )


async def preview_current_major_intent_confirmation(
    ctx: RunContext[RequestContext],
    major_intents: MajorIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
    constraint_intent_type: ConstraintIntentType | None = None,
) -> str:
    """Intent preview for explicit major / major-category preference or constraint.

    Examples: “想学网络与新媒体”, “不想学审计”, “医学类的不要”,
    “护理别要”, “以后优先看电子信息类”.
    Short colloquial exclusions that clearly name a major, major category, or
    discipline should still use this tool and pass the corresponding negative
    major intent field; do not answer them as free-form chat.
    For mixed explicit input like “医学护理这些别碰，财会还能接受”, pass
    `major_intents` directly with positive and negative fields instead of
    calling this tool repeatedly without arguments.
    Mixed positive/negative utterances without an explicit "first analyze the
    impact/boundary" request are preference/constraint previews, not read-only
    major-fit analysis.
    Do not use this for read-only fit questions like “电子信息工程适合我吗”.
    If the current turn already names the target major clearly, pass
    `major_intents` directly so the tool can reuse it instead of extracting again.
    """
    return await preview_current_intent_confirmation(
        ctx,
        major_intents=major_intents,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
        recovery_scope="major",
    )


async def preview_current_school_intent_confirmation(
    ctx: RunContext[RequestContext],
    school_intents: SchoolIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
    constraint_intent_type: ConstraintIntentType | None = None,
) -> str:
    """Intent preview for explicit school preference or exclusion."""
    return await preview_current_intent_confirmation(
        ctx,
        school_intents=school_intents,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
        recovery_scope="school",
    )


async def preview_current_region_intent_confirmation(
    ctx: RunContext[RequestContext],
    city_intents: CityIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
    constraint_intent_type: ConstraintIntentType | None = None,
) -> str:
    """Intent preview for explicit region / city preference or exclusion."""
    return await preview_current_intent_confirmation(
        ctx,
        city_intents=city_intents,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
        recovery_scope="region",
    )


async def preview_current_career_intent_confirmation(
    ctx: RunContext[RequestContext],
    career_intents: CareerIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
) -> str:
    """Intent preview for explicit career-path preference or exclusion.

    Examples: “以后优先按体制内方向看”, “现在不想进体制内了”.
    Do not use this for read-only fit questions like “体制内适不适合我”.
    """
    return await preview_current_intent_confirmation(
        ctx,
        career_intents=career_intents,
        intent_mode=intent_mode,
        recovery_scope="career_preference",
    )


async def preview_direction_analysis_from_request(
    request_context: RequestContext,
    direction_slot: str,
) -> str:
    logger.info(
        "preview_direction_analysis_from_request: session_id=%s direction_slot=%s",
        _session_id(request_context),
        direction_slot,
    )
    return await _preview_direction_analysis_from_request(request_context, direction_slot)


async def preview_direction_comparison_from_request(
    request_context: RequestContext,
    direction_slots: list[str],
) -> str:
    logger.info(
        "preview_direction_comparison_from_request: session_id=%s direction_slots=%s",
        _session_id(request_context),
        direction_slots,
    )
    return await _preview_direction_comparison_from_request(request_context, direction_slots)
