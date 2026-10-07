"""B1：权威证据从 Java 一路走到 Gateway 账本。

要证的是**同一条证据在四层里是同一个东西**：Java 签发的 ID、内容摘要、
招生范围在 InternalClient → Domain MCP → Gateway 账本 → 输出校验里都不变形、
不丢失、不被顶替。

fixture 的形状取自 Java DTO（`ResponseDTO{code,msg,data,evidence}`），
不是从 Python 侧的期望编的——P1a 栽过的跟头正是照消费侧的期望编形状。
"""
from __future__ import annotations

import pytest

from app.gateway.output_validation import merge_evidence
from app.harness.binding import ThreadBinding
from app.mcp_server.tools_readonly import InternalClientBackend, ReadonlyDomainTools


def _java_envelope(rows: list[dict], evidence: list[dict]) -> dict:
    """Java `ResponseDTO` 的线上形状：evidence 是 data 的**兄弟字段**。"""
    return {"code": 0, "msg": "", "data": rows, "evidence": evidence}


JAVA_EVIDENCE = {
    "evidenceId": "ev_9f1c4c2ab0e34d7f8a1b",
    "sourceLevel": "authoritative",
    "sourceSystem": "gaotu.school_major_score_line",
    "dataVersion": "sha256:4a7d1ed414474e4033ac29ccb8653d9b",
    "paramsDigest": "sha256:9f2c1d",
    "tenantId": "tenant-1",
    "sessionId": "101",
    "threadId": "thr_test",
    "admissionMode": "major",
    "admissionUnitId": "unit-1",
    "scope": {
        "tenantId": "tenant-1",
        "sessionId": "101",
        "schoolId": "s1",
        "majorId": "m1",
        "areaId": "31",
        "batch": "本科批",
        "year": 2025,
        "subjectType": "物理类",
    },
    "observedAt": "2026-09-21T00:00:00Z",
}


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr_test",
        tenant_id="tenant-1",
        session_id="101",
        user_id="202",
        allowed_capabilities=frozenset({"admission_read", "admission.get_history"}),
        admission_mode="major",
        snapshot_version=42,
    )


@pytest.mark.asyncio
async def test_real_array_data_does_not_break_the_envelope(monkeypatch) -> None:
    """真实 `data` 是**数组**；替身曾经返回 dict，于是 `dict([...])` 直接抛。"""
    captured = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        # 事实形状的行：当前 `_admission_envelope` 按 admissionUnitId 把事实与
        # 证据配对（把历史行与事实拆开是 B2 的事）。这里要验的是**证据有没有
        # 原样穿过这一层**，所以用这条路径能观测到的形状。
        return _java_envelope(
            [
                {"year": 2025, "minScore": 612, "minPos": 9000, "enrollNum": 30},
                {"year": 2024, "minScore": 605, "minPos": 9800, "enrollNum": 28},
            ],
            [JAVA_EVIDENCE],
        )

    monkeypatch.setattr(
        "app.mcp_server.tools_readonly.internal_client.query_school_major_score_line",
        fake_query,
    )
    backend = InternalClientBackend(tenant_id="tenant-1", chat_session_id="101", thread_id="thr_test")
    tools = ReadonlyDomainTools(_binding(), backend=backend)

    result = await tools.call(
        "admission.get_history",
        {
            "admissionMode": "major",
            "schoolId": "s1",
            "majorId": "m1",
            "areaId": "31",
            "batch": "本科批",
            "year": 2025,
            "subjectType": "物理类",
            "stateVersion": 42,
        },
    )

    assert result["status"] == "ok"
    # 这条工具的口径是**历史**：返回逐年事实，不返回"事实+录取率"。
    assert result["kind"] == "history"
    assert result["data"][0]["minScore"] == 612
    assert "unitAdmissionRate" not in result["data"][0]
    # 证据没有在第一步就被丢掉。
    assert [item["evidenceId"] for item in result["evidenceRefs"]] == [JAVA_EVIDENCE["evidenceId"]]
    # scope 三参确实发出去了：没有它们 Java 不会签发。
    assert captured["tenant_id"] == "tenant-1"
    assert captured["chat_session_id"] == "101"
    assert captured["thread_id"] == "thr_test"


