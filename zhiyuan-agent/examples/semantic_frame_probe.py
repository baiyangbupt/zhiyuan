#!/usr/bin/env python3
"""Run SemanticIntentRouter directly for case prompts.

This probe is intentionally scoped to L2 semantic routing.  It does not run the
full ChatAgent, call planning tools, or generate user-facing replies.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

from app.agent.context import RequestContext
from app.config import LLMConfig, SemanticRouterConfig
from app.llm.client import LLMClient
from app.resolver.semantic_intent_router import SemanticIntentRouter


RUNNER_PATH = Path(__file__).with_name("dialog_regression_runner.py")
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner_for_semantic_probe", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load dialog_regression_runner from {RUNNER_PATH}")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _load_cases(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return runner._expand_case_payload(data)


def _flatten_case_prompts(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        prompts = case.get("prompts") or []
        for step_index, step in enumerate(prompts, start=1):
            if not isinstance(step, dict):
                step = {"prompt": str(step)}
            rows.append(
                {
                    "case": case.get("name"),
                    "sessionId": str(case.get("sessionId") or ""),
                    "stepIndex": step_index,
                    "prompt": str(step.get("prompt") or ""),
                    "flow": list(case.get("flow") or []),
                    "coverage": list(case.get("coverage") or []),
                    "expectedRoutingPath": step.get("expectedRoutingPath"),
                    "expectedActionFamily": step.get("expectedActionFamily"),
                    "expectedNoAction": bool(step.get("expectedNoAction")),
                }
            )
    return rows


def _limit_rows(rows: list[dict[str, Any]], *, limit: int = 0, coverage: list[str] | None = None) -> list[dict[str, Any]]:
    filtered = rows
    if coverage:
        required = set(coverage)
        filtered = [
            row for row in filtered
            if required & set(row.get("coverage") or [])
        ]
    if limit > 0:
        filtered = filtered[:limit]
    return filtered


def _build_router(
    *,
    timeout_seconds: float,
    model_name: str = "",
    base_url: str = "",
    api_key: str = "",
    enable_thinking: bool | None = None,
) -> SemanticIntentRouter:
    llm_config = LLMConfig()
    router_config = SemanticRouterConfig(
        _env_file=None,
        enabled=True,
        blocking=True,
        timeout_seconds=timeout_seconds,
        llm_provider="openai_compatible" if (model_name or base_url or api_key) else None,
        llm_model_name=model_name,
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_enable_thinking=enable_thinking,
    )
    return SemanticIntentRouter(LLMClient(llm_config), router_config)


async def _probe_row(router: SemanticIntentRouter, row: dict[str, Any]) -> dict[str, Any]:
    context = RequestContext(
        userid="semantic-frame-probe",
        sessionid=str(row.get("sessionId") or ""),
    )
    shadow = await router.route_shadow(
        str(row.get("prompt") or ""),
        request_context=context,
        active_pending=None,
    )
    return {
        **row,
        "responseText": "",
        "turnObservability": {
            "semanticRouterShadow": shadow.event_payload(),
        },
    }


async def run_probe(
    *,
    cases_path: str,
    limit: int = 0,
    coverage: list[str] | None = None,
    timeout_seconds: float = 10.0,
    model_name: str = "",
    base_url: str = "",
    api_key: str = "",
    enable_thinking: bool | None = None,
) -> dict[str, Any]:
    rows = _limit_rows(
        _flatten_case_prompts(_load_cases(cases_path)),
        limit=limit,
        coverage=coverage,
    )
    router = _build_router(
        timeout_seconds=timeout_seconds,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        enable_thinking=enable_thinking,
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(await _probe_row(router, row))
    return {
        "probe": {
            "cases": cases_path,
            "limit": limit,
            "coverage": coverage or [],
            "timeoutSeconds": timeout_seconds,
            "timeoutMode": "disabled" if timeout_seconds <= 0 else "bounded",
            "modelName": model_name or "main-llm",
        },
        "records": records,
    }


def _parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool value: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe SemanticIntentRouter frames for dialog case prompts.")
    parser.add_argument("--cases", required=True, help="case definition JSON")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--coverage", action="append", default=[], help="only include cases with this coverage tag; can repeat")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="set <= 0 to disable timeout and record actual latency")
    parser.add_argument("--model-name", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--enable-thinking", type=_parse_bool, default=None)
    parser.add_argument("--output", help="write JSON probe records to this path")
    args = parser.parse_args()

    payload = asyncio.run(
        run_probe(
            cases_path=args.cases,
            limit=args.limit,
            coverage=args.coverage,
            timeout_seconds=args.timeout_seconds,
            model_name=args.model_name,
            base_url=args.base_url,
            api_key=args.api_key,
            enable_thinking=args.enable_thinking,
        )
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
