"""空会话补录成绩之后，网关**下一轮**必须看到新成绩。

Java 侧补录成功会把规划状态版本 +1（`ChatSessionBizService.updateScoreDetail` →
`PlanningStateService.applyScoreDetailUpdate`）。网关不额外接收"失效信号"，
靠的是两条既有机制接力：

1. **每个回合都重问 Java 要权威快照**（`_handle_uncached` 里的 `snapshot_loader`），
   当前回合用的是刚读回来的那份，不看 `_snapshots` 缓存；
2. **缓存写入按版本淘汰**（`_store_snapshot`）：比起缓存旧的快照拒收，
   而补录恰好把版本 +1 → 新快照一定写得进去。

这个文件把两条都钉住：补录前（缺成绩 → clarification）与补录后（成绩齐 →
正常的 unclassified）各跑一个真实 `handle_turn`，断言模型实际拿到的快照/执行
计划变了；再把版本守卫的四种情形（更新 / 更旧 / 相等 / authoritative 回退）各钉一条。

写这个文件的直接动机：`_store_snapshot` 的"版本更小就拒收"如果被误改成无条件
拒收，症状是**用户补录完成、下一轮模型还在说"请先提供成绩"**——链路上不打报错，
只有真实回合才知道。所以这里用真实回合而不是只测 `_store_snapshot` 单函数。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.gateway.contracts import ConversationTurnSnapshot
from app.gateway.service import GatewayService, _session_key
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
        return {"thread": {"id": "thr-score-refresh"}}

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


class SwitchingSnapshotLoader:
    """可切换的权威快照来源；**每次调用都算数**（current 代表 Java 侧最新状态）。"""

    def __init__(self, workspace: dict[str, Any]) -> None:
        self.current = workspace
        self.calls = 0

    def __call__(self, **kwargs) -> dict[str, Any]:
        self.calls += 1
        return self.current


def _workspace(*, version: int, score: int | None = None, rank: int | None = None,
               missing: list[str] | None = None) -> dict[str, Any]:
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
        "phase": "intake" if missing else "candidate_exploration",
        "studentSummary": summary,
        "scoreContext": score_context,
        "missingFacts": list(missing or []),
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr-score-refresh",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


def _gateway(loader: SwitchingSnapshotLoader, codex: CodexHarness) -> GatewayService:
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


def _item_text(codex: CodexHarness, index: int, marker: str) -> str:
    """取第 index 轮喂给模型的某条文本（按开头 marker 找，避免多重转义）。"""
    for item in codex.turns[index]:
        if isinstance(item, dict) and str(item.get("text", "")).startswith(marker):
            return item["text"]
    raise AssertionError(f"turn {index}: no context item starting with {marker!r}")


@pytest.mark.asyncio
async def test_next_turn_sees_score_after_same_session_backfill() -> None:
    """补录（Java 侧版本 +1、成绩补上）后，下一轮模型看到的是新快照，不再澄清缺成绩。"""
    loader = SwitchingSnapshotLoader(_workspace(version=10))
    codex = CodexHarness()
    gateway = _gateway(loader, codex)

    first = await _turn(gateway, turn_id="ui-1")
    assert first.get("error") is None, first
    # 补录前：快照缺 score/rank（build_snapshot 自动补进 missingFacts），执行计划要求先澄清。
    plan_before = _item_text(codex, 0, "【本轮执行计划骨架】")
    assert '"taskFamily": "clarification"' in plan_before
    assert '"blockedSteps": ["score", "rank"]' in plan_before

    # —— Java 侧补录：userScoreDetail 写入 + 规划状态版本 +1（同一会话，不换 sessionId）。
    loader.current = _workspace(version=11, score=650, rank=12000)

    second = await _turn(gateway, turn_id="ui-2")
    assert second.get("error") is None, second
    # 下一轮：网关重问 Java（不是复用缓存），新成绩进入状态补丁，
    # 缺口清空 → 执行计划不再是 clarification。
    patch_after = _item_text(codex, 1, '{"kind"')
    assert '"kind": "state_patch"' in patch_after
    assert '"path": "scoreContext"' in patch_after
    assert '"score": 650, "rank": 12000' in patch_after
    plan_after = _item_text(codex, 1, "【本轮执行计划骨架】")
    assert '"taskFamily": "unclassified"' in plan_after
    assert '"clarification"' not in plan_after
    assert '"blockedSteps": []' in plan_after
    assert loader.calls >= 2, "每轮都必须重问 Java 要权威快照"

    cached = await gateway.get_current_snapshot(tenant_id="tenant-1", session_id="session-1")
    assert cached is not None and cached.snapshot_version == 11, "缓存也应被新版本替换"
    assert cached.score_context.get("score") == 650


@pytest.mark.asyncio
async def test_non_adjacent_version_jump_still_sends_full_snapshot_with_new_score() -> None:
    """版本跳号（如补录与另一处状态变更叠加）时退化成整份 turn_snapshot，**内容仍是新的**。

    相邻版本才做增量（state_patch），这是既有约定；这条钉的是"非相邻 ≠ 不更新"——
    否则一次跳版本就会让模型整轮拿着旧成绩。
    """
    loader = SwitchingSnapshotLoader(_workspace(version=30))
    codex = CodexHarness()
    gateway = _gateway(loader, codex)

    await _turn(gateway, turn_id="ui-1")
    loader.current = _workspace(version=32, score=650, rank=12000)
    await _turn(gateway, turn_id="ui-2")

    state_after = _item_text(codex, 1, '{"kind"')
    assert '"kind": "turn_snapshot"' in state_after
    assert '"score": 650' in state_after
    assert '"taskFamily": "unclassified"' in _item_text(codex, 1, "【本轮执行计划骨架】")


def test_store_snapshot_keeps_newest_unless_authoritative() -> None:
    """版本守卫：更旧拒收、相等放行、更新替换；authoritative 允许合法回退。"""
    gateway = _gateway(SwitchingSnapshotLoader(_workspace(version=1)), CodexHarness())
    key = _session_key("tenant-1", "session-1")

    def snapshot(version: int) -> ConversationTurnSnapshot:
        return ConversationTurnSnapshot(snapshot_version=version, session_id="session-1")

    assert gateway._store_snapshot(key, snapshot(10)) is True
    # 迟到的旧快照（重放/并发回合）不得把新状态顶回去。
    assert gateway._store_snapshot(key, snapshot(9)) is False
    assert gateway._snapshots[key].snapshot_version == 10
    # 相等版本可写：同一版本的重复读取不该被判成冲突。
    assert gateway._store_snapshot(key, snapshot(10)) is True
    # 补录后的新版本（+1）一定写得进去 —— 这是"下一轮看得到"的前提。
    assert gateway._store_snapshot(key, snapshot(11)) is True
    assert gateway._snapshots[key].snapshot_version == 11
    # authoritative：reset / supersede 之后版本合法地往回走，必须能落回来。
    assert gateway._store_snapshot(key, snapshot(3), authoritative=True) is True
    assert gateway._snapshots[key].snapshot_version == 3