@pytest.mark.asyncio
async def test_java_evidence_id_survives_the_mcp_layer_unchanged(monkeypatch) -> None:
    """ID 与摘要原样透传：任何一层擅自重写都会让下游 verify 查不到。"""
    async def fake_query(**kwargs):
        # 数据留空的话根本不会走到"事实与证据配对"那一步，证据自然也不会出现在
        # 结果里——那样测的就不是"ID 有没有被改写"，而是"有没有事实"。
        return _java_envelope(
            [
                {"year": 2025, "minScore": 612, "minPos": 9000, "enrollNum": 30},
                {"year": 2024, "minScore": 605, "minPos": 9800, "enrollNum": 28},
            ],
            [JAVA_EVIDENCE],
        )

    monkeypatch.setattr(
        "app.mcp_server.tools_readonly.internal_client.query_school_major_score_line",
        fake_query,
    )
    backend = InternalClientBackend(tenant_id="tenant-1", chat_session_id="101", thread_id="thr_test")
    tools = ReadonlyDomainTools(_binding(), backend=backend)

    result = await tools.call(
        "admission.get_history",
        {
            "admissionMode": "major",
            "schoolId": "s1",
            "majorId": "m1",
            "areaId": "31",
            "batch": "本科批",
            "year": 2025,
            "subjectType": "物理类",
            "stateVersion": 42,
        },
    )

    preserved = result["evidenceRefs"][0]
    assert preserved["evidenceId"] == JAVA_EVIDENCE["evidenceId"]
    assert preserved["dataVersion"] == JAVA_EVIDENCE["dataVersion"]
    assert preserved["paramsDigest"] == JAVA_EVIDENCE["paramsDigest"]


@pytest.mark.asyncio
async def test_no_evidence_means_no_evidence_not_a_self_minted_one(monkeypatch) -> None:
    """替身/上游没给证据时，不能凭空造一条 authoritative 出来。

    自铸的 ID 对不上 Java 台账里的任何一条，下游 verify 一定说"查不到"——
    而更糟的是它让"有证据"恒真，于是所有"必须引用证据"的检查从未做过判定。
    """
    async def fake_query(**kwargs):
        return _java_envelope(
            [
                {
                    "admissionMode": "major",
                    "admissionUnitId": "unit-1",
                    "schoolId": "s1",
                    "unitAdmissionRate": 45,
                    "riskTier": "冲",
                    "majorItems": [{"majorId": "m1", "majorAdmissionRate": 85}],
                }
            ],
            [],
        )

    monkeypatch.setattr(
        "app.mcp_server.tools_readonly.internal_client.query_school_major_score_line",
        fake_query,
    )
    backend = InternalClientBackend(tenant_id="tenant-1", chat_session_id="101", thread_id="thr_test")
    tools = ReadonlyDomainTools(_binding(), backend=backend)

    result = await tools.call(
        "admission.get_history",
        {
            "admissionMode": "major",
            "schoolId": "s1",
            "areaId": "31",
            "batch": "本科批",
            "year": 2025,
            "subjectType": "物理类",
            "stateVersion": 42,
        },
    )

    assert result["evidenceRefs"] == []


def test_same_id_with_a_different_data_version_keeps_the_snapshot_record() -> None:
    """同 ID、内容标识（dataVersion）有出入：**信快照，不报错**（2026-10-07 修）。

    本回合那份不是"另一条证据"，是对快照的**转述**——以前按"稳定身份全等"判，
    转述一转就冲突 → 整轮硬失败（线上形态：补录确认后下一轮
    `evidence_identity_conflict`，用户只看到"当前对话引擎暂时不可用"）。
    现在的语义：快照是权威，转述不覆盖它；说错内容由下游 `evidence_mismatch` 拦。
    """
    snapshot_record = dict(JAVA_EVIDENCE)
    turn_record = dict(JAVA_EVIDENCE, dataVersion="sha256:other")

    merged = merge_evidence([snapshot_record], [turn_record])

    assert merged[JAVA_EVIDENCE["evidenceId"]] == snapshot_record


