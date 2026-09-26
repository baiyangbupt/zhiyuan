from __future__ import annotations

import pytest

from app.gateway.snapshot import build_snapshot, diff_snapshots
from app.util import internal_client


def fake_backend_workspace() -> dict:
    return {
        "sessionId": 101,
        "version": 42,
        "phase": "candidate_exploration",
        "studentSummary": {
            "provinceName": "浙江",
            "score": 612,
            "rank": 18420,
            "subjects": ["物理", "化学"],
        },
        "profileState": {
            "explicitProfile": {
                "majorPreferences": {"include": ["计算机科学与技术"]},
                "schoolPreferences": {"include": ["浙江大学"]},
            }
        },
        "constraintState": {
            "hardConstraints": {"maxTuition": 60000},
            "softPreferences": {"regions": ["华东"]},
        },
        "staleFlags": {"review": False},
        "reviewState": {"summary": {"riskCount": 1, "warnCount": 2}},
        "workflowStatus": {"reviewStatus": "reviewed"},
        "candidatePoolState": {"summary": {"total": 12}},
        "allowedCapabilities": ["admission_read", "catalog_read"],
        "evidence": [
            {
                "evidenceId": "ev-score",
                "sourceLevel": "authoritative",
                "dataVersion": "2026.09.07",
                "limitations": [],
            }
        ],
        "workingPlanState": {"items": [{"school": "不应进入模型快照"}]},
        "operationLogs": [{"type": "secret", "payload": "不应进入模型快照"}],
    }


def test_candidate_projection_contains_authoritative_score_and_allowed_capabilities() -> None:
    snapshot = build_snapshot(fake_backend_workspace())

    assert snapshot.snapshot_version == 42
    assert snapshot.score_context["province"] == "浙江"
    assert snapshot.score_context["rank"] == 18420
    assert "admission_read" in snapshot.allowed_capabilities
    assert "plan_apply" not in snapshot.allowed_capabilities
    assert "workingPlanState" not in snapshot.model_dump(by_alias=True)
    assert "operationLogs" not in snapshot.model_dump(by_alias=True)


def test_missing_score_becomes_explicit_missing_fact() -> None:
    workspace = fake_backend_workspace()
    workspace["studentSummary"].pop("rank")
    workspace["studentSummary"].pop("score")

    snapshot = build_snapshot(workspace)

    assert "score" in snapshot.missing_facts
    assert "rank" in snapshot.missing_facts
    assert snapshot.score_context["province"] == "浙江"


def test_projection_fills_missing_score_context_from_authoritative_turn_snapshot() -> None:
    """`turn-snapshot` 已经把 `scoreContext` 算好了 ✓（Java 权威 ✓）——**缺什么补什么** ✓。

    背景（2026-09-26 真栈）：真载荷的 `studentSummary` 里**没有** `batch` ✗，于是投影出的
    `score_context` 少这一格 ✗ → 网关解析专业 ID 时拿不到学历层次 ✗ → 目录对"临床医学"
    返回 `multi` ✗（本科/专科各一条 ✓）→ 安全阀按设计不取 ID ✓（只发名字 ✓）→
    "专业 ID 优先"在真栈上**没被激活** ✗（报告第三十四轮 ✓）。

    口径：**派生值优先** ✓（别处依赖它的形状 ✓），`scoreContext` 只补缺 ✓；
    别名 `strengthSubjects` → `subjects` 要对上 ✓（否则真载荷的选科会整个丢掉 ✗）。
    """
    workspace = fake_backend_workspace()
    workspace.pop("studentSummary")  # 真栈这条路没有 summary ✗
    workspace["scoreContext"] = {
        "province": "江西",
        "score": 484,
        "batch": "本科批(批次线429分)",
        "batchScore": 429,
        "strengthSubjects": ["化学", "生物"],
    }

    snapshot = build_snapshot(workspace)

    assert snapshot.score_context["batch"] == "本科批(批次线429分)", "派生拿不到的格由权威值补"
    assert snapshot.score_context["province"] == "江西"
    assert snapshot.score_context["subjects"] == ["化学", "生物"], "别名 strengthSubjects 要归到 subjects"


