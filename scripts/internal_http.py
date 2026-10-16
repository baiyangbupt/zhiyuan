from __future__ import annotations

import json
import math
from http.client import HTTPException
import os
import subprocess
from typing import Any
from urllib import error, parse, request


STATUS_MARKER = "\n__ZHIYUAN_HTTP_STATUS__:"
TOKEN_HEADER = "X-Internal-Service-Token"
INTERNAL_SEGMENTS = {"inner", "internal", "admin", "debug"}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.HTTPError(req.full_url, code, "Redirect refused", headers, None)


def require_internal_service_token() -> str:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "")
    if not token or token != token.strip() or any(ord(char) < 32 or ord(char) == 127 for char in token):
        raise ValueError("missing or invalid INTERNAL_SERVICE_TOKEN")
    return token


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 15,
    extra_headers: dict[str, str] | None = None,
    ssh_host: str | None = None,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 2147483647:
        raise ValueError("invalid HTTP timeout")
    parsed_url = parse.urlsplit(url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or any(ord(char) < 32 or ord(char) == 127 for char in url)
    ):
        raise ValueError("invalid HTTP endpoint")
    headers = {"Accept": "application/json"}
    for name, value in (extra_headers or {}).items():
        if name.lower() == TOKEN_HEADER.lower():
            raise ValueError("cannot override internal service credential")
        if any(ord(char) < 32 or ord(char) == 127 for char in name + value):
            raise ValueError("invalid HTTP header")
        headers[name] = value
    protected = bool(INTERNAL_SEGMENTS.intersection(parse.unquote(parsed_url.path).split("/")))
    token = require_internal_service_token() if protected else ""
    if token:
        if token in url:
            raise ValueError("credential must not appear in endpoint")
        headers[TOKEN_HEADER] = token
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False)
        headers["Content-Type"] = "application/json"
    if ssh_host is not None:
        if not ssh_host or ssh_host.startswith("-") or any(char.isspace() for char in ssh_host):
            raise ValueError("invalid SSH host")
        configuration = [
            "silent",
            'proto = "=http,https"',
            f"max-time = {math.ceil(timeout_seconds)}",
            f"request = {json.dumps(method)}",
            f"url = {json.dumps(url, ensure_ascii=False)}",
            f"write-out = {json.dumps(STATUS_MARKER + '%{http_code}')}",
        ]
        configuration.extend(f"header = {json.dumps(name + ': ' + value, ensure_ascii=False)}" for name, value in headers.items())
        if body is not None:
            configuration.append(f"data-binary = {json.dumps(body, ensure_ascii=False)}")
        try:
            process = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_host, "curl -q --config -"],
                input="\n".join(configuration) + "\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds + 10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("internal SSH request failed") from None
        if process.returncode != 0:
            raise RuntimeError("internal SSH request failed")
        raw, marker, status_text = process.stdout.rpartition(STATUS_MARKER)
        if not marker or not status_text.isdigit():
            raise RuntimeError("internal SSH response has no HTTP status")
        status = int(status_text)
    else:
        req = request.Request(url, data=body.encode("utf-8") if body is not None else None, headers=headers, method=method)
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=timeout_seconds) as response:
                status = response.status
                raw = response.read().decode("utf-8")
        except (error.URLError, OSError, ValueError, HTTPException):
            raise RuntimeError("HTTP request failed; redirects are not allowed") from None
    if not 200 <= status < 300:
        raise RuntimeError(f"HTTP request rejected (status {status})")
    if not raw:
        return {"status": status}
    try:
        value = json.loads(raw)
    except ValueError:
        raise RuntimeError("HTTP response is not valid JSON") from None
    if token and json.dumps(token, ensure_ascii=False)[1:-1] in json.dumps(value, ensure_ascii=False):
        raise RuntimeError("HTTP response contains service credential")
    if isinstance(value, dict):
        value.setdefault("_status", status)
        return value
    return {"_status": status, "data": value}
