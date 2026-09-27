"""回合收尾：**失败必须让用户看得见** ✓✓——这条是 F15 在真栈上追出来的。

病在两处不对称 ✗：老信封那条路有 `recoverable.error` 的映射 ✓，V1 这条**无条件**发
`assistant.completed` ✗；而失败时 `result` 里没有 `reply` ✗ → `message` 变空串 ✗ →
前端"有终态且有答案文本"的渲染条件不成立 ✓ → 用户那边**整轮静默** ✗（页面快照实证 ✓）。
"""
import pytest

from app.server import _RECOVERABLE_TURN_FAILURE, _emit_turn_terminal, _proposal_preview_payload


class _Channel:
    def __init__(self, *, uses_v1: bool) -> None:
        self.uses_v1 = uses_v1
        self.frames: list[object] = []

    async def emit_frame(self, frame) -> None:
        self.frames.append(frame)


def _collector() -> tuple[list[dict], object]:
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    return events, emit


@pytest.mark.asyncio
async def test_a_failed_turn_emits_a_recoverable_error_not_an_empty_answer() -> None:
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={"error": "output_schema_invalid: responseType"},
        session_id="900047",
    )

    assert [event["type"] for event in events] == ["recoverable.error", "turn.completed"]
    payload = events[0]["payload"]
    # 键名照前端白名单 ✓：多一个键就会被丢掉 ✓（白名单只放 code/message ✓）。
    assert set(payload) == {"code", "message"}
    assert payload["message"] == _RECOVERABLE_TURN_FAILURE  # **不许空着** ✓
    assert "output_schema_invalid" in payload["code"]  # 技术细节留给 code ✓


@pytest.mark.asyncio
async def test_a_successful_turn_still_emits_the_answer() -> None:
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit, channel=channel, result={"reply": "答案"}, session_id="900047"
    )

    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]
    assert events[0]["payload"]["message"] == "答案"


@pytest.mark.asyncio
async def test_a_proposal_preview_is_emitted_as_an_event_before_the_answer() -> None:
    """提案预览**必须发成事件** ✓✓——网关早就算好了它 ✓（`proposalPreview` 在结果里 ✓），
    而这里原本只发 `assistant.completed` ✗ → 页面上永远看不到提案卡 ✓，
    且**不会报错** ✓（外面看像"链路没走到" ✗）。实测：Java `prepare … 200` ✓、
    事件流里却一条 `proposal.preview` 都没有 ✓。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={"reply": "整理好了", "proposalPreview": {"proposalRef": "p-1", "sourceVersion": 1}},
        session_id="900047",
    )

    assert [event["type"] for event in events] == [
        "proposal.preview",  # 卡在前 ✓：用户先看到"要不要采纳" ✓，再看答案 ✓
        "assistant.completed",
        "turn.completed",
    ]
    assert events[0]["payload"]["proposalRef"] == "p-1"


def test_the_mapped_ref_wins_over_the_compiler_id() -> None:
    """**`proposalRef` 优先于 `proposalId`** ✓✓：网关会把 `proposalRef` 换成**待确认那一条**
    的 ref ✓（确认时服务端拿它核对 ✓），而 Java 的预览里两者**同时**在 ✓——
    映射写成 `proposalId` 优先的话 ✓，会把网关的覆盖**撤销掉** ✗（实测：版本换成 1 ✓、
    ref 却始终是 `ugp_…` ✓，确认照旧 `stale_state` ✓）。
    """
    payload = _proposal_preview_payload(
        {"proposalId": "ugp_compiler", "proposalRef": "00f9bf22-pending", "sourceVersion": 1}
    )
    assert payload["proposalRef"] == "00f9bf22-pending"


def test_the_preview_is_translated_into_the_frontend_contract_shape() -> None:
    """**翻译归网关** ✓✓：Java 的预览字段名与前端白名单**对不上** ✗
    （实测 Java 给 `proposalId`/`title`/`summary`/`status`/`blockingReason` ✓，
    白名单要 `proposalRef`/`diff`/`sourceVersion`/`expiresAt` ✗）——
    不翻译的话 `sanitizeV1Payload` 会把它过滤成 `{}` ✓，页面拿到的是**空卡** ✓。
    """
    payload = _proposal_preview_payload(
        {
            "proposalId": "ugp_c8a8f81b",
            "sourceVersion": 0,
            "title": "补齐到 80 个志愿的调整预览",
            "summary": "canonical solver 输入超过 M1 受控复杂度上限。",
            "status": "blocked",
            "strategy": "fill_missing_count",
            "blockingReason": "…",
            "solverResult": {"internal": "不该给前端看"},
            "solverInputDigest": "不该给前端看",
        }
    )

    assert set(payload) <= {"proposalRef", "diff", "sourceVersion", "expiresAt"}
    assert payload["proposalRef"] == "ugp_c8a8f81b"
    assert payload["sourceVersion"] == 0
    assert payload["diff"]["status"] == "blocked"
    assert payload["diff"]["title"].startswith("补齐到")
    # **求解器内部形状不许过** ✓：它们对用户没意义，还会让载荷随求解器版本漂移 ✓。
    assert "solverResult" not in payload["diff"]
    assert "solverInputDigest" not in payload["diff"]


@pytest.mark.asyncio
async def test_a_conversation_action_result_is_emitted() -> None:
    """采纳/放弃的结果**必须发成事件** ✓✓——否则卡片停在"待确认" ✗
    （实测：点了放弃 ✓，事件流里只有 `assistant.completed("操作已处理。")` ✓）。
    键名照前端白名单 ✓；`workspaceVersion` 取**外层**的 `snapshotVersion` ✓。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "reply": "操作已处理。",
            "actionResult": {"actionStatus": "cancelled", "proposalRef": "ugp_1", "actualChanges": {}},
            "snapshotVersion": 3,
        },
        session_id="900047",
    )

    assert [event["type"] for event in events] == [
        "conversationAction.result",
        "assistant.completed",
        "turn.completed",
    ]
    payload = events[0]["payload"]
    assert set(payload) <= {"proposalRef", "actionStatus", "newStateVersion", "workspaceVersion"}
    assert payload["actionStatus"] == "cancelled"
    assert payload["workspaceVersion"] == 3
    assert "actualChanges" not in payload  # 白名单没它的位置 ✓，不带 ✓


@pytest.mark.asyncio
async def test_no_preview_event_when_the_gateway_did_not_produce_one() -> None:
    """没有预览时**不许**凭空发一条 ✓（空卡片比没有卡片更糟 ✗）。"""
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit, channel=channel, result={"reply": "答案", "proposalPreview": None}, session_id="900047"
    )

    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]


@pytest.mark.asyncio
async def test_the_old_envelope_lane_gets_a_frame_and_no_v1_events() -> None:
    """compat 路由服务的是老 UI ✓：给它发 V1 事件是噪声 ✗。"""
    channel = _Channel(uses_v1=False)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit, channel=channel, result={"reply": "答案"}, session_id="900047"
    )

    assert events == []
    assert len(channel.frames) == 1
