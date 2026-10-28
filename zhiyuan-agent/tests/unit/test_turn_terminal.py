"""回合收尾：**失败必须让用户看得见** ✓✓——这条是 F15 在真栈上追出来的。

病在两处不对称 ✗：老信封那条路有 `recoverable.error` 的映射 ✓，V1 这条**无条件**发
`assistant.completed` ✗；而失败时 `result` 里没有 `reply` ✗ → `message` 变空串 ✗ →
前端"有终态且有答案文本"的渲染条件不成立 ✓ → 用户那边**整轮静默** ✗（页面快照实证 ✓）。
"""
from types import SimpleNamespace

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
    # **失败不许报 completed** ✗✓：这一支原来与成功分支发同一个写死的 payload ✗，
    # 于是一次解析失败在终态上长得和"一切正常"一模一样 ✓。降级值取 harness 对原生
    # 失败终态的同一映射（`app/harness/codex.py:339-345` ✓）。
    assert events[1]["payload"] == {
        "executionStatus": "failed",
        "toolStatus": "failed",
        "runtimeStatus": "native",
    }
    # 失败时**没有** assistant.completed ✓：空答案帧会让前端渲染出空白气泡 ✓。
    assert "assistant.completed" not in [event["type"] for event in events]


@pytest.mark.asyncio
async def test_score_update_business_rejection_reaches_the_user_not_the_generic_text() -> None:
    """补录被后端**业务性拒绝**时，用户要看到 Java 的原文（2026-10-06 实测：空会话补录
    被 Java 110「请选择批次后再创建会话」拒了，而用户看到的只有"当前对话引擎暂时不可用"
    ——可行动的下一步被通用文案吞掉）。技术细节仍留在 `code` 里 ✓；其它错误一律通用文案 ✓。"""
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "error": "score_update_unavailable: 请选择批次后再创建会话",
            "reply": "请选择批次后再创建会话",
        },
        session_id="900047",
    )

    payload = events[0]["payload"]
    assert payload["message"] == "请选择批次后再创建会话"
    assert "score_update_unavailable" in payload["code"]

    # 通用失败仍是通用文案（不外泄内部细节）。
    events, emit = _collector()
    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={"error": "output_schema_invalid: responseType", "reply": _RECOVERABLE_TURN_FAILURE},
        session_id="900047",
    )
    assert events[0]["payload"]["message"] == _RECOVERABLE_TURN_FAILURE


def test_the_compat_lane_carries_the_score_update_reason_too() -> None:
    """老信封那条路（`_native_reply_frame`）同样把原因带给用户 ✓——
    两条路的文案都取网关算好的 `reply`，不许一边有一边没有 ✓。"""
    from app.server import _native_reply_frame

    frame = _native_reply_frame(
        {"error": "score_update_unavailable: 请选择批次后再创建会话", "reply": "请选择批次后再创建会话"},
        "900047",
    )

    assert frame["type"] == "recoverable.error"
    assert "请选择批次后再创建会话" in frame["content"]


@pytest.mark.asyncio
async def test_a_successful_turn_still_emits_the_answer() -> None:
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit, channel=channel, result={"reply": "答案"}, session_id="900047"
    )

    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]
    assert events[0]["payload"]["message"] == "答案"
    # 没有观测（缺 `output` ✓）时按最保守的默认值发 ✓——与合成器的默认一致 ✓，
    # 但**不许**把失败冒充成 completed ✗（失败支在上面已覆盖 ✓）。
    assert events[1]["payload"] == {
        "executionStatus": "completed",
        "toolStatus": "completed",
        "runtimeStatus": "native",
    }


