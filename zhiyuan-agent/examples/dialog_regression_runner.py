#!/usr/bin/env python3
"""Run real websocket dialog regression cases against the local compat endpoint.

Usage:
  ./.venv/bin/python examples/dialog_regression_runner.py
  ./.venv/bin/python examples/dialog_regression_runner.py --cases examples/dialog_regression_cases.json
  ./.venv/bin/python examples/dialog_regression_runner.py --session 35 --prompts "方案有了么" "帮我审查一下"
  ./.venv/bin/python examples/dialog_regression_runner.py --cases examples/dialog_regression_plan_cases.json --assert-plan-style
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sqlite3
import statistics
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib import error, request

import websockets

DEFAULT_URL = (
    os.environ.get("ZHIYUAN_REGRESSION_AGENT_URL")
    or os.environ.get("AGENT_DIALOG_E2E_URL")
    or "ws://127.0.0.1:18291/gaotu-assistant-agent/plus/chat/1/bot/test/do"
)
DEFAULT_USER_ID = "dialog-regression-user"
DEFAULT_HISTORY_DB = Path(__file__).resolve().parents[1] / "data" / "chat_history.db"
DEFAULT_INTERNAL_SERVICE_URL = (
    os.environ.get("ZHIYUAN_REGRESSION_BACKEND_URL")
    or os.environ.get("INTERNAL_SERVICE_URL")
    or "http://127.0.0.1:18290"
)
DEFAULT_BACKEND_DB_HOST = os.environ.get("ZHIYUAN_REGRESSION_DB_HOST") or "127.0.0.1"
DEFAULT_BACKEND_DB_PORT = os.environ.get("ZHIYUAN_REGRESSION_DB_PORT") or "3306"
DEFAULT_BACKEND_DB_USER = os.environ.get("ZHIYUAN_REGRESSION_DB_USER") or "root"
DEFAULT_BACKEND_DB_NAME = os.environ.get("ZHIYUAN_REGRESSION_DB_NAME") or "sales_bot"
DEFAULT_BACKEND_DB_PASSWORD = os.environ.get("ZHIYUAN_REGRESSION_DB_PASSWORD") or os.environ.get("MYSQL_PWD") or ""
DEFAULT_BACKEND_VOLUNTEER_DATA_DIR = (
    os.environ.get("ZHIYUAN_REGRESSION_VOLUNTEER_DATA_DIR")
    or str(Path(__file__).resolve().parents[2] / "zhiyuan-server" / "data" / "tmp")
)
PENDING_STATE_KEYS = ("pendingConfirmation", "planEditCache")
BACKEND_STATE_CLONE_KEYS = ("planningState", "userprofile", "userScoreDetail")
BACKEND_VOLUNTEER_FILE_SUFFIXES = ("", "_temp", "_final", "_temp_summary", "_final_summary")

EMPTY_CONSTRAINT_STATE = {
    "hardConstraints": {
        "mustIncludeRegions": [],
        "mustExcludeRegions": [],
        "mustIncludeMajors": [],
        "mustExcludeMajors": [],
        "mustIncludeSchools": [],
        "mustExcludeSchools": [],
    },
    "softPreferences": {
        "preferRegions": [],
        "preferMajors": [],
        "preferSchools": [],
        "avoidRegions": [],
        "avoidMajors": [],
        "avoidSchools": [],
    },
    "derivedPreferences": {
        "recommendedMajorClusters": [],
        "riskToleranceInferred": None,
        "tuitionFlexibilityInferred": None,
        "employmentOrientationInferred": [],
    },
}

EMPTY_EXPLICIT_PROFILE = {
    "positiveSchools": [],
    "negativeSchools": [],
    "positiveMajors": [],
    "negativeMajors": [],
    "positiveRegions": [],
    "negativeRegions": [],
}

EMPTY_USER_PROFILE_INTENT_FIELDS = {
    "major_intent": {
        "level1": [],
        "level2": [],
        "level3": [],
        "level1_emotion": [],
        "level2_emotion": [],
        "level3_emotion": [],
    },
    "negative_major_intent": {
        "level1": [],
        "level2": [],
        "level3": [],
        "level1_emotion": [],
        "level2_emotion": [],
        "level3_emotion": [],
    },
    "college_info": {
        "values": [],
        "values_emotion": [],
    },
    "negative_college_info": {
        "values": [],
        "values_emotion": [],
    },
    "city_info": {
        "province": [],
        "province_emotion": [],
        "city": [],
        "city_emotion": [],
        "area": [],
    },
    "negative_city_info": {
        "province": [],
        "province_emotion": [],
        "city": [],
        "city_emotion": [],
        "area": [],
    },
}

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "name": "plan-empty-status",
        "sessionId": "35",
        "prompts": ["方案有了么"],
    },
    {
        "name": "plan-generate-then-status",
        "sessionId": "35",
        "prompts": ["直接生成一版方案", "确认", "方案有了么"],
    },
    {
        "name": "plan-reviewed-status",
        "sessionId": "26",
        "prompts": ["方案有了么"],
    },
]

PLAN_STYLE_BANNED_SUBSTRINGS = [
    "你必须决定",
    "必须做出选择",
    "必须做一个选择",
    "必须选一个",
    "我无法继续回应",
    "我不再重复解释",
    "我不再回应",
    "最后一次说明",
    "必须停止这个循环",
    "停止这个循环",
    "完全没有意义",
    "当前这版财会类方案就是最优解",
    "当前这版财会类方案保留",
    "我现在直接帮你重新生成",
    "你现在必须决定",
    "你选哪个",
    "请选一个",
    "请明确回复",
    "回复 A 或 B",
    "没有第三个选项",
    "补偿预览",
    "不要再反复查看",
    "选 A/B/C",
    "选 A、B 或 C",
    "选 A、B、C",
    "当前前5位概况",
    "当前前 5 位概况",
    "前5位概况",
    "前 5 位概况",
]

PLAN_STYLE_BANNED_EXACT_LINES = {"你。", "只有。", "请。"}

ROUTING_PATH_BY_HISTORY_MODEL_NAME = {
    "semantic-router-shadow": "",
    "plan-fast-route": "plan_fast_route",
    "plan-query-fast-route": "plan_query_fast_route",
    "major-intent-fast-route": "major_intent_fast_route",
    "major-compare-fast-route": "major_compare_fast_route",
    "career-direction-fast-route": "career_direction_fast_route",
    "pending-intent-impact-fast-route": "pending_intent_impact_fast_route",
    "direct-pending-plan-confirmation": "direct_pending_plan_confirm",
    "direct-pending-intent-confirmation": "direct_pending_intent_confirm",
    "direct-plan-confirmation-guard": "plan_confirmation_guard_no_pending",
    "direct-readonly-closure-ack": "readonly_closure_ack",
}

ROUTING_PATH_BY_TOOL_CALL_ID_PREFIX = (
    ("fast-plan-next-", "plan_fast_route"),
    ("fast-execute-", "plan_fast_route"),
    ("fast-query-volunteer-plan", "plan_query_fast_route"),
    ("fast-preview-major-intent", "major_intent_fast_route"),
    ("fast-compare-majors", "major_compare_fast_route"),
    ("fast-analyze-current-career-direction", "career_direction_fast_route"),
    ("direct-pending-intent-confirmation", "direct_pending_intent_confirm"),
)

STRUCTURED_FOLLOWUP_TYPES = {
    "planningWorkspaceAction",
    "pendingConfirmationCard",
    "interestAnalysisPopup",
    "planEditSelectPopup",
    "intentDetectSelectPopup",
    "intentConfirmPopup",
}

PENDING_APPLY_ROUTING_PATHS = {
    "direct_pending_plan_confirm",
    "direct_pending_intent_confirm",
    "pending_plan_short_text_confirm",
    "pending_intent_short_text_confirm",
    "plan_confirmation_card_confirm",
    "intent_confirmation_card_confirm",
}

READONLY_APPLIED_ACTION_FAMILIES = {
    "analyze_adjustment",
    "query_ordered",
    "query_state",
    "review_plan",
}

READONLY_APPLIED_RESULT_KINDS = {
    "adjustment_analysis",
    "ordered_snapshot",
    "review_result",
    "status_overview",
}

PENDING_APPLY_ACTION_FAMILIES = {
    "apply_existing_pending",
    "apply_fix_proposal",
    "apply_selected_intents",
}

PENDING_APPLY_MESSAGE_CODES = {
    "constraint_applied",
    "preference_applied",
}

FOLLOWUP_USER_TEXT_FIELDS = (
    "title",
    "summary",
    "content",
    "impactTitle",
    "impact",
    "actionText",
    "confirmText",
    "cancelText",
)


def _is_structured_followup_message(message: dict[str, Any]) -> bool:
    message_type = str(message.get("type") or "").strip()
    if message_type in STRUCTURED_FOLLOWUP_TYPES:
        return True
    content = message.get("content")
    if isinstance(content, dict):
        content_type = str(content.get("type") or "").strip()
        if content_type in STRUCTURED_FOLLOWUP_TYPES:
            return True
    return False


def _is_silent_workspace_action_message(message: dict[str, Any]) -> bool:
    message_type = str(message.get("type") or "").strip()
    content = message.get("content")
    content_obj = content if isinstance(content, dict) else {}
    content_type = str(content_obj.get("type") or "").strip()
    return (
        (message_type == "planningWorkspaceAction" or content_type == "planningWorkspaceAction")
        and bool(content_obj.get("silent"))
    )


def _split_primary_and_followup_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    followups: list[dict[str, Any]] = []
    for message in messages:
        if _is_structured_followup_message(message):
            followups.append(message)
        else:
            primary.append(message)
    return primary, followups


async def _ask_once(
    url: str,
    session_id: str,
    user_id: str,
    prompt: str,
    *,
    open_timeout: float = 30,
    response_timeout: float = 120,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int | None]]:
    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "content": prompt,
        "inputType": "text",
    }
    started_at = time.perf_counter()
    first_message_at: float | None = None
    final_message_at: float | None = None
    async with websockets.connect(url, max_size=2**22, open_timeout=open_timeout) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        streamed_messages: list[dict[str, Any]] = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=response_timeout)
            now = time.perf_counter()
            if first_message_at is None:
                first_message_at = now
            message = json.loads(raw)
            streamed_messages.append(message)
            if message.get("end") is True:
                final_message_at = now
                break

        primary, streamed_followups = _split_primary_and_followup_messages(streamed_messages)
        followups: list[dict[str, Any]] = list(streamed_followups)
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            followup_message = json.loads(raw)
            followups.append(followup_message)

    timing = {
        "firstMessageMs": int(((first_message_at or final_message_at or time.perf_counter()) - started_at) * 1000),
        "finalMessageMs": int(((final_message_at or time.perf_counter()) - started_at) * 1000),
    }
    return primary, followups, timing


def _load_cases(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return DEFAULT_CASES
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _expand_case_payload(data)


def _expand_case_payload(data: Any) -> list[dict[str, Any]]:
    report_path = Path(__file__).with_name("dialog_case_evaluation_report.py")
    spec = importlib.util.spec_from_file_location("dialog_case_evaluation_report_for_runner", report_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load dialog_case_evaluation_report from {report_path}")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    expand_case_payload = report._expand_case_payload

    return expand_case_payload(data)


def _offset_session_id(session_id: Any, session_offset: int) -> str:
    """Return the session id after applying a numeric offset.

    Backend chatSessionId is numeric in the current system, so offset mode only
    supports numeric case session ids.
    """
    value = str(session_id)
    if session_offset == 0:
        return value
    if not value.isdigit():
        raise ValueError(f"--session-offset requires numeric sessionId, got {value!r}")
    shifted = int(value) + session_offset
    if shifted <= 0:
        raise ValueError(f"--session-offset produced non-positive sessionId: {value} + {session_offset}")
    return str(shifted)


def _apply_session_offset(cases: list[dict[str, Any]], session_offset: int) -> list[dict[str, Any]]:
    if session_offset == 0:
        return cases
    adjusted = deepcopy(cases)
    for case in adjusted:
        if "sessionId" not in case:
            raise ValueError("--session-offset requires every case to define sessionId")
        original_session_id = case["sessionId"]
        case["sessionId"] = _offset_session_id(original_session_id, session_offset)
        case["baseSessionId"] = str(original_session_id)
        if "cloneBackendStateFromSessionId" not in case and case.get("sourceSessionId"):
            case["cloneBackendStateFromSessionId"] = str(case["sourceSessionId"])
        if "cloneBackendStateFromSessionId" not in case and _case_requires_backend_state_clone(case):
            case["cloneBackendStateFromSessionId"] = str(original_session_id)
    return adjusted


def _filter_cases_by_name(cases: list[dict[str, Any]], names: list[str] | None) -> list[dict[str, Any]]:
    expected = [str(name).strip() for name in names or [] if str(name).strip()]
    if not expected:
        return cases
    expected_set = set(expected)
    filtered = [case for case in cases if str(case.get("name") or "") in expected_set]
    found = {str(case.get("name") or "") for case in filtered}
    missing = [name for name in expected if name not in found]
    if missing:
        raise ValueError(f"--case-name did not match any case: {', '.join(missing)}")
    return filtered


def _case_session_ids(cases: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for case in cases:
        session_id = str(case["sessionId"])
        if session_id in seen:
            continue
        seen.add(session_id)
        result.append(session_id)
    return result


def _case_requires_active_pending(case: dict[str, Any]) -> bool:
    contract = case.get("fixtureContract")
    if not isinstance(contract, dict):
        return False
    required_state = {
        str(item or "").strip()
        for item in (contract.get("requiredState") or [])
        if str(item or "").strip()
    }
    return "activePending" in required_state


def _case_requires_backend_state_clone(case: dict[str, Any]) -> bool:
    contract = case.get("fixtureContract")
    if not isinstance(contract, dict):
        return False
    required_state = {
        str(item or "").strip()
        for item in (contract.get("requiredState") or [])
        if str(item or "").strip()
    }
    if required_state & {
        "orderedPlan",
        "formalPlan",
        "candidatePool",
        "reviewState",
        "specialPathContext",
        "activePending",
    }:
        return True
    fixture_type = str(contract.get("type") or "").strip()
    return fixture_type in {
        "formal_plan_present",
        "pending_exists",
        "special_path_profile",
    }


def _backend_state_clone_keys_for_case(case: dict[str, Any]) -> tuple[str, ...]:
    keys = list(BACKEND_STATE_CLONE_KEYS)
    if _case_requires_active_pending(case):
        for key in PENDING_STATE_KEYS:
            if key not in keys:
                keys.append(key)
    return tuple(keys)


def _clone_results_have_active_pending(clone_results: list[dict[str, Any]]) -> bool:
    for item in clone_results:
        if not isinstance(item, dict):
            continue
        if str(item.get("key") or "").strip() != "pendingConfirmation":
            continue
        if item.get("ok") is not True or item.get("skipped"):
            continue
        if str(item.get("sourcePendingStatus") or "").strip() == "active":
            return True
    return False


def _clear_history(db_path: Path, session_ids: list[str]) -> int:
    if not session_ids or not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        cursor = conn.executemany(
            "DELETE FROM chat_session_history WHERE session_id = ?",
            [(session_id,) for session_id in session_ids],
        )
        conn.commit()
    return cursor.rowcount if cursor.rowcount is not None else 0


def _clear_backend_pending_state(
    base_url: str,
    session_ids: list[str],
    *,
    timeout_seconds: float = 5,
) -> list[dict[str, Any]]:
    """Clear backend pending state used by confirmation-card flows.

    SQLite history cleanup is not enough for live regression: pending
    confirmations live in backend extra-data and can otherwise leak across
    cases that reuse real session ids.
    """
    results: list[dict[str, Any]] = []
    normalized_base_url = str(base_url or "").rstrip("/")
    if not normalized_base_url:
        return results
    for session_id in session_ids:
        for key in PENDING_STATE_KEYS:
            payload = {
                "chatSessionId": session_id,
                "dataKey": key,
                "dataType": "JSON_OBJECT",
                "dataValue": {},
                "version": 0,
            }
            req = request.Request(
                f"{normalized_base_url}/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            result: dict[str, Any] = {"session": session_id, "key": key, "ok": False}
            try:
                with request.urlopen(req, timeout=timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                result["status"] = response.status
                result["ok"] = 200 <= int(response.status) < 300
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        parsed = raw[:200]
                    result["response"] = parsed
            except (OSError, error.URLError, TimeoutError) as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
            results.append(result)
    return results


def _http_get_json(url: str, *, timeout_seconds: float = 5) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _write_backend_extra_data(
    base_url: str,
    session_id: str,
    key: str,
    value: dict[str, Any],
    *,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    normalized_base_url = str(base_url or "").rstrip("/")
    payload = {
        "chatSessionId": session_id,
        "dataKey": key,
        "dataType": "JSON_OBJECT",
        "dataValue": value,
        "version": 0,
    }
    req = request.Request(
        f"{normalized_base_url}/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    result: dict[str, Any] = {"status": response.status}
    if raw:
        try:
            result["response"] = json.loads(raw)
        except Exception:
            result["response"] = raw[:200]
    return result


def _get_backend_extra_data(
    base_url: str,
    session_id: str,
    key: str,
    *,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    normalized_base_url = str(base_url or "").rstrip("/")
    data = _http_get_json(
        f"{normalized_base_url}/gaotu-assistant-bot/inner/chat/1/session/get-extra-data"
        f"?chatSessionId={session_id}&keyList={key}&version=0",
        timeout_seconds=timeout_seconds,
    )
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _clear_profile_intent_fields(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(profile) if isinstance(profile, dict) else {}
    for key, value in EMPTY_USER_PROFILE_INTENT_FIELDS.items():
        cleaned[key] = deepcopy(value)
    return cleaned


def _clear_planning_intent_fields(planning_state: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(planning_state) if isinstance(planning_state, dict) else {}
    profile_state = cleaned.setdefault("profileState", {})
    if not isinstance(profile_state, dict):
        profile_state = {}
        cleaned["profileState"] = profile_state
    explicit_profile = profile_state.setdefault("explicitProfile", {})
    if not isinstance(explicit_profile, dict):
        explicit_profile = {}
        profile_state["explicitProfile"] = explicit_profile
    explicit_profile.update(deepcopy(EMPTY_EXPLICIT_PROFILE))
    cleaned["constraintState"] = deepcopy(EMPTY_CONSTRAINT_STATE)
    return cleaned


def _clear_backend_planning_intent_state(
    base_url: str,
    session_ids: list[str],
    *,
    timeout_seconds: float = 5,
) -> list[dict[str, Any]]:
    """Clear accepted intent/preference state while preserving plan data.

    Some live regression cases intentionally reuse real sessions that already
    have candidate/ordered/review state. A clean-dialog intent case should not
    inherit previously accepted preferences from the same session, so this
    helper resets only the profile/constraint intent fields.
    """
    results: list[dict[str, Any]] = []
    normalized_base_url = str(base_url or "").rstrip("/")
    if not normalized_base_url:
        return results
    for session_id in session_ids:
        result: dict[str, Any] = {"session": session_id, "ok": False, "keys": []}
        try:
            planning_state = _get_backend_extra_data(
                normalized_base_url,
                session_id,
                "planningState",
                timeout_seconds=timeout_seconds,
            )
            if planning_state:
                cleaned_planning_state = _clear_planning_intent_fields(planning_state)
                write_result = _write_backend_extra_data(
                    normalized_base_url,
                    session_id,
                    "planningState",
                    cleaned_planning_state,
                    timeout_seconds=timeout_seconds,
                )
                result["keys"].append("planningState")
                result["planningStateStatus"] = write_result.get("status")

            user_profile = _get_backend_extra_data(
                normalized_base_url,
                session_id,
                "userprofile",
                timeout_seconds=timeout_seconds,
            )
            if user_profile:
                cleaned_user_profile = _clear_profile_intent_fields(user_profile)
                write_result = _write_backend_extra_data(
                    normalized_base_url,
                    session_id,
                    "userprofile",
                    cleaned_user_profile,
                    timeout_seconds=timeout_seconds,
                )
                result["keys"].append("userprofile")
                result["userprofileStatus"] = write_result.get("status")
            result["ok"] = True
        except (OSError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _clone_backend_session_state(
    base_url: str,
    *,
    source_session_id: str,
    target_session_id: str,
    keys: tuple[str, ...] = BACKEND_STATE_CLONE_KEYS,
    timeout_seconds: float = 5,
) -> list[dict[str, Any]]:
    """Clone backend extra-data state for destructive live regression cases."""
    results: list[dict[str, Any]] = []
    normalized_base_url = str(base_url or "").rstrip("/")
    if not normalized_base_url:
        return results
    for key in keys:
        result: dict[str, Any] = {
            "sourceSession": source_session_id,
            "targetSession": target_session_id,
            "key": key,
            "ok": False,
        }
        try:
            value = _get_backend_extra_data(
                normalized_base_url,
                source_session_id,
                key,
                timeout_seconds=timeout_seconds,
            )
            if not value:
                result["skipped"] = "source_empty"
                result["ok"] = True
                results.append(result)
                continue
            cloned_value = deepcopy(value)
            if key == "planningState":
                cloned_value["sessionId"] = int(target_session_id) if target_session_id.isdigit() else target_session_id
            elif key == "pendingConfirmation":
                result["sourcePendingStatus"] = str(value.get("status") or "").strip()
                result["sourcePendingKind"] = str(value.get("kind") or "").strip()
            write_result = _write_backend_extra_data(
                normalized_base_url,
                target_session_id,
                key,
                cloned_value,
                timeout_seconds=timeout_seconds,
            )
            result["status"] = write_result.get("status")
            result["ok"] = 200 <= int(write_result.get("status") or 0) < 300
        except (OSError, error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _clone_backend_chat_session_row(
    *,
    source_session_id: str,
    target_session_id: str,
    db_host: str,
    db_port: str,
    db_user: str,
    db_password: str,
    db_name: str,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Clone assistant_chat_session row for live destructive regression sessions.

    Extra-data cloning is not sufficient for apply flows that refresh
    recommendation data through ChatSession. Keep this test-runner-only and
    explicit via --clone-backend-chat-session.
    """

    result: dict[str, Any] = {
        "sourceSession": source_session_id,
        "targetSession": target_session_id,
        "table": "assistant_chat_session",
        "ok": False,
    }
    if not str(source_session_id).isdigit() or not str(target_session_id).isdigit():
        result["error"] = "source and target session ids must be numeric"
        return result
    sql = (
        "INSERT INTO assistant_chat_session "
        "(id, tenant_id, user_id, bot_id, mobile, user_name, session_status, start_time, end_time, create_time, update_time) "
        "SELECT {target_id}, tenant_id, user_id, bot_id, mobile, "
        "CONCAT(COALESCE(user_name, ''), '-regression-{target_id}'), session_status, start_time, end_time, NOW(), NOW() "
        "FROM assistant_chat_session src "
        "WHERE src.id = {source_id} "
        "AND NOT EXISTS (SELECT 1 FROM assistant_chat_session dst WHERE dst.id = {target_id}); "
        "SELECT ROW_COUNT();"
    ).format(source_id=int(source_session_id), target_id=int(target_session_id))
    cmd = [
        "mysql",
        f"-h{db_host}",
        f"-P{db_port}",
        f"-u{db_user}",
        "-N",
        "-B",
        db_name,
        "-e",
        sql,
    ]
    env = os.environ.copy()
    if db_password:
        env["MYSQL_PWD"] = db_password
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["returnCode"] = proc.returncode
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()
    if proc.stdout.strip():
        result["stdout"] = proc.stdout.strip()
    if proc.returncode != 0:
        result["error"] = proc.stderr.strip() or f"mysql exited {proc.returncode}"
        return result
    inserted = 0
    for line in reversed([item.strip() for item in proc.stdout.splitlines() if item.strip()]):
        try:
            inserted = int(line)
            break
        except ValueError:
            continue
    result["insertedRows"] = inserted
    result["ok"] = True
    result["skipped"] = "target_exists" if inserted == 0 else None
    return result


