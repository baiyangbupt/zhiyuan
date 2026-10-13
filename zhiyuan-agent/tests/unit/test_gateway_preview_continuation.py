"""预览没有可确认卡片时的跟话（2026-10-13 实测，会话 10041981，20:22）：收尾话术要纠回来。

现场复刻：用户选了三所学校，模型回复"我把它们和「学费一年 3 万以内」合成一件事，
**提交给你确认了**……点卡片或回复确认"——而本轮 `proposal.preview` 的真实结局是
`info`（"当前方案里已经有 3 个专业组……本轮不需要调整方案"，**无按钮**），
用户被引向一个**不存在的确认动作**。同族历史：多规则场景 blocked 卡而文案称"待确认"。

这里钉 `GatewayService.continue_after_proposal_preview` 的七条：
① 触发档 = blocked ∪ info ∪ preview_only；ready / pending / applied 一律不触发；
② 跟话是**助手回合**（喂进内部标签指令、**不落 user 消息**、产出落 agent 消息）；
③ nudge 必须**纠正收尾**（点名"没有可确认的卡片/不要重复确认指令"）+ 带结局事实
   （info=已满足 / blocked=原因原文 / preview_only=仅供参考）+ 下一步动线 + 封闭式提问
   + 不许原样重发同一提案；
④ 幂等按**触发它的用户回合**：同一回合重复触发只跟一次；不同回合各自可跟（收尾是回合事实）；
⑤ 跟话回合自己失败：只返回一次带措辞的失败（不许说"已提交/待确认"），不重试、不循环；
⑥ 用户已动话头（水位变了）→ 让路，不跟话；
⑦ 会话锁被占着 → 不插队，也不死锁。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.gateway.service import (
    CONTINUATION_CLOSE_TAG,
    CONTINUATION_OPEN_TAG,
    GatewayService,
    _PREVIEW_CONTINUATION_FAILURE_REPLY,
)
from app.gateway.ui_events import SessionKey
from app.harness.binding import ThreadBinding


class _MessageStore:
    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.agent_messages: list[str] = []

    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        self.user_messages.append(content)
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        self.agent_messages.append(content)
        return 2


class _ScriptedCodex:
    """按轮次给输出；每一轮的输入原样记下来（跟话指令就在里面）。"""

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = list(outputs)
        self.turns: list[list[Any]] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-preview-cont"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.turns.append(input_items)

        @dataclass
        class Collected:
            status: str
            output: dict | None
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)
            error_code: str | None = None

        if not self.outputs:
            raise AssertionError("替身没有更多剧本：跟话被多跑了一轮 ✗")
        output = self.outputs.pop(0)
        if output.get("__error__"):
            return Collected(status="failed", output=None, events=[], error_code=output["__error__"])
        return Collected(status="completed", output=output, events=[])


def _workspace(version: int = 5) -> dict[str, Any]:
    return {
        "sessionId": "session-1",
        "version": version,
        "phase": "candidate_exploration",
        "studentSummary": {"provinceName": "浙江", "score": 650, "rank": 12000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


class _SnapshotLoader:
    def __call__(self, **kwargs) -> dict[str, Any]:
        return _workspace()


def _gateway(codex: _ScriptedCodex, *, store: _MessageStore | None = None) -> tuple[GatewayService, _MessageStore]:
    message_store = store or _MessageStore()
    gateway = GatewayService(
        mode="codex_write",
        codex=codex,
        legacy=None,
        message_store=message_store,
        binding_loader=lambda **kwargs: ThreadBinding(
            thread_id="thr-preview-cont",
            tenant_id="tenant-1",
            session_id="session-1",
            user_id="user-1",
            allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
        ),
        snapshot_loader=_SnapshotLoader(),
    )
    return gateway, message_store


def _collector() -> tuple[list[dict], Any]:
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    return events, emit


async def _continue(
    gateway: GatewayService,
    *,
    status: str = "info",
    preview: dict[str, Any] | None = None,
    source_turn_id: str = "turn-user-1",
    watermark: int = 0,
    emit=None,
):
    payload = {"status": status}
    payload.update(preview or {})
    return await gateway.continue_after_proposal_preview(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="cont-1",
        source_turn_id=source_turn_id,
        preview=payload,
        user_turn_watermark=watermark,
        emit=emit,
    )


@pytest.mark.asyncio
async def test_an_info_preview_runs_exactly_one_continuation_turn() -> None:
    """info（本轮无需调整、无卡片）→ 恰好一轮跟话：纠正收尾 + 助手消息入流并落库。

    现场复刻：模型收尾说"提交给你确认了、点卡片或回复确认"，实际没有可确认的卡。
    """
    corrected = (
        "纠正一下：这一轮其实没有需要你确认的卡片——你想加的三所学校方案里都已经在了。"
        "接下来你想让我看看它们的录取把握，还是换个口径再筛？"
    )
    codex = _ScriptedCodex([{"responseType": "text", "message": corrected}])
    gateway, store = _gateway(codex)
    events, emit = _collector()

    result = await _continue(
        gateway,
        status="info",
        preview={"summary": "当前方案里已经有 3 个专业组，本轮不需要调整方案"},
        emit=emit,
    )

    assert result is not None
    assert result["reply"] == corrected
    # ① 恰好跑了一轮（跟话），且只一轮。
    assert len(codex.turns) == 1
    nudge = codex.turns[0][-1]["text"]
    # ② nudge：内部标签 + **纠正收尾**（点名"没有可确认的卡片"、不重复确认指令）。
    assert nudge.startswith(CONTINUATION_OPEN_TAG)
    assert nudge.endswith(CONTINUATION_CLOSE_TAG)
    assert "如实纠正收尾" in nudge
    assert "没有可确认的卡片" in nudge
    assert "点卡片确认" in nudge and "不要重复那条确认指令" in nudge
    # ③ 结局事实：info = 已满足 + 后端结论原文在内。
    assert "方案里已经满足了" in nudge
    assert "当前方案里已经有 3 个专业组，本轮不需要调整方案" in nudge
    # ④ 动线 + 封闭式提问 + 不许原样重发同一提案。
    assert "下一步动线" in nudge
    assert "封闭式" in nudge
    assert "不要原样重发同一个提案" in nudge
    # ⑤ 助手消息：回合事件 + 落库；**不伪造用户消息**。
    assert [event["type"] for event in events] == ["turn.started"]
    assert store.agent_messages == [corrected]
    assert store.user_messages == []


@pytest.mark.asyncio
async def test_a_blocked_preview_carries_the_reason_verbatim() -> None:
    """blocked（被拒、无卡片）→ 同样跟话；原因原文（`blockingReason`）逐字喂进 nudge。"""
    codex = _ScriptedCodex(
        [{"responseType": "text", "message": "刚才这条要求这次没能落进方案，我说下为什么、怎么绕。"}]
    )
    gateway, store = _gateway(codex)
    events, emit = _collector()

    result = await _continue(
        gateway,
        status="blocked",
        preview={"blockingReason": "同档前置规则：暂不支持覆盖要求字段"},
        emit=emit,
    )

    assert result is not None
    assert len(codex.turns) == 1
    nudge = codex.turns[0][-1]["text"]
    assert "被校验拒绝了" in nudge
    assert "同档前置规则：暂不支持覆盖要求字段" in nudge
    assert "没有落成待确认" in nudge and "没有生成可确认的卡片" in nudge
    assert "替代路径" in nudge
    assert store.agent_messages == ["刚才这条要求这次没能落进方案，我说下为什么、怎么绕。"]
    assert store.user_messages == []


@pytest.mark.asyncio
async def test_a_preview_only_outcome_is_framed_as_reference_only() -> None:
    """preview_only（只出参考预览）→ 跟话把它框成"仅供参考、不能确认落地"。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "这次先给你参考口径，真要用我们再定。"}])
    gateway, _ = _gateway(codex)

    assert await _continue(gateway, status="preview_only") is not None

    nudge = codex.turns[0][-1]["text"]
    assert "参考预览" in nudge and "仅供参考、不能确认落地" in nudge
    assert "后端未给出具体说明" in nudge  # 没给 summary/blockingReason 时的兜底


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "pending", "applied", "unknown", ""])
async def test_statuses_outside_the_trigger_set_never_continue(status: str) -> None:
    """触发档只有 blocked/info/preview_only；ready（可确认卡片）等**维持现状**。

    ready 那一路模型收尾说"点卡确认"是对的——一个字节都不许动（与 applied 同此）。
    """
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, store = _gateway(codex)
    events, emit = _collector()

    assert await _continue(gateway, status=status or "none", emit=emit) is None

    assert codex.turns == []
    assert events == []
    assert store.agent_messages == []


