"""Handler 注册表。

每种 action_family 注册一个 handler 函数。
dispatcher 通过 HANDLER_REGISTRY[action_family] 获取对应 handler。

当前阶段：Plan 主路径 action 已迁入注册表；执行层只保留安全门禁、
preview 预览生成和历史兼容兜底。
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from pydantic_ai import RunContext

from app.agent.context import RequestContext
from app.tools.plan_orchestration_models import PlanActionPlan, PlanExecutionResult

HandlerFunc = Callable[
    [RunContext[RequestContext], PlanActionPlan],
    Coroutine[Any, Any, PlanExecutionResult],
]

# 注册表：action_family → handler 函数
# 未注册的 action_family 会 fallback 到执行层的 unsupported_action。
HANDLER_REGISTRY: dict[str, HandlerFunc] = {}


def register_handler(action_family: str):
    """装饰器：将函数注册为某 action_family 的 handler。"""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        HANDLER_REGISTRY[action_family] = func
        return func
    return decorator
