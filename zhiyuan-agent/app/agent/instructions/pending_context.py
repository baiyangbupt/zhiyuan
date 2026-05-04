"""待确认操作注入段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_pending_context(deps: RequestContext) -> str:
    """将 pending plan action 注入到指令中。

    同时兼容旧 pending_plan_action dict 和新 conversation_phase.pending。
    """
    # 优先消费新的 conversation_phase
    phase = getattr(deps, "conversation_phase", None)
    if phase and phase.pending:
        pending = phase.pending
        return (
            "当前存在上一轮待确认的方案动作：\n"
            f"- 动作类型：{pending.action_family}\n"
            f"- 预览摘要：{pending.preview_summary}\n"
            f"- 影响范围：{pending.affected_scope}\n"
            "如果用户本轮明确表示确认、执行、就按这个来，不要重新规划或猜测参数，"
            "直接调用 `execute_plan_action` 并传入上一轮的确认后执行 payload。"
        )

    # 兼容旧格式
    pending_plan_action = deps.pending_plan_action
    if not pending_plan_action:
        return ""

    action_family = pending_plan_action.get("action_family") or ""
    user_goal = pending_plan_action.get("user_goal") or ""
    summary = pending_plan_action.get("summary") or ""
    plan_payload = pending_plan_action.get("plan_payload") or ""

    return (
        "当前存在上一轮待确认的方案动作：\n"
        f"- 动作类型：{action_family}\n"
        f"- 用户目标：{user_goal}\n"
        f"- 预览摘要：{summary}\n"
        f"- 确认后执行 payload：{plan_payload}\n"
        "如果用户本轮明确表示确认、执行、就按这个来，不要重新规划或猜测参数，"
        "直接调用 `execute_plan_action` 并传入上面的确认后执行 payload。"
    )
