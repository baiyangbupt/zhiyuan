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
    assert payload["activeProposal"] == {"proposalRef": "proposal-1"}
    assert payload["lastTurnId"] == "turn-2"
    assert payload["lastResponseType"] == "clarification"


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
