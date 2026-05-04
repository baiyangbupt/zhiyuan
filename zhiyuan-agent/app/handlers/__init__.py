"""Plan action handler 包。

将 plan_execution_tool.py (~2000行) 的 16 种 action 分派逻辑
拆分为独立 handler 模块，通过 HANDLER_REGISTRY 注册。

当前阶段：建立分发骨架和接口约定。
handler 迁移按以下顺序逐步进行：
1. query_handlers (只读，最简单)
2. analysis_handlers (只读 + 格式化)
3. compensation_handlers (有 apply 但逻辑独立)
4. generate_handler (单独逻辑)
5. mutation_handlers (最复杂，涉及 volunteer_ref 解析)

设计原则：
- handler 接口统一：async def handle(ctx, plan) -> PlanExecutionResult
- dispatcher 精简为路由 + 后处理
- volunteer_ref 解析提取到 shared.py 复用
"""

from app.handlers.registry import HANDLER_REGISTRY, HandlerFunc

# 导入 handler 模块以触发 @register_handler 注册
import app.handlers.query_handlers  # noqa: F401
import app.handlers.analysis_handlers  # noqa: F401
import app.handlers.compensation_handlers  # noqa: F401
import app.handlers.generate_handler  # noqa: F401
import app.handlers.mutation_handlers  # noqa: F401

__all__ = ["HANDLER_REGISTRY", "HandlerFunc"]
