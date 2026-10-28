"""发展方向（career_update 动作族，career v1「完整落库」）：网关准备段与全链。

链路：模型说"用户表达了什么方向"（`CareerUpdateRequest` 草稿）→ 网关把预览物化成
pending（**agent 侧**：Java 的 `PendingPlanningCommandBizService` 没有 profile-patch
命令类型）→ 用户确认（点卡/打字）→ 两段式 claim→execute → 执行体**读-合并-写**
`latentProfile.futureDevelopment.careerTypes`（整字段赋值纪律：先读回全文）→
结果回写 pending（complete）→ `conversationAction.result` 入流。

这里钉六件事：
① **中文规范标签唯一落库**：契约层归一以后，网关落库前再归一一次——英文槽位名 /
   中文近义混着来也落四个规范标签；归不了的入口在契约层就拒（不静默丢弃 ✗）；
② 写模式物化 pending（kind=career_update，operationId **生产者落下**、按回合派生
   ——同一回合重试是重放）；只读模式只出预览、**不给确认按钮** ✓；
③ guard 对不上就 `stale_state`（拿旧版本确认一个已经变化的会话更糟 ✗）；
④ 全链接缝：prepare 落下的 pending 草稿喂回执行器 → 确认 → PATCH 被调用（既有
   `industryPreferences` 不许被整字段赋值抹掉 ✗）→ 结果 applied（版本在
   `data.version` 上 ✓）；
⑤ 幂等：要落的方向已在库里 → **不重写**（不制造无谓的版本推进），照实报"已生效" ✓；
⑥ 失败路径 fail closed：读不到画像不写（残缺值会抹库 ✗）；pending 里草稿丢了拒绝
   执行（不自造要写入的方向 ✗）。
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.gateway.contracts import CareerUpdateRequest, ConversationTurnSnapshot
from app.gateway.conversation_actions import execute_conversation_action
from app.gateway.output_validation import OutputContractError
from app.gateway.service import (
    TURN_OUTPUT_SCHEMA,
    GatewayService,
    _session_key,
)
from app.util import internal_client


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.response
        if callable(response):
            response = response(args, kwargs)
        return response


def _gateway(*, mode: str = "codex_write", active: dict | None = None) -> GatewayService:
    async def snapshot_loader(**kwargs):
        workspace = {"sessionId": "s1", "version": 8}
        if active is not None:
            workspace["activeProposal"] = active
        return workspace

    return GatewayService(
        mode=mode,
        codex=None,
        legacy=None,
        message_store=None,
        binding_loader=lambda **kwargs: None,
        snapshot_loader=snapshot_loader,
    )


def _snapshot(version: int = 8) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(snapshot_version=version, session_id="s1")


def _request(**overrides) -> CareerUpdateRequest:
    payload = {
        "sourceVersionGuard": 8,
        "userOriginalText": "想考公，也可能考研",
        "careerTypes": ["体制内/考公导向", "深造发展导向"],
    }
    payload.update(overrides)
    return CareerUpdateRequest.model_validate(payload)


# ── 契约层：入口归一 + 归不了就拒（修复回合）────────────────────────────────────


def test_contract_normalizes_entry_aliases_into_canonical_labels() -> None:
    request = _request(careerTypes=["考公", "further_study", "进企业"])
    assert request.career_types == ["体制内/考公导向", "深造发展导向", "市场化就业导向"]


def test_contract_accepts_a_bare_string_for_a_single_direction() -> None:
    """模型只给一个方向时常写成裸字符串（schema 里是数组）——宽容收下 ✓。"""
    assert _request(careerTypes="读研").career_types == ["深造发展导向"]


def test_contract_rejects_unknown_directions_with_an_actionable_message() -> None:
    """归不了的入口必须**拒**（修复回合），不许静默丢弃 ✗：丢掉一项 = 用户说了、
    卡片上没有；错误信息里要带四类规范标签，模型这一轮就能改对 ✓。"""
    with pytest.raises(ValidationError) as exc:
        _request(careerTypes=["当医生"])
    message = str(exc.value)
    assert "当医生" in message
    assert "体制内/考公导向" in message and "市场化就业导向" in message


def test_contract_rejects_an_empty_direction_list() -> None:
    with pytest.raises(ValidationError, match="at least one direction"):
        _request(careerTypes=[])


def test_model_schema_declares_the_career_draft_with_the_label_vocabulary() -> None:
    """严格 schema 必须**先声明** `careerUpdateRequest`（additionalProperties:false 的
    性格：不声明 = 模型一输出就被自己的 schema 拒，症状是"模型从不产出方向草稿"✗）；
    四类标签的口径要能从 schema 读出来（description 直接进模型上下文 ✓）。"""
    assert "careerUpdateRequest" in TURN_OUTPUT_SCHEMA["properties"]
    assert "careerUpdateRequest" in TURN_OUTPUT_SCHEMA["required"]
    property_schema = TURN_OUTPUT_SCHEMA["properties"]["careerUpdateRequest"]
    rendered = json.dumps(property_schema, ensure_ascii=False)
    for label in ("体制内/考公导向", "稳定就业导向", "深造发展导向", "市场化就业导向"):
        assert label in rendered
    # 严格 schema：对象分支的 required 必须覆盖全部 properties（上游拒 optional）
    branches = [b for b in property_schema.get("anyOf", []) if b.get("type") != "null"]
    assert len(branches) == 1
    assert set(branches[0]["required"]) == set(branches[0]["properties"])


# ── 准备段：写模式物化 pending / 只读模式只出预览 ───────────────────────────────


@pytest.mark.asyncio
async def test_write_mode_prepares_the_pending_and_returns_the_flat_card_shape(monkeypatch):
    """写模式：物化 `kind=career_update` 的 pending ✓；卡片带 pendingId 与刷新后的版本 ✓。"""
    recorder = _Recorder({
        "code": 0,
        "data": {"pendingId": "career_pending_1", "sourceVersion": 8},
    })
    monkeypatch.setattr(internal_client, "save_pending_confirmation", recorder)
    gateway = _gateway(active={
        "proposalRef": "career_pending_1",
        "pendingId": "career_pending_1",
        "sourceVersion": 8,
        "kind": "career_update",
        "actionFamily": "update_career_types",
    })

    preview = await gateway._prepare_career_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(),
        snapshot=_snapshot(),
    )

    # pending 载荷：三个生产者标记 + operationId + 草稿（中文规范标签）
    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args[0] == "s1"
    assert kwargs["tenant_id"] == "t1"
    payload = args[1]
    assert payload["kind"] == "career_update"
    assert payload["actionFamily"] == "update_career_types"
    assert payload["proposalSource"] == "career_update"
    assert payload["status"] == "active"
    assert payload["sourceVersion"] == 8
    assert payload["careerUpdateRequest"]["careerTypes"] == ["体制内/考公导向", "深造发展导向"]
    assert payload["careerUpdateRequest"]["userOriginalText"] == "想考公，也可能考研"
    # 幂等键与身份**按回合派生**：同一回合重试是重放（upsert 命中同一条）
    assert payload["operationId"] and len(payload["operationId"]) == 32
    assert payload["pendingId"] == f"career_{payload['operationId'][:24]}"

    # **扁平**合同形状：server.py 从顶层读 title/summary/status（包 diff 会出空卡 ✗）
    assert preview["title"] == "更新发展方向"
    # 词表统一（2026-10-16）：写模式 = pending 已落库 ⇒ `ready`（前端卡面词表认识它，
    # 显示"待确认" + 按钮 ✓）；原来写死的 `pending` 不在 web 词表 → "处理结果未知" ✗。
    assert preview["status"] == "ready"
    assert preview["requiresConfirmation"] is True
    assert preview["summary"] == "发展方向：体制内/考公导向、深造发展导向"
    assert preview["careerUpdate"]["careerTypes"] == ["体制内/考公导向", "深造发展导向"]
    # 身份与版本换成"待确认那一条"的（与提案同一处口径）
    assert preview["proposalRef"] == "career_pending_1"
    assert preview["sourceVersion"] == 8


@pytest.mark.asyncio
async def test_prepare_normalizes_even_if_the_draft_carried_aliases(monkeypatch):
    """落库前最后一道归一：契约层已被绕过（旧路径/直接构造）时也不许把别名写进库 ✗。"""
    recorder = _Recorder({"code": 0, "data": {"pendingId": "career_p"}})
    monkeypatch.setattr(internal_client, "save_pending_confirmation", recorder)
    gateway = _gateway()
    sneaky = CareerUpdateRequest.model_construct(
        source_version_guard=8,
        user_original_text="稳定工作，读研",
        career_types=["stable_job", "考研", "当医生"],
    )

    preview = await gateway._prepare_career_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=sneaky,
        snapshot=_snapshot(),
    )

    payload = recorder.calls[0][0][1]
    assert payload["careerUpdateRequest"]["careerTypes"] == ["稳定就业导向", "深造发展导向"], \
        "英文槽位名/别名归一，归不了的丢弃（契约层本该拒——这里是兜底）"
    assert preview["careerUpdate"]["careerTypes"] == ["稳定就业导向", "深造发展导向"]


@pytest.mark.asyncio
async def test_readonly_mode_only_previews_and_never_offers_confirmation(monkeypatch):
    """只读模式：只出只读预览、**不给确认按钮** ✓（按钮背后没有可确认的 pending ✗）。"""
    recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "save_pending_confirmation", recorder)
    gateway = _gateway(mode="codex_readonly")

    preview = await gateway._prepare_career_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(),
        snapshot=_snapshot(),
    )

    assert recorder.calls == []
    # 词表统一（2026-10-16）：只读模式没有可确认的卡 ⇒ `preview_only`（与 Java
    # `Status.PREVIEW_ONLY` 逐字一致 ✓），不再是词表外的 `pending`。
    assert preview["status"] == "preview_only"
    assert preview["requiresConfirmation"] is False
    assert preview["proposalRef"] is None
    assert preview["summary"] == "发展方向：体制内/考公导向、深造发展导向"


@pytest.mark.asyncio
async def test_source_version_guard_mismatch_fails_closed_before_calling_java(monkeypatch):
    """模型看的是旧快照 → `stale_state`，不打 Java ✓。"""
    recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "save_pending_confirmation", recorder)
    gateway = _gateway()

    with pytest.raises(OutputContractError) as exc:
        await gateway._prepare_career_update_preview(
            _session_key("t1", "s1"),
            tenant_id="t1",
            session_id="s1",
            turn_id="turn-9",
            request=_request(sourceVersionGuard=7),
            snapshot=_snapshot(version=8),
        )

    assert exc.value.code == "stale_state"
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_java_rejection_text_is_carried_into_the_contract_error(monkeypatch):
    """Java 的拒绝原文必须原样带走（内部异常串不上用户面，业务原文是）✓。"""
    monkeypatch.setattr(
        internal_client,
        "save_pending_confirmation",
        _Recorder({"code": 40001, "msg": "当前没有可确认的资料更新"}),
    )
    gateway = _gateway()

    with pytest.raises(OutputContractError) as exc:
        await gateway._prepare_career_update_preview(
            _session_key("t1", "s1"),
            tenant_id="t1",
            session_id="s1",
            turn_id="turn-9",
            request=_request(),
            snapshot=_snapshot(),
        )

    assert exc.value.code == "career_update_unavailable"
    assert "当前没有可确认的资料更新" in str(exc.value)


# ── 全链接缝：prepare 的 pending 草稿 → 确认 → PATCH → 结果回写 ─────────────────


def _active_from_prepared_pending(payload: dict, *, revision: int = 1) -> dict:
    """把 prepare 落下的 pending 载荷装回 `activeProposal`（Java 的暴露形状 ✓）。"""
    return {
        "proposalRef": payload["pendingId"],
        "pendingId": payload["pendingId"],
        "sourceVersion": payload.get("sourceVersion", 8),
        "revision": revision,
        "kind": payload["kind"],
        "actionFamily": payload["actionFamily"],
        "data": dict(payload),
    }


@pytest.mark.asyncio
async def test_the_full_chain_from_prepared_pending_to_patched_profile(monkeypatch):
    """全链：prepare 物化的 pending → 确认（claim）→ 执行器**读-合并-写** →
    PATCH 被调用（既有键不许被抹掉 ✗）→ 结果回写 pending（complete，同一 claim token ✓）。"""
    def saved_pending(args, kwargs):
        # Java 的 save 响应把**我们自己落下的** pendingId 原样带回（真实形状）
        return {"code": 0, "data": {"pendingId": args[1]["pendingId"], "sourceVersion": 8}}

    save = _Recorder(saved_pending)
    monkeypatch.setattr(internal_client, "save_pending_confirmation", save)
    gateway = _gateway()
    await gateway._prepare_career_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(),  # ["体制内/考公导向", "深造发展导向"]
        snapshot=_snapshot(),
    )
    prepared = save.calls[0][0][1]
    active = _active_from_prepared_pending(prepared)
    snapshot_payload = {"snapshotVersion": 8, "sessionId": "s1", "activeProposal": active}

    # 执行侧替身：画像里已有一个方向 + 一个**别的键**（industryPreferences）
    profile_recorder = _Recorder({
        "code": 0,
        "data": {
            "latentProfile": {
                "futureDevelopment": {
                    "careerTypes": ["市场化就业导向"],
                    "industryPreferences": ["互联网"],
                }
            }
        },
    })
    patch_recorder = _Recorder({"code": 0, "data": {"version": 9}})
    monkeypatch.setattr(internal_client, "get_planning_profile", profile_recorder)
    monkeypatch.setattr(internal_client, "update_planning_latent_profile", patch_recorder)

    resolve_calls = []

    async def resolver(session_id=None, *args, **kwargs):
        resolve_calls.append(kwargs)
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    async def executor(*args, **kwargs):
        raise AssertionError("career_update 不许走 pending-command 执行器（Java 没有这一族）")

    result = await execute_conversation_action(
        tenant_id="t1",
        session_id="s1",
        action={
            "actionType": "confirm_proposal",
            "proposalRef": active["proposalRef"],
            "expectedSourceVersion": 8,
        },
        snapshot=snapshot_payload,
        resolver=resolver,
        executor=executor,
    )

    assert result.action_status == "applied"
    assert result.new_state_version == 9, "版本在 PATCH 响应的 data.version 上"
    assert result.actual_changes == [
        {"target": "careerTypes", "value": "体制内/考公导向"},
        {"target": "careerTypes", "value": "深造发展导向"},
    ], "actualChanges 只报新增（既有那项不在里面）"

    # 执行体真的读了画像、写了**全文合并**（整字段赋值纪律）
    assert profile_recorder.calls[0][0] == ("s1",)
    args, kwargs = patch_recorder.calls[0]
    assert args == ("s1",)
    written = kwargs["future_development"]
    assert written["careerTypes"] == ["市场化就业导向", "体制内/考公导向", "深造发展导向"]
    assert written["industryPreferences"] == ["互联网"], "整字段赋值：既有键必须读回原样带上"

    # 结果回写：complete 与 claim 用**同一个** claim token、认准同一条 pending
    assert len(resolve_calls) == 2
    assert resolve_calls[0]["action"] == "confirm"
    assert resolve_calls[1]["action"] == "complete"
    assert resolve_calls[1]["claim_token"] == resolve_calls[0]["claim_token"]
    assert resolve_calls[1]["pending_id"] == active["pendingId"]
    assert active["pendingId"].startswith("career_"), "身份按回合派生（生产者那一层落下）"
    assert resolve_calls[1]["expected_revision"] == 4, "回写用 claim 返回的修订号"


@pytest.mark.asyncio
async def test_a_replayed_pending_that_is_already_recorded_is_a_no_op(monkeypatch):
    """幂等：要落的方向已经在库里 → **不重写**（不制造无谓的版本推进），报"已生效" ✓。"""
    profile_recorder = _Recorder({
        "code": 0,
        "data": {
            "latentProfile": {
                "futureDevelopment": {"careerTypes": ["考公", "深造发展导向"]}
            }
        },
    })
    patch_recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "get_planning_profile", profile_recorder)
    monkeypatch.setattr(internal_client, "update_planning_latent_profile", patch_recorder)

    async def resolver(session_id=None, *args, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    payload = {
        "pendingId": "career_p",
        "kind": "career_update",
        "actionFamily": "update_career_types",
        "operationId": "op-career-1",
        "sourceVersion": 8,
        "careerUpdateRequest": {
            "careerTypes": ["体制内/考公导向", "深造发展导向"],
            "userOriginalText": "考公，也可能考研",
        },
    }
    snapshot_payload = {
        "snapshotVersion": 8,
        "sessionId": "s1",
        "activeProposal": _active_from_prepared_pending(payload),
    }

    result = await execute_conversation_action(
        tenant_id="t1",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "career_p"},
        snapshot=snapshot_payload,
        resolver=resolver,
    )

    assert result.action_status == "applied"
    assert result.actual_changes == [], "没有新增 → 不给 front 制造任何变化"
    assert patch_recorder.calls == [], "已落库的方向不许再写一次（版本不该空转）"


@pytest.mark.asyncio
async def test_unreadable_profile_refuses_to_write(monkeypatch):
    """读不到画像就**拒绝执行** ✓：整字段赋值下拿残缺值写库会把既有键整个抹掉 ✗。"""
    async def boom(session_id):
        raise RuntimeError("java down")

    monkeypatch.setattr(internal_client, "get_planning_profile", boom)
    patch_recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "update_planning_latent_profile", patch_recorder)

    resolve_calls = []

    async def resolver(session_id=None, *args, **kwargs):
        resolve_calls.append(kwargs)
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "failed"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    payload = {
        "pendingId": "career_p",
        "kind": "career_update",
        "actionFamily": "update_career_types",
        "operationId": "op-career-1",
        "sourceVersion": 8,
        "careerUpdateRequest": {"careerTypes": ["深造发展导向"], "userOriginalText": "考研"},
    }
    snapshot_payload = {
        "snapshotVersion": 8,
        "sessionId": "s1",
        "activeProposal": _active_from_prepared_pending(payload),
    }

    result = await execute_conversation_action(
        tenant_id="t1",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "career_p"},
        snapshot=snapshot_payload,
        resolver=resolver,
    )

    assert result.action_status == "failed"
    assert result.code == "career_profile_unreadable"
    assert patch_recorder.calls == [], "读不到就不许写"
    # 失败也要回写 pending（否则永远停在 applying —— 重复确认会被误判成"没有落地"）
    assert resolve_calls[-1]["action"] == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("removed_key", ["operationId", "careerUpdateRequest"])
async def test_refuses_to_execute_when_the_pending_is_incomplete(monkeypatch, removed_key):
    """"是方向更新但缺件" ≠ "不是方向更新"：前者**拒绝执行**（不自造幂等键/方向 ✗）。"""
    payload = {
        "pendingId": "career_p",
        "kind": "career_update",
        "actionFamily": "update_career_types",
        "operationId": "op-career-1",
        "sourceVersion": 8,
        "careerUpdateRequest": {"careerTypes": ["深造发展导向"], "userOriginalText": "考研"},
    }
    payload.pop(removed_key)

    async def resolver(session_id=None, *args, **kwargs):
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    async def executor(*args, **kwargs):
        raise AssertionError("pending 不完整时执行器一次都不该被调")

    result = await execute_conversation_action(
        tenant_id="t1",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "career_p"},
        snapshot={
            "snapshotVersion": 8,
            "sessionId": "s1",
            "activeProposal": _active_from_prepared_pending(payload),
        },
        resolver=resolver,
        executor=executor,
    )

    assert result.action_status == "failed"
    assert result.code == ("career_update_payload_missing" if removed_key == "careerUpdateRequest" else "operation_id_missing")


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["kind", "actionFamily", "proposalSource"])
async def test_detection_accepts_each_producer_marker(monkeypatch, marker: str) -> None:
    """生产者的三个标记（kind / actionFamily / proposalSource）任一命中即识别 ✓。"""
    payload = {
        "pendingId": "career_p",
        "kind": "career_update",
        "actionFamily": "update_career_types",
        "proposalSource": "career_update",
        "operationId": "op-career-1",
        "sourceVersion": 8,
        "careerUpdateRequest": {"careerTypes": ["深造发展导向"], "userOriginalText": "考研"},
    }
    active = _active_from_prepared_pending(payload)
    if marker == "kind":
        active.pop("kind")
        active["data"].pop("proposalSource")
    elif marker == "actionFamily":
        active.pop("actionFamily")
        active["data"].pop("proposalSource")
    else:
        active.pop("kind")
        active.pop("actionFamily")

    async def resolver(session_id=None, *args, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    async def executor(*args, **kwargs):
        raise AssertionError("career_update 不许走 pending-command 执行器")

    # 只要识别成功，就会走到 career 执行体（读画像）——用 recorder 喂一个空画像，
    # 断言点只在"识别"本身：执行体被叫到了（否则会落到提案分支 → executor 才被调）。
    profile_recorder = _Recorder({"code": 0, "data": {"latentProfile": {"futureDevelopment": {}}}})
    monkeypatch.setattr(internal_client, "get_planning_profile", profile_recorder)
    monkeypatch.setattr(
        internal_client, "update_planning_latent_profile", _Recorder({"code": 0, "data": {"version": 9}})
    )

    result = await execute_conversation_action(
        tenant_id="t1",
        session_id="s1",
        action={"actionType": "confirm_proposal", "proposalRef": "career_p"},
        snapshot={"snapshotVersion": 8, "sessionId": "s1", "activeProposal": active},
        resolver=resolver,
        executor=executor,
    )

    assert result.action_status == "applied"
    assert len(profile_recorder.calls) == 1, "识别成功 = 走了 career 执行体"