@pytest.mark.asyncio
async def test_status_matching_is_case_and_space_insensitive() -> None:
    """状态比对先 normalize（大小写/空白）——Java 侧的大小写漂移不吃掉触发。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "纠正收尾。"}])
    gateway, _ = _gateway(codex)

    assert await _continue(gateway, status=" INFO ") is not None

    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_the_same_triggering_turn_never_continues_twice() -> None:
    """同一个触发回合重复到达 → 只跟一次（幂等按触发它的用户回合）。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "纠正一次。"}])
    gateway, _ = _gateway(codex)

    first = await _continue(gateway, status="info")
    second = await _continue(gateway, status="info")

    assert first is not None and second is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_a_later_turn_gets_its_own_correction() -> None:
    """另一个用户回合再次产出 info 预览 → **各自**跟自己的（收尾话术是回合事实）。"""
    codex = _ScriptedCodex(
        [
            {"responseType": "text", "message": "纠正第一轮的收尾。"},
            {"responseType": "text", "message": "纠正第二轮的收尾。"},
        ]
    )
    gateway, _ = _gateway(codex)

    assert await _continue(gateway, status="info", source_turn_id="turn-user-1") is not None
    assert await _continue(gateway, status="info", source_turn_id="turn-user-2") is not None

    assert len(codex.turns) == 2


