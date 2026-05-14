"""模块化指令构建。

ChatAgent 直接消费 assembler.build_instructions；每个模块输出一段
instruction 文本，由 assembler 组装成最终指令。

模块分工：
- identity: 角色设定 + 学生信息
- planning_context: 方案状态注入
- pending_context: 待确认操作注入
- style_rules: 回复风格约束
- tool_dispatch_rules: 工具调度约束（Explore/Intent/Plan 分工）
- assembler: 组装入口
"""

from app.agent.instructions.assembler import build_instructions

__all__ = ["build_instructions"]
