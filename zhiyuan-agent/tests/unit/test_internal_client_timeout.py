from types import SimpleNamespace

from app.util.internal_client import HttpClient


def test_internal_http_client_uses_configured_total_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.util.internal_client.InternalServiceConfig",
        lambda: SimpleNamespace(url="http://internal.example", timeout_seconds=2.5),
    )

    client = HttpClient()

    assert client.timeout.total == 2.5


def test_internal_http_client_keeps_timeout_positive(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.util.internal_client.InternalServiceConfig",
        lambda: SimpleNamespace(url="http://internal.example", timeout_seconds=0),
    )

    client = HttpClient()

    assert client.timeout.total == 0.1
