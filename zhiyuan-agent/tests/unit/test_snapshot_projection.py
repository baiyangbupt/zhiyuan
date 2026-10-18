from __future__ import annotations

import pytest
from pydantic import ValidationError

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


# ── 发展方向（career v1）：模型快照里必须看得见 ────────────────────────────────
#
# 数据源：`latentProfile.futureDevelopment.careerTypes`（中文规范标签落库 ✓）。
# 投影 DTO 里**没有** latentProfile（Java 未暴露 ✓）——组合层由 `server.py` 的
# snapshot_loader 包装（`_attach_career_directions`，agent 侧直读画像）把值按
# **workspace 形状**注入进来，本节就在那个形状上钉：挪到 `preferences.careerTypes`
# ✓、**弱偏好**语义 ✓（只进推荐理由/排序/解释，绝不做硬筛 ✗）、旧数据里的槽位名/
# 别名也归一 ✓（历史值曾写过非标签形式 ✓）。


def test_projection_exposes_career_types_as_normalized_labels() -> None:
    workspace = fake_backend_workspace()
    workspace["profileState"]["latentProfile"] = {
        "futureDevelopment": {
            "careerTypes": ["考公", "深造发展导向"],
            "industryPreferences": ["互联网"],
        }
    }

    snapshot = build_snapshot(workspace)

    assert snapshot.preferences["careerTypes"] == ["体制内/考公导向", "深造发展导向"], \
        "落库/快照同一形式：中文规范标签（旧数据护栏也在这一层归一）"
    assert snapshot.preferences["careerTypes"] != ["考公", "深造发展导向"], "别名不进快照"


def test_projection_omits_career_types_key_when_nothing_is_recorded() -> None:
    """没落过库时**键就不出现** ✓：一个空列表会被模型读成"用户说了但没有方向" ✗。"""
    snapshot = build_snapshot(fake_backend_workspace())
    assert "careerTypes" not in snapshot.preferences


def test_projection_drops_unknown_career_entries_instead_of_guessing() -> None:
    workspace = fake_backend_workspace()
    workspace["profileState"]["latentProfile"] = {
        "futureDevelopment": {"careerTypes": ["当医生", "进企业"]}
    }

    snapshot = build_snapshot(workspace)

    assert snapshot.preferences["careerTypes"] == ["市场化就业导向"], "归不了的丢弃，不猜"


@pytest.mark.asyncio
async def test_career_enrichment_reads_the_profile_and_injects_workspace_shape(monkeypatch) -> None:
    """`_attach_career_directions`：投影 DTO 载荷 → 直读画像 → 注入 workspace 形状 ✓。"""
    from app.server import _attach_career_directions

    calls = []

    async def get_profile(session_id):
        calls.append(session_id)
        return {
            "code": 0,
            "data": {
                "latentProfile": {
                    "futureDevelopment": {"careerTypes": ["考研"], "industryPreferences": []}
                }
            },
        }

    monkeypatch.setattr(internal_client, "get_planning_profile", get_profile)
    payload = {"data": {"sessionId": "900047", "snapshotVersion": 12}}

    enriched = await _attach_career_directions(payload)

    assert calls == ["900047"]
    assert enriched["data"]["profileState"]["latentProfile"]["futureDevelopment"]["careerTypes"] == [
        "深造发展导向"
    ]
    # 原载荷不被就地改写（快照缓存里还挂着同一份对象）
    assert "profileState" not in payload["data"]
    # 注入后的形状正是 `build_snapshot` 读的形状 ✓（钉住两层的接缝）
    workspace = dict(enriched["data"])
    workspace.setdefault("studentSummary", {})
    snapshot = build_snapshot(workspace)
    assert snapshot.preferences["careerTypes"] == ["深造发展导向"]


