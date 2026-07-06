"""4.0 agent 数据模型。

这些模型描述结构化意图、对话阶段和 direct 工具动作元数据。

模块：
- intent_frame: 结构化用户意图（替代 user_goal 字符串 + 关键词匹配）
- conversation_phase: 对话阶段状态机 + 统一待确认协议
- typed_actions: 类型化方案动作联合体
"""

from app.models.intent_frame import IntentFrame, TargetSpec, ScopeSpec
from app.models.conversation_phase import (
    ConversationPhase,
    PendingConfirmation,
    PhaseState,
)
from app.models.typed_actions import PlanAction

__all__ = [
    "IntentFrame",
    "TargetSpec",
    "ScopeSpec",
    "ConversationPhase",
    "PendingConfirmation",
    "PhaseState",
    "PlanAction",
]
