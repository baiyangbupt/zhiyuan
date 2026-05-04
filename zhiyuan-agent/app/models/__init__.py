"""新抽象层数据模型。

Phase 1 引入的纯定义模块，不修改任何现有运行逻辑。
后续 Phase 2+ 的 ActionResolver、handler 拆分等会消费这些模型。

模块：
- intent_frame: 结构化用户意图（替代 user_goal 字符串 + 关键词匹配）
- conversation_phase: 对话阶段状态机 + 统一待确认协议
- typed_actions: 类型化原子动作联合体（替代 flat PlanAtomicAction）
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