def _clone_backend_volunteer_data_files(
    *,
    source_session_id: str,
    target_session_id: str,
    data_dir: str | Path,
    suffixes: tuple[str, ...] = BACKEND_VOLUNTEER_FILE_SUFFIXES,
) -> dict[str, Any]:
    """Clone local session_volunteer files for live apply-flow regressions.

    Java apply flows refresh recommendation overlays from the original
    session_volunteer_{session}.json source file. Disposable cloned sessions
    need the same local source files, otherwise apply fails before reaching
    business logic.
    """

    result: dict[str, Any] = {
        "sourceSession": source_session_id,
        "targetSession": target_session_id,
        "dataDir": str(data_dir),
        "ok": False,
        "files": [],
    }
    if not str(source_session_id).isdigit() or not str(target_session_id).isdigit():
        result["error"] = "source and target session ids must be numeric"
        return result

    root = Path(data_dir)
    copied = 0
    original_present = False
    for suffix in suffixes:
        source = root / f"session_volunteer_{source_session_id}{suffix}.json"
        target = root / f"session_volunteer_{target_session_id}{suffix}.json"
        file_result: dict[str, Any] = {
            "suffix": suffix,
            "source": str(source),
            "target": str(target),
            "ok": False,
        }
        if not source.exists():
            file_result["skipped"] = "source_missing"
            file_result["ok"] = True
            result["files"].append(file_result)
            continue
        if suffix == "":
            original_present = True
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
            file_result["ok"] = True
            file_result["copied"] = True
            file_result["bytes"] = target.stat().st_size
        except OSError as exc:
            file_result["error"] = f"{type(exc).__name__}: {exc}"
        result["files"].append(file_result)

    failed = [item for item in result["files"] if not item.get("ok")]
    result["copiedFiles"] = copied
    if failed:
        result["error"] = "some files failed to copy"
        return result
    if not original_present:
        result["error"] = "source original session_volunteer file missing"
        return result
    result["ok"] = True
    return result


