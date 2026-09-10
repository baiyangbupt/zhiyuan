#!/usr/bin/env python3
"""Transparent capture proxy between Codex App Server and DeepSeek.

Diagnostic-only: relays any POST (any path) to https://api.deepseek.com and dumps
the raw SSE byte stream to disk, one file per request.

Hard constraints (see task doc):
  * path-agnostic forwarding (no hardcoded /v1/responses)
  * chunk-by-chunk relay, never buffered
  * headers forwarded verbatim (Authorization included), only Host dropped
  * Authorization masked to its first 8 chars before anything is written to disk
  * read timeout >= 300s so the proxy never times out first

Usage:
    python sse_capture_proxy.py --port 18999 --dump-dir /root/dev/zhiyuan/.runtime/sse-capture
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

UPSTREAM = "https://api.deepseek.com"

# Hop-by-hop headers are not forwarded in either direction (RFC 7230 6.1).
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

# Header names whose value is masked before it can reach a dump file.
SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key", "openai-api-key"}

MASK_KEEP = 8
READ_TIMEOUT_SECONDS = 300.0


def mask(value: str) -> str:
    """Keep only the first MASK_KEEP characters of a secret value."""
    if len(value) <= MASK_KEEP:
        return value[:MASK_KEEP] + "…[MASKED len=%d]" % len(value)
    return value[:MASK_KEEP] + "…[MASKED len=%d]" % len(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class SSEWatcher:
    """Incrementally tracks complete SSE events in the byte stream (read-only)."""

    def __init__(self) -> None:
        self._pending = b""
        self._hold_cr = b""
        self.event_names: list[str] = []
        self.data_types: list[str] = []
        self.last_complete_event_name: str | None = None
        self.last_complete_data_type: str | None = None
        self.incomplete_tail = b""

    def feed(self, chunk: bytes) -> None:
        # events routinely straddle chunk boundaries: carry the pending tail
        # forward instead of parsing each chunk in isolation
        data = self._pending + self._hold_cr + chunk
        self._hold_cr = b""
        if data.endswith(b"\r"):
            self._hold_cr = b"\r"
            data = data[:-1]
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        parts = data.split(b"\n\n")
        self._pending = parts.pop()
        self.incomplete_tail = self._pending
        for part in parts:
            name, data_type = self._parse(part)
            if name is None and data_type is None:
                continue
            self.event_names.append(name or "")
            self.last_complete_event_name = name
            if data_type is not None:
                self.data_types.append(data_type)
                self.last_complete_data_type = data_type

    @staticmethod
    def _parse(block: bytes) -> tuple[str | None, str | None]:
        name: str | None = None
        payload: list[str] = []
        for raw_line in block.split(b"\n"):
            line = raw_line.decode("utf-8", "replace")
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                payload.append(line[len("data:") :].strip())
            elif line.startswith("{"):
                payload.append(line.strip())
        data_type: str | None = None
        joined = "".join(payload)
        if joined:
            try:
                parsed = json.loads(joined)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                value = parsed.get("type")
                if isinstance(value, str):
                    data_type = value
        return name, data_type


class DumpWriter:
    """One file per upstream request; flushed after every chunk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = path.open("w", encoding="utf-8")
        self.chunk_count = 0
        self.byte_count = 0

    def line(self, text: str = "") -> None:
        self._fh.write(text + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def _dump_request(
    dump: DumpWriter,
    index: int,
    request: web.Request,
    forwarded_headers: dict[str, str],
    body: bytes,
) -> None:
    dump.line("=" * 78)
    dump.line(f"request_index: {index}")
    dump.line(f"start_wall: {now_iso()}")
    dump.line(f"method: {request.method}")
    dump.line(f"path: {request.rel_url}")
    dump.line(f"upstream_url: {UPSTREAM}{request.rel_url}")
    dump.line("request_headers:")
    for name, value in request.headers.items():
        if name.lower() in SENSITIVE_HEADERS:
            dump.line(f"  {name}: {mask(value)}")
        else:
            dump.line(f"  {name}: {value}")
    dump.line(f"request_body_bytes: {len(body)}")
    dump.line("request_body:")
    dump.line(body.decode("utf-8", "replace"))
    dump.line("chunks:")


async def handle(request: web.Request) -> web.StreamResponse:
    app = request.app
    dump_dir: Path = app["dump_dir"]
    session: ClientSession = app["session"]

    index = app["counter"]
    app["counter"] = index + 1
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump = DumpWriter(dump_dir / f"req-{index:04d}-{stamp}.log")
    finished = False
    downstream: web.StreamResponse | None = None

    try:
        body = await request.read()
        forwarded_headers: dict[str, str] = {}
        for name, value in request.headers.items():
            lowered = name.lower()
            if lowered in HOP_BY_HOP or lowered == "host" or lowered == "content-length":
                continue
            forwarded_headers[name] = value

        _dump_request(dump, index, request, forwarded_headers, body)

        url = f"{UPSTREAM}{request.rel_url}"
        started = time.perf_counter()
        upstream_error: BaseException | None = None
        client_write_error: BaseException | None = None
        watcher = SSEWatcher()
        upstream_status: int | None = None

        try:
            upstream = await session.request(
                request.method,
                url,
                headers=forwarded_headers,
                data=body,
                allow_redirects=False,
            )
            upstream_status = upstream.status
            dump.line(f"upstream_status: {upstream.status} {upstream.reason}")
            dump.line("upstream_response_headers:")
            for name, value in upstream.headers.items():
                dump.line(f"  {name}: {value}")

            downstream = web.StreamResponse(status=upstream.status, reason=upstream.reason)
            for name, value in upstream.headers.items():
                lowered = name.lower()
                if lowered in HOP_BY_HOP or lowered == "content-length":
                    continue
                downstream.headers[name] = value
            await downstream.prepare(request)
            dump.line(f"client_prepared_at: {time.perf_counter() - started:.3f}")

            try:
                async for chunk in upstream.content.iter_any():
                    offset = time.perf_counter() - started
                    dump.chunk_count += 1
                    dump.byte_count += len(chunk)
                    dump.line(
                        f"  +{offset:.3f}s len={len(chunk)} repr={chunk!r}"
                    )
                    watcher.feed(chunk)
                    dump.line(
                        "    sse_tail_event="
                        f"{watcher.last_complete_event_name} sse_tail_type="
                        f"{watcher.last_complete_data_type}"
                    )
                    if client_write_error is None:
                        try:
                            await downstream.write(chunk)
                        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
                            client_write_error = exc
                            dump.line(
                                f"    client_write_error: {type(exc).__name__}: {exc}"
                            )
                            # keep draining upstream so the true upstream
                            # termination is still captured
            finally:
                try:
                    await downstream.write_eof()
                except Exception:
                    pass
        except (asyncio.TimeoutError, socket.timeout, TimeoutError) as exc:
            upstream_error = exc
        except Exception as exc:  # noqa: BLE001 - diagnostic capture
            upstream_error = exc

        elapsed = time.perf_counter() - started

        if isinstance(upstream_error, (asyncio.TimeoutError, socket.timeout, TimeoutError)):
            terminal = "TIMEOUT"
            dump.line(f"terminal: TIMEOUT threshold_s={READ_TIMEOUT_SECONDS}")
        elif upstream_error is not None:
            terminal = "EXCEPTION"
            dump.line(
                "terminal: EXCEPTION "
                f"type={type(upstream_error).__module__}.{type(upstream_error).__name__} "
                f"str={upstream_error!s}"
            )
        else:
            terminal = "CLEAN_EOF"
            dump.line("terminal: CLEAN_EOF (upstream ended the stream)")

        dump.line(f"upstream_status: {upstream_status}")
        dump.line(f"chunk_count: {dump.chunk_count}")
        dump.line(f"byte_count: {dump.byte_count}")
        dump.line(f"total_elapsed_s: {elapsed:.3f}")
        dump.line(f"last_complete_sse_event_name: {watcher.last_complete_event_name}")
        dump.line(f"last_complete_sse_event_type: {watcher.last_complete_data_type}")
        dump.line(f"sse_event_names: {json.dumps(watcher.event_names)}")
        dump.line(f"sse_data_types: {json.dumps(watcher.data_types)}")
        dump.line(f"incomplete_tail_bytes: {len(watcher.incomplete_tail)}")
        dump.line(f"incomplete_tail_repr: {watcher.incomplete_tail!r}")
        if client_write_error is not None:
            dump.line(
                f"client_write_error: {type(client_write_error).__name__}: {client_write_error}"
            )
        dump.line("=== END ===")
        finished = True

        print(
            f"[proxy] #{index:04d} {request.method} {request.rel_url} -> "
            f"{upstream_status} terminal={terminal} elapsed={elapsed:.3f}s "
            f"chunks={dump.chunk_count} last_event={watcher.last_complete_data_type}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic capture
        dump.line(
            f"proxy_error: {type(exc).__module__}.{type(exc).__name__}: {exc}"
        )
        print(f"[proxy] #{index:04d} proxy_error {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        if not finished:
            dump.line("proxy_error: handler aborted before terminal record")
        dump.close()

    if downstream is not None:
        return downstream
    return web.Response(status=502, text="proxy_error")


def build_app(dump_dir: Path, start_index: int = 1) -> web.Application:
    app = web.Application(client_max_size=256 * 1024 * 1024)
    app["dump_dir"] = dump_dir
    app["counter"] = start_index
    app.router.add_route("*", "/{tail:.*}", handle)
    return app


async def main_async(args: argparse.Namespace) -> None:
    dump_dir = Path(args.dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)
    timeout = ClientTimeout(total=None, sock_read=args.read_timeout, connect=30.0)
    session = ClientSession(timeout=timeout, auto_decompress=False)
    app = build_app(dump_dir, args.start_index)
    app["session"] = session
    app.on_cleanup.append(lambda _app: session.close())
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()
    print(
        f"[proxy] listening on http://{args.host}:{args.port} -> {UPSTREAM} "
        f"dump_dir={dump_dir} read_timeout={args.read_timeout}s",
        flush=True,
    )
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18999)
    parser.add_argument(
        "--dump-dir",
        default="/root/dev/zhiyuan/.runtime/sse-capture",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="dump file numbering starts here (use to continue after a restart)",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=READ_TIMEOUT_SECONDS,
        help="upstream read timeout in seconds (>=300 per task spec)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
