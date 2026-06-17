#!/usr/bin/env python3
"""LLM-driven exploratory dialog runner for the live Agent websocket.

This script is intentionally an examples/ tool. It does not change production
runtime behavior. It can reuse an existing chatSessionId, or explicitly create a
new backend session when tk/pf and a payload are provided.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DEFAULT_SCENARIOS = EXAMPLES / "dialog_auto_explorer_scenarios.json"
DEFAULT_AGENT_URL = "ws://127.0.0.1:18091/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_BACKEND_URL = os.environ.get("INTERNAL_SERVICE_URL") or "http://127.0.0.1:18090"
DEFAULT_HISTORY_DB = ROOT / "data" / "chat_history.db"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("DIALOG_AUTO_EXPLORER_OUTPUT_DIR") or "/tmp/zhiyuan-dialog-auto-explorer")
DEFAULT_USER_ID = "dialog-auto-explorer"

RUNNER_PATH = EXAMPLES / "dialog_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner_for_auto_explorer", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {RUNNER_PATH}")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

COLLECTOR_PATH = EXAMPLES / "collect_production_session_samples.py"
COLLECTOR_SPEC = importlib.util.spec_from_file_location("collect_production_session_samples_for_auto_explorer", COLLECTOR_PATH)
if COLLECTOR_SPEC is None or COLLECTOR_SPEC.loader is None:
    raise RuntimeError(f"cannot load {COLLECTOR_PATH}")
collector = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(collector)

SEV_ERROR = "error"
SEV_WARN = "warning"
SEV_INFO = "info"

INTERNAL_LEAK_SUBSTRINGS = [
    "payload",
    "action_family",
    "volunteerId",
    "pending_plan_action",
    "pending_intent_change",
    "tool_call_id",
    "traceback",
    "NullPointerException",
    "Local auth bypass",
]

USER_VISIBLE_ERROR_SUBSTRINGS = [
    "system error",
    "server error",
    "服务器异常",
    "系统错误",
    "刷新候选池失败",
    "当前权益不足",
]


@dataclass
class LLMSettings:
    provider: str
    model: str
    api_key: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout_seconds: float


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(ROOT / ".env", override=False)


def _llm_settings() -> LLMSettings:
    _load_dotenv()
    provider = os.environ.get("LLM_PROVIDER", "openai_compatible").strip()
    model = os.environ.get("LLM_MODEL_NAME", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    if provider == "openai" and not base_url:
        base_url = "https://api.openai.com/v1"
    if not model:
        raise RuntimeError("LLM_MODEL_NAME is required for dialog auto explorer")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required for dialog auto explorer")
    if not base_url:
        raise RuntimeError("LLM_BASE_URL is required for dialog auto explorer")
    return LLMSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        temperature=float(os.environ.get("DIALOG_AUTO_EXPLORER_TEMPERATURE") or os.environ.get("LLM_TEMPERATURE") or 0.6),
        max_tokens=int(os.environ.get("DIALOG_AUTO_EXPLORER_MAX_TOKENS") or 800),
        timeout_seconds=float(os.environ.get("DIALOG_AUTO_EXPLORER_LLM_TIMEOUT") or 60),
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


async def _call_llm_json(messages: list[dict[str, str]], *, settings: LLMSettings | None = None) -> dict[str, Any]:
    cfg = settings or _llm_settings()
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=cfg.timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{cfg.base_url}/chat/completions", json=payload, headers=headers) as resp:
            raw = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"LLM request failed status={resp.status} body={raw[:300]}")
            data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    parsed = _extract_json_object(content)
    if not parsed:
        raise RuntimeError(f"LLM did not return a JSON object: {content[:300]}")
    return parsed


def _load_scenario_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
        scenarios: list[dict[str, Any]] = []
        for item in data["scenarios"]:
            if not isinstance(item, dict):
                continue
            merged = {**defaults, **item}
            merged["goals"] = [*defaults.get("goals", []), *item.get("goals", [])]
            merged["issueFocus"] = [*defaults.get("issueFocus", []), *item.get("issueFocus", [])]
            scenarios.append(merged)
        return scenarios
    raise ValueError("scenario file must be a list or an object with scenarios[]")


def _select_scenarios(all_scenarios: list[dict[str, Any]], names: list[str] | None) -> list[dict[str, Any]]:
    if not names:
        return all_scenarios
    wanted = set(names)
    selected = [item for item in all_scenarios if str(item.get("name")) in wanted]
    missing = sorted(wanted - {str(item.get("name")) for item in selected})
    if missing:
        raise ValueError(f"unknown scenario names: {missing}")
    return selected


def _extract_session_id(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend([
            data.get("chatSessionId"),
            data.get("sessionId"),
            data.get("id"),
        ])
        session = data.get("session") or data.get("chatSession")
        if isinstance(session, dict):
            candidates.extend([session.get("chatSessionId"), session.get("sessionId"), session.get("id")])
        page_url = str(data.get("url") or data.get("webUrl") or data.get("redirectUrl") or "")
        if page_url:
            parsed = parse.urlparse(page_url)
            query = parse.parse_qs(parsed.query)
            candidates.extend(query.get("chatSessionId") or [])
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    raise ValueError("cannot extract chatSessionId from create session response")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: float = 180) -> dict[str, Any]:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except (OSError, error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"POST {url} failed: {type(exc).__name__}: {exc}") from exc
    return json.loads(raw) if raw else {}


def _create_session(
    *,
    backend_url: str,
    tenant_id: str,
    payload: dict[str, Any],
    mode: str,
    tk: str,
    pf: str,
) -> dict[str, Any]:
    base = backend_url.rstrip("/")
    if mode == "integration":
        endpoint = f"{base}/gaotu-assistant-bot/chat/{tenant_id}/integration/v1/session/initialize"
    elif mode == "session":
        endpoint = f"{base}/gaotu-assistant-bot/chat/{tenant_id}/session/create"
    else:
        raise ValueError(f"unsupported create mode: {mode}")
    headers: dict[str, str] = {}
    if tk:
        headers["tk"] = tk
    if pf:
        headers["pf"] = pf
    return _post_json(endpoint, payload, headers)


def _text_snippet(text: str, limit: int = 300) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized[:limit]


def _add_issue(issues: list[dict[str, Any]], *, code: str, severity: str, message: str, evidence: str = "") -> None:
    issues.append({"code": code, "severity": severity, "message": message, "evidence": _text_snippet(evidence, 500)})


def _is_repeated_reply(previous_text: str, text: str) -> bool:
    previous = _text_snippet(previous_text, 500)
    current = _text_snippet(text, 500)
    if len(previous) <= 80 or len(current) <= 80:
        return False
    if previous == current or previous in current or current in previous:
        return True
    return SequenceMatcher(None, previous, current).ratio() >= 0.92


def _detect_heuristic_issues(
    *,
    scenario: dict[str, Any],
    prompt: str,
    text: str,
    thinking: str,
    followups: list[dict[str, Any]],
    ws_error: str,
    elapsed_ms: int,
    previous_text: str = "",
) -> list[dict[str, Any]]:
    del scenario, prompt, followups
    issues: list[dict[str, Any]] = []
    if ws_error:
        _add_issue(issues, code="ws_error", severity=SEV_ERROR, message="Agent websocket returned an error message", evidence=ws_error)
    if not text.strip() and not ws_error:
        _add_issue(issues, code="empty_reply", severity=SEV_ERROR, message="Assistant reply text is empty")
    for value in INTERNAL_LEAK_SUBSTRINGS:
        if value.lower() in text.lower() or value.lower() in thinking.lower():
            _add_issue(issues, code="internal_leak", severity=SEV_ERROR, message=f"Internal implementation token leaked: {value}", evidence=text or thinking)
    for value in USER_VISIBLE_ERROR_SUBSTRINGS:
        if value.lower() in text.lower():
            _add_issue(issues, code="user_visible_error", severity=SEV_ERROR, message=f"User visible error wording detected: {value}", evidence=text)
    for violation in runner._check_plan_reply_style(text):
        _add_issue(issues, code="style_violation", severity=SEV_ERROR, message=violation, evidence=text)
    if 0 < len(text.strip()) < 60:
        _add_issue(issues, code="too_short", severity=SEV_WARN, message="Assistant reply is very short for an advisory dialog", evidence=text)
    if elapsed_ms >= 180000:
        _add_issue(issues, code="slow_reply", severity=SEV_WARN, message=f"Assistant reply took {elapsed_ms}ms", evidence=str(elapsed_ms))
    if previous_text and _is_repeated_reply(previous_text, text):
        _add_issue(issues, code="repeated_reply", severity=SEV_WARN, message="Assistant repeated the previous reply almost verbatim", evidence=text)
    return issues


async def _judge_turn_with_llm(
    *,
    scenario: dict[str, Any],
    prompt: str,
    response_text: str,
    followup_summary: dict[str, Any],
    session_context: dict[str, Any],
    settings: LLMSettings | None,
) -> list[dict[str, Any]]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict QA reviewer for a Chinese college-admission assistant. "
                "Return JSON only. Flag concrete user-facing problems: wrong action boundary, contradiction, "
                "unclear next step, hallucinated plan state, internal terminology leakage, or refusal. "
                "Do not flag minor style preferences. You are also given sessionContext from backend hidden state. "
                "Do not mark concrete numbers, schools, majors, plan size, candidate counts, review status, "
                "or data freshness facts as hallucinated when they are supported by sessionContext. Still flag "
                "wording, action-boundary problems, contradictions, unsupported claims, or conflicts with sessionContext."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scenario": {
                        "name": scenario.get("name"),
                        "description": scenario.get("description"),
                        "goals": scenario.get("goals") or [],
                        "issueFocus": scenario.get("issueFocus") or [],
                    },
                    "userPrompt": prompt,
                    "assistantResponse": response_text,
                    "followups": followup_summary,
                    "sessionContext": session_context,
                    "requiredJsonSchema": {
                        "issues": [
                            {"severity": "error|warning|info", "code": "short_code", "message": "specific issue", "evidence": "short quote"}
                        ]
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    parsed = await _call_llm_json(messages, settings=settings)
    raw_issues = parsed.get("issues") if isinstance(parsed.get("issues"), list) else []
    issues: list[dict[str, Any]] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or SEV_WARN).strip().lower()
        if severity not in {SEV_ERROR, SEV_WARN, SEV_INFO}:
            severity = SEV_WARN
        code = str(item.get("code") or "llm_judge_issue").strip() or "llm_judge_issue"
        message = str(item.get("message") or "LLM judge flagged this turn").strip()
        evidence = str(item.get("evidence") or "").strip()
        _add_issue(issues, code=f"llm_{code}", severity=severity, message=message, evidence=evidence)
    return issues


def _compact_turns(turns: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for turn in turns[-limit:]:
        compact.append(
            {
                "turn": turn.get("turn"),
                "user": _text_snippet(turn.get("prompt", ""), 220),
                "assistant": _text_snippet(turn.get("responseText", ""), 420),
                "issues": [f"{item.get('severity')}:{item.get('code')}" for item in turn.get("issues", [])],
            }
        )
    return compact


async def _generate_next_user_prompt(
    *,
    scenario: dict[str, Any],
    turns: list[dict[str, Any]],
    settings: LLMSettings | None,
) -> dict[str, str]:
    messages = [
        {
            "role": "system",
            "content": (
                "You simulate a realistic Chinese parent or student using a college-admission planning assistant. "
                "Keep messages natural, short, and scenario-focused. Probe the assistant until the flow is complete "
                "or quality problems appear. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scenario": {
                        "name": scenario.get("name"),
                        "description": scenario.get("description"),
                        "persona": scenario.get("persona"),
                        "goals": scenario.get("goals") or [],
                        "issueFocus": scenario.get("issueFocus") or [],
                    },
                    "dialogSoFar": _compact_turns(turns),
                    "instruction": (
                        "Return {'action':'ask','message':'...','reason':'...'} to continue, or "
                        "{'action':'stop','message':'','reason':'...'} if the scenario is sufficiently covered. "
                        "The message must be in Chinese and should be one user turn only."
                    ),
                },
                ensure_ascii=False,
            ),
        },
    ]
    parsed = await _call_llm_json(messages, settings=settings)
    action = str(parsed.get("action") or "ask").strip().lower()
    message = str(parsed.get("message") or "").strip()
    reason = str(parsed.get("reason") or "").strip()
    if action == "stop":
        return {"action": "stop", "message": "", "reason": reason or "model_stop"}
    if not message:
        return {"action": "stop", "message": "", "reason": "model_returned_empty_message"}
    return {"action": "ask", "message": message, "reason": reason}


def _next_prompt_from_seed(scenario: dict[str, Any], turns: list[dict[str, Any]]) -> str | None:
    seed_prompts = scenario.get("seedPrompts") or scenario.get("prompts") or []
    if len(turns) >= len(seed_prompts):
        return None
    item = seed_prompts[len(turns)]
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("prompt") or item.get("text") or "").strip()
    return str(item).strip()


def _should_stop_after_turn(
    *,
    turn_index: int,
    first_issue_turn: int | None,
    extra_turns_after_issue: int,
    issue_count: int,
    issue_limit: int,
    model_requested_stop: bool = False,
) -> bool:
    if first_issue_turn is not None and turn_index >= first_issue_turn + max(extra_turns_after_issue, 0):
        return True
    if model_requested_stop and (first_issue_turn is None or issue_count == 0):
        return True
    if issue_limit > 0 and issue_count >= issue_limit and first_issue_turn is not None:
        return turn_index >= first_issue_turn + max(extra_turns_after_issue, 0)
    return False


def _severity_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {SEV_ERROR: 0, SEV_WARN: 0, SEV_INFO: 0}
    for item in issues:
        severity = str(item.get("severity") or SEV_WARN)
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _collect_issues(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for turn in turns:
        for item in turn.get("issues", []) or []:
            payload = dict(item)
            payload["turn"] = turn.get("turn")
            payload["prompt"] = turn.get("prompt")
            issues.append(payload)
    return issues


def _load_history_observability(history_db: str, session_id: str, prompt: str) -> dict[str, Any]:
    if not history_db:
        return {}
    path = Path(history_db)
    if not path.exists():
        return {}
    try:
        history = runner._load_history_json(path, session_id)
        turn_messages = runner._latest_turn_messages(history, prompt)
        return runner._summarize_turn_observability(turn_messages)
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return {}


def _compact_issue_context(value: Any, *, max_string_len: int = 500) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_issue_context(item, max_string_len=max_string_len) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_issue_context(item, max_string_len=max_string_len) for item in value]
    if isinstance(value, str) and len(value) > max_string_len:
        return value[:max_string_len] + f"...<truncated {len(value) - max_string_len} chars>"
    return value


def _fetch_session_context(
    *,
    backend_url: str,
    tenant_id: str,
    session_id: str,
    timeout_seconds: float,
    sample_size: int,
) -> dict[str, Any]:
    """Fetch a redacted backend summary for LLM judge grounding."""
    base = backend_url.rstrip("/")
    score_resp = collector.fetch_json(
        base,
        f"/gaotu-assistant-bot/inner/chat/{tenant_id}/session/get-extra-data",
        {"chatSessionId": session_id, "keyList": "userScoreDetail", "version": 0},
        timeout=timeout_seconds,
    )
    workspace_resp = collector.fetch_json(
        base,
        f"/gaotu-assistant-bot/inner/planning/{tenant_id}/session/workspace-state",
        {"chatSessionId": session_id},
        timeout=timeout_seconds,
    )
    return _compact_issue_context(
        {
            "sessionId": session_id,
            "userScoreDetail": collector.summarize_user_score(score_resp),
            "planningState": collector.summarize_workspace(workspace_resp, sample_size=sample_size),
        }
    )


async def _run_scenario(
    *,
    scenario: dict[str, Any],
    session_id: str,
    agent_url: str,
    user_id: str,
    max_turns: int,
    extra_turns_after_issue: int,
    issue_limit: int,
    open_timeout: float,
    response_timeout: float,
    history_db: str,
    backend_url: str,
    tenant_id: str,
    context_timeout: float,
    context_sample_size: int,
    llm_user: bool,
    llm_judge: bool,
    llm_settings: LLMSettings | None,
) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    first_issue_turn: int | None = None
    model_requested_stop = False
    previous_text = ""

    for turn_index in range(1, max_turns + 1):
        prompt = _next_prompt_from_seed(scenario, turns)
        prompt_reason = "seed_prompt"
        if prompt is None:
            if not llm_user:
                break
            generated = await _generate_next_user_prompt(scenario=scenario, turns=turns, settings=llm_settings)
            prompt_reason = generated.get("reason") or "llm_generated"
            if generated.get("action") == "stop":
                model_requested_stop = True
                if not turns:
                    break
                if _should_stop_after_turn(
                    turn_index=turn_index - 1,
                    first_issue_turn=first_issue_turn,
                    extra_turns_after_issue=extra_turns_after_issue,
                    issue_count=len(_collect_issues(turns)),
                    issue_limit=issue_limit,
                    model_requested_stop=True,
                ):
                    break
                prompt = "还有没有需要我注意的问题？"
            else:
                prompt = generated.get("message") or "还有没有需要我注意的问题？"
        started_at = time.perf_counter()
        try:
            primary, followups, timing = await runner._ask_once(
                agent_url,
                session_id,
                user_id,
                prompt,
                open_timeout=open_timeout,
                response_timeout=response_timeout,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            response_text = runner._extract_text(primary)
            thinking_text = runner._extract_thinking(primary)
            ws_error = runner._extract_error_text(primary)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            primary = []
            followups = []
            timing = {"firstMessageMs": None, "finalMessageMs": None}
            response_text = ""
            thinking_text = ""
            ws_error = f"{type(exc).__name__}: {exc}"
        followup_targets, followup_refreshes, followup_types = runner._followup_summary(followups)
        observability = _load_history_observability(history_db, session_id, prompt)
        session_context = _fetch_session_context(
            backend_url=backend_url,
            tenant_id=tenant_id,
            session_id=session_id,
            timeout_seconds=context_timeout,
            sample_size=context_sample_size,
        ) if llm_judge else {}
        if observability.get("historyMessages"):
            session_context["turnObservability"] = observability
        issues = _detect_heuristic_issues(
            scenario=scenario,
            prompt=prompt,
            text=response_text,
            thinking=thinking_text,
            followups=followups,
            ws_error=ws_error,
            elapsed_ms=elapsed_ms,
            previous_text=previous_text,
        )
        if llm_judge and response_text:
            try:
                judged = await _judge_turn_with_llm(
                    scenario=scenario,
                    prompt=prompt,
                    response_text=response_text,
                    followup_summary={"targets": followup_targets, "refreshes": followup_refreshes, "types": followup_types},
                    session_context=session_context,
                    settings=llm_settings,
                )
                issues.extend(judged)
            except Exception as exc:
                _add_issue(
                    issues,
                    code="llm_judge_failed",
                    severity=SEV_WARN,
                    message=f"LLM judge failed: {type(exc).__name__}",
                    evidence=str(exc),
                )
        turn = {
            "turn": turn_index,
            "sessionId": session_id,
            "prompt": prompt,
            "promptSource": prompt_reason,
            "elapsedMs": elapsed_ms,
            "firstMessageMs": timing.get("firstMessageMs"),
            "finalMessageMs": timing.get("finalMessageMs"),
            "primaryMessages": len(primary),
            "thinkingMessages": sum(1 for message in primary if message.get("type") == "thinking"),
            "followupMessages": len(followups),
            "followupTargets": followup_targets,
            "followupRefreshes": followup_refreshes,
            "followupTypes": followup_types,
            "responseText": response_text,
            "thinkingText": thinking_text,
            "wsError": ws_error,
            "issues": issues,
        }
        if observability.get("historyMessages"):
            turn["turnObservability"] = observability
        if session_context:
            turn["sessionContext"] = session_context
        turns.append(turn)
        if issues and first_issue_turn is None:
            first_issue_turn = turn_index
        previous_text = response_text
        issue_count = len(_collect_issues(turns))
        print(json.dumps({"event": "turn", "scenario": scenario.get("name"), "turn": turn_index, "issues": len(issues), "elapsedMs": elapsed_ms}, ensure_ascii=True))
        if _should_stop_after_turn(
            turn_index=turn_index,
            first_issue_turn=first_issue_turn,
            extra_turns_after_issue=extra_turns_after_issue,
            issue_count=issue_count,
            issue_limit=issue_limit,
            model_requested_stop=model_requested_stop,
        ):
            break
    issues = _collect_issues(turns)
    return {
        "name": scenario.get("name"),
        "description": scenario.get("description"),
        "sessionId": session_id,
        "turns": turns,
        "issues": issues,
        "summary": {
            "turns": len(turns),
            "issues": len(issues),
            "severity": _severity_counts(issues),
            "firstIssueTurn": first_issue_turn,
        },
    }


def _build_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Dialog Auto Explorer Report",
        "",
        f"- generatedAt: {payload.get('generatedAt')}",
        f"- scenarios: {payload.get('summary', {}).get('scenarios')}",
        f"- turns: {payload.get('summary', {}).get('turns')}",
        f"- issues: {payload.get('summary', {}).get('issues')}",
        "",
        "| Scenario | Session | Turns | Issues | Errors | Warnings |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for scenario in payload.get("scenarios") or []:
        severity = scenario.get("summary", {}).get("severity") or {}
        lines.append(
            f"| {scenario.get('name')} | {scenario.get('sessionId')} | {scenario.get('summary', {}).get('turns', 0)} | "
            f"{scenario.get('summary', {}).get('issues', 0)} | {severity.get(SEV_ERROR, 0)} | {severity.get(SEV_WARN, 0)} |"
        )
    lines.extend(["", "## Issues", ""])
    for scenario in payload.get("scenarios") or []:
        if not scenario.get("issues"):
            continue
        lines.append(f"### {scenario.get('name')} session={scenario.get('sessionId')}")
        for issue in scenario.get("issues") or []:
            lines.append(
                f"- turn {issue.get('turn')} [{issue.get('severity')}] {issue.get('code')}: {issue.get('message')}"
            )
            if issue.get("evidence"):
                lines.append(f"  evidence: {issue.get('evidence')}")
        lines.append("")
    lines.extend(["## Turn Samples", ""])
    for scenario in payload.get("scenarios") or []:
        lines.append(f"### {scenario.get('name')}")
        for turn in scenario.get("turns") or []:
            lines.append(f"- T{turn.get('turn')} user: {_text_snippet(turn.get('prompt', ''), 160)}")
            lines.append(f"  assistant: {_text_snippet(turn.get('responseText', ''), 240)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _summarize_payload(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    turns = sum(len(item.get("turns") or []) for item in scenarios)
    issues = [issue for item in scenarios for issue in (item.get("issues") or [])]
    return {
        "scenarios": len(scenarios),
        "turns": turns,
        "issues": len(issues),
        "severity": _severity_counts(issues),
    }


async def _main_async(args: argparse.Namespace) -> int:
    scenarios = _select_scenarios(_load_scenario_payload(Path(args.scenarios)), args.scenario)
    llm_settings = _llm_settings() if (not args.disable_llm_user or args.llm_judge) else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y%m%d-%H%M%S")

    results: list[dict[str, Any]] = []
    create_payload = json.loads(Path(args.create_session_payload).read_text(encoding="utf-8")) if args.create_session_payload else None
    for scenario in scenarios:
        session_id = str(args.session_id or scenario.get("sessionId") or "").strip()
        create_response: dict[str, Any] | None = None
        if create_payload is not None:
            create_response = _create_session(
                backend_url=args.backend_url,
                tenant_id=args.tenant_id,
                payload=create_payload,
                mode=args.create_mode,
                tk=args.tk or os.environ.get("DIALOG_AUTO_EXPLORER_TK", ""),
                pf=args.pf or os.environ.get("DIALOG_AUTO_EXPLORER_PF", "WEB"),
            )
            session_id = _extract_session_id(create_response)
        if not session_id:
            raise ValueError(f"scenario {scenario.get('name')} has no sessionId; pass --session-id or --create-session-payload")
        if args.clear_history:
            runner._clear_history(Path(args.history_db), [session_id])
        if args.clear_backend_pending:
            runner._clear_backend_pending_state(args.backend_url, [session_id])
        print(json.dumps({"event": "scenario_start", "scenario": scenario.get("name"), "sessionId": session_id}, ensure_ascii=True))
        result = await _run_scenario(
            scenario=scenario,
            session_id=session_id,
            agent_url=args.agent_url,
            user_id=args.user_id,
            max_turns=args.max_turns,
            extra_turns_after_issue=args.extra_turns_after_issue,
            issue_limit=args.issue_limit,
            open_timeout=args.open_timeout,
            response_timeout=args.response_timeout,
            history_db=args.history_db,
            backend_url=args.backend_url,
            tenant_id=args.tenant_id,
            context_timeout=args.context_timeout,
            context_sample_size=args.context_sample_size,
            llm_user=not args.disable_llm_user,
            llm_judge=args.llm_judge,
            llm_settings=llm_settings,
        )
        if create_response is not None:
            result["createSession"] = {"mode": args.create_mode, "responseCode": create_response.get("code"), "responseMsg": create_response.get("msg")}
        results.append(result)

    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": {
            "agentUrl": args.agent_url,
            "backendUrl": args.backend_url,
            "maxTurns": args.max_turns,
            "extraTurnsAfterIssue": args.extra_turns_after_issue,
            "llmUser": not args.disable_llm_user,
            "llmJudge": args.llm_judge,
            "contextSampleSize": args.context_sample_size,
        },
        "summary": _summarize_payload(results),
        "scenarios": results,
    }
    json_path = output_dir / f"dialog-auto-explorer-{created_at}.json"
    md_path = output_dir / f"dialog-auto-explorer-{created_at}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_build_markdown_report(payload), encoding="utf-8")
    print(json.dumps({"event": "report", "json": str(json_path), "markdown": str(md_path), "summary": payload["summary"]}, ensure_ascii=True))
    return 1 if payload["summary"].get("severity", {}).get(SEV_ERROR, 0) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LLM-driven exploratory dialogs against the live Agent websocket.")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS), help="scenario JSON file")
    parser.add_argument("--scenario", action="append", help="scenario name to run; can repeat")
    parser.add_argument("--session-id", help="reuse this backend chatSessionId for every selected scenario")
    parser.add_argument("--create-session-payload", help="JSON payload used to create a fresh backend session before each scenario")
    parser.add_argument("--create-mode", choices=["session", "integration"], default="integration", help="backend create endpoint mode")
    parser.add_argument("--tk", default="", help="login token header for backend create session")
    parser.add_argument("--pf", default="WEB", help="platform header for backend create session")
    parser.add_argument("--tenant-id", default="1")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--agent-url", default=DEFAULT_AGENT_URL)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB))
    parser.add_argument("--context-timeout", type=float, default=20)
    parser.add_argument("--context-sample-size", type=int, default=8)
    parser.add_argument("--clear-history", action="store_true")
    parser.add_argument("--clear-backend-pending", action="store_true")
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--extra-turns-after-issue", type=int, default=2)
    parser.add_argument("--issue-limit", type=int, default=5)
    parser.add_argument("--open-timeout", type=float, default=30)
    parser.add_argument("--response-timeout", type=float, default=180)
    parser.add_argument("--disable-llm-user", action="store_true", help="only run seed prompts; do not generate follow-up user turns")
    parser.add_argument("--llm-judge", action="store_true", help="use the configured LLM to judge each assistant turn")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main_async(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
