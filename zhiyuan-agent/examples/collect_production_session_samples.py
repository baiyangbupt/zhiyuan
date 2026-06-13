#!/usr/bin/env python3
"""Collect read-only production session samples for simulation/test datasets.

The script is intentionally read-only:
- one MySQL SELECT discovers recent sessions and user base fields;
- internal GET endpoints fetch frontend-visible messages, userScoreDetail, and
  workspace-state;
- workspace-state is summarized locally to avoid exporting full candidate pools.

Typical production usage:
  python examples/collect_production_session_samples.py \
    --config-path /apps/zhiyuan-server-prod/application-online.yml \
    --limit 100 \
    --scan-limit 300 \
    --gzip

Copy to a test host after verification:
  scp /tmp/zhiyuan-production-sample-100-YYYYMMDD-HHMMSS.json.gz root@10.218.4.10:/tmp/
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8090"
DEFAULT_TENANT_ID = 1
DEFAULT_CONFIG_PATH = "/apps/zhiyuan-server-prod/application-online.yml"
DEFAULT_DB_HOST = "prod-hl-dayi-prod.rwlb.rds.aliyuncs.com"
DEFAULT_DB_PORT = "3306"
DEFAULT_DB_USER = "hl_zhiyuan_rw"
DEFAULT_DB_NAME = "hl_zhiyuan"
DEFAULT_OUTPUT_DIR = "/tmp"

SENSITIVE_KEYS = {
    "mobile",
    "phone",
    "telephone",
    "idCard",
    "id_card",
    "cardNo",
    "token",
    "loginToken",
    "avatarUrl",
    "avatar_url",
    "openId",
    "unionId",
    "password",
    "passwordHash",
}
MESSAGE_KEEP_KEYS = [
    "id",
    "chatSessionId",
    "messageFrom",
    "messageFromUserName",
    "contentType",
    "content",
    "feedback",
    "displayTime",
    "createTime",
    "updateTime",
]
USER_SCORE_KEYS = [
    "province",
    "examYear",
    "subjectType",
    "subjectList",
    "subjectScoreList",
    "batch",
    "totalScore",
    "totalScorePos",
    "prepareType",
    "volunteerModel",
    "volunteerDetailModel",
    "volunteerCount",
    "strategyType",
    "preferredMajors",
    "unacceptableMajors",
    "preferredRegions",
    "tuitionRange",
    "filterType",
    "specialPlan",
    "minority",
    "sex",
    "colorSituation",
    "colorSistuation",
    "bonusPolicy",
    "bonusScore",
    "acceptForeignSchool",
    "strengthSubjectList",
]
ITEM_KEEP_KEYS = [
    "volunteerId",
    "unitId",
    "planSchoolDataId",
    "schoolId",
    "schoolUnitCode",
    "schoolName",
    "provinceName",
    "cityName",
    "schoolLevel",
    "schoolNature",
    "schoolCategory",
    "schoolRank",
    "majorId",
    "majorName",
    "majorCode",
    "tier",
    "admissionRatio",
    "rankInTier",
    "position",
    "selected",
    "safetyMajor",
    "tuitionPerYear",
    "finalScore",
    "intentScore",
]

MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{80,}\b")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def _env_or_default(name: str, default: str) -> str:
    return os.environ.get(name) or default


def read_db_password(path: str) -> str:
    env_password = os.environ.get("ZHIYUAN_SAMPLE_DB_PASSWORD") or os.environ.get("MYSQL_PWD")
    if env_password:
        return env_password
    config_path = Path(path)
    if not config_path.exists():
        raise RuntimeError(
            f"DB password not found. Set ZHIYUAN_SAMPLE_DB_PASSWORD or provide --config-path; missing {path}"
        )
    for line in config_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*password:\s*(\S+)\s*$", line)
        if match:
            return match.group(1)
    raise RuntimeError(f"password not found in {path}")


def mysql_query(sql: str, *, args: argparse.Namespace, password: str) -> str:
    cmd = [
        "mysql",
        "-h",
        args.db_host,
        "-P",
        str(args.db_port),
        "-u",
        args.db_user,
        f"-D{args.db_name}",
        "--batch",
        "--raw",
        "--skip-column-names",
        "--default-character-set=utf8mb4",
        "-e",
        sql,
    ]
    env = os.environ.copy()
    env["MYSQL_PWD"] = password
    proc = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"mysql query failed: {proc.stderr.strip()}")
    return proc.stdout


def parse_tsv(stdout: str, columns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.reader(stdout.splitlines(), delimiter="\t"):
        if not row:
            continue
        item: dict[str, Any] = {}
        for index, col in enumerate(columns):
            item[col] = row[index] if index < len(row) and row[index] != "NULL" else None
        rows.append(item)
    return rows


def fetch_json(base_url: str, path: str, params: dict[str, Any] | None = None, *, timeout: float = 20) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"_error": str(exc), "_url": url}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - preserve raw diagnostics for ops use.
        return {
            "_error": f"json decode failed: {exc}",
            "_rawPrefix": body[:200].decode("utf-8", errors="replace"),
            "_url": url,
        }
    if not isinstance(parsed, dict):
        return {"_error": f"unexpected response type: {type(parsed).__name__}", "_url": url}
    return parsed


def redact_value(value: Any, key: str | None = None) -> Any:
    if key and key in SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_value(v, k) for k, v in value.items() if k not in {"avatarUrl", "avatar_url"}}
    if isinstance(value, list):
        return [redact_value(v, key) for v in value]
    if isinstance(value, str):
        value = JWT_RE.sub("<token>", value)
        value = MOBILE_RE.sub("<mobile>", value)
        value = LONG_TOKEN_RE.sub("<long-token>", value)
    return value


def trim_text(value: Any, max_len: int) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= max_len:
        return value
    return value[:max_len] + f"...<truncated {len(value) - max_len} chars>"


def pick(data: Any, keys: list[str]) -> Any:
    if not isinstance(data, dict):
        return data
    return {key: data.get(key) for key in keys if key in data}


def summarize_items(items: Any, *, sample_size: int) -> dict[str, Any]:
    if not isinstance(items, list):
        return {"total": 0, "tierCounts": {}, "samples": []}
    tier_counts: Counter[str] = Counter()
    school_units: set[str] = set()
    major_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        tier = item.get("tier") or item.get("majorTier") or item.get("schoolTier")
        if tier:
            tier_counts[str(tier)] += 1
        unit_id = item.get("unitId") or item.get("planSchoolDataId") or item.get("schoolUnitCode") or item.get("schoolName")
        if unit_id:
            school_units.add(str(unit_id))
        if item.get("majorName") or item.get("majorId"):
            major_count += 1
    samples = [pick(redact_value(item), ITEM_KEEP_KEYS) for item in items[:sample_size] if isinstance(item, dict)]
    return {
        "total": len(items),
        "unitCountApprox": len(school_units),
        "majorItemCountApprox": major_count,
        "tierCounts": dict(tier_counts),
        "samples": samples,
    }


def summarize_unit_items(items: Any, *, sample_size: int) -> dict[str, Any]:
    if not isinstance(items, list):
        return {"unitTotal": 0, "majorTotal": 0, "tierCounts": {}, "samples": []}
    tier_counts: Counter[str] = Counter()
    major_total = 0
    samples: list[dict[str, Any]] = []
    for index, unit in enumerate(items):
        if not isinstance(unit, dict):
            continue
        tier = unit.get("tier")
        if tier:
            tier_counts[str(tier)] += 1
        majors = unit.get("majorItems") if isinstance(unit.get("majorItems"), list) else []
        major_total += len(majors)
        if index < sample_size:
            sample = pick(
                redact_value(unit),
                ITEM_KEEP_KEYS + ["source", "locked", "pinned", "orderedBy", "orderReason", "schoolEnrollRatio"],
            )
            sample["majorItems"] = [pick(redact_value(m), ITEM_KEEP_KEYS) for m in majors[:3] if isinstance(m, dict)]
            sample["majorItemTotal"] = len(majors)
            samples.append(sample)
    return {
        "unitTotal": len(items),
        "majorTotal": major_total,
        "tierCounts": dict(tier_counts),
        "samples": samples,
    }


def summarize_review(review: Any) -> dict[str, Any] | None:
    if not isinstance(review, dict):
        return None
    checks = review.get("checks") if isinstance(review.get("checks"), list) else []
    return {
        "status": review.get("status"),
        "reviewedAt": review.get("reviewedAt"),
        "sourceVersion": review.get("sourceVersion"),
        "summary": review.get("summary"),
        "checks": [
            pick(
                redact_value(check),
                ["code", "level", "passed", "summary", "detail", "suggestedAction", "affectedUnitIds", "affectedVolunteerIds"],
            )
            for check in checks
        ],
        "compensationPreview": redact_value(review.get("compensationPreview")),
        "pendingActions": redact_value(review.get("pendingActions")),
    }


def summarize_workspace(resp: dict[str, Any], *, sample_size: int) -> dict[str, Any]:
    if not isinstance(resp, dict) or resp.get("code") != 0:
        return {"ok": False, "error": resp.get("msg") or resp.get("_error"), "rawCode": resp.get("code")}
    data = resp.get("data")
    if not isinstance(data, dict):
        return {"ok": False, "error": "missing data"}
    candidate = data.get("candidatePoolState") or {}
    working = data.get("workingPlanState") or data.get("initialRecommendationState") or data.get("draftPlanState") or {}
    ordered = data.get("orderedPlanState") or {}
    return {
        "ok": True,
        "sessionId": data.get("sessionId"),
        "version": data.get("version"),
        "phase": data.get("phase"),
        "staleFlags": data.get("staleFlags"),
        "constraintState": redact_value(data.get("constraintState")),
        "planGenerationState": redact_value(data.get("planGenerationState")),
        "candidatePoolState": {
            "generatedAt": candidate.get("generatedAt"),
            "sourceVersion": candidate.get("sourceVersion"),
            "statusCode": candidate.get("statusCode"),
            "statusMessage": candidate.get("statusMessage"),
            "requiredCount": candidate.get("requiredCount"),
            "requiredTierCounts": candidate.get("requiredTierCounts"),
            "requiredUnitCount": candidate.get("requiredUnitCount"),
            "requiredMajorCount": candidate.get("requiredMajorCount"),
            "userScore": candidate.get("userScore"),
            "batchScore": candidate.get("batchScore"),
            "sourceProvinceName": candidate.get("sourceProvinceName"),
            "volunteerModel": candidate.get("volunteerModel"),
            "summary": candidate.get("summary"),
            "itemsSummary": summarize_items(candidate.get("items"), sample_size=sample_size),
        },
        "workingPlanState": {
            "summary": working.get("summary") if isinstance(working, dict) else None,
            "generationMode": working.get("generationMode") if isinstance(working, dict) else None,
            "autoCompleted": working.get("autoCompleted") if isinstance(working, dict) else None,
            "gradientAdjusted": working.get("gradientAdjusted") if isinstance(working, dict) else None,
            "itemsSummary": summarize_unit_items(working.get("items") if isinstance(working, dict) else None, sample_size=sample_size),
        },
        "orderedPlanState": {
            "summary": ordered.get("summary") if isinstance(ordered, dict) else None,
            "generationMode": ordered.get("generationMode") if isinstance(ordered, dict) else None,
            "autoCompleted": ordered.get("autoCompleted") if isinstance(ordered, dict) else None,
            "gradientAdjusted": ordered.get("gradientAdjusted") if isinstance(ordered, dict) else None,
            "itemsSummary": summarize_unit_items(ordered.get("items") if isinstance(ordered, dict) else None, sample_size=sample_size),
        },
        "reviewState": summarize_review(data.get("reviewState")),
        "dataFreshnessState": redact_value(data.get("dataFreshnessState")),
        "workflowStatus": redact_value(data.get("workflowStatus")),
    }


def summarize_user_score(resp: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resp, dict) or resp.get("code") != 0:
        return {"ok": False, "error": resp.get("msg") or resp.get("_error"), "rawCode": resp.get("code")}
    data = resp.get("data") or {}
    score = data.get("userScoreDetail") if isinstance(data, dict) else None
    if not isinstance(score, dict):
        return {"ok": False, "error": "missing userScoreDetail"}
    return {"ok": True, **redact_value(pick(score, USER_SCORE_KEYS))}


def summarize_messages(resp: dict[str, Any], *, max_content_chars: int) -> dict[str, Any]:
    if not isinstance(resp, dict) or resp.get("code") != 0:
        return {"ok": False, "error": resp.get("msg") or resp.get("_error"), "rawCode": resp.get("code"), "items": []}
    data = resp.get("data") if isinstance(resp.get("data"), list) else []
    items: list[dict[str, Any]] = []
    user_count = 0
    assistant_count = 0
    card_count = 0
    for msg in data:
        if not isinstance(msg, dict):
            continue
        message_from = str(msg.get("messageFrom"))
        if message_from == "1":
            user_count += 1
        elif message_from == "0":
            assistant_count += 1
        if str(msg.get("contentType", "")).upper() == "CARD":
            card_count += 1
        item = pick(msg, MESSAGE_KEEP_KEYS)
        item["content"] = trim_text(redact_value(item.get("content")), max_content_chars)
        items.append(redact_value(item))
    return {
        "ok": True,
        "total": len(items),
        "userMessageCount": user_count,
        "assistantMessageCount": assistant_count,
        "cardMessageCount": card_count,
        "items": items,
    }


def session_has_dialogue(message_summary: dict[str, Any]) -> bool:
    return message_summary.get("userMessageCount", 0) > 0 and message_summary.get("assistantMessageCount", 0) > 0


def fetch_messages_for_session(session: dict[str, Any], *, args: argparse.Namespace) -> dict[str, Any]:
    sid = session["sessionId"]
    resp = fetch_json(
        args.base_url,
        f"/gaotu-assistant-bot/inner/chat/{args.tenant_id}/message/list-all",
        {"chatSessionId": sid},
        timeout=args.message_timeout,
    )
    return summarize_messages(resp, max_content_chars=args.max_content_chars)


def fetch_one(session: dict[str, Any], *, args: argparse.Namespace, messages: dict[str, Any] | None = None) -> dict[str, Any]:
    sid = session["sessionId"]
    if messages is None:
        messages = fetch_messages_for_session(session, args=args)
    score = summarize_user_score(
        fetch_json(
            args.base_url,
            f"/gaotu-assistant-bot/inner/chat/{args.tenant_id}/session/get-extra-data",
            {"chatSessionId": sid, "keyList": "userScoreDetail", "version": 0},
            timeout=args.extra_timeout,
        )
    )
    workspace = summarize_workspace(
        fetch_json(
            args.base_url,
            f"/gaotu-assistant-bot/inner/planning/{args.tenant_id}/session/workspace-state",
            {"chatSessionId": sid},
            timeout=args.workspace_timeout,
        ),
        sample_size=args.workspace_sample_size,
    )
    return {
        "session": redact_value(session),
        "messages": messages,
        "userScoreDetail": score,
        "planningState": workspace,
    }


def collect_candidate_sessions(*, args: argparse.Namespace, password: str) -> list[dict[str, Any]]:
    dialogue_filter = ""
    if not args.include_empty:
        dialogue_filter = """
  AND EXISTS (SELECT 1 FROM assistant_chat_message mx WHERE mx.chat_session_id=s.id AND mx.message_from='1' LIMIT 1)
  AND EXISTS (SELECT 1 FROM assistant_chat_message my WHERE my.chat_session_id=s.id AND my.message_from='0' LIMIT 1)"""
    sql = f"""