@pytest.mark.asyncio
async def test_career_enrichment_degrades_to_passthrough_on_every_failure_mode(monkeypatch) -> None:
    """补读失败**不阻断回合** ✓：异常 / 码非 0 / 没有方向 / 非投影形状 → 原样放行 ✓。"""
    from app.server import _attach_career_directions

    async def boom(session_id):
        raise RuntimeError("java down")

    monkeypatch.setattr(internal_client, "get_planning_profile", boom)
    payload = {"data": {"sessionId": "900047"}}
    assert await _attach_career_directions(payload) == payload

    async def rejected(session_id):
        return {"code": 404, "msg": "not found"}

    monkeypatch.setattr(internal_client, "get_planning_profile", rejected)
    assert await _attach_career_directions(payload) == payload

    async def empty(session_id):
        return {"code": 0, "data": {"latentProfile": {"futureDevelopment": {"careerTypes": []}}}}

    monkeypatch.setattr(internal_client, "get_planning_profile", empty)
    assert await _attach_career_directions(payload) == payload

    # 非投影形状（替身/单测的 workspace 载荷）不补、也不打画像接口
    async def must_not_call(session_id):
        raise AssertionError("workspace 形状不该触发直读")

    monkeypatch.setattr(internal_client, "get_planning_profile", must_not_call)
    workspace_payload = {"sessionId": "900047", "version": 3}
    assert await _attach_career_directions(workspace_payload) == workspace_payload


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


# ── §五-48 最小第一步：真载荷（turn-snapshot）形状回归 ────────────────────────
#
# 真载荷按 `ConversationTurnSnapshotDTO`（Java 12 字段）序列化 ✓：**没有**
# profileState / constraintState / studentSummary 这些 workspace 形状键 ✗——
# 旧投影从这些键重导，产出 `confirmedConstraints={}` / `preferences={}`，
# **Java 已算好的权威数据被空覆盖丢弃** ✗（§35/§37 真因 ✓，§五-48 最重案件）。
# 本节钉住口径：**权威字段优先、缺才回落** ✓；careerTypes 旁路照旧合入 ✓；
# 两套形状认不出时**原样透传/报错，禁静默空** ✓。


def real_turn_snapshot_payload() -> dict:
    """按 `ConversationTurnSnapshotDTO` 字段清单造的真载荷（camelCase 与 Java JSON 一致 ✓）。"""
    return {
        "snapshotVersion": 42,
        "sessionId": 900047,
        "admissionMode": "major",
        "planningStage": "candidate_exploration",
        "scoreContext": {
            "province": "江西",
            "examYear": 2026,
            "score": 484,
            "rank": 32000,
            "batch": "本科批(批次线429分)",
            "batchScore": 429,
            "subjects": ["物理", "化学"],
            "strengthSubjects": ["物理", "化学"],
        },
        "confirmedConstraints": {
            "excludedMajors": ["临床医学"],
            "hard": {"maxTuition": 60000},
            "hardPlanningObjectives": {"priorityRules": [{"ruleId": "pr-1", "minCount": 1}]},
            "staleFlags": {"review": False},
        },
        "preferences": {
            "major": {"include": ["计算机科学与技术"]},
            "school": {"include": ["浙江大学"]},
            "region": {"include": ["华东"]},
            "soft": {"regions": ["华东"]},
            "candidateSummary": {"total": 80},
            "reviewSummary": {"riskCount": 1, "warnCount": 2},
            "workflow": {"reviewStatus": "reviewed"},
        },
        "activeProposal": {
            "proposalRef": "pending-1",
            "pendingId": "pending-1",
            "status": "active",
            "requiresConfirmation": True,
            "data": {"action": "preview"},
        },
        "missingFacts": [],
        "allowedCapabilities": ["catalog_read", "admission_read"],
        "evidence": [],
        "admissionFacts": [],
    }


def test_real_turn_snapshot_payload_carries_java_computed_fields_verbatim() -> None:
    """§35 的锁 ✓：真载荷里 Java 已算的约束/偏好必须**非空且逐字**进快照 ✗勿重导。"""
    payload = real_turn_snapshot_payload()
    assert payload["confirmedConstraints"], "夹具本身就得非空（否则测不到覆盖）"
    assert payload["preferences"], "夹具本身就得非空（否则测不到覆盖）"

    snapshot = build_snapshot(payload)

    assert snapshot.confirmed_constraints == payload["confirmedConstraints"], "权威约束逐字携带"
    assert snapshot.preferences == payload["preferences"], "权威偏好逐字携带"
    assert snapshot.snapshot_version == 42
    assert snapshot.planning_stage == "candidate_exploration"
    # 成绩上下文：权威值带上（别名桥保持现状 ✓——strengthSubjects 只归到 subjects ✓，不重复留键 ✓）
    assert snapshot.score_context == {
        key: value for key, value in payload["scoreContext"].items() if key != "strengthSubjects"
    }, "权威成绩上下文不被派生值挤掉"
    assert snapshot.missing_facts == []
    assert "admission_read" in snapshot.allowed_capabilities


