"""结构化用户意图模型。

替代现有 user_goal 字符串 + _goal_requests_* 关键词匹配，
由 LLM 直接输出结构化 IntentFrame，ActionResolver 消费。

设计原则：
- verb 枚举直接映射到 action_family，消除二次字符串匹配
- target 携带志愿引用、院校/专业/地域名，消除 user_goal 正则解析
- scope 携带筛选维度，消除 PlanAtomicAction.filters 的 untyped dict
- review_issue_code 直接携带，消除 match_review_issue_code_from_goal
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Verb 枚举说明
# ---------------------------------------------------------------------------
# 与现有 action_family 的映射关系：
#
# | verb        | → action_family           | 备注                |
# |-------------|---------------------------|---------------------|
# | query       | query_state/draft/ordered/candidates | 由 topic 细分   |
# | analyze     | analyze_adjustment        |                     |
# | review      | review_plan               |                     |
# | generate    | generate_plan             |                     |
# | add         | add_units                 |                     |
# | remove      | remove_units              |                     |
# | move        | move_unit                 |                     |
# | replace     | replace_units             |                     |
# | reorder     | sort_ordered_plan / regenerate_order | scope.sort_field 决定 |
# | compensate  | preview_compensation / apply_compensation |       |
# | compare     | —                         | Explore 比较        |
# | recommend   | —                         | Explore 推荐        |
# | explain     | —                         | Explore 解释        |
# | explore     | —                         | Explore 方向分析    |
# | set_preference   | → Intent 偏好工具    |                     |
# | set_constraint   | → Intent 约束工具    |                     |
# | remove_preference| → Intent 清除工具    |                     |

Verb = Literal[
    # === Plan 操作 ===
    "query",          # 查询当前方案/排序/候选；query_draft 仅为历史 action 名
    "analyze",        # 分析调整建议
    "review",         # 审查方案
    "generate",       # 生成方案
    "add",            # 添加志愿
    "remove",         # 删除志愿
    "move",           # 移动志愿位置
    "replace",        # 替换志愿
    "reorder",        # 重新排序
    "compensate",     # 补偿/补稳/补齐

    # === Explore 操作 ===
    "compare",        # 方向/院校/专业 对比
    "recommend",      # 推荐请求
    "explain",        # 解释性问答
    "explore",        # 职业方向探索

    # === Intent 操作 ===
    "set_preference",     # 设置偏好
    "set_constraint",     # 设置约束
    "remove_preference",  # 清除偏好

]

Topic = Literal[
    "career",     # 职业方向
    "school",     # 院校
    "major",      # 专业
    "region",     # 地域
    "plan",       # 方案整体（冲稳保结构、数量、风险等）
    "general",    # 通用/无特定话题
]

TaskLayer = Literal[
    "explore",    # 信息探索、方向分析
    "intent",     # 偏好/约束 管理
    "plan",       # 方案编辑操作
]


class TargetSpec(BaseModel):
    """操作目标：指定具体的志愿、院校、专业等。

    用于替代 PlanAtomicAction 中 volunteer_ids + 零散字段。
    """

    # 志愿引用：如 "@3", "北京工业大学-计算机"
    volunteer_refs: list[str] = Field(default_factory=list)

    # 专业组引用：如 "第3个专业组", "unit-xxx"
    unit_refs: list[str] = Field(default_factory=list)

    # 具体名称引用
    school_names: list[str] = Field(default_factory=list)
    major_names: list[str] = Field(default_factory=list)
    region_names: list[str] = Field(default_factory=list)

    # 职业方向 slot（对应 explore_direction_tool 的 career slot）
    career_types: list[str] = Field(default_factory=list)

    # 审查问题编码（14 种，如 "high_tuition", "cooperative_program" 等）
    review_issue_code: str | None = None

    # 源位置 / 目标位置（move_unit / move_ordered_unit 场景）
    source_position: int | None = None
    position: int | None = None

    @property
    def has_refs(self) -> bool:
        """是否包含任何具体引用。"""
        return bool(
            self.volunteer_refs
            or self.unit_refs
            or self.school_names
            or self.major_names
            or self.region_names
        )


class ScopeSpec(BaseModel):
    """操作范围：筛选条件，用于候选查询、批量添加/替换等。

    字段对齐 PlanAtomicAction.filters 中实际使用的维度。
    """

    # 档位：冲/稳/保
    tier: Literal["冲", "稳", "保", ""] = ""

    # 地域范围
    province: str = ""

    # 标签筛选（对齐 backend candidate-pool/query 协议）
    school_tags: list[str] = Field(default_factory=list)
    major_tags: list[str] = Field(default_factory=list)

    # 关键词筛选
    school_keyword: str = ""
    major_keyword: str = ""

    # 返回数量限制
    limit: int = 5

    # 替换类操作是否要求替换后方案数量不减少；用于触发容量预检。
    preserve_count: bool = False

    # 当前方案排序字段。为空表示整体重新生成顺序；非空表示按指定字段排序。
    sort_field: Literal["admissionRatio", "schoolRank", "finalScore", ""] = ""

    # 是否针对 review issue 批量操作
    is_review_issue_batch: bool = False

    @property
    def has_filters(self) -> bool:
        """是否包含任何筛选条件。"""
        return bool(
            self.tier
            or self.province
            or self.school_tags
            or self.major_tags
            or self.school_keyword
            or self.major_keyword
            or self.preserve_count
        )


class IntentFrame(BaseModel):
    """结构化用户意图。

    由 LLM 在 classify_user_intent 工具中输出，
    ActionResolver 直接消费该结构做确定性动作映射。

    与现有 PlanActionPlan 的关系：
    - IntentFrame 描述"用户想做什么"（输入侧）
    - PlanActionPlan 描述"系统应该怎么做"（输出侧）
    - ActionResolver 负责 IntentFrame → PlanActionPlan 的映射

    兼容说明：
    - 运行时动作选择不再从 raw_utterance / user_goal 做关键词改写。
    - raw_utterance 仅用于日志、解释和实体消歧；动作族、位置、排序字段、
      审查问题等必须由结构化字段承载。
    """

    task_layer: TaskLayer
    topic: Topic = "general"
    verb: Verb

    target: TargetSpec = Field(default_factory=TargetSpec)
    scope: ScopeSpec = Field(default_factory=ScopeSpec)

    # 保留原始用户表达，供日志和兜底
    raw_utterance: str = ""

    # 历史字段，仅用于兼容旧样本；自然语言 frame 不再承载确认执行。
    # 确认/取消必须通过 service-level pendingConfirmation 入口处理。
    is_confirmation_of_previous: bool = False