SELECT
  s.id,
  s.tenant_id,
  s.bot_id,
  s.user_id,
  s.user_name,
  s.session_status,
  DATE_FORMAT(s.start_time, '%Y-%m-%d %H:%i:%s'),
  DATE_FORMAT(s.end_time, '%Y-%m-%d %H:%i:%s'),
  DATE_FORMAT(s.create_time, '%Y-%m-%d %H:%i:%s'),
  DATE_FORMAT(s.update_time, '%Y-%m-%d %H:%i:%s'),
  u.user_level,
  u.channel,
  DATE_FORMAT(u.expired_date, '%Y-%m-%d %H:%i:%s'),
  (SELECT COUNT(*) FROM assistant_chat_message m WHERE m.chat_session_id=s.id) AS message_count,
  (SELECT COUNT(*) FROM assistant_chat_message m WHERE m.chat_session_id=s.id AND m.message_from='1') AS user_message_count,
  (SELECT COUNT(*) FROM assistant_chat_message m WHERE m.chat_session_id=s.id AND m.message_from='0') AS assistant_message_count
FROM assistant_chat_session s
LEFT JOIN assistant_user_base u ON u.id=s.user_id
WHERE s.tenant_id={int(args.tenant_id)}{dialogue_filter}
ORDER BY s.create_time DESC, s.id DESC
LIMIT {int(args.scan_limit)};
"""
    rows = parse_tsv(
        mysql_query(sql, args=args, password=password),
        [
            "sessionId",
            "tenantId",
            "botId",
            "userId",
            "userName",
            "sessionStatus",
            "startTime",
            "endTime",
            "createTime",
            "updateTime",
            "userLevel",
            "channel",
            "expiredDate",
            "messageCount",
            "userMessageCount",
            "assistantMessageCount",
        ],
    )
    numeric_keys = [
        "sessionId",
        "tenantId",
        "botId",
        "userId",
        "sessionStatus",
        "messageCount",
        "userMessageCount",
        "assistantMessageCount",
    ]
    for row in rows:
        for key in numeric_keys:
            if row.get(key) is not None:
                try:
                    row[key] = int(row[key])
                except ValueError:
                    pass
    return rows


def build_output_path(args: argparse.Namespace, started: dt.datetime) -> str:
    if args.output:
        output = args.output
    else:
        ts = started.strftime("%Y%m%d-%H%M%S")
        output = str(Path(args.output_dir) / f"zhiyuan-production-sample-{args.limit}-{ts}.json")
    if args.gzip and not output.endswith(".gz"):
        output += ".gz"
    return output


def write_output(output: str, data: dict[str, Any]) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output.endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect recent production session samples using read-only DB SELECT and internal GET APIs."
    )
    parser.add_argument("--base-url", default=_env_or_default("ZHIYUAN_SAMPLE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--tenant-id", type=int, default=int(_env_or_default("ZHIYUAN_SAMPLE_TENANT_ID", str(DEFAULT_TENANT_ID))))
    parser.add_argument("--config-path", default=_env_or_default("ZHIYUAN_SAMPLE_CONFIG_PATH", DEFAULT_CONFIG_PATH))
    parser.add_argument("--db-host", default=_env_or_default("ZHIYUAN_SAMPLE_DB_HOST", DEFAULT_DB_HOST))
    parser.add_argument("--db-port", default=_env_or_default("ZHIYUAN_SAMPLE_DB_PORT", DEFAULT_DB_PORT))
    parser.add_argument("--db-user", default=_env_or_default("ZHIYUAN_SAMPLE_DB_USER", DEFAULT_DB_USER))
    parser.add_argument("--db-name", default=_env_or_default("ZHIYUAN_SAMPLE_DB_NAME", DEFAULT_DB_NAME))
    parser.add_argument("--limit", type=int, default=100, help="number of valid sessions to export")
    parser.add_argument("--scan-limit", type=int, default=300, help="recent sessions to scan in the read-only SELECT")
    parser.add_argument("--include-empty", action="store_true", help="include sessions without both user and assistant messages")
    parser.add_argument("--sleep", type=float, default=0.05, help="delay between sessions to avoid request bursts")
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--gzip", action="store_true")
    parser.add_argument("--workspace-sample-size", type=int, default=5)
    parser.add_argument("--max-content-chars", type=int, default=5000)
    parser.add_argument("--message-timeout", type=float, default=15)
    parser.add_argument("--extra-timeout", type=float, default=15)
    parser.add_argument("--workspace-timeout", type=float, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    password = read_db_password(args.config_path)
    candidates = collect_candidate_sessions(args=args, password=password)

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for session in candidates:
        if len(selected) >= args.limit:
            break
        try:
            messages = fetch_messages_for_session(session, args=args)
            if not args.include_empty and not session_has_dialogue(messages):
                skipped.append(
                    {
                        "sessionId": session["sessionId"],
                        "reason": "no_user_and_assistant_dialogue",
                        "messageCount": messages.get("total"),
                    }
                )
            else:
                selected.append(fetch_one(session, args=args, messages=messages))
        except Exception as exc:  # noqa: BLE001 - keep collecting other sessions.
            errors.append({"sessionId": session.get("sessionId"), "error": str(exc)})
        if args.sleep > 0:
            time.sleep(args.sleep)

    ended = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    output = build_output_path(args, started)
    result = {
        "metadata": {
            "generatedAt": started.isoformat(),
            "finishedAt": ended.isoformat(),
            "hostBaseUrl": args.base_url,
            "tenantId": args.tenant_id,
            "requestedLimit": args.limit,
            "scanLimit": args.scan_limit,
            "selectedCount": len(selected),
            "skippedCount": len(skipped),
            "errorCount": len(errors),
            "readonlySources": [
                "SELECT assistant_chat_session LEFT JOIN assistant_user_base ORDER BY create_time DESC LIMIT N",
                f"/gaotu-assistant-bot/inner/chat/{args.tenant_id}/message/list-all?chatSessionId=...",
                f"/gaotu-assistant-bot/inner/chat/{args.tenant_id}/session/get-extra-data?keyList=userScoreDetail&version=0",
                f"/gaotu-assistant-bot/inner/planning/{args.tenant_id}/session/workspace-state?chatSessionId=...",
            ],
            "privacyNote": "Obvious token/mobile/avatar fields are redacted; message and planning text is retained for simulation/case extraction.",
            "workspaceNote": "Workspace state is summarized locally; full candidate and plan item arrays are not exported.",
        },
        "sessions": selected,
        "skipped": skipped,
        "errors": errors,
    }
    write_output(output, result)
    print(
        json.dumps(
            {
                "output": output,
                "selectedCount": len(selected),
                "skippedCount": len(skipped),
                "errorCount": len(errors),
                "firstSessionIds": [s["session"].get("sessionId") for s in selected[:10]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
