from types import SimpleNamespace

import pytest

from app.util import internal_client
from app.util.internal_client import (
    EXECUTE_WAIT_TIMEOUT_SECONDS,
    HttpClient,
)


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


def test_timeout_resolver_keeps_default_when_not_overridden(monkeypatch) -> None:
    """没给覆盖值时**原样返回**默认超时 ✓（常规调用的护栏不许被顺带放宽 ✗）。"""
    monkeypatch.setattr(
        "app.util.internal_client.InternalServiceConfig",
        lambda: SimpleNamespace(url="http://internal.example", timeout_seconds=2.5),
    )
    client = HttpClient()

    assert client._resolve_timeout() is client.timeout
    assert client._resolve_timeout(None) is client.timeout


def test_timeout_resolver_honors_the_per_call_override(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.util.internal_client.InternalServiceConfig",
        lambda: SimpleNamespace(url="http://internal.example", timeout_seconds=2.5),
    )
    client = HttpClient()

    assert client._resolve_timeout(45).total == 45


@pytest.mark.asyncio
async def test_execute_pending_command_relaxes_the_wait(monkeypatch) -> None:
    """`pending-command/execute` 是**同步等命令跑完** ✓（Java 单事务同步返回 ✓）：
    补录成绩这条实测 23.8s ✓，默认 10s 会在**写已提交**之后超时 ✗ → 卡上误显"未生效" ✗
    （2026-10-06 真栈实测 ✓）。这条调用必须带放宽后的总超时 ✓。
    """
    calls: list[dict] = []

    async def fake_post(**kwargs):
        calls.append(kwargs)
        return {"code": 0, "data": {}}

    monkeypatch.setattr(internal_client.http_client, "post", fake_post)

    await internal_client.execute_pending_planning_command(
        "1",
        "900032",
        operation_id="op-score-1",
        pending_id="pending-score-1",
        claim_token="claim-token",
        expected_plan_version=1,
        command_type="update_score_detail",
        score_update={"totalScore": 485},
    )

    assert len(calls) == 1
    assert calls[0]["timeout_seconds"] == EXECUTE_WAIT_TIMEOUT_SECONDS
    assert calls[0]["json_data"]["commandType"] == "update_score_detail"



@pytest.mark.asyncio
async def test_execute_timeout_is_unknown_in_progress_not_failed(monkeypatch) -> None:
    """超时≠未执行：必须返回 applying，不能把已提交的命令显示成失败。"""
    import asyncio

    async def fake_post(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(internal_client.http_client, "post", fake_post)

    result = await internal_client.execute_pending_planning_command(
        "1",
        "900032",
        operation_id="op-timeout-1",
        pending_id="pending-timeout-1",
        claim_token="claim-token",
        expected_plan_version=1,
        command_type="fill_to_count",
        regenerate_ordered_plan=True,
        proposal_apply={"targetCount": 50},
    )

    assert result["status"] == "applying"
    assert result["code"] == 0
    assert "稍后重试" in result["data"]["message"]
