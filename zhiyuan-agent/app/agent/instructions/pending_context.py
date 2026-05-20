"""待确认操作注入段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.context import resolve_pending_confirmation, resolve_pending_plan_payload_text

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_pending_context(deps: RequestContext) -> str:
    """将 pending plan action 注入到指令中。

    新字段优先；当 conversation_phase 已注入时，只读取 conversation_phase.pending。
    旧 pending_plan_action dict 仅用于尚未注入 phase 的兼容入口。
    """
    pending = resolve_pending_confirmation(deps)
    if pending is None or pending.kind != "plan_mutation":
        return ""

    plan_payload = resolve_pending_plan_payload_text(deps)
    return (
        "当前存在上一轮待确认的方案动作：\n"
        f"- 动作类型：{pending.action_family}\n"
        f"- 预览摘要：{pending.preview_summary}\n"
        f"- 影响范围：{pending.affected_scope}\n"
        f"- 确认后执行 payload：{plan_payload}\n"
        "如果用户本轮明确表示确认、执行、就按这个来，不要重新规划或猜测参数，"
        "直接调用 `execute_plan_action` 并传入上一轮的确认后执行 payload。"
    )
