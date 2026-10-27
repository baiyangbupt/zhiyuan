"""确认之后的自动续接（2026-10-09 生效版 / 2026-10-13 失败版）：助手要接住这一轮的话头。

用户实测一（会话 10041981，10-09）：助手先承诺"确认成绩后我先按方向给你几个院校专业组
参考…"，用户点确认后只收到写死的"操作已处理。"——话头断了。
用户实测二（同一会话，10-13）："学费≤2 万"优先规则 preview=ready，用户打字确认后 apply
失败 `409 priority_target_not_in_plan`——失败后没有任何助手跟话，用户只见一张失败卡。

这里钉 `GatewayService.continue_after_action` 的七条：
① 触发档 = `applied` ∪ `failed`；`stale_state` / `cancelled` / `applying`（非终态）/
   `not_executable` 等维持现状（边界见 `continue_after_action` docstring）；
② 续接是**助手回合**：喂进去的是内部分隔标签包住的续接指令，
   **不落 user 消息**（transcript 里没有伪造的用户消息），产出落 agent 消息；
③ 失败版 nudge 必须带**原因原文**（`code: message`）并点名三样纪律：
   如实解释（翻业务语言）、给替代路径、封闭式提问；
④ 同一操作（proposalRef 为键）只续一次——重复结果照样不重复触发（applied/failed 同款）；
⑤ 续接回合自己失败：只返回一次带措辞的失败（生效版说"已生效"、失败版说"没成功"），
   不重试、不循环（再来一次调用也走台账）；
⑥ 用户已动话头（水位变了）→ 让路，不续接；
⑦ 会话锁被占着 → 不插队（既有串行语义优先），也不死锁。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.gateway.service import (
    CONTINUATION_CLOSE_TAG,
    CONTINUATION_OPEN_TAG,
    GatewayService,
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
    """按轮次给输出 ✓；每一轮的输入原样记下来（续接指令就在里面 ✓）。"""

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = list(outputs)
        self.turns: list[list[Any]] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-continuation"}}

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
            raise AssertionError("替身没有更多剧本：续接被多跑了一轮 ✗")
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
            thread_id="thr-continuation",
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
    status: str = "applied",
    ref: str = "pending-1",
    watermark: int = 0,
    emit=None,
    extra: dict[str, Any] | None = None,
):
    return await gateway.continue_after_action(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="cont-1",
        action_result={"actionStatus": status, "proposalRef": ref, **(extra or {})},
        user_turn_watermark=watermark,
        emit=emit,
    )


@pytest.mark.asyncio
async def test_an_applied_confirm_runs_exactly_one_continuation_turn() -> None:
    """applied → 恰好一轮续接：助手消息入流（turn.started ✓）并落库 ✓，且**没有**用户消息 ✓。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "我接着按方向给你几个院校专业组参考。"}])
    gateway, store = _gateway(codex)
    events, emit = _collector()

    result = await _continue(gateway, emit=emit)

    assert result is not None
    assert result["reply"] == "我接着按方向给你几个院校专业组参考。"
    # ① 恰好多跑了一轮（续接），且只一轮。
    assert len(codex.turns) == 1
    # ② 喂进去的最后一条是**内部续接指令**（带分隔标签、点明"已生效"、要求继续）。
    nudge = codex.turns[0][-1]["text"]
    assert nudge.startswith(CONTINUATION_OPEN_TAG)
    assert nudge.endswith(CONTINUATION_CLOSE_TAG)
    assert "已经生效" in nudge
    assert "不要再让用户确认同一件事" in nudge
    assert "pending-1" in nudge
    # ③ 助手消息：回合事件 + 落库（transcript 的助手那一侧）。
    assert [event["type"] for event in events] == ["turn.started"]
    assert store.agent_messages == ["我接着按方向给你几个院校专业组参考。"]
    # ④ **不伪造用户消息**：transcript 的用户那一侧一个字都没有。
    assert store.user_messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["stale_state", "cancelled", "applying", "conflict", "not_executable", "expired"],
)
async def test_actions_outside_the_trigger_set_never_continue(status: str) -> None:
    """触发档只有 applied/failed 两档；其余**维持现状**：没有续接回合，也没有事件。

    逐档理由见 `continue_after_action` docstring：cancelled 是用户自己的取消；stale_state
    （conflict 并进这一档）/expired 要的是刷新重来；applying **不是终态**（续接会提前占掉
    幂等台账）；not_executable 什么都没试过。
    """
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, store = _gateway(codex)
    events, emit = _collector()

    assert await _continue(gateway, status=status, emit=emit) is None

    assert codex.turns == []
    assert events == []
    assert store.agent_messages == []


