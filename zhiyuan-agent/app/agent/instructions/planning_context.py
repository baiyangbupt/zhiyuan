"""方案状态注入段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_planning_context(deps: RequestContext) -> str:
    """将 planning_summary 注入到指令中，提供用户方案的核心信息。"""
    planning = deps.planning_summary
    if not planning or not planning.phase:
        return ""

    lines: list[str] = []

    # 方案总况
    if planning.ordered_total > 0:
        lines.append(f"用户当前方案已有 {planning.ordered_total} 个志愿（目标 {planning.ordered_target_total} 个）。")
    elif planning.draft_total > 0:
        lines.append(f"用户当前已加入方案 {planning.draft_total} 个志愿（目标 {planning.draft_target_total} 个），尚未生成正式顺序。")
    else:
        lines.append("用户尚未生成方案。")

    # 冲稳保分布
    tier = planning.tier_counts
    if tier:
        chong = tier.get("冲", 0)
        wen = tier.get("稳", 0)
        bao = tier.get("保", 0)
        if chong or wen or bao:
            lines.append(f"冲稳保分布：冲 {chong} 个、稳 {wen} 个、保 {bao} 个。")

    # 代表院校
    if planning.sample_schools:
        lines.append(f"方案涉及院校举例：{'、'.join(planning.sample_schools[:5])}。")

    # 偏好匹配
    if planning.positive_regions:
        lines.append(f"用户地区偏好：{'、'.join(planning.positive_regions[:5])}。")
    if planning.positive_majors:
        lines.append(f"用户专业偏好：{'、'.join(planning.positive_majors[:5])}。")

    # 审查风险
    if planning.review_risk_count > 0 or planning.review_warn_count > 0:
        lines.append(f"审查情况：风险 {planning.review_risk_count} 项，提醒 {planning.review_warn_count} 项。")
        if planning.risk_summaries:
            lines.append(f"主要问题：{'；'.join(planning.risk_summaries[:3])}。")
    elif planning.ordered_total > 0:
        lines.append("审查情况：暂无明显风险。")

    # 待处理建议
    if planning.pending_action_count > 0 and planning.pending_action_summaries:
        lines.append(f"待处理建议：{'；'.join(planning.pending_action_summaries[:2])}。")

    stale_notice = str(getattr(deps, "stale_pending_notice", "") or "").strip()
    if stale_notice:
        lines.append(
            f"注意：{stale_notice}如果用户本轮仍要调整方案，必须重新调用方案预览工具生成新的确认卡片；"
            "不要复述旧预览，也不要让用户用文字确认。"
        )

    header = "当前会话已存在统一规划状态，用户的方案概况如下：\n"
    footer = (
        "\n请基于以上方案现状回答用户。"
        "如果用户问方案情况，应直接走 plan_next_action(action_family=\"query_state\") -> execute_plan_action，"
        "不要先单独调用 collect_plan_context_inputs；plan_next_action 内部会读取必要上下文。"
        "\n3.0.1 用户侧不再使用“草稿”概念；即使底层字段叫 draft，也要表达为“方案/已加入方案”。"
        "\n当前 planning 状态的优先级高于历史对话。如果当前方案志愿数为0，即使历史里提到过候选，也不能当成当前方案。"
    )
    return header + "\n".join(lines) + footer
