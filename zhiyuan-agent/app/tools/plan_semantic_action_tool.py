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
PlanActionFamily = Literal[
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
PlanActionSortField = Literal["admissionRatio", "schoolRank", "finalScore"]
LocalPlanAction = Literal["none", "move_ordered_unit"]
LocalPlanRank = Literal["highest", "lowest", "best", "worst"]
LocalPlanTargetRank = Literal["first", "last"]
class PlanSemanticActionDecision(BaseModel):
    actionFamily: PlanSemanticAction = "none"
    confidence: float = 0.0
    reason: str = ""
    replyFocus: list[str] = Field(default_factory=list)
    targetStrategies: list[str] = Field(default_factory=list)
    targetIssueCodes: list[str] = Field(default_factory=list)
    profileScenario: Literal["none", "adhoc_scenario", "current_student_update", "ambiguous"] = "none"
    proposedProfile: dict[str, object] = Field(default_factory=dict)

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

    @field_validator("profileScenario", mode="before")
    @classmethod
    def _coerce_profile_scenario(cls, value: object) -> str:
        text = str(value or "").strip()
        return text if text in {"none", "adhoc_scenario", "current_student_update", "ambiguous"} else "none"

    @field_validator("proposedProfile", mode="before")
    @classmethod
    def _coerce_proposed_profile(cls, value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}


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


class PlanActionDslDecision(BaseModel):
    actionFamily: PlanActionFamily = "none"
    confidence: float = 0.0
    reason: str = ""
    unsupportedAction: str | None = None
    reviewIssueCode: str | None = None
    volunteerIds: list[str] = Field(default_factory=list)
    unitIds: list[str] = Field(default_factory=list)
    sourceMajorNames: list[str] = Field(default_factory=list)
    sourcePosition: int | None = None
    positionScope: Literal["single", "after"] = "single"
    targetPosition: int | None = None
    sortField: PlanActionSortField | None = None
    tier: str | None = None
    provinceKeyword: str | None = None
    schoolKeyword: str | None = None
    majorKeyword: str | None = None
    schoolTags: list[str] = Field(default_factory=list)
    majorTags: list[str] = Field(default_factory=list)
    preserveCount: bool = False
    limit: int = 5

    @field_validator("actionFamily", mode="before")
    @classmethod
    def _coerce_action_family(cls, value: object) -> object:
        if value in (None, ""):
            return "none"
        return value

    @field_validator("volunteerIds", "unitIds", "sourceMajorNames", "schoolTags", "majorTags", mode="before")
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

    @field_validator("sourcePosition", "targetPosition", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @field_validator("sortField", mode="before")
    @classmethod
    def _coerce_optional_sort_field(cls, value: object) -> object | None:
        if value in (None, ""):
            return None
        return value

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

    @field_validator("preserveCount", mode="before")
    @classmethod
    def _coerce_preserve_count(cls, value: object) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {"true", "1", "yes", "y", "是", "需要", "保留", "保持", "不变"}
        return bool(value)


class PlanAtomicActionDslDecision(PlanActionDslDecision):
    minTuitionPerYear: int | None = None
    maxTuitionPerYear: int | None = None
    preferenceFit: Literal["aligned", "unrelated", "conflict"] | None = None

    @field_validator("minTuitionPerYear", "maxTuitionPerYear", mode="before")
    @classmethod
    def _coerce_optional_tuition(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            amount = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return amount if amount > 0 else None

    @field_validator("preferenceFit", mode="before")
    @classmethod
    def _coerce_preference_fit(cls, value: object) -> object | None:
        text = str(value or "").strip()
        if text in {"aligned", "unrelated", "conflict"}:
            return text
        return None


class LocalPlanActionDslDecision(BaseModel):
    actionFamily: LocalPlanAction = "none"
    confidence: float = 0.0
    reason: str = ""
    tier: str | None = None
    sortField: PlanActionSortField | None = None
    rank: LocalPlanRank | None = None
    targetOrdinal: int | None = None
    targetRank: LocalPlanTargetRank | None = None
    unsupportedAction: str | None = None

    @field_validator("actionFamily", mode="before")
    @classmethod
    def _coerce_action_family(cls, value: object) -> object:
        if value in (None, ""):
            return "none"
        return value

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

    @field_validator("targetOrdinal", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @field_validator("sortField", "rank", "targetRank", mode="before")
    @classmethod
    def _coerce_empty_optional(cls, value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


_plan_action_llm_client: LLMClient | None = None
_plan_action_agent: Agent[None, str] | None = None
_fix_proposal_selection_agent: Agent[None, str] | None = None
_plan_atomic_action_dsl_agent: Agent[None, str] | None = None
_local_plan_action_dsl_agent: Agent[None, str] | None = None


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
                "即使 actionFamily=none，仍可以并且应该输出 replyFocus/targetIssueCodes，"
                "用于约束完整 Agent 只回答用户点名的问题，避免泛化回复。"
                "首轮泛化方案解读不要抢到 analyze_adjustment：例如用户问当前方案对某专业/地域/职业方向承接怎么样、"
                "省外/公办/高收费是不是太多、这版偏专业还是学校、值不值得、说人话讲讲、整体是否划算，"
                "如果只是想了解当前方案事实、覆盖、比例、偏向或价值判断，且最近上下文里没有审查结果或处理建议，"
                "应 actionFamily=none，让完整 Agent 读取方案和候选事实回答；"
                "不要把这类问题改写成录取率断层、冲稳保比例或其它审查修复问题。"
                "如果首轮问题只是咨询风险价值、解释边界或查看事实，例如中外合作贵不贵/值不值得、"
                "高收费会不会影响保底、医学护理里中医算不算、候选里有没有某类更稳机会，"
                "应 actionFamily=none，让完整 Agent 按方案、候选和专业事实回答；"
                "不要因为文本提到了高收费、中外合作、医学、保底、某专业，就改写成审查修复分析。"
                "但当用户明确是在问当前方案里某一类审查风险或提醒的命中数量、占比、有没有或多不多，"
                "例如费用预算、高收费、中外合作、限报条件、特殊招生这类当前方案风险，"
                "可以判为 review_plan，并必须填写 targetIssueCodes 和 replyFocus=[\"target_issue_only\"]；"
                "这种场景只读审查，不生成调整预览，也不要填写 unavailable_guidance。"
                "当用户只是说帮我用大白话看风险、风险大不大、是不是有点多、家里预算一般、先别动，"
                "本质仍是当前方案的只读风险解释，应 actionFamily=none；"
                "如果 recentPlanContext.reviewIssueCodes 已给出对应风险 code，必须把这些 code 放入 targetIssueCodes，"
                "并把 replyFocus 设为 [\"target_issue_only\"]；"
                "不要填 unavailable_guidance，也不要因为提到费用/合作办学就生成 replace_risk_items。"
                "例如用户问“中外合作是不是有点多，家里预算一般，先别动”，且 reviewIssueCodes 包含 cooperative_program/high_tuition，"
                "输出 actionFamily=none、replyFocus=[\"target_issue_only\"]、targetIssueCodes=[\"cooperative_program\",\"high_tuition\"]。"
                "当用户问当前强基+普通批方案是否合理，且 recentPlanContext.specialPath 包含 strongbase 或 regular_batch，"
                "这是方案状态/路径解释查询，应 actionFamily=query_state，replyFocus 至少包含 state_explanation 和 review_boundary；不要输出 none。"
                "用户问当前方案能不能补稳/补保/补齐、候选是否足够、候选不够时怎么办、为什么不能补齐，"
                "如果只是要判断可行性、解释边界或给调整思路，而不是要求立刻生成可确认调整清单，可判为 analyze_adjustment，"
                "但 replyFocus 必须同时包含 shortage_boundary 和 plan_structure_shortage_only；"
                "plan_structure_shortage_only 只用于纯方案结构缺口，例如补稳、补保、补齐数量、候选供给不足、保底够不够。"
                "如果用户问题绑定地域/城市、专业方向、学校层次、职业路径或生活取舍，例如“想去北京天津但别没学上”，"
                "这不是纯结构缺口，actionFamily=none，交给完整 Agent 做综合分析。"
                "不要判成 query_state；query_state 只适合单纯查看现状统计。"
                "没有最近审查结果或处理建议时，analyze_adjustment 的快捷入口只适合 shortage_boundary 或 unavailable_guidance；"
                "其中 unavailable_guidance 只适合用户明确追问已经出现的提醒为什么不能处理、为什么不能直接改、"
                "或让系统解释这些处理建议该如何取舍；"
                "不能把普通风险解释、价值判断、白话分析、先别动看一眼归为 unavailable_guidance。"
                "不要仅因为你能推断出 targetStrategies/targetIssueCodes 就判为 analyze_adjustment。"
                "preview_fix_proposal 只表示用户正在承接最近一次审查/处理建议，"
                "希望把这些已识别的问题整理成一版可确认的调整预览；"
                "通常需要能从上下文看到最近审查结果或处理建议；"
                "如果 planningSummary 显示已有当前方案，且用户同一轮明确要求检查某类方案提醒并先看可确认的调整预览，"
                "也可以判为 preview_fix_proposal，由服务层先重新审查再生成预览。"
                "当用户已经明确说“先给我看预览/先看调整预览/给我一版预览/列出可确认的调整”，"
                "并且目标属于审查处理建议（例如处理录取率倒挂、补兜底专业、替换高收费/中外合作、补断层），"
                "应优先判为 preview_fix_proposal；不要只判为 review_plan 或 analyze_adjustment。"
                "只有用户只是问“有没有问题/能怎么处理/为什么/说人话/怎么取舍”，没有要求预览时，才判为 review_plan 或 analyze_adjustment。"
                "用户直接提出新的方案动作时不要判为 preview_fix_proposal，例如按推荐系数/院校层次/录取率排序、"
                "移动、删除、加入、替换、只保留某专业、排除某地域、更新偏好或要求；这些应交给完整 Agent 生成具体动作计划。"
                "用户说“把两万以上且跟我意向不沾边的删掉/移出”也是明确删除动作，不是审查修复预览。"
                "尤其是用户直接说按录取率从高到低/从低到高排一下、按录取概率排序、按推荐系数或院校层次排序，"
                "即使说了“先看预览”，本质也是 sort_ordered_plan 排序动作，不是审查修复建议；actionFamily 应为 none。"
                "用户只是问是否太冲、先看看影响、说人话、解释为什么、列命中项、怎么取舍、还没有要求生成可确认调整内容时，"
                "通常是 analyze_adjustment 或 none，不要生成预览。"
                "如果用户提出的是基础报考资料变化后的重新规划，例如分数、位次、省份、选科、批次等变化后要重新按新条件规划，"
                "这不属于当前方案内部的风险修复或普通调序替换；actionFamily 填 analyze_adjustment，"
                "replyFocus 必须包含 profile_change_replan。此时不要填写 targetStrategies，也不要当作缺少当前方案参数处理。"
                "必须额外判断 profileScenario："
                "current_student_update 表示用户在修正/更新当前学生本人的基础资料，或明确让当前会话以后按这组资料重算；"
                "adhoc_scenario 表示用户只是临时拿一组条件测算、假设推演、帮别人问、或没有要覆盖当前学生资料；"
                "ambiguous 表示无法确定是临时测算还是当前学生资料更新；"
                "none 表示不是资料变化重规划。"
                "只有 current_student_update 才允许服务层记录“旧方案未按新资料重算”的状态；"
                "adhoc_scenario 只能作为临时场景回答，不更新 profile，不让当前方案继承这组条件；"
                "ambiguous 应要求用户确认这是不是要更新本人资料，不要生成旧方案失效状态。"
                "proposedProfile 可填结构化资料，例如 score、rank、province、subjects、subjectCombo、batch；"
                "不要为了凑字段而猜，缺失就留空。"
                "承接上文的资料纠正也要按结构化语义判断：如果用户在前文已经纠正分数、省份或选科，"
                "随后说“按这组资料重来/重新规划/重新出方案/基于620湖北物化生重来”，"
                "且没有临时测算或帮别人问的语义，必须输出 profileScenario=current_student_update，"
                "replyFocus 包含 profile_change_replan，并把本轮明确出现的 score/province/subjectCombo 放入 proposedProfile。"
                "例如“那基于620湖北物化生重来”应输出 proposedProfile={score:620, province:'湖北', subjectCombo:'物化生'}。"
                "如果只修正单一字段，例如“分数也说错了应该是620不是630”，只填 score，不要猜省份和选科。"
                "如果用户说“如果按515临时看看/帮别人看看/假设这个分数”，profileScenario=adhoc_scenario，不能写成 current_student_update。"
                "如果用户是在追问当前方案是否已经按此前提出的新分数、省份、选科、批次等基础资料重算，"
                "或者问“现在方案是不是按这组资料算的”，actionFamily 通常填 query_state，"
                "replyFocus 必须包含 profile_change_state_query；此时只表达查询意图，"
                "不要把它重新判成一次新的 profile_change_replan，也不要补造 proposedProfile。"
                "如果用户语义同时包含解释问题和承接最近审查建议生成可确认处理预览，且上下文有对应处理建议，才可 preview_fix_proposal。"
                "高副作用的真正执行不在这里决定；这里最多决定是否生成预览。"
                "targetStrategies 可选填后端修复策略线索，例如 sort_by_probability、adjust_major_group_inner_safety、"
                "fill_probability_gap、rebalance_tier_ratio、replace_risk_items、remove_risk_items。"
                "targetIssueCodes 可选填当前用户聚焦的审查问题 code，例如 high_tuition、cooperative_program、"
                "probability_inversion、probability_gap、major_group_safety_intent_alignment、group_inner_safety_guard、"
                "admission_limit、special_enrollment、count_validation、edge_score、safety_guard。"
                "replyFocus 可选填回复展示重点，例如 unavailable_guidance 表示用户想知道为什么某些提醒不能直接处理以及自己可以怎么调；"
                "shortage_boundary 表示用户重点关注候选不足、补稳/补保是否可行；plan_structure_shortage_only 表示它是纯方案结构缺口而非地域/专业/学校/职业取舍；"
                "target_issue_only 表示只围绕用户点名的某类问题展开。"
                "只要用户的问题明确聚焦当前方案中的某一类审查提醒、风险来源或处理方向，就必须填写 targetStrategies，"
                "不要把它留空；同时尽量填写 targetIssueCodes。targetIssueCodes 用来约束后续分析只围绕用户点名的那类问题展开。"
                "审查修复目标要按用户想让系统怎么动来判，不要只按用户提到的风险依据来判："
                "如果用户说录取率太悬/不够安全，但动作是补入、加入、保留一个更安全/更稳的专业，"
                "这类目标是补专业组内安全垫，不是排序。"
                "当用户承接审查结果要求在专业组里补更安全/更稳的专业、补兜底专业、处理非意向托底或组内安全垫时，"
                "targetStrategies 只填写 adjust_major_group_inner_safety，targetIssueCodes 填 major_group_safety_intent_alignment 或 group_inner_safety_guard；"
                "不要同时填写 sort_by_probability 或 rebalance_tier_ratio，除非用户还明确要求重排顺序或调整冲稳保比例。"
                "sort_by_probability 只用于用户要求处理录取率倒挂、修正当前审查指出的顺序倒挂、调整前后顺序或修正风险梯度顺序；"
                "用户要求补更安全专业时不要用 sort_by_probability，即使问题里提到录取率。"
                "当用户要求处理录取率倒挂或修正审查里的录取率顺序问题时填写 sort_by_probability，targetIssueCodes 填 probability_inversion；"
                "当用户要求补录取概率断层时填写 fill_probability_gap，targetIssueCodes 填 probability_gap；"
                "当用户泛泛要求补稳/调冲稳保比例时填写 rebalance_tier_ratio。"
                "当用户围绕学费预算压力、收费偏高、合作办学、国际项目等当前方案里的费用/项目风险询问怎么处理、"
                "要不要替换、能否换成普通收费、先看影响或取舍时，targetStrategies 填 replace_risk_items，"
                "targetIssueCodes 填 high_tuition 和/或 cooperative_program；"
                "如果用户明确只想移出这类风险项而不是替换补位，可填 remove_risk_items。"
                "当用户围绕限报条件、体检限制、外语单科限制、特殊招生等不适合保留的条目询问怎么处理时，"
                "targetStrategies 优先填写 remove_risk_items，若语义是换成更合适条目则填写 replace_risk_items。"
                "只有很确定时 confidence >= 0.8；不确定时 actionFamily=none 或 confidence < 0.8。"
                "输出 JSON：actionFamily, confidence, reason, replyFocus, targetStrategies, targetIssueCodes, profileScenario, proposedProfile。"
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


def _get_local_plan_action_dsl_agent() -> Agent[None, str]:
    global _local_plan_action_dsl_agent
    if _local_plan_action_dsl_agent is None:
        _local_plan_action_dsl_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是 3.2.0 当前方案局部动作 DSL 抽取器，只输出 JSON。"
                "任务是把用户本轮对当前正式方案排序区的明确局部动作，抽成 LocalPlanActionDslDecision；"
                "不回复用户、不执行工具、不创建 pending、不做旧 recovery。"
                "不要依据固定关键词或模板做判断，要基于语义、上下文和副作用边界判断。"
                "当前只支持 actionFamily=move_ordered_unit，表示移动当前方案排序区里的展示单元/专业组。"
                "支持的形态是：在冲/稳/保某个档位内，按一个排序依据选择一个极值项，再移动到同一档位内的某个序位。"
                "tier 输出 保底、稳档、冲档之一；sortField 只能是 admissionRatio、schoolRank、finalScore。"
                "sortField 映射必须严格按语义：录取率/录取概率=admissionRatio；院校层次/院校排名=schoolRank；推荐系数/推荐分/综合推荐=finalScore。"
                "不要把推荐系数误写成 admissionRatio；不要把录取率误写成 finalScore。"
                "rank 表示 selector 选择哪个项：录取率/推荐系数高的用 highest，低的用 lowest；"
                "院校层次/院校排名更好、更靠前用 best，更靠后用 worst。"
                "targetOrdinal 表示档内第几位，例如保底第一位输出 1，冲档第二位输出 2；"
                "如果用户明确说档内最后/末位，targetRank=last 且 targetOrdinal 为空。"
                "如果用户说全局第 N 位，或没有说清楚档内目标位置，不要强行当作档内位置。"
                "如果用户要求锁定/固定/保护不动，输出 actionFamily=none、unsupportedAction=pin_or_lock_unit。"
                "如果用户只是查询、审查、解释影响、问能不能、要求整体排序、删除/加入/替换、或对象不是当前方案排序区局部移动，输出 none。"
                "必须有正式方案且无 active pending 才可高置信输出 move_ordered_unit；否则输出 none。"
                "只有 actionFamily、tier、sortField、rank、targetOrdinal/targetRank 都能确定时，confidence 才能 >= 0.85。"
                "不确定时 actionFamily=none 或 confidence < 0.85。"
                "例：'把稳档里推荐系数最高的专业组放到稳档第一位' 输出 actionFamily=move_ordered_unit, tier=稳档, sortField=finalScore, rank=highest, targetOrdinal=1。"
                "例：'把冲档院校层次最靠前的那个移到冲档第二位' 输出 sortField=schoolRank, rank=best, targetOrdinal=2。"
                "例：'把保底录取率最低的放到保底最后' 输出 sortField=admissionRatio, rank=lowest, targetRank=last。"
                "输出 JSON 字段：actionFamily, confidence, reason, tier, sortField, rank, targetOrdinal, targetRank, unsupportedAction。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _local_plan_action_dsl_agent


def _get_plan_atomic_action_dsl_agent() -> Agent[None, str]:
    global _plan_atomic_action_dsl_agent
    if _plan_atomic_action_dsl_agent is None:
        _plan_atomic_action_dsl_agent = Agent(
            model=_get_plan_action_llm_client().model,
            output_type=str,
            instructions=(
                "你是高考志愿方案对话的当前方案原子动作 DSL 判定器，只输出 JSON。"
                "任务是判断用户本轮是否明确要求对当前方案生成一个可确认的原子变更预览；"
                "不回复用户、不执行工具、不创建 pending。"
                "不要依据固定关键词或模板做判断，要基于语义、上下文、动作副作用和结构化范围是否足够来判断。"
                "actionFamily 只能是 none、generate_plan、add_units、remove_units、move_unit、move_ordered_unit、"
                "replace_units、remove_ordered_unit、sort_ordered_plan、regenerate_order。"
                "只有用户明确要生成、补入、删除、移动、替换、排序或重排当前方案时，才输出非 none；"
                "只是在问数量、有没有、原因、影响、适不适合、风险、政策、学校/专业介绍、对比分析、偏好记录或报考条件变更时输出 none。"
                "如果用户只是表达想去/不想去、想学/不想学、只保留/必须有某方向，但没有明确要求调整当前方案，输出 none。"
                "如果用户明确说要从当前方案中删掉某专业、某院校、某地域或某类风险，使用 remove_units，"
                "并把专业名放 sourceMajorNames，院校放 schoolKeyword，地域放 provinceKeyword。"
                "如果对象是当前方案审查已经识别出的风险或提醒类型，例如高收费、中外合作、限报条件、特殊招生，"
                "不要把它当成专业名；使用 remove_units 或 replace_units，并把对应审查 code 放 reviewIssueCode，"
                "例如高收费=high_tuition，中外合作=cooperative_program，限报条件=admission_limit，特殊类型招生=special_enrollment。"
                "如果用户明确删除当前方案里超过某个学费阈值的志愿，填写 minTuitionPerYear；"
                "如果用户明确要求预算上限或不超过某个费用，填写 maxTuitionPerYear。"
                "如果用户同时限定不贴合意向、跟意向不沾边或与偏好冲突，填写 preferenceFit=unrelated 或 conflict。"
                "如果用户明确说要加入或补齐某类候选，使用 add_units，并把筛选条件放 majorKeyword、schoolKeyword、provinceKeyword、tier 或 tags。"
                "如果用户明确说把某条学校+专业移动到第 N 位，使用 move_unit，volunteerIds 填用户原始引用，targetPosition 填 N。"
                "如果用户只用位置表达，如“第8个移到第12位/第8条放到第12”，没有学校专业名，"
                "使用 move_ordered_unit，sourcePosition 填 8，targetPosition 填 12。"
                "如果用户明确删除第 N 个/第 N 个专业组且没有学校专业名，使用 remove_ordered_unit，sourcePosition 填 N。"
                "如果用户明确删除第 N 位之后/后面的当前方案展示单元，使用 remove_ordered_unit，"
                "sourcePosition 填 N，positionScope 填 after；如果还限定冲/稳/保或数量，同时填写 tier 和 limit。"
                "如果用户明确要求按录取率/院校层次/推荐系数整体排序，使用 sort_ordered_plan，"
                "sortField 分别填 admissionRatio、schoolRank、finalScore。"
                "替换动作必须同时能看出要替换当前方案里的对象和新方向；否则输出 none 或低置信。"
                "preserveCount 只在用户明确要求数量不变、补齐、保持满额时为 true。"
                "limit 只在用户明确数量时填写，否则默认 5。"
                "高副作用真正执行不在这里决定；这里只编译预览链路。"
                "只有很确定时 confidence >= 0.85；不确定时 actionFamily=none 或 confidence < 0.85。"
                "输出 JSON 字段：actionFamily, confidence, reason, unsupportedAction, reviewIssueCode, volunteerIds, unitIds, "
                "sourceMajorNames, sourcePosition, positionScope, targetPosition, sortField, tier, provinceKeyword, schoolKeyword, "
                "majorKeyword, schoolTags, majorTags, minTuitionPerYear, maxTuitionPerYear, preferenceFit, preserveCount, limit。"
            ),
            model_settings=_get_plan_action_llm_client().model_settings,
        )
    return _plan_atomic_action_dsl_agent


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
        profileScenario=decision.profileScenario,
        proposedProfile=dict(decision.proposedProfile or {}),
    )


def _normalize_fix_proposal_selection_decision(
    decision: FixProposalSelectionDecision,
) -> FixProposalSelectionDecision:
    return FixProposalSelectionDecision(
        proposalId=str(decision.proposalId or "").strip(),
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
    )


def _normalize_local_plan_action_dsl_decision(
    decision: LocalPlanActionDslDecision,
) -> LocalPlanActionDslDecision:
    action_family = str(decision.actionFamily or "none").strip()
    if action_family not in {"none", "move_ordered_unit"}:
        action_family = "none"
    tier = str(decision.tier or "").strip() or None
    tier_aliases = {"保": "保底", "保档": "保底", "稳": "稳档", "冲": "冲档"}
    if tier:
        tier = tier_aliases.get(tier, tier)
    rank = str(decision.rank or "").strip() or None
    if rank not in {"highest", "lowest", "best", "worst", None}:
        rank = None
    target_rank = str(decision.targetRank or "").strip() or None
    if target_rank not in {"first", "last", None}:
        target_rank = None
    return LocalPlanActionDslDecision(
        actionFamily=action_family,  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
        tier=tier,
        sortField=decision.sortField,
        rank=rank,  # type: ignore[arg-type]
        targetOrdinal=decision.targetOrdinal,
        targetRank=target_rank,  # type: ignore[arg-type]
        unsupportedAction=str(decision.unsupportedAction or "").strip() or None,
    )


def _normalize_list_values(values: object) -> list[str]:
    result: list[str] = []
    raw_values = values if isinstance(values, (list, tuple, set)) else ([] if values is None else [values])
    for item in raw_values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_plan_action_dsl_decision(decision: PlanActionDslDecision) -> PlanActionDslDecision:
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
    tier = str(decision.tier or "").strip()
    tier_aliases = {"保": "保底", "保护": "保底"}
    tier = tier_aliases.get(tier, tier)
    limit = decision.limit if isinstance(decision.limit, int) else 5
    if limit <= 0:
        limit = 5
    return PlanActionDslDecision(
        actionFamily=action_family,  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        reason=str(decision.reason or "").strip(),
        unsupportedAction=str(decision.unsupportedAction or "").strip() or None,
        reviewIssueCode=str(decision.reviewIssueCode or "").strip() or None,
        volunteerIds=_normalize_list_values(decision.volunteerIds),
        unitIds=_normalize_list_values(decision.unitIds),
        sourceMajorNames=_normalize_list_values(decision.sourceMajorNames),
        sourcePosition=decision.sourcePosition,
        positionScope=decision.positionScope,
        targetPosition=decision.targetPosition,
        sortField=sort_field or None,  # type: ignore[arg-type]
        tier=tier or None,
        provinceKeyword=str(decision.provinceKeyword or "").strip() or None,
        schoolKeyword=str(decision.schoolKeyword or "").strip() or None,
        majorKeyword=str(decision.majorKeyword or "").strip() or None,
        schoolTags=_normalize_list_values(decision.schoolTags),
        majorTags=_normalize_list_values(decision.majorTags),
        preserveCount=bool(decision.preserveCount),
        limit=limit,
    )


def _normalize_plan_atomic_action_dsl_decision(decision: PlanAtomicActionDslDecision) -> PlanAtomicActionDslDecision:
    base = _normalize_plan_action_dsl_decision(decision)
    preference_fit = str(decision.preferenceFit or "").strip()
    if preference_fit not in {"aligned", "unrelated", "conflict"}:
        preference_fit = ""
    return PlanAtomicActionDslDecision(
        actionFamily=base.actionFamily,
        confidence=base.confidence,
        reason=base.reason,
        unsupportedAction=base.unsupportedAction,
        reviewIssueCode=base.reviewIssueCode,
        volunteerIds=list(base.volunteerIds),
        unitIds=list(base.unitIds),
        sourceMajorNames=list(base.sourceMajorNames),
        sourcePosition=base.sourcePosition,
        positionScope=base.positionScope,
        targetPosition=base.targetPosition,
        sortField=base.sortField,
        tier=base.tier,
        provinceKeyword=base.provinceKeyword,
        schoolKeyword=base.schoolKeyword,
        majorKeyword=base.majorKeyword,
        schoolTags=list(base.schoolTags),
        majorTags=list(base.majorTags),
        preserveCount=base.preserveCount,
        limit=base.limit,
        minTuitionPerYear=decision.minTuitionPerYear,
        maxTuitionPerYear=decision.maxTuitionPerYear,
        preferenceFit=preference_fit or None,  # type: ignore[arg-type]
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


async def classify_plan_atomic_action_dsl(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    recent_plan_context: dict[str, object] | None = None,
) -> PlanAtomicActionDslDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "recentPlanContext": recent_plan_context or {},
            "decisionQuestion": "当前用户是否明确提出了可编译为 AtomicPlanActionDsl 的当前方案变更预览动作？",
        },
        ensure_ascii=False,
    )
    result = await _get_plan_atomic_action_dsl_agent().run(prompt)
    return _normalize_plan_atomic_action_dsl_decision(
        parse_extraction_json(result.output, PlanAtomicActionDslDecision)
    )


async def classify_local_plan_action_dsl(
    latest_utterance: str,
    *,
    request_context: RequestContext,
    recent_plan_context: dict[str, object] | None = None,
) -> LocalPlanActionDslDecision:
    prompt = json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningSummary": _planning_summary_payload(getattr(request_context, "planning_summary", None)),
            "activePending": bool(getattr(getattr(request_context, "conversation_phase", None), "pending", None)),
            "recentPlanContext": recent_plan_context or {},
            "decisionQuestion": "当前用户是否明确提出了可编译为 3.2.0 LocalPlanActionDsl 的当前方案档内局部移动动作？",
        },
        ensure_ascii=False,
    )
    result = await _get_local_plan_action_dsl_agent().run(prompt)
    return _normalize_local_plan_action_dsl_decision(
        parse_extraction_json(result.output, LocalPlanActionDslDecision)
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
