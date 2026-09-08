from __future__ import annotations

import asyncio

from app.server import app, health_check


def test_health_endpoint_returns_agent_status() -> None:
    response = asyncio.run(health_check())

    assert response["status"] == "UP"
    assert response["service"] == "zhiyuan-agent"


def test_prefixed_health_endpoint_is_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/health" in paths
    assert "/gaotu-assistant-agent/health" in paths
