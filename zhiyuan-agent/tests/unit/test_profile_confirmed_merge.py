"""确认后同源意向并入 userprofile（评审 §五-31a）的单元测试。

四条口径各有用例：
① 约束确认成功 → merge 调用**带正确值 + code**（入口级 + 两个挂点各一条）；
② 重复/并发确认并集正确（不丢不覆盖）；
③ 正负互斥（同一对象不会同时出现在 include/exclude 两侧）；
④ 并集写回**不覆盖**既有无关字段（`add-extra-data` 是整串覆盖）。
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.gateway.conversation_actions import execute_conversation_action
from app.services import profile_manager
from app.services.profile_manager import merge_confirmed_intents_into_profile
from app.util import internal_client
from app.zhiyuan_agent import tools as tools_mod


class FakeProfileBackend:
    """内存版后端画像 KV：读-改-写语义与 `add-extra-data`（整串覆盖）一致。"""

    def __init__(self, profile=None, *, read_error: str | None = None):
        self.profile = deepcopy(profile)
        self.read_error = read_error
        self.reads = 0
        self.saves: list[dict] = []
        self.explicit_calls: list[dict] = []
        self.read_delay = 0.0
        self.write_delay = 0.0

    async def get_user_profile(self, session_id):
        self.reads += 1
        if self.read_delay:
            await asyncio.sleep(self.read_delay)
        if self.read_error:
            raise RuntimeError(self.read_error)
        return {"code": 0, "data": {"userprofile": deepcopy(self.profile)}}

    async def save_user_profile(self, session_id, data_value, *args, **kwargs):
        if self.write_delay:
            await asyncio.sleep(self.write_delay)
        stored = deepcopy(data_value)
        self.saves.append(stored)
        self.profile = stored
        return {"code": 0}

    async def update_planning_explicit_profile(self, session_id, **kwargs):
        self.explicit_calls.append(kwargs)
        return {"code": 0}


@pytest.fixture
def backend(monkeypatch):
    fake = FakeProfileBackend()
    monkeypatch.setattr(profile_manager, "get_user_profile", fake.get_user_profile)
    monkeypatch.setattr(profile_manager, "save_user_profile", fake.save_user_profile)
    monkeypatch.setattr(
        profile_manager, "update_planning_explicit_profile", fake.update_planning_explicit_profile
    )
    return fake


@pytest.fixture
def code_stubs(monkeypatch):
    """code 走 `code_enrichment`（评审口径："值带 code"）——这里打桩成确定性编码。"""

    async def major_codes(values, level, batch):
        return [f"{level}:{value}" for value in values]

    async def school_codes(values):
        return [f"school:{value}" for value in values]

    async def province_codes(values):
        return [f"province:{value}" for value in values]

    async def city_codes(values):
        return [f"city:{value}" for value in values]

    monkeypatch.setattr("app.util.code_enrichment.get_major_codes_async", major_codes)
    monkeypatch.setattr("app.util.code_enrichment.get_school_codes_async", school_codes)
    monkeypatch.setattr("app.util.code_enrichment.get_province_codes_async", province_codes)
    monkeypatch.setattr("app.util.code_enrichment.get_city_codes_async", city_codes)


def _major_values(saved: dict, key: str) -> list[str]:
    payload = saved.get(key) or {}
    return [value for level in ("level1", "level2", "level3") for value in (payload.get(level) or [])]


# ── ① 确认成功 → 值 + code 落库 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmed_merge_writes_values_and_codes(backend, code_stubs):
    result = await merge_confirmed_intents_into_profile(
        "900001",
        major_intents={"level3": ["临床医学"], "negative_level3": ["口腔医学"]},
        school_intents={"colleges": ["浙江大学"]},
        region_intents={"province": ["北京市"], "negative_city": ["天津市"]},
    )

    assert result["applied"] is True
    assert sorted(result["updated"]) == ["major", "region", "school"]
    saved = backend.saves[0]
    assert saved["major_intent"]["level3"] == ["临床医学"]
    assert saved["major_intent"]["level3_code"] == ["level3:临床医学"]
    assert saved["negative_major_intent"]["level3"] == ["口腔医学"]
    assert saved["negative_major_intent"]["level3_code"] == ["level3:口腔医学"]
    assert saved["college_info"]["values"] == ["浙江大学"]
    assert saved["college_info"]["values_code"] == ["school:浙江大学"]
    assert saved["city_info"]["province"] == ["北京市"]
    assert saved["city_info"]["province_code"] == ["province:北京市"]
    assert saved["negative_city_info"]["city"] == ["天津市"]
    assert saved["negative_city_info"]["city_code"] == ["city:天津市"]
    # 显式规划画像同步（与 legacy ProfileManager 写回同一口径）。
    assert backend.explicit_calls == [
        {
            "major_preferences": {"positive": ["临床医学"], "negative": ["口腔医学"]},
            "school_preferences": {"positive": ["浙江大学"], "negative": []},
            "region_preferences": {"positive": ["北京市"], "negative": ["天津市"]},
        }
    ]


@pytest.mark.asyncio
async def test_gateway_constraint_confirm_merges_into_userprofile(monkeypatch, backend, code_stubs):
    """挂点 A：网关约束确认（applied）后，同源意向并入 userprofile。"""
    execute_calls: list[dict] = []

    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "applied"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    async def executor(*args, **kwargs):
        execute_calls.append(kwargs)
        return {"code": 0, "data": {"status": "applied", "stateVersion": 9}}

    async def empty_lookup(*args, **kwargs):
        return {"resultType": "empty", "data": None}

    monkeypatch.setattr(internal_client, "catalog_lookup_major", empty_lookup)
    monkeypatch.setattr(internal_client, "catalog_lookup_city", empty_lookup)
    monkeypatch.setattr(internal_client, "catalog_lookup_province", empty_lookup)

    snapshot = {
        "snapshotVersion": 7,
        "sessionId": "900222",
        "scoreContext": {"batch": "本科批"},
        "activeProposal": {
            "proposalRef": "pending-1",
            "pendingId": "pending-1",
            "sourceVersion": 7,
            "revision": 3,
            "data": {
                "operationId": "op-9",
                "proposalId": "proposal-9",
                "proposalSource": "user_goal",
                "userGoalRequest": {
                    "goalType": "must_include_scope",
                    "targetScopes": [
                        {"scopeType": "school", "entityType": "school", "name": "浙江大学"},
                        {"scopeType": "major_scope", "entityType": "major", "name": "临床医学"},
                        {
                            "scopeType": "province_scope",
                            "entityType": "region",
                            "name": "北京市",
                            "scopeLevel": "province",
                        },
                    ],
                    "negativeScopes": [
                        {
                            "scopeType": "city_scope",
                            "entityType": "region",
                            "name": "天津市",
                            "scopeLevel": "city",
                        },
                    ],
                },
            },
        },
    }

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="900222",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot,
        resolver=resolver,
        executor=executor,
    )

    assert result.action_status == "applied"
    assert execute_calls and execute_calls[0]["command_type"] == "apply_constraint_and_regenerate"
    assert backend.saves, "约束确认成功后必须把同源意向并入 userprofile"
    saved = backend.saves[-1]
    assert saved["college_info"]["values"] == ["浙江大学"]
    assert saved["college_info"]["values_code"] == ["school:浙江大学"]
    assert _major_values(saved, "major_intent") == ["临床医学"]
    assert saved["city_info"]["province"] == ["北京市"]
    assert saved["negative_city_info"]["city"] == ["天津市"]
    assert backend.explicit_calls


@pytest.mark.asyncio
async def test_gateway_confirm_does_not_merge_when_command_fails(monkeypatch, backend, code_stubs):
    """未生效（failed）不落库：只有成功点才并集写回。"""

    async def resolver(session_id, **kwargs):
        if kwargs.get("action") in {"complete", "fail"}:
            return {"code": 0, "data": {"status": "failed"}}
        return {"code": 0, "data": {"status": "applying", "revision": 4, "transitionApplied": True}}

    async def executor(*args, **kwargs):
        return {"code": 40001, "data": {"status": "failed"}}

    async def empty_lookup(*args, **kwargs):
        return {"resultType": "empty", "data": None}

    monkeypatch.setattr(internal_client, "catalog_lookup_major", empty_lookup)
    monkeypatch.setattr(internal_client, "catalog_lookup_city", empty_lookup)
    monkeypatch.setattr(internal_client, "catalog_lookup_province", empty_lookup)

    snapshot = {
        "snapshotVersion": 7,
        "sessionId": "900223",
        "activeProposal": {
            "proposalRef": "pending-1",
            "pendingId": "pending-1",
            "sourceVersion": 7,
            "revision": 3,
            "data": {
                "operationId": "op-9",
                "proposalId": "proposal-9",
                "proposalSource": "user_goal",
                "userGoalRequest": {
                    "goalType": "must_include_scope",
                    "targetScopes": [{"scopeType": "school", "entityType": "school", "name": "浙江大学"}],
                    "negativeScopes": [],
                },
            },
        },
    }

    result = await execute_conversation_action(
        tenant_id="tenant-7",
        session_id="900223",
        action={"actionType": "confirm_proposal", "proposalRef": "pending-1"},
        snapshot=snapshot,
        resolver=resolver,
        executor=executor,
    )

    assert result.action_status == "failed"
    assert backend.saves == []


@pytest.mark.asyncio
async def test_tools_constraint_confirm_merges_into_userprofile(monkeypatch):
    """挂点 B：工具确认（constraint_updated）后，同源意向并入 userprofile。"""
    merge_calls: list[tuple] = []

    async def fake_merge(session_id, **kwargs):
        merge_calls.append((session_id, kwargs))
        return {"applied": True, "updated": ["major"]}

    async def fake_execute(*args, **kwargs):
        return {
            "code": 0,
            "data": {"completedSteps": ["constraint_updated", "ordered_plan_regenerated"], "planningState": {}},
        }

    monkeypatch.setattr(tools_mod, "merge_confirmed_intents_into_profile", fake_merge)
    monkeypatch.setattr(tools_mod.internal_client, "execute_pending_planning_command", fake_execute)

    ctx = SimpleNamespace(
        deps=SimpleNamespace(sessionid="900321", batch="01", tenant_id=1, sandbox=None)
    )
    merged = {
        "major_intents": {"level3": ["临床医学"], "negative_level3": ["口腔医学"], "major_tag": ["985"]},
        "school_intents": {"colleges": ["浙江大学"]},
        "city_intents": {"negative_province": ["西藏自治区"]},
    }
    pending = {
        "pending_id": "pending-major",
        "execution_payload": {"merged": merged, "intentMode": "constraint"},
    }

    success, data, _message = await tools_mod._apply_intent_pending(ctx, pending)

    assert success is True
    assert data["constraint_state_applied"] is True
    assert len(merge_calls) == 1
    session_id, kwargs = merge_calls[0]
    assert session_id == "900321"
    assert kwargs["batch"] == "01"
    # 值取自同一份 merged（与 constraintUpdate 同源）；属性键交给上游的 constraintUpdate。
    assert kwargs["major_intents"] == merged["major_intents"]
    assert kwargs["school_intents"] == merged["school_intents"]
    assert kwargs["region_intents"] == merged["city_intents"]


@pytest.mark.asyncio
async def test_tools_confirm_does_not_merge_without_constraint_success(monkeypatch):
    merge_calls: list[tuple] = []

    async def fake_merge(session_id, **kwargs):
        merge_calls.append((session_id, kwargs))
        return {"applied": True, "updated": ["major"]}

    async def fake_execute(*args, **kwargs):
        return {"code": 0, "data": {"completedSteps": [], "planningState": {}}}

    monkeypatch.setattr(tools_mod, "merge_confirmed_intents_into_profile", fake_merge)
    monkeypatch.setattr(tools_mod.internal_client, "execute_pending_planning_command", fake_execute)

    ctx = SimpleNamespace(
        deps=SimpleNamespace(sessionid="900322", batch="01", tenant_id=1, sandbox=None)
    )
    pending = {
        "pending_id": "pending-major",
        "execution_payload": {
            "merged": {"major_intents": {"level3": ["临床医学"]}},
            "intentMode": "constraint",
        },
    }

    success, data, _message = await tools_mod._apply_intent_pending(ctx, pending)

    assert success is True
    assert data["constraint_state_applied"] is False
    assert merge_calls == []


# ── ② 重复 / 并发确认：并集不丢不覆盖 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_confirmation_unions_without_losing_previous(backend, code_stubs):
    await merge_confirmed_intents_into_profile("900002", major_intents={"level3": ["临床医学"]})
    await merge_confirmed_intents_into_profile("900002", major_intents={"level3": ["软件工程"]})

    saved = backend.saves[-1]
    assert set(_major_values(saved, "major_intent")) == {"临床医学", "软件工程"}


@pytest.mark.asyncio
async def test_concurrent_confirmation_keeps_both_unions(backend, code_stubs):
    """并发确认：读-改-写串行（不串行时后写的会吃掉先写的并集）。"""
    backend.read_delay = 0.01
    backend.write_delay = 0.01

    await asyncio.gather(
        merge_confirmed_intents_into_profile("900003", major_intents={"level3": ["临床医学"]}),
        merge_confirmed_intents_into_profile("900003", school_intents={"colleges": ["浙江大学"]}),
    )

    saved = backend.saves[-1]
    assert _major_values(saved, "major_intent") == ["临床医学"]
    assert saved["college_info"]["values"] == ["浙江大学"]


# ── ③ 正负互斥 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_positive_confirmation_removes_existing_negative_same_object(backend, code_stubs):
    backend.profile = {
        "negative_major_intent": {"level3": ["临床医学"], "level3_emotion": ["Strong"]},
    }

    await merge_confirmed_intents_into_profile("900004", major_intents={"level3": ["临床医学"]})

    saved = backend.saves[-1]
    assert saved["major_intent"]["level3"] == ["临床医学"]
    assert saved["negative_major_intent"]["level3"] == []


@pytest.mark.asyncio
async def test_contradictory_payload_never_writes_both_sides(backend, code_stubs):
    """同一次确认里同时 include/exclude 同一对象：正压负，两侧永远不会同时出现。"""
    await merge_confirmed_intents_into_profile(
        "900005",
        major_intents={"level3": ["临床医学"], "negative_level3": ["临床医学"]},
        school_intents={"colleges": ["浙江大学"], "negative_colleges": ["浙江大学"]},
        region_intents={"province": ["北京市"], "negative_province": ["北京市"]},
    )

    saved = backend.saves[0]
    assert saved["major_intent"]["level3"] == ["临床医学"]
    assert saved["negative_major_intent"]["level3"] == []
    assert saved["college_info"]["values"] == ["浙江大学"]
    assert saved["negative_college_info"]["values"] == []
    assert saved["city_info"]["province"] == ["北京市"]
    assert saved["negative_city_info"]["province"] == []


@pytest.mark.asyncio
async def test_negative_confirmation_removes_existing_positive_same_object(backend, code_stubs):
    backend.profile = {
        "college_info": {"values": ["浙江大学"], "values_emotion": ["Strong"]},
    }

    await merge_confirmed_intents_into_profile("900009", school_intents={"negative_colleges": ["浙江大学"]})

    saved = backend.saves[-1]
    assert saved["college_info"]["values"] == []
    assert saved["negative_college_info"]["values"] == ["浙江大学"]


# ── ④ 只并集：不覆盖既有无关字段（整串覆盖写回的前提是 merge）──────────────────


@pytest.mark.asyncio
async def test_merge_keeps_unrelated_existing_fields(backend, code_stubs):
    backend.profile = {
        "major_intent": {"level2": ["财政学类"], "level2_emotion": ["Strong"]},
        "college_info": {"values": ["浙江大学"], "values_emotion": ["Strong"]},
        "city_info": {"province": ["北京市"], "province_emotion": ["Strong"]},
        "strength_subject_info": {"values": ["物理"], "values_emotion": [], "values_code": []},
        # 模型不承载的族（排序侧读 tag_info.values）：整串覆盖也不许被置空。
        "tag_info": {"values": ["985"], "values_emotion": ["Strong"]},
        "negative_tag_info": {"values": None, "values_emotion": None},
    }

    result = await merge_confirmed_intents_into_profile(
        "900006", region_intents={"negative_province": ["西藏自治区"]}
    )

    assert result["updated"] == ["region"]
    saved = backend.saves[0]
    assert saved["major_intent"]["level2"] == ["财政学类"]
    assert saved["college_info"]["values"] == ["浙江大学"]
    assert saved["city_info"]["province"] == ["北京市"]
    assert saved["strength_subject_info"]["values"] == ["物理"]
    assert saved["tag_info"] == {"values": ["985"], "values_emotion": ["Strong"]}
    assert saved["negative_city_info"]["province"] == ["西藏自治区"]


# ── 旁路纪律：读不到不写、非数字会话跳过、无内容不空写、失败不影响主链路 ────────


@pytest.mark.asyncio
async def test_unreadable_profile_never_overwrites(monkeypatch, backend):
    """读失败 fail-closed：绝不拿空画像整串覆盖既有画像。"""
    broken = FakeProfileBackend(read_error="backend down")
    monkeypatch.setattr(profile_manager, "get_user_profile", broken.get_user_profile)
    monkeypatch.setattr(profile_manager, "save_user_profile", broken.save_user_profile)
    monkeypatch.setattr(
        profile_manager, "update_planning_explicit_profile", broken.update_planning_explicit_profile
    )

    result = await merge_confirmed_intents_into_profile("900007", major_intents={"level3": ["临床医学"]})

    assert result["applied"] is False
    assert result["reason"] == "merge_failed"
    assert broken.saves == []


@pytest.mark.asyncio
async def test_error_response_never_overwrites(monkeypatch):
    broken = FakeProfileBackend()

    async def failing_get(session_id):
        return {"code": 500, "msg": "boom"}

    monkeypatch.setattr(profile_manager, "get_user_profile", failing_get)
    monkeypatch.setattr(profile_manager, "save_user_profile", broken.save_user_profile)

    result = await merge_confirmed_intents_into_profile("900010", major_intents={"level3": ["临床医学"]})

    assert result["applied"] is False
    assert broken.saves == []


@pytest.mark.asyncio
async def test_non_numeric_session_id_skips_without_network(backend, code_stubs):
    result = await merge_confirmed_intents_into_profile("s1", major_intents={"level3": ["临床医学"]})

    assert result == {"applied": False, "reason": "invalid_session_id"}
    assert backend.reads == 0
    assert backend.saves == []


@pytest.mark.asyncio
async def test_payload_without_confirmed_intents_skips_without_network(backend):
    result = await merge_confirmed_intents_into_profile(
        "900008",
        major_intents={"major_tag": ["985"], "program_type": ["普通类"]},
        school_intents={"school_nature": ["公办"]},
    )

    assert result["applied"] is False
    assert result["reason"] == "no_confirmed_intents"
    assert backend.reads == 0
    assert backend.saves == []
