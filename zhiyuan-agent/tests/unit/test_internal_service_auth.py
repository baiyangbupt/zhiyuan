from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import InternalServiceConfig
from app.util import internal_client


HEADER = "X-Internal-Service-Token"
TOKEN = "offline-test-credential"


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in ("INTERNAL_SERVICE_URL", "INTERNAL_SERVICE_TOKEN", "INTERNAL_SERVICE_TIMEOUT_SECONDS"):
        monkeypatch.delenv(key, raising=False)


def test_default_backend_is_loopback_and_import_safe(isolated_config, monkeypatch):
    config = InternalServiceConfig(_env_file=None)
    assert config.url == "http://127.0.0.1:8090"
    assert config.token.get_secret_value() == ""
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: config)
    assert internal_client.HttpClient().base_urls == ["http://127.0.0.1:8090"]


def test_token_is_loaded_from_one_environment_key_and_redacted(isolated_config, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", TOKEN)
    config = InternalServiceConfig(_env_file=None)
    assert config.token.get_secret_value() == TOKEN
    assert TOKEN not in repr(config)
    assert TOKEN not in config.model_dump_json()


def test_explicit_backend_list_is_preserved(isolated_config, monkeypatch):
    config = InternalServiceConfig(url="http://127.0.0.1:18290, http://127.0.0.1:18291", _env_file=None)
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: config)
    assert internal_client.HttpClient().base_urls == ["http://127.0.0.1:18290", "http://127.0.0.1:18291"]


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
@pytest.mark.parametrize("override", [None, {"x-internal-service-token": "untrusted-override", "Origin": "https://browser.invalid"}])
async def test_all_http_verbs_send_configured_token_without_redirecting(isolated_config, monkeypatch, method, override):
    config = InternalServiceConfig(token=TOKEN, _env_file=None)
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: config)
    calls = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {"code": 0, "data": {}}

    def capture(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    session = MagicMock()
    session.__aenter__.return_value = session
    for verb in ("get", "post", "put", "patch", "delete"):
        getattr(session, verb).side_effect = capture
    monkeypatch.setattr(internal_client.aiohttp, "ClientSession", lambda **kwargs: session)
    client = internal_client.HttpClient()
    arguments = {"headers": override}
    if method in {"post", "put", "patch"}:
        arguments["json_data"] = {"probe": True}
    assert await getattr(client, method)("/internal/evidence/verify", **arguments) == {"code": 0, "data": {}}
    assert len(calls) == 1
    sent = calls[0][1]
    credentials = [(key, value) for key, value in sent["headers"].items() if key.lower() == HEADER.lower()]
    assert credentials == [(HEADER, TOKEN)]
    assert sent["allow_redirects"] is False
    if override:
        assert sent["headers"]["Origin"] == override["Origin"]


def test_missing_token_does_not_create_a_credential(isolated_config, monkeypatch):
    monkeypatch.setattr(internal_client, "InternalServiceConfig", lambda: InternalServiceConfig(_env_file=None))
    assert HEADER not in internal_client.HttpClient().default_headers
