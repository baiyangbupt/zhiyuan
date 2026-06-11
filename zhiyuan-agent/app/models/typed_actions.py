"""类型化原子动作联合体。

替代现有 PlanAtomicAction 的 untyped dict 方式，
每种 action_family 一个 class，有明确的必选字段和类型校验。

与现有 PlanAtomicAction 的关系：
- PlanAtomicAction 是执行层消费的 flat 结构（保留不动）
- typed actions 是意图层产出的强类型结构
- ActionResolver 输出 typed action，dispatcher 转换为 PlanAtomicAction

设计决策：
- 使用 discriminated union（Annotated[Union, Field(discriminator)]）
- 每个 action class 的 action_type 是 Literal 常量
- 共享字段通过 _ActionBase 统一
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 审查问题目标（复用现有 PlanReviewIssueTarget 的结构）
# ---------------------------------------------------------------------------

class ReviewIssueRef(BaseModel):
    """审查问题引用。

    对应现有 PlanReviewIssueTarget 的精简版。
    只保留 ActionResolver 需要的字段。
    """

    code: str
    scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] = "full_issue"
    label: str = ""
    narrowed_refs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 筛选条件（对齐 candidate-pool/query 协议）
# ---------------------------------------------------------------------------

class SelectionFilters(BaseModel):
    """候选筛选条件。

    对齐 backend candidate-pool/query 接口的参数：
    - provinceNames / cityNames
    - schoolTags / negativeSchoolTags
    - majorTags / negativeMajorTags
    - schoolKeywords / majorKeywords
    - tier (冲/稳/保)
    - limit
    """

    province: str = ""
    school_tags: list[str] = Field(default_factory=list)
    major_tags: list[str] = Field(default_factory=list)
    school_keyword: str = ""
    major_keyword: str = ""
    tier: Literal["冲", "稳", "保", ""] = ""
    limit: int = 5
    preserve_count: bool = False

    def to_atomic_filters(self) -> dict[str, Any]:
        """转换为 PlanAtomicAction.filters dict（兼容现有执行层）。"""
        result: dict[str, Any] = {}
        if self.province:
            result["province_keyword"] = self.province
        if self.school_tags:
            result["school_tags"] = self.school_tags
        if self.major_tags:
            result["major_tags"] = self.major_tags
        if self.school_keyword:
            result["school_keyword"] = self.school_keyword
        if self.major_keyword:
            result["major_keyword"] = self.major_keyword
        if self.tier:
            result["tier"] = self.tier
        if self.limit != 5:
            result["limit"] = self.limit
        if self.preserve_count:
            result["preserve_count"] = True
        return result

    @property
    def has_filters(self) -> bool:
        return bool(
            self.province
            or self.school_tags
            or self.major_tags
            or self.school_keyword
            or self.major_keyword
            or self.tier
        )


# ---------------------------------------------------------------------------
# 各类型化动作
# ---------------------------------------------------------------------------

class _ActionBase(BaseModel):
    """动作基类：所有动作共享的字段。"""
    reason: str = ""


# === 查询类 ===

class QueryStateAction(_ActionBase):
    """查询方案总览。"""
    action_type: Literal["query_state"] = "query_state"


class QueryDraftAction(_ActionBase):
    """Legacy action name for querying the current working plan."""
    action_type: Literal["query_draft"] = "query_draft"


class QueryOrderedAction(_ActionBase):
    """查询已排序方案（支持局部查询）。"""
    action_type: Literal["query_ordered"] = "query_ordered"
    volunteer_refs: list[str] = Field(default_factory=list)


class QueryCandidatesAction(_ActionBase):
    """查询候选志愿。"""
    action_type: Literal["query_candidates"] = "query_candidates"
    filters: SelectionFilters = Field(default_factory=SelectionFilters)


# === 生成/分析类 ===

class GeneratePlanAction(_ActionBase):
    """生成方案（首次生成或覆盖重建）。"""
    action_type: Literal["generate_plan"] = "generate_plan"
    force_regenerate: bool = False


class AnalyzeAdjustmentAction(_ActionBase):
    """分析调整建议。"""
    action_type: Literal["analyze_adjustment"] = "analyze_adjustment"


class ReviewPlanAction(_ActionBase):
    """审查方案。"""
    action_type: Literal["review_plan"] = "review_plan"


# === 补偿类 ===

class PreviewCompensationAction(_ActionBase):
    """预览补偿/补稳方案。"""
    action_type: Literal["preview_compensation"] = "preview_compensation"


class ApplyCompensationAction(_ActionBase):
    """应用补偿方案。"""
    action_type: Literal["apply_compensation"] = "apply_compensation"


# === 志愿增删改类 ===

class AddUnitsAction(_ActionBase):
    """添加志愿。

    至少需要 volunteer_ids 或 selection_filters 之一。
    """
    action_type: Literal["add_units"] = "add_units"
    volunteer_ids: list[str] = Field(default_factory=list)
    selection_filters: SelectionFilters = Field(default_factory=SelectionFilters)

    @property
    def has_target(self) -> bool:
        return bool(self.volunteer_ids) or self.selection_filters.has_filters


class RemoveUnitsAction(_ActionBase):
    """删除志愿。

    支持按 ID 删除或按 review issue 批量删除。
    """
    action_type: Literal["remove_units"] = "remove_units"
    volunteer_ids: list[str] = Field(default_factory=list)
    review_issue: ReviewIssueRef | None = None

    @property
    def has_target(self) -> bool:
        return bool(self.volunteer_ids) or self.review_issue is not None


class MoveUnitAction(_ActionBase):
    """移动志愿位置。"""
    action_type: Literal["move_unit"] = "move_unit"
    volunteer_id: str = ""
    source_position: int | None = None
    target_position: int | None = None


class MoveOrderedUnitAction(_ActionBase):
    """移动专业组位置。"""
    action_type: Literal["move_ordered_unit"] = "move_ordered_unit"
    unit_id: str = ""
    source_position: int | None = None
    target_position: int | None = None


class RemoveOrderedUnitAction(_ActionBase):
    """删除专业组。"""
    action_type: Literal["remove_ordered_unit"] = "remove_ordered_unit"
    unit_ids: list[str] = Field(default_factory=list)
    source_position: int | None = None


class ReplaceUnitsAction(_ActionBase):
    """替换志愿。

    移出 remove_ids 对应的志愿，按 replacement_filters 补入新候选。
    """
    action_type: Literal["replace_units"] = "replace_units"
    remove_ids: list[str] = Field(default_factory=list)
    # 源侧按专业整体替换时显式填写。为空时只处理 remove_ids 定位到的具体志愿。
    source_major_names: list[str] = Field(default_factory=list)
    replacement_filters: SelectionFilters = Field(default_factory=SelectionFilters)
    review_issue: ReviewIssueRef | None = None

    @property
    def has_target(self) -> bool:
        return bool(self.remove_ids) or self.review_issue is not None


class RegenerateOrderAction(_ActionBase):
    """重新排序。"""
    action_type: Literal["regenerate_order"] = "regenerate_order"
    # 结构性再平衡标记（保持总数，调整冲稳保配比）
    structural_rebalance: bool = False


class SortOrderedPlanAction(_ActionBase):
    """按指定字段排序当前方案。"""
    action_type: Literal["sort_ordered_plan"] = "sort_ordered_plan"
    sort_field: Literal["admissionRatio", "schoolRank", "finalScore"] = "admissionRatio"


# ---------------------------------------------------------------------------
# 联合体
# ---------------------------------------------------------------------------

PlanAction = Annotated[
    Union[
        QueryStateAction,
        QueryDraftAction,
        QueryOrderedAction,
        QueryCandidatesAction,
        GeneratePlanAction,
        AnalyzeAdjustmentAction,
        ReviewPlanAction,
        PreviewCompensationAction,
        ApplyCompensationAction,
        AddUnitsAction,
        RemoveUnitsAction,
        MoveUnitAction,
        MoveOrderedUnitAction,
        RemoveOrderedUnitAction,
        ReplaceUnitsAction,
        SortOrderedPlanAction,
        RegenerateOrderAction,
    ],
    Field(discriminator="action_type"),
]
"""16 种 action_family 的类型化联合体。

