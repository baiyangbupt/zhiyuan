"""Semantic plan-action classification.

This module classifies a user turn into a structured Plan action family.  It is
not a text shortcut and does not execute tools.  Runtime callers may consume the
result only when confidence is high; otherwise the full agent remains the
source of truth.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from app.agent.context import PlanningSummary, RequestContext
from app.config import LLMConfig
from app.llm.client import LLMClient
from app.tools.extraction_json import parse_extraction_json

logger = logging.getLogger(__name__)

PlanSemanticAction = Literal[
    "none",
    "query_state",
    "review_plan",
    "analyze_adjustment",
    "preview_fix_proposal",
]
PlanRecoveryAction = Literal[
    "none",
    "generate_plan",
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "replace_units",
    "remove_ordered_unit",
    "sort_ordered_plan",
    "regenerate_order",
]
PlanRecoverySortField = Literal["admissionRatio", "schoolRank", "finalScore"]
CompositeGoalAction = Literal["none", "only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"]
CompositeGoalScopeType = Literal["major", "school", "region", "career", "program_type", "tuition"]
PendingSemanticAction = Literal[
    "none",
    "confirm_pending",
    "reject_pending",
    "ask_pending_impact",
]


class PlanSemanticActionDecision(BaseModel):
    actionFamily: PlanSemanticAction = "none"
    confidence: float = 0.0
    reason: str = ""
    replyFocus: list[str] = Field(default_factory=list)
    targetStrategies: list[str] = Field(default_factory=list)
    targetIssueCodes: list[str] = Field(default_factory=list)

    @field_validator("replyFocus", "targetStrategies", "targetIssueCodes", mode="before")
    @classmethod
    def _coerce_list_fields(cls, value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)


class FixProposalSelectionDecision(BaseModel):
    proposalId: str = ""
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)


class PlanRecoveryActionDecision(BaseModel):
    actionFamily: PlanRecoveryAction = "none"
    confidence: float = 0.0
    reason: str = ""
    reviewIssueCode: str | None = None
    volunteerIds: list[str] = Field(default_factory=list)
    unitIds: list[str] = Field(default_factory=list)
    sourceMajorNames: list[str] = Field(default_factory=list)
    sourcePosition: int | None = None
    positionScope: Literal["single", "after"] = "single"
    targetPosition: int | None = None
    sortField: PlanRecoverySortField | None = None
    tier: str | None = None
    provinceKeyword: str | None = None
    schoolKeyword: str | None = None
    majorKeyword: str | None = None
    schoolTags: list[str] = Field(default_factory=list)
    majorTags: list[str] = Field(default_factory=list)
    preserveCount: bool = False
    limit: int = 5

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)

    @field_validator("sourcePosition", "targetPosition", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @field_validator("positionScope", mode="before")
    @classmethod
    def _coerce_position_scope(cls, value: object) -> str:
        text = str(value or "").strip()
        return text if text in {"single", "after"} else "single"

    @field_validator("limit", mode="before")
    @classmethod
    def _coerce_limit(cls, value: object) -> int:
        if value in (None, ""):
            return 5
        try:
            limit = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 5
        return limit if limit > 0 else 5


class CompositeGoalDecision(BaseModel):
    action: CompositeGoalAction = "none"
    confidence: float = 0.0
    reason: str = ""
    scopeType: CompositeGoalScopeType | None = None
    targetValues: list[str] = Field(default_factory=list)
    negativeValues: list[str] = Field(default_factory=list)
    maxTuitionPerYear: int | None = None
    constraintIntentType: Literal["default", "only_keep", "must_have"] = "default"

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)

    @field_validator("scopeType", mode="before")
    @classmethod
    def _coerce_optional_scope_type(cls, value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("maxTuitionPerYear", mode="before")
    @classmethod
    def _coerce_optional_tuition(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


class PendingSemanticActionDecision(BaseModel):
    action: PendingSemanticAction = "none"
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)


_plan_action_llm_client: LLMClient | None = None
_plan_action_agent: Agent[None, str] | None = None
_fix_proposal_selection_agent: Agent[None, str] | None = None
_plan_recovery_action_agent: Agent[None, str] | None = None
_composite_goal_agent: Agent[None, str] | None = None
_pending_action_agent: Agent[None, str] | None = None


def _get_plan_action_llm_client() -> LLMClient:
    global _plan_action_llm_client
    if _plan_action_llm_client is None:
        _plan_action_llm_client = LLMClient(LLMConfig())
    return _plan_action_llm_client


def _get_plan_action_agent() -> Agent[None, str]:
    global _plan_action_agent
    if _plan_action_agent is None:
        _plan_action_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿方案对话的结构化动作判定器，只输出 JSON。"
                "任务是判断当前用户在方案层到底需要哪类动作，不负责回复用户，也不执行方案。"
                "不要依据固定关键词或模板做判断，要基于用户语义、上下文和副作用边界判断。"
                "actionFamily 只能是 none、query_state、review_plan、analyze_adjustment、preview_fix_proposal。"
                "query_state 表示用户只想查看当前方案概况、数量、分布或状态。"
                "review_plan 表示用户想重新审查风险、查看审查结论或校验审查是否准确。"
                "analyze_adjustment 表示用户想理解问题、比较处理方向、知道为什么不能处理或怎么取舍，"
                "但还没有要求系统生成一版可确认的调整内容。"
                "首轮泛化方案解读不要抢到 analyze_adjustment：例如用户问当前方案对某专业/地域/职业方向承接怎么样、"
                "省外/公办/高收费是不是太多、这版偏专业还是学校、值不值得、说人话讲讲、整体是否划算，"
                "如果只是想了解当前方案事实、覆盖、比例、偏向或价值判断，且最近上下文里没有审查结果或处理建议，"
                "应 actionFamily=none，让完整 Agent 读取方案和候选事实回答；"
                "不要把这类问题改写成录取率断层、冲稳保比例或其它审查修复问题。"
                "如果首轮问题只是咨询风险价值、解释边界或查看事实，例如中外合作贵不贵/值不值得、"
                "高收费会不会影响保底、医学护理里中医算不算、候选里有没有某类更稳机会，"
                "应 actionFamily=none，让完整 Agent 按方案、候选和专业事实回答；"
                "不要因为文本提到了高收费、中外合作、医学、保底、某专业，就改写成审查修复分析。"
                "用户问当前方案能不能补稳/补保/补齐、候选是否足够、候选不够时怎么办、为什么不能补齐，"
                "如果只是要判断可行性、解释边界或给调整思路，而不是要求立刻生成可确认调整清单，可判为 analyze_adjustment，"
                "但 replyFocus 必须包含 shortage_boundary；"
                "不要判成 query_state；query_state 只适合单纯查看现状统计。"
                "没有最近审查结果或处理建议时，analyze_adjustment 的快捷入口只适合 shortage_boundary 或 unavailable_guidance；"
                "不要仅因为你能推断出 targetStrategies/targetIssueCodes 就判为 analyze_adjustment。"
                "preview_fix_proposal 只表示用户正在承接最近一次审查/处理建议，"
                "希望把这些已识别的问题整理成一版可确认的调整预览；"
                "通常需要能从上下文看到最近审查结果或处理建议；"
                "如果 planningSummary 显示已有当前方案，且用户同一轮明确要求检查某类方案提醒并先看可确认的调整预览，"
                "也可以判为 preview_fix_proposal，由服务层先重新审查再生成预览。"
                "当用户已经明确说“先给我看预览/先看调整预览/给我一版预览/列出可确认的调整”，"
                "并且目标属于审查处理建议（例如补兜底专业、按录取率重排、替换高收费/中外合作、补断层），"
                "应优先判为 preview_fix_proposal；不要只判为 review_plan 或 analyze_adjustment。"
                "只有用户只是问“有没有问题/能怎么处理/为什么/说人话/怎么取舍”，没有要求预览时，才判为 review_plan 或 analyze_adjustment。"
                "用户直接提出新的方案动作时不要判为 preview_fix_proposal，例如按推荐系数/院校层次/录取率排序、"
                "移动、删除、加入、替换、只保留某专业、排除某地域、更新偏好或要求；这些应交给完整 Agent 生成具体动作计划。"
                "用户只是问是否太冲、先看看影响、说人话、解释为什么、列命中项、怎么取舍、还没有要求生成可确认调整内容时，"
                "通常是 analyze_adjustment 或 none，不要生成预览。"
                "如果用户提出的是基础报考资料变化后的重新规划，例如分数、位次、省份、选科、批次等变化后要重新按新条件规划，"
                "这不属于当前方案内部的风险修复或普通调序替换；actionFamily 填 analyze_adjustment，"
                "replyFocus 必须包含 profile_change_replan。此时不要填写 targetStrategies，也不要当作缺少当前方案参数处理。"
                "这类回复应说明需要先确认基础信息变化，再重新生成候选/方案或给调整预览；确认前不能悄悄改当前方案。"
                "如果用户语义同时包含解释问题和承接最近审查建议生成可确认处理预览，且上下文有对应处理建议，才可 preview_fix_proposal。"
                "高副作用的真正执行不在这里决定；这里最多决定是否生成预览。"
                "targetStrategies 可选填后端修复策略线索，例如 sort_by_probability、adjust_major_group_inner_safety、"
                "fill_probability_gap、rebalance_tier_ratio、replace_risk_items、remove_risk_items。"
                "targetIssueCodes 可选填当前用户聚焦的审查问题 code，例如 high_tuition、cooperative_program、"
                "probability_inversion、probability_gap、major_group_safety_intent_alignment、group_inner_safety_guard、"
                "admission_limit、special_enrollment、count_validation、edge_score、safety_guard。"
                "replyFocus 可选填回复展示重点，例如 unavailable_guidance 表示用户想知道为什么某些提醒不能直接处理以及自己可以怎么调；"
                "shortage_boundary 表示用户重点关注候选不足、补稳/补保是否可行；target_issue_only 表示只围绕用户点名的某类问题展开。"
                "只要用户的问题明确聚焦当前方案中的某一类审查提醒、风险来源或处理方向，就必须填写 targetStrategies，"
                "不要把它留空；同时尽量填写 targetIssueCodes。targetIssueCodes 用来约束后续分析只围绕用户点名的那类问题展开。"
                "当用户承接审查结果要求在专业组里补更安全/更稳的专业、补兜底专业、处理非意向托底或组内安全垫时，"
                "targetStrategies 优先填写 adjust_major_group_inner_safety，targetIssueCodes 填 major_group_safety_intent_alignment 或 group_inner_safety_guard；"
                "当用户要求处理录取率倒挂或按录取率重排时填写 sort_by_probability，targetIssueCodes 填 probability_inversion；"
                "当用户要求补录取概率断层时填写 fill_probability_gap，targetIssueCodes 填 probability_gap；"
                "当用户泛泛要求补稳/调冲稳保比例时填写 rebalance_tier_ratio。"
                "当用户围绕学费预算压力、收费偏高、合作办学、国际项目等当前方案里的费用/项目风险询问怎么处理、"
                "要不要替换、能否换成普通收费、先看影响或取舍时，targetStrategies 填 replace_risk_items，"
                "targetIssueCodes 填 high_tuition 和/或 cooperative_program；"
                "如果用户明确只想移出这类风险项而不是替换补位，可填 remove_risk_items。"
                "当用户围绕限报条件、体检限制、外语单科限制、特殊招生等不适合保留的条目询问怎么处理时，"
                "targetStrategies 优先填写 remove_risk_items，若语义是换成更合适条目则填写 replace_risk_items。"
                "只有很确定时 confidence >= 0.8；不确定时 actionFamily=none 或 confidence < 0.8。"
                "输出 JSON：actionFamily, confidence, reason, replyFocus, targetStrategies, targetIssueCodes。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _plan_action_agent


def _get_fix_proposal_selection_agent() -> Agent[None, str]:
    global _fix_proposal_selection_agent
    if _fix_proposal_selection_agent is None:
        _fix_proposal_selection_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿方案审查处理建议的候选仲裁器，只输出 JSON。"
                "任务是在已经由后端生成的 ready 处理建议中，选择最贴近用户当前诉求的一项。"
                "这不是用户意图路由，也不执行方案；只能从输入 candidates 里选择 proposalId，或在不确定时返回空字符串。"
                "不要依据固定关键词或模板，要综合 latestUserText、assistantReply、候选 title/summary/strategy/sourceCheckCodes 判断。"
                "优先匹配用户明确聚焦的问题、处理方向和副作用边界；不要因为候选排在前面就选择它。"
                "如果用户同时提到多个问题，但明确要求先看某一类预览，选择这一类；如果没有足够依据区分，proposalId 置空。"
                "只有很确定时 confidence >= 0.8；不确定时 confidence < 0.8 且 proposalId 置空。"
                "输出 JSON：proposalId, confidence, reason。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _fix_proposal_selection_agent


def _get_pending_action_agent() -> Agent[None, str]:
    global _pending_action_agent
    if _pending_action_agent is None:
        _pending_action_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿对话的待处理内容判定器，只输出 JSON。"
                "任务是判断当前用户回复与当前 active pending 内容的关系，不负责回复用户，也不执行动作。"
                "不要依据固定关键词、固定短语或模板做判断，要基于用户语义、当前待处理内容和上下文一致性判断。"
                "action 只能是 none、confirm_pending、reject_pending、ask_pending_impact。"
                "confirm_pending 表示用户清楚地接受当前等待采纳/确认的内容，并希望继续执行或正式采用；"
                "只有回复对象和 pendingState 的摘要/类型一致时才可以确认。"
                "reject_pending 表示用户明确否定当前等待处理的内容，或明确取消/放弃这条预览。"
                "ask_pending_impact 表示用户没有确认或拒绝，只是在追问这条内容的影响、范围、命中项、当前方案关系或后果。"
                "none 表示用户在开启新问题、做只读分析、表达不清、转到别的主题，或无法判断是否针对当前待处理内容。"
                "用户问“这版是不是太冲”“说人话”“先看看影响”“候选里还有吗”等新问题，不要判成 reject_pending；"
                "除非用户明确说不要当前预览、取消这次、先不执行当前这条。"
                "如果用户重复、加强或换一种说法表达 pendingState 里同一个待采纳目标，"
                "并且没有提出新的冲突范围，应判为 confirm_pending；这表示用户是在确认当前待采纳内容，"
                "不是让系统另起一个无关方案动作。"
                "用户说“这个方案还是不行”“还是不对”并继续提出新的保留、排除、必须有、只保留等目标时，"
                "若目标与 pendingState 不一致，这是新诉求或对原诉求的细化，不是取消当前 pending；应判为 none，让主 Agent 重新理解。"
                "若目标与 pendingState 一致，只是继续强调同一个保留/排除/必须有范围，应判为 confirm_pending。"
                "只有用户明确把当前待处理内容作为对象并说不要它、取消它、暂不采纳它、别按这条来，才可 reject_pending。"
                "如果用户的回复可能与当前待处理内容不一致、可能是在确认别的内容，必须 action=none 或低置信。"
                "只有很确定时 confidence >= 0.85；不确定时 confidence < 0.85。"
                "输出 JSON：action, confidence, reason。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _pending_action_agent


def _get_plan_recovery_action_agent() -> Agent[None, str]:
    global _plan_recovery_action_agent
    if _plan_recovery_action_agent is None:
        _plan_recovery_action_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿方案对话的结构化恢复判定器，只输出 JSON。"
                "这个判定只在完整 Agent 没有调用工具、也没有生成可执行预览时使用；"
                "任务是判断用户是否已经明确提出一个方案层动作，并提取 plan_next_action 需要的结构化字段。"
                "不要依据固定关键词或模板做判断，要基于语义、上下文、动作副作用和用户是否给足对象/范围来判断。"
                "actionFamily 只能是 none、generate_plan、add_units、remove_units、move_unit、move_ordered_unit、"
                "replace_units、remove_ordered_unit、sort_ordered_plan、regenerate_order。"
                "只有用户明确要生成、补入、删除、移动、替换、排序或重排当前方案时，才输出非 none；"
                "只是在问原因、问影响、闲聊、专业/学校咨询、政策咨询、对比分析、偏好记录或报考条件变更时输出 none。"
                "如果用户只是表达想去/不想去、想学/不想学、只保留/必须有某方向，但没有明确要求立刻调整当前方案，"
                "这属于意向/条件预览，不在本恢复器里处理，输出 none。"
                "如果用户明确说要从当前方案中删掉某专业、某院校、某地域或某类风险，"
                "使用 remove_units，并把专业名放 sourceMajorNames，院校放 schoolKeyword，地域放 provinceKeyword。"
                "如果对象是当前方案审查已经识别出的风险或提醒类型，例如高收费、中外合作、限报条件、特殊招生，"
                "不要把它当成专业名；使用 remove_units 或 replace_units，并把对应审查 code 放 reviewIssueCode，"
                "例如高收费=high_tuition，中外合作=cooperative_program，限报条件=admission_limit，特殊类型招生=special_enrollment。"
                "如果用户明确说要加入或补齐某类候选，使用 add_units，并把筛选条件放 majorKeyword、schoolKeyword、provinceKeyword、tier 或 tags。"
                "如果用户明确说把某条学校+专业移动到第 N 位，使用 move_unit，volunteerIds 填用户原始引用，targetPosition 填 N。"
                "如果用户只用位置表达，如“第8个移到第12位/第8条放到第12”，没有学校专业名，"
                "使用 move_ordered_unit，sourcePosition 填 8，targetPosition 填 12。"
                "如果用户明确删除第 N 个/第 N 个专业组且没有学校专业名，使用 remove_ordered_unit，sourcePosition 填 N。"
                "如果用户明确删除第 N 位之后/后面的当前方案展示单元，使用 remove_ordered_unit，"
                "sourcePosition 填 N，positionScope 填 after；如果还限定冲/稳/保或数量，同时填写 tier 和 limit。"
                "如果用户明确要求按录取率/院校层次/推荐系数整体排序，使用 sort_ordered_plan，"
                "sortField 分别填 admissionRatio、schoolRank、finalScore；局部筛选查看不要判成排序。"
                "替换动作必须同时能看出要替换当前方案里的对象和新方向；否则输出 none 或低置信。"
                "preserveCount 只在用户明确要求数量不变、补齐、保持满额时为 true。"
                "limit 只在用户明确数量时填写，否则默认 5。"
                "高副作用真正执行不在这里决定；这里只恢复预览链路。"
                "只有很确定时 confidence >= 0.85；不确定时 actionFamily=none 或 confidence < 0.85。"
                "输出 JSON 字段：actionFamily, confidence, reason, reviewIssueCode, volunteerIds, unitIds, sourceMajorNames, "
                "sourcePosition, positionScope, targetPosition, sortField, tier, provinceKeyword, schoolKeyword, majorKeyword, "
                "schoolTags, majorTags, preserveCount, limit。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _plan_recovery_action_agent


def _get_composite_goal_agent() -> Agent[None, str]:
    global _composite_goal_agent
    if _composite_goal_agent is None:
        _composite_goal_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿对话的复合报考目标判定器，只输出 JSON。"
                "这个判定只在完整 Agent 已经尝试普通方案动作、但没有形成待确认内容时使用；"
                "任务是判断用户原话本质上是否在提出长期报考条件与当前方案调整的复合目标。"
                "不要依据固定关键词或模板做判断，要基于语义、宾语、当前方案副作用和用户是否要求改变后续推荐口径来判断。"
                "action 只能是 none、only_keep_scope、must_include_scope、exclude_scope、tuition_budget_scope。"
                "only_keep_scope 表示用户要求范围限定为某些专业/院校/地域/职业方向/项目类型，其他方向不要；"
                "must_include_scope 表示用户要求方案至少保留某些方向，但其他方向可以继续保留；"
                "exclude_scope 表示用户要求避开、排除或移出某些方向或项目类型。"
                "tuition_budget_scope 表示用户给出每年学费/费用预算上限，并要求当前方案中超出预算的志愿移出、替换或补位。"
                "scopeType 只能是 major、school、region、career、program_type、tuition；只在实体范围清楚时填写。"
                "program_type 表示招生项目或培养项目类型，例如中外合作办学、国际项目、校企合作、单列专业等；"
                "如果用户表达“不接受/排除/移出中外合作项目”，这是 program_type，不要当成专业名。"
                "只有用户明确承接最近审查结果说处理审查里的中外合作提醒时，才交给审查修复链路；本判定器应输出 none。"
                "targetValues 放 only_keep_scope / must_include_scope 的正向对象，negativeValues 放 exclude_scope 的排除对象。"
                "tuition_budget_scope 必须填写 maxTuitionPerYear 为整数元/年，scopeType 填 tuition，不要把数字放到 targetValues。"
                "用户只是询问影响、适不适合、要不要、能不能、政策、学校/专业介绍、对比分析、只读审查时，必须 action=none。"
                "用户明确说只保留/只要/仅限/限定某方向，即使还提到'其他不要'，也应输出 only_keep_scope，"
                "且只把用户明确点名的正向对象放 targetValues，不要把未点名的其他方向展开成 negativeValues。"
                "用户明确说必须有/至少有/保留一个某方向，且其他方向可以保留，输出 must_include_scope。"
                "用户明确说不要/不考虑/排除/删掉当前方案里的某方向，输出 exclude_scope。"
                "如果用户明确删除第几个志愿、移动第几个志愿、或点名某个具体学校+专业作为当前方案里的单条志愿，"
                "这是原子方案动作，不是复合报考目标，输出 none。"
                "如果对象无法归入专业、院校、地域、职业或项目类型，或无法提取清楚具体对象，输出 none 或低置信。"
                "只有很确定时 confidence >= 0.85；不确定时 action=none 或 confidence < 0.85。"
                "constraintIntentType 对 only_keep_scope 填 only_keep，对 must_include_scope 填 must_have，其他填 default。"
                "输出 JSON：action, confidence, reason, scopeType, targetValues, negativeValues, maxTuitionPerYear, constraintIntentType。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _composite_goal_agent


def _planning_summary_payload(summary: PlanningSummary | None) -> dict[str, object]:
    if summary is None:
        return {}
    return {
        "phase": summary.phase,
        "version": summary.version,
        "workingTotal": summary.working_total,
        "draftTotal": summary.working_total,
        "orderedTotal": summary.ordered_total,
        "orderedTargetTotal": summary.ordered_target_total,
        "reviewRiskCount": summary.review_risk_count,
        "reviewWarnCount": summary.review_warn_count,
        "riskSummaries": summary.risk_summaries,
        "tierCounts": summary.tier_counts,
    }


def _pending_state_payload(pending_state: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(pending_state, dict):
        return {}
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        execution_payload = {}
    return {
        "kind": pending_state.get("kind") or "",
        "status": pending_state.get("status") or "",
        "actionFamily": pending_state.get("actionFamily") or "",
        "summary": pending_state.get("summary") or "",
        "userGoal": pending_state.get("userGoal") or "",
        "proposalTitle": execution_payload.get("proposalTitle") or "",
        "proposalSummary": execution_payload.get("proposalSummary") or "",
        "intentMode": execution_payload.get("intentMode") or "",
        "constraintIntentType": execution_payload.get("constraintIntentType") or "",
    }


def _normalize_plan_semantic_action_decision(decision: PlanSemanticActionDecision) -> PlanSemanticActionDecision:
    action_family = str(decision.actionFamily or "none").strip()
    allowed = {"none", "query_state", "review_plan", "analyze_adjustment", "preview_fix_proposal"}
    if action_family not in allowed:
        action_family = "none"
    confidence = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    return PlanSemanticActionDecision(
        actionFamily=action_family,  # type: ignore[arg-type]
        confidence=confidence,
        reason=str(decision.reason or "").strip(),
        replyFocus=[
            str(item or "").strip()
            for item in decision.replyFocus
            if str(item or "").strip()
        ],
        targetStrategies=[
            str(item or "").strip()
            for item in decision.targetStrategies
            if str(item or "").strip()
        ],
        targetIssueCodes=[
            str(item or "").strip()
            for item in decision.targetIssueCodes
            if str(item or "").strip()
        ],
    )


def _normalize_fix_proposal_selection_decision(
    decision: FixProposalSelectionDecision,
) -> FixProposalSelectionDecision:
    return FixProposalSelectionDecision(
        proposalId=str(decision.proposalId or "").strip(),
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
    )


def _normalize_list_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_plan_recovery_action_decision(decision: PlanRecoveryActionDecision) -> PlanRecoveryActionDecision:
    action_family = str(decision.actionFamily or "none").strip()
    allowed = {
        "none",
        "generate_plan",
        "add_units",
        "remove_units",
        "move_unit",
        "move_ordered_unit",
        "replace_units",
        "remove_ordered_unit",
        "sort_ordered_plan",
        "regenerate_order",
    }
    if action_family not in allowed:
        action_family = "none"
    sort_field = str(decision.sortField or "").strip()
    if sort_field not in {"admissionRatio", "schoolRank", "finalScore"}:
        sort_field = ""
    limit = decision.limit if isinstance(decision.limit, int) else 5
    if limit <= 0:
        limit = 5
    return PlanRecoveryActionDecision(
        actionFamily=action_family,  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
        reviewIssueCode=str(decision.reviewIssueCode or "").strip() or None,
        volunteerIds=_normalize_list_values(decision.volunteerIds),
        unitIds=_normalize_list_values(decision.unitIds),
        sourceMajorNames=_normalize_list_values(decision.sourceMajorNames),
        sourcePosition=decision.sourcePosition,
        positionScope=decision.positionScope,
        targetPosition=decision.targetPosition,
        sortField=sort_field or None,  # type: ignore[arg-type]
        tier=str(decision.tier or "").strip() or None,
        provinceKeyword=str(decision.provinceKeyword or "").strip() or None,
        schoolKeyword=str(decision.schoolKeyword or "").strip() or None,
        majorKeyword=str(decision.majorKeyword or "").strip() or None,
        schoolTags=_normalize_list_values(decision.schoolTags),
        majorTags=_normalize_list_values(decision.majorTags),
        preserveCount=bool(decision.preserveCount),
        limit=limit,
    )


def _normalize_composite_goal_decision(decision: CompositeGoalDecision) -> CompositeGoalDecision:
    action = str(decision.action or "none").strip()
    if action not in {"none", "only_keep_scope", "must_include_scope", "exclude_scope", "tuition_budget_scope"}:
        action = "none"
    scope_type = str(decision.scopeType or "").strip()
    if scope_type not in {"major", "school", "region", "career", "program_type", "tuition"}:
        scope_type = ""
    constraint_intent_type = str(decision.constraintIntentType or "default").strip()
    if constraint_intent_type not in {"default", "only_keep", "must_have"}:
        constraint_intent_type = "default"
    if action == "only_keep_scope":
        constraint_intent_type = "only_keep"
    elif action == "must_include_scope":
        constraint_intent_type = "must_have"
    elif action == "exclude_scope":
        constraint_intent_type = "default"
    elif action == "tuition_budget_scope":
        constraint_intent_type = "default"
    return CompositeGoalDecision(
        action=action,  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
        scopeType=scope_type or None,  # type: ignore[arg-type]
        targetValues=_normalize_list_values(decision.targetValues),
        negativeValues=_normalize_list_values(decision.negativeValues),
        maxTuitionPerYear=decision.maxTuitionPerYear if isinstance(decision.maxTuitionPerYear, int) and decision.maxTuitionPerYear > 0 else None,
        constraintIntentType=constraint_intent_type,  # type: ignore[arg-type]
    )


def _normalize_pending_semantic_action_decision(
    decision: PendingSemanticActionDecision,
) -> PendingSemanticActionDecision:
    action = str(decision.action or "none").strip()
    allowed = {"none", "confirm_pending", "reject_pending", "ask_pending_impact"}
    if action not in allowed:
        action = "none"
    confidence = max(0.0, min(1.0, float(decision.confidence or 0.0)))
    return PendingSemanticActionDecision(
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        reason=str(decision.reason or "").strip(),
    )


async def classify_plan_semantic_action(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    recent_plan_context: dict[str, object] | None = None,
) -> PlanSemanticActionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "recentPlanContext": recent_plan_context or {},
            "decisionQuestion": "当前用户是否在方案层要求查看、审查、分析调整，还是生成可确认的处理预览？",
        },
        ensure_ascii=False,
    )
    result = await _get_plan_action_agent().run(prompt)
    return _normalize_plan_semantic_action_decision(
        parse_extraction_json(result.output, PlanSemanticActionDecision)
    )


async def select_fix_proposal_candidate(
    *,
    latest_utterance: str,
    assistant_reply: str = "",
    candidates: list[dict[str, object]],
    request_context: RequestContext,
) -> FixProposalSelectionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "assistantReply": assistant_reply,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "candidates": candidates,
            "decisionQuestion": "在这些 ready 处理建议中，哪一个最贴近用户本轮真正想先看的调整预览？",
        },
        ensure_ascii=False,
    )
    result = await _get_fix_proposal_selection_agent().run(prompt)
    return _normalize_fix_proposal_selection_decision(
        parse_extraction_json(result.output, FixProposalSelectionDecision)
    )


async def classify_plan_recovery_action(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    recent_plan_context: dict[str, object] | None = None,
) -> PlanRecoveryActionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "recentPlanContext": recent_plan_context or {},
            "decisionQuestion": "完整 Agent 没有生成可执行预览时，是否可把用户原话恢复为一个结构化方案调整预览动作？",
        },
        ensure_ascii=False,
    )
    result = await _get_plan_recovery_action_agent().run(prompt)
    return _normalize_plan_recovery_action_decision(
        parse_extraction_json(result.output, PlanRecoveryActionDecision)
    )


async def classify_composite_goal_action(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    attempted_action_family: str | None = None,
    attempted_result: dict[str, object] | None = None,
) -> CompositeGoalDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "attemptedPlanAction": attempted_action_family or "",
            "attemptedResultKind": (attempted_result or {}).get("result_kind") or (attempted_result or {}).get("resultKind") or "",
            "attemptedSummary": (attempted_result or {}).get("summary") or "",
            "decisionQuestion": "用户原话是否应恢复为复合报考目标，而不是普通删除/加入/替换动作？",
        },
        ensure_ascii=False,
    )
    result = await _get_composite_goal_agent().run(prompt)
    return _normalize_composite_goal_decision(
        parse_extraction_json(result.output, CompositeGoalDecision)
    )


async def classify_pending_confirmation_action(
    latest_utterance: str,
    *,
    pending_state: dict[str, object] | None,
    request_context: RequestContext,
) -> PendingSemanticActionDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "pendingState": _pending_state_payload(pending_state),
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "decisionQuestion": "当前用户回复是在确认、拒绝、追问当前待处理内容，还是开启了其他话题？",
        },
        ensure_ascii=False,
    )
    result = await _get_pending_action_agent().run(prompt)
    return _normalize_pending_semantic_action_decision(
        parse_extraction_json(result.output, PendingSemanticActionDecision)
    )
