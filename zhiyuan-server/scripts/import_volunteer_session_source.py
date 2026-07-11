#!/usr/bin/env python3
"""Import an upstream volunteer source JSON file for one existing session.

The script is dry-run by default. It writes only the local session_volunteer
JSON file when --execute is provided. It does not create sessions or mutate DB
rows.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib import error, request


REMOVE_FIELDS = {
    "enrollAdvice",
    "converProcess",
    "enrollMajorSubtitle",
    "enrollMajorId",
}

FILE_SUFFIX = {
    "original": "",
    "temp": "_temp",
    "final": "_final",
}


def default_temp_data_path():
    return (
        os.getenv("VOLUNTEER_TEMP_DATA_PATH")
        or os.getenv("GAOTU_ZHIYUAN_TEMP_DATA_PATH")
        or "/apps/volunnter-tmpdata"
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-session-id", type=int, required=True,
                        help="existing assistant chat session id")
    parser.add_argument("--source-file", required=True,
                        help="upstream exported JSON file")
    parser.add_argument("--tenant-id", type=int, default=1,
                        help="tenant id used by optional warm-up request")
    parser.add_argument("--temp-data-path", default=default_temp_data_path(),
                        help="directory containing session_volunteer_*.json files")
    parser.add_argument("--file-kind", choices=sorted(FILE_SUFFIX), default="original",
                        help="which session volunteer file to write")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090",
                        help="local server base URL for optional warm-up")
    parser.add_argument("--warm-up", action="store_true",
                        help="after writing, call workspace-state once to trigger legacy import")
    parser.add_argument("--no-clean", action="store_true",
                        help="write the unwrapped source JSON without source-data normalization")
    parser.add_argument("--execute", action="store_true",
                        help="actually write the target file. Default is dry-run")
    return parser.parse_args()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def unwrap_payload(value):
    if isinstance(value, dict) and "data" in value:
        data = value.get("data")
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return data
    return value


def clean_value(key, value):
    if key == "score" and isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        try:
            return int(float(stripped))
        except ValueError:
            return value
    if key == "enrollRatio" and isinstance(value, str):
        stripped = value.strip()
        if stripped.endswith("%"):
            try:
                return int(stripped[:-1])
            except ValueError:
                return value
    return value


def clean_json(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in REMOVE_FIELDS:
                continue
            cleaned[key] = clean_json(clean_value(key, item))
        return cleaned
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    return value


def validate_payload(payload, file_kind):
    warnings = []
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object after unwrapping optional data")
    if file_kind == "original":
        if "model" not in payload:
            warnings.append("original source has no model field")
        detail_list = payload.get("detailList")
        if not isinstance(detail_list, list) or not detail_list:
            raise ValueError("original source must contain a non-empty detailList")
    else:
        has_recommend_lists = any(isinstance(payload.get(key), list) for key in ("sprints", "safes", "protects"))
        has_legacy_detail = isinstance(payload.get("detailList"), list)
        if not has_recommend_lists and not has_legacy_detail:
            raise ValueError("temp/final source must contain sprints/safes/protects or legacy detailList")
    return warnings


def target_path(args):
    suffix = FILE_SUFFIX[args.file_kind]
    name = f"session_volunteer_{args.chat_session_id}{suffix}.json"
    return Path(args.temp_data_path) / name


def digest_json(payload):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def write_payload(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    return len(data.encode("utf-8"))


def warm_up_workspace(args):
    url = (
        args.base_url.rstrip("/")
        + f"/gaotu-assistant-bot/inner/planning/{args.tenant_id}/session/workspace-state"
        + f"?chatSessionId={args.chat_session_id}"
    )
    try:
        with request.urlopen(url, timeout=30) as response:
            body = response.read(500).decode("utf-8", errors="replace")
            return response.status, body
    except error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        return exc.code, body


def main():
    args = parse_args()
    source = unwrap_payload(load_json(args.source_file))
    payload = source if args.no_clean else clean_json(source)
    warnings = validate_payload(payload, args.file_kind)
    target = target_path(args)
    digest = digest_json(payload)

    print(f"chat_session_id={args.chat_session_id}")
    print(f"file_kind={args.file_kind}")
    print(f"target={target}")
    print(f"sha256={digest}")
    for warning in warnings:
        print(f"warning={warning}")

    if not args.execute:
        print("dry_run=true")
        print("Add --execute to write the target file.")
        if args.warm_up:
            print("warm_up=skipped_in_dry_run")
        return

    size = write_payload(target, payload)
    print(f"written_bytes={size}")

    if args.warm_up:
        status, body = warm_up_workspace(args)
        print(f"warm_up_status={status}")
        print(f"warm_up_body_prefix={body}")


if __name__ == "__main__":
    main()
