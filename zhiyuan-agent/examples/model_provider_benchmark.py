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


def _check_step_assertions(text: str, followups: list[dict[str, Any]], step: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    lower_text = text.lower()
    for expected in step.get("assertContains") or []:
        if str(expected).lower() not in lower_text:
            violations.append(f"missing expected text: {expected}")
    contains_any = step.get("assertContainsAny") or []
    if contains_any and not any(str(item).lower() in lower_text for item in contains_any):
        violations.append(f"none of expected alternatives found: {contains_any}")
    for forbidden in step.get("assertNotContains") or []:
        if str(forbidden).lower() in lower_text:
            violations.append(f"contains forbidden text: {forbidden}")
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
    return violations


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
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            followups.append(json.loads(raw))
    text = "\n".join(str(item.get("content", "")) for item in primary if item.get("type") == "text").strip()
    thinking = [str(item.get("content", "")) for item in primary if item.get("type") == "thinking"]
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


def _start_agent(provider: ProviderConfig, port: int) -> subprocess.Popen[str]:
    env = provider.agent_env()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.server:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    return subprocess.Popen(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


async def _run_agent_for_provider(
    provider: ProviderConfig,
    cases: list[dict[str, Any]],
    *,
    agent_url: str,
    user_id: str,
    runs: int,
    open_timeout: float,
    response_timeout: float,
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
                    )
                    if not step.get("keepFullText"):
                        measured.pop("text", None)
                    if not step.get("keepFollowups"):
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
    agent_port: int,
    agent_url: str | None,
    user_id: str,
    runs: int,
    open_timeout: float,
    response_timeout: float,
    startup_timeout: float,
) -> list[dict[str, Any]]:
    cases = _load_cases(cases_path)
    results: list[dict[str, Any]] = []
    for provider in providers:
        process: subprocess.Popen[str] | None = None
        provider_agent_url = agent_url or f"ws://127.0.0.1:{agent_port}{DEFAULT_WS_PATH}"
        try:
            if start_agent:
                process = _start_agent(provider, agent_port)
                await _wait_for_agent_ready(provider_agent_url, startup_timeout)
            result = await _run_agent_for_provider(
                provider,
                cases,
                agent_url=provider_agent_url,
                user_id=user_id,
                runs=runs,
                open_timeout=open_timeout,
                response_timeout=response_timeout,
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
        errors = 0
        assertion_failures = 0
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
                if step.get("assertion_violations"):
                    assertion_failures += 1
        summaries.append(
            {
                "provider": provider_result.get("provider"),
                "model": provider_result.get("model"),
                "steps": steps,
                "errors": errors,
                "assertion_failures": assertion_failures,
                "first_message_seconds": _duration_stats(first_times),
                "final_seconds": _duration_stats(final_times),
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
        "direct": None,
        "agent": None,
        "agent_summary": None,
    }
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
            agent_port=args.agent_port,
            agent_url=args.agent_url,
            user_id=args.user_id,
            runs=args.agent_runs,
            open_timeout=args.open_timeout,
            response_timeout=args.response_timeout,
            startup_timeout=args.startup_timeout,
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
    parser.add_argument("--direct-runs", type=int, default=DEFAULT_DIRECT_RUNS)
    parser.add_argument("--direct-timeout", type=float, default=90)
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--agent-runs", type=int, default=DEFAULT_AGENT_RUNS)
    parser.add_argument("--agent-url", help="existing compat websocket URL; ignored when --start-agent uses --agent-port")
    parser.add_argument("--start-agent", action="store_true", help="start one temporary agent process for each provider")
    parser.add_argument("--agent-port", type=int, default=8100)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--open-timeout", type=float, default=30)
    parser.add_argument("--response-timeout", type=float, default=120)
    parser.add_argument("--startup-timeout", type=float, default=45)
    args = parser.parse_args()
    if args.direct_only and args.agent_only:
        raise SystemExit("--direct-only and --agent-only cannot be used together")
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
