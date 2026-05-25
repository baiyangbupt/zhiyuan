"""指令组装入口。

将各模块化段落组装为最终 system instructions 字符串，
供 ChatAgent 的 instructions= 参数消费。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from app.agent.instructions.identity import build_identity
from app.agent.instructions.pending_context import build_pending_context
from app.agent.instructions.planning_context import build_planning_context
from app.agent.instructions.style_rules import build_style_rules
from app.agent.instructions.tool_dispatch_rules import build_tool_dispatch_rules

if TYPE_CHECKING:
    from app.agent.context import RequestContext


def _is_first_turn(deps: "RequestContext") -> bool:
    history = deps.chat_history or []
    return len(history) <= 1


def _build_first_turn_guidance() -> str:
    return (
        "这是用户进入当前会话后的起手阶段。首轮回复请先用很短的自然语言帮用户建立使用心智："
        "你应结合当前会话状态、已有报考参考信息和 planning 状态，自行判断此时最适合强调的是方向探索、信息查询、方案查看、方案审查还是方案调整。"
        "顺带点明对话框适合直接提问、工作台适合查看方案和候选。"
        "如果用户这一轮已经问得很具体，就直接回答该问题，只在结尾自然补一句还能继续怎么问，不要固定成同一套例子。"
        "不要写成长篇欢迎词，不要自我包装，不要堆砌资历。"
    )


def build_instructions(ctx: RunContext["RequestContext"]) -> str:
    """组装完整 system instructions。

    段落顺序：
    1. 角色设定 + 学生信息
    2. 方案状态上下文
    3. 待确认操作上下文
    4. 首轮引导（如果是首轮）
    5. 工具调度规则
    6. 回复风格约束
    """
    parts: list[str] = []

    # 1. Identity
    parts.append(build_identity(ctx.deps))

    # 2. Planning context
    planning_ctx = build_planning_context(ctx.deps)
    if planning_ctx:
        parts.append(planning_ctx)

    # 3. Pending context
    pending_ctx = build_pending_context(ctx.deps)
    if pending_ctx:
        parts.append(pending_ctx)

    # 4. First turn guidance
    if _is_first_turn(ctx.deps):
        parts.append(_build_first_turn_guidance())

    # 5. Tool dispatch rules
    parts.append(build_tool_dispatch_rules())

    # 6. Style rules
    parts.append(build_style_rules())

    return "\n\n".join(parts)