@pytest.mark.asyncio
async def test_a_failed_confirm_runs_exactly_one_continuation_turn() -> None:
    """失败 → 同样恰好一轮续接（2026-10-13 缺口）：助手消息入流并落库，**没有**用户消息 ✓。

    现场复刻（会话 10041981 ✓）：apply `409 priority_target_not_in_plan` ✗，修前失败后
    一片安静 ✗；修后喂给模型的是**失败版 nudge** ✓——原因原文在内 ✓、三条纪律在内 ✓。
    """
    codex = _ScriptedCodex(
        [{"responseType": "text", "message": "这条优先要求当前方案里没有落点，我们换个口径。"}]
    )
    gateway, store = _gateway(codex)
    events, emit = _collector()

    result = await _continue(
        gateway,
        status="failed",
        emit=emit,
        extra={"code": "409", "message": "priority_target_not_in_plan: 当前方案没有命中优先目标"},
    )

    assert result is not None
    assert result["reply"] == "这条优先要求当前方案里没有落点，我们换个口径。"
    # ① 恰好一轮续接（失败也接，且只接一次）。
    assert len(codex.turns) == 1
    nudge = codex.turns[0][-1]["text"]
    # ② 失败版 nudge：分隔标签 + 明说**没有生效** + 原因原文逐字在内。
    assert nudge.startswith(CONTINUATION_OPEN_TAG)
    assert nudge.endswith(CONTINUATION_CLOSE_TAG)
    assert "执行失败" in nudge and "没有生效" in nudge
    assert "409: priority_target_not_in_plan: 当前方案没有命中优先目标" in nudge
    assert "pending-1" in nudge
    # ③ 三条纪律：如实解释（翻业务语言）/ 给替代路径 / 封闭式提问 / 不许原样重发提案。
    assert "如实解释" in nudge
    assert "替代路径" in nudge and "放宽口径" in nudge
    assert "封闭式" in nudge
    assert "不要原样重发同一个提案" in nudge
    # ④ 助手消息：回合事件 + 落库（transcript 的助手那一侧）；**不伪造用户消息**。
    assert [event["type"] for event in events] == ["turn.started"]
    assert store.agent_messages == ["这条优先要求当前方案里没有落点，我们换个口径。"]
    assert store.user_messages == []


