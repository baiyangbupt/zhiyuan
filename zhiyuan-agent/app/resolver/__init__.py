"""ActionResolver 确定性动作映射包。

用 IntentFrame + PlanContextInputs + ConversationPhase → ActionResolution
的确定性规则替代 plan_orchestration_tool 中的 8 个 _goal_requests_* 关键词匹配函数。
"""

from app.resolver.action_resolver import ActionResolution, ActionResolver

__all__ = ["ActionResolution", "ActionResolver"]