@pytest.mark.asyncio
async def test_a_partial_turn_reports_its_real_status_not_completed() -> None:
    """**终态取真实结果** ✓✓：网关早把状态算好了 ✓（`output.executionStatus` 经
    `synthesize_execution_status` **只降不升** ✓），写死 `completed` 等于在最后一步
    又升回去 ✗——用户要求读+写、系统只做了读，界面照样报"完成" ✓✗。
    `limitations` 也要原样带给用户 ✓（它就是"哪里没做到"的说明 ✓）。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "reply": "先给你能查到的部分。",
            "output": {
                "message": "先给你能查到的部分。",
                "responseType": "text",
                "executionStatus": "partial",
                "limitations": ["部分省份数据未覆盖"],
            },
            "trace": {"batchReport": {"status": "partial"}},
        },
        session_id="900047",
    )

    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]
    answer = events[0]["payload"]
    assert answer["executionStatus"] == "partial"
    assert answer["limitations"] == ["部分省份数据未覆盖"]
    assert events[1]["payload"] == {
        "executionStatus": "partial",
        "toolStatus": "partial",
        "runtimeStatus": "native",
    }


@pytest.mark.asyncio
async def test_tools_can_succeed_while_the_request_is_blocked() -> None:
    """**两个问题不许互相推导** ✓✓：`toolStatus` 是"这些调用成功了吗" ✓、
    `executionStatus` 是"用户的诉求满足了吗" ✓——工具全绿而诉求被阻断是常态
    （比如数据缺失 ✓），把 toolStatus 抄成 executionStatus ✗ 会让前端以为
    "工具都成功 ⇒ 诉求已满足" ✓✗，与合成器"只降不升"的方向正好相反 ✓。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "reply": "这一问需要先把省份补上。",
            "output": {
                "responseType": "clarification",
                "executionStatus": "blocked",
                "limitations": ["缺少省份信息，无法给出分数线"],
            },
            "trace": {"batchReport": {"status": "completed"}},
        },
        session_id="900047",
    )

    terminal = events[-1]
    assert terminal["type"] == "turn.completed"
    assert terminal["payload"] == {
        "executionStatus": "blocked",
        "toolStatus": "completed",  # 工具都成功了 ✓——但它抬不动诉求 ✓
        "runtimeStatus": "native",
    }


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


def test_the_plan_lifecycle_impact_rides_inside_the_diff() -> None:
    """方案调整卡的 `impact`（确认前不动、确认后写入本会话并重新生成）要进 `diff` ✓。

    它是卡面**唯一**说明"确认后到底发生什么"的字段（summary 只说本次替换/移出多少 ✗）；
    白名单漏了它 → 卡上没有任何生命周期说明 ✓（A2 卡面文案等于没落地）。
    """
    payload = _proposal_preview_payload(
        {
            "proposalRef": "pending-scope-1",
            "sourceVersion": 24,
            "title": "只保留“安徽”的调整预览",
            "summary": "当前方案中有 2 个专业组符合“安徽”……",
            "status": "ready",
            "requiresConfirmation": True,
            "impact": "确认前不会改动当前方案；确认后这条范围要求会写入本会话的报考要求，并按它重新生成、刷新方案。",
        }
    )

    assert payload["diff"]["impact"].startswith("确认前不会改动当前方案")
    assert "写入本会话" in payload["diff"]["impact"]


def test_the_score_update_summary_rides_inside_the_diff() -> None:
    """补录卡的结构化那份（`scoreUpdate`）要进 `diff` ✓✓：它是**卡片渲染明细行**的输入
    （省份/科类/批次/各科/总分/位次 ✓），来源是 Java 按合并后成绩算的 `scoreSummary` ✓。
    白名单漏了它 → 卡片只剩一句话摘要 ✓（用户核对不了"系统到底要写哪些字段" ✗）。
    """
    summary = {"provinceName": "浙江省", "totalScore": 641, "totalScorePos": 3100}

    payload = _proposal_preview_payload(
        {
            "proposalRef": "pending-score-1",
            "sourceVersion": 1,
            "title": "更新成绩",
            "summary": "浙江省 · 总分 641",
            "status": "pending",
            "requiresConfirmation": True,
            "scoreUpdate": summary,
        }
    )

    assert payload["proposalRef"] == "pending-score-1"
    assert payload["diff"]["scoreUpdate"] == summary
    assert payload["diff"]["requiresConfirmation"] is True


