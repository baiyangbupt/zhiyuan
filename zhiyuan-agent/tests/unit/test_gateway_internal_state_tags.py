"""机器可读上下文必须被显式标记为「内部状态、禁止原样转述」（2026-10-06 真事故）。

用户实测回复里出现「规划阶段也从「ordered」推进到「profile_ready」」：快照、
state_patch、执行计划骨架、工具契约每轮都以裸 JSON / 半结构化文本注入，模型
分不清"给我推理用的机器状态"和"可以讲给用户听的内容"（base_instructions 第 10
条是另一道闸，这里钉的是网关注入层）。

两件事：
1. 每个机器块都被 `【内部状态（机器格式，禁止原样转述给用户）】…【内部状态结束】`
   包住，并紧跟一句"只能用业务语言转述"；
2. 块内内容**逐字不变**（与不加标签时会产生的文本逐字相等）——只加标签/引导，
   不删真值：模型仍需要版本、缺口、候选和约束才能干活。

断言不用"包含子串"而是逐字相等：子串只能证明"标签在"，证明不了"真值没被顺手
裁掉"；后来者改注释、改渲染顺序都会在这两条上现形。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.engine.execution_plan import build_execution_plan
from app.engine.tool_orchestration import render_tool_contracts
from app.engine.working_set import ConversationWorkingSet
from app.gateway.service import (
    INTERNAL_STATE_CLOSE_TAG,
    INTERNAL_STATE_OPEN_TAG,
    INTERNAL_STATE_REMINDER,
    GatewayService,
)
from app.gateway.snapshot import build_snapshot
from app.harness.binding import ThreadBinding


class FakeMessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


class CodexHarness:
    """只记录每轮喂进去的输入；输出恒为一个合法的最小文本应答。"""

    def __init__(self) -> None:
        self.turns: list[list[Any]] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-internal-state"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
        self.turns.append(input_items)
        return {"turn": {"id": f"turn-{len(self.turns)}"}}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.turns.append(input_items)

        @dataclass
        class Collected:
            status: str
            output: dict
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)

        return Collected(
            status="completed",
            output={"responseType": "text", "message": "好的。"},
            events=[],
        )


class StaticSnapshotLoader:
    def __init__(self, workspace: dict[str, Any]) -> None:
        self.workspace = workspace

    def __call__(self, **kwargs) -> dict[str, Any]:
        return self.workspace


def _workspace(
    *,
    version: int,
    score: int | None = None,
    rank: int | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"provinceName": "浙江"}
    score_context: dict[str, Any] = {}
    if score is not None:
        summary["score"] = score
        score_context["score"] = score
    if rank is not None:
        summary["rank"] = rank
        score_context["rank"] = rank
    return {
        "sessionId": "session-1",
        "version": version,
        "phase": "candidate_exploration",
        "studentSummary": summary,
        "scoreContext": score_context,
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr-internal-state",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


def _gateway(loader: StaticSnapshotLoader, codex: CodexHarness) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=None,
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=loader,
    )


async def _turn(gateway: GatewayService, *, turn_id: str) -> dict[str, Any]:
    return await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id=turn_id,
        content="你好",
    )


def _unwrap(text: str) -> str:
    """取出【内部状态】块里的原始内容；标签或提醒句缺失直接失败。"""
    assert text.startswith(INTERNAL_STATE_OPEN_TAG + "\n"), text[:120]
    body, separator, reminder = text[len(INTERNAL_STATE_OPEN_TAG) + 1:].partition(
        "\n" + INTERNAL_STATE_CLOSE_TAG + "\n"
    )
    assert separator, "机器块没有【内部状态结束】标签"
    assert reminder == INTERNAL_STATE_REMINDER
    return body


@pytest.mark.asyncio
async def test_machine_blocks_are_tagged_and_contents_are_byte_identical() -> None:
    workspace = _workspace(version=10)
    loader = StaticSnapshotLoader(workspace)
    codex = CodexHarness()
    gateway = _gateway(loader, codex)

    result = await _turn(gateway, turn_id="ui-1")
    assert result.get("error") is None, result

    items = codex.turns[0]
    assert len(items) == 5
    # 用户原话是最后一条，**不加**标签（标签只给机器块）。
    assert items[-1] == {"type": "text", "text": "你好"}

    snapshot = build_snapshot(workspace)
    expected_state = json.dumps(
        {"kind": "turn_snapshot", "snapshot": snapshot.model_dump(by_alias=True)},
        ensure_ascii=False,
    )
    assert _unwrap(items[0]["text"]) == expected_state

    working_set = ConversationWorkingSet.from_snapshot(snapshot)
    assert _unwrap(items[1]["text"]) == working_set.as_context_text()

    expected_plan = (
        "【本轮执行计划骨架】\n"
        "这是执行约束和完成条件提示，不是用户新问题。"
        "Codex 仍需根据用户原话确定任务类型、工具和最终步骤。\n"
        + json.dumps(build_execution_plan(snapshot, working_set).as_payload(), ensure_ascii=False)
    )
    assert _unwrap(items[2]["text"]) == expected_plan

    expected_contracts = (
        "【工具编排约束】\n"
        "以下约束用于避免不完整查询和重复读取，不是用户新问题。\n"
        + render_tool_contracts()
    )
    assert _unwrap(items[3]["text"]) == expected_contracts

    # 每个机器块恰好一组标签 + 一句提醒；标签与提醒的措辞本身也不许被改弱。
    for item in items[:4]:
        assert item["text"].count(INTERNAL_STATE_OPEN_TAG) == 1
        assert item["text"].count(INTERNAL_STATE_CLOSE_TAG) == 1
        assert item["text"].endswith(INTERNAL_STATE_REMINDER)
    assert "禁止原样转述" in INTERNAL_STATE_OPEN_TAG
    assert "只能用业务语言转述" in INTERNAL_STATE_REMINDER


@pytest.mark.asyncio
async def test_state_patch_block_is_tagged_with_content_untouched() -> None:
    """版本 +1 的下一轮走 state_patch：同样带标签，补丁内容一字不少。"""
    loader = StaticSnapshotLoader(_workspace(version=10))
    codex = CodexHarness()
    gateway = _gateway(loader, codex)

    await _turn(gateway, turn_id="ui-1")
    updated = _workspace(version=11, score=650, rank=12000)
    loader.workspace = updated
    await _turn(gateway, turn_id="ui-2")

    payload = json.loads(_unwrap(codex.turns[1][0]["text"]))
    assert payload["kind"] == "state_patch"
    assert payload["patch"]["baseVersion"] == 10
    assert payload["patch"]["targetVersion"] == 11
    change = next(
        item for item in payload["patch"]["changes"] if item["path"] == "scoreContext"
    )
    expected_context = build_snapshot(updated).model_dump(by_alias=True)["scoreContext"]
    assert change["newValue"] == expected_context
    assert change["newValue"]["score"] == 650
    # 计划骨架块也仍带着新真值（标签没有把内容吃掉）。
    plan_body = _unwrap(codex.turns[1][2]["text"])
    assert '"taskFamily": "unclassified"' in plan_body
