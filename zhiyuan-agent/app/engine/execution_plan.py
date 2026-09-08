from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.engine.working_set import ConversationWorkingSet
from app.gateway.contracts import ConversationTurnSnapshot


TASK_FAMILIES = (
    "intake",
    "query",
    "explore",
    "plan_review",
    "plan_mutation",
    "confirmation",
    "clarification",
    "unclassified",
)


@dataclass(slots=True)
class PlanStep:
    step_id: str
    description: str
    status: str = "pending"
    required_tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionPlan:
    """A model-facing execution scaffold, not an intent classifier.

    Codex remains responsible for understanding the user's objective, choosing
    tools, and refining the plan. The gateway only supplies authoritative
    state-derived blockers and a stable completion contract.
    """

    objective: str
    task_family: str
    steps: list[PlanStep]
    required_tools: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    finish_condition: str = "完成用户目标，或明确说明仍缺少的关键信息。"
    user_visible_next_step: str | None = None

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["taskFamily"] = payload.pop("task_family")
        payload["requiredTools"] = payload.pop("required_tools")
        payload["completedSteps"] = payload.pop("completed_steps")
        payload["blockedSteps"] = payload.pop("blocked_steps")
        payload["finishCondition"] = payload.pop("finish_condition")
        payload["userVisibleNextStep"] = payload.pop("user_visible_next_step")
        payload["steps"] = [
            {
                "stepId": step.step_id,
                "description": step.description,
                "status": step.status,
                "requiredTools": step.required_tools,
            }
            for step in self.steps
        ]
        return payload


def build_execution_plan(
    snapshot: ConversationTurnSnapshot,
    working_set: ConversationWorkingSet,
) -> ExecutionPlan:
    """Build only the deterministic scaffold available before user parsing."""
    if working_set.active_proposal or snapshot.active_proposal:
        task_family = "confirmation"
        objective = "处理当前待确认方案；先核对方案内容和用户意图。"
    elif snapshot.missing_facts:
        task_family = "clarification"
        objective = "完成用户本轮请求，并先补齐业务状态缺口。"
    else:
        task_family = "unclassified"
        objective = "理解并完成用户本轮请求。"

    blocked_steps = list(snapshot.missing_facts)
    next_step = (
        "向用户澄清缺失信息：" + "、".join(blocked_steps)
        if blocked_steps
        else None
    )
    return ExecutionPlan(
        objective=objective,
        task_family=task_family,
        steps=[
            PlanStep("understand", "理解用户目标并确定任务类型"),
            PlanStep("resolve_context", "解析当前会话中的实体、约束和指代"),
            PlanStep("execute", "仅在参数完整时调用所需领域工具"),
            PlanStep("verify", "检查事实来源、版本和结果覆盖范围"),
            PlanStep("respond", "按事实、限制、下一步组织回复"),
        ],
        blocked_steps=blocked_steps,
        user_visible_next_step=next_step,
    )
