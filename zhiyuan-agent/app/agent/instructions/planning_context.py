"""方案状态注入段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_planning_context(deps: RequestContext) -> str:
    """将 planning_summary 注入到指令中。"""
    planning = deps.planning_summary
    if not planning or not planning.phase:
        return ""

    lines = [
        f"- 当前规划阶段：{planning.phase}",
        f"- 当前草稿志愿数：{planning.draft_total}",
        f"- 当前排序志愿数：{planning.ordered_total}",
    ]
    if planning.review_risk_count > 0 or planning.review_warn_count > 0:
        lines.append(
            f"- 当前风险摘要：风险{planning.review_risk_count}项，提醒{planning.review_warn_count}项"
        )
    if planning.risk_summaries:
        lines.append(f"- 当前主要风险：{'；'.join(planning.risk_summaries)}")
    if planning.pending_action_count > 0:
        lines.append(
            f"- 当前待处理建议：{planning.pending_action_count}项，主要为：{'；'.join(planning.pending_action_summaries)}"
        )

    return (
        "当前会话已存在统一规划状态，请基于现有方案继续推进，不要把用户当作完全未开始填报：\n"
        + "\n".join(lines)
        + "\n如果用户是在追问风险、补偿或排序，请优先围绕当前规划状态回答。"
        "\n当前 planning 状态的优先级高于历史对话。如果当前草稿志愿数和排序志愿数都是0，就说明还没有正式方案；"
        "即使历史里提到过候选、推荐或50个志愿，也不能把它们当成当前方案来审查、补稳或调整。"
    )
