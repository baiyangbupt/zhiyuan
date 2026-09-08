from app.engine.execution_plan import build_execution_plan
from app.engine.working_set import ConversationWorkingSet
from app.gateway.contracts import ConversationTurnSnapshot


def test_execution_plan_exposes_authoritative_missing_facts_without_classifying_user_text() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=7,
        sessionId="s1",
        missingFacts=["province", "subjectType"],
    )
    working_set = ConversationWorkingSet.from_snapshot(snapshot)

    plan = build_execution_plan(snapshot, working_set)

    assert plan.task_family == "clarification"
    assert plan.blocked_steps == ["province", "subjectType"]
    assert "province" in (plan.user_visible_next_step or "")
    assert [step.step_id for step in plan.steps] == [
        "understand",
        "resolve_context",
        "execute",
        "verify",
        "respond",
    ]


def test_execution_plan_marks_active_proposal_as_confirmation_scaffold() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=7,
        sessionId="s1",
        activeProposal={"proposalRef": "proposal-1"},
    )
    working_set = ConversationWorkingSet.from_snapshot(snapshot)

    plan = build_execution_plan(snapshot, working_set)

    assert plan.task_family == "confirmation"
    assert plan.blocked_steps == []
    assert plan.as_payload()["steps"][0]["stepId"] == "understand"
