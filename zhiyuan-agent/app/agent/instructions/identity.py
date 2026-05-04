"""角色设定 + 学生信息段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def build_identity(deps: RequestContext) -> str:
    """角色定义 + 学生基础信息注入。"""
    lines = [
        "你是一位拥有17年经验的专业高考志愿填报顾问孙成老师。"
        "你的任务是通过多轮对话收集学生信息，然后给出志愿填报建议。"
    ]

    score = deps.score_detail
    if score:
        lines.append(
            f"当前学生的高考信息如下：\n"
            f"- 性别：{score.sex}\n"
            f"- 省份：{score.province}\n"
            f"- 高考总分：{score.total_score}\n"
            f"- 选科：{'、'.join(score.subject_list)}"
        )

    init = deps.init_profile
    if init:
        init_lines: list[str] = []
        if init.strength_subjects:
            init_lines.append(f"- 优势学科：{'、'.join(init.strength_subjects)}")
        if init.major.level2:
            init_lines.append(f"- 意向专业：{'、'.join(init.major.level2)}")
        if init.major.negative_level2:
            init_lines.append(f"- 不接受的专业：{'、'.join(init.major.negative_level2)}")
        if init.city.province:
            init_lines.append(f"- 意向省份/地区：{'、'.join(init.city.province)}")
        if init_lines:
            lines.append(
                "学生在开始对话前已通过问卷预填了以下偏好信息（已作为报考参考信息记录，无需重复询问）：\n"
                + "\n".join(init_lines)
                + "\n你可以在对话中确认或补充这些信息，但不要从零开始重新收集。"
            )

    return "\n\n".join(lines)
