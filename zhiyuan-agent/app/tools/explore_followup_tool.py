"""Follow-up handlers for explore-stage actions."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from app.agent.context import RequestContext
from app.tools.plan_execution_tool import execute_plan_action
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.intent_response_tool import (
    ExploreFollowupResult,
    serialize_explore_followup_result,
)
from app.util.code_enrichment import normalize_candidate_filters_async
from app.util.internal_client import (
    get_intent_change_cache,
    get_pending_confirmation,
    get_planning_state,
    query_planning_candidate_pool,
)

logger = logging.getLogger(__name__)


def _build_minimal_request_context(session_id: str, batch: str) -> Any:
    request_context = RequestContext(
        userid="",
        sessionid=session_id,
        chat_history=[],
        batch=batch,
        score_detail=None,
        init_profile=None,
        planning_summary=None,
    )
    return SimpleNamespace(deps=request_context)


def _build_candidate_filters_from_intents(merged: dict[str, Any]) -> dict[str, Any]:
    city_intents = merged.get("city_intents") or {}
    school_intents = merged.get("school_intents") or {}
    major_intents = merged.get("major_intents") or {}
    major_categories = list(dict.fromkeys(major_intents.get("level2", []) or []))
    negative_major_categories = list(dict.fromkeys(major_intents.get("negative_level2", []) or []))
    if not major_categories:
        major_categories = list(dict.fromkeys(major_intents.get("level3", []) or []))
    if not negative_major_categories:
        negative_major_categories = list(dict.fromkeys(major_intents.get("negative_level3", []) or []))
    return {
        "provinceNames": city_intents.get("province", []),
        "negativeProvinceNames": city_intents.get("negative_province", []),
        "cityNames": city_intents.get("city", []),
        "negativeCityNames": city_intents.get("negative_city", []),
        "schoolKeywords": school_intents.get("colleges", []),
        "negativeSchoolKeywords": school_intents.get("negative_colleges", []),
        "majorKeywords": major_categories,
        "negativeMajorKeywords": negative_major_categories,
        "schoolTags": [],
        "negativeSchoolTags": [],
        "majorTags": major_intents.get("level1", []),
        "negativeMajorTags": major_intents.get("negative_level1", []),
    }


async def _query_candidate_total(session_id: str, candidate_filters: dict[str, Any]) -> int | None:
    try:
        resp = await query_planning_candidate_pool(
            1,
            int(session_id),
            tiers=candidate_filters.get("tiers"),
            province_names=candidate_filters.get("provinceNames"),
            negative_province_names=candidate_filters.get("negativeProvinceNames"),
            city_names=candidate_filters.get("cityNames"),
            negative_city_names=candidate_filters.get("negativeCityNames"),
            school_keywords=candidate_filters.get("schoolKeywords"),
            negative_school_keywords=candidate_filters.get("negativeSchoolKeywords"),
            major_keywords=candidate_filters.get("majorKeywords"),
            negative_major_keywords=candidate_filters.get("negativeMajorKeywords"),
            school_tags=candidate_filters.get("schoolTags"),
            negative_school_tags=candidate_filters.get("negativeSchoolTags"),
            major_tags=candidate_filters.get("majorTags"),
            negative_major_tags=candidate_filters.get("negativeMajorTags"),
            page=1,
            page_size=1,
        )
        return (resp or {}).get("data", {}).get("total")
    except Exception:
        logger.warning("Query filtered candidate total failed: session_id=%s", session_id, exc_info=True)
        return None


async def _query_candidate_base_total(session_id: str) -> int | None:
    try:
        planning_state = await get_planning_state(int(session_id))
        return (((planning_state or {}).get("data") or {}).get("candidatePoolState") or {}).get("summary", {}).get("total")
    except Exception:
        logger.warning("Query candidate base total failed: session_id=%s", session_id, exc_info=True)
        return None


async def _load_cached_intents(session_id: str) -> tuple[dict[str, Any], str]:
    try:
        pending_result = await get_pending_confirmation(session_id)
        pending_data = (pending_result or {}).get("data", {}).get("pendingConfirmation") or {}
        if (
            isinstance(pending_data, dict)
            and pending_data.get("status") == "active"
            and pending_data.get("kind") == "intent_change"
        ):
            execution_payload = pending_data.get("executionPayload") or {}
            merged = execution_payload.get("merged") or {}
            if isinstance(merged, dict) and _has_any_intent_payload(
                merged.get("major_intents"),
                merged.get("school_intents"),
                merged.get("city_intents"),
                merged.get("career_intents"),
            ):
                intent_mode = execution_payload.get("intentMode") or pending_data.get("intentMode") or "preference"
                return {
                    "major_intents": merged.get("major_intents") or {},
                    "school_intents": merged.get("school_intents") or {},
                    "city_intents": merged.get("city_intents") or {},
                    "career_intents": merged.get("career_intents") or {},
                }, intent_mode
    except Exception:
        logger.warning("Load pendingConfirmation intents failed: session_id=%s", session_id, exc_info=True)

    cache_result = await get_intent_change_cache(session_id)
    cache_data = (cache_result or {}).get("data", {}).get("planEditCache") or {}
    merged = {
        "major_intents": cache_data.get("major_intents") or {},
        "school_intents": cache_data.get("school_intents") or {},
        "city_intents": cache_data.get("city_intents") or {},
        "career_intents": cache_data.get("career_intents") or {},
    }
    intent_mode = cache_data.get("intent_mode") or "preference"
    return merged, intent_mode


def _has_any_intent_payload(
    major_intents: dict | None,
    school_intents: dict | None,
    city_intents: dict | None,
    career_intents: dict | None = None,
) -> bool:
    def _has_values(payload: dict | None) -> bool:
        return bool(payload and any(values for values in payload.values()))

    return (
        _has_values(major_intents)
        or _has_values(school_intents)
        or _has_values(city_intents)
        or _has_values(career_intents)
    )


async def handle_interest_analysis_action_result(
    *,
    session_id: str,
    batch: str,
    action_type: str,
) -> str:
    merged, intent_mode = await _load_cached_intents(session_id)
    if not _has_any_intent_payload(
        merged.get("major_intents"),
        merged.get("school_intents"),
        merged.get("city_intents"),
        merged.get("career_intents"),
    ):
        return serialize_explore_followup_result(
            ExploreFollowupResult(
                actionType=action_type,
                sessionId=session_id,
                intentMode=intent_mode,
                handled=False,
                messageCode="cache_missing",
            )
        )

    if action_type == "candidate_query":
        candidate_filters = await normalize_candidate_filters_async(
            _build_candidate_filters_from_intents(merged),
            batch,
        )
        has_filterable_fields = any(candidate_filters.get(key) for key in (
            "provinceNames",
            "negativeProvinceNames",
            "cityNames",
            "negativeCityNames",
            "schoolKeywords",
            "negativeSchoolKeywords",
            "majorKeywords",
            "negativeMajorKeywords",
            "majorTags",
            "negativeMajorTags",
        ))
        if not has_filterable_fields:
            return serialize_explore_followup_result(
                ExploreFollowupResult(
                    actionType=action_type,
                    sessionId=session_id,
                    intentMode=intent_mode,
                    handled=True,
                    messageCode="candidate_not_filterable",
                )
            )
        base_total = await _query_candidate_base_total(session_id)
        filtered_total = await _query_candidate_total(session_id, candidate_filters)
        return serialize_explore_followup_result(
            ExploreFollowupResult(
                actionType=action_type,
                sessionId=session_id,
                intentMode=intent_mode,
                handled=True,
                messageCode="candidate_query",
                candidateFilters=candidate_filters,
                filteredTotal=filtered_total,
                baseTotal=base_total,
            )
        )

    if action_type == "plan_analyze":
        ctx = _build_minimal_request_context(session_id, batch)
        plan_payload = await plan_next_action(
            ctx,
            user_goal="结合当前已识别偏好/要求分析方案",
            action_family="analyze_adjustment",
            user_confirmed=True,
        )
        plan_result_text = await execute_plan_action(ctx, plan_payload)
        plan_result = json.loads(plan_result_text)
        delegated_text = plan_result.get("summary") or plan_result.get("state_summary") or ""
        return serialize_explore_followup_result(
            ExploreFollowupResult(
                actionType=action_type,
                sessionId=session_id,
                intentMode=intent_mode,
                handled=True,
                messageCode="intent_analysis",
                delegatedText=delegated_text,
            )
        )

    if action_type in {"prefer_confirm", "constrain_confirm"}:
        from app.tools.intent_response_tool import parse_intent_analysis_payload, render_intent_analysis_payload
        from app.tools.intent_state_tool import analyze_volunteer_intent_change

        ctx = _build_minimal_request_context(session_id, batch)
        payload_text = await analyze_volunteer_intent_change(
            ctx,
            merged.get("major_intents"),
            merged.get("school_intents"),
            merged.get("city_intents"),
            None,
            analysis_stage="confirmed",
            career_intents=merged.get("career_intents"),
            confirm_enabled=action_type in {"prefer_confirm", "constrain_confirm"},
            intent_mode=intent_mode,
        )
        delegated_text = render_intent_analysis_payload(payload_text)
        return serialize_explore_followup_result(
            ExploreFollowupResult(
                actionType=action_type,
                sessionId=session_id,
                intentMode=intent_mode,
                handled=True,
                messageCode="intent_analysis",
                analysisPayload=parse_intent_analysis_payload(payload_text).model_dump(),
                delegatedText=delegated_text,
            )
        )

    return serialize_explore_followup_result(
        ExploreFollowupResult(
            actionType=action_type,
            sessionId=session_id,
            intentMode=intent_mode,
            handled=False,
            messageCode="unsupported_action",
        )
    )
