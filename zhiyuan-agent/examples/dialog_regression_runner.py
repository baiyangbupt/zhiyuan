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
import json
import sqlite3
import statistics
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import websockets

DEFAULT_URL = "ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_USER_ID = "dialog-regression-user"
DEFAULT_HISTORY_DB = Path(__file__).resolve().parents[1] / "data" / "chat_history.db"

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
    "选哪个",
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
    "plan-fast-route": "plan_fast_route",
    "plan-query-fast-route": "plan_query_fast_route",
    "major-intent-fast-route": "major_intent_fast_route",
    "major-compare-fast-route": "major_compare_fast_route",
    "career-direction-fast-route": "career_direction_fast_route",
    "pending-intent-impact-fast-route": "pending_intent_impact_fast_route",
    "direct-pending-plan-confirmation": "direct_pending_plan_confirm",
    "direct-pending-intent-confirmation": "direct_pending_intent_confirm",
    "direct-plan-confirmation-guard": "plan_confirmation_guard_no_pending",
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
        primary: list[dict[str, Any]] = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=response_timeout)
            now = time.perf_counter()
            if first_message_at is None:
                first_message_at = now
            message = json.loads(raw)
            primary.append(message)
            if message.get("end") is True:
                final_message_at = now
                break

        followups: list[dict[str, Any]] = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            followups.append(json.loads(raw))

    timing = {
        "firstMessageMs": int(((first_message_at or final_message_at or time.perf_counter()) - started_at) * 1000),
        "finalMessageMs": int(((final_message_at or time.perf_counter()) - started_at) * 1000),
    }
    return primary, followups, timing


def _load_cases(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return DEFAULT_CASES
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("cases file must be a JSON array")
    return data


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
    return adjusted


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
    return summary


def _followup_summary(followups: list[dict[str, Any]]) -> tuple[list[str], list[bool]]:
    targets: list[str] = []
    refreshes: list[bool] = []
    for item in followups:
        content = item.get("content")
        if not isinstance(content, dict):
            continue
        target = content.get("targetView")
        if target is not None:
            text = str(target).strip()
            if text and text not in targets:
                targets.append(text)
        refresh = content.get("refresh")
        if isinstance(refresh, bool):
            refreshes.append(refresh)
    return targets, refreshes


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


def _extract_thinking(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages if m.get("type") == "thinking").strip()


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
    assert_no_followups = bool(step.get("assertNoFollowups"))

    combined_text = text.lower()
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
            f.get("content", {}).get("targetView") == assert_followup_target
            for f in followups
        )
        if not found_target:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupTarget FAILED — expected targetView='{assert_followup_target}' not in followups"
            )
    if assert_followup_refresh is not None:
        found_refresh = any(
            f.get("content", {}).get("refresh") == assert_followup_refresh
            for f in followups
        )
        if not found_refresh:
            violations.append(
                f"{case_name} session={session_id} prompt={prompt_label}: "
                f"assertFollowupRefresh FAILED — expected refresh={assert_followup_refresh} not in followups"
            )
    if assert_no_followups and followups:
        violations.append(
            f"{case_name} session={session_id} prompt={prompt_label}: "
            f"assertNoFollowups FAILED — expected no followups but got {len(followups)}"
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


def _build_metrics_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed_values = [
        int(record["elapsedMs"])
        for record in records
        if isinstance(record.get("elapsedMs"), int) and not record.get("error")
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
        "failedSteps": sum(1 for record in records if record.get("error")),
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
) -> None:
    failures: list[str] = []
    warnings: list[str] = []
    metrics_records: list[dict[str, Any]] = []
    for case in cases:
        name = str(case.get("name") or f"session-{case.get('sessionId')}")
        session_id = str(case["sessionId"])
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
                metrics_records.append(
                    {
                        "case": name,
                        "sessionId": session_id,
                        "prompt": prompt,
                        "elapsedMs": elapsed_ms,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
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
            if keep_response_text:
                record["responseText"] = _extract_text(primary)
                record["thinkingText"] = _extract_thinking(primary)
            if history_db:
                history = _load_history_json(Path(history_db), session_id)
                turn_observability = _summarize_turn_observability(
                    _latest_turn_messages(history, prompt)
                )
                if turn_observability.get("historyMessages"):
                    record["turnObservability"] = turn_observability
            if followups:
                followup_targets, followup_refreshes = _followup_summary(followups)
                record["followupCount"] = len(followups)
                record["followupTargets"] = followup_targets
                record["followupRefreshes"] = followup_refreshes
            text = _extract_text(primary)
            if case_assert_style:
                violations = _check_plan_reply_style(text)
                if violations:
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
            perf_failures, perf_warnings = _check_performance_assertions(elapsed_ms, step, name, session_id)
            for warning in perf_warnings:
                print(f"  LATENCY_WARN: {warning}")
            failures.extend(perf_failures)
            warnings.extend(perf_warnings)
            if content_violations:
                record["contentViolations"] = content_violations
            if perf_failures:
                record["performanceViolations"] = perf_failures
            if perf_warnings:
                record["performanceWarnings"] = perf_warnings
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
    print("=== METRICS SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
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
                    "warnings": warnings,
                    "failures": failures,
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
    parser.add_argument("--session", help="run an ad hoc session id")
    parser.add_argument("--prompts", nargs="*", help="ad hoc prompts for --session")
    parser.add_argument("--assert-plan-style", action="store_true", help="fail when plan replies contain severe forced-choice or internal wording")
    parser.add_argument("--open-timeout", type=float, default=30, help="websocket opening handshake timeout in seconds")
    parser.add_argument("--response-timeout", type=float, default=120, help="timeout in seconds while waiting for each prompt response")
    parser.add_argument("--metrics-output", help="write per-step latency and assertion summary to JSON")
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
    args = parser.parse_args()

    if args.session:
        prompts = args.prompts or ["方案有了么"]
        cases = [{"name": "ad-hoc", "sessionId": args.session, "prompts": prompts}]
    else:
        cases = _load_cases(args.cases)
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
        )
    )


if __name__ == "__main__":
    main()
