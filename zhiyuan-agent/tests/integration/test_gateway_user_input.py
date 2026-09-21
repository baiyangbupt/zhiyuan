"""A4：原生问答桥与澄清卡合同。

链路是双向的，所以这里既测"问题怎么变成卡"，也测"答案怎么回到**原来的 rpc id**"。
后者尤其容易做错：回成一个新请求也能让模型继续跑，只是它永远在等那个旧 id。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.gateway.ui_events import SessionKey
from app.gateway.user_input import (
    INPUT_KIND_FORM,
    UserInputBroker,
    UserInputError,
)
from app.harness.client import AppServerClient


FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "codex" / "fake_app_server.py"
FAKE_COMMAND = [sys.executable, str(FAKE_SERVER)]
KEY = SessionKey(tenant_id="tenant-1", session_id="session-1")


async def _client(broker: UserInputBroker) -> AppServerClient:
    client = AppServerClient(FAKE_COMMAND, request_timeout=10.0)
    client.server_request_handler = broker.handle_server_request
    await client.start()
    await client.initialize(client_name="zhiyuan-gateway", client_version="1")
    return client


def _broker(**kwargs) -> UserInputBroker:
    kwargs.setdefault("runtime_generation", "gen-1")
    kwargs.setdefault("scope_resolver", lambda thread_id: KEY)
    return UserInputBroker(**kwargs)


async def _wait_for_card(broker: UserInputBroker, key: SessionKey = KEY) -> dict:
    for _ in range(200):
        cards = broker.snapshot(key)
        if cards:
            return cards[0]
        await asyncio.sleep(0.01)
    raise AssertionError("澄清卡始终没有出现")


@pytest.mark.asyncio
async def test_native_question_round_trips_under_the_original_rpc_id() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        assert card["inputKind"] == "choice"
        assert card["questions"][0]["id"] == "major"
        assert card["requestId"]

        outcome = await broker.answer(
            KEY,
            card["requestId"],
            {"inputKind": "choice", "answers": {"major": {"answers": ["计算机类"]}}},
        )
        assert outcome["status"] == "accepted"

        # 关键：回包用的是**原来那个 rpc id**，不是新开一个。
        answered = await client.wait_for_notification(
            lambda n: n.get("method") == "test/server_request_answered", timeout=5
        )
        assert answered["params"]["requestId"] == 9001
        assert answered["params"]["result"] == {"answers": {"major": {"answers": ["计算机类"]}}}
        assert answered["params"]["error"] is None

        # 回答一张卡不应该凭空开新回合——那会让模型从"等答案"变成"开了两轮"。
        stats = await client.request("test/stats", {})
        assert stats["turnStarts"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_answering_from_another_session_is_refused() -> None:
    """跨会话作答是越权，不是"输错了"——失败方式必须是拒绝，不是忽略。"""
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        with pytest.raises(PermissionError, match="clarification_scope_mismatch"):
            await broker.answer(
                SessionKey(tenant_id="tenant-1", session_id="other-session"),
                card["requestId"],
                {"inputKind": "choice", "answers": {"major": {"answers": ["计算机类"]}}},
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_same_answer_is_accepted_and_a_different_one_conflicts() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)
        first = {"inputKind": "choice", "answers": {"major": {"answers": ["计算机类"]}}}

        assert (await broker.answer(KEY, card["requestId"], first))["status"] == "accepted"
        # 同答案重发 = 客户端没收到确认，不是新问题。
        assert (await broker.answer(KEY, card["requestId"], first))["status"] == "accepted"
        # 不同答案 = 客户端把两个请求搞混了，替它挑一个是错的。
        second = {"inputKind": "choice", "answers": {"major": {"answers": ["计算机科学与技术"]}}}
        assert (await broker.answer(KEY, card["requestId"], second))["status"] == "conflict"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_expired_question_never_completes_the_future() -> None:
    broker = _broker(ttl_seconds=0.05)
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)
        await asyncio.sleep(0.2)

        # 过期后不能再作答：卡片已经不在可答集合里。
        assert broker.snapshot(KEY) == []
        outcome = await broker.answer(
            KEY,
            card["requestId"],
            {"inputKind": "choice", "answers": {"major": {"answers": ["计算机类"]}}},
        )
        assert outcome["status"] == "unknown_request"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_secret_questions_are_refused_outright() -> None:
    """口令类输入不进卡片、不落库、不经过模型。"""
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test", "secret": True})
        with pytest.raises(UserInputError, match="secret_input_unsupported"):
            await broker.handle_server_request(
                {
                    "id": 77,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": "thr_test",
                        "turnId": "t1",
                        "questions": [
                            {"id": "pw", "question": "密码？", "isSecret": True, "options": []}
                        ],
                    },
                }
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_free_form_answer_is_allowed_only_when_the_question_says_so() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)
        # 替身里这题 isOther=True：自由输入是允许的。
        outcome = await broker.answer(
            KEY,
            card["requestId"],
            {"inputKind": "choice", "answers": {"major": {"answers": ["智能科学与技术"]}}},
        )
        assert outcome["status"] == "accepted"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_option_that_was_never_offered_is_refused_when_is_other_is_false() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        # 换一张不许自由输入的卡：isOther 缺省即 False。
        task = asyncio.create_task(
            broker.handle_server_request(
                {
                    "id": 88,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": "thr_test",
                        "turnId": "t1",
                        "questions": [
                            {
                                "id": "major",
                                "question": "哪一个？",
                                "options": [{"label": "计算机类"}],
                            }
                        ],
                    },
                }
            )
        )
        card = await _wait_for_card(broker)
        with pytest.raises(UserInputError, match="clarification_option_not_offered"):
            await broker.answer(
                KEY,
                card["requestId"],
                {"inputKind": "choice", "answers": {"major": {"answers": ["我自己编的"]}}},
            )
        task.cancel()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_answer_shape_is_enforced_server_side() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        with pytest.raises(UserInputError, match="clarification_answer_shape"):
            await broker.answer(KEY, card["requestId"], {"inputKind": "choice", "answers": {}})
        with pytest.raises(UserInputError, match="clarification_input_kind_mismatch"):
            await broker.answer(
                KEY, card["requestId"], {"inputKind": INPUT_KIND_FORM, "action": "accept"}
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_form_elicitation_uses_action_and_typed_content() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/elicitation", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        assert card["inputKind"] == INPUT_KIND_FORM
        assert card["requestedSchema"]["required"] == ["confirm"]

        # form 的回包是 action + typed content，**不是** answers 数组。
        outcome = await broker.answer(
            KEY, card["requestId"], {"inputKind": INPUT_KIND_FORM, "action": "accept", "content": {"confirm": True}}
        )
        assert outcome["status"] == "accepted"

        answered = await client.wait_for_notification(
            lambda n: n.get("method") == "test/server_request_answered", timeout=5
        )
        assert answered["params"]["result"] == {
            "action": "accept",
            "content": {"confirm": True},
            "_meta": None,
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_form_decline_does_not_invent_content() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/elicitation", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        await broker.answer(KEY, card["requestId"], {"inputKind": INPUT_KIND_FORM, "action": "decline"})
        answered = await client.wait_for_notification(
            lambda n: n.get("method") == "test/server_request_answered", timeout=5
        )
        assert answered["params"]["result"]["action"] == "decline"
        assert answered["params"]["result"]["content"] is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_form_content_is_validated_against_the_server_saved_schema() -> None:
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/elicitation", {"threadId": "thr_test"})
        card = await _wait_for_card(broker)

        cases = [
            ({"inputKind": INPUT_KIND_FORM, "action": "accept", "content": {}},
             "clarification_required_field_missing"),
            ({"inputKind": INPUT_KIND_FORM, "action": "accept", "content": {"confirm": "yes"}},
             "clarification_field_type"),
            ({"inputKind": INPUT_KIND_FORM, "action": "accept",
              "content": {"confirm": True, "sneaky": "x"}},
             "clarification_unknown_field"),
            ({"inputKind": INPUT_KIND_FORM, "action": "accept", "content": None},
             "clarification_content_required"),
        ]
        for payload, expected in cases:
            with pytest.raises(UserInputError, match=expected):
                await broker.answer(KEY, card["requestId"], payload)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_runtime_restart_invalidates_unanswered_questions() -> None:
    """JSON-RPC 请求不跨进程复活：那个 id 在新进程里不存在了。"""
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        await _wait_for_card(broker)

        broker.expire_runtime("gen-1")

        assert broker.snapshot(KEY) == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_resolved_notification_clears_the_card() -> None:
    """`serverRequest/resolved` 只有 id、没有原因：拿不到原因就记 resolved，不猜。"""
    broker = _broker()
    client = await _client(broker)
    try:
        await client.request("test/request_user_input", {"threadId": "thr_test"})
        await _wait_for_card(broker)

        broker.resolve_native("gen-1", 9001, "resolved")

        assert broker.snapshot(KEY) == []
    finally:
        await client.close()