@pytest.mark.asyncio
async def test_a_failed_continuation_is_reported_once_and_never_retried() -> None:
    """跟话回合自己失败：一条不许说"已提交/待确认"的措辞 + 零成本下一步；不重试、不循环。"""
    codex = _ScriptedCodex([{"__error__": "turn_failed"}])
    gateway, store = _gateway(codex)

    result = await _continue(gateway, status="blocked")

    assert result is not None and result["error"] == "turn_failed"
    assert result["reply"] == _PREVIEW_CONTINUATION_FAILURE_REPLY
    assert "没有生成可确认的卡片" in result["reply"]
    assert "已提交" not in result["reply"] and "待确认" not in result["reply"]
    assert "继续" in result["reply"]
    assert len(codex.turns) == 1
    assert store.agent_messages == []  # 失败不产助手消息
    # 不循环：同一个触发回合再来一次，还是不发第二轮。
    assert await _continue(gateway, status="blocked") is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_a_user_turn_that_landed_first_wins() -> None:
    """用户已经动了话头（水位前进）→ 让路：不跟话、不发任何事件。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, _ = _gateway(codex)
    events, emit = _collector()

    assert await _continue(gateway, status="info", watermark=1, emit=emit) is None

    assert codex.turns == []
    assert events == []


@pytest.mark.asyncio
async def test_a_busy_session_is_never_interleaved() -> None:
    """会话锁被占着（有回合在跑或在等）→ 不插队：直接放弃，不排队、不死锁。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, _ = _gateway(codex)
    lock = gateway._session_locks.setdefault(
        SessionKey(tenant_id="tenant-1", session_id="session-1"), __import__("asyncio").Lock()
    )

    async with lock:
        assert await _continue(gateway, status="info") is None

    assert codex.turns == []
