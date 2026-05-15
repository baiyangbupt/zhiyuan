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
import time
from pathlib import Path
from typing import Any

import websockets

DEFAULT_URL = "ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do"
DEFAULT_USER_ID = "dialog-regression-user"

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
]

PLAN_STYLE_BANNED_EXACT_LINES = {"你。", "只有。", "请。"}


async def _ask_once(
    url: str,
    session_id: str,
    user_id: str,
    prompt: str,
    *,
    open_timeout: float = 30,
    response_timeout: float = 120,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "content": prompt,
        "inputType": "text",
    }
    async with websockets.connect(url, max_size=2**22, open_timeout=open_timeout) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        primary: list[dict[str, Any]] = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=response_timeout)
            message = json.loads(raw)
            primary.append(message)
            if message.get("end") is True:
                break

        followups: list[dict[str, Any]] = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            followups.append(json.loads(raw))

    return primary, followups


def _load_cases(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return DEFAULT_CASES
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("cases file must be a JSON array")
    return data


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
) -> list[str]:
    """Check per-prompt content assertions from the case step definition."""
    violations: list[str] = []
    prompt_label = step.get("prompt") or step.get("text") or ""
    assert_contains = step.get("assertContains") or []
    assert_contains_any = step.get("assertContainsAny") or []
    assert_not_contains = step.get("assertNotContains") or []
    assert_followup_target = step.get("assertFollowupTarget")
    assert_followup_refresh = step.get("assertFollowupRefresh")

    combined_text = text.lower()
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
    return violations


async def _run_cases(
    url: str,
    user_id: str,
    cases: list[dict[str, Any]],
    *,
    assert_plan_style: bool = False,
    open_timeout: float = 30,
    response_timeout: float = 120,
) -> None:
    failures: list[str] = []
    for case in cases:
        name = str(case.get("name") or f"session-{case.get('sessionId')}")
        session_id = str(case["sessionId"])
        case_assert_style = bool(case.get("assertPlanStyle", assert_plan_style))
        print(f"=== CASE {name} session={session_id} ===")

        raw_prompts = list(case.get("prompts") or [])
        steps: list[dict[str, Any]] = []
        for item in raw_prompts:
            if isinstance(item, str):
                steps.append({"prompt": item})
            elif isinstance(item, dict):
                steps.append(item)
            else:
                steps.append({"prompt": str(item)})

        for step in steps:
            prompt = str(step.get("prompt") or step.get("text") or "")
            print(f">>> {prompt}")
            started_at = time.perf_counter()
            try:
                primary, followups = await _ask_once(
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
                print(f"error={type(exc).__name__}: {exc} elapsedMs={elapsed_ms}")
                continue
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            print(
                "metrics="
                + json.dumps(
                    {
                        "elapsedMs": elapsed_ms,
                        "primaryMessages": len(primary),
                        "followupMessages": len(followups),
                    },
                    ensure_ascii=False,
                )
            )
            print(_summarize_primary(primary))
            text = _extract_text(primary)
            if case_assert_style:
                violations = _check_plan_reply_style(text)
                if violations:
                    failures.append(f"{name} session={session_id} prompt={prompt}: {'; '.join(violations)}")
            content_violations = _check_content_assertions(text, followups, step, name, session_id)
            if content_violations:
                for v in content_violations:
                    print(f"  CONTENT_ASSERT_FAIL: {v}")
                failures.extend(content_violations)
            if followups:
                print("followups=" + json.dumps(followups, ensure_ascii=False))
        print()
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
    args = parser.parse_args()

    if args.session:
        prompts = args.prompts or ["方案有了么"]
        cases = [{"name": "ad-hoc", "sessionId": args.session, "prompts": prompts}]
    else:
        cases = _load_cases(args.cases)

    asyncio.run(
        _run_cases(
            args.url,
            args.user_id,
            cases,
            assert_plan_style=args.assert_plan_style,
            open_timeout=args.open_timeout,
            response_timeout=args.response_timeout,
        )
    )


if __name__ == "__main__":
    main()
