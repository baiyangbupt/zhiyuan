import json

import pytest

from app.engine.working_set import ConversationWorkingSet
from app.gateway.contracts import ConversationTurnSnapshot, TurnOutput


def test_working_set_projects_validated_cross_turn_objects() -> None:
    snapshot = ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    working_set = ConversationWorkingSet.from_snapshot(snapshot)
    output = TurnOutput(
        responseType="clarification",
        message="还缺少省份",
        uncertainties=["province"],
        proposalRef="proposal-1",
    )

    working_set.apply_output(output, "turn-2")
    payload = working_set.as_payload()

    assert payload["snapshotVersion"] == 7
    assert payload["activeProposal"]["proposalRef"] == "proposal-1"
    assert payload["activeProposal"]["status"] == "pending_confirmation"
    assert payload["activeProposal"]["requiresConfirmation"] is True
    assert payload["lastTurnId"] == "turn-2"
    assert payload["lastResponseType"] == "clarification"


def test_working_set_projects_proposal_as_readonly_confirmation_state() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=7,
            sessionId="s1",
            activeProposal={
                "pendingId": "pending-1",
                "status": "active",
                "actionFamily": "remove_plan_item",
                "operations": [{"target": "school-3"}],
                "sourceVersion": 7,
            },
        )
    )

    assert working_set.active_proposal == {
        "proposalRef": "pending-1",
        "status": "active",
        "requiresConfirmation": True,
        "sourceVersion": 7,
        "summary": "",
        "actionFamily": "remove_plan_item",
        "changes": [{"target": "school-3"}],
        "blockingReason": None,
    }


def test_working_set_does_not_replace_new_snapshot_constraints() -> None:
    old = ConversationTurnSnapshot(
        snapshotVersion=7,
        sessionId="s1",
        confirmedConstraints={"hard": {"annualTuitionMax": 20000}},
    )
    new = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=8,
            sessionId="s1",
            confirmedConstraints={"hard": {"annualTuitionMax": 15000}},
        )
    )
    assert old.confirmed_constraints["hard"]["annualTuitionMax"] == 20000
    assert new.confirmed_constraints["hard"]["annualTuitionMax"] == 15000


def test_working_set_projects_only_stable_tool_entities() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )

    working_set.ingest_payload(
        {
            "events": [
                {
                    "type": "mcpToolCall",
                    "result": {
                        "resolvedEntities": [
                            {"entityId": "school-1", "entityType": "school", "name": "甲大学"},
                            {"name": "没有稳定 ID"},
                        ],
                        "data": {"candidates": [{"id": "school-2", "name": "乙大学"}]},
                    },
                }
            ]
        }
    )

    assert [item["entityId"] for item in working_set.candidate_entities] == [
        "school-1",
        "school-2",
    ]

    working_set.ingest_payload(
        {"resolvedEntities": [{"entityId": "school-1", "name": "甲大学（更新）"}]}
    )
    assert [item["entityId"] for item in working_set.candidate_entities] == [
        "school-2",
        "school-1",
    ]
    assert working_set.candidate_entities[-1]["name"] == "甲大学（更新）"


def test_working_set_invalidates_candidates_when_stage_changes() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=7, sessionId="s1", planningStage="candidate_exploration"
        )
    )
    working_set.ingest_payload(
        {"resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}]},
        turn_id="turn-1",
    )

    working_set.reconcile_snapshot(
        ConversationTurnSnapshot(snapshotVersion=8, sessionId="s1", planningStage="plan_review")
    )

    assert working_set.candidate_entities == []
    assert working_set.candidate_source_turn_id is None
    assert working_set.candidate_scope_version == 8


def test_working_set_drops_stale_artifact_refs_when_version_advances() -> None:
    """2026-10-17 真事故：工作集把 v1 旧产物一直摆在模型面前，模型在新回合（v5）
    里把它和新产物一起抄进 artifactRefs → stale_state。快照版本推进后旧引用应被淘汰。"""
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )
    working_set.artifact_refs = [
        {"artifactId": "old", "artifactType": "candidate", "stateVersion": 6},
        {"artifactId": "cur", "artifactType": "candidate", "stateVersion": 7},
        {"artifactId": "future", "artifactType": "candidate", "stateVersion": 8},
        {"artifactId": "no-version", "artifactType": "candidate"},
        {"artifactId": "alias", "artifactType": "candidate", "state_version": 8},
    ]

    working_set.reconcile_snapshot(
        ConversationTurnSnapshot(snapshotVersion=8, sessionId="s1")
    )

    assert [item["artifactId"] for item in working_set.artifact_refs] == [
        "future",
        "no-version",
        "alias",
    ]


