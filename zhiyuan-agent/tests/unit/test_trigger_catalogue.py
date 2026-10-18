"""J1 触发目录：契约校验，不冒充模型路由回归。

这组测试只证明目录自洽（动作/载体/槽位/状态/歧义形状），不证明模型会按目录走。
模型路由若要验证，另跑固定模型版本/温度的可选 live eval，不纳入 CI。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.gateway.contracts import ConversationTurnSnapshot
from app.gateway.journey import (
    ACTION_STATUS,
    IMPLEMENTED_ACTIONS,
    PLANNED_ACTIONS,
    available_actions,
    from_snapshot,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "trigger_catalogue.json"
GOAL_FAMILIES = {
    "discover", "query", "preference", "candidate",
    "plan_mutation", "review", "interpret", "meta",
}
FORBIDDEN_COPY = ("概率", "最可能", "滑档风险低", "风险等级")


def entries() -> list[dict]:
    return json.loads(FIXTURES.read_text("utf-8"))


def standard_context():
    return from_snapshot(
        ConversationTurnSnapshot(
            snapshotVersion=87,
            sessionId="s1",
            journey={
                "hasProfile": True,
                "hasCandidates": True,
                "hasPlan": True,
                "planInterpretable": True,
                "candidateFreshness": "fresh",
                "planFreshness": "fresh",
                "reviewFreshness": "fresh",
                "refreshRequirement": "none",
                "tierQuotaGoal": False,
                "pendingStatus": None,
            },
        )
    )


def test_catalogue_has_thirty_nine_unique_entries() -> None:
    rows = entries()
    assert len(rows) == 39
    assert len({row["id"] for row in rows}) == 39


def test_goal_families_and_actions_are_known() -> None:
    for row in entries():
        assert row["goalFamily"] in GOAL_FAMILIES, row["id"]
        assert row["expectedAction"] in ACTION_STATUS, row["id"]


def test_status_is_consistent_with_the_action_table() -> None:
    for row in entries():
        action_status = ACTION_STATUS[row["expectedAction"]]
        if action_status == "planned":
            assert row["status"] == "planned", row["id"]
        else:
            assert row["status"] in {"implemented", "partial"}, row["id"]
            assert row["status"] != "planned", row["id"]


def test_write_actions_declare_slots() -> None:
    for row in entries():
        if row["write"]:
            assert row["slots"], row["id"]
        else:
            assert row["slots"] == [], row["id"]


def test_carriers_are_real_names_and_do_not_promote_missing_contracts() -> None:
    for row in entries():
        carrier = str(row["carrier"] or "")
        assert carrier.strip(), row["id"]
        assert "goalType=prefer" not in carrier, row["id"]
        assert "system.action" not in carrier, row["id"]


def test_planned_entries_say_they_are_unsupported() -> None:
    for row in entries():
        if row["status"] == "planned":
            text = str(row["failureBehavior"])
            assert "尚未支持" in text or "待实现" in text, row["id"]


def test_ambiguity_is_one_closed_question() -> None:
    for row in entries():
        ambiguity = row["ambiguity"]
        if ambiguity is None:
            continue
        assert isinstance(ambiguity, dict), row["id"]
        assert str(ambiguity.get("question") or "").strip(), row["id"]
        options = ambiguity.get("options")
        assert isinstance(options, list) and 2 <= len(options) <= 3, row["id"]
        assert all(str(option).strip() for option in options), row["id"]


def test_user_facing_copy_avoids_predictive_language() -> None:
    for row in entries():
        text = str(row["failureBehavior"])
        for token in FORBIDDEN_COPY:
            assert token not in text, f"{row['id']} contains {token}"


def test_planned_actions_never_enter_available_actions() -> None:
    context = standard_context()
    assert context is not None
    assert not (set(available_actions(context)) & PLANNED_ACTIONS)
    assert IMPLEMENTED_ACTIONS.isdisjoint(PLANNED_ACTIONS)


def test_catalogue_covers_each_goal_family() -> None:
    counts: dict[str, int] = {}
    for row in entries():
        counts[row["goalFamily"]] = counts.get(row["goalFamily"], 0) + 1
    assert counts.get("query", 0) >= 6
    assert counts.get("candidate", 0) >= 5
    assert counts.get("preference", 0) >= 6
    assert counts.get("plan_mutation", 0) >= 8
    assert counts.get("review", 0) >= 3
    assert counts.get("interpret", 0) >= 3
    assert counts.get("meta", 0) >= 5