def test_projection_maps_canonical_profile_fields_and_pending_proposal() -> None:
    workspace = fake_backend_workspace()
    workspace["profileState"]["explicitProfile"] = {
        "positiveMajors": ["计算机科学与技术"],
        "negativeMajors": ["临床医学"],
        "positiveRegions": ["华东"],
    }
    workspace["activeProposal"] = {
        "pendingId": "pending-1",
        "data": {"action": "preview"},
    }

    snapshot = build_snapshot(workspace)

    assert snapshot.preferences["major"] == ["计算机科学与技术"]
    assert snapshot.preferences["region"] == ["华东"]
    assert snapshot.confirmed_constraints["excludedMajors"] == ["临床医学"]
    assert snapshot.active_proposal == workspace["activeProposal"]


def test_projection_rejects_workspace_without_session_id() -> None:
    workspace = fake_backend_workspace()
    workspace.pop("sessionId")

    with pytest.raises(ValueError, match="workspace sessionId is required"):
        build_snapshot(workspace)


def test_diff_only_emits_whitelisted_top_level_paths_and_adjacent_version() -> None:
    before = build_snapshot(fake_backend_workspace())
    workspace = fake_backend_workspace()
    workspace["version"] = 43
    workspace["phase"] = "plan_review"
    workspace["workingPlanState"]["items"].append({"school": "仍不应进入 patch"})
    after = build_snapshot(workspace)

    patch = diff_snapshots(before, after)

    assert patch.base_version == 42
    assert patch.target_version == 43
    assert {change["path"] for change in patch.changes} == {"planningStage"}


def test_projection_derives_canonical_mode_from_volunteer_model() -> None:
    workspace = fake_backend_workspace()
    workspace["candidatePoolState"]["volunteerModel"] = "majorGroup"

    snapshot = build_snapshot(workspace)

    assert snapshot.admission_mode == "major_group"
    assert snapshot.model_dump(by_alias=True)["admissionMode"] == "major_group"


def test_mode_change_invalidates_admission_references() -> None:
    before_workspace = fake_backend_workspace()
    before_workspace["candidatePoolState"]["volunteerModel"] = "major"
    after_workspace = fake_backend_workspace()
    after_workspace["version"] = 43
    after_workspace["candidatePoolState"]["volunteerModel"] = "majorGroup"

    patch = diff_snapshots(build_snapshot(before_workspace), build_snapshot(after_workspace))

    assert {change["path"] for change in patch.changes} == {"admissionMode"}
    assert {
        invalidation["kind"]
        for invalidation in patch.invalidations
        if invalidation.get("kind")
    } >= {
        "admission_mode",
        "evidence",
        "candidate",
        "review",
        "artifact",
        "proposal",
    }


def test_projection_rejects_non_mapping_backend_payload() -> None:
    with pytest.raises(ValueError, match="workspace payload must be an object"):
        build_snapshot([])


@pytest.mark.asyncio
async def test_turn_snapshot_client_uses_tenant_session_and_skill(monkeypatch) -> None:
    calls = []

    async def get(*, endpoint, params, error_msg):
        calls.append((endpoint, params, error_msg))
        return {"code": 0, "data": {"snapshotVersion": 42}}

    monkeypatch.setattr(internal_client.http_client, "get", get)

    result = await internal_client.get_conversation_turn_snapshot(
        7, 101, "candidate-recommendation"
    )

    assert result["data"]["snapshotVersion"] == 42
    assert calls == [
        (
            "/gaotu-assistant-bot/inner/planning/7/session/turn-snapshot",
            {"chatSessionId": 101, "skill": "candidate-recommendation"},
            "获取 conversation turn snapshot 失败",
        )
    ]
