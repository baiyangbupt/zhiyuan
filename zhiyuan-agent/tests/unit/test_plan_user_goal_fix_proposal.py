from app.tools.plan_orchestration_models import PlanGoal
from app.tools.plan_user_goal_fix_proposal import (
    build_user_goal_fix_proposal_req_from_goal_payload,
    build_user_goal_fix_proposal_req_from_plan_goal,
    linked_repair_proposal_from_backend,
    scopes_for_user_goal_fix_req,
)


def test_scopes_for_user_goal_fix_req_expands_multi_value_scope():
    scopes = scopes_for_user_goal_fix_req(
        {"entity_type": "major", "values": ["会计学", "审计学"]},
        evidence_source="plan_goal",
    )

    assert [scope["normalizedName"] for scope in scopes] == ["会计学", "审计学"]
    assert all(scope["entityType"] == "major" for scope in scopes)
    assert scopes[0]["evidence"]["values"] == ["会计学", "审计学"]


def test_build_user_goal_fix_req_from_plan_goal_keeps_optional_version_guard():
    goal = PlanGoal(
        goal_type="exclude_scope",
        user_original_text="不要会计和审计",
        negative_scopes=[{"entity_type": "major", "values": ["会计学", "审计学"]}],
        confidence="high",
    )

    payload = build_user_goal_fix_proposal_req_from_plan_goal(goal, 0)

    assert payload is not None
    assert payload["proposalSource"] == "user_goal"
    assert payload["goalType"] == "exclude_scope"
    assert payload["sourceVersionGuard"] is None
    assert [scope["normalizedName"] for scope in payload["negativeScopes"]] == ["会计学", "审计学"]
    assert payload["targetScopes"] == []


def test_build_user_goal_fix_req_from_goal_payload_requires_version_guard():
    goal = {
        "goal_type": "only_keep_scope",
        "user_original_text": "只保留临床医学",
        "target_scopes": [{"entity_type": "major", "values": ["临床医学"]}],
    }

    assert build_user_goal_fix_proposal_req_from_goal_payload(goal, 0) is None

    payload = build_user_goal_fix_proposal_req_from_goal_payload(
        goal,
        12,
        context={"source": "service"},
        evidence_source="confirmed_intent",
    )

    assert payload is not None
    assert payload["sourceVersionGuard"] == 12
    assert payload["context"] == {"source": "service"}
    assert payload["targetScopes"][0]["evidence"]["source"] == "confirmed_intent"


def test_linked_repair_proposal_from_backend_accepts_camel_and_snake_fields():
    proposal = linked_repair_proposal_from_backend(
        {
            "proposal_id": "ugp-1",
            "proposal_source": "user_goal",
            "source_version": 12,
            "source_version_guard": 12,
            "strategy": "exclude_scope",
            "status": "preview_only",
            "actions": [
                {
                    "action_type": "replace_volunteers",
                    "remove_volunteer_ids": ["old-1"],
                    "candidate_volunteer_ids": ["new-1"],
                    "replacement_pairs": [{"fromVolunteerId": "old-1", "toVolunteerId": "new-1"}],
                }
            ],
            "dry_run_result": {"status": "preview_only"},
        },
        default_source="user_goal",
        default_source_version_guard=12,
    )

    assert proposal is not None
    assert proposal.proposal_source == "user_goal"
    assert proposal.strategy == "exclude_scope"
    assert proposal.applyable is False
    assert proposal.actions[0].action_type == "replace_volunteers"
    assert proposal.actions[0].replacement_pairs[0]["toVolunteerId"] == "new-1"

