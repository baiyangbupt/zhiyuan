from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client() -> TestClient:
    patches = [
        patch("app.server.LLMClient"),
        patch("app.server.ChatHistoryStore"),
        patch("app.server.configure_logfire"),
        patch("app.server.HistoryConfig", return_value=MagicMock(db_path=":memory:")),
    ]
    for item in patches:
        item.start()
    try:
        from app.server import app

        return TestClient(app)
    finally:
        for item in reversed(patches):
            item.stop()


def test_health_endpoint_returns_agent_status() -> None:
    client = _client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.json()["service"] == "zhiyuan-agent"


def test_prefixed_health_endpoint_returns_agent_status() -> None:
    client = _client()

    response = client.get("/gaotu-assistant-agent/health")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.json()["service"] == "zhiyuan-agent"
