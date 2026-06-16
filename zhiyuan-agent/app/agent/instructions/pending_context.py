"""待确认操作注入段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.context import resolve_pending_confirmation, resolve_pending_plan_payload_text

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_pending_context(deps: RequestContext) -> str:
    """将 pending plan action 注入到指令中。

    只读取后端 active pendingConfirmation 投影出的 conversation_phase.pending。
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
        f"- 用户确认后执行 payload：{plan_payload}\n"
        "不要在模型回复里自行调用 `execute_plan_action` 执行这个 payload。"
        "明确的短文本确认会由服务端统一 pendingConfirmation 链路校验并执行；"
        "如果本轮仍进入模型，说明当前表达没有安全命中确认兜底。"
        "若用户是在追问审查解释、处理分类、影响范围、候选不足原因或当前方案状态，"
        "应按只读问题正常调用相应 Plan 工具或基于已知审查事实回答，并说明原预览仍未执行；"
        "只有用户确实是在表达确认但不够清楚时，才提示点击当前预览里的确认按钮，或重新说明要确认的内容以便重新生成预览。"
    )
