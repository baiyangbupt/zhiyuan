"""补录成绩（score_update 动作族）：网关准备段与卡片文案。

链路：模型说"要补哪些字段"（`ScoreUpdateRequest` 草稿）→ 网关把草稿交给 Java
（写模式 `prepare`：物化成 `kind=score_update` 的待确认；只读模式 `preview`：只出预览、
**不给确认按钮**）→ 返回**扁平**的前端合同形状（`server.py::_proposal_preview_payload`
从**顶层**读 title/summary/status ✓）→ 卡上的结构化明细来自 Java 按**合并后**成绩算的
`scoreSummary`（模型文本里的复述不作数 ✗）。

这里钉四件事：
① guard 对不上就 `stale_state`（拿旧版本确认一个已经变化的会话更糟 ✗）；
② 写/只读两种模式各走各的端点、`requiresConfirmation` 只在写模式为真 ✓；
③ Java 的嵌套 `result` 形状与扁平形状都认 ✓（prepare/preview 两种返回 ✓）；
④ 刷新后的 `activeProposal` 覆盖 `proposalRef`/`sourceVersion` ✓——与提案同一口径，
   不换的话确认第一步就必 `stale_state` ✗（卡带着编译器的 `ugp_…` 或旧版本 ✓✗）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, ScoreUpdateRequest
from app.gateway.output_validation import OutputContractError
from app.gateway.service import (
    GatewayService,
    _active_proposal_preview_override,
    _score_update_summary_text,
    _session_key,
)
from app.util import internal_client

SUMMARY = {
    "provinceName": "浙江省",
    "provinceCode": "330000",
    "subjectType": "物理类",
    "subjectTypeCode": "physics",
    "examYear": 2026,
    "batchName": "本科批",
    "batchLevel": "undergraduate",
    "batchScore": 490.0,
    "totalScore": 641,
    "totalScorePos": 3100,
    "subjects": [
        {"subject": "chinese", "subjectName": "语文", "score": 118},
        {"subject": "math", "subjectName": "数学", "score": 131},
        {"subject": "english", "subjectName": "英语", "score": 126},
    ],
}


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def _request(**overrides) -> ScoreUpdateRequest:
    payload = {
        "sourceVersionGuard": 8,
        "userOriginalText": "语文118，数学131，英语126，总分641，位次3100",
        "totalScore": 641,
        "totalScorePos": 3100,
        "subjectScoreList": [{"subject": "chinese", "score": 118}],
    }
    payload.update(overrides)
    return ScoreUpdateRequest.model_validate(payload)


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


@pytest.mark.asyncio
async def test_write_mode_prepares_the_pending_and_returns_the_flat_card_shape(monkeypatch):
    """写模式：`prepare` 物化待确认 ✓；卡片带 Java 产出的 pendingId 与刷新后的版本 ✓。"""
    recorder = _Recorder({
        "code": 0,
        "data": {
            "status": "prepared",
            "pendingId": "pending-score-1",
            "operationId": "op-score-1",
            "result": {
                "status": "ready",
                "requiresConfirmation": True,
                "sourceVersion": 8,
                "summary": SUMMARY,
            },
        },
    })
    monkeypatch.setattr(internal_client, "prepare_score_update", recorder)
    gateway = _gateway(active={
        "proposalRef": "pending-score-1",
        "pendingId": "pending-score-1",
        "sourceVersion": 8,
        "kind": "score_update",
        "actionFamily": "update_score_detail",
    })

    preview = await gateway._prepare_score_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(),
        snapshot=_snapshot(),
    )

    # prepare 的形状：requestId = 租户:会话:回合（同一回合重试＝重放，同一个 operationId）
    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args == ("t1", "s1")
    assert kwargs["request_id"] == "t1:s1:turn-9"
    assert kwargs["payload"]["sourceVersionGuard"] == 8
    assert kwargs["payload"]["totalScore"] == 641
    assert kwargs["payload"]["subjectScoreList"] == [{"subject": "chinese", "score": 118}], \
        "用户**真说了**各科时原样透传（Java 侧的整体替换语义在这里才是对的）"
    assert "province" not in kwargs["payload"], "exclude_none：模型没说的字段不许替它编"

    # **扁平**合同形状：server.py 从顶层读 title/summary/status（包 diff 会出空卡 ✗）
    assert preview["title"] == "更新成绩"
    # 词表统一（2026-10-16）：写模式 = pending 已落库 ⇒ `ready`（前端卡面词表认识它，
    # 显示"待确认" + 按钮 ✓）；原来写死的 `pending` 不在 web 词表 → "处理结果未知" ✗。
    assert preview["status"] == "ready"
    assert preview["requiresConfirmation"] is True
    assert preview["scoreUpdate"] == SUMMARY, "结构化那份原样来自 Java 的合并结果"
    assert preview["summary"] == "浙江省 · 物理类 · 本科批 · 2026 年 · 总分 641 · 位次 3100 · 语文 118、数学 131、英语 126"
    # 身份与版本换成"待确认那一条"的（与提案同一处口径）
    assert preview["proposalRef"] == "pending-score-1"
    assert preview["sourceVersion"] == 8


@pytest.mark.asyncio
async def test_readonly_mode_only_previews_and_never_offers_confirmation(monkeypatch):
    """只读模式：走 `preview`、**不给确认按钮** ✓（按钮背后没有可确认的 pending ✗）。"""
    recorder = _Recorder({
        "code": 0,
        "data": {"status": "ready", "sourceVersion": 8, "requiresConfirmation": False, "summary": SUMMARY},
    })
    prepare_recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "preview_score_update", recorder)
    monkeypatch.setattr(internal_client, "prepare_score_update", prepare_recorder)
    gateway = _gateway(mode="codex_readonly")

    preview = await gateway._prepare_score_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(),
        snapshot=_snapshot(),
    )

    assert len(recorder.calls) == 1 and prepare_recorder.calls == []
    # 词表统一（2026-10-16）：只读模式没有可确认的卡 ⇒ `preview_only`（与 Java
    # `Status.PREVIEW_ONLY` 逐字一致 ✓），不再是词表外的 `pending`。
    assert preview["status"] == "preview_only"
    assert preview["requiresConfirmation"] is False
    assert preview["proposalRef"] is None
    assert preview["summary"].startswith("浙江省")


@pytest.mark.asyncio
async def test_empty_subject_list_is_turned_back_into_not_sent(monkeypatch):
    """各科"没带"必须表现为**没有这个字段** ✗✓：`subjectScoreList: []` 会被 Java 的合并
    按"整体替换"处理 ✓（表单补录靠它清空负面意向 ✓），把服务端**既有各科**整个抹掉 ✗ →
    合并校验 110「请填写各科成绩后再创建会话」✓（2026-10-06 真栈实测 ✓）。

    真模型的输出常带 `[]`（schema 里这是数组 ✓），护栏必须在网关边界把它还原成"没带" ✓。
    """
    recorder = _Recorder({
        "code": 0,
        "data": {"pendingId": "pending-score-1", "result": {"status": "ready", "sourceVersion": 8, "summary": SUMMARY}},
    })
    monkeypatch.setattr(internal_client, "prepare_score_update", recorder)
    gateway = _gateway()

    preview = await gateway._prepare_score_update_preview(
        _session_key("t1", "s1"),
        tenant_id="t1",
        session_id="s1",
        turn_id="turn-9",
        request=_request(subjectScoreList=[]),
        snapshot=_snapshot(),
    )

    args, kwargs = recorder.calls[0]
    assert "subjectScoreList" not in kwargs["payload"], \
        "空数组必须还原成没带（否则会把服务端既有的各科抹掉 → 110）"
    assert kwargs["payload"]["totalScore"] == 641
    # 卡上的各科只能来自 Java 合并后的 summary（这里原样透传 ✓）
    assert preview["scoreUpdate"] == SUMMARY


@pytest.mark.asyncio
async def test_source_version_guard_mismatch_fails_closed_before_calling_java(monkeypatch):
    """模型看的是旧快照 → `stale_state`，不打 Java ✓（拿旧版本确认变化后的会话更糟 ✗）。"""
    recorder = _Recorder({"code": 0, "data": {}})
    monkeypatch.setattr(internal_client, "prepare_score_update", recorder)
    gateway = _gateway()

    with pytest.raises(OutputContractError) as exc:
        await gateway._prepare_score_update_preview(
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
@pytest.mark.parametrize("response", [
    {"code": 110, "msg": "补录成绩校验未通过"},
    {"code": 0, "data": {"pendingId": "pending-score-1", "result": {"status": "ready"}}},
])
async def test_java_rejection_or_missing_summary_fails_closed(monkeypatch, response):
    """Java 业务码非 0、或预览里没有 summary（卡片将是一张空壳）→ 都按契约错误拒 ✗。"""
    monkeypatch.setattr(internal_client, "prepare_score_update", _Recorder(response))
    gateway = _gateway()

    with pytest.raises(OutputContractError) as exc:
        await gateway._prepare_score_update_preview(
            _session_key("t1", "s1"),
            tenant_id="t1",
            session_id="s1",
            turn_id="turn-9",
            request=_request(),
            snapshot=_snapshot(),
        )
    assert exc.value.code == "score_update_unavailable"


@pytest.mark.asyncio
async def test_java_rejection_text_is_carried_into_the_contract_error(monkeypatch):
    """Java 的 110 原文必须原样带走 ✗✓（2026-10-06 实测：`code:110 /
    msg:"请选择批次后再创建会话"` 被替换成一句英文通用文案，用户最终只看到
    "当前对话引擎暂时不可用"——**缺的是批次**这个可行动的事实被整段吞掉）。"""
    monkeypatch.setattr(
        internal_client,
        "prepare_score_update",
        _Recorder({"code": 110, "msg": "请选择批次后再创建会话"}),
    )
    gateway = _gateway()

    with pytest.raises(OutputContractError) as exc:
        await gateway._prepare_score_update_preview(
            _session_key("t1", "s1"),
            tenant_id="t1",
            session_id="s1",
            turn_id="turn-9",
            request=_request(),
            snapshot=_snapshot(),
        )

    assert exc.value.code == "score_update_unavailable"
    assert "请选择批次后再创建会话" in str(exc.value)


def test_recoverable_reply_surfaces_only_score_update_business_text() -> None:
    """失败回复的放行规则：**只有**补录的业务拒绝用 Java 原文，其它一律通用文案
    （内部异常串不上用户面）。"""
    from app.gateway.service import _recoverable_turn_reply

    assert (
        _recoverable_turn_reply("score_update_unavailable: 非标准选科编码")
        == "非标准选科编码"
    )
    # Java 没给 msg 时的英文兜底**不上用户面**（用户看不懂，回通用文案）。
    assert (
        _recoverable_turn_reply(
            "score_update_unavailable: Java score update preview rejected the request"
        )
        == "当前对话引擎暂时不可用，请稍后重试。"
    )
    # 其它错误的原文（`RuntimeError` / `KeyError: 'x'` …）不外泄。
    assert _recoverable_turn_reply("RuntimeError") == "当前对话引擎暂时不可用，请稍后重试。"
    assert "KeyError" not in _recoverable_turn_reply("KeyError: 'x'")


def test_summary_text_renders_everything_java_computed() -> None:
    assert _score_update_summary_text(SUMMARY) == (
        "浙江省 · 物理类 · 本科批 · 2026 年 · 总分 641 · 位次 3100 · 语文 118、数学 131、英语 126"
    )


def test_summary_text_degrades_gracefully() -> None:
    """缺项不编造：没说的不渲染 ✓；单科缺分的跳过 ✓；全空则空串 ✓。"""
    assert _score_update_summary_text({"totalScore": 641}) == "总分 641"
    assert _score_update_summary_text({
        "totalScore": 641,
        "subjects": [{"subjectName": "语文", "score": None}, {"subject": "math", "score": 131}],
    }) == "总分 641 · math 131"
    assert _score_update_summary_text({}) == ""


def test_active_proposal_override_replaces_identity_and_version_from_nested_data() -> None:
    """顶层没有版本时从 `data.sourceVersion` 取 ✓（Java 两种暴露都可能 ✓）。"""
    preview = {"proposalRef": "ugp_compiler", "sourceVersion": 0, "title": "更新成绩"}
    active = {"proposalRef": "pending-score-1", "data": {"sourceVersion": 8}}

    override = _active_proposal_preview_override(preview, active)

    assert override["proposalRef"] == "pending-score-1"
    assert override["sourceVersion"] == 8
    assert override["title"] == "更新成绩", "只换身份与版本，展示内容不动"


def test_active_proposal_override_reads_attributes_too() -> None:
    """`active_proposal` **是模型不是 dict** ✓（实测按字典读一次都没命中 ✓）——属性路也要走 ✓。"""
    active = SimpleNamespace(pending_id="pending-score-2", source_version=9)

    override = _active_proposal_preview_override({"proposalRef": "ugp", "sourceVersion": 0}, active)

    assert override["proposalRef"] == "pending-score-2"
    assert override["sourceVersion"] == 9


def test_active_proposal_override_leaves_the_preview_alone_without_identity() -> None:
    override = _active_proposal_preview_override(
        {"proposalRef": "ugp_compiler", "sourceVersion": 3}, {"data": {}}
    )
    assert override == {"proposalRef": "ugp_compiler", "sourceVersion": 3}
