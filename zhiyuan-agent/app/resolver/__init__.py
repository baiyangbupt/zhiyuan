"""ActionResolver 确定性动作映射包。

用 IntentFrame + PlanContextInputs → ActionResolution
的确定性规则替代历史 planner 里的关键词匹配动作归一化。
"""

from app.resolver.action_resolver import ActionResolution, ActionResolver

__all__ = ["ActionResolution", "ActionResolver"]