def test_projection_falls_back_to_workspace_shape_when_authoritative_fields_are_missing() -> None:
    """缺才回落 ✓（fallback 保留，防 workspace 形状载荷回归 ✗）：空 `{}` 也算缺 ✓。"""
    workspace = fake_backend_workspace()
    assert "confirmedConstraints" not in workspace and "preferences" not in workspace

    snapshot = build_snapshot(workspace)

    assert snapshot.preferences["major"] == {"include": ["计算机科学与技术"]}
    assert snapshot.preferences["school"] == {"include": ["浙江大学"]}
    assert snapshot.preferences["soft"] == {"regions": ["华东"]}
    assert snapshot.confirmed_constraints["hard"] == {"maxTuition": 60000}

    # 键在但值为空（Java 未记录时就是空 map ✓）→ 仍算缺，回落照旧 ✓
    workspace["confirmedConstraints"] = {}
    workspace["preferences"] = {}

    snapshot = build_snapshot(workspace)

    assert snapshot.preferences["major"] == {"include": ["计算机科学与技术"]}
    assert snapshot.confirmed_constraints["hard"] == {"maxTuition": 60000}


def test_authoritative_preferences_still_receive_injected_career_types() -> None:
    """权威非空时 careerTypes 旁路照旧合入 ✓（§五-48 bullet 3：旁路别拆 ✗）——权威键一个不丢。"""
    payload = real_turn_snapshot_payload()
    payload["profileState"] = {
        "latentProfile": {"futureDevelopment": {"careerTypes": ["考研"]}}
    }

    snapshot = build_snapshot(payload)

    assert snapshot.preferences["careerTypes"] == ["深造发展导向"]
    for key, value in payload["preferences"].items():
        assert snapshot.preferences[key] == value, f"权威键 {key} 不许丢"
    assert set(snapshot.preferences) == set(payload["preferences"]) | {"careerTypes"}


def test_projection_never_covers_unrecognized_non_empty_fields_with_empty() -> None:
    """两套派生清单都认不出的键：**非空内容逐字透传** ✓（假空覆盖被禁 ✗，原则②）。"""
    payload = {
        "sessionId": "s1",
        "confirmedConstraints": {"priorityRules": [{"ruleId": "pr-1", "minCount": 1}]},
        "preferences": {"unknownBucket": {"kept": True}},
    }

    snapshot = build_snapshot(payload)

    assert snapshot.confirmed_constraints == payload["confirmedConstraints"]
    assert snapshot.preferences == payload["preferences"]


def test_projection_passes_through_unrecognizable_non_mapping_fields_loudly() -> None:
    """认不出的**非空非对象**形状：透传→契约层报错 ✓（报错好过静默空 ✗，原则②）。"""
    payload = {"sessionId": "s1", "confirmedConstraints": ["opaque-shape"]}

    with pytest.raises(ValidationError):
        build_snapshot(payload)


def test_projection_passes_journey_block_through() -> None:
    workspace = fake_backend_workspace()
    workspace["journey"] = {"hasPlan": True, "planVersion": 42, "planInterpretable": True}

    snapshot = build_snapshot(workspace)

    assert snapshot.journey == workspace["journey"]


def test_projection_rejects_non_mapping_journey() -> None:
    workspace = fake_backend_workspace()
    workspace["journey"] = ["not-an-object"]

    with pytest.raises(ValueError, match="journey must be an object"):
        build_snapshot(workspace)


def test_diff_includes_journey_when_block_changes() -> None:
    before_workspace = fake_backend_workspace()
    before_workspace["journey"] = {"hasPlan": False, "planVersion": 42}
    after_workspace = fake_backend_workspace()
    after_workspace["version"] = 43
    after_workspace["journey"] = {"hasPlan": True, "planVersion": 43}

    patch = diff_snapshots(build_snapshot(before_workspace), build_snapshot(after_workspace))

    assert "journey" in {change["path"] for change in patch.changes}


def test_state_patch_accepts_journey_path() -> None:
    from app.gateway.contracts import StatePatch

    patch = StatePatch(
        baseVersion=42,
        targetVersion=43,
        changes=[{"path": "journey", "oldValue": None, "newValue": {"hasPlan": True}}],
    )

    assert patch.changes[0]["path"] == "journey"
