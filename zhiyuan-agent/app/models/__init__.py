"""4.0 agent 数据模型。

这些模型描述对话阶段和统一待确认协议。

模块：
- conversation_phase: 对话阶段状态机 + 统一待确认协议
"""

from app.models.conversation_phase import (
    ConversationPhase,
    PendingConfirmation,
    PhaseState,
)

__all__ = [
    "ConversationPhase",
    "PendingConfirmation",
    "PhaseState",
]