def test_model_citation_of_a_snapshot_evidence_does_not_conflict() -> None:
    """线上事故逐字段复刻：Java 签发件（快照）× 模型转述件（本回合）。

    两边来自 2026-10-07 的实证：
    · 快照那份是 Java 台账投影（带 `sourceSystem`/`paramsDigest`/scope 三参）；
    · 本回合那份是模型终态正文里抄回来的引用——只抄 `evidenceId`/`sourceLevel`/
      `dataVersion` 与一个**查询参数** scope，`sourceSystem`/`paramsDigest` 全丢。
    这一对曾经直接把整轮打成 `evidence_identity_conflict`；现在必须并得出、
    且账本里留下的是**快照那份**（原件），不是残缺的转述。
    """
    snapshot_record = {
        "evidenceId": "ev_01M49X3TS1EVA6PXXC2BMG73SP",
        "sourceLevel": "authoritative",
        "sourceSystem": "gaotu.batchList",
        "paramsDigest": "5c0e803deaefc0e3ee3be13497f84de9",
        "dataVersion": "fc7bd2c8d3cd6dad653afc03d4c7b40a",
        "scope": {"tenantId": 1, "chatSessionId": 10041955, "threadId": "01a113d0"},
        "observedAt": "2026-10-07T08:44:47+08:00",
        "limitations": [],
    }
    turn_record = {
        # 模型转述：没有 sourceSystem / paramsDigest，scope 被换成了查询参数。
        "evidenceId": "ev_01M49X3TS1EVA6PXXC2BMG73SP",
        "sourceLevel": "authoritative",
        "dataVersion": "fc7bd2c8d3cd6dad653afc03d4c7b40a",
        "scope": {"kind": "catalog_batch_options", "areaId": "330000", "batch": "第一段"},
        "observedAt": "2026-10-07T08:44:47+08:00",
        "limitations": ["仅覆盖浙江省批次设置与批次线，不含院校专业录取数据"],
    }

    merged = merge_evidence([snapshot_record], [turn_record])

    kept = merged["ev_01M49X3TS1EVA6PXXC2BMG73SP"]
    assert kept is snapshot_record
    assert kept["sourceSystem"] == "gaotu.batchList"
    assert kept["paramsDigest"] == "5c0e803deaefc0e3ee3be13497f84de9"


def test_root_identity_divergence_is_still_rejected() -> None:
    """根身份（租户/会话/来源系统）都非空且不同 = **另一条**证据顶着同一个 ID。

    这不是"转述残缺"（残缺是缺字段，不是字段不同），只能 fail closed——
    放宽的不是冲突，是"缺"。
    """
    for field, value in (
        ("tenantId", "tenant-2"),
        ("sessionId", "999"),
        ("sourceSystem", "gaotu.otherSource"),
    ):
        with pytest.raises(ValueError, match="evidence_identity_conflict"):
            merge_evidence([dict(JAVA_EVIDENCE)], [dict(JAVA_EVIDENCE, **{field: value})])


def test_observed_at_difference_is_not_a_conflict() -> None:
    """观测时间不同不等于证据内容不同。

    把 `observedAt` 算进稳定身份，会让正常的"同一份数据被再次观测"变成冲突——
    而那是每天都会发生的事。
    """
    first = dict(JAVA_EVIDENCE, observedAt="2026-09-20T00:00:00Z")
    second = dict(JAVA_EVIDENCE, observedAt="2026-09-21T00:00:00Z")

    merged = merge_evidence([first], [second])

    assert list(merged) == [JAVA_EVIDENCE["evidenceId"]]


def test_snapshot_and_turn_evidence_are_both_kept() -> None:
    """两个来源都要在：只留一个会让另一边引用时"看得见、够不着"。"""
    snapshot_record = dict(JAVA_EVIDENCE)
    turn_record = dict(JAVA_EVIDENCE, evidenceId="ev_turn_only")

    merged = merge_evidence([snapshot_record], [turn_record])

    assert set(merged) == {JAVA_EVIDENCE["evidenceId"], "ev_turn_only"}


def test_records_without_an_id_are_skipped_not_treated_as_one() -> None:
    merged = merge_evidence([{"sourceLevel": "authoritative"}], [{"evidenceId": "ev-1"}])

    assert list(merged) == ["ev-1"]