def test_working_set_context_text_explicitly_names_candidates_and_ids() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )
    working_set.candidate_entities = [
        {"entityId": "school-1", "name": "甲大学"},
        {"entityId": "school-2", "name": "乙大学"},
    ]

    text = working_set.as_context_text()

    assert "当前候选学校：甲大学（ID=school-1）、乙大学（ID=school-2）" in text
    assert "不要说看不到候选" in text


def test_working_set_context_text_exposes_confirmed_query_scope() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=7,
            sessionId="s1",
            confirmedConstraints={"historyQuery": {"areaId": "330000", "majorId": "major-cs"}},
        )
    )

    assert "已确认历史查询参数：areaId=330000, majorId=major-cs" in working_set.as_context_text()


def test_empty_candidate_context_does_not_forbid_acknowledging_missing_objects() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )

    text = working_set.as_context_text()

    assert "不要说看不到候选" not in text
    assert "当前候选学校：当前工作集未保留候选对象" in text
    assert "当前没有已确认候选" not in text


def test_empty_candidate_context_preserves_available_history_as_a_reference_source() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )

    text = working_set.as_context_text()

    assert "不代表线程历史中从未出现候选" in text
    assert "优先使用可用历史中的明确对象和可靠来源解析指代" in text
    assert "不要编造候选或对象 ID" in text


def test_empty_candidate_context_limits_clarification_and_requery_to_unresolved_requests() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )

    text = working_set.as_context_text()

    assert "仅当本轮请求依赖候选且仍无法解析时" in text
    assert "澄清缺失条件，或使用已获准的只读查询" in text
    assert "重新查询不等于恢复上一批候选" in text
    assert "当前条件下的新结果" in text


@pytest.mark.parametrize("has_candidates", [False, True], ids=["empty", "known"])
def test_candidate_guidance_preserves_query_scope_and_structured_context(
    has_candidates: bool,
) -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=7,
            sessionId="s1",
            planningStage="candidate_exploration",
            confirmedConstraints={"historyQuery": {"areaId": "330000", "majorId": "major-cs"}},
        )
    )
    if has_candidates:
        working_set.ingest_payload(
            {"resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}]},
            turn_id="turn-1",
        )

    text = working_set.as_context_text()
    payload = json.loads(text.split("结构化状态：", 1)[1])

    assert "已确认历史查询参数：areaId=330000, majorId=major-cs" in text
    assert "仍必须向用户询问缺失的省份、科类、批次、专业等参数" in text
    assert payload["snapshotVersion"] == 7
    assert payload["sessionId"] == "s1"
    assert payload["confirmedConstraints"] == {
        "historyQuery": {"areaId": "330000", "majorId": "major-cs"}
    }
    assert payload["candidateEntities"] == (
        [{"entityId": "school-1", "name": "甲大学"}] if has_candidates else []
    )
    assert payload["candidateSet"] == {
        "scopeVersion": 7,
        "planningStage": "candidate_exploration",
        "sourceTurnId": "turn-1" if has_candidates else None,
        "items": [{"entityId": "school-1", "name": "甲大学"}] if has_candidates else [],
    }


def test_candidate_context_keeps_rolling_entities_from_multiple_turns() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )
    working_set.ingest_payload(
        {"resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}]},
        turn_id="turn-1",
    )
    working_set.ingest_payload(
        {"resolvedEntities": [{"entityId": "school-2", "name": "乙大学"}]},
        turn_id="turn-2",
    )

    text = working_set.as_context_text()
    payload = json.loads(text.split("结构化状态：", 1)[1])

    assert "当前候选学校：甲大学（ID=school-1）、乙大学（ID=school-2）" in text
    assert "不要说看不到候选" in text
    assert payload["candidateSet"]["items"] == [
        {"entityId": "school-1", "name": "甲大学"},
        {"entityId": "school-2", "name": "乙大学"},
    ]
    assert payload["candidateSet"]["sourceTurnId"] == "turn-2"


@pytest.mark.parametrize("result_key", ["items", "candidates"])
def test_empty_tool_result_keeps_known_candidate_context_and_source(result_key: str) -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )
    working_set.ingest_payload(
        {"resolvedEntities": [{"entityId": "school-1", "name": "甲大学"}]},
        turn_id="turn-1",
    )

    working_set.ingest_payload({"data": {result_key: []}}, turn_id="turn-2")
    text = working_set.as_context_text()
    payload = json.loads(text.split("结构化状态：", 1)[1])

    assert "当前候选学校：甲大学（ID=school-1）" in text
    assert "不要说看不到候选" in text
    assert payload["candidateSet"]["items"] == [{"entityId": "school-1", "name": "甲大学"}]
    assert payload["candidateSet"]["sourceTurnId"] == "turn-1"


