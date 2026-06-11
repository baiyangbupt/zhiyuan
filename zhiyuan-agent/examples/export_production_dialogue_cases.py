#!/usr/bin/env python3
"""Export production-visible chat messages into dialog regression case drafts.

The script is intentionally read-only. It pulls frontend-visible messages from
the backend message API, redacts obvious personal data, and writes reviewable
case definitions that are compatible with dialog_regression_runner.py.

Typical usage:
  python examples/export_production_dialogue_cases.py \
    --base-url http://127.0.0.1:8090 \
    --sessions 2752 2936 \
    --output examples/production_dialogue_case_candidates.json

  python examples/export_production_dialogue_cases.py \
    --base-url http://127.0.0.1:8090 \
    --discover-sessions --max-sessions 50 \
    --output /tmp/production-dialogue-cases.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "http://127.0.0.1:8090"
DEFAULT_TENANT_ID = "1"
DEFAULT_OUTPUT = "examples/production_dialogue_case_candidates.json"

STRUCTURED_CONTENT_TYPES = {"CARD"}
USER_MESSAGE_FROM_VALUES = {"1", "USER", "user", "student", "STUDENT"}

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
UUID_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LONG_NUMBER_RE = re.compile(r"(?<![\d.])\d{7,}(?![\d.])")
SCORE_RE = re.compile(r"(?<!\d)([3-6]\d{2}|7[0-5]\d)(?:\s*分)(?!\d)")
RANK_RE = re.compile(r"(?<!\d)\d{4,6}\s*(?:名|位|位次|排名)(?!\d)")
SESSION_ID_RE = re.compile(r"(?:session_id=|sessionId[=:]\s*[\"']?)(\d+)")


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (OSError, error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed: {method} {url}: {exc}") from exc
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json response: {method} {url}: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"unexpected response type: {method} {url}: {type(parsed).__name__}")
    return parsed


def _api_data(response: dict[str, Any], *, context: str) -> Any:
    if int(response.get("code", 0) or 0) != 0:
        raise RuntimeError(f"{context} failed: code={response.get('code')} msg={response.get('msg')}")
    return response.get("data")


def _read_session_ids(path: str | None) -> list[str]:
    if not path:
        return []
    text = Path(path).read_text(encoding="utf-8")
    ids: list[str] = []
    for token in re.split(r"[\s,，]+", text):
        token = token.strip()
        if token:
            ids.append(token)
    return ids


def _session_ids_from_log_text(text: str) -> list[str]:
    return [match.group(1) for match in SESSION_ID_RE.finditer(text or "")]


def _read_session_ids_from_log(path: str | None) -> list[str]:
    if not path:
        return []
    return _session_ids_from_log_text(Path(path).read_text(encoding="utf-8", errors="ignore"))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def discover_recent_sessions(
    base_url: str,
    tenant_id: str,
    *,
    page_size: int,
    max_sessions: int,
) -> list[str]:
    """Discover recent sessions through the existing session page API."""
    result: list[str] = []
    page = 1
    base = base_url.rstrip("/")
    while len(result) < max_sessions:
        url = f"{base}/gaotu-assistant-bot/chat/{tenant_id}/session/page"
        payload = {
            "page": page,
            "pageSize": min(page_size, max_sessions - len(result)),
            "orderBy": [{"asc": False, "column": "id"}],
        }
        data = _api_data(_request_json("POST", url, payload=payload), context="session page")
        if not isinstance(data, dict):
            break
        records = data.get("records") or []
        if not isinstance(records, list) or not records:
            break
        for item in records:
            if isinstance(item, dict) and item.get("id") is not None:
                result.append(str(item.get("id")))
                if len(result) >= max_sessions:
                    break
        total = int(data.get("total") or 0)
        if total and len(result) >= total:
            break
        page += 1
    return _dedupe(result)


def fetch_messages(base_url: str, tenant_id: str, session_id: str) -> list[dict[str, Any]]:
    base = base_url.rstrip("/")
    query = parse.urlencode({"chatSessionId": session_id})
    url = f"{base}/gaotu-assistant-bot/inner/chat/{tenant_id}/message/list-all?{query}"
    data = _api_data(_request_json("GET", url), context=f"message list session={session_id}")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        text = content
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except Exception:
                return text
            return _stringify_content(parsed)
        return text
    if isinstance(content, dict):
        parts: list[str] = []
        for key in ("title", "summary", "content", "message", "text", "impact", "actionText"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        return "\n".join(dict.fromkeys(parts))
    if isinstance(content, list):
        return "\n".join(_stringify_content(item) for item in content)
    return str(content)


def _is_user_message(message: dict[str, Any]) -> bool:
    value = str(message.get("messageFrom") or "").strip()
    return value in USER_MESSAGE_FROM_VALUES


def _redact(text: str) -> str:
    result = str(text or "")
    result = JWT_RE.sub("[TOKEN]", result)
    result = UUID_TOKEN_RE.sub("[TOKEN]", result)
    result = PHONE_RE.sub("[手机号]", result)
    result = SCORE_RE.sub("[分数]", result)
    result = RANK_RE.sub("[位次]", result)
    result = LONG_NUMBER_RE.sub("[数字ID]", result)
    result = re.sub(r"(我叫|我是|孩子叫|学生叫|姓名[:：]?)[\u4e00-\u9fa5A-Za-z]{2,8}", r"\1[姓名]", result)
    return re.sub(r"\s+", " ", result).strip()


def extract_user_prompts(messages: list[dict[str, Any]]) -> list[str]:
    prompts: list[str] = []
    for message in messages:
        if not _is_user_message(message):
            continue
        content_type = str(message.get("contentType") or "").strip()
        if content_type in STRUCTURED_CONTENT_TYPES:
            continue
        text = _redact(_stringify_content(message.get("content")))
        if not text:
            continue
        if text.lower() in {"ping", "pong"}:
            continue
        prompts.append(text)
    return prompts


def _classify_prompt(prompt: str) -> list[str]:
    text = prompt
    coverage: list[str] = ["production_dialogue_source"]
    if any(word in text for word in ("方案", "志愿", "冲", "稳", "保", "排序", "审查", "删除", "移除", "保留")):
        coverage.append("plan")
    if any(word in text for word in ("专业", "临床", "计算机", "医学", "法学", "电气", "会计", "土木")):
        coverage.append("major_preference")
    if any(word in text for word in ("北京", "上海", "广东", "城市", "省", "地区", "地域")):
        coverage.append("region_preference")
    if any(word in text for word in ("就业", "体制", "考公", "稳定", "职业", "工作")):
        coverage.append("career_direction")
    if any(word in text for word in ("学费", "贵", "中外", "预算", "钱")):
        coverage.append("budget_tuition")
    if any(word in text for word in ("不要", "不去", "排除", "只要", "只看", "只保留", "仅保留", "必须")):
        coverage.append("hard_constraint")
    if any(word in text for word in ("确认", "好的", "可以", "执行", "采纳")):
        coverage.append("confirmation_followup")
    return _dedupe(coverage)


def build_case(session_id: str, messages: list[dict[str, Any]], *, max_prompts: int) -> dict[str, Any] | None:
    prompts = extract_user_prompts(messages)
    if not prompts:
        return None
    prompts = prompts[:max_prompts]
    coverage: list[str] = []
    for prompt in prompts:
        coverage.extend(_classify_prompt(prompt))
    prompt_items = [
        {
            "prompt": prompt,
            "qualityFocus": ["real_user_language", "actionable_next_step"],
            "minTextLengthWarn": 80,
        }
        for prompt in prompts
    ]
    return {
        "name": f"prod-dialogue-session-{session_id}",
        "sessionId": str(session_id),
        "sourceSessionId": str(session_id),
        "source": "production_message_list",
        "needsReview": True,
        "flow": ["production_dialogue"],
        "coverage": _dedupe(coverage),
        "prompts": prompt_items,
    }


def write_cases(cases: list[dict[str, Any]], output: str, *, base_url: str, tenant_id: str) -> None:
    payload = {
        "metadata": {
            "release": "3.1.0",
            "purpose": "Draft cases exported from production-visible dialogue messages for manual review.",
            "source": "backend /inner/chat/{tenantId}/message/list-all",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "baseUrl": base_url,
            "tenantId": tenant_id,
            "privacy": "Prompts are automatically redacted and must be manually reviewed before promotion to stable regression sets.",
        },
        "defaults": {
            "coverage": ["production_dialogue_candidate", "needs_manual_review"],
            "assertPlanStyle": True,
            "promptDefaults": {
                "assertNotContains": ["payload", "action_family", "volunteerId"],
                "assertThinkingNotContains": ["payload", "action_family", "volunteerId"],
                "forbiddenPatterns": ["已直接删除", "已直接调整", "payload", "action_family"],
                "warnElapsedSeconds": 45,
                "maxElapsedSeconds": 100,
            },
        },
        "cases": cases,
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL.")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--sessions", nargs="*", default=[], help="Explicit chat session IDs.")
    parser.add_argument("--sessions-file", help="Text file with session IDs separated by whitespace or commas.")
    parser.add_argument("--sessions-log-file", help="Agent/server log file; session ids are parsed from session_id=... or sessionId=....")
    parser.add_argument("--sessions-from-stdin", action="store_true", help="Read agent/server logs from stdin and parse session ids.")
    parser.add_argument("--discover-sessions", action="store_true", help="Discover recent sessions through /session/page; may require authenticated gateway access.")
    parser.add_argument("--max-sessions", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-prompts-per-session", type=int, default=8)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    session_ids = _dedupe([
        *args.sessions,
        *_read_session_ids(args.sessions_file),
        *_read_session_ids_from_log(args.sessions_log_file),
    ])
    if args.sessions_from_stdin:
        session_ids = _dedupe([*session_ids, *_session_ids_from_log_text(sys.stdin.read())])
    if args.discover_sessions:
        try:
            discovered = discover_recent_sessions(
                args.base_url,
                args.tenant_id,
                page_size=max(1, args.page_size),
                max_sessions=max(1, args.max_sessions),
            )
        except Exception as exc:
            print(f"warning: session discovery failed: {exc}", file=sys.stderr)
            discovered = []
        session_ids = _dedupe([*session_ids, *discovered])
    if not session_ids:
        raise SystemExit("no sessions provided; use --sessions, --sessions-file, --sessions-log-file, --sessions-from-stdin, or --discover-sessions")

    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    for session_id in session_ids[: max(1, args.max_sessions)]:
        try:
            messages = fetch_messages(args.base_url, args.tenant_id, session_id)
            case = build_case(session_id, messages, max_prompts=max(1, args.max_prompts_per_session))
        except Exception as exc:
            failures.append(f"{session_id}: {exc}")
            continue
        if case:
            cases.append(case)

    write_cases(cases, args.output, base_url=args.base_url, tenant_id=args.tenant_id)
    print(f"wrote {len(cases)} cases to {args.output}")
    if failures:
        print("failed sessions:", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
    return 0 if cases else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