使用 discriminator 自动分发：
```python
action = PlanAction.model_validate({"action_type": "add_units", "volunteer_ids": ["v1"]})
assert isinstance(action, AddUnitsAction)
```
"""

# ---------------------------------------------------------------------------
# action_type → action_family 映射
# ---------------------------------------------------------------------------

ACTION_TYPE_TO_FAMILY: dict[str, str] = {
    "query_state": "query_state",
    "query_draft": "query_draft",
    "query_ordered": "query_ordered",
    "query_candidates": "query_candidates",
    "generate_plan": "generate_plan",
    "analyze_adjustment": "analyze_adjustment",
    "review_plan": "review_plan",
    "preview_compensation": "preview_compensation",
    "apply_compensation": "apply_compensation",
    "add_units": "add_units",
    "remove_units": "remove_units",
    "move_unit": "move_unit",
    "move_ordered_unit": "move_ordered_unit",
    "remove_ordered_unit": "remove_ordered_unit",
    "replace_units": "replace_units",
    "sort_ordered_plan": "sort_ordered_plan",
    "regenerate_order": "regenerate_order",
}
"""action_type 到现有 action_family 的一一映射。

当前两者完全相同，未来如果 action_type 细分（如 query_state vs query_summary），
映射表会体现差异。
"""