def test_working_set_clears_blocked_planned_task_draft() -> None:
    snapshot = ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    working_set = ConversationWorkingSet.from_snapshot(snapshot)
    working_set.task_draft = {"stale": True}
    output = TurnOutput(
        responseType="text",
        message="删除动作尚未支持。",
        intentDraft={
            "sourceTurnId": "turn-1",
            "userText": "删掉 B",
            "goalFamily": "plan_mutation",
            "action": "remove",
            "targets": [{"schoolName": "B大学", "majorName": "计算机"}],
            "validity": "this_adjustment",
        },
    )

    working_set.apply_output(output, "turn-1")

    assert working_set.task_draft is None
    assert working_set.as_payload()["taskDraft"] is None
    assert working_set.has_open_task() is False


def test_working_set_keeps_manual_review_digest() -> None:
    working_set = ConversationWorkingSet.from_snapshot(
        ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    )

    working_set.mark_manual_review("digest-v1", 7)

    payload = working_set.as_payload()
    assert payload["lastManualReviewDigest"] == "digest-v1"
    assert payload["lastManualReviewVersion"] == 7


def test_working_set_keeps_a_bounded_composite_task_draft() -> None:
    snapshot = ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    working_set = ConversationWorkingSet.from_snapshot(snapshot)
    output = TurnOutput(
        responseType="text",
        message="先确认约束，再预览加入。",
        intentDraft={
            "sourceTurnId": "turn-1",
            "userText": "加 A，学费三万内",
            "goalFamily": "plan_mutation",
            "action": "add",
            "targets": [{"schoolName": "A大学", "majorName": "计算机"}],
            "scopes": [
                {"scopeType": "tuition", "name": "30000", "strength": "must"}
            ],
            "validity": "unknown",
        },
    )

    working_set.apply_output(output, "turn-1")
    payload = working_set.as_payload()

    task = payload["taskDraft"]
    assert task["changeSet"]["status"] == "needs_constraints_first"
    assert task["changeSet"]["operations"][0]["kind"] == "constrain"
    assert task["intentDraft"]["targets"][0]["schoolName"] == "A大学"
    assert task["turnId"] == "turn-1"

    working_set.reconcile_snapshot(
        ConversationTurnSnapshot(snapshotVersion=8, sessionId="s1")
    )
    assert working_set.as_payload()["taskDraft"]["changeSet"]["status"] == (
        "needs_constraints_first"
    )


def test_cancel_proposal_clears_the_task_draft() -> None:
    snapshot = ConversationTurnSnapshot(snapshotVersion=7, sessionId="s1")
    working_set = ConversationWorkingSet.from_snapshot(snapshot)
    working_set.apply_output(
        TurnOutput(
            responseType="text",
            message="先约束再加入。",
            intentDraft={
                "sourceTurnId": "turn-1",
                "userText": "加 A，学费三万内",
                "goalFamily": "plan_mutation",
                "action": "add",
                "targets": [{"schoolName": "A大学", "majorName": "计算机"}],
                "scopes": [{"scopeType": "tuition", "name": "30000", "strength": "must"}],
                "validity": "unknown",
            },
        ),
        "turn-1",
    )
    assert working_set.task_draft is not None

    working_set.apply_output(
        TurnOutput(
            responseType="text",
            message="已取消。",
            conversationAction={
                "actionType": "cancel_proposal",
                "proposalRef": "pending-1",
                "intent": "explicit",
            },
        ),
        "turn-2",
    )

    assert working_set.task_draft is None
    assert working_set.as_payload()["taskDraft"] is None
