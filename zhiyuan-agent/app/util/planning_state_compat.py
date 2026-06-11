from __future__ import annotations

from typing import Any


def get_working_plan_state(planning_state: dict[str, Any] | None) -> dict[str, Any]:
    """Return the active working-plan payload with legacy fallback.

    New sessions should use ``workingPlanState``. Older persisted sessions may
    still expose ``draftPlanState`` during the migration window.
    """
    state = planning_state or {}
    working_plan_state = state.get("workingPlanState")
    if working_plan_state is None:
        working_plan_state = state.get("draftPlanState")
    return working_plan_state or {}


def get_working_plan_summary(planning_state: dict[str, Any] | None) -> dict[str, Any]:
    """Return the summary block of the active working-plan state."""
    return (get_working_plan_state(planning_state).get("summary") or {})


def get_working_plan_items(planning_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the item list of the active working-plan state."""
    return list(get_working_plan_state(planning_state).get("items") or [])

