"""Session-scoped virtual file cache for the Release 4.0 Zhiyuan Agent."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.agent.context import PlanningSummary
from app.models.conversation_phase import PendingConfirmation
from app.schemas.user_profile import UserProfile
from app.util import internal_client


DEFAULT_WARM_PATHS = ("score.json", "profile.json", "plan/summary.json", "pending.json")
_DEFAULT_TTL_SECONDS = 300.0

_PATH_ALIASES = {
    "score": "score.json",
    "score.json": "score.json",
    "profile": "profile.json",
    "profile.json": "profile.json",
    "constraints": "constraints.json",
    "constraint": "constraints.json",
    "constraints.json": "constraints.json",
    "plan": "plan/summary.json",
    "plan/summary": "plan/summary.json",
    "plan_summary": "plan/summary.json",
    "summary": "plan/summary.json",
    "plan/summary.json": "plan/summary.json",
    "plan/items": "plan/items.json",
    "plan_items": "plan/items.json",
    "plan/items.json": "plan/items.json",
    "plan/candidates": "plan/candidates.json",
    "plan_candidates": "plan/candidates.json",
    "plan/candidates.json": "plan/candidates.json",
    "plan/review": "plan/review.json",
    "plan_review": "plan/review.json",
    "plan/review.json": "plan/review.json",
    "pending": "pending.json",
    "pending.json": "pending.json",
}

SUPPORTED_PATHS = frozenset(
    {
        "score.json",
        "profile.json",
        "constraints.json",
        "plan/summary.json",
        "plan/items.json",
        "plan/candidates.json",
        "plan/review.json",
        "pending.json",
    }
)


def normalize_sandbox_path(path: str) -> str:
    normalized = str(path or "").strip().lstrip("/").lower()
    normalized = normalized.replace("\\", "/")
    normalized = normalized.removesuffix("/")
    result = _PATH_ALIASES.get(normalized)
    if result is None:
        raise ValueError(f"unsupported sandbox path: {path}")
    return result


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _clean_string_list(values: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(values):
        if isinstance(item, dict):
            text = item.get("name") or item.get("label") or item.get("value")
        else:
            text = item
        value = str(text or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _response_data(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response


def _extract_extra_data_value(response: Any, key: str) -> dict[str, Any]:
    data = _response_data(response)
    value = data.get(key)
    if value is None:
        value = data.get("dataValue")
    if value is None and isinstance(response, dict) and key in response:
        value = response.get(key)
    result = _as_dict(value)
    if result:
        version = _as_int(data.get("dataVersion") or data.get("version"))
        if version > 0:
            result.setdefault("_extraDataVersion", version)
            result.setdefault("dataVersion", version)
    return result


def _extract_version(*values: Any) -> int:
    for value in values:
        data = _as_dict(value)
        for key in ("version", "planningVersion", "sourceBackendVersion", "source_backend_version"):
            version = _as_int(data.get(key))
            if version > 0:
                return version
    return 0


def _score_file_from_backend(raw_data: dict[str, Any], *, batch: str | None = None) -> dict[str, Any]:
    if not raw_data:
        return {"available": False, "batch": batch or "01"}
    province_raw = raw_data.get("province")
    province_name = (
        province_raw.get("name", "")
        if isinstance(province_raw, dict)
        else str(province_raw or raw_data.get("provinceName") or "")
    )
    sex_raw = raw_data.get("sex")
    sex_name = sex_raw.get("name", "") if isinstance(sex_raw, dict) else str(sex_raw or "")
    subject_list = _clean_string_list(raw_data.get("subjectList") or raw_data.get("subject_list") or [])
    return {
        "available": True,
        "province": province_name,
        "total_score": _as_int(raw_data.get("totalScore") or raw_data.get("total_score")),
        "subject_list": subject_list,
        "sex": sex_name,
        "volunteer_model": str(raw_data.get("volunteerModel") or raw_data.get("volunteer_model") or "major"),
        "batch": str(raw_data.get("batch") or batch or "01"),
    }


def _score_file_from_object(score_detail: Any, *, batch: str | None = None) -> dict[str, Any]:
    if score_detail is None:
        return {"available": False, "batch": batch or "01"}
    return {
        "available": True,
        "province": str(getattr(score_detail, "province", "") or ""),
        "total_score": _as_int(getattr(score_detail, "total_score", 0)),
        "subject_list": list(getattr(score_detail, "subject_list", []) or []),
        "sex": str(getattr(score_detail, "sex", "") or ""),
        "volunteer_model": str(getattr(score_detail, "volunteer_model", "") or "major"),
        "batch": batch or "01",
    }


def _profile_file_from_model(profile: UserProfile | None) -> dict[str, Any]:
    if profile is None:
        return {
            "available": False,
            "positive": {
                "majors": {"level1": [], "level2": [], "level3": []},
                "schools": [],
                "regions": {"province": [], "city": [], "area": []},
            },
            "negative": {},
            "strength_subjects": [],
        }
    return {
        "available": True,
        "positive": {
            "majors": {
                "level1": list(profile.major.level1),
                "level2": list(profile.major.level2),
                "level3": list(profile.major.level3),
            },
            "schools": list(profile.school.colleges),
            "regions": {
                "province": list(profile.city.province),
                "city": list(profile.city.city),
                "area": list(profile.city.area),
            },
        },
        "negative": {
            "majors": {
                "level1": list(profile.major.negative_level1),
                "level2": list(profile.major.negative_level2),
                "level3": list(profile.major.negative_level3),
            },
            "schools": list(profile.school.negative_colleges),
            "regions": {
                "province": list(profile.city.negative_province),
                "city": list(profile.city.negative_city),
                "area": list(profile.city.negative_area),
            },
        },
        "strength_subjects": list(profile.strength_subjects),
    }


def _profile_file_from_backend(raw_data: dict[str, Any]) -> dict[str, Any]:
    if not raw_data:
        return _profile_file_from_model(None)
    if "positive" in raw_data or "negative" in raw_data:
        data = dict(raw_data)
        data.setdefault("available", True)
        return data
    return _profile_file_from_model(UserProfile.from_backend_format(raw_data))


def _profile_file_from_summary(summary: PlanningSummary | None) -> dict[str, Any]:
    if summary is None:
        return _profile_file_from_model(None)
    return {
        "available": True,
        "positive": {
            "majors": list(summary.positive_majors or []),
            "regions": list(summary.positive_regions or []),
        },
        "negative": {},
        "strength_subjects": [],
    }


def _plan_summary_file_from_object(summary: PlanningSummary | None) -> dict[str, Any]:
    if summary is None or _as_int(getattr(summary, "ordered_total", 0)) <= 0:
        return {
            "has_plan": False,
            "guidance": "还没有生成正式方案，可以先明确报考要求或生成方案。",
        }
    return {
        "has_plan": True,
        "phase": summary.phase,
        "version": summary.version,
        "ordered_total": summary.ordered_total,
        "ordered_target_total": summary.ordered_target_total or summary.ordered_total,
        "tier_counts": dict(summary.tier_counts or {}),
        "review": {
            "risk_count": summary.review_risk_count,
            "warn_count": summary.review_warn_count,
            "risk_summaries": list(summary.risk_summaries or []),
        },
        "sample_schools": list(summary.sample_schools or []),
        "positive_regions": list(summary.positive_regions or []),
        "positive_majors": list(summary.positive_majors or []),
    }


def _plan_summary_file_from_backend_state(state: dict[str, Any]) -> dict[str, Any]:
    return _plan_summary_file_from_object(PlanningSummary.from_backend_state(state))


def _review_file_from_backend_state(state: dict[str, Any]) -> dict[str, Any]:
    review_state = _as_dict(state.get("reviewState"))
    summary = _as_dict(review_state.get("summary"))
    checks = review_state.get("checks") if isinstance(review_state.get("checks"), list) else []
    return {
        "available": bool(review_state),
        "version": _as_int(state.get("version")),
        "summary": summary,
        "checks": checks,
        "risk_count": _as_int(summary.get("riskCount") or summary.get("risk_count")),
        "warn_count": _as_int(summary.get("warnCount") or summary.get("warn_count")),
    }


def _constraints_file_from_backend_state(state: dict[str, Any]) -> dict[str, Any]:
    constraint_state = _as_dict(state.get("constraintState") or state.get("constraints"))
    profile_state = _as_dict(state.get("profileState"))
    explicit_profile = _as_dict(profile_state.get("explicitProfile"))
    return {
        "available": bool(constraint_state or explicit_profile),
        "version": _as_int(state.get("version")),
        "constraints": constraint_state,
        "explicit_profile": explicit_profile,
    }


_CANDIDATE_ENRICHMENT_FIELDS = (
    "unitId",
    "unit_id",
    "planSchoolDataId",
    "schoolId",
    "schoolUnitCode",
    "displaySchoolName",
    "provinceName",
    "cityName",
    "schoolBatch",
    "schoolLevel",
    "schoolNature",
    "schoolCategory",
    "schoolRank",
    "schoolEnrollRatio",
    "baoyanRatio",
    "upgradeRatio",
    "masterCount",
    "doctorCount",
    "schoolRankTags",
    "schoolBasicTags",
    "schoolPopupTags",
    "schoolTags",
    "majorId",
    "majorCode",
    "majorCategoryId",
    "majorSubCategoryId",
    "majorLevel",
    "majorDiscipline",
    "majorCategory",
    "majorTier",
    "planNum",
    "duration",
    "tuitionPerYear",
    "admissionRatio",
    "finalScore",
    "intentScore",
    "baseScore",
    "futureDevelopmentScore",
    "rankInTier",
    "hotIndex",
    "salaryAvg",
    "majorPlanTags",
    "majorRankTags",
    "riskFlags",
    "reasonCodes",
    "mustSubjects",
)


def _clean_volunteer_id(value: Any) -> str:
    return str(value or "").strip()


def _legacy_volunteer_prefix(value: Any) -> str:
    text = _clean_volunteer_id(value)
    if not text:
        return ""
    parts = text.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else text


def _ordered_unit_id_from_volunteer_id(value: Any) -> str:
    text = _clean_volunteer_id(value)
    if not text:
        return ""
    return text.split("_", 1)[0]


def _ordered_unit_lookup(units: list[Any]) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    by_plan_school_data_id: dict[str, dict[str, Any]] = {}
    by_position: dict[int, dict[str, Any]] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        plan_school_data_id = _clean_volunteer_id(unit.get("planSchoolDataId") or unit.get("plan_school_data_id"))
        if plan_school_data_id and plan_school_data_id not in by_plan_school_data_id:
            by_plan_school_data_id[plan_school_data_id] = unit
        position = _as_int(unit.get("position"))
        if position > 0 and position not in by_position:
            by_position[position] = unit
    return by_plan_school_data_id, by_position


def _ordered_unit_for_item(
    item: dict[str, Any],
    by_plan_school_data_id: dict[str, dict[str, Any]],
    by_position: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    volunteer_id = _clean_volunteer_id(item.get("volunteerId") or item.get("volunteer_id"))
    if volunteer_id:
        unit = by_plan_school_data_id.get(_legacy_volunteer_prefix(volunteer_id))
        if unit is not None:
            return unit
    return by_position.get(_as_int(item.get("position")), {})


def _candidate_lookup(candidates: list[Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_volunteer_id: dict[str, dict[str, Any]] = {}
    by_legacy_prefix: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        volunteer_id = _clean_volunteer_id(candidate.get("volunteerId") or candidate.get("volunteer_id"))
        if volunteer_id and volunteer_id not in by_volunteer_id:
            by_volunteer_id[volunteer_id] = candidate
        legacy_prefix = _legacy_volunteer_prefix(volunteer_id)
        if legacy_prefix and legacy_prefix not in by_legacy_prefix:
            by_legacy_prefix[legacy_prefix] = candidate
    return by_volunteer_id, by_legacy_prefix


def _candidate_for_ordered_item(
    item: dict[str, Any],
    by_volunteer_id: dict[str, dict[str, Any]],
    by_legacy_prefix: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    volunteer_id = _clean_volunteer_id(item.get("volunteerId") or item.get("volunteer_id"))
    if not volunteer_id:
        return {}
    candidate = by_volunteer_id.get(volunteer_id)
    if candidate is not None:
        return candidate
    return by_legacy_prefix.get(_legacy_volunteer_prefix(volunteer_id), {})


def _merge_ordered_item_with_candidate(item: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(item)
    for key in _CANDIDATE_ENRICHMENT_FIELDS:
        value = candidate.get(key)
        if value not in (None, "", [], {}) and merged.get(key) in (None, "", [], {}):
            merged[key] = value
    if merged.get("schoolName") in (None, "") and candidate.get("schoolName"):
        merged["schoolName"] = candidate.get("schoolName")
    if merged.get("majorName") in (None, "") and candidate.get("majorName"):
        merged["majorName"] = candidate.get("majorName")
    if merged.get("tier") in (None, ""):
        tier = candidate.get("tier") or candidate.get("majorTier") or candidate.get("majorLevel")
        if tier not in (None, ""):
            merged["tier"] = tier
    if merged.get("unitId") in (None, "", [], {}):
        unit_id = (
            _ordered_unit_id_from_volunteer_id(merged.get("volunteerId"))
            or candidate.get("orderedUnitId")
            or candidate.get("ordered_unit_id")
            or candidate.get("unitId")
        )
        if unit_id:
            merged["unitId"] = unit_id
    return merged


def _enrich_ordered_items_from_candidates(ordered_state: dict[str, Any], candidate_state: dict[str, Any]) -> list[dict[str, Any]]:
    items = ordered_state.get("items")
    if not isinstance(items, list):
        items = []
    units = ordered_state.get("units")
    if not isinstance(units, list):
        units = []
    candidates = candidate_state.get("items")
    if not isinstance(candidates, list):
        candidates = []
    by_volunteer_id, by_legacy_prefix = _candidate_lookup(candidates)
    by_plan_school_data_id, by_position = _ordered_unit_lookup(units)
    enriched: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ordered_unit = _ordered_unit_for_item(item, by_plan_school_data_id, by_position)
        if ordered_unit:
            item = dict(item)
            unit_id = ordered_unit.get("unitId") or ordered_unit.get("unit_id")
            if unit_id not in (None, "", [], {}):
                item["unitId"] = unit_id
            plan_school_data_id = ordered_unit.get("planSchoolDataId") or ordered_unit.get("plan_school_data_id")
            if plan_school_data_id not in (None, "", [], {}) and item.get("planSchoolDataId") in (None, "", [], {}):
                item["planSchoolDataId"] = plan_school_data_id
        candidate = _candidate_for_ordered_item(item, by_volunteer_id, by_legacy_prefix)
        enriched.append(_merge_ordered_item_with_candidate(item, candidate))
    return enriched


def _ordered_items_file_from_response(response: Any) -> dict[str, Any]:
    data = _response_data(response)
    ordered_state = _as_dict(data.get("orderedPlanState") or data.get("ordered_plan_state") or data)
    candidate_state = _as_dict(data.get("candidatePoolState") or data.get("candidate_pool_state"))
    enriched_items = _enrich_ordered_items_from_candidates(ordered_state, candidate_state)
    items = ordered_state.get("items")
    if not isinstance(items, list):
        items = ordered_state.get("units") if isinstance(ordered_state.get("units"), list) else []
    if enriched_items:
        items = enriched_items
    return {
        "available": bool(items or ordered_state.get("summary")),
        "version": _extract_version(data, ordered_state),
        "summary": _as_dict(ordered_state.get("summary")),
        "items": items,
        "units": ordered_state.get("units") if isinstance(ordered_state.get("units"), list) else [],
        "enriched": bool(enriched_items and candidate_state),
    }


def _candidate_file_from_response(response: Any) -> dict[str, Any]:
    data = _response_data(response)
    candidate_state = _as_dict(data.get("candidatePoolState") or data.get("candidate_pool_state") or data)
    items = candidate_state.get("items")
    if not isinstance(items, list):
        items = candidate_state.get("units") if isinstance(candidate_state.get("units"), list) else []
    page = _as_dict(data.get("page") or data.get("pagination") or candidate_state.get("page"))
    return {
        "available": bool(items or candidate_state.get("summary")),
        "version": _extract_version(data, candidate_state),
        "summary": _as_dict(candidate_state.get("summary")),
        "items": items,
        "page": page,
    }


def _pending_file_from_state(state: dict[str, Any] | PendingConfirmation | None, *, version: int = 0) -> dict[str, Any]:
    if isinstance(state, PendingConfirmation):
        return {
            "active": True,
            "kind": state.kind,
            "action_family": state.action_family,
            "preview_summary": state.preview_summary,
            "summary": state.preview_summary,
            "affected_scope": state.affected_scope,
            "execution_payload": dict(state.execution_payload or {}),
            "composite_proposal": dict(state.composite_proposal or {}),
            "source_backend_version": state.source_backend_version,
            "created_turn": state.created_turn,
        }
    data = _as_dict(state)
    if not data or str(data.get("status") or "active").strip() != "active":
        return {"active": False, "source_backend_version": version}
    execution_payload = _as_dict(data.get("executionPayload") or data.get("execution_payload"))
    composite_proposal = _as_dict(data.get("compositeProposal") or data.get("composite_proposal"))
    preview_summary = str(
        data.get("previewSummary")
        or data.get("preview_summary")
        or data.get("summary")
        or ""
    )
    return {
        "active": True,
        "pending_id": str(data.get("pendingId") or data.get("pending_id") or ""),
        "session_id": str(data.get("sessionId") or data.get("session_id") or ""),
        "kind": str(data.get("kind") or ""),
        "action_family": str(data.get("actionFamily") or data.get("action_family") or ""),
        "preview_summary": preview_summary,
        "summary": preview_summary,
        "user_goal": str(data.get("userGoal") or data.get("user_goal") or ""),
        "affected_scope": str(data.get("affectedScope") or data.get("affected_scope") or ""),
        "execution_payload": execution_payload,
        "composite_proposal": composite_proposal,
        "source_backend_version": _as_int(
            data.get("sourceBackendVersion") or data.get("source_backend_version"),
            default=version,
        ),
        "created_turn": _as_int(data.get("createdTurn") or data.get("created_turn")),
        "status": str(data.get("status") or "active"),
        "raw": dict(data),
    }


@dataclass(frozen=True)
class BackendReadResult:
    data: dict[str, Any]
    version: int = 0


@dataclass
class CacheEntry:
    data: dict[str, Any]
    version: int = 0
    fetched_at: float = field(default_factory=time.monotonic)
    ttl_seconds: float = _DEFAULT_TTL_SECONDS


class BackendAdapter:
    """Map sandbox paths to backend API calls and extract path-specific payloads."""

    def __init__(self, session_id: str, *, tenant_id: int | str = 1, batch: str | None = None) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.batch = batch or "01"

    @classmethod
    def supported_paths(cls) -> set[str]:
        return set(SUPPORTED_PATHS)

    async def read(self, path: str, query: dict[str, Any] | None = None) -> BackendReadResult:
        normalized_path = normalize_sandbox_path(path)
        if normalized_path == "score.json":
            response = await internal_client.get_user_score_detail(self.session_id)
            raw_data = _extract_extra_data_value(response, "userScoreDetail")
            return BackendReadResult(_score_file_from_backend(raw_data, batch=self.batch), _extract_version(response, raw_data))
        if normalized_path == "profile.json":
            response = await internal_client.get_user_init_profile(self.session_id)
            raw_data = _extract_extra_data_value(response, "userInitProfile")
            return BackendReadResult(_profile_file_from_backend(raw_data), _extract_version(response, raw_data))
        if normalized_path == "constraints.json":
            response = await internal_client.get_planning_workspace_state(self.session_id)
            state = _response_data(response)
            version = _extract_version(response, state)
            return BackendReadResult(_constraints_file_from_backend_state(state), version)
        if normalized_path == "plan/summary.json":
            response = await internal_client.get_planning_state(self.session_id)
            state = _response_data(response)
            version = _extract_version(response, state)
            return BackendReadResult(_plan_summary_file_from_backend_state(state), version)
        if normalized_path == "plan/items.json":
            response = await internal_client.get_planning_state(self.session_id)
            data = _ordered_items_file_from_response(response)
            return BackendReadResult(data, _extract_version(response, data))
        if normalized_path == "plan/candidates.json":
            query = query or {}
            response = await internal_client.query_planning_candidate_pool(
                self.tenant_id,
                self.session_id,
                tiers=_clean_string_list(query.get("tiers")),
                province_names=_clean_string_list(query.get("province_names") or query.get("provinceNames")),
                negative_province_names=_clean_string_list(
                    query.get("negative_province_names") or query.get("negativeProvinceNames")
                ),
                city_names=_clean_string_list(query.get("city_names") or query.get("cityNames")),
                negative_city_names=_clean_string_list(query.get("negative_city_names") or query.get("negativeCityNames")),
                school_keywords=_clean_string_list(query.get("school_keywords") or query.get("schoolKeywords")),
                negative_school_keywords=_clean_string_list(
                    query.get("negative_school_keywords") or query.get("negativeSchoolKeywords")
                ),
                major_keywords=_clean_string_list(query.get("major_keywords") or query.get("majorKeywords")),
                negative_major_keywords=_clean_string_list(
                    query.get("negative_major_keywords") or query.get("negativeMajorKeywords")
                ),
                school_tags=_clean_string_list(query.get("school_tags") or query.get("schoolTags")),
                negative_school_tags=_clean_string_list(
                    query.get("negative_school_tags") or query.get("negativeSchoolTags")
                ),
                major_tags=_clean_string_list(query.get("major_tags") or query.get("majorTags")),
                negative_major_tags=_clean_string_list(query.get("negative_major_tags") or query.get("negativeMajorTags")),
                page=max(1, _as_int(query.get("page"), 1)),
                page_size=max(1, _as_int(query.get("page_size") or query.get("pageSize"), 20)),
                sort_field=str(query.get("sort_field") or query.get("sortField") or "finalScore"),
                sort_order=str(query.get("sort_order") or query.get("sortOrder") or "desc"),
            )
            data = _candidate_file_from_response(response)
            return BackendReadResult(data, _extract_version(response, data))
        if normalized_path == "plan/review.json":
            response = await internal_client.get_planning_state(self.session_id)
            state = _response_data(response)
            version = _extract_version(response, state)
            return BackendReadResult(_review_file_from_backend_state(state), version)
        if normalized_path == "pending.json":
            response = await internal_client.get_last_pending_confirmation(self.session_id)
            raw_data = _extract_extra_data_value(response, "pendingConfirmation")
            if not raw_data:
                response = await internal_client.get_pending_confirmation(self.session_id)
                raw_data = _extract_extra_data_value(response, "pendingConfirmation")
            version = _extract_version(response, raw_data)
            data = _pending_file_from_state(raw_data, version=version)
            return BackendReadResult(data, _extract_version(data, response, raw_data))
        raise ValueError(f"unsupported sandbox path: {path}")


class SandboxFileCache:
    """Session-level virtual file cache with TTL and planning-version invalidation."""

    def __init__(
        self,
        session_id: str,
        adapter: Any,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        latest_backend_version: int = 0,
    ) -> None:
        self._session_id = session_id
        self._adapter = adapter
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._latest_backend_version = max(0, int(latest_backend_version or 0))

    @property
    def latest_backend_version(self) -> int:
        return self._latest_backend_version

    def update_latest_backend_version(self, version: int) -> None:
        self._latest_backend_version = max(self._latest_backend_version, _as_int(version))

    def prime(
        self,
        path: str,
        data: dict[str, Any],
        *,
        version: int = 0,
        ttl_seconds: float | None = None,
    ) -> None:
        normalized_path = normalize_sandbox_path(path)
        normalized_version = _as_int(version)
        if normalized_version > 0:
            self.update_latest_backend_version(normalized_version)
        self._cache[normalized_path] = CacheEntry(
            data=data,
            version=normalized_version,
            fetched_at=time.monotonic(),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self._ttl_seconds,
        )

    def peek(self, path: str) -> dict[str, Any] | None:
        normalized_path = normalize_sandbox_path(path)
        entry = self._cache.get(normalized_path)
        if entry is None or self._is_stale(normalized_path, entry):
            return None
        return entry.data

    async def read(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_path = normalize_sandbox_path(path)
        entry = self._cache.get(normalized_path)
        if entry is not None and query is None and not self._is_stale(normalized_path, entry):
            return entry.data

        result = await self._adapter.read(normalized_path, query=query)
        if isinstance(result, BackendReadResult):
            data = result.data
            version = result.version
        else:
            data = result if isinstance(result, dict) else {}
            version = _extract_version(data)
        if version > 0:
            self.update_latest_backend_version(version)
        if query is None:
            self._cache[normalized_path] = CacheEntry(
                data=data,
                version=_as_int(version),
                fetched_at=time.monotonic(),
                ttl_seconds=self._ttl_seconds,
            )
        return data

    def invalidate(self, paths: list[str] | tuple[str, ...] | set[str]) -> None:
        for path in paths:
            try:
                normalized_path = normalize_sandbox_path(path)
            except ValueError:
                continue
            self._cache.pop(normalized_path, None)

    async def warm(
        self,
        paths: list[str] | tuple[str, ...] = DEFAULT_WARM_PATHS,
        *,
        raise_on_error: bool = False,
    ) -> dict[str, dict[str, Any] | BaseException]:
        normalized_paths = [normalize_sandbox_path(path) for path in paths]
        results = await asyncio.gather(
            *(self.read(path) for path in normalized_paths),
            return_exceptions=True,
        )
        warmed: dict[str, dict[str, Any] | BaseException] = {}
        for path, result in zip(normalized_paths, results):
            warmed[path] = result
            if raise_on_error and isinstance(result, BaseException):
                raise result
        return warmed

    def _is_stale(self, path: str, entry: CacheEntry) -> bool:
        if (time.monotonic() - entry.fetched_at) > entry.ttl_seconds:
            return True
        if path.startswith("plan/") or path == "constraints.json" or path == "pending.json":
            return entry.version < self._latest_backend_version
        return False


def build_request_sandbox(
    *,
    session_id: str,
    tenant_id: int | str = 1,
    batch: str | None = None,
    score_detail: Any = None,
    init_profile: UserProfile | None = None,
    planning_state: dict[str, Any] | None = None,
    planning_summary: PlanningSummary | None = None,
    pending_state: dict[str, Any] | None = None,
    pending: PendingConfirmation | None = None,
) -> SandboxFileCache:
    planning_version = _extract_version(planning_state or {}, planning_summary.__dict__ if planning_summary else {})
    sandbox = SandboxFileCache(
        session_id,
        BackendAdapter(session_id, tenant_id=tenant_id, batch=batch),
        latest_backend_version=planning_version,
    )
    sandbox.prime("score.json", _score_file_from_object(score_detail, batch=batch))
    if init_profile is not None:
        sandbox.prime("profile.json", _profile_file_from_model(init_profile))
    else:
        sandbox.prime("profile.json", _profile_file_from_summary(planning_summary))
    if planning_state:
        sandbox.prime("plan/summary.json", _plan_summary_file_from_backend_state(planning_state), version=planning_version)
        sandbox.prime("plan/review.json", _review_file_from_backend_state(planning_state), version=planning_version)
        sandbox.prime("constraints.json", _constraints_file_from_backend_state(planning_state), version=planning_version)
    else:
        sandbox.prime("plan/summary.json", _plan_summary_file_from_object(planning_summary), version=planning_version)
    pending_version = _extract_version(pending_state or {}) or planning_version
    sandbox.prime("pending.json", _pending_file_from_state(pending_state or pending, version=pending_version), version=pending_version)
    return sandbox