@pytest.mark.asyncio
async def test_a_failed_result_without_a_reason_still_continues() -> None:
    """失败但后端没给 code/message：照续 ✓（措辞里有兜底说法 ✓），不许因此静默 ✗。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "这一步没成，我说下可能的方向。"}])
    gateway, _ = _gateway(codex)

    assert await _continue(gateway, status="failed") is not None

    nudge = codex.turns[0][-1]["text"]
    assert "后端未给出具体原因" in nudge


@pytest.mark.asyncio
async def test_upstream_strategy_failure_is_not_explained_as_confirmation_expiry() -> None:
    codex = _ScriptedCodex([{"responseType": "text", "message": "上游数据策略不可用，本次成绩没有更新。"}])
    gateway, _ = _gateway(codex)

    result = await _continue(
        gateway,
        status="failed",
        extra={"code": "84009", "message": "当前策略已失效，请刷新页面"},
    )

    assert result is not None
    nudge = codex.turns[0][-1]["text"]
    assert "上游志愿数据策略" in nudge
    assert "不是确认卡过期" in nudge
    assert "不是登录凭证失效" in nudge
    assert "核对取数模式" in nudge


@pytest.mark.asyncio
async def test_the_same_failed_result_never_continues_twice() -> None:
    """同一个操作失败结果重复到达 → 只续一次（幂等与 applied 同款）。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "接住失败。"}])
    gateway, _ = _gateway(codex)

    first = await _continue(gateway, status="failed", extra={"code": "409", "message": "x"})
    second = await _continue(gateway, status="failed", extra={"code": "409", "message": "x"})

    assert first is not None and second is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_the_same_operation_never_continues_twice() -> None:
    """同一个操作（proposalRef 为键）重复给结果 → 只续一次（幂等）。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "接上一步。"}])
    gateway, _ = _gateway(codex)

    first = await _continue(gateway)
    second = await _continue(gateway)

    assert first is not None and second is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_a_failed_continuation_is_reported_once_and_never_retried() -> None:
    """续接回合自己失败：返回一次带措辞的失败（确认本身**已生效**，别让用户以为失败），
    不重试、不循环——同一个操作再来一次也不跑。"""
    codex = _ScriptedCodex([{"__error__": "turn_failed"}])
    gateway, store = _gateway(codex)

    result = await _continue(gateway)

    assert result is not None and result["error"] == "turn_failed"
    assert "已经生效" in result["reply"] and "继续" in result["reply"]
    assert len(codex.turns) == 1
    assert store.agent_messages == []  # 失败不产助手消息 ✓
    # 不循环：同一个操作再来一次，还是不发第二轮。
    assert await _continue(gateway) is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_a_failed_continuation_after_a_failed_action_never_claims_success() -> None:
    """失败版续接自己崩了 → 措辞**不许说"已生效"** ✗（本次执行就是没成功），
    说清"哪一步没成"并给下一步动作 ✓；同样不重试、不循环 ✓。"""
    codex = _ScriptedCodex([{"__error__": "turn_failed"}])
    gateway, store = _gateway(codex)

    result = await _continue(gateway, status="failed", extra={"code": "409", "message": "x"})

    assert result is not None and result["error"] == "turn_failed"
    assert "已经生效" not in result["reply"]
    assert "没能执行成功" in result["reply"] and "继续" in result["reply"]
    assert len(codex.turns) == 1
    assert store.agent_messages == []
    assert await _continue(gateway, status="failed") is None
    assert len(codex.turns) == 1


@pytest.mark.asyncio
async def test_a_user_turn_that_landed_first_wins() -> None:
    """用户已经动了话头（水位前进）→ 让路：不续接、不发任何事件。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, _ = _gateway(codex)
    events, emit = _collector()

    assert await _continue(gateway, watermark=1, emit=emit) is None

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
        assert await _continue(gateway) is None

    assert codex.turns == []


@pytest.mark.asyncio
async def test_a_user_turn_starts_while_the_action_was_running() -> None:
    """点卡路径的水位：动作执行期间用户又发了一条（水位 +1）→ 回来时不续接。"""
    codex = _ScriptedCodex([{"responseType": "text", "message": "不该被用到"}])
    gateway, _ = _gateway(codex)

    baseline = gateway.user_turn_watermark(tenant_id="tenant-1", session_id="session-1")
    assert baseline == 0
    # 用户在动作执行中间发了一条普通消息（`handle_turn` 拿锁前 +1 ✓）。
    await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="ui-later",
        content="等等，先帮我看个别的",
        emit=None,
    )
    # 替身模型的输出不是动作，`handle_turn` 正常收尾；此刻水位已经前进。
    assert gateway.user_turn_watermark(tenant_id="tenant-1", session_id="session-1") == 1

    assert await _continue(gateway, watermark=baseline) is None
