import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from app.config import InternalServiceConfig
from app.gateway.session_reclaim import PendingPresence, classify_pending_response
from app.gateway.ui_events import SessionKey
from app.util import internal_client


KEY = SessionKey("7", "101")
TOKEN = "offline-pending-token"


@asynccontextmanager
async def pending_server(monkeypatch, *, status=200, body=None, headers=""):
    requests = []
    payload = json.dumps({"code": 0, "data": None}).encode() if body is None else body

    async def serve(reader, writer):
        try:
            requests.append((await reader.readuntil(b"\r\n\r\n")).decode())
            writer.write(
                f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n{headers}\r\n".encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = InternalServiceConfig(url=f"http://127.0.0.1:{port}", token=TOKEN, _env_file=None)
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: config)
    monkeypatch.setattr(internal_client, "http_client", internal_client.HttpClient())
    async with server:
        yield requests


async def test_pending_loader_uses_tenant_scoped_read_and_service_credential(monkeypatch):
    async with pending_server(monkeypatch) as requests:
        response = await internal_client.load_pending_for_reclaim(tenant_id="7", session_id="101")
    assert classify_pending_response(KEY, response).presence is PendingPresence.ABSENT
    assert len(requests) == 1
    assert requests[0].startswith("GET /gaotu-assistant-bot/inner/chat/7/session/pending?chatSessionId=101 HTTP/1.1\r\n")
    assert f"X-Internal-Service-Token: {TOKEN}\r\n" in requests[0]


@pytest.mark.parametrize("status", [201, 301, 401, 403, 404, 429, 500, 503])
async def test_non_200_cannot_disguise_absence_with_success_envelope(monkeypatch, status):
    async with pending_server(monkeypatch, status=status, headers="Location: /unexpected\r\n") as requests:
        response = await internal_client.load_pending_for_reclaim(tenant_id=7, session_id=101)
    assert classify_pending_response(KEY, response).presence is PendingPresence.UNKNOWN
    assert len(requests) == 1


@pytest.mark.parametrize("body", [
    b"not-json", b"[]", b"null", b'{}', b'{"code":0}',
    b'{"code":false,"data":null}', b'{"code":0,"data":null,"success":false}',
])
async def test_http_success_still_requires_valid_business_envelope(monkeypatch, body):
    async with pending_server(monkeypatch, body=body):
        response = await internal_client.load_pending_for_reclaim(tenant_id=7, session_id=101)
    assert classify_pending_response(KEY, response).presence is PendingPresence.UNKNOWN


async def test_legacy_get_keeps_non_200_json_behavior(monkeypatch):
    async with pending_server(monkeypatch, status=503):
        response = await internal_client.http_client.get("/legacy")
    assert response == {"code": 0, "data": None}


@pytest.mark.parametrize("invalid", [
    None, True, False, 0, -1, 1.5, "", "../7", "1/other", "01", " 7", "1.0",
    "9223372036854775808", 9223372036854775808,
])
@pytest.mark.parametrize("field", ["tenant_id", "session_id"])
async def test_invalid_backend_long_id_is_rejected_before_network(monkeypatch, invalid, field):
    async def forbidden_request(*args, **kwargs):
        pytest.fail("invalid ID must not initiate HTTP")

    monkeypatch.setattr(internal_client.http_client, "get", forbidden_request)
    arguments = {"tenant_id": 7, "session_id": 101, field: invalid}
    with pytest.raises(ValueError):
        await internal_client.load_pending_for_reclaim(**arguments)
