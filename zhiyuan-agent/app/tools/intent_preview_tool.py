"""Intent preview wrappers built on top of core intent analysis tools."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.domain.career_slots import CAREER_SYSTEM_PUBLIC_SERVICE
from app.schemas.tool_inputs import (
    CareerIntentPreviewInput,
    CityIntentPreviewInput,
    MajorIntentPreviewInput,
    SchoolIntentPreviewInput,
)
from app.tools.explore_direction_tool import (
    preview_generic_direction_analysis_from_request as _preview_generic_direction_analysis_from_request,
    preview_direction_analysis_from_request as _preview_direction_analysis_from_request,
    preview_direction_comparison_from_request as _preview_direction_comparison_from_request,
    resolve_career_direction_slots as _resolve_career_direction_slots,
    should_use_generic_direction_analysis as _should_use_generic_direction_analysis,
)
from app.tools.intent_response_tool import render_intent_analysis_payload
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    ANALYSIS_STAGE_INTEREST,
    INTENT_MODE_PREFERENCE,
    analyze_volunteer_intent_change,
)

logger = logging.getLogger(__name__)
IntentMode = Literal["preference", "constraint"]


def _session_id(request_context: RequestContext) -> str:
    return str(getattr(request_context, "sessionid", "") or getattr(request_context, "session_id", ""))


def _payload_from_model(model_cls: type[BaseModel], value: BaseModel | dict | None) -> dict | None:
    if value is None:
        return None
    model = value if isinstance(value, model_cls) else model_cls.model_validate(value)
    payload = model.model_dump()
    normalized = {key: item for key, item in payload.items() if item}
    return normalized or None


async def analyze_current_interest(
    ctx: RunContext[RequestContext],
    intent_mode: str = INTENT_MODE_PREFERENCE,
    recovery_scope: str | None = "generic",
) -> str:
    """Read-only Explore analysis for interest / fit questions.

    Use this for questions that ask whether a direction, school, major, or region
    is suitable or worth understanding first. This path must not create pending
    intent state or ask the user to confirm a preference update.
    """
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
            intent_mode=intent_mode,
            persist_cache=False,
        )
    )


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
    intent_mode: str = INTENT_MODE_PREFERENCE,
) -> str:
    """Read-only Explore analysis for major fit questions like “电子信息工程适合我吗”.

    Use this when the user is only asking whether a major or major category fits
    them. Do not use it to write new preferences into pending intent state.
    """
    return await analyze_current_interest(
        ctx,
        intent_mode=intent_mode,
        recovery_scope="major",
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
) -> str:
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
        return await _preview_direction_analysis_from_request(
            request_context,
            CAREER_SYSTEM_PUBLIC_SERVICE,
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
    recovery_scope: str | None = None,
) -> str:
    """High-level Intent preview from the current utterance.

    Use this when the user is explicitly stating a new long-term preference or
    requirement that should be confirmed before being applied. Prefer the
    theme-specific wrappers below when the topic is already clear.
    If you already know the explicit structured intent from the current turn,
    pass it in directly so the tool can skip another extraction round.
    """
    return render_intent_analysis_payload(
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
        )
    )


async def preview_current_major_intent_confirmation(
    ctx: RunContext[RequestContext],
    major_intents: MajorIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
) -> str:
    """Intent preview for explicit major / major-category preference or constraint.

    Examples: “想学网络与新媒体”, “不想学审计”, “以后优先看电子信息类”.
    Do not use this for read-only fit questions like “电子信息工程适合我吗”.
    If the current turn already names the target major clearly, pass
    `major_intents` directly so the tool can reuse it instead of extracting again.
    """
    return await preview_current_intent_confirmation(
        ctx,
        major_intents=major_intents,
        intent_mode=intent_mode,
        recovery_scope="major",
    )


async def preview_current_school_intent_confirmation(
    ctx: RunContext[RequestContext],
    school_intents: SchoolIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
) -> str:
    """Intent preview for explicit school preference or exclusion."""
    return await preview_current_intent_confirmation(
        ctx,
        school_intents=school_intents,
        intent_mode=intent_mode,
        recovery_scope="school",
    )


async def preview_current_region_intent_confirmation(
    ctx: RunContext[RequestContext],
    city_intents: CityIntentPreviewInput | None = None,
    intent_mode: IntentMode | None = None,
) -> str:
    """Intent preview for explicit region / city preference or exclusion."""
    return await preview_current_intent_confirmation(
        ctx,
        city_intents=city_intents,
        intent_mode=intent_mode,
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