def _load_history_json(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT history_json FROM chat_session_history WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return []
    try:
        data = json.loads(str(row[0] or "[]"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _latest_turn_messages(history: list[dict[str, Any]], prompt: str) -> list[dict[str, Any]]:
    """Return messages for the latest persisted turn matching prompt."""
    prompt_text = str(prompt or "")
    start_index: int | None = None
    for index in range(len(history) - 1, -1, -1):
        message = history[index] if isinstance(history[index], dict) else {}
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("part_kind") == "user-prompt" and str(part.get("content") or "") == prompt_text:
                start_index = index
                break
        if start_index is not None:
            break
    if start_index is None:
        return []
    return history[start_index:]


def _plan_payload_fields_from_call_args(args: dict[str, Any]) -> dict[str, Any]:
    raw_payload = args.get("plan_payload")
    if not isinstance(raw_payload, str) or not raw_payload.strip():
        return {}
    payload = _parse_json_object(raw_payload)
    if not payload:
        return {}
    result: dict[str, Any] = {}
    action_family = str(payload.get("action_family") or "").strip()
    stage = str(payload.get("stage") or "").strip()
    if action_family:
        result["actionFamily"] = action_family
    if stage:
        result["stage"] = stage
    return result


def _add_unique(target: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _routing_path_from_model_name(model_name: Any) -> str:
    return ROUTING_PATH_BY_HISTORY_MODEL_NAME.get(str(model_name or "").strip(), "")


def _routing_path_from_tool_call_id(call_id: Any) -> str:
    text = str(call_id or "").strip()
    for prefix, routing_path in ROUTING_PATH_BY_TOOL_CALL_ID_PREFIX:
        if text.startswith(prefix):
            return routing_path
    if text.startswith("direct-") and text.endswith("-confirmation"):
        return "direct_pending_plan_confirm"
    return ""


def _summarize_turn_observability(turn_messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract tool/action metadata from persisted pydantic-ai JSON history."""
    tool_calls: list[dict[str, Any]] = []
    returns_by_call_id: dict[str, dict[str, Any]] = {}
    tool_return_count = 0
    action_families: list[str] = []
    result_kinds: list[str] = []
    routing_paths: list[str] = []
    semantic_router_shadow: dict[str, Any] | None = None
    route_decision: dict[str, Any] | None = None
    event_timings: dict[str, Any] = {}

    for message in turn_messages:
        if not isinstance(message, dict):
            continue
        _add_unique(routing_paths, _routing_path_from_model_name(message.get("model_name")))
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            kind = part.get("part_kind")
            tool_name = str(part.get("tool_name") or "").strip()
            call_id = str(part.get("tool_call_id") or "").strip()
            if kind == "tool-call" and tool_name:
                _add_unique(routing_paths, _routing_path_from_tool_call_id(call_id))
                args = _parse_json_object(part.get("args"))
                item: dict[str, Any] = {"name": tool_name}
                if call_id:
                    item["toolCallId"] = call_id
                action_family = str(args.get("action_family") or "").strip()
                if tool_name == "execute_plan_action":
                    item.update(_plan_payload_fields_from_call_args(args))
                    action_family = action_family or str(item.get("actionFamily") or "").strip()
                elif action_family:
                    item["actionFamily"] = action_family
                stage = str(args.get("current_stage") or "").strip()
                if stage:
                    item["stage"] = stage
                _add_unique(action_families, item.get("actionFamily"))
                tool_calls.append(item)
                continue
            if kind == "tool-return" and tool_name:
                tool_return_count += 1
                data = _parse_json_object(part.get("content"))
                if call_id and data:
                    returns_by_call_id[call_id] = data
                continue
            if kind == "text" and message.get("model_name") == "semantic-router-shadow":
                data = _parse_json_object(part.get("content"))
                shadow = data.get("semanticRouterShadow") if isinstance(data, dict) else None
                if isinstance(shadow, dict):
                    semantic_router_shadow = shadow
                continue
            if kind == "text":
                data = _parse_json_object(part.get("content"))
                if data.get("event") == "conversation_turn_event":
                    _add_unique(routing_paths, data.get("routingPath"))
                    _add_unique(action_families, data.get("actionFamily"))
                    _add_unique(result_kinds, data.get("resultKind"))
                    for observed_tool in data.get("toolCalls") or []:
                        if not isinstance(observed_tool, dict):
                            continue
                        _add_unique(action_families, observed_tool.get("actionFamily"))
                        _add_unique(result_kinds, observed_tool.get("resultKind"))
                    raw_route_decision = data.get("routeDecision")
                    if isinstance(raw_route_decision, dict):
                        route_decision = raw_route_decision
                    for key in (
                        "totalDurationMs",
                        "llmDurationMs",
                        "toolDurationMs",
                        "classificationDurationMs",
                        "preSemanticRouteDurationMs",
                        "preFullAgentDurationMs",
                        "historyLoadDurationMs",
                        "pendingLoadDurationMs",
                        "initialStateLoadDurationMs",
                        "runtimeHistoryBuildDurationMs",
                        "backendContextLoadDurationMs",
                        "requestContextBuildDurationMs",
                        "guardPipelineDurationMs",
                        "turnDecisionDurationMs",
                        "turnDecisionCacheHitCount",
                        "intentEntityProfileDurationMs",
                        "intentSideEffectDurationMs",
                        "postFullAgentDurationMs",
                        "unattributedDurationMs",
                        "toolCallCount",
                    ):
                        if data.get(key) is not None:
                            event_timings[key] = data.get(key)

    for item in tool_calls:
        call_id = str(item.get("toolCallId") or "")
        returned = returns_by_call_id.get(call_id) or {}
        action_family = str(returned.get("action_family") or item.get("actionFamily") or "").strip()
        stage = str(returned.get("stage") or item.get("stage") or "").strip()
        result_kind = str(returned.get("result_kind") or "").strip()
        if action_family:
            item["actionFamily"] = action_family
            _add_unique(action_families, action_family)
        if stage:
            item["stage"] = stage
        if result_kind:
            item["resultKind"] = result_kind
            _add_unique(result_kinds, result_kind)
        if "applied" in returned:
            item["applied"] = bool(returned.get("applied"))
        message_code = str(returned.get("messageCode") or "").strip()
        if message_code:
            item["messageCode"] = message_code
        if returned:
            item["success"] = result_kind != "error"

    summary = {
        "historyMessages": len(turn_messages),
        "toolCallCount": len(tool_calls),
        "toolReturnCount": tool_return_count,
        "toolCalls": tool_calls,
        "actionFamilies": action_families,
        "resultKinds": result_kinds,
    }
    if routing_paths:
        summary["routingPath"] = routing_paths[0]
        if len(routing_paths) > 1:
            summary["routingPathCandidates"] = routing_paths
    if semantic_router_shadow:
        summary["semanticRouterShadow"] = semantic_router_shadow
    if event_timings:
        summary["eventTimings"] = event_timings
    if route_decision:
        summary["routeDecision"] = route_decision
        post_apply_evidence_plan = route_decision.get("postApplyEvidencePlan")
        if isinstance(post_apply_evidence_plan, dict):
            summary["postApplyEvidencePlan"] = post_apply_evidence_plan
        agent_run = route_decision.get("agentRun")
        if isinstance(agent_run, dict):
            failed_node = str(agent_run.get("failedNode") or "").strip()
            error_type = str(agent_run.get("errorType") or "").strip()
            error_message = str(agent_run.get("errorMessage") or "").strip()
            if failed_node or error_type or error_message:
                summary["agentRunFailure"] = {
                    key: value
                    for key, value in {
                        "failedNode": failed_node,
                        "failedNodeIndex": agent_run.get("failedNodeIndex"),
                        "failedNodeElapsedMs": agent_run.get("failedNodeElapsedMs"),
                        "errorType": error_type,
                        "errorMessage": error_message,
                        "errorStatusCode": agent_run.get("errorStatusCode"),
                        "errorResponseText": agent_run.get("errorResponseText"),
                        "totalDurationMs": agent_run.get("totalDurationMs"),
                    }.items()
                    if value not in (None, "")
                }
        arbitration = route_decision.get("arbitration")
        if isinstance(arbitration, dict):
            summary["fastRouteArbitration"] = arbitration
    return summary


def _followup_summary(followups: list[dict[str, Any]]) -> tuple[list[str], list[bool], list[str]]:
    targets: list[str] = []
    refreshes: list[bool] = []
    types: list[str] = []
    for item in followups:
        item_type = str(item.get("type") or "").strip()
        if item_type and item_type not in types:
            types.append(item_type)
        content = item.get("content")
        if not isinstance(content, dict):
            continue
        content_type = str(content.get("type") or "").strip()
        if content_type and content_type not in types:
            types.append(content_type)
        target = content.get("targetView")
        if target is not None:
            text = str(target).strip()
            if text and text not in targets:
                targets.append(text)
        refresh = content.get("refresh")
        if isinstance(refresh, bool):
            refreshes.append(refresh)
    return targets, refreshes, types


def _followup_content_dict(followup: dict[str, Any]) -> dict[str, Any]:
    content = followup.get("content")
    if isinstance(content, dict):
        return content
    parsed = _parse_json_object(content)
    return parsed if isinstance(parsed, dict) else {}


def _followup_type(followup: dict[str, Any]) -> str:
    content = _followup_content_dict(followup)
    return str(followup.get("type") or content.get("type") or "").strip()


def _runtime_shadow_case_id(case: dict[str, Any], step: dict[str, Any], step_count: int) -> str:
    for source in (step,):
        for key in ("profileCaseId", "shadowCaseId", "runtimeShadowCaseId", "caseId", "goldenCaseId"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    if step_count == 1:
        for key in ("profileCaseId", "shadowCaseId", "runtimeShadowCaseId", "caseId", "goldenCaseId"):
            value = str(case.get(key) or "").strip()
            if value:
                return value
    return ""


def _infer_pending_kind_from_card(content: dict[str, Any]) -> str:
    kind = str(content.get("kind") or "").strip()
    if kind in {"intent_change", "plan_mutation"}:
        return kind
    action_family = str(content.get("actionFamily") or "").strip()
    if action_family == "apply_selected_intents":
        return "intent_change"
    if action_family:
        return "plan_mutation"
    return kind or "unknown_pending"


def _execution_kind_for_pending(pending_kind: str) -> str:
    if pending_kind == "plan_mutation":
        return "pending_plan_mutation"
    if pending_kind == "intent_change":
        return "pending_intent_change"
    return ""


def _pending_cards_from_followups(followups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for followup in followups:
        if _followup_type(followup) != "pendingConfirmationCard":
            continue
        content = _followup_content_dict(followup)
        kind = _infer_pending_kind_from_card(content)
        card: dict[str, Any] = {"kind": kind}
        for source_key, target_key in (
            ("pendingId", "pendingId"),
            ("actionFamily", "actionFamily"),
            ("targetView", "targetView"),
        ):
            value = str(content.get(source_key) or "").strip()
            if value:
                card[target_key] = value
        execution_kind = _execution_kind_for_pending(kind)
        if execution_kind:
            card["executionPayload"] = {"kind": execution_kind}
        cards.append(card)
    return cards


def _workspace_refresh_targets_from_followups(followups: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for followup in followups:
        if _followup_type(followup) != "planningWorkspaceAction":
            continue
        content = _followup_content_dict(followup)
        if content.get("refresh") is False:
            continue
        _add_unique(targets, content.get("targetView"))
    return targets


def _turn_applied_existing_pending(turn_observability: dict[str, Any]) -> bool:
    routing_path = str(turn_observability.get("routingPath") or "").strip()
    if routing_path in PENDING_APPLY_ROUTING_PATHS:
        return True
    for item in turn_observability.get("toolCalls") or []:
        if not isinstance(item, dict) or item.get("applied") is not True:
            continue
        action_family = str(item.get("actionFamily") or "").strip()
        result_kind = str(item.get("resultKind") or "").strip()
        message_code = str(item.get("messageCode") or "").strip()
        if action_family in READONLY_APPLIED_ACTION_FAMILIES or result_kind in READONLY_APPLIED_RESULT_KINDS:
            continue
        if action_family in PENDING_APPLY_ACTION_FAMILIES or message_code in PENDING_APPLY_MESSAGE_CODES:
            return True
    return False


def _turn_has_post_apply_evidence_plan(turn_observability: dict[str, Any]) -> bool:
    if isinstance(turn_observability.get("postApplyEvidencePlan"), dict):
        return True
    route_decision = turn_observability.get("routeDecision")
    return isinstance(route_decision, dict) and isinstance(route_decision.get("postApplyEvidencePlan"), dict)


def _turn_route_decision_route(turn_observability: dict[str, Any]) -> str:
    route_decision = turn_observability.get("routeDecision")
    if not isinstance(route_decision, dict):
        return ""
    return str(route_decision.get("route") or route_decision.get("sideEffect") or "").strip()


def _runtime_reply_focus(turn_observability: dict[str, Any]) -> list[str]:
    focus_values: list[str] = []
    for value in _as_string_list(turn_observability.get("replyFocus")):
        _add_unique(focus_values, value)
    route_decision = turn_observability.get("routeDecision")
    if isinstance(route_decision, dict) and route_decision.get("unsupportedAction"):
        _add_unique(focus_values, str(route_decision.get("unsupportedAction") or ""))
    for item in turn_observability.get("toolCalls") or []:
        if not isinstance(item, dict):
            continue
        for value in _as_string_list(item.get("replyFocus")):
            _add_unique(focus_values, value)
    return focus_values


def _runtime_route_presentation(turn_observability: dict[str, Any]) -> str:
    route_decision = turn_observability.get("routeDecision")
    if not isinstance(route_decision, dict):
        return ""
    display_payload = route_decision.get("displayPayload")
    if isinstance(display_payload, dict):
        value = str(display_payload.get("presentation") or "").strip()
        if value:
            return value
    return str(route_decision.get("displayPresentation") or route_decision.get("presentation") or "").strip()


def _runtime_observation_profile(case: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    for source in (step, case):
        value = source.get("runtimeObservationProfile")
        if isinstance(value, dict):
            return dict(value)
        text = str(value or "").strip()
        if text:
            return {"type": text}
    return {}


def _runtime_latency_profile_payload(record: dict[str, Any], turn_observability: dict[str, Any]) -> dict[str, Any]:
    route_decision = turn_observability.get("routeDecision")
    if not isinstance(route_decision, dict):
        route_decision = {}
    event_timings = turn_observability.get("eventTimings")
    if not isinstance(event_timings, dict):
        event_timings = {}
    agent_run = route_decision.get("agentRun")
    if not isinstance(agent_run, dict):
        agent_run = {}
    node_timings = [
        item
        for item in (agent_run.get("nodeTimings") or [])
        if isinstance(item, dict)
    ]
    model_node_count = sum(
        1
        for item in node_timings
        if "model" in str(item.get("node") or "").lower()
    )
    tool_node_count = sum(
        1
        for item in node_timings
        if "tool" in str(item.get("node") or "").lower()
    )
    return {
        "profileType": "latency_profile",
        "decompose": ["model_planning", "tool_calls", "final_reply_generation"],
        "elapsedMs": record.get("elapsedMs"),
        "firstMessageMs": record.get("firstMessageMs"),
        "finalMessageMs": record.get("finalMessageMs"),
        "toolCallCount": turn_observability.get("toolCallCount") or event_timings.get("toolCallCount"),
        "toolReturnCount": turn_observability.get("toolReturnCount"),
        "toolDurationMs": route_decision.get("toolDurationMs") or event_timings.get("toolDurationMs"),
        "llmDurationMs": route_decision.get("llmDurationMs") or event_timings.get("llmDurationMs"),
        "classificationDurationMs": route_decision.get("classificationDurationMs") or event_timings.get("classificationDurationMs"),
        "preSemanticRouteDurationMs": route_decision.get("preSemanticRouteDurationMs") or event_timings.get("preSemanticRouteDurationMs"),
        "preFullAgentDurationMs": route_decision.get("preFullAgentDurationMs") or event_timings.get("preFullAgentDurationMs"),
        "historyLoadDurationMs": route_decision.get("historyLoadDurationMs") or event_timings.get("historyLoadDurationMs"),
        "pendingLoadDurationMs": route_decision.get("pendingLoadDurationMs") or event_timings.get("pendingLoadDurationMs"),
        "initialStateLoadDurationMs": route_decision.get("initialStateLoadDurationMs") or event_timings.get("initialStateLoadDurationMs"),
        "runtimeHistoryBuildDurationMs": route_decision.get("runtimeHistoryBuildDurationMs") or event_timings.get("runtimeHistoryBuildDurationMs"),
        "backendContextLoadDurationMs": route_decision.get("backendContextLoadDurationMs") or event_timings.get("backendContextLoadDurationMs"),
        "requestContextBuildDurationMs": route_decision.get("requestContextBuildDurationMs") or event_timings.get("requestContextBuildDurationMs"),
        "guardPipelineDurationMs": route_decision.get("guardPipelineDurationMs") or event_timings.get("guardPipelineDurationMs"),
        "turnDecisionDurationMs": route_decision.get("turnDecisionDurationMs") or event_timings.get("turnDecisionDurationMs"),
        "turnDecisionCacheHitCount": route_decision.get("turnDecisionCacheHitCount") or event_timings.get("turnDecisionCacheHitCount"),
        "intentEntityProfileDurationMs": route_decision.get("intentEntityProfileDurationMs") or event_timings.get("intentEntityProfileDurationMs"),
        "intentSideEffectDurationMs": route_decision.get("intentSideEffectDurationMs") or event_timings.get("intentSideEffectDurationMs"),
        "postFullAgentDurationMs": route_decision.get("postFullAgentDurationMs") or event_timings.get("postFullAgentDurationMs"),
        "unattributedDurationMs": route_decision.get("unattributedDurationMs") or event_timings.get("unattributedDurationMs"),
        "routeTotalDurationMs": route_decision.get("totalDurationMs") or event_timings.get("totalDurationMs"),
        "modelNodeCount": model_node_count or None,
        "toolNodeCount": tool_node_count or None,
        "agentRun": agent_run if agent_run else None,
    }


def _runtime_side_effect_and_output(
    *,
    pending_cards: list[dict[str, Any]],
    workspace_targets: list[str],
    turn_observability: dict[str, Any],
    planning_profile: dict[str, Any],
    record: dict[str, Any],
) -> tuple[str, str, str, str]:
    if record.get("error") or record.get("wsError"):
        return "error", "error", "none", ""
    route = _turn_route_decision_route(turn_observability)
    route_decision = turn_observability.get("routeDecision")
    if isinstance(route_decision, dict):
        route_side_effect = str(route_decision.get("sideEffect") or "").strip()
        route_action_family = str(route_decision.get("actionFamily") or "").strip()
        if (
            route == "local_plan_action_unsupported"
            or route_side_effect == "plan_preview_or_clarification"
        ):
            return (
                route_side_effect or "plan_preview_or_clarification",
                "plan_mutation_or_unsupported",
                "none",
                "conditional_plan_mutation",
            )
        if route_action_family == "pin_or_lock_unit" and route_decision.get("unsupportedAction"):
            return (
                "plan_preview_or_clarification",
                "plan_mutation_or_unsupported",
                "none",
                "conditional_plan_mutation",
            )
        if route_side_effect == "readonly_or_plan_preview":
            return (
                "readonly_or_plan_preview",
                str(route_decision.get("outputType") or "readonly_or_plan_mutation").strip()
                or "readonly_or_plan_mutation",
                "none",
                "conditional_plan_mutation",
            )
    if route == "apply_pending_then_new_request":
        pending_type = "none"
        if len(pending_cards) == 1:
            pending_type = str(pending_cards[0].get("kind") or "unknown_pending").strip()
        elif len(pending_cards) > 1:
            pending_type = "multiple"
        return (
            "apply_pending_then_new_request",
            "composite",
            pending_type,
            "apply_existing_pending_then_followup",
        )
    if route == "needs_plan_first":
        return "needs_plan_first", "readonly", "none", ""
    if len(pending_cards) > 1:
        return "multiple_pending", "multiple_pending", "multiple", ""
    if len(pending_cards) == 1:
        pending_type = str(pending_cards[0].get("kind") or "unknown_pending").strip()
        execution_kind = _execution_kind_for_pending(pending_type)
        if pending_type == "intent_change":
            return "intent_pending", "intent_change", pending_type, execution_kind
        if pending_type == "plan_mutation":
            return "plan_preview", "plan_mutation", pending_type, execution_kind
        return "unknown_pending", "unknown_pending", pending_type, execution_kind
    if _turn_applied_existing_pending(turn_observability):
        if route == "apply_pending_then_readonly" or _turn_has_post_apply_evidence_plan(turn_observability):
            return (
                "apply_pending_then_readonly",
                "apply_then_readonly",
                "none",
                "apply_existing_pending_then_readonly",
            )
        return "apply_existing_pending", "apply_then_readonly", "none", "apply_existing_pending_then_readonly"
    if bool(planning_profile.get("pendingExists")):
        return "readonly_while_pending", "readonly", "unchanged_existing_pending", ""
    return "readonly", "readonly", "none", ""


def _build_runtime_shadow_observation(
    case: dict[str, Any],
    step: dict[str, Any],
    record: dict[str, Any],
    followups: list[dict[str, Any]],
    step_count: int,
) -> dict[str, Any] | None:
    case_id = _runtime_shadow_case_id(case, step, step_count)
    if not case_id:
        return None
    turn_observability = record.get("turnObservability")
    if not isinstance(turn_observability, dict):
        turn_observability = {}
    planning_profile = case.get("planningStateProfile")
    if not isinstance(planning_profile, dict):
        planning_profile = {}
    pending_cards = _pending_cards_from_followups(followups)
    workspace_targets = _workspace_refresh_targets_from_followups(followups)
    side_effect, output_type, pending_type, execution_kind = _runtime_side_effect_and_output(
        pending_cards=pending_cards,
        workspace_targets=workspace_targets,
        turn_observability=turn_observability,
        planning_profile=planning_profile,
        record=record,
    )
    if pending_type == "multiple":
        presentation = "multiple_cards"
    elif pending_type in {"intent_change", "plan_mutation"}:
        presentation = "confirmation_card"
    elif output_type == "error":
        presentation = "error"
    elif output_type == "plan_mutation_or_unsupported":
        presentation = "conditional_options"
    else:
        presentation = "readonly_answer"
    route_presentation = _runtime_route_presentation(turn_observability)
    if route_presentation:
        presentation = route_presentation

    runtime: dict[str, Any] = {
        "sideEffect": side_effect,
        "outputType": output_type,
        "pendingType": pending_type,
        "displayPayload": {"presentation": presentation},
        "replyFocus": _runtime_reply_focus(turn_observability),
        "workspaceRefreshTargets": workspace_targets,
    }
    observation_profile = _runtime_observation_profile(case, step)
    if (
        str(observation_profile.get("type") or "").strip() == "latency_profile"
        and not record.get("error")
        and not record.get("wsError")
    ):
        latency_profile = _runtime_latency_profile_payload(record, turn_observability)
        runtime["outputType"] = "latency_profile"
        runtime["displayPayload"] = {"presentation": "diagnostic"}
        runtime["diagnosticPayload"] = latency_profile
        runtime["evidenceContract"] = {
            "requiredInputs": ["agent_observability"],
            "steps": ["decompose_model_planning", "decompose_tool_calls", "decompose_final_reply"],
            "toolBudget": observation_profile.get("toolBudget") if isinstance(observation_profile.get("toolBudget"), dict) else {},
        }
        for value in _as_string_list(observation_profile.get("replyFocus") or observation_profile.get("targetIssue")):
            _add_unique(runtime["replyFocus"], value)
    if execution_kind:
        runtime["executionPayload"] = {"kind": execution_kind}
    if pending_cards:
        runtime["pendingCards"] = pending_cards
    if turn_observability:
        runtime["turnObservability"] = {
            key: turn_observability[key]
            for key in (
                "routingPath",
                "routingPathCandidates",
                "toolCallCount",
                "toolReturnCount",
                "actionFamilies",
                "resultKinds",
                "replyFocus",
                "postApplyEvidencePlan",
                "routeDecision",
                "eventTimings",
            )
            if key in turn_observability
        }
    post_apply_evidence_plan = turn_observability.get("postApplyEvidencePlan")
    if not isinstance(post_apply_evidence_plan, dict):
        route_decision = turn_observability.get("routeDecision")
        if isinstance(route_decision, dict):
            post_apply_evidence_plan = route_decision.get("postApplyEvidencePlan")
    if isinstance(post_apply_evidence_plan, dict):
        runtime["postApplyEvidencePlan"] = post_apply_evidence_plan
        runtime.setdefault("turnObservability", {})["postApplyEvidencePlan"] = post_apply_evidence_plan
    if record.get("error"):
        runtime["error"] = record.get("error")
    if record.get("wsError"):
        runtime["wsError"] = record.get("wsError")
    return {
        "caseId": case_id,
        "actualSource": "dialog_regression_runner",
        "case": record.get("case"),
        "stepIndex": record.get("stepIndex"),
        "sessionId": record.get("sessionId"),
        "prompt": record.get("prompt"),
        "elapsedMs": record.get("elapsedMs"),
        "runtime": runtime,
    }


def _build_runtime_shadow_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_side_effect: dict[str, int] = {}
    by_pending_type: dict[str, int] = {}
    for observation in observations:
        runtime = observation.get("runtime") if isinstance(observation, dict) else {}
        if not isinstance(runtime, dict):
            continue
        _bump(by_side_effect, runtime.get("sideEffect"))
        _bump(by_pending_type, runtime.get("pendingType"))
    return {
        "observations": len(observations),
        "bySideEffect": by_side_effect,
        "byPendingType": by_pending_type,
    }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _summarize_primary(messages: list[dict[str, Any]]) -> str:
    text_parts = [m.get("content", "") for m in messages if m.get("type") == "text"]
    thinking_parts = [m.get("content", "") for m in messages if m.get("type") == "thinking"]
    summary = []
    if thinking_parts:
        summary.append("thinking=" + " | ".join(str(x) for x in thinking_parts))
    if text_parts:
        summary.append("text=" + " | ".join(str(x) for x in text_parts))
    return "\n".join(summary) if summary else json.dumps(messages, ensure_ascii=False)


def _extract_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("type") == "text").strip()


def _extract_error_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("type") == "error").strip()


def _extract_thinking(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("type") == "thinking").strip()


def _extract_followup_user_text(followups: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in followups:
        if _is_silent_workspace_action_message(item):
            continue
        content = item.get("content")
        if isinstance(content, dict):
            for field in FOLLOWUP_USER_TEXT_FIELDS:
                value = content.get(field)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        elif isinstance(content, str) and content.strip():
            parts.append(content.strip())
    return "\n".join(parts).strip()


def _check_plan_reply_style(text: str) -> list[str]:
    violations: list[str] = []
    for value in PLAN_STYLE_BANNED_SUBSTRINGS:
        if value in text:
            violations.append(f"contains banned substring: {value}")
    for line in text.splitlines():
        if line.strip() in PLAN_STYLE_BANNED_EXACT_LINES:
            violations.append(f"contains dangling line: {line.strip()}")
            break
    return violations


def _check_content_assertions(
    text: str,
    followups: list[dict[str, Any]],
    step: dict[str, Any],
    case_name: str,
    session_id: str,
    thinking_text: str = "",
) -> list[str]:
    """Check per-prompt content assertions from the case step definition."""
    violations: list[str] = []
    prompt_label = step.get("prompt") or step.get("text") or ""
    assert_contains = step.get("assertContains") or []
    assert_contains_any = step.get("assertContainsAny") or []
    assert_not_contains = step.get("assertNotContains") or []
    assert_thinking_contains = step.get("assertThinkingContains") or []
    assert_thinking_contains_any = step.get("assertThinkingContainsAny") or []
    assert_thinking_not_contains = step.get("assertThinkingNotContains") or []
    assert_followup_target = step.get("assertFollowupTarget")
    assert_followup_refresh = step.get("assertFollowupRefresh")
    assert_followup_type = step.get("assertFollowupType")
    assert_followup_count = step.get("assertFollowupCount")
    assert_actionable_followup_types = _as_string_list(step.get("assertActionableFollowupTypes"))
    assert_actionable_followup_targets = _as_string_list(step.get("assertActionableFollowupTargets"))
    assert_actionable_followup_count = step.get("assertActionableFollowupCount")
    assert_no_followups = bool(step.get("assertNoFollowups"))
    visible_followups = [
        item
        for item in followups
        if str(item.get("type") or "").strip() != "thinking"
        and not _is_silent_workspace_action_message(item)
    ]
    actionable_followups = followups
    actionable_followup_targets, _, actionable_followup_types = _followup_summary(actionable_followups)

    followup_user_text = _extract_followup_user_text(visible_followups)
    searchable_text = "\n".join(part for part in (text, followup_user_text) if part).strip()
    combined_text = searchable_text.lower()
    combined_thinking = thinking_text.lower()
    for expected in assert_contains:
        if expected.lower() not in combined_text:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertContains FAILED — expected '{expected}' not found in response"
            )
    for forbidden in assert_not_contains:
        if forbidden.lower() in combined_text:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertNotContains FAILED — forbidden '{forbidden}' found in response"
            )
    if assert_contains_any and not any(kw.lower() in combined_text for kw in assert_contains_any):
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertContainsAny FAILED — none of {assert_contains_any} found in response"
        )
    for expected in assert_thinking_contains:
        if expected.lower() not in combined_thinking:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertThinkingContains FAILED — expected '{expected}' not found in thinking messages"
            )
    for forbidden in assert_thinking_not_contains:
        if forbidden.lower() in combined_thinking:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertThinkingNotContains FAILED — forbidden '{forbidden}' found in thinking messages"
            )
    if assert_thinking_contains_any and not any(kw.lower() in combined_thinking for kw in assert_thinking_contains_any):
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertThinkingContainsAny FAILED — none of {assert_thinking_contains_any} found in thinking messages"
        )
    if assert_followup_target:
        found_target = any(
            _followup_content_dict(f).get("targetView") == assert_followup_target
            for f in actionable_followups
        )
        if not found_target:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupTarget FAILED — expected targetView='{assert_followup_target}' not in followups"
            )
    if assert_followup_refresh is not None:
        found_refresh = any(
            _followup_content_dict(f).get("refresh") == assert_followup_refresh
            for f in actionable_followups
        )
        if not found_refresh:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupRefresh FAILED — expected refresh={assert_followup_refresh} not in followups"
            )
    if assert_followup_type:
        _, _, followup_types = _followup_summary(visible_followups)
        if str(assert_followup_type) not in followup_types:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupType FAILED — expected type='{assert_followup_type}' not in followups"
            )
    if assert_followup_count is not None:
        try:
            expected_count = int(assert_followup_count)
        except (TypeError, ValueError):
            expected_count = None
        if expected_count is not None and len(visible_followups) != expected_count:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupCount FAILED — expected {expected_count} followups but got {len(visible_followups)}"
            )
    for expected_type in assert_actionable_followup_types:
        if expected_type not in actionable_followup_types:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertActionableFollowupTypes FAILED — expected type='{expected_type}' not in actionable followups"
            )
    for expected_target in assert_actionable_followup_targets:
        if expected_target not in actionable_followup_targets:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertActionableFollowupTargets FAILED — expected targetView='{expected_target}' not in actionable followups"
            )
    if assert_actionable_followup_count is not None:
        try:
            expected_actionable_count = int(assert_actionable_followup_count)
        except (TypeError, ValueError):
            expected_actionable_count = None
        if expected_actionable_count is not None and len(actionable_followups) != expected_actionable_count:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertActionableFollowupCount FAILED — expected {expected_actionable_count} actionable followups but got {len(actionable_followups)}"
            )
    if assert_no_followups and visible_followups:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertNoFollowups FAILED — expected no followups but got {len(visible_followups)}"
        )
    return violations


def _tool_names_from_observability(turn_observability: dict[str, Any] | None) -> list[str]:
    if not isinstance(turn_observability, dict):
        return []
    names: list[str] = []
    for item in turn_observability.get("toolCalls") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _check_tool_assertions(
    turn_observability: dict[str, Any] | None,
    step: dict[str, Any],
    case_name: str,
    session_id: str,
) -> list[str]:
    """Check tool-chain assertions from the case step definition."""
    violations: list[str] = []
    prompt_label = step.get("prompt") or step.get("text") or ""
    turn_observability = turn_observability if isinstance(turn_observability, dict) else {}
    tool_names = _tool_names_from_observability(turn_observability)

    expected_routing_path = str(step.get("expectedRoutingPath") or "").strip()
    if expected_routing_path:
        actual_routing_path = str(turn_observability.get("routingPath") or "").strip()
        if actual_routing_path != expected_routing_path:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"expectedRoutingPath FAILED — expected {expected_routing_path} got {actual_routing_path}"
            )
    expected_routing_paths = [str(item).strip() for item in step.get("expectedRoutingPathAny") or [] if str(item).strip()]
    if expected_routing_paths:
        actual_routing_path = str(turn_observability.get("routingPath") or "").strip()
        if actual_routing_path not in expected_routing_paths:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"expectedRoutingPathAny FAILED — expected one of {expected_routing_paths} got {actual_routing_path}"
            )

    required_action_families = [str(item) for item in step.get("assertActionFamiliesContain") or []]
    action_families = [str(item) for item in turn_observability.get("actionFamilies") or []]
    missing_action_families = [name for name in required_action_families if name not in action_families]
    if missing_action_families:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertActionFamiliesContain FAILED — missing {missing_action_families} from {action_families}"
        )

    required_result_kinds = [str(item) for item in step.get("assertResultKindsContain") or []]
    result_kinds = [str(item) for item in turn_observability.get("resultKinds") or []]
    missing_result_kinds = [name for name in required_result_kinds if name not in result_kinds]
    if missing_result_kinds:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertResultKindsContain FAILED — missing {missing_result_kinds} from {result_kinds}"
        )
    accepted_result_kinds = [
        str(item).strip()
        for item in step.get("assertResultKindsContainAny") or []
        if str(item).strip()
    ]
    if accepted_result_kinds and not any(name in result_kinds for name in accepted_result_kinds):
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertResultKindsContainAny FAILED — expected one of {accepted_result_kinds} in {result_kinds}"
        )

    expected_tool_names = [str(item) for item in step.get("expectedToolNames") or []]
    if expected_tool_names and tool_names != expected_tool_names:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"expectedToolNames FAILED — expected {expected_tool_names} got {tool_names}"
        )

    required_tool_names = [str(item) for item in step.get("assertToolNamesContain") or []]
    missing_required = [name for name in required_tool_names if name not in tool_names]
    if missing_required:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertToolNamesContain FAILED — missing {missing_required} from {tool_names}"
        )

    forbidden_tool_names = [str(item) for item in step.get("assertToolNamesNotContain") or []]
    forbidden_found = [name for name in forbidden_tool_names if name in tool_names]
    if forbidden_found:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertToolNamesNotContain FAILED — forbidden {forbidden_found} found in {tool_names}"
        )

    max_tool_call_count = step.get("maxToolCallCount")
    if max_tool_call_count is not None:
        try:
            max_count = int(max_tool_call_count)
        except (TypeError, ValueError):
            max_count = None
        if max_count is not None and len(tool_names) > max_count:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"maxToolCallCount FAILED — toolCallCount={len(tool_names)} > {max_count}"
            )

    expected_tool_counts = step.get("expectedToolCounts") or {}
    if isinstance(expected_tool_counts, dict):
        actual_counts = {name: tool_names.count(name) for name in set(tool_names)}
        for name, expected_count in expected_tool_counts.items():
            try:
                expected = int(expected_count)
            except (TypeError, ValueError):
                continue
            actual = actual_counts.get(str(name), 0)
            if actual != expected:
                violations.append(
                    f"{case_name} session={session_id} prompt={prompt_label}: "
                    f"expectedToolCounts FAILED — expected {name}={expected} got {actual}"
                )

    if step.get("assertNoRepeatedToolNames"):
        repeated = sorted({name for name in tool_names if tool_names.count(name) > 1})
        if repeated:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertNoRepeatedToolNames FAILED — repeated {repeated} in {tool_names}"
            )

    return violations


def _as_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _milliseconds_from_step(step: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _as_optional_float(step.get(key))
        if value is None:
            continue
        if key.lower().endswith("seconds"):
            return int(value * 1000)
        return int(value)
    return None


def _check_performance_assertions(
    elapsed_ms: int,
    step: dict[str, Any],
    case_name: str,
    session_id: str,
) -> tuple[list[str], list[str]]:
    """Return hard failures and soft warnings for per-step latency budgets."""
    failures: list[str] = []
    warnings: list[str] = []
    prompt_label = step.get("prompt") or step.get("text") or ""
    max_elapsed_ms = _milliseconds_from_step(step, "maxElapsedMs", "maxElapsedSeconds")
    warn_elapsed_ms = _milliseconds_from_step(step, "warnElapsedMs", "warnElapsedSeconds")

    if max_elapsed_ms is not None and elapsed_ms > max_elapsed_ms:
        failures.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"maxElapsed FAILED — elapsedMs={elapsed_ms} > maxElapsedMs={max_elapsed_ms}"
        )
    if warn_elapsed_ms is not None and elapsed_ms > warn_elapsed_ms:
        warnings.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"latency warning — elapsedMs={elapsed_ms} > warnElapsedMs={warn_elapsed_ms}"
        )
    return failures, warnings


def _duration_summary(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"count": 0, "minMs": None, "medianMs": None, "p95Ms": None, "maxMs": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "count": len(values),
        "minMs": min(values),
        "medianMs": int(statistics.median(values)),
        "p95Ms": ordered[p95_index],
        "maxMs": max(values),
    }


def _record_failure_reasons(record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if str(record.get("failureReason") or "").strip() == "environment":
        reasons.append("environment")
        return reasons
    if record.get("error"):
        reasons.append("request")
    if record.get("wsError"):
        reasons.append("ws")
    if record.get("styleViolations"):
        reasons.append("style")
    if record.get("contentViolations"):
        reasons.append("content")
    if record.get("toolViolations"):
        reasons.append("tool")
    if record.get("performanceViolations"):
        reasons.append("performance")
    return reasons


def _fixture_type_from_contract(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("type") or "").strip()
    return ""


def _add_fixture_and_root_cause_fields(
    record: dict[str, Any],
    case: dict[str, Any],
    step: dict[str, Any] | None = None,
) -> None:
    fixture_contract = case.get("fixtureContract")
    fixture_type = _fixture_type_from_contract(fixture_contract)
    if fixture_type:
        record["fixtureType"] = fixture_type
        if isinstance(fixture_contract, dict):
            record["fixtureContract"] = fixture_contract
    root_cause = ""
    if step:
        root_cause = str(step.get("expectedRootCause") or "").strip()
    root_cause = root_cause or str(case.get("expectedRootCause") or case.get("rootCause") or "").strip()
    if root_cause:
        record["expectedRootCause"] = root_cause


def _build_metrics_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    failed_records = [
        record
        for record in records
        if _record_failure_reasons(record)
    ]
    failed_by_reason: dict[str, int] = {}
    for record in failed_records:
        for reason in _record_failure_reasons(record):
            failed_by_reason[reason] = failed_by_reason.get(reason, 0) + 1
    by_fixture: dict[str, int] = {}
    by_expected_root_cause: dict[str, int] = {}
    failed_by_expected_root_cause: dict[str, int] = {}
    for record in records:
        fixture_type = str(record.get("fixtureType") or "").strip()
        if fixture_type:
            by_fixture[fixture_type] = by_fixture.get(fixture_type, 0) + 1
        root_cause = str(record.get("expectedRootCause") or "").strip()
        if root_cause:
            by_expected_root_cause[root_cause] = by_expected_root_cause.get(root_cause, 0) + 1
            if _record_failure_reasons(record):
                failed_by_expected_root_cause[root_cause] = failed_by_expected_root_cause.get(root_cause, 0) + 1
    elapsed_values = [
        int(record["elapsedMs"])
        for record in records
        if isinstance(record.get("elapsedMs"), int) and not _record_failure_reasons(record)
    ]
    slowest = sorted(
        (
            record
            for record in records
            if isinstance(record.get("elapsedMs"), int)
        ),
        key=lambda item: int(item["elapsedMs"]),
        reverse=True,
    )[:5]
    return {
        "steps": len(records),
        "successfulSteps": len(elapsed_values),
        "failedSteps": len(failed_records),
        "failedByReason": failed_by_reason,
        "byFixture": by_fixture,
        "byExpectedRootCause": by_expected_root_cause,
        "failedByExpectedRootCause": failed_by_expected_root_cause,
        "elapsed": _duration_summary(elapsed_values),
        "slowest": [
            {
                "case": record.get("case"),
                "sessionId": record.get("sessionId"),
                "prompt": record.get("prompt"),
                "elapsedMs": record.get("elapsedMs"),
            }
            for record in slowest
        ],
        "fastRouteArbitration": _build_fast_route_arbitration_summary(records),
    }


def _bump(counter: dict[str, int], key: Any) -> None:
    text = str(key or "").strip()
    if not text:
        return
    counter[text] = counter.get(text, 0) + 1


def _build_fast_route_arbitration_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    observed = 0
    needed = 0
    selected_paths: dict[str, int] = {}
    needed_reasons: dict[str, int] = {}
    candidate_paths: dict[str, int] = {}
    needed_examples: list[dict[str, Any]] = []

    for record in records:
        turn = record.get("turnObservability")
        if not isinstance(turn, dict):
            continue
        arbitration = turn.get("fastRouteArbitration")
        if not isinstance(arbitration, dict):
            continue
        observed += 1
        _bump(selected_paths, arbitration.get("selectedPath"))
        for path in arbitration.get("semanticArbitrationCandidatePaths") or []:
            _bump(candidate_paths, path)
        if arbitration.get("semanticArbitrationNeeded") is True:
            needed += 1
            _bump(needed_reasons, arbitration.get("semanticArbitrationReason"))
            if len(needed_examples) < 10:
                needed_examples.append(
                    {
                        "case": record.get("case"),
                        "sessionId": record.get("sessionId"),
                        "prompt": record.get("prompt"),
                        "selectedPath": arbitration.get("selectedPath"),
                        "reason": arbitration.get("semanticArbitrationReason"),
                        "candidatePaths": arbitration.get("semanticArbitrationCandidatePaths") or [],
                    }
                )

    return {
        "observed": observed,
        "semanticArbitrationNeeded": needed,
        "semanticArbitrationNotNeeded": observed - needed,
        "selectedPaths": selected_paths,
        "neededReasons": needed_reasons,
        "candidatePaths": candidate_paths,
        "neededExamples": needed_examples,
    }


async def _run_cases(
    url: str,
    user_id: str,
    cases: list[dict[str, Any]],
    *,
    assert_plan_style: bool = False,
    open_timeout: float = 30,
    response_timeout: float = 120,
    metrics_output: str | None = None,
    history_db: str | None = str(DEFAULT_HISTORY_DB),
    keep_response_text: bool = False,
    clear_history_per_case: bool = False,
    clear_backend_pending_per_case: bool = False,
    clear_backend_planning_intent_per_case: bool = False,
    internal_service_url: str = DEFAULT_INTERNAL_SERVICE_URL,
    clone_backend_chat_session: bool = False,
    backend_db_host: str = DEFAULT_BACKEND_DB_HOST,
    backend_db_port: str = DEFAULT_BACKEND_DB_PORT,
    backend_db_user: str = DEFAULT_BACKEND_DB_USER,
    backend_db_password: str = DEFAULT_BACKEND_DB_PASSWORD,
    backend_db_name: str = DEFAULT_BACKEND_DB_NAME,
    backend_volunteer_data_dir: str = DEFAULT_BACKEND_VOLUNTEER_DATA_DIR,
    runtime_shadow_output: str | None = None,
) -> None:
    failures: list[str] = []
    warnings: list[str] = []
    metrics_records: list[dict[str, Any]] = []
    runtime_shadow_observations: list[dict[str, Any]] = []
    for case in cases:
        name = str(case.get("name") or f"session-{case.get('sessionId')}")
        session_id = str(case["sessionId"])
        case_env_failures: list[str] = []
        clone_source_session_id = str(case.get("cloneBackendStateFromSessionId") or "").strip()
        clone_results: list[dict[str, Any]] = []
        if clone_source_session_id:
            if clone_backend_chat_session:
                session_clone_result = _clone_backend_chat_session_row(
                    source_session_id=clone_source_session_id,
                    target_session_id=session_id,
                    db_host=backend_db_host,
                    db_port=backend_db_port,
                    db_user=backend_db_user,
                    db_password=backend_db_password,
                    db_name=backend_db_name,
                )
                print(
                    "clonedCaseBackendChatSession="
                    + json.dumps(
                        {
                            "dbHost": backend_db_host,
                            "dbName": backend_db_name,
                            "sourceSession": clone_source_session_id,
                            "targetSession": session_id,
                            "result": session_clone_result,
                        },
                        ensure_ascii=False,
                    )
                )
                if not session_clone_result.get("ok"):
                    warnings.append(
                        f"{name} session={session_id}: backend chat session clone failed: "
                        + json.dumps(session_clone_result, ensure_ascii=False)
                    )
                volunteer_file_clone_result = _clone_backend_volunteer_data_files(
                    source_session_id=clone_source_session_id,
                    target_session_id=session_id,
                    data_dir=backend_volunteer_data_dir,
                )
                print(
                    "clonedCaseBackendVolunteerData="
                    + json.dumps(
                        {
                            "dataDir": backend_volunteer_data_dir,
                            "sourceSession": clone_source_session_id,
                            "targetSession": session_id,
                            "result": volunteer_file_clone_result,
                        },
                        ensure_ascii=False,
                    )
                )
                if not volunteer_file_clone_result.get("ok"):
                    warnings.append(
                        f"{name} session={session_id}: backend volunteer data clone failed: "
                        + json.dumps(volunteer_file_clone_result, ensure_ascii=False)
                    )
            clone_results = _clone_backend_session_state(
                internal_service_url,
                source_session_id=clone_source_session_id,
                target_session_id=session_id,
                keys=_backend_state_clone_keys_for_case(case),
            )
            print(
                "clonedCaseBackendState="
                + json.dumps(
                    {
                        "baseUrl": internal_service_url,
                        "sourceSession": clone_source_session_id,
                        "targetSession": session_id,
                        "results": clone_results,
                    },
                    ensure_ascii=False,
                )
            )
            failed_clones = [item for item in clone_results if not item.get("ok")]
            if failed_clones:
                case_env_failures.append(
                    "backend state clone had failures: "
                    + json.dumps(
                        {
                            "baseUrl": internal_service_url,
                            "sourceSession": clone_source_session_id,
                            "targetSession": session_id,
                            "failures": failed_clones,
                        },
                        ensure_ascii=False,
                    )
                )
        if clear_history_per_case and history_db:
            deleted = _clear_history(Path(history_db), [session_id])
            print(
                "clearedCaseHistory="
                + json.dumps(
                    {
                        "db": str(Path(history_db)),
                        "session": session_id,
                        "deletedRows": deleted,
                    },
                    ensure_ascii=False,
                )
            )
        preserve_cloned_active_pending = (
            clear_backend_pending_per_case
            and _case_requires_active_pending(case)
            and _clone_results_have_active_pending(clone_results)
        )
        if preserve_cloned_active_pending:
            print(
                "skippedCaseBackendPendingClear="
                + json.dumps(
                    {
                        "baseUrl": internal_service_url,
                        "session": session_id,
                        "reason": "cloned_source_active_pending",
                    },
                    ensure_ascii=False,
                )
            )
        elif clear_backend_pending_per_case:
            pending_results = _clear_backend_pending_state(internal_service_url, [session_id])
            print(
                "clearedCaseBackendPending="
                + json.dumps(
                    {
                        "baseUrl": internal_service_url,
                        "session": session_id,
                        "results": pending_results,
                    },
                    ensure_ascii=False,
                )
            )
            failed_pending_clears = [item for item in pending_results if not item.get("ok")]
            if failed_pending_clears:
                case_env_failures.append(
                    "backend pending clear had failures: "
                    + json.dumps(
                        {
                            "baseUrl": internal_service_url,
                            "session": session_id,
                            "failures": failed_pending_clears,
                        },
                        ensure_ascii=False,
                    )
                )
        should_clear_planning_intent = (
            clear_backend_planning_intent_per_case
            or bool(case.get("clearBackendPlanningIntentState"))
        )
        if should_clear_planning_intent:
            planning_intent_results = _clear_backend_planning_intent_state(internal_service_url, [session_id])
            print(
                "clearedCaseBackendPlanningIntent="
                + json.dumps(
                    {
                        "baseUrl": internal_service_url,
                        "session": session_id,
                        "results": planning_intent_results,
                    },
                    ensure_ascii=False,
                )
            )
            failed_planning_intent_clears = [item for item in planning_intent_results if not item.get("ok")]
            if failed_planning_intent_clears:
                case_env_failures.append(
                    "backend planning intent clear had failures: "
                    + json.dumps(
                        {
                            "baseUrl": internal_service_url,
                            "session": session_id,
                            "failures": failed_planning_intent_clears,
                        },
                        ensure_ascii=False,
                    )
                )
        case_assert_style = bool(case.get("assertPlanStyle", assert_plan_style))
        base_session_id = str(case.get("baseSessionId") or "")
        session_label = f"{session_id} base={base_session_id}" if base_session_id else session_id
        print(f"=== CASE {name} session={session_label} ===")

        raw_prompts = list(case.get("prompts") or [])
        steps: list[dict[str, Any]] = []
        for item in raw_prompts:
            if isinstance(item, str):
                steps.append({"prompt": item})
            elif isinstance(item, dict):
                steps.append(item)
            else:
                steps.append({"prompt": str(item)})
        step_count = len(steps)

        if case_env_failures:
            for env_failure in case_env_failures:
                failure = f"{name} session={session_id}: environment setup failed: {env_failure}"
                failures.append(failure)
                print(f"  ENV_SETUP_FAIL: {failure}")
            record = {
                "case": name,
                "stepIndex": 0,
                "sessionId": session_id,
                "prompt": "",
                "elapsedMs": 0,
                "error": "; ".join(case_env_failures),
                "failureReason": "environment",
                "environmentFailures": list(case_env_failures),
            }
            _add_fixture_and_root_cause_fields(record, case, {})
            metrics_records.append(record)
            print("metrics=" + json.dumps(record, ensure_ascii=False))
            print()
            continue

        for step_index, step in enumerate(steps, start=1):
            prompt = str(step.get("prompt") or step.get("text") or "")
            print(f">>> {prompt}")
            started_at = time.perf_counter()
            try:
                primary, followups, timing = await _ask_once(
                    url,
                    session_id,
                    user_id,
                    prompt,
                    open_timeout=open_timeout,
                    response_timeout=response_timeout,
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                failures.append(f"{name} session={session_id} prompt={prompt}: request failed: {type(exc).__name__}: {exc}")
                error_record = {
                    "case": name,
                    "stepIndex": step_index,
                    "sessionId": session_id,
                    "prompt": prompt,
                    "elapsedMs": elapsed_ms,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _add_fixture_and_root_cause_fields(error_record, case, step)
                if history_db:
                    history = _load_history_json(Path(history_db), session_id)
                    turn_observability = _summarize_turn_observability(
                        _latest_turn_messages(history, prompt)
                    )
                    if turn_observability.get("historyMessages"):
                        error_record["turnObservability"] = turn_observability
                shadow_observation = _build_runtime_shadow_observation(
                    case,
                    step,
                    error_record,
                    [],
                    step_count,
                )
                if shadow_observation:
                    error_record["runtimeShadowCaseId"] = shadow_observation["caseId"]
                    runtime_shadow_observations.append(shadow_observation)
                metrics_records.append(error_record)
                print(f"error={type(exc).__name__}: {exc} elapsedMs={elapsed_ms}")
                continue
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            record = {
                "case": name,
                "stepIndex": step_index,
                "sessionId": session_id,
                "prompt": prompt,
                "elapsedMs": elapsed_ms,
                "firstMessageMs": timing.get("firstMessageMs"),
                "finalMessageMs": timing.get("finalMessageMs"),
                "primaryMessages": len(primary),
                "thinkingMessages": sum(1 for message in primary if message.get("type") == "thinking"),
                "followupMessages": len(followups),
            }
            _add_fixture_and_root_cause_fields(record, case, step)
            if keep_response_text:
                record["responseText"] = _extract_text(primary)
                record["thinkingText"] = _extract_thinking(primary)
            error_text = _extract_error_text(primary)
            if error_text:
                record["wsError"] = error_text
            if history_db:
                history = _load_history_json(Path(history_db), session_id)
                turn_observability = _summarize_turn_observability(
                    _latest_turn_messages(history, prompt)
                )
                if turn_observability.get("historyMessages"):
                    record["turnObservability"] = turn_observability
            if followups:
                followup_targets, followup_refreshes, followup_types = _followup_summary(followups)
                record["followupCount"] = len(followups)
                record["followupTargets"] = followup_targets
                record["followupRefreshes"] = followup_refreshes
                record["followupTypes"] = followup_types
            text = _extract_text(primary)
            if case_assert_style:
                violations = _check_plan_reply_style(text)
                if violations:
                    record["styleViolations"] = violations
                    failures.append(f"{name} session={session_id} prompt={prompt}: {'; '.join(violations)}")
            content_violations = _check_content_assertions(
                text,
                followups,
                step,
                name,
                session_id,
                thinking_text=_extract_thinking(primary),
            )
            if content_violations:
                for v in content_violations:
                    print(f"  CONTENT_ASSERT_FAIL: {v}")
                failures.extend(content_violations)
            tool_violations = _check_tool_assertions(
                record.get("turnObservability"),
                step,
                name,
                session_id,
            )
            if tool_violations:
                for v in tool_violations:
                    print(f"  TOOL_ASSERT_FAIL: {v}")
                failures.extend(tool_violations)
            perf_failures, perf_warnings = _check_performance_assertions(elapsed_ms, step, name, session_id)
            for warning in perf_warnings:
                print(f"  LATENCY_WARN: {warning}")
            failures.extend(perf_failures)
            warnings.extend(perf_warnings)
            if content_violations:
                record["contentViolations"] = content_violations
            if tool_violations:
                record["toolViolations"] = tool_violations
            if perf_failures:
                record["performanceViolations"] = perf_failures
            if perf_warnings:
                record["performanceWarnings"] = perf_warnings
            shadow_observation = _build_runtime_shadow_observation(
                case,
                step,
                record,
                followups,
                step_count,
            )
            if shadow_observation:
                record["runtimeShadowCaseId"] = shadow_observation["caseId"]
                runtime_shadow_observations.append(shadow_observation)
            metrics_records.append(record)
            print(
                "metrics="
                + json.dumps(
                    record,
                    ensure_ascii=False,
                )
            )
            print(_summarize_primary(primary))
            if followups:
                print("followups=" + json.dumps(followups, ensure_ascii=False))
        print()
    summary = _build_metrics_summary(metrics_records)
    runtime_shadow_summary = _build_runtime_shadow_summary(runtime_shadow_observations)
    print("=== METRICS SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if runtime_shadow_observations:
        print("=== RUNTIME SHADOW SUMMARY ===")
        print(json.dumps(runtime_shadow_summary, ensure_ascii=False, indent=2))
    if warnings:
        print("=== WARNINGS ===")
        for warning in warnings:
            print(warning)
    if metrics_output:
        Path(metrics_output).write_text(
            json.dumps(
                {
                    "records": metrics_records,
                    "summary": summary,
                    "runtimeShadowSummary": runtime_shadow_summary,
                    "warnings": warnings,
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if runtime_shadow_output:
        Path(runtime_shadow_output).write_text(
            json.dumps(
                {
                    "observations": runtime_shadow_observations,
                    "summary": runtime_shadow_summary,
                    "source": "dialog_regression_runner",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if failures:
        print("=== FAILURES ===")
        for failure in failures:
            print(failure)
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real websocket dialog regression cases.")
    parser.add_argument("--url", default=DEFAULT_URL, help="compat websocket URL")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="user id used in requests")
    parser.add_argument("--cases", help="JSON file containing a case array")
    parser.add_argument("--case-name", action="append", help="run only the named case; can be passed multiple times")
    parser.add_argument("--session", help="run an ad hoc session id")
    parser.add_argument("--prompts", nargs="*", help="ad hoc prompts for --session")
    parser.add_argument("--assert-plan-style", action="store_true", help="fail when plan replies contain severe forced-choice or internal wording")
    parser.add_argument("--open-timeout", type=float, default=30, help="websocket opening handshake timeout in seconds")
    parser.add_argument("--response-timeout", type=float, default=120, help="timeout in seconds while waiting for each prompt response")
    parser.add_argument("--metrics-output", help="write per-step latency and assertion summary to JSON")
    parser.add_argument(
        "--runtime-shadow-output",
        help="write readonly runtime observations for runtime_shadow_diff.py; does not change dialog behavior",
    )
    parser.add_argument(
        "--session-offset",
        type=int,
        default=0,
        help="add this numeric offset to every case sessionId so fixed case files can run against clean sessions",
    )
    parser.add_argument(
        "--clear-history",
        action="store_true",
        help="delete local Agent SQLite chat history rows for the case session ids before running",
    )
    parser.add_argument(
        "--history-db",
        default=str(DEFAULT_HISTORY_DB),
        help="Agent SQLite history db used by --clear-history",
    )
    parser.add_argument(
        "--keep-response-text",
        action="store_true",
        help="store the full response text and thinking text in metrics-output for case-level evaluation",
    )
    parser.add_argument(
        "--clear-history-per-case",
        action="store_true",
        help="delete the local Agent SQLite history row for a case session before each case; useful when many cases reuse real session ids",
    )
    parser.add_argument(
        "--clear-backend-pending",
        action="store_true",
        help="clear backend pendingConfirmation and legacy planEditCache for all case sessions before running",
    )
    parser.add_argument(
        "--clear-backend-pending-per-case",
        action="store_true",
        help="clear backend pendingConfirmation and legacy planEditCache for a case session before each case",
    )
    parser.add_argument(
        "--clear-backend-planning-intent-per-case",
        action="store_true",
        help="clear accepted planning profile/constraint intent fields for each case while keeping plan/candidate data",
    )
    parser.add_argument(
        "--internal-service-url",
        default=DEFAULT_INTERNAL_SERVICE_URL,
        help="backend base URL used by --clear-backend-pending options",
    )
    parser.add_argument(
        "--clone-backend-chat-session",
        action="store_true",
        help="when a case clones backend extra-data, also clone assistant_chat_session row through MySQL",
    )
    parser.add_argument("--backend-db-host", default=DEFAULT_BACKEND_DB_HOST)
    parser.add_argument("--backend-db-port", default=DEFAULT_BACKEND_DB_PORT)
    parser.add_argument("--backend-db-user", default=DEFAULT_BACKEND_DB_USER)
    parser.add_argument("--backend-db-password", default=DEFAULT_BACKEND_DB_PASSWORD)
    parser.add_argument("--backend-db-name", default=DEFAULT_BACKEND_DB_NAME)
    parser.add_argument(
        "--backend-volunteer-data-dir",
        default=DEFAULT_BACKEND_VOLUNTEER_DATA_DIR,
        help="local zhiyuan-server data/tmp directory used with --clone-backend-chat-session",
    )
    args = parser.parse_args()

    if args.session:
        prompts = args.prompts or ["方案有了么"]
        cases = [{"name": "ad-hoc", "sessionId": args.session, "prompts": prompts}]
    else:
        cases = _load_cases(args.cases)
    cases = _filter_cases_by_name(cases, args.case_name)
    cases = _apply_session_offset(cases, args.session_offset)
    if args.clear_history:
        session_ids = _case_session_ids(cases)
        deleted = _clear_history(Path(args.history_db), session_ids)
        print(
            "clearedHistory="
            + json.dumps(
                {
                    "db": str(Path(args.history_db)),
                    "sessions": session_ids,
                    "deletedRows": deleted,
                },
                ensure_ascii=False,
            )
        )
    if args.clear_backend_pending:
        session_ids = _case_session_ids(cases)
        pending_results = _clear_backend_pending_state(args.internal_service_url, session_ids)
        print(
            "clearedBackendPending="
            + json.dumps(
                {
                    "baseUrl": args.internal_service_url,
                    "sessions": session_ids,
                    "results": pending_results,
                },
                ensure_ascii=False,
            )
        )

    asyncio.run(
        _run_cases(
            args.url,
            args.user_id,
            cases,
            assert_plan_style=args.assert_plan_style,
            open_timeout=args.open_timeout,
            response_timeout=args.response_timeout,
            metrics_output=args.metrics_output,
            history_db=args.history_db,
            keep_response_text=args.keep_response_text,
            clear_history_per_case=args.clear_history_per_case,
            clear_backend_pending_per_case=args.clear_backend_pending_per_case,
            clear_backend_planning_intent_per_case=args.clear_backend_planning_intent_per_case,
            internal_service_url=args.internal_service_url,
            clone_backend_chat_session=args.clone_backend_chat_session,
            backend_db_host=args.backend_db_host,
            backend_db_port=args.backend_db_port,
            backend_db_user=args.backend_db_user,
            backend_db_password=args.backend_db_password,
            backend_db_name=args.backend_db_name,
            backend_volunteer_data_dir=args.backend_volunteer_data_dir,
            runtime_shadow_output=args.runtime_shadow_output,
        )
    )


if __name__ == "__main__":
    main()
