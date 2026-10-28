"""A2：统一事件合同与适配器。

fixture 里的原生形状**从真实录制取**（codex-cli 0.155.1 + 真实模型回合），
不是照调用方的期望编的——编出来的形状会让适配器测起来全绿、接真机就哑。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.gateway.event_adapter import adapt_notification
from app.gateway.ui_events import (
    EVENT_TYPES,
    PROTOCOL_VERSION,
    SessionKey,
    UiEvent,
    resync_snapshot,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "conversation_v1.jsonl"


def _cases() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_fixture_covers_the_required_shapes() -> None:
    """fixture 自己也要有防线：少录一类形状，后面所有断言都会静默变弱。"""
    names = {case["name"] for case in _cases()}

    assert {
        "nested_mcp_start",
        "nested_mcp_completed",
        "nested_mcp_failed",
        "agent_json_delta",
        "reasoning_delta",
        "turn_completed",
    } <= names


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_adapter_matches_recorded_shape(case: dict) -> None:
    assert adapt_notification(case["notification"], "ui-turn") == case["expected"]


def test_nested_mcp_start_is_progress_without_arguments() -> None:
    raw = {
        "method": "item/started",
        "params": {
            "threadId": "t",
            "turnId": "c",
            "item": {
                "id": "i",
                "type": "mcpToolCall",
                "server": "zhiyuan_domain",
                "tool": "admission.get_history",
                "status": "inProgress",
                "arguments": {"private": "do-not-display"},
            },
        },
    }

    assert adapt_notification(raw, "u") == [
        {
            "type": "tool.progress",
            "payload": {
                "itemId": "i",
                "tool": "admission.get_history",
                "status": "started",
                "label": "正在查询历年录取",
            },
        }
    ]


def test_adapter_output_never_contains_raw_arguments_or_results() -> None:
    """逐条过 fixture：任何原文泄漏都要在**全量**上被抓到，而不是只在个别用例上。"""
    for case in _cases():
        rendered = json.dumps(adapt_notification(case["notification"], "ui-turn"), ensure_ascii=False)
        assert "do-not-display" not in rendered
        assert "school-secret" not in rendered
        assert "minScore" not in rendered


def test_agent_message_delta_is_private_until_business_validation() -> None:
    """No raw prose, including a readable prefix, may precede validation."""
    with_item = adapt_notification(
        {"method": "item/agentMessage/delta",
         "params": {"delta": "你", "itemId": "msg_1", "turnId": "turn_1"}},
        "ui-turn",
    )
    without_item = adapt_notification(
        {"method": "item/agentMessage/delta", "params": {"delta": "好"}}, "ui-turn"
    )

    assert with_item == []
    assert without_item == []
    assert adapt_notification(
        {"method": "item/agentMessage/delta", "params": {"delta": ""}}, "ui-turn"
    ) == []


def test_adapter_ignores_non_mapping_and_missing_params() -> None:
    assert adapt_notification(None, "u") == []
    assert adapt_notification({"method": "item/started"}, "u") == []
    assert adapt_notification({"method": "item/started", "params": None}, "u") == []


def test_every_emitted_type_is_in_the_frozen_whitelist() -> None:
    for case in _cases():
        for event in adapt_notification(case["notification"], "ui-turn"):
            assert event["type"] in EVENT_TYPES


def test_ui_event_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError, match="unknown_ui_event_type"):
        UiEvent(
            type="totally.made.up",
            sessionId="42",
            turnId="t1",
            streamEpoch="e1",
            sequence=1,
            payload={},
        )


def test_ui_event_requires_positive_sequence_and_non_empty_epoch() -> None:
    common = {"sessionId": "42", "turnId": "t1", "payload": {}}

    with pytest.raises(ValidationError):
        UiEvent(type="turn.started", streamEpoch="e1", sequence=0, **common)
    with pytest.raises(ValidationError):
        UiEvent(type="turn.started", streamEpoch="", sequence=1, **common)


def test_ui_event_forbids_extra_fields() -> None:
    """多带的字段是协议漂移的信号，宁可拒收也不要静默放行。"""
    with pytest.raises(ValidationError):
        UiEvent(
            type="turn.started",
            sessionId="42",
            turnId="t1",
            streamEpoch="e1",
            sequence=1,
            payload={},
            secret="leak",
        )


def test_ui_event_serializes_with_camel_case_aliases() -> None:
    event = UiEvent(
        type="turn.phase",
        sessionId="42",
        turnId="t1",
        streamEpoch="e1",
        sequence=8,
        payload={"phase": "querying_evidence", "status": "started", "label": "正在查询历年录取"},
    )

    dumped = json.loads(event.model_dump_json(by_alias=True))

    assert dumped["protocolVersion"] == PROTOCOL_VERSION
    assert dumped["sessionId"] == "42"
    assert dumped["streamEpoch"] == "e1"
    assert dumped["sequence"] == 8


def test_resync_snapshot_is_a_control_frame_not_a_ui_event() -> None:
    """resync 允许 sequence=0，且不能通过 UiEvent 的校验——这不是漏洞，是分工。"""
    frame = resync_snapshot(
        session_id="42", turn_id="t1", stream_epoch="epoch-2", baseline={"turns": {}}
    )

    assert frame["type"] == "session.resync"
    assert frame["sequence"] == 0
    assert frame["payload"]["baseline"] == {"turns": {}}
    with pytest.raises(ValidationError):
        UiEvent(**{**frame, "type": "session.resync"})


def test_session_key_has_no_thread_component() -> None:
    """thread 会随进程重启改变，不能进隔离边界。"""
    key = SessionKey(tenant_id="7", session_id="42")

    assert key.tenant_id == "7"
    assert key.session_id == "42"
    assert SessionKey(tenant_id="7", session_id="42") == key
    assert SessionKey(tenant_id="8", session_id="42") != key
