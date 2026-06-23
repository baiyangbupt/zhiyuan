#!/usr/bin/env python3
"""Benchmark LLM providers with real agent scenarios and direct API calls.

The config file must not contain real API keys. Use api_key_env to reference
local environment variables instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import websockets


DEFAULT_CASES = "examples/model_provider_benchmark_e2e_cases.json"
DEFAULT_WS_PATH = "/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_USER_ID = "model-benchmark-user"
DEFAULT_DIRECT_RUNS = 3
DEFAULT_AGENT_RUNS = 1
DEFAULT_HISTORY_DB = Path(__file__).resolve().parents[1] / "data" / "chat_history.db"


@dataclass
class ProviderConfig:
    name: str
    provider: str
    model: str
    base_url: str
    api_key_env: str
    temperature: float = 0
    max_tokens: int = 1024

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProviderConfig":
        required = ["name", "provider", "model", "base_url", "api_key_env"]
        missing = [key for key in required if not str(raw.get(key) or "").strip()]
        if missing:
            raise ValueError(f"provider config missing required fields: {missing}")
        return cls(
            name=str(raw["name"]),
            provider=str(raw["provider"]),
            model=str(raw["model"]),
            base_url=str(raw["base_url"]).rstrip("/"),
            api_key_env=str(raw["api_key_env"]),
            temperature=float(raw.get("temperature", 0)),
            max_tokens=int(raw.get("max_tokens", 1024)),
        )

    def api_key(self) -> str:
        value = os.environ.get(self.api_key_env, "").strip()
        if not value:
            raise RuntimeError(f"missing API key env var: {self.api_key_env}")
        return value

    def agent_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "LLM_PROVIDER": self.provider,
                "LLM_MODEL_NAME": self.model,
                "LLM_BASE_URL": self.base_url,
                "LLM_API_KEY": self.api_key(),
                "LLM_TEMPERATURE": str(self.temperature),
                "LLM_MAX_TOKENS": str(self.max_tokens),
            }
        )
        return env


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_config(path: str) -> tuple[list[ProviderConfig], list[dict[str, str]]]:
    raw = _load_json(path)
    providers = [ProviderConfig.from_dict(item) for item in raw.get("providers", [])]
    if not providers:
        raise ValueError("config must contain at least one provider")
    direct_prompts = raw.get("direct_prompts") or []
    if not direct_prompts:
        direct_prompts = [
            {
                "name": "short_explanation",
                "prompt": "用两句话解释高考志愿填报里的冲稳保是什么意思。",
            }
        ]
    return providers, direct_prompts


def _select_providers(providers: list[ProviderConfig], selected: list[str] | None) -> list[ProviderConfig]:
    if not selected:
        return providers
    selected_set = set(selected)
    filtered = [provider for provider in providers if provider.name in selected_set]
    missing = selected_set - {provider.name for provider in filtered}
    if missing:
        raise ValueError(f"provider names not found in config: {sorted(missing)}")
    return filtered


def _duration_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(max(values), 3),
    }


def _classify_provider_error(status_code: int | None, body: str) -> str:
    text = str(body or "").lower()
    if "insufficient balance" in text or "insufficient_balance" in text:
        return "insufficient_balance"
    if "model does not exist" in text or "model not found" in text:
        return "model_not_found"
    if "quota" in text or "rate limit" in text or "rate_limit" in text:
        return "quota_or_rate_limited"
    if status_code is None:
        return "request_error"
    if status_code in {401, 403}:
        return "auth_or_permission_error"
    if status_code == 404:
        return "not_found"
    if status_code >= 500:
        return "provider_server_error"
    if status_code >= 400:
        return "http_error"
    return "ok"


def _extract_model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return []
    result: list[str] = []
    for item in raw_items:
        model_id = item.get("id") if isinstance(item, dict) else item
        text = str(model_id or "").strip()
        if text:
            result.append(text)
    return result


def _precheck_smoke_payload(provider: ProviderConfig) -> dict[str, Any]:
    return {
        "model": provider.model,
        "messages": [{"role": "user", "content": "请只回复 OK"}],
        "temperature": 0,
        "max_tokens": max(1, min(int(provider.max_tokens or 16), 16)),
    }


async def _run_provider_precheck(provider: ProviderConfig, *, timeout: float) -> dict[str, Any]:
    """Check provider availability without exposing API key values."""
    record: dict[str, Any] = {
        "provider": provider.name,
        "model": provider.model,
        "base_url": provider.base_url,
        "api_key_env": provider.api_key_env,
        "api_key_present": False,
        "models_endpoint": None,
        "direct_smoke": None,
        "status": "unknown",
        "quality_matrix_eligible": False,
        "excluded_reason": None,
    }
    try:
        api_key = provider.api_key()
    except RuntimeError:
        record["status"] = "missing_api_key"
        record["excluded_reason"] = "missing_api_key"
        return record
    record["api_key_present"] = True
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        models_started = time.perf_counter()
        models_record: dict[str, Any] = {}
        try:
            response = await client.get(f"{provider.base_url}/models", headers=headers)
            models_record.update(
                {
                    "status": response.status_code,
                    "total_seconds": round(time.perf_counter() - models_started, 3),
                }
            )
            if response.status_code >= 400:
                body = response.text[:500]
                models_record["error_category"] = _classify_provider_error(response.status_code, body)
                models_record["error"] = body
            else:
                try:
                    model_ids = _extract_model_ids(response.json())
                except ValueError:
                    model_ids = []
                    models_record["error_category"] = "invalid_json"
                models_record["model_count"] = len(model_ids)
                models_record["model_listed"] = provider.model in model_ids if model_ids else None
        except Exception as exc:
            models_record.update(
                {
                    "total_seconds": round(time.perf_counter() - models_started, 3),
                    "error_category": "request_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        record["models_endpoint"] = models_record

        smoke_started = time.perf_counter()
        smoke_record: dict[str, Any] = {}
        try:
            response = await client.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=_precheck_smoke_payload(provider),
            )
            smoke_record.update(
                {
                    "status": response.status_code,
                    "total_seconds": round(time.perf_counter() - smoke_started, 3),
                    "response_bytes": len(response.content),
                }
            )
            if response.status_code >= 400:
                body = response.text[:500]
                smoke_record["error_category"] = _classify_provider_error(response.status_code, body)
                smoke_record["error"] = body
        except Exception as exc:
            smoke_record.update(
                {
                    "total_seconds": round(time.perf_counter() - smoke_started, 3),
                    "error_category": "request_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        record["direct_smoke"] = smoke_record

    if (record.get("direct_smoke") or {}).get("status") and int((record["direct_smoke"] or {}).get("status")) < 400:
        record["status"] = "ok"
        record["quality_matrix_eligible"] = True
        return record
    direct_category = str((record.get("direct_smoke") or {}).get("error_category") or "").strip()
    models_category = str((record.get("models_endpoint") or {}).get("error_category") or "").strip()
    record["status"] = direct_category or models_category or "unavailable"
    record["excluded_reason"] = record["status"]
    return record


async def run_provider_prechecks(
    providers: list[ProviderConfig],
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider in providers:
        print(f"[precheck] provider={provider.name} model={provider.model}")
        result = await _run_provider_precheck(provider, timeout=timeout)
        results.append(result)
        print(
            "  status={status} eligible={eligible} reason={reason}".format(
                status=result.get("status"),
                eligible=result.get("quality_matrix_eligible"),
                reason=result.get("excluded_reason") or "",
            )
        )
    return results


def _filter_prechecked_providers(
    providers: list[ProviderConfig],
    prechecks: list[dict[str, Any]],
) -> list[ProviderConfig]:
    eligible = {
        str(item.get("provider") or "")
        for item in prechecks
        if item.get("quality_matrix_eligible") is True
    }
    return [provider for provider in providers if provider.name in eligible]


def _direct_payload(provider: ProviderConfig, prompt: str, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": provider.temperature,
        "max_tokens": provider.max_tokens,
    }
    if stream:
        payload["stream"] = True
    return payload


async def _run_direct_prompt(
    provider: ProviderConfig,
    prompt_case: dict[str, str],
    *,
    runs: int,
    timeout: float,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {provider.api_key()}",
        "Content-Type": "application/json",
    }
    prompt = str(prompt_case["prompt"])
    result: dict[str, Any] = {
        "prompt": prompt_case.get("name") or prompt[:24],
        "non_stream": [],
        "stream": [],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        for index in range(runs):
            started = time.perf_counter()
            record: dict[str, Any] = {"run": index + 1}
            try:
                response = await client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=_direct_payload(provider, prompt, stream=False),
                )
                record.update(
                    {
                        "status": response.status_code,
                        "total_seconds": round(time.perf_counter() - started, 3),
                        "response_bytes": len(response.content),
                    }
                )
                if response.status_code >= 400:
                    record["error"] = response.text[:500]
            except Exception as exc:
                record.update({"error": f"{type(exc).__name__}: {exc}", "total_seconds": round(time.perf_counter() - started, 3)})
            result["non_stream"].append(record)

        for index in range(runs):
            started = time.perf_counter()
            first_chunk_at: float | None = None
            chunks = 0
            record = {"run": index + 1}
            try:
                async with client.stream(
                    "POST",
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=_direct_payload(provider, prompt, stream=True),
                ) as response:
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            chunks += 1
                            if first_chunk_at is None:
                                first_chunk_at = time.perf_counter()
                    record.update(
                        {
                            "status": response.status_code,
                            "first_chunk_seconds": round(first_chunk_at - started, 3) if first_chunk_at else None,
                            "total_seconds": round(time.perf_counter() - started, 3),
                            "chunks": chunks,
                        }
                    )
                    if response.status_code >= 400:
                        record["error"] = "stream returned error status"
            except Exception as exc:
                record.update({"error": f"{type(exc).__name__}: {exc}", "total_seconds": round(time.perf_counter() - started, 3), "chunks": chunks})
            result["stream"].append(record)
    return result


async def run_direct_benchmark(
    providers: list[ProviderConfig],
    prompts: list[dict[str, str]],
    *,
    runs: int,
    timeout: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider in providers:
        provider_result = {
            "provider": provider.name,
            "model": provider.model,
            "base_url": provider.base_url,
            "prompts": [],
        }
        print(f"[direct] provider={provider.name} model={provider.model}")
        for prompt_case in prompts:
            prompt_result = await _run_direct_prompt(provider, prompt_case, runs=runs, timeout=timeout)
            provider_result["prompts"].append(prompt_result)
            non_stream_times = [item["total_seconds"] for item in prompt_result["non_stream"] if "total_seconds" in item and not item.get("error")]
            stream_first = [item["first_chunk_seconds"] for item in prompt_result["stream"] if item.get("first_chunk_seconds") is not None and not item.get("error")]
            stream_total = [item["total_seconds"] for item in prompt_result["stream"] if "total_seconds" in item and not item.get("error")]
            print(
                "  prompt={prompt} non_stream={non_stream} stream_first={first} stream_total={total}".format(
                    prompt=prompt_result["prompt"],
                    non_stream=_duration_stats(non_stream_times),
                    first=_duration_stats(stream_first),
                    total=_duration_stats(stream_total),
                )
            )
        results.append(provider_result)
    return results


def _load_cases(path: str) -> list[dict[str, Any]]:
    data = _load_json(path)
    if not isinstance(data, list):
        raise ValueError("cases file must be a JSON array")
    return data


def _case_steps(case: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in case.get("prompts") or []:
        if isinstance(item, str):
            steps.append({"prompt": item})
        elif isinstance(item, dict):
            steps.append(item)
        else:
            steps.append({"prompt": str(item)})
    return steps


def _case_session_ids(cases: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for case in cases:
        session_id = str(case.get("sessionId") or "")
        if not session_id or session_id in seen:
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


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _check_step_assertions(
    text: str,
    followups: list[dict[str, Any]],
    step: dict[str, Any],
    *,
    thinking: list[str] | None = None,
    final_seconds: float | None = None,
) -> list[str]:
    violations: list[str] = []
    lower_text = text.lower()
    lower_thinking = "\n".join(thinking or []).lower()
    for expected in step.get("assertContains") or []:
        if str(expected).lower() not in lower_text:
            violations.append(f"missing expected text: {expected}")
    contains_any = step.get("assertContainsAny") or []
    if contains_any and not any(str(item).lower() in lower_text for item in contains_any):
        violations.append(f"none of expected alternatives found: {contains_any}")
    for forbidden in step.get("assertNotContains") or []:
        if str(forbidden).lower() in lower_text:
            violations.append(f"contains forbidden text: {forbidden}")
    for expected in step.get("expectedKeyPoints") or []:
        if str(expected).lower() not in lower_text:
            violations.append(f"missing expected keypoint: {expected}")
    for group in step.get("expectedKeyPointGroups") or []:
        label = ""
        values: list[Any] = []
        if isinstance(group, dict):
            label = str(group.get("label") or "").strip()
            values = list(group.get("any") or group.get("values") or [])
        elif isinstance(group, list):
            values = group
        else:
            values = [group]
        normalized_values = [str(item).strip() for item in values if str(item).strip()]
        if not normalized_values:
            continue
        if not any(value.lower() in lower_text for value in normalized_values):
            display = label or " / ".join(normalized_values)
            violations.append(f"missing expected keypoint group: {display}")
    for forbidden in step.get("forbiddenPatterns") or []:
        if str(forbidden).lower() in lower_text:
            violations.append(f"contains forbidden pattern: {forbidden}")
    for expected in step.get("assertThinkingContains") or []:
        if str(expected).lower() not in lower_thinking:
            violations.append(f"missing expected thinking text: {expected}")
    thinking_any = step.get("assertThinkingContainsAny") or []
    if thinking_any and not any(str(item).lower() in lower_thinking for item in thinking_any):
        violations.append(f"none of expected thinking alternatives found: {thinking_any}")
    for forbidden in step.get("assertThinkingNotContains") or []:
        if str(forbidden).lower() in lower_thinking:
            violations.append(f"contains forbidden thinking text: {forbidden}")
    if step.get("assertNoFollowups") is True and followups:
        violations.append(f"expected no followups, got {len(followups)}")
    target = step.get("assertFollowupTarget")
    if target:
        found = any((item.get("content") or {}).get("targetView") == target for item in followups)
        if not found:
            violations.append(f"missing followup targetView: {target}")
    refresh = step.get("assertFollowupRefresh")
    if refresh is not None:
        found = any((item.get("content") or {}).get("refresh") == refresh for item in followups)
        if not found:
            violations.append(f"missing followup refresh: {refresh}")
    followup_count = step.get("assertFollowupCount")
    if followup_count is not None and len(followups) != int(followup_count):
        violations.append(f"expected {followup_count} followups, got {len(followups)}")
    max_elapsed = _as_float(step.get("maxElapsedSeconds"))
    if max_elapsed is not None and final_seconds is not None and final_seconds > max_elapsed:
        violations.append(f"exceeded max elapsed seconds: {final_seconds:.3f}s > {max_elapsed:.3f}s")
    return violations


def _check_step_warnings(final_seconds: float | None, step: dict[str, Any]) -> list[str]:
    warn_elapsed = _as_float(step.get("warnElapsedSeconds"))
    if warn_elapsed is not None and final_seconds is not None and final_seconds > warn_elapsed:
        return [f"exceeded warn elapsed seconds: {final_seconds:.3f}s > {warn_elapsed:.3f}s"]
    return []


def _check_step_quality_warnings(text: str, step: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    min_text_length = _as_float(step.get("minTextLengthWarn"))
    if min_text_length is not None and len(text.strip()) < int(min_text_length):
        warnings.append(f"reply may be too thin: {len(text.strip())} chars < {int(min_text_length)} chars")
    return warnings


def _followup_targets(followups: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for item in followups:
        content = item.get("content")
        if isinstance(content, dict) and content.get("targetView") is not None:
            targets.append(str(content["targetView"]))
    return targets


def _followup_refreshes(followups: list[dict[str, Any]]) -> list[bool]:
    refreshes: list[bool] = []
    for item in followups:
        content = item.get("content")
        if isinstance(content, dict) and isinstance(content.get("refresh"), bool):
            refreshes.append(bool(content["refresh"]))
    return refreshes


async def _ask_agent_once(
    agent_url: str,
    session_id: str,
    user_id: str,
    prompt: str,
    *,
    open_timeout: float,
    response_timeout: float,
) -> dict[str, Any]:
    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "content": prompt,
        "inputType": "text",
    }
    started = time.perf_counter()
    first_message_at: float | None = None
    final_at: float | None = None
    primary: list[dict[str, Any]] = []
    followups: list[dict[str, Any]] = []
    async with websockets.connect(agent_url, max_size=2**22, open_timeout=open_timeout) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=response_timeout)
            now = time.perf_counter()
            if first_message_at is None:
                first_message_at = now
            message = json.loads(raw)
            primary.append(message)
            if message.get("end") is True:
                final_at = now
                break
        terminal_error = any(item.get("type") == "error" and item.get("end") is True for item in primary)
        while not terminal_error:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except (asyncio.TimeoutError, TimeoutError):
                break
            followups.append(json.loads(raw))
    text = "\n".join(str(item.get("content", "")) for item in primary if item.get("type") == "text").strip()
    thinking = [str(item.get("content", "")) for item in primary if item.get("type") == "thinking"]
    error_messages = [
        str(item.get("content", "") or item.get("message", "")).strip()
        for item in primary
        if item.get("type") == "error"
    ]
    error_messages = [message for message in error_messages if message]
    error_text = "; ".join(error_messages)
    return {
        "first_message_seconds": round((first_message_at or final_at or time.perf_counter()) - started, 3),
        "final_seconds": round((final_at or time.perf_counter()) - started, 3),
        "thinking": thinking,
        "text": text,
        "text_length": len(text),
        "text_preview": text[:300],
        "primary_types": [item.get("type") for item in primary],
        "followup_count": len(followups),
        "followup_targets": _followup_targets(followups),
        "followup_refreshes": _followup_refreshes(followups),
        "followups": followups,
        "assertion_violations": [],
        **({"error": error_text or "agent returned error message"} if error_messages or any(item.get("type") == "error" for item in primary) else {}),
    }


async def _wait_for_agent_ready(url: str, timeout: float) -> None:
    parsed = urlsplit(url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    docs_url = f"{scheme}://{parsed.netloc}/docs"
    deadline = time.perf_counter() + timeout
    async with httpx.AsyncClient(timeout=3) as client:
        while time.perf_counter() < deadline:
            try:
                response = await client.get(docs_url)
                if response.status_code < 500:
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
    raise TimeoutError(f"agent did not become ready within {timeout}s: {docs_url}")


def _start_agent(
    provider: ProviderConfig,
    host: str,
    port: int,
    *,
    log_dir: str | None = None,
) -> tuple[subprocess.Popen[str], Path | None]:
    env = provider.agent_env()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    log_handle = None
    log_path: Path | None = None
    if log_dir:
        log_path = Path(log_dir) / f"model-provider-agent-{provider.name}-{port}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        stdout=log_handle or subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    if log_handle is not None:
        log_handle.close()
    return process, log_path


async def _run_agent_for_provider(
    provider: ProviderConfig,
    cases: list[dict[str, Any]],
    *,
    agent_url: str,
    user_id: str,
    runs: int,
    open_timeout: float,
    response_timeout: float,
    keep_response_text: bool,
    keep_followups: bool,
) -> dict[str, Any]:
    provider_result: dict[str, Any] = {
        "provider": provider.name,
        "model": provider.model,
        "agent_url": agent_url,
        "cases": [],
    }
    print(f"[agent] provider={provider.name} model={provider.model}")
    for run_index in range(runs):
        for case in cases:
            case_name = str(case.get("name") or f"session-{case.get('sessionId')}")
            session_id = str(case["sessionId"])
            case_record = {"run": run_index + 1, "name": case_name, "sessionId": session_id, "steps": []}
            for step in _case_steps(case):
                prompt = str(step.get("prompt") or step.get("text") or "")
                step_record: dict[str, Any] = {"prompt": prompt}
                try:
                    measured = await _ask_agent_once(
                        agent_url,
                        session_id,
                        user_id,
                        prompt,
                        open_timeout=open_timeout,
                        response_timeout=response_timeout,
                    )
                    measured["assertion_violations"] = _check_step_assertions(
                        str(measured.get("text") or ""),
                        list(measured.get("followups") or []),
                        step,
                        thinking=list(measured.get("thinking") or []),
                        final_seconds=float(measured.get("final_seconds") or 0),
                    )
                    measured["latency_warnings"] = _check_step_warnings(
                        float(measured.get("final_seconds") or 0),
                        step,
                    )
                    measured["quality_warnings"] = _check_step_quality_warnings(
                        str(measured.get("text") or ""),
                        step,
                    )
                    if not keep_response_text and not step.get("keepFullText"):
                        measured.pop("text", None)
                    if not keep_followups and not step.get("keepFollowups"):
                        measured.pop("followups", None)
                    step_record.update(measured)
                except Exception as exc:
                    step_record.update({"error": f"{type(exc).__name__}: {exc}"})
                case_record["steps"].append(step_record)
                if "error" in step_record:
                    print(f"  {case_name} prompt={prompt} error={step_record['error']}")
                else:
                    print(
                        f"  {case_name} prompt={prompt} first={step_record['first_message_seconds']}s "
                        f"final={step_record['final_seconds']}s text_len={step_record['text_length']}"
                    )
            provider_result["cases"].append(case_record)
    return provider_result


async def run_agent_benchmark(
    providers: list[ProviderConfig],
    cases_path: str,
    *,
    start_agent: bool,
    agent_host: str,
    agent_port: int,
    agent_log_dir: str | None,
    agent_url: str | None,
    user_id: str,
    runs: int,
    open_timeout: float,
    response_timeout: float,
    startup_timeout: float,
    keep_response_text: bool,
    keep_followups: bool,
    clear_history: bool,
    history_db: str,
) -> list[dict[str, Any]]:
    cases = _load_cases(cases_path)
    session_ids = _case_session_ids(cases)
    results: list[dict[str, Any]] = []
    for provider in providers:
        process: subprocess.Popen[str] | None = None
        log_path: Path | None = None
        provider_agent_url = agent_url or f"ws://127.0.0.1:{agent_port}{DEFAULT_WS_PATH}"
        try:
            if clear_history:
                deleted = _clear_history(Path(history_db), session_ids)
                print(
                    "[agent] cleared history provider={provider} db={db} sessions={sessions} deleted={deleted}".format(
                        provider=provider.name,
                        db=history_db,
                        sessions=",".join(session_ids),
                        deleted=deleted,
                    )
                )
            if start_agent:
                process, log_path = _start_agent(provider, agent_host, agent_port, log_dir=agent_log_dir)
                try:
                    await _wait_for_agent_ready(provider_agent_url, startup_timeout)
                except Exception:
                    if log_path and log_path.exists():
                        print(f"[agent-startup-log] provider={provider.name} log={log_path}")
                        print(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
                    raise
            result = await _run_agent_for_provider(
                provider,
                cases,
                agent_url=provider_agent_url,
                user_id=user_id,
                runs=runs,
                open_timeout=open_timeout,
                response_timeout=response_timeout,
                keep_response_text=keep_response_text,
                keep_followups=keep_followups,
            )
            results.append(result)
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return results


def _summarize_agent(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for provider_result in results:
        first_times: list[float] = []
        final_times: list[float] = []
        text_lengths: list[float] = []
        errors = 0
        assertion_failures = 0
        latency_warnings = 0
        quality_warnings = 0
        steps = 0
        for case in provider_result.get("cases", []):
            for step in case.get("steps", []):
                steps += 1
                if step.get("error"):
                    errors += 1
                    continue
                if isinstance(step.get("first_message_seconds"), (int, float)):
                    first_times.append(float(step["first_message_seconds"]))
                if isinstance(step.get("final_seconds"), (int, float)):
                    final_times.append(float(step["final_seconds"]))
                if isinstance(step.get("text_length"), (int, float)):
                    text_lengths.append(float(step["text_length"]))
                if step.get("assertion_violations"):
                    assertion_failures += 1
                if step.get("latency_warnings"):
                    latency_warnings += 1
                if step.get("quality_warnings"):
                    quality_warnings += 1
        valid_steps = max(steps - errors, 0)
        quality_gate_passed = max(valid_steps - assertion_failures, 0)
        summaries.append(
            {
                "provider": provider_result.get("provider"),
                "model": provider_result.get("model"),
                "steps": steps,
                "errors": errors,
                "assertion_failures": assertion_failures,
                "latency_warnings": latency_warnings,
                "quality_warnings": quality_warnings,
                "quality_gate_pass_rate": round(quality_gate_passed / valid_steps, 3) if valid_steps else None,
                "first_message_seconds": _duration_stats(first_times),
                "final_seconds": _duration_stats(final_times),
                "text_length": _duration_stats(text_lengths),
            }
        )
    return summaries


def _write_results(path: str | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


async def async_main(args: argparse.Namespace) -> None:
    providers, direct_prompts = _load_config(args.config)
    providers = _select_providers(providers, args.provider)
    output: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "providers": [provider.name for provider in providers],
        "active_providers": [provider.name for provider in providers],
        "provider_precheck": None,
        "direct": None,
        "agent": None,
        "agent_summary": None,
    }
    if not args.skip_precheck:
        prechecks = await run_provider_prechecks(
            providers,
            timeout=args.precheck_timeout,
        )
        output["provider_precheck"] = prechecks
        if args.skip_unavailable_providers:
            providers = _filter_prechecked_providers(providers, prechecks)
            output["active_providers"] = [provider.name for provider in providers]
            if not providers:
                _write_results(args.output, output)
                return
    if not args.agent_only:
        output["direct"] = await run_direct_benchmark(
            providers,
            direct_prompts,
            runs=args.direct_runs,
            timeout=args.direct_timeout,
        )
    if not args.direct_only:
        agent_results = await run_agent_benchmark(
            providers,
            args.cases,
            start_agent=args.start_agent,
            agent_host=args.agent_host,
            agent_port=args.agent_port,
            agent_log_dir=args.agent_log_dir,
            agent_url=args.agent_url,
            user_id=args.user_id,
            runs=args.agent_runs,
            open_timeout=args.open_timeout,
            response_timeout=args.response_timeout,
            startup_timeout=args.startup_timeout,
            keep_response_text=args.keep_response_text,
            keep_followups=args.keep_followups,
            clear_history=args.clear_history,
            history_db=args.history_db,
        )
        output["agent"] = agent_results
        output["agent_summary"] = _summarize_agent(agent_results)
    _write_results(args.output, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark model providers for direct API and agent scenarios.")
    parser.add_argument("--config", required=True, help="provider config JSON")
    parser.add_argument("--provider", action="append", help="provider name to run; can be repeated")
    parser.add_argument("--output", help="write JSON results to this path")
    parser.add_argument("--direct-only", action="store_true", help="only run direct model API benchmark")
    parser.add_argument("--agent-only", action="store_true", help="only run agent scenario benchmark")
    parser.add_argument("--skip-precheck", action="store_true", help="skip provider availability precheck")
    parser.add_argument("--precheck-timeout", type=float, default=30)
    parser.add_argument(
        "--skip-unavailable-providers",
        action="store_true",
        help="after precheck, exclude providers whose direct smoke is unavailable from direct/agent quality runs",
    )
    parser.add_argument("--direct-runs", type=int, default=DEFAULT_DIRECT_RUNS)
    parser.add_argument("--direct-timeout", type=float, default=90)
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--agent-runs", type=int, default=DEFAULT_AGENT_RUNS)
    parser.add_argument("--agent-url", help="existing compat websocket URL; ignored when --start-agent uses --agent-port")
    parser.add_argument("--start-agent", action="store_true", help="start one temporary agent process for each provider")
    parser.add_argument("--agent-host", default="127.0.0.1", help="host used by --start-agent")
    parser.add_argument("--agent-port", type=int, default=8100)
    parser.add_argument("--agent-log-dir", default="/private/tmp", help="write temporary agent startup logs here when --start-agent is used")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--open-timeout", type=float, default=30)
    parser.add_argument("--response-timeout", type=float, default=120)
    parser.add_argument("--startup-timeout", type=float, default=45)
    parser.add_argument("--keep-response-text", action="store_true", help="keep full agent replies in output JSON")
    parser.add_argument("--keep-followups", action="store_true", help="keep full followup messages in output JSON")
    parser.add_argument("--clear-history", action="store_true", help="clear local agent chat history for case sessions before each provider")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB), help="local agent SQLite history DB")
    args = parser.parse_args()
    if args.direct_only and args.agent_only:
        raise SystemExit("--direct-only and --agent-only cannot be used together")
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
