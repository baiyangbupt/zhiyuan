import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.config import InternalServiceConfig
from app.gateway.thread_recovery import ThreadRecovery, ThreadRecoveryError
from app.gateway.ui_events import SessionKey
from app.harness.binding import ThreadBinding
from app.mcp_server.context import ThreadBindingRegistry
from app.util import internal_client


@asynccontextmanager
async def binding_server(monkeypatch, *, status=200, body=b'{"code":0,"data":null}'):
    requests = []

    async def serve(reader, writer):
        try:
            requests.append((await reader.readuntil(b"\r\n\r\n")).decode())
            writer.write(
                f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n"
                "Location: /unexpected\r\n\r\n".encode() + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = InternalServiceConfig(
        url=f"http://127.0.0.1:{port}", token="offline-binding-token", _env_file=None,
    )
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: config)
    monkeypatch.setattr(internal_client, "http_client", internal_client.HttpClient())
    async with server:
        yield requests


@pytest.fixture
async def production_lookup(monkeypatch, tmp_path):
    from app.server import lifespan

    path = str(tmp_path / "bindings.sqlite")
    registry = ThreadBindingRegistry(path)
    registry.store(
        ThreadBinding(thread_id="thr-local", tenant_id="7", session_id="101", user_id="9"),
        expires_at="2020-01-01T00:00:00+00:00",
    )
    captured = {}

    async def build_runtime(config, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("app.server.configure_logfire", lambda: None)
    monkeypatch.setattr("app.server.GatewayConfig", lambda: SimpleNamespace(mode="codex_readonly"))
    monkeypatch.setattr("app.server.CodexAppServerConfig", lambda: SimpleNamespace(
        binding_ttl_seconds=900, binding_registry_path=path,
    ))
    monkeypatch.setattr("app.server._build_legacy_chat_service", lambda mode: None)
    monkeypatch.setattr("app.server._build_event_store", lambda: None)
    monkeypatch.setattr("app.server.build_gateway_runtime", build_runtime)
    async with lifespan(FastAPI()):
        yield captured["current_binding_loader"]


@pytest.mark.parametrize("status,body", [
    (201, b'{"code":0,"data":null}'),
    (301, b'{"code":0,"data":null}'),
    (401, b'{"code":0,"data":null}'),
    (403, b'{"code":0,"data":null}'),
    (404, b'{"code":0,"data":null}'),
    (429, b'{"code":0,"data":null}'),
    (500, b'{"code":0,"data":null}'),
    (503, b'{"code":0,"data":null}'),
    (200, b'null'), (200, b'[]'), (200, b'{}'), (200, b'not-json'),
    (200, b'{"data":null}'), (200, b'{"code":0}'),
    (200, b'{"code":false,"data":null}'),
    (200, b'{"code":0.0,"data":null}'),
    (200, b'{"code":0,"data":null,"success":false}'),
    (200, b'{"code":0,"data":null,"error":"failed"}'),
    (200, b'{"code":0,"data":"invalid-binding"}'),
    (200, b'{"code":0,"data":{"code":0,"data":null}}'),
    (200, b'{"threadId":"thr-raw","tenantId":7,"chatSessionId":101}'),
    (200, b'{"code":0,"data":{"threadId":"thr-unscoped"}}'),
])
async def test_production_lookup_rejects_untrusted_http_without_fallback_or_thread_operations(
    monkeypatch, production_lookup, status, body,
):
    operations = []

    def forbidden_fallback(self, tenant_id, session_id):
        operations.append("registry")
        return {"threadId": "thr-local", "tenantId": 7, "chatSessionId": 101}

    monkeypatch.setattr(ThreadBindingRegistry, "latest_for_session", forbidden_fallback)

    async def resume(thread_id):
        operations.append("resume")

    async def create():
        operations.append("create")
        return {"thread": {"id": "thr-new"}}

    recovery = ThreadRecovery(lookup=production_lookup, resume=resume, create=create)
    async with binding_server(monkeypatch, status=status, body=body) as requests:
        with pytest.raises(ThreadRecoveryError):
            await recovery.load_or_resume(SessionKey("7", "101"))
    assert operations == []
    assert len(requests) == 1


@pytest.mark.parametrize("data,expected", [
    (None, "thr-local"),
    ({"threadId": "thr-backend", "tenantId": 7, "chatSessionId": 101}, "thr-backend"),
])
async def test_production_lookup_preserves_authority_and_expired_local_recovery(
    monkeypatch, production_lookup, data, expected,
):
    resumed = []

    async def create():
        pytest.fail("valid recovery must not create a thread")

    recovery = ThreadRecovery(lookup=production_lookup, resume=resumed.append, create=create)
    body = json.dumps({"code": 0, "data": data}).encode()
    async with binding_server(monkeypatch, body=body) as requests:
        assert await recovery.load_or_resume(SessionKey("7", "101")) == expected
    assert resumed == [expected]
    assert requests[0].startswith(
        "GET /gaotu-assistant-bot/inner/codex/7/thread-binding/current?chatSessionId=101 HTTP/1.1\r\n"
    )
    assert "X-Internal-Service-Token: offline-binding-token\r\n" in requests[0]
