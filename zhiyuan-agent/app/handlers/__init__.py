"""Plan action handler 包。

将 plan_execution_tool.py (~2000行) 的 16 种 action 分派逻辑
拆分为独立 handler 模块，通过 HANDLER_REGISTRY 注册。

当前阶段：Plan 主路径 action 已迁入 handler registry。

设计原则：
- handler 接口统一：async def handle(ctx, plan) -> PlanExecutionResult
- dispatcher 精简为路由 + 后处理
- volunteer_ref 解析提取到 shared.py 复用
"""

from app.handlers.registry import HANDLER_REGISTRY, HandlerFunc

# 导入 handler 模块以触发 @register_handler 注册
import app.handlers.query_handlers  # noqa: F401
import app.handlers.analysis_handlers  # noqa: F401
import app.handlers.fix_proposal_handlers  # noqa: F401
import app.handlers.generate_handler  # noqa: F401
import app.handlers.mutation_handlers  # noqa: F401

__all__ = ["HANDLER_REGISTRY", "HandlerFunc"]
