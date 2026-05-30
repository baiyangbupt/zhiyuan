"""确定性动作映射层。

用 IntentFrame + PlanContextInputs + ConversationPhase → ActionResolution
的确定性规则，替代 plan_orchestration_tool 中 8 个 _goal_requests_* 关键词匹配函数。

设计原则：
- 所有映射规则为数据表驱动，不依赖中文字符串匹配
- IntentFrame.verb 直接对应 action_family（少数由 topic 细分）
- 现有 _normalize_adjustment_action_family 的 5 条降级规则保留语义，改为结构化条件判断
- review_issue_code 由 IntentFrame.target 直接携带，不再从 user_goal 关键词匹配
- 缺参检测复用现有逻辑的语义，但基于 typed action 的字段做判断
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.conversation_phase import ConversationPhase, PhaseState
from app.models.intent_frame import IntentFrame
from app.models.typed_actions import (
    AddUnitsAction,
    AnalyzeAdjustmentAction,
    ApplyCompensationAction,
    GeneratePlanAction,
    MoveOrderedUnitAction,
    MoveUnitAction,
    PlanAction,
    PreviewCompensationAction,
    QueryCandidatesAction,
    QueryDraftAction,
    QueryOrderedAction,
    QueryStateAction,
    RegenerateOrderAction,
    RemoveUnitsAction,
    RemoveOrderedUnitAction,
    ReplaceUnitsAction,
    ReviewIssueRef,
    ReviewPlanAction,
    SelectionFilters,
    SortOrderedPlanAction,
)
from app.tools.plan_orchestration_models import PlanContextInputs
from app.tools.review_issue_registry import (
    get_review_issue_rule,
    review_issue_default_action_family,
    review_issue_scope_kind,
)


# ---------------------------------------------------------------------------
# ActionResolution — resolver 的输出
# ---------------------------------------------------------------------------

class ActionResolution(BaseModel):
    """ActionResolver 的完整输出。

    对应现有 PlanActionPlan 的输入侧语义：
    - action_family: 确定的动作族
    - stage: 应进入的阶段
    - requires_confirmation: 是否需要用户确认
    - action: 类型化的 PlanAction 实例
    - blocked_reason: 如果 stage=blocked 的原因
    - missing_inputs: 缺少的必要参数
    - reply_guidance: 回复生成的辅助信息
    """

    action_family: str
    stage: Literal["analyze", "preview", "apply", "review", "blocked"] = "preview"
    requires_confirmation: bool = True
    action: Any = None  # PlanAction instance; Any to avoid union serialization issues
    blocked_reason: str = ""
    missing_inputs: list[str] = Field(default_factory=list)
    reply_guidance: dict[str, Any] = Field(default_factory=dict)

    # 附加元数据
    review_issue_override: bool = False
    normalization_applied: str = ""
    should_rerun_review: bool = False
    should_refresh_workspace: bool = False


def _infer_sort_field(text: str) -> Literal["admissionRatio", "schoolRank", "finalScore"]:
    compact = str(text or "")
    if "院校层次" in compact or "学校层次" in compact or "院校排名" in compact:
        return "schoolRank"
    if "推荐系数" in compact or "推荐分" in compact:
        return "finalScore"
    return "admissionRatio"


# ---------------------------------------------------------------------------
# 不需要现有方案就能执行的动作
# ---------------------------------------------------------------------------

_PLAN_INDEPENDENT_ACTIONS = {
    "query_state",
    "query_draft",
    "query_ordered",
    "query_candidates",
    "generate_plan",
}

_PLAN_DEPENDENT_ACTIONS = {
    "analyze_adjustment",
    "preview_compensation",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
    "apply_compensation",
    "review_plan",
}

# 不需要用户确认即可执行的只读动作
_NO_CONFIRMATION_ACTIONS = {
    "query_state",
    "query_draft",
    "query_ordered",
    "query_candidates",
    "analyze_adjustment",
    "preview_compensation",
    "review_plan",
}

# 永远需要确认的高副作用动作
_ALWAYS_CONFIRM_ACTIONS = {
    "generate_plan",
    "sort_ordered_plan",
    "regenerate_order",
    "apply_compensation",
    "replace_units",
    "move_ordered_unit",
    "remove_ordered_unit",
}


# ---------------------------------------------------------------------------
# ActionResolver
# ---------------------------------------------------------------------------

class ActionResolver:
    """确定性动作映射器。

    核心流程：
    1. verb_to_action_family: IntentFrame.verb → 初始 action_family
    2. apply_review_issue_override: review issue 的 scope_kind 覆盖规则
    3. apply_normalization: 5 条降级规则（对应旧 _normalize_adjustment_action_family）
    4. build_typed_action: 构造类型化 PlanAction
    5. check_missing_inputs: 缺参检测
    6. determine_stage: 决定 stage
    7. determine_confirmation: 确认标志
    """

    def resolve(
        self,
        frame: IntentFrame,
        context: PlanContextInputs,
        phase: ConversationPhase | None = None,
    ) -> ActionResolution:
        """将 IntentFrame 映射为 ActionResolution。"""
        # Step 1: verb → initial action_family
        action_family = self._verb_to_action_family(frame)

        # 非 plan 层直接返回 blocked（由其他工具处理）
        if frame.task_layer != "plan":
            return ActionResolution(
                action_family=action_family,
                stage="blocked",
                requires_confirmation=False,
                blocked_reason=f"task_layer={frame.task_layer}, 应由对应的 {frame.task_layer} 工具处理",
            )

        if action_family in {"pin_unit", "unpin_unit"}:
            return ActionResolution(
                action_family=action_family,
                stage="blocked",
                requires_confirmation=False,
                blocked_reason=(
                    "3.0.1 新版工作台不提供固定/锁定志愿入口；"
                    "建议改用移动到指定位置或方案排序。"
                ),
                reply_guidance={
                    "user_message": (
                        "当前新版工作台暂不提供固定/锁定志愿入口，"
                        "可以改为移动到指定位置，或使用方案排序后再人工微调。"
                    )
                },
            )

        # Step 2: review issue override
        review_issue_override = False
        if frame.target.review_issue_code:
            new_family = self._apply_review_issue_override(
                action_family, frame.target.review_issue_code, frame
            )
            if new_family != action_family:
                review_issue_override = True
                action_family = new_family

        # Step 3: normalization（5 条降级规则）
        normalization_applied = ""
        original_family = action_family
        action_family = self._apply_normalization(action_family, frame, context)
        if action_family != original_family:
            normalization_applied = f"{original_family} → {action_family}"

        # Step 4: build typed action
        action = self._build_typed_action(action_family, frame)

        # Step 5: missing inputs
        missing_inputs = self._check_missing_inputs(action_family, frame, context)

        # Step 6: determine stage
        user_confirmed = (
            frame.verb == "confirm" and frame.is_confirmation_of_previous
        )
        stage = self._determine_stage(
            action_family,
            user_confirmed=user_confirmed,
            missing_inputs=missing_inputs,
        )

        # Step 7: confirmation flag
        requires_confirmation = self._determine_confirmation(action_family, stage)

        # Step 8: workspace flags
        should_rerun_review = stage == "apply" and action_family in {
            "generate_plan",
            "add_units",
            "remove_units",
            "move_unit",
            "move_ordered_unit",
            "replace_units",
            "remove_ordered_unit",
            "sort_ordered_plan",
            "regenerate_order",
            "apply_compensation",
        }
        should_refresh_workspace = stage in {"apply", "review"}

        return ActionResolution(
            action_family=action_family,
            stage=stage,
            requires_confirmation=requires_confirmation,
            action=action,
            missing_inputs=missing_inputs,
            review_issue_override=review_issue_override,
            normalization_applied=normalization_applied,
            should_rerun_review=should_rerun_review,
            should_refresh_workspace=should_refresh_workspace,
        )

    # ------------------------------------------------------------------
    # Step 1: verb → action_family
    # ------------------------------------------------------------------

    _VERB_TO_FAMILY: dict[str, str] = {
        "analyze": "analyze_adjustment",
        "review": "review_plan",
        "generate": "generate_plan",
        "add": "add_units",
        "remove": "remove_units",
        "move": "move_unit",
        "pin": "pin_unit",
        "unpin": "unpin_unit",
        "replace": "replace_units",
        "reorder": "regenerate_order",
        "compensate": "preview_compensation",
        "confirm": "apply_compensation",
        "reject": "query_state",
    }

    def _verb_to_action_family(self, frame: IntentFrame) -> str:
        """IntentFrame.verb → action_family。

        query verb 需要由 topic 细分。
        confirm verb 特殊：消费 pending 时对应 pending 的 action_family。
        """
        if frame.verb == "query":
            return self._resolve_query_family(frame)

        if frame.verb == "confirm" and frame.is_confirmation_of_previous:
            return "apply_compensation"

        return self._VERB_TO_FAMILY.get(frame.verb, "query_state")

    def _resolve_query_family(self, frame: IntentFrame) -> str:
        """query verb 根据 topic 和 target 细分。"""
        if frame.target.has_refs:
            return "query_ordered"
        if frame.scope.has_filters:
            return "query_candidates"

        topic_map = {
            "plan": "query_state",
            "general": "query_state",
            "career": "query_state",
            "school": "query_ordered",
            "major": "query_ordered",
            "region": "query_candidates",
        }
        return topic_map.get(frame.topic, "query_state")

    # ------------------------------------------------------------------
    # Step 2: review issue override
    # ------------------------------------------------------------------

    def _apply_review_issue_override(
        self, action_family: str, review_issue_code: str, frame: IntentFrame
    ) -> str:
        """根据 review issue 的 scope_kind 覆盖 action_family。

        对应旧逻辑中 matched_review_issue 的 scope_kind 分支：
        - item_removal: 默认 remove_units，有替换意图时保留 replace_units
        - structural: 强制覆盖为 default_action_family（覆盖掉直接增删移动）
        - informational: 如果是 remove/replace 则覆盖为 review_plan
        """
        scope_kind = review_issue_scope_kind(review_issue_code)
        default_action = review_issue_default_action_family(review_issue_code)

        if scope_kind == "item_removal":
            # 旧逻辑：replacement_requested = _goal_requests_replacement(user_goal) or _has_selection_scope(filters)
            # 新逻辑：必须有实际筛选条件才算有替换意图，verb=replace 但无条件视为误分类
            has_replacement_intent = frame.scope.has_filters
            if action_family == "replace_units" and not has_replacement_intent:
                return "remove_units"
            if action_family not in {"remove_units", "replace_units"} and default_action:
                return default_action
        elif scope_kind == "structural":
            mutation_actions = {
                "add_units", "remove_units", "move_unit",
                "replace_units",
                "sort_ordered_plan",
            }
            if action_family in mutation_actions and default_action:
                return default_action
        elif scope_kind == "informational":
            if action_family in {"remove_units", "replace_units"}:
                return "review_plan"

        return action_family

    # ------------------------------------------------------------------
    # Step 3: normalization（5 条降级规则）
    # ------------------------------------------------------------------

    def _apply_normalization(
        self, action_family: str, frame: IntentFrame, context: PlanContextInputs
    ) -> str:
        """对应旧 _normalize_adjustment_action_family 的 5 条规则。

        规则 1: generate_plan → analyze_adjustment
            条件: 已有方案 + 不是显式要求重新生成 + verb 实际是 analyze
        规则 2: preview_compensation → add_units
            条件: 方案未满额 + 有稳定性补入意图（scope.tier in {稳, 保}）
        规则 3: regenerate_order → replace_units
            条件: 有结构再平衡意图（scope.tier + 无明确 reorder verb）
        规则 4: preview_compensation → analyze_adjustment
            条件: 方案已满额
        规则 5: regenerate_order → analyze_adjustment
            条件: 没有明确 reorder verb + 有 analyze 意图
        """
        has_plan = self._has_existing_plan(context)

        # Rule 1: generate → analyze (已有方案，不是要强制重建)
        if (
            action_family == "generate_plan"
            and has_plan
            and frame.verb != "generate"
            and frame.verb == "analyze"
        ):
            return "analyze_adjustment"

        # Rule 2: compensation → add_units (未满额 + 稳保方向)
        if (
            action_family == "preview_compensation"
            and not self._is_plan_filled(context)
            and frame.scope.tier in {"稳", "保"}
        ):
            return "add_units"

        # Rule 3: regenerate_order → replace_units (结构再平衡)
        if (
            action_family == "regenerate_order"
            and frame.scope.tier
            and frame.verb != "reorder"
        ):
            return "replace_units"

        # Rule 4: compensation → analyze (方案已满)
        if action_family == "preview_compensation" and self._is_plan_filled(context):
            return "analyze_adjustment"

        # Rule 5: regenerate_order → analyze (非明确 reorder + 是 analyze)
        if (
            action_family == "regenerate_order"
            and frame.verb != "reorder"
            and frame.verb == "analyze"
        ):
            return "analyze_adjustment"

        return action_family

    # ------------------------------------------------------------------
    # Step 4: build typed action
    # ------------------------------------------------------------------

    def _build_typed_action(self, action_family: str, frame: IntentFrame) -> Any:
        """根据 action_family 和 frame 构造对应的 typed action。"""
        filters = self._scope_to_filters(frame.scope)
        review_issue = self._target_to_review_issue(frame.target)

        builders: dict[str, Any] = {
            "query_state": lambda: QueryStateAction(reason=frame.raw_utterance),
            "query_draft": lambda: QueryDraftAction(reason=frame.raw_utterance),
            "query_ordered": lambda: QueryOrderedAction(
                volunteer_refs=frame.target.volunteer_refs,
                reason=frame.raw_utterance,
            ),
            "query_candidates": lambda: QueryCandidatesAction(
                filters=filters,
                reason=frame.raw_utterance,
            ),
            "generate_plan": lambda: GeneratePlanAction(
                force_regenerate=(frame.verb == "generate"),
                reason=frame.raw_utterance,
            ),
            "analyze_adjustment": lambda: AnalyzeAdjustmentAction(
                reason=frame.raw_utterance,
            ),
            "review_plan": lambda: ReviewPlanAction(reason=frame.raw_utterance),
            "preview_compensation": lambda: PreviewCompensationAction(
                reason=frame.raw_utterance,
            ),
            "apply_compensation": lambda: ApplyCompensationAction(
                reason=frame.raw_utterance,
            ),
            "add_units": lambda: AddUnitsAction(
                volunteer_ids=frame.target.volunteer_refs,
                selection_filters=filters,
                reason=frame.raw_utterance,
            ),
            "remove_units": lambda: RemoveUnitsAction(
                volunteer_ids=frame.target.volunteer_refs,
                review_issue=review_issue,
                reason=frame.raw_utterance,
            ),
            "move_unit": lambda: MoveUnitAction(
                volunteer_id=(
                    frame.target.volunteer_refs[0]
                    if frame.target.volunteer_refs
                    else ""
                ),
                target_position=frame.target.position,
                reason=frame.raw_utterance,
            ),
            "move_ordered_unit": lambda: MoveOrderedUnitAction(
                unit_id=(
                    frame.target.unit_refs[0]
                    if frame.target.unit_refs
                    else ""
                ),
                target_position=frame.target.position,
                reason=frame.raw_utterance,
            ),
            "remove_ordered_unit": lambda: RemoveOrderedUnitAction(
                unit_ids=frame.target.unit_refs,
                reason=frame.raw_utterance,
            ),
            "replace_units": lambda: ReplaceUnitsAction(
                remove_ids=frame.target.volunteer_refs,
                replacement_filters=filters,
                review_issue=review_issue,
                reason=frame.raw_utterance,
            ),
            "sort_ordered_plan": lambda: SortOrderedPlanAction(
                sort_field=_infer_sort_field(frame.raw_utterance),
                reason=frame.raw_utterance,
            ),
            "regenerate_order": lambda: RegenerateOrderAction(
                structural_rebalance=bool(frame.scope.tier),
                reason=frame.raw_utterance,
            ),
        }

        builder = builders.get(action_family)
        if builder:
            return builder()
        return QueryStateAction(reason=frame.raw_utterance)

    # ------------------------------------------------------------------
    # Step 5: missing inputs
    # ------------------------------------------------------------------

    def _check_missing_inputs(
        self, action_family: str, frame: IntentFrame, context: PlanContextInputs
    ) -> list[str]:
        """检测缺少的必要输入。"""
        missing: list[str] = []

        if action_family == "remove_units":
            if not frame.target.volunteer_refs and not frame.target.review_issue_code:
                missing.append("volunteer_ids")

        if action_family == "move_unit":
            if not frame.target.volunteer_refs:
                missing.append("volunteer_id")
            if frame.target.position is None:
                missing.append("target_position")

        if action_family == "move_ordered_unit":
            if not frame.target.unit_refs:
                missing.append("unit_ids")
            if frame.target.position is None:
                missing.append("target_position")

        if action_family == "remove_ordered_unit":
            if not frame.target.unit_refs:
                missing.append("unit_ids")

        if action_family == "add_units":
            if not frame.target.volunteer_refs and not frame.scope.has_filters:
                missing.append("selection_scope")

        if action_family == "replace_units":
            if not frame.target.volunteer_refs and not frame.target.review_issue_code:
                missing.append("volunteer_ids")
            if not frame.scope.has_filters:
                missing.append("replacement_scope")

        # 依赖现有方案的动作在方案为空时阻塞
        if action_family in _PLAN_DEPENDENT_ACTIONS and not self._has_existing_plan(context):
            missing.append("existing_plan")

        return missing

    # ------------------------------------------------------------------
    # Step 6: determine stage
    # ------------------------------------------------------------------

    def _determine_stage(
        self,
        action_family: str,
        *,
        user_confirmed: bool,
        missing_inputs: list[str],
    ) -> Literal["analyze", "preview", "apply", "review", "blocked"]:
        """决定应进入的执行阶段。

        对应旧 _determine_stage 的完整逻辑，但移除了 current_stage passthrough
        （IntentFrame 不需要外部覆盖 stage）。
        """
        # 只读动作直接 apply
        if action_family in {
            "query_state", "query_draft", "query_ordered", "query_candidates",
            "analyze_adjustment", "preview_compensation",
        }:
            return "apply"

        # 缺参 → analyze
        if missing_inputs:
            return "analyze"

        # review
        if action_family == "review_plan":
            return "review"

        # 用户已确认 → apply
        if user_confirmed:
            return "apply"

        # 默认 → preview
        return "preview"

    # ------------------------------------------------------------------
    # Step 7: confirmation flag
    # ------------------------------------------------------------------

    def _determine_confirmation(self, action_family: str, stage: str) -> bool:
        """确定是否需要用户确认。"""
        if stage == "analyze":
            return False
        if action_family in _NO_CONFIRMATION_ACTIONS:
            return False
        if action_family in _ALWAYS_CONFIRM_ACTIONS:
            return True
        # 其他变更类动作默认需要确认
        return action_family not in _NO_CONFIRMATION_ACTIONS

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _has_existing_plan(context: PlanContextInputs) -> bool:
        return (context.draft_count > 0) or (context.ordered_count > 0)

    @staticmethod
    def _is_plan_filled(context: PlanContextInputs) -> bool:
        if context.ordered_count <= 0 or context.target_count <= 0:
            return False
        return context.ordered_count >= context.target_count

    @staticmethod
    def _scope_to_filters(scope: Any) -> SelectionFilters:
        """从 IntentFrame.scope 构造 SelectionFilters。"""
        return SelectionFilters(
            province=scope.province,
            school_tags=list(scope.school_tags),
            major_tags=list(scope.major_tags),
            school_keyword=scope.school_keyword,
            major_keyword=scope.major_keyword,
            tier=scope.tier,
            limit=scope.limit,
        )

    @staticmethod
    def _target_to_review_issue(target: Any) -> ReviewIssueRef | None:
        """从 IntentFrame.target 构造 ReviewIssueRef。"""
        if not target.review_issue_code:
            return None
        scope_mode: Literal["full_issue", "narrowed_issue", "explicit_items"] = "full_issue"
        if target.volunteer_refs:
            scope_mode = "explicit_items"
        elif target.position is not None:
            scope_mode = "narrowed_issue"
        return ReviewIssueRef(
            code=target.review_issue_code,
            scope_mode=scope_mode,
        )
