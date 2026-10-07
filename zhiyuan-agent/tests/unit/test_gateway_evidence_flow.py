"""P1c-2：四态核验接进 Gateway 之后，六行分流表在**真实调用路径**上的表现。

与 `test_evidence_verification.py`（纯函数那一层）分开：这里验的是"接进去了没有、
接对没有"——核验器被调用几次、重查跑了几轮、整轮失败时**用户侧有没有兜底输出**。

那两条 fail-closed（`unknown` 与 Java 不可达）是重点：它们的失效方式都是"静默放宽"，
不写下来就没人会发现。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.gateway.service import GatewayService
from app.harness.binding import ThreadBinding


class FakeMessageStore:
    async def save_user_message(self, chat_session_id: str, content: str) -> int:
        return 1

    async def save_agent_message(self, chat_session_id: str, content: str, ws_type: str = "reply") -> int:
        return 2


@dataclass
class Verifier:
    """可数的核验器替身：`statuses` 是 id → 状态；不在表里的按 unknown（与真实现一致）。"""

    statuses: dict[str, str]
    calls: list[list[str]] = field(default_factory=list)

    async def __call__(self, *, tenant_id, chat_session_id, evidence_ids, thread_id=None):
        self.calls.append(list(evidence_ids))
        return {
            evidence_id: {
                "status": status,
                "sourceSystem": "gaotu.schoolMajorScoreLine",
                "paramsDigest": f"digest-{evidence_id}",
            }
            for evidence_id, status in self.statuses.items()
            if evidence_id in evidence_ids
        }


class CodexHarness:
    """按回合号返回预置输出；重查回合是第二次调用。"""

    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.turns: list[list] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-p1c2"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
        self.turns.append(input_items)
        return {"turn": {"id": f"turn-{len(self.turns)}"}}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.turns.append(input_items)
        payload = self.outputs[min(len(self.turns) - 1, len(self.outputs) - 1)]

        @dataclass
        class Collected:
            status: str
            output: dict
            events: list
            turn_id: str = "turn-1"
            payload: dict = field(default_factory=dict)

        return Collected(status="completed", output=payload["output"], events=payload.get("events", []))


def _ledger_record(evidence_id: str, *, status: str = "valid") -> dict:
    """**账本**里的记录形状（工具结果/快照那一侧）：带来源、摘要、状态。"""
    return {
        "evidenceId": evidence_id,
        "sourceLevel": "authoritative",
        "dataVersion": "2026.09.07",
        "sourceSystem": "gaotu.schoolMajorScoreLine",
        "paramsDigest": f"digest-{evidence_id}",
        "status": status,
        # 归属：校验器在 `strict_scope` 下要求账本记录带会话身份（与快照同一个会话）。
        "scope": {"tenantId": "tenant-1", "chatSessionId": "session-1"},
    }


def _output_ref(evidence_id: str) -> dict:
    """**模型输出**里的引用形状：只许契约里有的字段（`EvidenceRef` 是 `extra="forbid"`）。"""
    return {
        "evidenceId": evidence_id,
        "sourceLevel": "authoritative",
        "dataVersion": "2026.09.07",
    }


def _fact_output(evidence_id: str) -> dict:
    return {
        "responseType": "fact",
        "message": "招生事实",
        "evidenceRefs": [_output_ref(evidence_id)],
    }


def _text_output(evidence_id: str) -> dict:
    return {
        "responseType": "text",
        "message": "顺带提一句",
        "evidenceRefs": [_output_ref(evidence_id)],
    }


def _turn_payload(evidence_id: str, *, response_type: str = "fact") -> dict:
    """一个回合的载荷：模型输出引用 + **工具结果里带着这条证据**（账本从后者建）。

    两边都要有：输出里的引用是"模型说它用了这条"，事件里的记录是"这条确实被查出来了"。
    只给输出、账本里没有 → 那是 `evidence_not_found`，与本文件要测的分流表无关。
    """
    output = _fact_output(evidence_id) if response_type == "fact" else _text_output(evidence_id)
    return {
        "output": output,
        "events": [
            {"type": "mcpToolCall", "result": {"evidence": [_ledger_record(evidence_id)]}}
        ],
    }


def _snapshot() -> dict:
    return {
        "sessionId": "session-1",
        "version": 42,
        "phase": "candidate_exploration",
        "studentSummary": {"province": "浙江", "score": 650, "rank": 1000},
        "allowedCapabilities": ["catalog_read", "admission_read"],
    }


def _snapshot_with_evidence(record: dict) -> dict:
    """补录确认后的快照：Java 台账里的权威证据已经进了 `evidence`（逐字投影）。"""
    snapshot = _snapshot()
    snapshot["evidence"] = [record]
    return snapshot


def _model_citation(evidence_id: str) -> dict:
    """模型**转述**证据的形状（逐字抄自 2026-10-07 线上事故的终态正文）。

    只有 `evidenceId`/`sourceLevel`/`dataVersion` 与一个**查询参数** scope；
    `sourceSystem`/`paramsDigest` 抄不到——那正是与快照记录"看上去撞身份"的来源。
    """
    return {
        "evidenceId": evidence_id,
        "sourceLevel": "authoritative",
        "dataVersion": "2026.09.07",
        "scope": {"kind": "catalog_batch_options", "areaId": "330000", "batch": "第一段"},
        "observedAt": "2026-10-07T08:44:47+08:00",
        "limitations": ["仅覆盖该省批次设置与批次线，不含院校专业录取数据"],
    }


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr-p1c2",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read", "admission_read"}),
    )


def _gateway(
    codex: CodexHarness, verifier: Verifier | None, snapshot: dict | None = None
) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=None,
        message_store=FakeMessageStore(),
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: snapshot or _snapshot(),
        evidence_verifier=verifier,
    )


async def _turn(gateway: GatewayService) -> dict:
    return await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="ui-1",
        content="查一下某校的分数",
    )


@pytest.mark.asyncio
async def test_all_valid_proceeds_through_the_normal_chain() -> None:
    verifier = Verifier({"ev-1": "valid"})
    gateway = _gateway(CodexHarness([_turn_payload("ev-1")]), verifier)

    result = await _turn(gateway)

    assert result.get("output") is not None
    assert verifier.calls == [["ev-1"]]


@pytest.mark.asyncio
async def test_unknown_fails_the_whole_turn_with_no_fallback_output() -> None:
    """台账里没有 = 没发生过：整轮作废，**用户侧没有任何自然语言兜底输出**。

    光断言错误码不够——这条的实质是"不留兜底"，所以这里断言没有 `output`、
    没有事件、也没有模型正文。
    """
    verifier = Verifier({})  # 谁都不在台账里
    gateway = _gateway(CodexHarness([_turn_payload("ev-ghost")]), verifier)

    result = await _turn(gateway)

    assert result["error"].startswith("evidence_not_authoritative:"), result["error"]
    assert "ev-ghost" in result["error"], "错误里必须带上是哪条证据"
    assert result.get("output") is None
    assert result.get("events") == []


@pytest.mark.asyncio
async def test_stale_on_a_fact_output_triggers_exactly_one_recheck() -> None:
    """失效是正常演进，给一次重查机会；**恰好一次**，不是"小于等于"。"""
    verifier = Verifier({"ev-old": "stale", "ev-new": "valid"})
    codex = CodexHarness([_turn_payload("ev-old"), _turn_payload("ev-new")])
    gateway = _gateway(codex, verifier)

    result = await _turn(gateway)

    assert result.get("output") is not None
    assert len(codex.turns) == 2, "应恰好重查一次"
    assert verifier.calls == [["ev-old"], ["ev-new"]]
    assert "重新取数" in json.dumps(codex.turns[1], ensure_ascii=False)


@pytest.mark.asyncio
async def test_still_stale_after_one_recheck_fails_closed() -> None:
    """第二次仍失效 → 整轮作废。**不循环**：同样参数再查一遍是确定性操作，再试无益。"""
    verifier = Verifier({"ev-old": "stale"})
    codex = CodexHarness([_turn_payload("ev-old")])
    gateway = _gateway(codex, verifier)

    result = await _turn(gateway)

    assert result["error"].startswith("evidence_recheck_failed:"), result["error"]
    assert result.get("output") is None
    assert len(codex.turns) == 2, "重查只许一次"


@pytest.mark.asyncio
async def test_stale_on_prose_is_rechecked_too() -> None:
    """散文里引用失效证据也要重查——2026-09-22 作废了"非 fact 只剥离"那一行。

    理由是实测的：澄清/散文照样在正文里报数字，剥离引用挡不住用户看见旧值。
    """
    verifier = Verifier({"ev-old": "stale", "ev-new": "valid"})
    codex = CodexHarness([_turn_payload("ev-old", response_type="text"), _turn_payload("ev-new")])
    gateway = _gateway(codex, verifier)

    result = await _turn(gateway)

    assert result.get("output") is not None
    assert len(codex.turns) == 2, "应重查一次"
    assert verifier.calls == [["ev-old"], ["ev-new"]]


@pytest.mark.asyncio
async def test_java_unreachable_fails_the_turn_and_never_lets_output_through() -> None:
    """第六张表最后一行：验证不了就不能盖权威章。**不放行**。"""

    class Unreachable:
        async def __call__(self, **kwargs):
            raise RuntimeError("connection refused")

    gateway = _gateway(CodexHarness([_turn_payload("ev-1")]), Unreachable())

    result = await _turn(gateway)

    assert result["error"].startswith("evidence_verification_unavailable:"), result["error"]
    assert result.get("output") is None


@pytest.mark.asyncio
async def test_without_a_verifier_the_turn_is_unchanged() -> None:
    """没配核验器（本地最小栈/单测）＝不核验。这条同时是"接进去没有"的对照：
    没有它，上面每一条都可能是因为核验根本没被调用而"通过"。"""
    gateway = _gateway(CodexHarness([_turn_payload("ev-1")]), None)

    result = await _turn(gateway)

    assert result.get("output") is not None


@pytest.mark.asyncio
async def test_snapshot_evidence_cited_by_the_model_does_not_fail_the_turn() -> None:
    """2026-10-07 事故回归：**补录确认之后的下一轮**，模型引用快照里的证据。

    线上形态（会话 10041955）：补录成绩确认后，下一轮模型在终态正文里引用了
    快照中的批次线证据（转述里没有 `sourceSystem`/`paramsDigest`），本回合事件里
    **没有**对应的工具结果——`merge_evidence` 拿"转述"去比"原件"的稳定身份五元组，
    判成 `evidence_identity_conflict` → 整轮失败（`recoverable=False`，
    用户只看到"当前对话引擎暂时不可用"）。

    这条把形状钉死：`evidence` 在快照里、引用在 AgentMessage 正文里（`_collect_records`
    从那里挖），核验器说 valid——回合必须正常走完，且账本里留给校验的是**快照那份**。
    """
    evidence_id = "ev-batch-1"
    snapshot_record = {
        "evidenceId": evidence_id,
        "sourceLevel": "authoritative",
        "sourceSystem": "gaotu.batchList",
        "paramsDigest": "digest-batch",
        "dataVersion": "2026.09.07",
        "scope": {"tenantId": "tenant-1", "chatSessionId": "session-1"},
        "observedAt": "2026-10-07T08:44:47+08:00",
        "limitations": [],
    }
    output = {
        "responseType": "text",
        "message": "补录已生效，批次线按已核验证据回答。",
        "evidenceRefs": [_model_citation(evidence_id)],
    }
    payload = {
        "output": output,
        # **只有模型自己的转述**——没有工具结果给这条证据背书（线上失败那一轮正是如此）。
        # 正文是原始 TurnOutput JSON（与真 codex 的 AgentMessage 一致），`_collect_records`
        # 会把它解析出来、把 `evidenceRefs` 当成"本回合证据"。
        "events": [
            {
                "type": "item_completed",
                "item": {
                    "type": "AgentMessage",
                    "id": "msg-1",
                    "text": json.dumps(output, ensure_ascii=False),
                },
            }
        ],
    }
    verifier = Verifier({evidence_id: "valid"})
    gateway = _gateway(
        CodexHarness([payload]), verifier, snapshot=_snapshot_with_evidence(snapshot_record)
    )

    result = await _turn(gateway)

    assert result.get("error") is None, result.get("error")
    assert result.get("output") is not None
    assert verifier.calls == [[evidence_id]]


@pytest.mark.asyncio
async def test_recheck_round_gets_the_same_progress_callbacks_as_the_first_round() -> None:
    """重查轮必须和首轮拿到**同一份**回调（2026-09-23 复核第 2 项）。

    不传的后果有两层：浏览器收不到重查过程的实时通知（只能在回合结束后一次性拿到）；
    `on_turn_started` 是把 native turn 绑到会话运行时的唯一入口，缺了它
    `turn/steer`、`turn/interrupt` 会指到**已经结束的首轮**。
    """
    seen: list[list[str]] = []

    class ProgressHarness(CodexHarness):
        """把收到的回调名记下来，并按真实 harness 的方式把它们调起来。"""

        async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
            seen.append(sorted(kwargs))
            on_started = kwargs.get("on_turn_started")
            if on_started is not None:
                await on_started(f"native-{len(seen)}")
            return await super().start_turn_and_collect(thread_id, input_items, output_schema)

    class Runtime:
        def __init__(self) -> None:
            self.bindings: list[tuple] = []

        def bind_codex_turn(self, key, ui_turn_id, codex_turn_id) -> None:
            self.bindings.append((key, ui_turn_id, codex_turn_id))

    async def emit(_event: dict) -> None:
        return None

    verifier = Verifier({"ev-old": "stale", "ev-new": "valid"})
    codex = ProgressHarness([_turn_payload("ev-old"), _turn_payload("ev-new")])
    gateway = _gateway(codex, verifier)
    gateway.session_runtime = Runtime()

    result = await gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="ui-1",
        content="查一下某校的分数",
        emit=emit,
    )

    assert result.get("output") is not None
    assert len(codex.turns) == 2, "应恰好重查一次"
    assert len(seen) == 2, "首轮与重查轮各一次 collect"
    assert seen[0] == seen[1], f"重查轮的回调必须与首轮一致：{seen}"
    assert "on_notification" in seen[1] and "on_turn_started" in seen[1]
    assert len(gateway.session_runtime.bindings) == 2, "重查轮的 native turn 也要绑上"


@pytest.mark.asyncio
async def test_recheck_without_a_collect_harness_returns_none_instead_of_the_ack() -> None:
    """只有 `start_turn` 的 harness：重查**不放行**（2026-09-23 复核第 1 项）。

    `start_turn` 只发 `turn/start` 就返回启动确认（`app/harness/codex.py`），那个 ack
    不是回合结果；把 `inProgress` 当结果往下走，等于用"还没生成完"骗过重查判定。
    正确行为是返回 `None`——由调用方按 `evidence_recheck_failed` 整轮作废。
    """

    class AckOnlyHarness:
        def __init__(self) -> None:
            self.calls = 0

        async def start_turn(self, thread_id, input_items, output_schema=None):
            self.calls += 1
            return {"turn": {"id": f"native-{self.calls}", "status": "inProgress"}}

    codex = AckOnlyHarness()
    service = object.__new__(GatewayService)
    service.codex = codex

    result = await service._recheck_turn("thread-1", "重查指令")

    assert result is None, "启动确认不许当回合结果"
    assert codex.calls == 0, "连 start_turn 都不该被调——它等不到终态"