@pytest.mark.asyncio
async def test_a_failed_action_result_carries_the_reason_to_the_card() -> None:
    """**失败不许静默** ✓✓（110 / 40904 / 84009 / -1 …）：`code`/`message` 原样带给前端 ✓
    ——白名单两者都放行 ✓（`conversationEvents.mjs` ✓）。只说"未生效"的话，
    用户只能反复点同一个确认 ✗，排障也没有锚点 ✗。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "reply": "这次确认没有生效。",
            "actionResult": {
                "actionStatus": "failed",
                "proposalRef": "pending-score-1",
                "code": "84009",
                "message": "上游策略校验未通过",
                "actualChanges": {},
            },
            "snapshotVersion": 3,
        },
        session_id="900047",
    )

    payload = events[0]["payload"]
    assert events[0]["type"] == "conversationAction.result"
    assert payload["actionStatus"] == "failed"
    assert payload["code"] == "84009"
    assert payload["message"] == "上游策略校验未通过"
    assert payload["workspaceVersion"] == 3


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
    assert set(payload) <= {
        "proposalRef",
        "actionStatus",
        "newStateVersion",
        "workspaceVersion",
        "code",
        "message",
        "requiresWorkspaceReload",
    }
    assert payload["actionStatus"] == "cancelled"
    assert payload["workspaceVersion"] == 3
    # Detailed state is fetched independently; large reviews must not overflow
    # the event store and lose this confirmation receipt.
    assert payload["requiresWorkspaceReload"] is True
    assert "actualChanges" not in payload
    assert "reviewState" not in payload


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


@pytest.mark.asyncio
async def test_the_terminal_judges_v1_by_the_sessions_current_connection() -> None:
    """通道判定按**收尾那一刻**的会话当前连接 ✓✓，不是入队时刻捕获的那条 ✗。

    捕获的那条可能已经被顶替（用户重连/刷新 ✓）：继续按它判，新 UI 那条连接会被
    当成老 UI ✗ → 只收到老信封帧 ✓，而新 UI 的 reducer 判否 ✗ → 答案与"已生效"都到不了 ✓✗。
    """
    captured = _Channel(uses_v1=False)  # 入队时刻那条：老 UI 形态
    current = _Channel(uses_v1=True)  # 收尾时刻的会话当前连接：新 UI 形态
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=captured,
        result={"reply": "答案"},
        session_id="900047",
        channel_resolver=lambda: current,
    )

    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]
    assert captured.frames == []  # 老信封那条帧不许再发到旧连接上 ✓
    assert len(current.frames) == 1  # 终态的老信封帧照旧发（新连接自己判否 ✓）

    # 反方向同理：捕获的是新 UI、当前连接已经是老 UI → 只发老信封帧 ✓，不发 V1 ✓。
    captured, current = _Channel(uses_v1=True), _Channel(uses_v1=False)
    events, emit = _collector()
    await _emit_turn_terminal(
        emit=emit,
        channel=captured,
        result={"reply": "答案"},
        session_id="900047",
        channel_resolver=lambda: current,
    )
    assert events == []
    assert len(current.frames) == 1

    # 没有当前连接（用户全关了页面）→ 退回捕获的那条 ✓（行为与从前一致 ✓）。
    captured, events, emit = _Channel(uses_v1=True), *_collector()
    await _emit_turn_terminal(
        emit=emit,
        channel=captured,
        result={"reply": "答案"},
        session_id="900047",
        channel_resolver=lambda: None,
    )
    assert [event["type"] for event in events] == ["assistant.completed", "turn.completed"]


@pytest.mark.asyncio
async def test_an_action_result_is_emitted_even_when_the_turn_also_failed() -> None:
    """`execute` 已回终局、收尾又出别的问题时，结果事件**照样进流** ✓✓。

    不变量（任务书）：只要 execute 回了终局（applied/cancelled/failed ✓），
    `conversationAction.result` 就必须进事件流（可丢帧、不可丢流 ✓）——
    它是"这次写入算不算数"的唯一凭据 ✓；漏了它，库里已经落地的改动在页面上
    永远停在"待确认" ✗（用户只能反复点同一个确认 ✓✗）。
    """
    channel = _Channel(uses_v1=True)
    events, emit = _collector()

    await _emit_turn_terminal(
        emit=emit,
        channel=channel,
        result={
            "reply": "",
            "error": "gateway_failure",
            "actionResult": {"actionStatus": "applied", "proposalRef": "pending-1", "code": "0"},
        },
        session_id="900047",
    )

    assert [event["type"] for event in events] == [
        "conversationAction.result",
        "recoverable.error",
        "turn.completed",
    ]
    assert events[0]["payload"]["actionStatus"] == "applied"
    assert events[0]["payload"]["proposalRef"] == "pending-1"


def test_the_attempted_rule_brief_rides_inside_the_diff() -> None:
    """被拒（`blocked`）卡上的人话摘要（`attemptedRuleBrief` ✓）要进 `diff`：
    它是"模型本来想调整什么"的唯一可读出处（`blockingReason` 是 Java 校验原文 ✗）。
    白名单漏了它 → 卡片只剩一句读不懂的拒单原因 ✗；只加在 blocked 卡上（正常卡不长字段 ✓）。
    """
    payload = _proposal_preview_payload(
        {
            "proposalId": "ugp_blocked",
            "sourceVersion": 3,
            "status": "blocked",
            "blockingReason": "同档前置规则：暂不支持非排他覆盖要求字段：location.xxx",
            "attemptedRuleBrief": "地域：北方/北京/上海",
        }
    )

    assert payload["diff"]["status"] == "blocked"
    assert payload["diff"]["attemptedRuleBrief"] == "地域：北方/北京/上海"


# ─────────────────────────────────────────────────────────────────────────────
# 动作收尾的**异常**分支（F13 的异常变体）：结果事件与 `recoverable.error` 都不许缺 ✓✓
#
# 修前（`_run_action_work` 的 `except` 只有 `logger.exception` ✗）：执行侧出意外时
# 用户那边**一条事件都没有** ✓——卡停在"待确认" ✓、重连也补不出来 ✓（结果事件与
# 连接无关 ✗✓ 的不变量，在异常这条路上漏了 ✓）。下面两条把它钉住 ✓。
# ─────────────────────────────────────────────────────────────────────────────


class _ExplodingChannel:
    """收尾发射中途炸掉的连接：`uses_v1` 一读就抛（终态发射的第一行就要它 ✓）。"""

    @property
    def uses_v1(self) -> bool:
        raise RuntimeError("channel gone")


def _action_msg(proposal_ref: str = "pending-1"):
    return SimpleNamespace(
        session_id="900047",
        conversation_action={
            "actionType": "confirm_proposal",
            "proposalRef": proposal_ref,
            "expectedSourceVersion": 0,
            "intent": "explicit",
        },
    )


@pytest.mark.asyncio
async def test_an_exception_in_the_action_work_reports_a_failed_result(monkeypatch) -> None:
    """异常分支必须发 `recoverable.error` + `conversationAction.result(failed)` ✓✓。

    只发错误不给结果 ✗：卡会一直停在"待确认"（用户只能反复点 ✓✗）；
    只给结果不给错误 ✗：这轮到底怎么了在时间线上没有锚点 ✓。
    """
    import app.server as server

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_run_native_turn", _boom)
    events, emit = _collector()

    await server._run_action_work(
        SimpleNamespace(), _action_msg(), "1", "turn-confirm", emit, _Channel(uses_v1=True)
    )

    assert [event["type"] for event in events] == ["recoverable.error", "conversationAction.result"]
    error = events[0]["payload"]
    assert error["code"] == "action_execution_exception"
    result = events[1]["payload"]
    assert result["actionStatus"] == "failed"
    assert result["code"] == "action_execution_exception"
    # 卡是按 `proposalRef` 找自己的结果事件的 ✓——入站动作上的 ref 要原样带 ✓。
    assert result["proposalRef"] == "pending-1"
    # 措辞是"未能确认"而不是"一定没生效" ✓：异常可能发生在 Java 已受理之后 ✓。
    assert "未能确认" in result["message"]


@pytest.mark.asyncio
async def test_the_failure_fallback_never_contradicts_a_result_that_already_went_out(monkeypatch) -> None:
    """真结果已经出站时**只**补 `recoverable.error` ✗✓：再补一条 failed 会与"已生效"矛盾 ✓。"""
    import app.server as server

    async def _applied(*args, **kwargs):
        return {
            "reply": "操作已处理。",
            "events": [],
            "actionResult": {"actionStatus": "applied", "proposalRef": "pending-1", "code": "0"},
            "snapshotVersion": 3,
        }

    monkeypatch.setattr(server, "_run_native_turn", _applied)
    events, emit = _collector()

    await server._run_action_work(
        SimpleNamespace(), _action_msg(), "1", "turn-confirm", emit, _ExplodingChannel()
    )

    assert [event["type"] for event in events] == ["recoverable.error"], \
        "已出站的结果才是权威终局：兜底不许把它反过来 ✗"
