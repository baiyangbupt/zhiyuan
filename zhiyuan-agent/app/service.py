from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.base_agent import ProgressCallback
from app.agent.chat_agent import ChatAgent
from app.agent.context import (
    PlanningSummary,
    RequestContext,
    ScoreDetail,
    resolve_pending_confirmation,
)
from app.zhiyuan_agent.agent import ZhiyuanAgent
from app.zhiyuan_agent.sandbox import DEFAULT_WARM_PATHS, build_request_sandbox
from app.zhiyuan_agent.tools import confirm_pending as zhiyuan_agent_confirm_pending
from app.models.conversation_phase import ConversationPhase, PendingConfirmation
from app.agent.usage_tracker import UsageTracker
from app.config import HistoryConfig
from app.data.history_store import ChatHistoryStore
from app.data.major_aliases import CATEGORY_PREFERRED_MAJOR_ALIASES
from app.data.message_utils import pydantic_ai_messages_to_dicts
from app.domain.major_entity_resolver import compact_major_text, resolve_major_entity, resolve_major_mentions_from_text
from app.domain import proposal_compiler
from app.domain.region_entity_resolver import normalize_region_names, resolve_region_entity
from app.domain.school_entity_resolver import resolve_school_entity
from app.domain.career_slots import normalize_career_slots, to_career_labels
from app.llm.client import LLMClient
from app.schemas.user_profile import UserProfile
from app.services.profile_manager import _normalize_batch
from app.schemas.ws import WSResponse
from app.sync.state_sync import PlanningStateSync
from app.tools.explore_followup_tool import handle_interest_analysis_action_result
from app.tools.plan_execution_tool import (
    clear_recent_plan_execution_result,
    consume_recent_plan_execution_result,
    execute_plan_action,
)
from app.tools.candidate_filter_extraction_tool import extract_candidate_query_filters_async
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.plan_semantic_action_tool import (
    classify_plan_atomic_action_dsl,
    classify_local_plan_action_dsl,
    classify_plan_semantic_action,
)
from app.tools.plan_query_profile_tool import PlanQueryProfileResult, classify_plan_query_profile
from app.tools.planning_workflow_tool import _format_fix_proposal_apply_result
from app.tools.planning_workflow_tool import _fix_proposal_facts
from app.tools.plan_orchestration_models import (
    CompositePlanProposal,
    PlanGoal,
    normalize_plan_action_payload,
)
from app.tools.intent_state_tool import (
    ANALYSIS_STAGE_CONFIRMED,
    apply_selected_intents as _apply_selected_intents,
    analyze_volunteer_intent_change,
    _classify_intent_side_effect,
    merge_selected_values,
    _normalize_constraint_type_for_payload,
    _remove_positive_major_targets_excluded_by_negative_scope,
)
from app.tools.intent_entity_profile_tool import extract_intent_entity_profile
from app.tools.intent_response_tool import (
    parse_intent_analysis_payload,
    parse_explore_followup_result,
    parse_intent_state_update_result,
    render_explore_followup_result,
    render_intent_state_update,
)
from app.tools.intent_relation_tool import compact_relation_impact_lines
from app.tools.turn_decision_tool import classify_turn_decision
from app.util.internal_client import (
    apply_planning_fix_proposal,
    generate_user_goal_planning_fix_proposals,
    get_last_pending_confirmation,
    get_message_by_id,
    get_pending_confirmation,
    get_planning_state,
    get_planning_workspace_state,
    get_user_init_profile,
    get_user_score_detail,
    save_intent_change_cache,
    save_pending_confirmation,
    update_session_tuition_range,
    update_message,
)
from app.util.structured_log import log_event

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    with contextlib.suppress(TypeError, ValueError):
        return float(raw)
    logger.warning("Invalid %s=%r; using default %.1f", name, raw, default)
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning("Invalid %s=%r; using default %s", name, raw, default)
    return default


_TURN_DECISION_TIMEOUT_SECONDS = max(0.0, _env_float("TURN_DECISION_TIMEOUT_SECONDS", 25.0))
_ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS = max(
    0.0,
    _env_float("ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS", 30.0),
)
_ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE = min(
    1.0,
    max(0.0, _env_float("ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE", 1.0)),
)
_ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS = max(
    0.0,
    _env_float("ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS", 30.0),
)

_PLAN_STYLE_SEVERE_MARKERS = (
    "你必须决定",
    "你现在必须决定",
    "必须做出选择",
    "必须做一个选择",
    "必须选一个",
    "没有第三个选项",
    "我无法继续回应",
    "我不再重复解释",
    "我不再回应",
    "最后一次说明",
    "必须停止这个循环",
    "停止这个循环",
    "完全没有意义",
    "当前这版财会类方案就是最优解",
    "当前这版财会类方案保留",
    "我现在直接帮你重新生成",
    "补偿预览",
    "不要再反复查看",
    "选哪个",
    "选 A/B/C",
    "选 A、B 或 C",
    "选 A、B、C",
)
_PLAN_STYLE_DANGLING_EXACT_LINES = {"你。", "只有。", "请。"}
_USER_REPLY_FORCED_CHOICE_MARKERS = (
    "你现在必须决定",
    "你必须决定",
    "必须做出选择",
    "必须做一个选择",
    "必须选一个",
    "没有第三个选项",
    "你选哪个",
    "请选一个",
    "请明确回复",
    "回复 A 或 B",
    "回复A或B",
)
_PLAN_STYLE_GUARD_PROMPT_KEYWORDS = (
    "方案",
    "志愿",
    "候选",
    "审查",
    "风险",
    "重排",
    "排序",
    "怎么调",
    "优化",
    "补偿",
    "补几个",
    "补齐",
    "补满",
    "还差",
    "怎么补",
    "更稳",
    "不合理",
    "稳不稳",
    "删掉",
    "删除",
    "去掉",
    "加进去",
    "加入",
    "往前挪",
    "往后挪",
    "换成",
)
_READONLY_USER_PROMPT_MARKERS = (
    "先别动",
    "先不要动",
    "不要动方案",
    "别动方案",
    "先不要改方案",
    "不要改方案",
    "先查一下不要改",
    "先看看不要改",
    "只分析",
    "先只分析",
    "只看",
    "只查",
    "别直接加",
    "不要直接加",
    "先别加",
    "先不要加",
    "别加入",
    "不要加入",
    "别加进",
    "不要加进",
    "先别记",
    "先不要记",
    "不要记偏好",
    "别记偏好",
    "不要记录",
    "别记录",
)
_PLAN_ACTION_NEGATIVE_ACK_MARKERS = (
    "上面没有要做",
    "上面没有要处理",
    "上面没有要替换",
    "没有要做的替换",
    "没有要处理的替换",
    "不用替换",
    "不要替换",
    "先不替换",
    "不用处理",
    "不要处理",
    "先不处理",
    "不执行",
    "先不执行",
)
_READONLY_MUTATION_GUARD_REPLY = (
    "我按“先看、先查、不直接改”的方式处理了这轮请求，当前不会加入、删除、移动或重排方案。"
    "如果你想把某个候选真正加入方案，可以再明确说“加入方案”或指定要调整的位置，我会先给出可确认的调整预览。"
)
_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY = (
    "这轮先按分析处理，不会改动当前方案。"
    "如果后面需要调整方案，我会先给出调整预览；确认前不会执行。"
)
_UNBACKED_PLAN_CONFIRMATION_REPLY = (
    "这轮还没有生成可执行的调整内容，所以不会改动当前方案。"
    "如果你要继续调整，请再发一次具体要求，我会重新定位影响范围并列出调整预览；"
    "只有你点“确认执行”或直接确认当前有效预览后才会执行。"
)
_NO_TOOL_NO_ACTION_BOUNDARY_REPLY = (
    "可以，先按这次思路保留和讨论；这轮不会改动当前方案，也不会写入后续报考参考里的偏好或要求，更不会开始任何方案调整。"
    "下一步如果要正式采用新的想法或调整方案，我会先把要采用的内容或调整预览列清楚，你确认前不会执行。"
)
_ROUTE_OBSERVABILITY_MODEL_NAME = "route-observability"
_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD = 0.8
_LOCAL_PLAN_ACTION_DSL_CONFIDENCE_THRESHOLD = 0.85
_LOCAL_PLAN_UNSUPPORTED_ACTIONS = frozenset({"pin_or_lock_unit"})
_INTENT_PREVIEW_TOOL_NAMES = {
    "analyze_volunteer_intent_change",
    "preview_current_intent_confirmation",
    "preview_current_major_intent_confirmation",
    "preview_current_school_intent_confirmation",
    "preview_current_region_intent_confirmation",
    "preview_current_career_intent_confirmation",
}
_INTENT_INTEREST_ANALYSIS_TOOL_NAMES = {
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
}
_MAJOR_CONTEXT_TOOL_NAMES = {
    "analyze_current_major_interest",
    "compare_major_options",
    "compare_majors",
    "compare_majors_adhoc",
    "get_major_introduction",
    "get_major_introductions",
}
_ENTITY_CONTEXT_TOOL_NAMES = _MAJOR_CONTEXT_TOOL_NAMES | {
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
    "compare_schools",
    "compare_schools_adhoc",
    "get_school_introduction",
    "preview_current_major_intent_confirmation",
    "preview_current_school_intent_confirmation",
    "preview_current_region_intent_confirmation",
    "preview_current_career_intent_confirmation",
    "preview_current_intent_confirmation",
}
_USER_REPLY_ENGLISH_WORD_REPLACEMENTS = (
    (re.compile(r"\s*\bmostly\b\s*", re.IGNORECASE), "基本上"),
    (re.compile(r"\s*\bincreasingly\b\s*", re.IGNORECASE), "越来越"),
    (re.compile(r"\s*\bbaseline\b\s*", re.IGNORECASE), "基准"),
)

_PLAN_ACTION_REPLY_SYNTHESIS_INSTRUCTIONS = """\
你负责把已经执行完成的志愿方案工具结果，整理成用户能看懂的一段中文回复。

约束：
- 只基于输入里的结构化事实回答，不新增数字、学校、专业、风险结论。
- 不要说“工具、系统、action_family、payload、blocked、preview_only、cannot_satisfy、候选池、自动修复、自动处理、自动补齐、自动应用、系统阻塞、预览验证未通过、预览参考状态、被卡住”。
- 不要说“系统给了/系统能执行/系统没法执行/暂时动不了/卡在哪/我立刻处理/给我明确态度我就能处理”。
- 统一用“你”，不要用“您”。
- 不要照抄 summary/state_summary；它们只是事实摘要。
- 如果已有可确认的调整预览，说明“我已把可确认的处理内容列出来，确认前不会改方案”，并点出核心处理内容。
- 如果某些建议暂时不能直接处理，用用户能理解的原因说清楚，例如“没有足够相近且风险更低的可替换志愿”“需要你先决定是否接受降层次或换专业范围”。
- 没有当前轮可确认的调整预览时，不要让用户直接“确认就执行”；应表达为“我可以先列出调整预览，确认前不会改方案”。
- 回复可以结构化，但要简洁，优先用 2-4 个短要点；不要堆叠多层标题。
"""

_FIX_PROPOSAL_STRATEGY_TEXT = {
    "replace_risk_items": "替换风险项",
    "remove_risk_items": "移出风险项",
    "fill_missing_count": "补足数量",
    "sort_by_probability": "按录取率重排",
    "rebalance_tier_ratio": "调整冲稳保结构",
    "fill_probability_gap": "补梯度断层",
    "add_safety_items": "补安全垫",
    "adjust_major_group_inner_safety": "补兜底专业",
}

_FIX_PROPOSAL_STATUS_TEXT = {
    "ready": "可以先列出调整预览，确认前不会改方案",
    "preview_only": "只能先作为处理方向参考，需要你决定取舍范围",
    "blocked": "需要你先取舍或放宽条件，暂时不适合直接改方案",
    "info": "仅供参考",
}
_PROFILE_CHANGE_REPLAN_REPLY_FOCUS = "profile_change_replan"

_REVIEW_REPLY_QUALITY_MARKERS = (
    "需要你先决定取舍的方向：",
    "建议你先查看具体影响，或调整筛选范围后再试：",
    "当前候选志愿里，目标冲稳保区间候选不足；",
    "当前候选志愿里，断层中间录取率候选不足；",
    "可以先出调整预览给你看：",
    "需要你先决定取舍或放宽条件：",
    "候选供给",
    "系统预估",
    "系统不会",
    "给个明确态度",
    "可以立即处理",
)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _score_like_values_for_reply(text: str | None) -> list[int]:
    values: list[int] = []
    for match in re.finditer(r"(?<!\d)(\d{3})(?!\d)", str(text or "")):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if 100 <= value <= 750 and value not in values:
            values.append(value)
    return values


def _reply_focus_set(value: Any) -> set[str]:
    if isinstance(value, dict):
        values: list[Any] = []
        raw_focus = value.get("reply_focus")
        if isinstance(raw_focus, list):
            values.extend(raw_focus)
        facts = value.get("facts") if isinstance(value.get("facts"), dict) else {}
        requested_focus = facts.get("requested_reply_focus") if isinstance(facts, dict) else None
        if isinstance(requested_focus, list):
            values.extend(requested_focus)
        return {str(item or "").strip() for item in values if str(item or "").strip()}
    values = getattr(value, "replyFocus", None)
    if isinstance(values, list):
        return {str(item or "").strip() for item in values if str(item or "").strip()}
    return set()


def _requests_profile_change_replan(value: Any) -> bool:
    return _PROFILE_CHANGE_REPLAN_REPLY_FOCUS in _reply_focus_set(value)


def _semantic_current_plan_analysis_allowed(value: Any) -> bool:
    """Whether semantic quick route may answer analysis without review context.

    Generic questions such as "这版值不值得/偏专业还是学校/省外是不是多"
    need richer plan reading by the full agent.  The semantic route should only
    take first-turn analysis when the classifier explicitly marks a bounded
    shortage/unavailable-guidance scenario and the user is actually asking for
    that boundary explanation.
    """

    focus = _reply_focus_set(value)
    if "unavailable_guidance" in focus:
        return True
    return "shortage_boundary" in focus and "plan_structure_shortage_only" in focus


def _semantic_current_plan_analysis_matches_prompt(value: Any, user_prompt: str | None) -> bool:
    focus = _reply_focus_set(value)
    if "shortage_boundary" in focus:
        return "plan_structure_shortage_only" in focus
    if "unavailable_guidance" in focus:
        return _review_prompt_prefers_unavailable_guidance(user_prompt) or _prompt_requests_plan_constraint_adjustment(user_prompt)
    return False


def _semantic_targeted_review_allowed(value: Any) -> bool:
    return proposal_compiler.semantic_targeted_review_allowed(
        value,
        confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
    )


def _turn_decision_is_plan_review_or_repair_preview(decision: Any) -> bool:
    try:
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return False
    return (
        str(getattr(decision, "taskLayer", "") or "").strip() == "plan"
        and str(getattr(decision, "sideEffect", "") or "").strip() == "readonly_or_plan_preview"
        and str(getattr(decision, "scopeAnchor", "") or "").strip() == "current_plan"
        and str(getattr(decision, "scenario", "") or "").strip() == "plan_review_or_repair_preview"
    )


def _turn_decision_snapshot(decision: Any) -> dict[str, Any]:
    return {
        "taskLayer": str(getattr(decision, "taskLayer", "") or "").strip(),
        "sideEffect": str(getattr(decision, "sideEffect", "") or "").strip(),
        "scopeAnchor": str(getattr(decision, "scopeAnchor", "") or "").strip(),
        "scenario": str(getattr(decision, "scenario", "") or "").strip(),
        "targetIssue": [
            str(item or "").strip()
            for item in list(getattr(decision, "targetIssue", []) or [])
            if str(item or "").strip()
        ],
        "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        "reason": str(getattr(decision, "reason", "") or ""),
    }


def _semantic_query_state_should_run_review(content: str | None) -> bool:
    """Promote a state query to review only when the user asks for judgment.

    Counts and distribution are status facts. Questions like "梯度有没有问题"
    require review evidence, even if the model classifies the turn as a broad
    query_state follow-up. The route remains readonly and does not imply a
    workspace refresh followup.
    """
    compact = _compact_plan_reply_text(str(content or ""))
    if not compact:
        return False
    has_review_subject = any(
        token in compact
        for token in (
            "梯度",
            "风险",
            "冲稳保",
            "录取率",
            "倒挂",
            "排序",
            "保底够",
            "保底足",
        )
    )
    has_review_judgment = any(
        token in compact
        for token in (
            "有没有问题",
            "有问题吗",
            "有问题么",
            "有没有风险",
            "稳不稳",
            "合理不",
            "合不合理",
            "不合理",
            "是否合理",
            "是不是有问题",
            "是不是不稳",
            "有无问题",
        )
    )
    return has_review_subject and has_review_judgment


def _plan_result_reply_focus_set(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    focus: list[Any] = []
    raw_focus = value.get("reply_focus")
    if isinstance(raw_focus, list):
        focus.extend(raw_focus)
    facts = value.get("facts") if isinstance(value.get("facts"), dict) else {}
    requested_focus = facts.get("requested_reply_focus") if isinstance(facts, dict) else None
    if isinstance(requested_focus, list):
        focus.extend(requested_focus)
    return {str(item or "").strip() for item in focus if str(item or "").strip()}


def _plan_result_requests_fix_preview(value: Any) -> bool:
    focus = _plan_result_reply_focus_set(value)
    return bool(focus & {"fix_proposal_preview", "ready_fix_proposals"})


def _plan_result_has_fix_proposals(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    facts = value.get("facts") if isinstance(value.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    if not isinstance(fix_facts, dict):
        return False
    if any(_as_int(fix_facts.get(key)) > 0 for key in ("ready_count", "blocked_count", "preview_only_count")):
        return True
    proposals = fix_facts.get("proposals")
    return isinstance(proposals, list) and bool(proposals)


def _plan_result_has_ready_fix_proposals(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    facts = value.get("facts") if isinstance(value.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    if not isinstance(fix_facts, dict):
        return False
    if _as_int(fix_facts.get("ready_count") or fix_facts.get("readyCount")) > 0:
        return True
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    return any(
        isinstance(proposal, dict) and str(proposal.get("status") or "").strip() == "ready"
        for proposal in proposals
    )


def _plan_route_context_requests_fix_preview(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    focus = value.get("replyFocus")
    return isinstance(focus, list) and any(
        str(item or "").strip() in {"fix_proposal_preview", "ready_fix_proposals"}
        for item in focus
    )


def _plan_route_context_has_fix_proposals(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    fix_facts = value.get("fixProposals")
    if not isinstance(fix_facts, dict):
        return False
    if any(_as_int(fix_facts.get(key)) > 0 for key in ("readyCount", "blockedCount", "previewOnlyCount")):
        return True
    proposals = fix_facts.get("proposals")
    return isinstance(proposals, list) and bool(proposals)


def _structured_review_context_is_readonly(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("lastActionFamily") or "").strip() != "review_plan":
        return False
    if str(value.get("lastResultKind") or "").strip() != "review_result":
        return False
    if _plan_route_context_requests_fix_preview(value):
        return False
    return _plan_route_context_has_fix_proposals(value)


def _structured_review_result_is_readonly(value: Any) -> bool:
    """A review result that should be explained, not promoted into a mutation.

    This only inspects structured tool output.  When the review result explicitly
    requests a fix preview, recovery is still allowed; otherwise a review result
    with proposals is treated as a read-only explanation/listing boundary.
    """

    if not isinstance(value, dict):
        return False
    if str(value.get("action_family") or "").strip() != "review_plan":
        return False
    if str(value.get("result_kind") or "").strip() != "review_result":
        return False
    if _plan_result_requests_fix_preview(value):
        return False
    focus = _plan_result_reply_focus_set(value)
    return _plan_result_has_fix_proposals(value) and (
        not focus or bool(focus & {"review_result", "fix_proposals", "unavailable_guidance"})
    )


def _prompt_asks_review_explanation_only(content: str | None) -> bool:
    compact = _compact_plan_reply_text(str(content or ""))
    if not compact:
        return False
    has_review_context = any(marker in compact for marker in ("审查", "提醒", "风险", "自动处理", "只是看看"))
    has_explanation_request = any(
        marker in compact
        for marker in (
            "看不懂",
            "帮我分一下",
            "分一下",
            "哪些只是看看",
            "哪些可以自动处理",
            "哪些可以先出调整预览",
            "哪些需要人工",
            "解释一下",
        )
    )
    return has_review_context and has_explanation_request


def _build_profile_change_replan_reply(
    user_prompt: str | None,
    *,
    request_context: RequestContext | None = None,
    profile_change_dsl: dict[str, Any] | None = None,
) -> str:
    score_values = _score_like_values_for_reply(user_prompt)
    dsl = profile_change_dsl if isinstance(profile_change_dsl, dict) else None
    dsl_type = str((dsl or {}).get("type") or "").strip()
    proposed_summary = _profile_replan_summary_for_reply(dsl)
    if dsl_type == "ProfileReplanAdhoc":
        score_text = proposed_summary or (f"{score_values[0]} 分" if score_values else "这组临时资料")
        missing_fields = [
            str(item or "").strip()
            for item in ((dsl or {}).get("missingProfileFields") or [])
            if str(item or "").strip()
        ]
        missing_line = ""
        if missing_fields:
            missing_text = "、".join(
                {
                    "score_or_rank": "分数或位次",
                    "province": "省份",
                    "subjects": "选科",
                }.get(item, item)
                for item in missing_fields
            )
            missing_line = f"\n- 如果要进一步临时测算候选或方案，还需要补充：{missing_text}。"
        return _sanitize_reply_for_user(_normalize_user_facing_terms(
            "\n".join([
                f"可以先按 {score_text} 当作临时场景看，但这不会更新当前学生资料，也不会让当前方案按这组资料失效。",
                "",
                "- 当前方案、候选池和待采纳内容都会保持原状态；这轮只作为临时测算口径。",
                "- 如果你要把这组资料改成当前学生资料，需要明确确认后再重新计算候选和方案。",
            ])
            + missing_line
        ))
    if dsl_type == "ProfileReplanAmbiguous":
        score_text = proposed_summary or (f"{score_values[0]} 分" if score_values else "这组资料")
        return _sanitize_reply_for_user(_normalize_user_facing_terms(
            "\n".join([
                f"我还不能确定 {score_text} 是只做临时测算，还是要更新当前学生资料后重新规划。",
                "",
                "- 在你确认前，我不会更新当前资料，也不会让当前方案失效。",
                "- 如果只是临时看看，可以直接说明“只是临时测算”；如果要按这组资料重算当前学生方案，请明确说“更新当前资料并重算”。",
            ])
        ))
    score_text = proposed_summary or (f"{score_values[0]} 分" if score_values else "新的成绩信息")
    current_score = None
    if request_context is not None:
        score_detail = getattr(request_context, "score_detail", None)
        with contextlib.suppress(TypeError, ValueError):
            parsed = int(getattr(score_detail, "total_score", 0) or 0)
            if parsed > 0:
                current_score = parsed
    current_summary = str((dsl or {}).get("currentProfileSummary") or "").strip()
    if not current_summary and current_score:
        current_summary = f"{current_score} 分"
    current_line = f"当前记录的是 {current_summary}；" if current_summary and current_summary != score_text else ""
    return _sanitize_reply_for_user(_normalize_user_facing_terms(
        "\n".join([
            f"可以按 {score_text} 重新规划，但这属于基础报考信息变化，不能直接当作普通方案调整来改。",
            "",
            f"- {current_line}如果要采用这组新信息，需要先确认更新基础画像，最好同时确认位次、批次是否也有变化。",
            "- 更新后应重新计算可选志愿，再生成新的方案或调整预览；当前方案仍按原来的信息保留。",
            "- 确认前我不会改当前方案。你确认按这个新成绩重新规划后，我再继续重算候选和方案。",
        ])
    ))


def _profile_replan_summary_for_reply(profile_change_dsl: dict[str, Any] | None) -> str:
    if not isinstance(profile_change_dsl, dict):
        return ""
    proposed = profile_change_dsl.get("proposedProfile")
    proposed = proposed if isinstance(proposed, dict) else {}
    summary = str(profile_change_dsl.get("proposedProfileSummary") or "").strip()
    if summary and set(proposed.keys()) <= {"score"}:
        score = _as_int(proposed.get("score"))
        if score > 0:
            return f"{score} 分"
    return summary


def _build_profile_change_replan_state_query_reply(
    *,
    profile_change_dsl: dict[str, Any],
    pending_state: dict[str, Any] | None = None,
) -> str:
    proposed_summary = str(profile_change_dsl.get("proposedProfileSummary") or "这组新资料").strip()
    current_summary = str(profile_change_dsl.get("currentProfileSummary") or "原来的资料").strip()
    pending_note = ""
    if isinstance(pending_state, dict) and str(pending_state.get("status") or "active").strip() == "active":
        summary = str(pending_state.get("summary") or "").strip()
        if summary:
            pending_note = f"\n\n另外，当前还有一项待采纳内容：{summary}；未采纳前不会生效。"
        else:
            pending_note = "\n\n另外，当前还有一项待采纳内容；未采纳前不会生效。"
    return _sanitize_reply_for_user(_normalize_user_facing_terms(
        "\n".join(
            [
                f"还不能说当前正式方案已经按 {proposed_summary} 重算。",
                "",
                f"- 这组信息已经被识别为当前学生资料变更后的重规划需求，但当前方案仍按 {current_summary} 保留。",
                "- 要按这组新资料看学校、保底、冲稳保或审查结论，需要先完成基础资料更新，并重新计算候选和生成方案。",
                "- 在新方案生成前，当前工作台里的正式方案只能按旧口径参考。",
            ]
        )
        + pending_note
    ))


def _current_profile_payload_from_context(request_context: RequestContext | None) -> dict[str, Any]:
    if request_context is None:
        return {}
    score_detail = getattr(request_context, "score_detail", None)
    if score_detail is None:
        return {}
    profile: dict[str, Any] = {}
    with contextlib.suppress(TypeError, ValueError):
        total_score = int(getattr(score_detail, "total_score", 0) or 0)
        if total_score > 0:
            profile["score"] = total_score
    province = str(getattr(score_detail, "province", "") or "").strip()
    if province:
        profile["province"] = province
    subject_list = [
        str(item or "").strip()
        for item in (getattr(score_detail, "subject_list", []) or [])
        if str(item or "").strip()
    ]
    if subject_list:
        profile["subjects"] = subject_list
    batch = str(getattr(request_context, "batch", "") or "").strip()
    if batch:
        profile["batch"] = batch
    return profile


def _compile_profile_replan_from_decision(
    decision: Any,
    *,
    request_context: RequestContext | None = None,
) -> proposal_compiler.ProfileChangeReplanCompiledSource:
    planning_version = 0
    planning_summary = getattr(request_context, "planning_summary", None) if request_context is not None else None
    if planning_summary is not None:
        with contextlib.suppress(TypeError, ValueError):
            planning_version = int(getattr(planning_summary, "version", 0) or 0)
    proposed_profile = getattr(decision, "proposedProfile", None)
    proposed_profile = proposed_profile if isinstance(proposed_profile, dict) else {}
    previous_dsl = (
        getattr(request_context, "latest_profile_change_replan_dsl", None)
        if request_context is not None
        else None
    )
    previous_profile = (
        previous_dsl.get("proposedProfile")
        if isinstance(previous_dsl, dict) and isinstance(previous_dsl.get("proposedProfile"), dict)
        else None
    )
    return proposal_compiler.compile_profile_change_replan_source(
        profile_scenario=str(getattr(decision, "profileScenario", "none") or "none"),
        proposed_profile=proposed_profile,
        previous_proposed_profile=previous_profile,
        current_profile=_current_profile_payload_from_context(request_context),
        planning_version=planning_version,
    )


def _compile_profile_replan_from_payload(
    payload: dict[str, Any] | None,
    *,
    request_context: RequestContext | None = None,
) -> proposal_compiler.ProfileChangeReplanCompiledSource:
    payload = payload if isinstance(payload, dict) else {}
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    proposed_profile = (
        payload.get("proposedProfile")
        or payload.get("proposed_profile")
        or facts.get("proposedProfile")
        or facts.get("proposed_profile")
    )
    proposed_profile = proposed_profile if isinstance(proposed_profile, dict) else {}
    previous_dsl = (
        getattr(request_context, "latest_profile_change_replan_dsl", None)
        if request_context is not None
        else None
    )
    previous_profile = (
        previous_dsl.get("proposedProfile")
        if isinstance(previous_dsl, dict) and isinstance(previous_dsl.get("proposedProfile"), dict)
        else None
    )
    profile_scenario = (
        payload.get("profileScenario")
        or payload.get("profile_scenario")
        or facts.get("profileScenario")
        or facts.get("profile_scenario")
        or "none"
    )
    planning_version = 0
    planning_summary = getattr(request_context, "planning_summary", None) if request_context is not None else None
    if planning_summary is not None:
        with contextlib.suppress(TypeError, ValueError):
            planning_version = int(getattr(planning_summary, "version", 0) or 0)
    return proposal_compiler.compile_profile_change_replan_source(
        profile_scenario=str(profile_scenario or "none"),
        proposed_profile=proposed_profile,
        previous_proposed_profile=previous_profile,
        current_profile=_current_profile_payload_from_context(request_context),
        planning_version=planning_version,
    )


def _semantic_decision_is_current_student_profile_replan(decision: Any) -> bool:
    if not _requests_profile_change_replan(decision):
        return False
    return str(getattr(decision, "profileScenario", "none") or "none").strip() == "current_student_update"


def _semantic_decision_is_profile_replan(decision: Any) -> bool:
    if not _requests_profile_change_replan(decision):
        return False
    return str(getattr(decision, "profileScenario", "none") or "none").strip() in {
        "current_student_update",
        "adhoc_scenario",
        "ambiguous",
    }


def _turn_decision_is_current_student_profile_replan(decision: Any) -> bool:
    if not _turn_decision_is_profile_replan(decision):
        return False
    return str(getattr(decision, "profileScenario", "none") or "none").strip() == "current_student_update"


def _turn_decision_is_profile_replan(decision: Any) -> bool:
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    profile_scenario = str(getattr(decision, "profileScenario", "none") or "none").strip()
    expected = {
        "current_student_update": ("profile_change_replan", "profile_update_replan"),
        "adhoc_scenario": ("profile_replan_adhoc", "profile_adhoc_replan"),
        "ambiguous": ("profile_replan_ambiguous", "profile_scope_ambiguous"),
    }.get(profile_scenario)
    if expected is None:
        return False
    expected_side_effect, expected_scenario = expected
    return (
        confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
        and str(getattr(decision, "taskLayer", "") or "").strip() == "plan"
        and str(getattr(decision, "sideEffect", "") or "").strip() == expected_side_effect
        and str(getattr(decision, "scopeAnchor", "") or "").strip() == "current_profile"
        and str(getattr(decision, "scenario", "") or "").strip() == expected_scenario
    )


def _profile_replan_routing_path(source: proposal_compiler.ProfileChangeReplanCompiledSource, *, prefix: str) -> str:
    side_effect = str(getattr(source, "side_effect", "") or "").strip()
    if side_effect == "profile_replan_adhoc":
        return f"{prefix}_profile_replan_adhoc"
    if side_effect == "profile_replan_ambiguous":
        return f"{prefix}_profile_replan_ambiguous"
    return f"{prefix}_profile_change_replan"


def _turn_decision_is_profile_change_state_query(
    decision: Any,
    *,
    pending_exists: bool = False,
) -> bool:
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    task_layer = str(getattr(decision, "taskLayer", "") or "").strip()
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    scope_anchor = str(getattr(decision, "scopeAnchor", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    expected_side_effect = "readonly_while_pending" if pending_exists else "readonly"
    return (
        confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
        and task_layer == "plan"
        and scope_anchor == "current_profile"
        and side_effect == expected_side_effect
        and scenario == "profile_change_state_query"
    )


async def _classify_active_pending_turn_decision(
    *,
    content: str,
    request_context: RequestContext,
    planning_summary: PlanningSummary | None,
    pending_state: dict[str, Any] | None,
    score_detail: ScoreDetail | None,
) -> Any | None:
    try:
        decision = await _classify_turn_decision_cached(
            content,
            request_context=request_context,
            payload={
                "planningStateProfile": _planning_state_profile_for_turn_decision(
                    planning_summary=planning_summary,
                    pending_state=pending_state if isinstance(pending_state, dict) else None,
                    score_detail=score_detail,
                ),
                "pendingState": pending_state if isinstance(pending_state, dict) else {},
            },
        )
    except Exception:
        logger.warning(
            "Active pending TurnDecision failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return None
    _store_current_turn_decision(request_context, decision)
    return decision


def _compact_fix_proposal_for_reply_synthesis(proposal: dict[str, Any]) -> dict[str, Any]:
    def clean_text(value: Any) -> str:
        return _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))

    status = str(proposal.get("status") or "").strip()
    strategy = str(proposal.get("strategy") or "").strip()
    action_summaries = [
        clean_text(item)
        for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])
        if clean_text(item)
    ][:4]
    shortages: list[str] = []
    for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
        if not isinstance(shortage, dict):
            continue
        message = str(shortage.get("message") or "").strip()
        if message:
            shortages.append(clean_text(message))
    warnings = [
        clean_text(item)
        for item in (proposal.get("warnings") or [])
        if clean_text(item)
    ][:3]
    reason_parts = [
        str(proposal.get("blocking_reason") or proposal.get("blockingReason") or "").strip(),
        *shortages[:3],
        *warnings,
    ]
    return {
        "title": clean_text(proposal.get("title")),
        "availability": _FIX_PROPOSAL_STATUS_TEXT.get(status, "需要结合审查结果进一步判断"),
        "strategy": _FIX_PROPOSAL_STRATEGY_TEXT.get(strategy, strategy),
        "summary": clean_text(proposal.get("summary")),
        "impact": clean_text(proposal.get("impact")),
        "action_summaries": action_summaries,
        "change_counts": {
            "remove_volunteers": _as_int(proposal.get("remove_volunteer_count") or proposal.get("removeVolunteerCount")),
            "add_volunteers": _as_int(proposal.get("add_volunteer_count") or proposal.get("addVolunteerCount")),
            "remove_units": _as_int(proposal.get("remove_unit_count") or proposal.get("removeUnitCount")),
            "add_units": _as_int(proposal.get("add_unit_count") or proposal.get("addUnitCount")),
        },
        "reason": [
            clean_text(part)
            for part in reason_parts
            if clean_text(part)
        ][:4],
    }


def _compact_plan_action_result_for_reply_synthesis(result: dict[str, Any]) -> dict[str, Any]:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = [
        _compact_fix_proposal_for_reply_synthesis(proposal)
        for proposal in (fix_facts.get("proposals") or [])[:6]
        if isinstance(proposal, dict)
    ]
    issue_examples: list[dict[str, Any]] = []
    for issue in (facts.get("issue_hit_plan_examples") or facts.get("review_issue_hit_plan_examples") or [])[:6]:
        if not isinstance(issue, dict):
            continue
        issue_examples.append(
            {
                "code": str(issue.get("code") or "").strip(),
                "summary": _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(issue.get("summary") or "").strip())),
                "count_text": str(issue.get("count_text") or issue.get("countText") or "").strip(),
                "items": [
                    _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(item or "").strip()))
                    for item in (issue.get("items") or [])[:4]
                    if str(item or "").strip()
                ],
            }
        )
    return {
        "action_family": str(result.get("action_family") or "").strip(),
        "result_kind": str(result.get("result_kind") or "").strip(),
        "summary": _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(result.get("summary") or "").strip())),
        "state_summary": _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(result.get("state_summary") or "").strip())),
        "reply_focus": result.get("reply_focus") if isinstance(result.get("reply_focus"), list) else [],
        "review": {
            "plan_total": _as_int(facts.get("plan_total")),
            "target_total": _as_int(facts.get("target_total")),
            "risk_count": _as_int(facts.get("risk_count")),
            "warn_count": _as_int(facts.get("warn_count")),
            "tier_counts": facts.get("tier_counts") if isinstance(facts.get("tier_counts"), dict) else {},
            "main_problems": [
                _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(item or "").strip()))
                for item in (facts.get("main_problems") or [])[:6]
                if str(item or "").strip()
            ],
            "issue_examples": issue_examples,
            "target_issue_codes": [
                str(code or "").strip()
                for code in (facts.get("target_issue_codes") or facts.get("targetIssueCodes") or [])
                if str(code or "").strip()
            ],
        },
        "fix_proposals": {
            "total": _as_int(fix_facts.get("total") or len(proposals)),
            "ready_count": _as_int(fix_facts.get("ready_count")),
            "needs_user_decision_count": _as_int(fix_facts.get("blocked_count")) + _as_int(fix_facts.get("preview_only_count")),
            "proposals": proposals,
        },
    }


async def _synthesize_semantic_plan_action_reply(
    llm_client: LLMClient,
    *,
    user_prompt: str,
    result: dict[str, Any],
    recent_plan_context: dict[str, Any] | None = None,
) -> tuple[str, Any | None]:
    """Use a no-tool model pass to turn plan facts into user-facing prose."""

    synthesis_agent = Agent(
        model=llm_client.model,
        output_type=str,
        instructions=_PLAN_ACTION_REPLY_SYNTHESIS_INSTRUCTIONS,
        tools=[],
        model_settings=llm_client.model_settings,
    )
    prompt_payload = {
        "user_prompt": user_prompt,
        "recent_plan_context": recent_plan_context or {},
        "tool_result_facts": _compact_plan_action_result_for_reply_synthesis(result),
    }
    run_result = await synthesis_agent.run(
        json.dumps(prompt_payload, ensure_ascii=False, default=str),
        model_settings=llm_client.model_settings,
    )
    reply = str(getattr(run_result, "output", "") or "").strip()
    usage = None
    with contextlib.suppress(Exception):
        usage = run_result.usage()
    return _sanitize_reply_for_user(_normalize_user_facing_terms(reply)), usage


def _log_conversation_turn_event(**fields: Any) -> None:
    log_event("conversation_turn_event", **fields)


def _log_zhiyuan_agent_poc_shadow_event(**fields: Any) -> None:
    log_event("zhiyuan_agent_poc_shadow_event", **fields)


def _log_pending_confirmation_event(**fields: Any) -> None:
    log_event("pending_confirmation_event", **fields)


def _route_observability_message(turn_event: dict[str, Any] | None) -> ModelResponse | None:
    if not turn_event:
        return None
    try:
        content = json.dumps(
            {
                "type": "routeObservability",
                "event": "conversation_turn_event",
                **turn_event,
            },
            ensure_ascii=False,
        )
    except Exception:
        return None
    return ModelResponse(parts=[TextPart(content=content)], model_name=_ROUTE_OBSERVABILITY_MODEL_NAME)


def _append_route_observability_message(messages: list[Any], turn_event: dict[str, Any] | None) -> list[Any]:
    observability_message = _route_observability_message(turn_event)
    if observability_message is None:
        return messages
    result = list(messages)
    for index in range(len(result) - 1, -1, -1):
        message = result[index]
        if not isinstance(message, ModelResponse) or _is_route_observability_message(message):
            continue
        if any(isinstance(part, TextPart) for part in getattr(message, "parts", []) or []):
            result.insert(index, observability_message)
            return result
    return [*result, observability_message]


def _append_completed_poc_shadow_observability_message(
    messages: list[Any],
    *,
    request_context: RequestContext | None,
    session_id: str,
    user_id: str,
    prompt_length: int,
) -> list[Any]:
    if request_context is None:
        return messages
    shadow = getattr(request_context, "_zhiyuan_agent_poc_shadow", None)
    if not isinstance(shadow, dict):
        return messages
    if str(shadow.get("status") or "").strip() == "running":
        return messages
    message = _shadow_observability_message(
        session_id=session_id,
        user_id=user_id,
        prompt_length=prompt_length,
        shadow=shadow,
    )
    if message is None:
        return messages
    return [*messages, message]


def _append_turn_observability_messages(
    messages: list[Any],
    turn_event: dict[str, Any] | None,
    *,
    request_context: RequestContext | None = None,
    session_id: str = "",
    user_id: str = "",
    prompt_length: int = 0,
) -> list[Any]:
    result = _append_route_observability_message(messages, turn_event)
    return _append_completed_poc_shadow_observability_message(
        result,
        request_context=request_context,
        session_id=session_id,
        user_id=user_id,
        prompt_length=prompt_length,
    )


def _shadow_observability_message(
    *,
    session_id: str,
    user_id: str,
    prompt_length: int,
    shadow: dict[str, Any],
) -> ModelResponse | None:
    try:
        content = json.dumps(
            {
                "type": "routeObservability",
                "event": "zhiyuan_agent_poc_shadow_event",
                "sessionId": session_id,
                "userId": user_id,
                "promptLength": prompt_length,
                "shadow": shadow,
                "zhiyuanAgentPocShadow": shadow,
            },
            ensure_ascii=False,
        )
    except Exception:
        return None
    return ModelResponse(parts=[TextPart(content=content)], model_name=_ROUTE_OBSERVABILITY_MODEL_NAME)


async def _append_zhiyuan_agent_poc_shadow_history(
    history_store: ChatHistoryStore,
    *,
    session_id: str,
    user_id: str,
    prompt_length: int,
    shadow: dict[str, Any],
) -> None:
    message = _shadow_observability_message(
        session_id=session_id,
        user_id=user_id,
        prompt_length=prompt_length,
        shadow=shadow,
    )
    if message is None:
        return
    for _ in range(20):
        history = await history_store.load(session_id)
        if history:
            history.append(message)
            await history_store.save(session_id, history)
            return
        await asyncio.sleep(0.25)
    await history_store.save(session_id, [message])


def _is_route_observability_message(message: Any) -> bool:
    if not isinstance(message, ModelResponse):
        return False
    if str(getattr(message, "model_name", "") or "") == _ROUTE_OBSERVABILITY_MODEL_NAME:
        return True
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, TextPart):
            try:
                data = json.loads(part.content)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                return True
    return False


def _iter_route_observability_events(messages: list[Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, TextPart):
                continue
            data = _parse_tool_return_json(part.content)
            if isinstance(data, dict) and data.get("type") == "routeObservability":
                events.append(data)
    return events


def _latest_profile_change_replan_dsl(messages: list[Any] | None) -> dict[str, Any] | None:
    for event in reversed(_iter_route_observability_events(messages)):
        route_decision = event.get("routeDecision") if isinstance(event.get("routeDecision"), dict) else {}
        dsl = route_decision.get("profileChangeReplanDsl")
        if (
            isinstance(dsl, dict)
            and dsl.get("type") == "ProfileChangeReplan"
            and str(dsl.get("profileMode") or "").strip() == "current_student_update"
        ):
            return dsl
    return None


def _llm_config_value(llm_client: LLMClient, field_name: str) -> str | None:
    config = getattr(llm_client, "config", None)
    value = getattr(config, field_name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class ChatServiceResponseEnvelope:
    """服务层统一回复结构，允许主文本外再携带附加工作台动作。"""

    primary: str | WSResponse
    followups: list[WSResponse] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeHistoryResult:
    """Short-lived history passed to the model; full history remains persisted."""

    model_history: list[Any] | None
    chat_history: list[dict]
    full_len: int = 0
    runtime_len: int = 0
    full_text_chars: int = 0
    runtime_text_chars: int = 0
    dropped_tool_return_count: int = 0
    has_pending: bool = False


def _iter_tool_call_parts(messages: list[Any] | None) -> list[ToolCallPart]:
    parts: list[ToolCallPart] = []
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolCallPart):
                parts.append(part)
    return parts


def _iter_tool_return_parts(messages: list[Any] | None) -> list[ToolReturnPart]:
    parts: list[ToolReturnPart] = []
    for message in messages or []:
        if not isinstance(message, ModelRequest):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolReturnPart):
                parts.append(part)
    return parts


def _select_current_tool_context_messages(
    new_messages: list[Any] | None,
    all_messages: list[Any] | None,
    runtime_history: RuntimeHistoryView,
) -> list[Any]:
    """Pick the current-turn message slice that still contains tool calls/returns.

    Pydantic direct-tool-return runs may expose only the synthesized direct text
    in ``new_messages`` while the full current turn, including tool call/return
    parts, is only visible in ``all_messages``. Pending-card creation must inspect
    the full tool context, but it must not scan stale history from previous turns.
    """
    current = list(new_messages or [])
    if _iter_tool_return_parts(current):
        return current

    runtime_len = len(runtime_history.model_history or [])
    inferred: list[Any] = []
    if all_messages and len(all_messages) >= runtime_len:
        inferred = list(all_messages[runtime_len:])
    if _iter_tool_return_parts(inferred):
        return inferred
    return current or inferred


def _message_text_chars(messages: list[Any] | None) -> int:
    total = 0
    for message in messages or []:
        for part in getattr(message, "parts", []) or []:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                total += len(content)
                continue
            args = getattr(part, "args", None)
            if isinstance(args, str):
                total += len(args)
            elif isinstance(args, dict):
                try:
                    total += len(json.dumps(args, ensure_ascii=False))
                except Exception:
                    pass
    return total


def _message_has_user_prompt(message: Any) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    return any(isinstance(part, UserPromptPart) for part in getattr(message, "parts", []) or [])


def _count_user_turns(messages: list[Any] | None) -> int:
    return sum(1 for message in messages or [] if _message_has_user_prompt(message))


def _latest_user_prompt_index(messages: list[Any]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if _message_has_user_prompt(messages[index]):
            return index
    return None


def _compact_tool_return_content(content: Any) -> str:
    if not isinstance(content, str):
        return "[工具结果已裁剪：非文本结果]"
    try:
        parsed = json.loads(content)
    except Exception:
        return "[工具结果已裁剪：原结果过长]"
    if not isinstance(parsed, dict):
        return "[工具结果已裁剪：原结果过长]"

    keys = (
        "result_kind",
        "action_family",
        "messageCode",
        "message",
        "summary",
        "preview_summary",
        "userFacingSummary",
        "workspace_refresh_targets",
        "targetView",
        "applied",
        "success",
    )
    compacted = {key: parsed.get(key) for key in keys if parsed.get(key) is not None}
    if not compacted:
        return "[工具结果已裁剪：原结果过长]"
    compacted["_truncated"] = True
    return json.dumps(compacted, ensure_ascii=False)


def _should_compact_runtime_tool_return(part: ToolReturnPart, max_tool_return_chars: int) -> bool:
    if not isinstance(part.content, str):
        return False
    if part.tool_name in _INTENT_PREVIEW_TOOL_NAMES:
        return True
    return max_tool_return_chars > 0 and len(part.content) > max_tool_return_chars


def _compact_runtime_message(message: Any, max_tool_return_chars: int) -> tuple[Any, int]:
    if not isinstance(message, ModelRequest):
        return message, 0

    changed = False
    dropped = 0
    compacted_parts: list[Any] = []
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, ToolReturnPart) and _should_compact_runtime_tool_return(part, max_tool_return_chars):
            compacted_parts.append(
                ToolReturnPart(
                    tool_name=part.tool_name,
                    content=_compact_tool_return_content(part.content),
                    tool_call_id=part.tool_call_id,
                )
            )
            changed = True
            dropped += 1
            continue
        compacted_parts.append(part)

    if not changed:
        return message, 0
    return ModelRequest(parts=compacted_parts), dropped


def build_runtime_history(
    full_history: list[Any] | None,
    *,
    latest_user_content: str,
    has_active_pending: bool | None = None,
    config: HistoryConfig | None = None,
) -> RuntimeHistoryResult:
    """Build the short history used by the live model call.

    The persisted session history stays complete. This function only limits what
    is sent to the model and to text-history consumers in RequestContext.
    """
    history = [
        message
        for message in list(full_history or [])
        if not _is_route_observability_message(message)
    ]
    cfg = config or HistoryConfig()
    max_messages = max(0, int(getattr(cfg, "runtime_max_messages", 24) or 0))
    has_pending = bool(has_active_pending)

    if not history:
        return RuntimeHistoryResult(
            model_history=None,
            chat_history=[{"role": "user", "content": latest_user_content}],
            full_len=0,
            runtime_len=0,
            full_text_chars=0,
            runtime_text_chars=0,
            dropped_tool_return_count=0,
            has_pending=has_pending,
        )

    if max_messages == 0 or len(history) <= max_messages:
        selected = history
    else:
        selected_indices = set(range(len(history) - max_messages, len(history)))
        keep_pending = bool(getattr(cfg, "runtime_keep_pending", True))
        if has_pending and keep_pending:
            current_turn_start = _latest_user_prompt_index(history)
            if current_turn_start is None:
                current_turn_start = 0
            selected_indices.update(range(current_turn_start, len(history)))
        selected = [history[index] for index in sorted(selected_indices)]

    dropped_tool_returns = 0
    compacted_history: list[Any] = []
    max_tool_return_chars = int(getattr(cfg, "runtime_drop_tool_returns_over_chars", 3000) or 0)
    for message in selected:
        compacted, dropped = _compact_runtime_message(message, max_tool_return_chars)
        compacted_history.append(compacted)
        dropped_tool_returns += dropped

    chat_history = pydantic_ai_messages_to_dicts(compacted_history)
    chat_history.append({"role": "user", "content": latest_user_content})

    return RuntimeHistoryResult(
        model_history=compacted_history,
        chat_history=chat_history,
        full_len=len(history),
        runtime_len=len(compacted_history),
        full_text_chars=_message_text_chars(history),
        runtime_text_chars=_message_text_chars(compacted_history),
        dropped_tool_return_count=dropped_tool_returns,
        has_pending=has_pending,
    )


_SUPPORTED_WORKSPACE_ACTION_TARGETS = proposal_compiler.SUPPORTED_WORKSPACE_ACTION_TARGETS


def _dedupe_workspace_targets(targets: list[str]) -> list[str]:
    deduped: list[str] = []
    for target in targets:
        value = str(target or "").strip()
        if not value or value not in _SUPPORTED_WORKSPACE_ACTION_TARGETS or value in deduped:
            continue
        deduped.append(value)
    return deduped


_WORKSPACE_ACTION_COPY = {
    "candidate": {
        "title": "查看候选库关联结果",
        "content": "可以查看当前查询相关的候选机会；这只是可见候选视图，不会改小基础候选池。",
        "actionText": "打开候选库",
    },
    "ordered": {
        "title": "查看调整后的排序方案",
        "content": "已刷新排序方案，可以查看本次调整后的志愿列表和位置变化。",
        "actionText": "打开排序方案",
    },
    "review": {
        "title": "查看最新审查结果",
        "content": "已刷新方案审查结果，可以查看风险、提醒和处理建议。",
        "actionText": "打开审查结果",
    },
}


def _build_workspace_action_response(
    session_id: str,
    target: str,
    *,
    refresh: bool = True,
    extra_payload: dict[str, Any] | None = None,
) -> WSResponse:
    target_value = str(target or "").strip()
    if target_value not in _WORKSPACE_ACTION_COPY:
        raise ValueError(f"Unsupported workspace action target: {target_value}")
    copy = _WORKSPACE_ACTION_COPY.get(
        target_value,
        {
            "title": "查看工作台更新",
            "content": "工作台已有更新，可以打开对应区域查看最新结果。",
            "actionText": "查看更新",
        },
    )
    return WSResponse(
        type="planningWorkspaceAction",
        session_id=session_id,
        content=json.dumps(
            {
                "type": "planningWorkspaceAction",
                "targetView": target_value,
                "refresh": refresh,
                **copy,
                **(extra_payload or {}),
            },
            ensure_ascii=False,
        ),
    )


def _build_silent_workspace_refresh_response(
    session_id: str,
    target: str,
    *,
    extra_payload: dict[str, Any] | None = None,
) -> WSResponse:
    payload = {
        "silent": True,
        "preserveView": True,
        **(extra_payload or {}),
    }
    return _build_workspace_action_response(
        session_id,
        target,
        refresh=True,
        extra_payload=payload,
    )


def _extract_extra_data_value(response: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    data = (response or {}).get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if value is None:
        value = data.get("dataValue")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        value = parsed
    if not isinstance(value, dict):
        return None
    result = dict(value)
    data_version = _as_int(data.get("dataVersion") or data.get("version"))
    if data_version > 0:
        result.setdefault("_extraDataVersion", data_version)
        result.setdefault("dataVersion", data_version)
    return result


async def _load_pending_confirmation_state(session_id: str) -> dict[str, Any] | None:
    try:
        response = await get_last_pending_confirmation(session_id)
    except Exception:
        logger.warning("Failed to load latest pending confirmation state: session_id=%s", session_id, exc_info=True)
        response = None
    state = _extract_extra_data_value(response, "pendingConfirmation")
    if state:
        return state
    try:
        response = await get_pending_confirmation(session_id)
    except Exception:
        logger.warning("Failed to load pending confirmation state: session_id=%s", session_id, exc_info=True)
        return None
    return _extract_extra_data_value(response, "pendingConfirmation")


def _pending_extra_data_version(state: dict[str, Any] | None) -> int:
    if not isinstance(state, dict):
        return 0
    return _as_int(
        state.get("_extraDataVersion")
        or state.get("dataVersion")
        or state.get("sourceBackendVersion")
        or state.get("source_backend_version")
        or state.get("planningVersion")
        or state.get("planning_version")
    )


def _pending_confirmation_from_state(state: dict[str, Any] | None) -> PendingConfirmation | None:
    """Build runtime pending projection from backend pendingConfirmation state."""
    if not isinstance(state, dict):
        return None
    if str(state.get("status") or "").strip() != "active":
        return None
    kind = str(state.get("kind") or "").strip()
    action_family = str(state.get("actionFamily") or "").strip()
    if kind not in {"intent_change", "plan_mutation"} or not action_family:
        return None
    execution_payload = state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return None
    composite_proposal = state.get("compositeProposal")
    if not isinstance(composite_proposal, dict):
        composite_proposal = {}
    source_backend_version = _as_int(
        state.get("sourceBackendVersion")
        or state.get("source_backend_version")
        or state.get("planningVersion")
        or state.get("planning_version")
    )
    if kind == "plan_mutation":
        if action_family == "apply_fix_proposal":
            payload = dict(execution_payload)
        else:
            payload = proposal_compiler.ensure_structured_plan_payload(
                execution_payload,
                action_family=action_family,
            )
            if not proposal_compiler.is_structured_plan_payload(payload):
                return None
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family=action_family,
            preview_summary=str(state.get("summary") or ""),
            execution_payload=payload,
            affected_scope=str(state.get("affectedScope") or state.get("affected_scope") or ""),
            source_backend_version=source_backend_version,
            composite_proposal=composite_proposal,
        )
        created_turn = _as_int(state.get("createdTurn") or state.get("created_turn"))
        if created_turn > 0:
            pending = pending.model_copy(update={"created_turn": created_turn})
        return pending

    intent_payload = execution_payload.get("merged")
    if not isinstance(intent_payload, dict) or not intent_payload:
        intent_payload = execution_payload.get("selectedData")
    if not isinstance(intent_payload, dict) or not intent_payload:
        return None
    pending = PendingConfirmation(
        kind="intent_change",
        action_family=action_family,
        preview_summary=str(state.get("summary") or ""),
        execution_payload=execution_payload,
        source_backend_version=source_backend_version,
        composite_proposal=composite_proposal,
    )
    created_turn = _as_int(state.get("createdTurn") or state.get("created_turn"))
    if created_turn > 0:
        pending = pending.model_copy(update={"created_turn": created_turn})
    return pending


def _intent_summary_from_pending_state(state: dict[str, Any] | None) -> str:
    if not isinstance(state, dict) or str(state.get("kind") or "").strip() != "intent_change":
        return ""
    summary = str(state.get("summary") or "").strip()
    if summary:
        return summary
    execution_payload = state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return ""
    intent_mode = str(execution_payload.get("intentMode") or "preference").strip() or "preference"
    constraint_intent_type = str(
        execution_payload.get("constraintIntentType")
        or execution_payload.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    merged = execution_payload.get("merged")
    if isinstance(merged, dict) and merged:
        return _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
    selected_data = execution_payload.get("selectedData")
    if isinstance(selected_data, dict):
        selected = [item for item in (selected_data.get("selected") or []) if isinstance(item, dict)]
        if selected:
            try:
                merged = merge_selected_values(selected)
            except Exception:
                merged = {}
            if merged:
                return _summarize_intent_values(
                    merged,
                    intent_mode=intent_mode,
                    constraint_intent_type=constraint_intent_type,
                )
    return ""


def _recent_intent_summary_for_no_plan_guard(
    pending_state: dict[str, Any] | None,
    recent_intent_analysis: dict[str, Any] | None,
) -> str:
    pending_summary = _intent_summary_from_pending_state(pending_state)
    if pending_summary and str((pending_state or {}).get("status") or "").strip() in {"active", "applied"}:
        return pending_summary
    if not isinstance(recent_intent_analysis, dict):
        return ""
    return _intent_card_primary_reply_from_preview_payload(recent_intent_analysis).split("：", 1)[-1].split("。", 1)[0].strip()


async def _save_pending_confirmation_state(session_id: str, state: dict[str, Any]) -> None:
    try:
        await save_pending_confirmation(session_id, state, version=_pending_extra_data_version(state))
    except Exception:
        logger.warning("Failed to save pending confirmation state: session_id=%s", session_id, exc_info=True)


async def _mark_pending_confirmation_message_status(
    session_id: str,
    message_id: Any,
    *,
    pending_id: str,
    status: str,
) -> None:
    message_id_text = str(message_id or "").strip()
    if not message_id_text:
        return
    try:
        msg_resp = await get_message_by_id(message_id_text)
        msg_data = (msg_resp or {}).get("data") or {}
        content_raw = msg_data.get("content", "")
        try:
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            content_obj = {}
        if not isinstance(content_obj, dict) or content_obj.get("type") != "pendingConfirmationCard":
            return
        card_pending_id = str(content_obj.get("pendingId") or "").strip()
        if card_pending_id and pending_id and card_pending_id != pending_id:
            return
        updated = {
            **content_obj,
            "clickable": False,
            "clicked": status == "applied",
            "status": status,
        }
        if status in {"applied", "cancelled"}:
            updated["click_type"] = 1 if status == "applied" else 0
        await update_message(
            message_id=message_id_text,
            chat_session_id=session_id,
            content=updated,
            message_from=0,
            content_type="CARD",
        )
    except Exception:
        logger.warning(
            "Failed to update pending confirmation card message: session_id=%s message_id=%s status=%s",
            session_id,
            message_id_text,
            status,
            exc_info=True,
        )


async def _mark_pending_confirmation_failed(
    session_id: str,
    pending_state: dict[str, Any],
    message_id: Any,
    *,
    pending_id: str,
    result_code: str,
) -> None:
    failed_state = dict(pending_state)
    failed_state["status"] = "expired"
    failed_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    failed_state["resultCode"] = result_code
    await _save_pending_confirmation_state(session_id, failed_state)
    await _mark_pending_confirmation_message_status(
        session_id,
        message_id,
        pending_id=pending_id,
        status="expired",
    )


async def _expire_active_pending_confirmation_state(
    session_id: str,
    *,
    reason: str,
) -> None:
    pending_state = await _load_pending_confirmation_state(session_id)
    if not isinstance(pending_state, dict):
        return
    if str(pending_state.get("status") or "").strip() != "active":
        return
    expired_state = dict(pending_state)
    expired_state["status"] = "expired"
    expired_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    expired_state["expiredReason"] = reason
    await _save_pending_confirmation_state(session_id, expired_state)


async def _clear_legacy_plan_edit_cache_best_effort(session_id: str) -> None:
    try:
        session_id_int = int(str(session_id).strip())
    except (TypeError, ValueError):
        return
    try:
        await save_intent_change_cache(session_id_int, {})
    except Exception:
        logger.warning("Failed to clear legacy planEditCache: session_id=%s", session_id, exc_info=True)


def _build_plan_pending_state(
    session_id: str,
    confirmation_candidate: dict[str, Any],
    *,
    replaced_pending: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    resolution = proposal_compiler.resolve_plan_confirmation_candidate(confirmation_candidate)
    action_family = resolution.action_family
    payload_data = proposal_compiler.ensure_structured_plan_payload(
        resolution.plan_payload,
        action_family=action_family,
    )
    source_backend_version = resolution.source_version_guard
    execution_payload = dict(payload_data)
    execution_payload["toolName"] = "confirm_pending"
    execution_payload["action_family"] = action_family
    execution_payload.setdefault("stage", "apply")
    execution_payload.setdefault("requires_confirmation", False)
    execution_payload.setdefault("should_refresh_workspace", True)
    execution_payload.setdefault("should_rerun_review", True)
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": action_family,
        "summary": str(confirmation_candidate.get("summary") or "").strip(),
        "userGoal": str(confirmation_candidate.get("user_goal") or "").strip(),
        "executionPayload": execution_payload,
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_backend_version,
    }
    composite_proposal = payload_data.get("composite_proposal")
    if isinstance(composite_proposal, dict):
        state["compositeProposal"] = composite_proposal
    intent_update = confirmation_candidate.get("intent_update")
    if isinstance(intent_update, dict) and intent_update.get("selected"):
        state["executionPayload"]["intentPayload"] = intent_update
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if compiled_proposal_id:
        state["compiledProposalId"] = compiled_proposal_id
        state["compilerSink"] = {
            "compiledProposalId": compiled_proposal_id,
            "sinkType": str(compiled_sink_metadata.get("sinkType") or "plan").strip() or "plan",
        }
        state["executionPayload"]["compiledProposalId"] = compiled_proposal_id
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _soft_negative_label(label: str, *, intent_mode: str) -> str:
    if intent_mode == "constraint":
        return label
    replacements = {
        "排除专业": "不优先专业",
        "排除专业类": "不优先专业类",
        "排除专业门类": "不优先专业门类",
        "排除院校": "不优先院校",
        "排除地域": "不优先地域",
        "排除方向": "不优先发展方向",
    }
    return replacements.get(label, label)


def _positive_intent_label(label: str, *, constraint_intent_type: str = "default") -> str:
    if constraint_intent_type == "only_keep":
        replacements = {
            "偏好专业": "只保留专业",
            "偏好专业类": "只保留专业类",
            "偏好专业门类": "只保留专业门类",
            "偏好院校": "只保留院校",
            "偏好地域": "只保留地域",
            "发展方向": "只保留发展方向",
        }
        return replacements.get(label, label)
    if constraint_intent_type == "must_have":
        replacements = {
            "偏好专业": "至少保留专业",
            "偏好专业类": "至少保留专业类",
            "偏好专业门类": "至少保留专业门类",
            "偏好院校": "至少保留院校",
            "偏好地域": "至少保留地域",
            "发展方向": "至少保留发展方向",
        }
        return replacements.get(label, label)
    return label


def _positive_int_from_structured_value(value: Any) -> int:
    raw_values = value if isinstance(value, list) else [value] if value is not None else []
    for raw_value in raw_values:
        try:
            amount = int(raw_value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            return amount
    return 0


def _summarize_intent_values(
    merged: dict[str, Any],
    *,
    intent_mode: str = "preference",
    constraint_intent_type: str = "default",
) -> str:
    parts: list[str] = []
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    career_intents = merged.get("career_intents") if isinstance(merged.get("career_intents"), dict) else {}
    tuition_budget = merged.get("tuition_budget") if isinstance(merged.get("tuition_budget"), dict) else {}
    physical_constraints = (
        merged.get("physical_constraints")
        if isinstance(merged.get("physical_constraints"), dict)
        else merged.get("physicalConstraints")
        if isinstance(merged.get("physicalConstraints"), dict)
        else {}
    )

    def add(label: str, values: Any) -> None:
        raw_values = values if isinstance(values, list) else [values] if values else []
        texts = [str(value or "").strip() for value in raw_values if str(value or "").strip()]
        if texts:
            parts.append(f"{label}：{'、'.join(dict.fromkeys(texts))}")

    add(_positive_intent_label("偏好专业", constraint_intent_type=constraint_intent_type), major_intents.get("level3"))
    add(_positive_intent_label("偏好专业类", constraint_intent_type=constraint_intent_type), major_intents.get("level2"))
    add(_positive_intent_label("偏好专业门类", constraint_intent_type=constraint_intent_type), major_intents.get("level1"))
    add(_soft_negative_label("排除专业", intent_mode=intent_mode), major_intents.get("negative_level3"))
    add(_soft_negative_label("排除专业类", intent_mode=intent_mode), major_intents.get("negative_level2"))
    add(_soft_negative_label("排除专业门类", intent_mode=intent_mode), major_intents.get("negative_level1"))
    add(_positive_intent_label("偏好院校", constraint_intent_type=constraint_intent_type), school_intents.get("colleges"))
    add(_soft_negative_label("排除院校", intent_mode=intent_mode), school_intents.get("negative_colleges"))
    add(
        _positive_intent_label("偏好地域", constraint_intent_type=constraint_intent_type),
        _as_text_list(city_intents.get("province"))
        + _as_text_list(city_intents.get("city"))
        + _as_text_list(city_intents.get("area")),
    )
    add(
        _soft_negative_label("排除地域", intent_mode=intent_mode),
        _as_text_list(city_intents.get("negative_province"))
        + _as_text_list(city_intents.get("negative_city"))
        + _as_text_list(city_intents.get("negative_area")),
    )
    add(
        _positive_intent_label("发展方向", constraint_intent_type=constraint_intent_type),
        to_career_labels(career_intents.get("positive")) or _as_text_list(career_intents.get("positive")),
    )
    add(
        _soft_negative_label("排除方向", intent_mode=intent_mode),
        to_career_labels(career_intents.get("negative")) or _as_text_list(career_intents.get("negative")),
    )
    min_tuition = _positive_int_from_structured_value(
        tuition_budget.get("min_tuition_per_year") or tuition_budget.get("minTuitionPerYear")
    )
    max_tuition = _positive_int_from_structured_value(
        tuition_budget.get("max_tuition_per_year") or tuition_budget.get("maxTuitionPerYear")
    )
    tuition_parts: list[str] = []
    if min_tuition > 0:
        tuition_parts.append(f"每年不低于 {min_tuition} 元")
    if max_tuition > 0:
        tuition_parts.append(f"每年不超过 {max_tuition} 元")
    if tuition_parts:
        parts.append(f"学费预算：{'，'.join(tuition_parts)}")
    add("避开项目", _as_text_list(physical_constraints.get("special_limits")) + _as_text_list(physical_constraints.get("specialLimits")))
    return "；".join(parts)


_PREFERENCE_STRENGTH_SUMMARY_LABELS = {
    "primary": "优先专业",
    "preferred": "偏好专业",
    "acceptable": "可以考虑专业",
    "must_have": "至少保留专业",
    "only_keep": "只保留专业",
    "exclude_soft": "不优先专业",
    "exclude_hard": "排除专业",
}


def _intent_entity_profile_strength_display_summary(profile: Any, *, batch: str = "01") -> str:
    """Build display text from 3.2.0 profile strength fields.

    Runtime execution still uses selectedData/merged for backend compatibility;
    this helper only preserves the user's visible priority semantics on cards
    and replies.
    """

    preference_strength = _model_value(profile, "preferenceStrength", {}) or {}
    if not isinstance(preference_strength, dict):
        return ""
    major_values = set(_profile_text_values(_model_value(profile, "majorValues", [])))
    if not major_values:
        return ""
    span_major_values: dict[str, set[str]] = {}
    for span in _model_value(profile, "entityPolaritySpans", []) or []:
        if not isinstance(span, dict):
            continue
        if str(span.get("entityType") or "").strip() != "major":
            continue
        strength = str(span.get("strength") or "").strip()
        entity = str(span.get("entity") or "").strip()
        if strength and entity:
            span_major_values.setdefault(strength, set()).add(entity)

    parts: list[str] = []
    for strength in ("primary", "preferred", "acceptable", "must_have", "only_keep", "exclude_soft", "exclude_hard"):
        negative = strength in {"exclude_soft", "exclude_hard"}
        values: list[str] = []
        for value in _profile_text_values(preference_strength.get(strength)):
            if value not in major_values and value not in span_major_values.get(strength, set()):
                continue
            _key, normalized_value = _profile_major_payload_key(value, batch=batch, negative=negative)
            if normalized_value and normalized_value not in values:
                values.append(normalized_value)
        if not values:
            continue
        label = _PREFERENCE_STRENGTH_SUMMARY_LABELS.get(strength, "偏好专业")
        parts.append(f"{label}：{'、'.join(dict.fromkeys(values))}")
    return "；".join(parts)


def _intent_profile_strength_summary_can_cover_merged(merged: dict[str, Any]) -> bool:
    """The strength summary currently only represents major entities."""

    if not isinstance(merged, dict):
        return False
    for key in ("school_intents", "city_intents", "career_intents", "tuition_budget", "physical_constraints", "physicalConstraints"):
        value = merged.get(key)
        if not isinstance(value, dict):
            continue
        if any(_as_text_list(raw_values) for raw_values in value.values()):
            return False
    return True


def _as_text_list(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else [values] if values else []
    return [str(value or "").strip() for value in raw_values if str(value or "").strip()]


def _normalize_school_intent_names(values: Any, batch: str | None = "01") -> list[str]:
    normalized: list[str] = []
    for value in _as_text_list(values):
        try:
            resolved = resolve_school_entity(value, batch)
            name = resolved.best.canonical_name if resolved.best else value
        except Exception:
            name = value
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _merge_intent_preview_item_values(items: list[Any]) -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    for item in items:
        value = getattr(item, "value", None)
        if value is None and isinstance(item, dict):
            value = item.get("value")
        if isinstance(value, dict) and value:
            values.append(value)
    if not values:
        return {}
    try:
        return merge_selected_values(values)
    except Exception:
        return {}


def _positive_intent_payload_subset(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    subset: dict[str, Any] = {}
    for group_key, group_value in payload.items():
        if not isinstance(group_value, dict):
            continue
        positive_group = {
            key: value
            for key, value in group_value.items()
            if not str(key or "").startswith("negative_") and value
        }
        if positive_group:
            subset[group_key] = positive_group
    return subset


def _selected_data_with_existing_positive_context(
    selected_data: dict[str, Any],
    existing_merged: dict[str, Any] | None,
) -> dict[str, Any]:
    existing_positive = _positive_intent_payload_subset(existing_merged)
    if not existing_positive:
        return selected_data
    selected = [
        item
        for item in (selected_data.get("selected") if isinstance(selected_data, dict) else []) or []
        if isinstance(item, dict)
    ]
    if not selected:
        return selected_data
    try:
        selected_merged = merge_selected_values(selected)
    except Exception:
        selected_merged = {}
    if _intent_payload_has_positive_value(selected_merged):
        return selected_data
    augmented = dict(selected_data)
    augmented["selected"] = [*selected, existing_positive]
    augmented.pop("displaySummary", None)
    augmented.pop("display_summary", None)
    return augmented


def _format_intent_card_content(summary: str, *, existing_summary: str = "") -> str:
    lines: list[str] = []
    summary_parts = [part.strip() for part in str(summary or "").split("；") if part.strip()]
    if summary_parts:
        lines.extend(f"- {part}" for part in summary_parts[:3])
        if len(summary_parts) > 3:
            lines.append(f"- 另有 {len(summary_parts) - 3} 条，采纳后会一并作为后续参考")
    existing_parts = [part.strip() for part in str(existing_summary or "").split("；") if part.strip()]
    if existing_parts:
        if lines:
            lines.append("")
        lines.append("当前已有参考：")
        lines.extend(f"- {part}" for part in existing_parts[:3])
        if len(existing_parts) > 3:
            lines.append(f"- 另有 {len(existing_parts) - 3} 条，可在页面顶部“查看意向”里查看")
    return "\n".join(lines).strip() or summary


def _intent_card_primary_reply(
    summary: str,
    *,
    intent_mode: str,
    existing_summary: str = "",
) -> str:
    summary_text = str(summary or "").strip()
    existing_text = str(existing_summary or "").strip()
    if not summary_text and existing_text:
        summary_text = existing_text
    if summary_text:
        title = "已列出这次报考条件预览" if intent_mode == "constraint" else "已列出这次报考想法预览"
        reply = f"{title}：{summary_text}。"
    else:
        reply = "已列出这次待采纳内容。"
    if existing_text and existing_text != summary_text:
        reply += f"\n\n当前已有参考：{existing_text}。"
    reply += "\n\n点“采纳”前不会生效。"
    return _sanitize_reply_for_user(reply)


def _intent_summary_from_item_content(
    items: list[Any],
    *,
    intent_mode: str,
    constraint_intent_type: str,
) -> str:
    if not items:
        return ""
    merged = _merge_intent_preview_item_values(items)
    if not merged:
        return ""
    standard_summary = _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    parts = [part.strip() for part in standard_summary.split("；") if part.strip()]
    if not parts:
        return ""

    def collect_content_values(category: str, key: str) -> list[str]:
        values: list[str] = []
        for item in items:
            raw_item = item.model_dump() if hasattr(item, "model_dump") else item
            if not isinstance(raw_item, dict):
                continue
            value = raw_item.get("value")
            if not isinstance(value, dict):
                continue
            group = value.get(category)
            if not isinstance(group, dict) or not group.get(key):
                continue
            structured_values = _as_text_list(group.get(key))
            content = str(raw_item.get("content") or "").strip()
            if not content:
                for structured_value in structured_values:
                    if structured_value and structured_value not in values:
                        values.append(structured_value)
                continue
            content = re.sub(r"^(把|将)", "", content)
            content = re.split(r"(记成|更新为|设为|从|作为|，|,)", content, maxsplit=1)[0].strip()
            content = re.sub(r"^当前已有参考", "", content).strip()
            content = re.sub(
                r"^(只保留专业门类|只保留专业类|只保留专业|至少保留专业门类|至少保留专业类|至少保留专业|偏好专业门类|偏好专业类|偏好专业|排除专业门类|排除专业类|排除专业|不优先专业门类|不优先专业类|不优先专业)[:：]",
                "",
                content,
            ).strip()
            content_values = [
                item.strip()
                for item in re.split(r"[、/，,]", content)
                if item.strip()
            ]
            if len(structured_values) == 1 and structured_values[0] and structured_values[0] in content:
                candidate_values = [content]
            elif (
                content_values
                and len(content_values) == len(structured_values)
                and set(content_values) == set(structured_values)
            ):
                candidate_values = content_values
            else:
                candidate_values = structured_values
            for content in candidate_values:
                if content and content not in values:
                    values.append(content)
        return values

    replacements = [
        ("只保留专业：", "major_intents", "level3"),
        ("至少保留专业：", "major_intents", "level3"),
        ("偏好专业：", "major_intents", "level3"),
        ("排除专业：", "major_intents", "negative_level3"),
        ("不优先专业：", "major_intents", "negative_level3"),
        ("只保留发展方向：", "career_intents", "positive"),
        ("至少保留发展方向：", "career_intents", "positive"),
        ("发展方向：", "career_intents", "positive"),
        ("排除方向：", "career_intents", "negative"),
        ("不优先发展方向：", "career_intents", "negative"),
    ]
    rewritten: list[str] = []
    for part in parts:
        replacement = ""
        for prefix, category, key in replacements:
            if part.startswith(prefix):
                values = collect_content_values(category, key)
                if values:
                    replacement = f"{prefix}{'、'.join(values)}"
                break
        rewritten.append(replacement or part)
    return "；".join(rewritten)


def _display_summary_from_intent_payload(intent_payload: dict[str, Any] | None) -> str:
    if not isinstance(intent_payload, dict):
        return ""
    for key in ("displaySummary", "display_summary"):
        value = str(intent_payload.get(key) or "").strip()
        if value:
            return _sanitize_reply_for_user(value)
    return ""


def _intent_card_primary_reply_from_preview_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return _intent_card_primary_reply("", intent_mode="preference", existing_summary="")
    intent_mode = str(payload.get("intentMode") or "preference").strip() or "preference"
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_intent_type = str(
        payload.get("constraintIntentType")
        or payload.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    items = list(payload.get("items") or [])
    existing_items = list(payload.get("existingItems") or [])
    selected_summary = _intent_summary_from_item_content(
        items,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(
        _merge_intent_preview_item_values(items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    existing_summary = _intent_summary_from_item_content(
        existing_items,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(
        _merge_intent_preview_item_values(existing_items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    return _intent_card_primary_reply(
        selected_summary or str(payload.get("summary") or payload.get("title") or "").strip(),
        intent_mode=intent_mode,
        existing_summary=existing_summary,
    )


def _intent_card_primary_reply_from_card(card: WSResponse | None) -> str:
    if not isinstance(card, WSResponse):
        return ""
    payload = _parse_tool_return_json(str(getattr(card, "content", "") or ""))
    if not isinstance(payload, dict):
        return ""
    return _intent_card_primary_reply_from_preview_payload(payload)


def _pending_confirmation_primary_reply_from_card(card: WSResponse | None) -> str:
    if not isinstance(card, WSResponse):
        return ""
    payload = _parse_tool_return_json(str(getattr(card, "content", "") or ""))
    if not isinstance(payload, dict):
        return ""
    kind = str(payload.get("kind") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    if kind == "plan_mutation":
        title = str(payload.get("title") or "调整预览").strip()
        lead = "已列出调整预览。"
        if title and not title.startswith("确认"):
            lead = f"已列出{title}。"
        lines = [lead]
        if summary:
            lines.extend(["", summary])
        lines.extend(["", "确认前不会改动当前方案；点“确认执行”后才会按这次预览处理。"])
        return _sanitize_reply_for_user("\n".join(lines))
    if kind == "intent_change":
        return _intent_card_primary_reply_from_card(card)
    return ""


def _semantic_intent_decision_suggests_readonly(decision: dict[str, Any] | None) -> bool:
    if not isinstance(decision, dict):
        return False
    return (
        str(decision.get("decision") or "").strip() in {"analysis_only", "mixed_answer_then_ask"}
        and float(decision.get("confidence") or 0.0) >= 0.7
    )


def _semantic_intent_decision_requires_readonly(decision: dict[str, Any] | None) -> bool:
    if not _semantic_intent_decision_suggests_readonly(decision):
        return False
    if isinstance(decision, dict) and decision.get("honored") is False:
        return False
    return True


def _normalize_admission_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text).lower()
    if compact in {"strongbase", "strong_base", "strong-base"} or "强基" in text:
        return "strongbase"
    if compact in {"comprehensive", "comprehensive_evaluation", "综合评价", "综评"} or "综评" in text or "综合评价" in text:
        return "comprehensive_evaluation"
    if "专项" in text:
        return "special_program"
    return text


def _admission_path_display(value: Any) -> str:
    normalized = _normalize_admission_path(value)
    if normalized == "strongbase":
        return "强基路径"
    if normalized == "comprehensive_evaluation":
        return "综评路径"
    if normalized == "special_program":
        return "专项路径"
    return normalized


def _intent_preview_payload_entity_kinds(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    merged = _merge_intent_preview_item_values([item for item in items if isinstance(item, dict)])
    kinds: set[str] = set()
    if isinstance(merged.get("major_intents"), dict) and merged.get("major_intents"):
        kinds.add("major")
    if isinstance(merged.get("school_intents"), dict) and merged.get("school_intents"):
        kinds.add("school")
    if isinstance(merged.get("city_intents"), dict) and merged.get("city_intents"):
        kinds.add("region")
    if isinstance(merged.get("career_intents"), dict) and merged.get("career_intents"):
        kinds.add("career")
    if _normalize_admission_path(payload.get("admissionPath") or payload.get("admission_path")):
        kinds.add("admission_path")
    return kinds


def _semantic_intent_decision_entity_kinds(decision: dict[str, Any] | None) -> set[str]:
    if not _semantic_decision_requests_intent_preview(decision):
        return set()
    kinds: set[str] = set()
    for span in decision.get("entityPolaritySpans") or []:
        if not isinstance(span, dict):
            continue
        entity_type = str(span.get("entityType") or "").strip()
        if entity_type in {"major", "school", "region", "career"}:
            kinds.add(entity_type)
        elif entity_type in {"admissionPath", "admission_path", "path"}:
            kinds.add("admission_path")
    if _normalize_admission_path(decision.get("admissionPath") or decision.get("admission_path")):
        kinds.add("admission_path")
    return kinds


def _intent_preview_payload_mismatches_semantic_decision(
    payload: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> bool:
    decision_kinds = _semantic_intent_decision_entity_kinds(decision)
    if not decision_kinds:
        return False
    payload_kinds = _intent_preview_payload_entity_kinds(payload)
    return not decision_kinds.issubset(payload_kinds)


def _compile_full_agent_intent_preview_turn_decision_arbitration(
    *,
    turn_decision: Any | None,
    semantic_decision: dict[str, Any] | None,
    preview_payload: dict[str, Any] | None,
):
    candidate = _intent_preview_candidate_from_payload(
        "__turn_decision_arbitration__",
        preview_payload,
    )
    return proposal_compiler.compile_runtime_intent_preview_turn_decision_arbitration_source(
        turn_decision=turn_decision,
        turn_decision_blocks_intent_pending=_turn_decision_blocks_runtime_intent_hard_cut(turn_decision),
        semantic_intent_preview_requested=_semantic_decision_requests_intent_preview(semantic_decision),
        semantic_entity_kinds=_semantic_intent_decision_entity_kinds(semantic_decision),
        preview_payload_entity_kinds=_intent_preview_payload_entity_kinds(preview_payload),
        preview_candidate_valid=candidate is not None,
        constraint_intent_type=str((preview_payload or {}).get("constraintIntentType") or ""),
    )


def _intent_preview_payload_from_semantic_decision(
    session_id: str,
    decision: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _semantic_decision_requests_intent_preview(decision):
        return None
    constraint_intent_type = str(decision.get("constraintIntentType") or "default").strip() or "default"
    intent_mode = "constraint" if constraint_intent_type in {"only_keep", "must_have"} else "preference"
    major_values: list[str] = []
    school_values: list[str] = []
    region_values: list[str] = []
    career_values: list[str] = []
    negative_major_values: list[str] = []
    negative_school_values: list[str] = []
    negative_region_values: list[str] = []
    negative_career_values: list[str] = []

    for span in decision.get("entityPolaritySpans") or []:
        if not isinstance(span, dict):
            continue
        entity = str(span.get("entity") or "").strip()
        if not entity:
            continue
        entity_type = str(span.get("entityType") or "").strip()
        polarity = str(span.get("polarity") or "").strip()
        strength = str(span.get("strength") or "").strip()
        negative = polarity == "negative" or strength in {"exclude_soft", "exclude_hard"}
        if entity_type == "major":
            (negative_major_values if negative else major_values).append(entity)
        elif entity_type == "school":
            (negative_school_values if negative else school_values).append(entity)
        elif entity_type == "region":
            (negative_region_values if negative else region_values).append(entity)
        elif entity_type == "career":
            (negative_career_values if negative else career_values).append(entity)

    def _dedupe(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    major_values = _dedupe(major_values)
    school_values = _dedupe(_normalize_school_intent_names(_dedupe(school_values)))
    region_values = _dedupe(region_values)
    career_values = _dedupe(career_values)
    negative_major_values = _dedupe(negative_major_values)
    negative_school_values = _dedupe(_normalize_school_intent_names(_dedupe(negative_school_values)))
    negative_region_values = _dedupe(negative_region_values)
    negative_career_values = _dedupe(negative_career_values)

    items: list[dict[str, Any]] = []
    if major_values:
        items.append({"content": f"偏好专业：{'、'.join(major_values)}", "selected": True, "value": {"major_intents": {"level3": major_values}}})
    if negative_major_values:
        items.append({"content": f"排除专业：{'、'.join(negative_major_values)}", "selected": True, "value": {"major_intents": {"negative_level3": negative_major_values}}})
    if school_values:
        items.append({"content": f"偏好院校：{'、'.join(school_values)}", "selected": True, "value": {"school_intents": {"colleges": school_values}}})
    if negative_school_values:
        items.append({"content": f"排除院校：{'、'.join(negative_school_values)}", "selected": True, "value": {"school_intents": {"negative_colleges": negative_school_values}}})
    if region_values:
        items.append({"content": f"偏好地域：{'、'.join(region_values)}", "selected": True, "value": {"city_intents": {"area": region_values}}})
    if negative_region_values:
        items.append({"content": f"排除地域：{'、'.join(negative_region_values)}", "selected": True, "value": {"city_intents": {"negative_area": negative_region_values}}})
    if career_values:
        items.append({"content": f"发展方向：{'、'.join(career_values)}", "selected": True, "value": {"career_intents": {"positive": career_values}}})
    if negative_career_values:
        items.append({"content": f"排除方向：{'、'.join(negative_career_values)}", "selected": True, "value": {"career_intents": {"negative": negative_career_values}}})
    admission_path = _normalize_admission_path(decision.get("admissionPath") or decision.get("admission_path"))
    if not items and not admission_path:
        return None
    summary_parts: list[str] = []
    if items:
        try:
            merged = merge_selected_values([item["value"] for item in items if isinstance(item.get("value"), dict)])
        except Exception:
            merged = {}
        summary = _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        if summary:
            summary_parts.append(summary)
    path_display = _admission_path_display(admission_path)
    if path_display:
        summary_parts.append(path_display)
    return {
        "status": "ready",
        "sessionId": session_id,
        "title": "确认这条报考想法",
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "analysisStage": "confirmed",
        "items": items,
        "existingItems": [],
        "admissionPath": admission_path,
        "message": "；".join(summary_parts),
    }


def _align_intent_preview_payload_with_semantic_decision(
    *,
    session_id: str,
    payload: dict[str, Any] | None,
    semantic_decision: dict[str, Any] | None,
    observability: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _intent_preview_payload_mismatches_semantic_decision(payload, semantic_decision):
        return payload
    semantic_payload = _intent_preview_payload_from_semantic_decision(
        session_id,
        semantic_decision,
    )
    if semantic_payload is None:
        return payload
    if isinstance(observability, dict):
        observability["latestIntentPreviewPayload"] = semantic_payload
        observability["intentPreviewPayloadSource"] = "semantic_side_effect_decision"
    return semantic_payload


def _merge_selected_intent_payload(intent_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    selected = intent_payload.get("selected")
    if not isinstance(selected, list) or not selected:
        return {}
    try:
        return merge_selected_values([item for item in selected if isinstance(item, dict)])
    except Exception:
        logger.warning("Failed to merge selected intent payload for card content", exc_info=True)
        return {}


def _summarize_selected_intent_payload(intent_payload: dict[str, Any] | None) -> str:
    display_summary = _display_summary_from_intent_payload(intent_payload)
    if display_summary:
        return display_summary
    merged = _merge_selected_intent_payload(intent_payload)
    if not merged:
        return ""
    intent_mode = str((intent_payload or {}).get("intentMode") or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    constraint_intent_type = str(
        (intent_payload or {}).get("constraintIntentType")
        or (intent_payload or {}).get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    return _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )


def _format_plan_card_intent_impact(intent_payload: dict[str, Any] | None) -> str:
    merged = _merge_selected_intent_payload(intent_payload)
    base = "确认前不会改动当前方案。"
    if not merged:
        return base
    intent_mode = str((intent_payload or {}).get("intentMode") or "preference").strip()
    has_positive = _intent_payload_has_positive_value(merged)
    has_negative = _intent_payload_has_negative_value(merged)
    if intent_mode == "constraint" and has_positive and has_negative:
        return f"{base}确认后会执行本次调整；优先方向会作为后续推荐参考，避开的方向会用于后续检查。"
    if intent_mode == "constraint" and has_negative:
        return f"{base}确认后会执行本次调整，并把这条避开条件作为后续参考。"
    if intent_mode == "constraint" and has_positive:
        return f"{base}确认后会执行本次调整，并把这条保留条件作为后续参考。"
    if has_positive and has_negative:
        return f"{base}确认后会执行本次调整；优先方向会作为后续推荐参考，不优先方向会适当靠后。"
    if has_positive or has_negative:
        return f"{base}确认后会执行本次调整，并同步后续报考参考。"
    return base


def _intent_payload_has_any_value(payload: dict[str, Any] | None, paths: list[tuple[str, str]]) -> bool:
    if not isinstance(payload, dict):
        return False
    for group_key, value_key in paths:
        group = payload.get(group_key)
        if not isinstance(group, dict):
            continue
        if _as_text_list(group.get(value_key)):
            return True
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get("selected") is False:
                continue
            value = item.get("value")
            if isinstance(value, dict) and _intent_payload_has_any_value(value, paths):
                return True
    return False


def _intent_payload_has_positive_value(payload: dict[str, Any] | None) -> bool:
    paths = [
        ("major_intents", "level3"),
        ("major_intents", "level2"),
        ("major_intents", "level1"),
        ("school_intents", "colleges"),
        ("city_intents", "province"),
        ("city_intents", "city"),
        ("city_intents", "area"),
        ("career_intents", "positive"),
    ]
    return _intent_payload_has_any_value(payload, paths)


def _intent_payload_has_negative_value(payload: dict[str, Any] | None) -> bool:
    paths = [
        ("major_intents", "negative_level3"),
        ("major_intents", "negative_level2"),
        ("major_intents", "negative_level1"),
        ("major_intents", "negative"),
        ("school_intents", "negative_colleges"),
        ("city_intents", "negative_province"),
        ("city_intents", "negative_city"),
        ("city_intents", "negative_area"),
        ("career_intents", "negative"),
        ("physical_constraints", "special_limits"),
        ("physicalConstraints", "specialLimits"),
    ]
    return _intent_payload_has_any_value(payload, paths)


def _constraint_payload_has_required_scope(
    merged: dict[str, Any] | None,
    *,
    constraint_intent_type: str,
) -> bool:
    return proposal_compiler.intent_payload_has_required_constraint_scope(
        merged,
        constraint_intent_type=constraint_intent_type,
    )


def _intent_preview_missing_required_constraint_scope(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        preview = parse_intent_analysis_payload(
            json.dumps(_normalize_intent_preview_payload_for_parse(payload), ensure_ascii=False)
        )
    except Exception:
        return False
    raw_constraint_type = str(getattr(preview, "constraintIntentType", "") or "").strip()
    if raw_constraint_type not in {"only_keep", "must_have"}:
        return False
    selected_values = [
        item.value
        for item in preview.items
        if item.selected and isinstance(item.value, dict) and item.value
    ]
    if not selected_values and preview.status != "existing_only":
        return True
    if not selected_values:
        selected_values = [
            item.value
            for item in preview.existingItems
            if isinstance(item.value, dict) and item.value
        ]
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        return True
    return not _intent_payload_has_positive_value(merged)


def _intent_preview_incomplete_constraint_reply(payload: dict[str, Any] | None) -> str:
    constraint_type = ""
    if isinstance(payload, dict):
        constraint_type = str(payload.get("constraintIntentType") or payload.get("constraint_intent_type") or "").strip()
    if constraint_type == "must_have":
        return "我理解你是想让方案里至少保留某个方向，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"
    return "我理解你是想把后续范围收紧，但这次没有稳定识别出具体要保留的专业、院校或地域。请直接补充要保留的范围，我再给你列出可采纳内容。"


def _intent_confirmation_mechanism_line(
    intent_mode: str,
    payload: dict[str, Any] | None = None,
) -> str:
    has_positive = _intent_payload_has_positive_value(payload)
    has_negative = _intent_payload_has_negative_value(payload)
    constraint_intent_type = str((payload or {}).get("constraintIntentType") or (payload or {}).get("constraint_intent_type") or "default").strip()
    if constraint_intent_type in {"only_keep", "must_have"}:
        intent_mode = "constraint"
    if intent_mode == "constraint" and constraint_intent_type == "only_keep":
        return "采纳后只保留这个范围；方案需要改动时会先给你看预览。"
    if intent_mode == "constraint" and constraint_intent_type == "must_have":
        return "采纳后至少保留这个方向；方案需要补入时会先给你看预览。"
    if intent_mode == "constraint" and has_positive and has_negative:
        return "采纳后优先方向会排得更靠前，避开的方向会用于后续检查。"
    if intent_mode == "constraint" and has_positive:
        return "采纳后会优先满足这些方向，并用于后续检查。"
    if intent_mode == "constraint" and has_negative:
        return "采纳后会避开这些方向，并用于后续检查。"
    if intent_mode == "constraint":
        return "采纳后会作为后续推荐和方案检查依据。"
    if has_positive and has_negative:
        return "采纳后优先方向会排得更靠前，不优先方向会适当靠后。"
    if has_positive:
        return "采纳后这些方向会排得更靠前。"
    if has_negative:
        return "采纳后这些方向会适当靠后。"
    return "采纳后会作为后续推荐参考。"


def _format_intent_card_impact(
    payload: dict[str, Any] | None,
    *,
    intent_mode: str,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
) -> str:
    analysis = payload.get("impactAnalysis") if isinstance(payload, dict) else None
    impact_lines = compact_relation_impact_lines(
        analysis if isinstance(analysis, dict) else None,
        intent_mode=intent_mode,
        limit=2,
    )
    mechanism_line = str(fallback_mechanism_line or _intent_confirmation_mechanism_line(intent_mode, payload)).strip()
    lines = [mechanism_line] if mechanism_line else []
    detail_lines = fallback_detail_lines if fallback_detail_lines else impact_lines
    lines.extend(line for line in detail_lines if line and line not in lines)
    return "\n".join(f"- {line}" for line in lines[:2])


def _build_intent_pending_state(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
    replaced_pending: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "intent_change",
        "status": "active",
        "actionFamily": "apply_selected_intents",
        "summary": summary,
        "executionPayload": {
            "toolName": "apply_selected_intents",
            "selectedData": selected_data,
            "merged": merged,
            "intentMode": intent_mode,
            "constraintIntentType": constraint_intent_type,
            "batch": batch,
        },
        "createdAt": now,
        "updatedAt": now,
    }
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if compiled_proposal_id:
        state["compiledProposalId"] = compiled_proposal_id
        state["compilerSink"] = {
            "compiledProposalId": compiled_proposal_id,
            "sinkType": str(compiled_sink_metadata.get("sinkType") or "intent").strip() or "intent",
        }
        state["executionPayload"]["compiledProposalId"] = compiled_proposal_id
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    if constraint_intent_type and constraint_intent_type != "default":
        state["constraintIntentType"] = constraint_intent_type
    if intent_mode == "constraint":
        composite_proposal = _build_constraint_composite_proposal_payload(
            {},
            merged=merged,
            selected_data=selected_data,
            constraint_intent_type=constraint_intent_type,
            batch=batch,
            summary=summary,
        )
        if isinstance(composite_proposal, dict):
            state["compositeProposal"] = composite_proposal
    return state

def _major_values_from_positive_intents(major_intents: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("level3", "level2", "level1"):
        for value in _as_text_list(major_intents.get(key)):
            if value and value not in values:
                values.append(value)
    return values


def _scope_payload(entity_type: str, values: list[str], *, scope_level: str | None = None) -> dict[str, Any] | None:
    deduped = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if not deduped:
        return None
    payload: dict[str, Any] = {"entity_type": entity_type, "values": deduped}
    if scope_level:
        payload["scope_level"] = scope_level
    return payload


def _positive_goal_scopes_from_intents(merged: dict[str, Any], batch: str | None = "01") -> list[dict[str, Any]]:
    raw_major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    major_intents = _remove_positive_major_targets_excluded_by_negative_scope(
        raw_major_intents,
        batch=batch or "01",
    ) or {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    scopes: list[dict[str, Any]] = []
    major_scope = _scope_payload("major", _major_values_from_positive_intents(major_intents))
    school_scope = _scope_payload("school", _normalize_school_intent_names(school_intents.get("colleges"), batch))
    region_province_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("province"), expected_level="province"),
        scope_level="province",
    )
    region_city_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("city"), expected_level="city"),
        scope_level="city",
    )
    region_area_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("area"), expected_level="area"),
        scope_level="area",
    )
    for scope in (major_scope, school_scope, region_province_scope, region_city_scope, region_area_scope):
        if scope is not None:
            scopes.append(scope)
    return scopes


def _negative_goal_scopes_from_intents(merged: dict[str, Any], batch: str | None = "01") -> list[dict[str, Any]]:
    major_intents = merged.get("major_intents") if isinstance(merged.get("major_intents"), dict) else {}
    school_intents = merged.get("school_intents") if isinstance(merged.get("school_intents"), dict) else {}
    city_intents = merged.get("city_intents") if isinstance(merged.get("city_intents"), dict) else {}
    scopes: list[dict[str, Any]] = []
    major_scope = _scope_payload(
        "major",
        _as_text_list(major_intents.get("negative_level3"))
        + _as_text_list(major_intents.get("negative_level2"))
        + _as_text_list(major_intents.get("negative_level1")),
    )
    school_scope = _scope_payload("school", _normalize_school_intent_names(school_intents.get("negative_colleges"), batch))
    region_province_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_province"), expected_level="province"),
        scope_level="province",
    )
    region_city_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_city"), expected_level="city"),
        scope_level="city",
    )
    region_area_scope = _scope_payload(
        "region",
        normalize_region_names(city_intents.get("negative_area"), expected_level="area"),
        scope_level="area",
    )
    for scope in (major_scope, school_scope, region_province_scope, region_city_scope, region_area_scope):
        if scope is not None:
            scopes.append(scope)
    return scopes


def _constraint_goal_type(constraint_intent_type: str) -> str:
    return proposal_compiler.structured_goal_type_from_constraint_intent_type(constraint_intent_type)


@dataclass
class _UserGoalFixConfirmationAttempt:
    fallback_to_intent: bool = False
    blocked_by_compiled_contract: bool = False
    fallback_mechanism_line: str = ""
    fallback_detail_lines: list[str] = field(default_factory=list)


@dataclass
class _UserGoalFixCandidate:
    proposal: dict[str, Any]
    source_version_guard: int
    user_goal_request: dict[str, Any]
    intent_payload: dict[str, Any] | None
    summary: str


@dataclass
class _IntentPreviewCandidate:
    payload: dict[str, Any]
    preview: Any
    selected_values: list[dict[str, Any]]
    merged: dict[str, Any]
    intent_mode: str
    constraint_intent_type: str
    existing_merged: dict[str, Any]
    selected_display_summary: str
    existing_summary: str
    summary: str


@dataclass
class _StructuredGoalIntentCandidate:
    selected_data: dict[str, Any]
    merged: dict[str, Any]
    intent_mode: str
    batch: str
    fallback_mechanism_line: str = ""
    fallback_detail_lines: list[str] = field(default_factory=list)


@dataclass
class _RuntimeCompiledPendingResult:
    card: WSResponse | None = None
    primary_reply: str = ""
    source: str = ""
    plan_includes_intent_update: bool = False
    workspace_refresh_targets: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)


def _compiled_workspace_refresh_targets(
    compiled: dict[str, Any] | None,
    *,
    fallback_targets: list[str] | None = None,
) -> list[str]:
    if not isinstance(compiled, dict):
        return _dedupe_workspace_targets(fallback_targets or [])
    raw_targets = compiled.get("workspaceRefreshTargets") or compiled.get("workspace_refresh_targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        execution_payload = compiled.get("executionPayload")
        if isinstance(execution_payload, dict):
            target = str(execution_payload.get("targetView") or "").strip()
            raw_targets = [target] if target else []
        else:
            raw_targets = []
    targets = _dedupe_workspace_targets(str(target) for target in raw_targets)
    if targets:
        return targets
    return _dedupe_workspace_targets(fallback_targets or [])


def _constraint_plan_confirmation_fallback(
    proposal: dict[str, Any] | None,
    *,
    constraint_intent_type: str,
) -> tuple[str, list[str]]:
    if not isinstance(proposal, dict):
        return "", []
    status = str(proposal.get("status") or "").strip()
    summary = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip())
    )
    impact = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("impact") or "").strip())
    )
    blocking_reason = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(
            str(proposal.get("blockingReason") or proposal.get("blocking_reason") or "").strip()
        )
    )
    if status == "info":
        mechanism_line = "采纳后先把这条条件记下来；当前方案已经符合这个方向，不需要立刻改动。"
        detail_lines = [summary or impact or "当前方案暂时不需要为了这条条件调整。"]
    else:
        mechanism_line = "采纳后先把这条条件记下来；当前没有可直接执行的方案调整。"
        detail_lines = [summary or blocking_reason or impact or "这次先记录条件，后续可以放宽范围后再让我重试。"]
    if constraint_intent_type == "only_keep":
        detail_lines.append("如果之后找到相关志愿，我会先给你调整预览，再由你确认。")
    elif constraint_intent_type == "must_have":
        detail_lines.append("如果之后补到相关志愿，我会先给你补入预览，再由你确认。")
    else:
        detail_lines.append("如果后面能明确要避开的范围，我会先给你调整预览，再由你确认。")
    return mechanism_line, [line for line in detail_lines if str(line or "").strip()]


def _build_constraint_composite_proposal_payload(
    plan_payload: dict[str, Any],
    *,
    merged: dict[str, Any],
    selected_data: dict[str, Any],
    constraint_intent_type: str,
    batch: str,
    summary: str,
) -> dict[str, Any] | None:
    goal_type = _constraint_goal_type(constraint_intent_type)
    target_scopes = _positive_goal_scopes_from_intents(merged, batch) if goal_type in {"only_keep_scope", "must_include_scope"} else []
    negative_scopes = _negative_goal_scopes_from_intents(merged, batch) if goal_type == "exclude_scope" else []
    if not target_scopes and not negative_scopes:
        return None

    goal = PlanGoal(
        goal_type=goal_type,  # type: ignore[arg-type]
        user_original_text=summary,
        target_scopes=target_scopes,
        negative_scopes=negative_scopes,
        confidence="high",
    )
    intent_update: dict[str, Any] = {
        "intentMode": "constraint",
        "constraintIntentType": constraint_intent_type,
    }
    if target_scopes:
        intent_update["targetScopes"] = target_scopes
    if negative_scopes:
        intent_update["negativeScopes"] = negative_scopes

    proposal = CompositePlanProposal(
        source_version=_as_int(plan_payload.get("planning_version")),
        goal=goal,
        intent_updates=[intent_update],
        plan_actions=[],
        decision_references=[],
        feasibility="ready",
        impact_summary=[str(plan_payload.get("preview_summary") or summary).strip()],
        requires_confirmation=True,
        post_apply_validation_plan=[
            "执行后重新读取当前方案",
            "执行后重新审查风险和提醒",
        ],
    )
    return proposal.model_dump()


async def _constraint_user_goal_fix_candidate_from_preview(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    batch: str,
    summary: str,
    constraint_intent_type: str = "default",
    attempt: _UserGoalFixConfirmationAttempt | None = None,
) -> _UserGoalFixCandidate | None:
    composite_proposal = _build_constraint_composite_proposal_payload(
        {},
        merged=merged,
        selected_data=selected_data,
        constraint_intent_type=constraint_intent_type,
        batch=batch,
        summary=summary,
    )
    if not isinstance(composite_proposal, dict):
        return None
    planning_version = _as_int(composite_proposal.get("source_version"))
    if planning_version <= 0:
        try:
            state_resp = await get_planning_state(session_id)
            planning_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
        except Exception:
            logger.warning("Failed to load planning state for user-goal proposal: session_id=%s", session_id, exc_info=True)
            planning_version = 0
    if planning_version <= 0:
        return None
    user_goal_request = proposal_compiler.build_structured_user_goal_fix_proposal_request(
        composite_proposal.get("goal") if isinstance(composite_proposal.get("goal"), dict) else {},
        planning_version,
        context={"source": "chat_service_constraint_confirmation"},
        evidence_source="confirmed_intent",
    )
    if not user_goal_request:
        return None
    try:
        proposal_result = await generate_user_goal_planning_fix_proposals(1, session_id, user_goal_request)
    except Exception:
        logger.warning(
            "Failed to generate user-goal plan proposal: session_id=%s summary=%s",
            session_id,
            summary,
            exc_info=True,
        )
        return None
    if proposal_result.get("code") != 0:
        return None
    data = proposal_result.get("data")
    if not isinstance(data, dict):
        return None
    selection = proposal_compiler.select_user_goal_fix_proposal(
        data,
        goal_type=_constraint_goal_type(constraint_intent_type),
        fallback_source_version_guard=planning_version,
    )
    if not isinstance(selection.proposal, dict):
        if attempt is not None:
            attempt.fallback_to_intent = selection.fallback_proposal is not None
            attempt.fallback_mechanism_line, attempt.fallback_detail_lines = _constraint_plan_confirmation_fallback(
                selection.fallback_proposal,
                constraint_intent_type=constraint_intent_type,
            )
        return None
    return _UserGoalFixCandidate(
        proposal=selection.proposal,
        source_version_guard=selection.source_version_guard,
        user_goal_request=user_goal_request,
        intent_payload=selected_data,
        summary=summary,
    )


async def _create_pending_fix_confirmation_result_from_user_goal_candidate(
    session_id: str,
    candidate: _UserGoalFixCandidate,
    *,
    attempt: _UserGoalFixConfirmationAttempt | None = None,
) -> _RuntimeCompiledPendingResult:
    compiled = proposal_compiler.compile_user_goal_fix_proposal(
        session_id=session_id,
        proposal=candidate.proposal,
        source_version_guard=candidate.source_version_guard,
        user_goal_request=candidate.user_goal_request,
        intent_payload=candidate.intent_payload,
        summary=candidate.summary,
    )
    contract_ok, contract_reasons = proposal_compiler.fix_proposal_sink_contract(compiled)
    if not contract_ok:
        if attempt is not None:
            attempt.blocked_by_compiled_contract = True
        logger.info(
            "Block user-goal fix pending before sink: session_id=%s reasons=%s proposal_id=%s",
            session_id,
            contract_reasons,
            proposal_compiler.proposal_id(candidate.proposal),
        )
        return _RuntimeCompiledPendingResult(
            source="user_goal_fix_proposal",
            blocked_reasons=["compiled_fix_sink_blocked", *contract_reasons],
        )
    compiled_sink_metadata = {
        "compiledProposalId": compiled["compiledProposalId"],
        "sinkType": "fix_proposal",
    }
    card = await _create_pending_fix_proposal_confirmation_response(
        session_id,
        candidate.proposal,
        source_version_guard=candidate.source_version_guard,
        proposal_source="user_goal",
        user_goal_request=candidate.user_goal_request,
        intent_payload=candidate.intent_payload,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    if card is None:
        return _RuntimeCompiledPendingResult(
            source="user_goal_fix_proposal",
            blocked_reasons=["compiled_fix_pending_sink_returned_empty"],
        )
    return _RuntimeCompiledPendingResult(
        card=card,
        source="user_goal_fix_proposal",
        workspace_refresh_targets=_compiled_workspace_refresh_targets(
            compiled,
            fallback_targets=["ordered"],
        ),
    )


def _merge_existing_intent_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        preview = parse_intent_analysis_payload(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return {}
    return _merge_intent_preview_item_values(list(preview.existingItems))


async def _structured_user_goal_fix_candidate_from_source(
    session_id: str,
    source: dict[str, Any] | None,
    *,
    context_source: str,
    intent_payload_override: dict[str, Any] | None = None,
    attempt: _UserGoalFixConfirmationAttempt | None = None,
) -> _UserGoalFixCandidate | None:
    compiled_request = proposal_compiler.compile_structured_user_goal_fix_request_source(
        source=source,
        context_source=context_source,
        intent_payload_override=intent_payload_override,
    )
    planning_version = compiled_request.source_version_guard
    if planning_version <= 0:
        try:
            state_resp = await get_planning_state(session_id)
            planning_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
        except Exception:
            logger.warning(
                "Failed to load planning state for structured user-goal proposal: session_id=%s",
                session_id,
                exc_info=True,
            )
            planning_version = 0
        if planning_version > 0 and isinstance(compiled_request.goal, dict):
            compiled_request = proposal_compiler.compile_structured_user_goal_fix_request_source(
                source=source,
                planning_version=planning_version,
                context_source=context_source,
                intent_payload_override=intent_payload_override,
            )
    if not compiled_request.matched:
        logger.info(
            "Skip structured user-goal proposal before Java preview: session_id=%s reasons=%s",
            session_id,
            compiled_request.blocking_reasons,
        )
        return None
    user_goal_request = compiled_request.user_goal_request
    try:
        proposal_result = await generate_user_goal_planning_fix_proposals(1, session_id, user_goal_request)
    except Exception:
        logger.warning(
            "Failed to generate structured user-goal plan proposal: session_id=%s goal_type=%s",
            session_id,
            user_goal_request.get("goalType"),
            exc_info=True,
        )
        return None
    if proposal_result.get("code") != 0:
        return None
    data = proposal_result.get("data")
    if not isinstance(data, dict):
        return None
    selection = proposal_compiler.select_user_goal_fix_proposal(
        data,
        goal_type=str(user_goal_request.get("goalType") or "").strip(),
        fallback_source_version_guard=planning_version,
    )
    if not isinstance(selection.proposal, dict):
        if attempt is not None:
            fallback_intent_payload = (
                intent_payload_override
                or proposal_compiler.structured_intent_payload_from_composite_proposal(source)
                or {}
            )
            fallback_constraint_type = str(
                fallback_intent_payload.get("constraintIntentType")
                or fallback_intent_payload.get("constraint_intent_type")
                or "default"
            ).strip() or "default"
            attempt.fallback_to_intent = True
            attempt.fallback_mechanism_line, attempt.fallback_detail_lines = _constraint_plan_confirmation_fallback(
                selection.fallback_proposal,
                constraint_intent_type=fallback_constraint_type,
            )
        return None
    intent_payload = (
        compiled_request.intent_payload
        or intent_payload_override
        or proposal_compiler.structured_intent_payload_from_composite_proposal(source)
    )
    summary = _summarize_selected_intent_payload(intent_payload)
    if not summary:
        summary = str(
            selection.proposal.get("summary")
            or selection.proposal.get("title")
            or compiled_request.summary_hint
            or ""
        ).strip()
    return _UserGoalFixCandidate(
        proposal=selection.proposal,
        source_version_guard=selection.source_version_guard,
        user_goal_request=user_goal_request,
        intent_payload=intent_payload,
        summary=summary,
    )


async def _structured_goal_intent_candidate_from_source(
    session_id: str,
    source: dict[str, Any] | None,
    *,
    intent_payload_override: dict[str, Any] | None = None,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
) -> _StructuredGoalIntentCandidate | None:
    compiled_input = proposal_compiler.compile_structured_goal_intent_input_source(
        source=source,
        intent_payload_override=intent_payload_override,
    )
    intent_payload = compiled_input.intent_payload
    if not isinstance(intent_payload, dict):
        return None
    selected_values = compiled_input.selected_values
    if not selected_values:
        logger.info(
            "Skip structured goal intent fallback before merge: session_id=%s reasons=%s",
            session_id,
            compiled_input.blocking_reasons,
        )
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning(
            "Failed to merge structured goal intent fallback: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not merged:
        return None
    intent_resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=selected_values,
        merged=merged,
        intent_mode=compiled_input.intent_mode,
        raw_constraint_intent_type=compiled_input.raw_constraint_intent_type,
    )
    if not intent_resolution.allowed:
        logger.info(
            "Skip structured goal intent fallback before compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
            session_id,
            compiled_input.raw_constraint_intent_type,
            intent_resolution.blocking_reasons,
            merged,
        )
        return None
    intent_mode = intent_resolution.intent_mode
    constraint_intent_type = intent_resolution.constraint_intent_type
    selected_data = {
        **intent_payload,
        "selected": selected_values,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
    }
    batch = await _resolve_session_batch(session_id)
    return _StructuredGoalIntentCandidate(
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        fallback_mechanism_line=fallback_mechanism_line,
        fallback_detail_lines=list(fallback_detail_lines or []),
    )


async def _create_pending_intent_confirmation_from_structured_goal_candidate(
    session_id: str,
    candidate: _StructuredGoalIntentCandidate,
) -> WSResponse | None:
    constraint_intent_type = str(
        candidate.selected_data.get("constraintIntentType")
        or candidate.selected_data.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    summary = _display_summary_from_intent_payload(candidate.selected_data) or _summarize_intent_values(
        candidate.merged,
        intent_mode=candidate.intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    if not summary:
        summary = "本次选择的要求内容。" if candidate.intent_mode == "constraint" else "本次选择的偏好内容。"
    compiled = proposal_compiler.compile_intent_preview_proposal(
        session_id=session_id,
        selected_data=candidate.selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=candidate.batch,
        constraint_intent_type=constraint_intent_type,
        summary=summary,
    )
    contract_ok, contract_reasons = proposal_compiler.intent_sink_contract(compiled)
    if not contract_ok:
        logger.info(
            "Block structured-goal intent pending before sink: session_id=%s reasons=%s",
            session_id,
            contract_reasons,
        )
        return None
    intent_response = await _create_pending_intent_confirmation_response(
        session_id,
        selected_data=candidate.selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=candidate.batch,
        fallback_mechanism_line=candidate.fallback_mechanism_line,
        fallback_detail_lines=candidate.fallback_detail_lines,
        compiled_sink_metadata={
            "compiledProposalId": compiled["compiledProposalId"],
            "sinkType": "intent",
        },
    )
    for followup in intent_response.followups:
        if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
            return followup
    return None


async def _create_pending_intent_confirmation_response(
    session_id: str,
    *,
    selected_data: dict[str, Any],
    merged: dict[str, Any],
    intent_mode: str,
    batch: str,
    fallback_mechanism_line: str = "",
    fallback_detail_lines: list[str] | None = None,
    summary_override: str = "",
    existing_summary: str = "",
    impact_payload: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> ChatServiceResponseEnvelope:
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if not compiled_proposal_id:
        logger.warning(
            "Block intent pending sink without compiled proposal: session_id=%s intent_mode=%s",
            session_id,
            intent_mode,
        )
        return ChatServiceResponseEnvelope(primary="", followups=[])
    replaced_pending = await _load_pending_confirmation_state(session_id)
    raw_constraint_intent_type = selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type")
    selected_values = [
        item
        for item in (selected_data.get("selected") if isinstance(selected_data, dict) else []) or []
        if isinstance(item, dict) and item
    ]
    intent_resolution = proposal_compiler.resolve_intent_select_input(
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
    )
    if not intent_resolution.allowed:
        logger.info(
            "Skip pending intent confirmation before sink with invalid compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
            session_id,
            raw_constraint_intent_type,
            intent_resolution.blocking_reasons,
            merged,
        )
        return ChatServiceResponseEnvelope(primary="", followups=[])
    intent_mode = intent_resolution.intent_mode
    constraint_intent_type = intent_resolution.constraint_intent_type
    mode_text = "要求" if intent_mode == "constraint" else "偏好"
    summary = str(summary_override or "").strip() or _display_summary_from_intent_payload(selected_data) or _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    if not summary:
        summary = f"本次选择的{mode_text}内容。"
    pending_state = _build_intent_pending_state(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary=summary,
        constraint_intent_type=constraint_intent_type,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    await _clear_legacy_plan_edit_cache_best_effort(session_id)
    card_content = _format_intent_card_content(summary, existing_summary=existing_summary)
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "intent_change",
        "actionFamily": "apply_selected_intents",
        "title": "采纳这次报考条件" if intent_mode == "constraint" else "采纳这次报考想法",
        "summary": summary,
        "content": card_content,
        "constraintIntentType": constraint_intent_type,
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "impactTitle": "采纳后的作用",
        "impact": _format_intent_card_impact(
            impact_payload if isinstance(impact_payload, dict) else {
                **merged,
                "constraintIntentType": constraint_intent_type,
            },
            intent_mode=intent_mode,
            fallback_mechanism_line=fallback_mechanism_line,
            fallback_detail_lines=fallback_detail_lines,
        ),
    }
    return ChatServiceResponseEnvelope(
        primary=_intent_card_primary_reply(summary, intent_mode=intent_mode, existing_summary=existing_summary),
        followups=[
            WSResponse(
                type="pendingConfirmationCard",
                session_id=session_id,
                content=json.dumps(payload, ensure_ascii=False),
            )
        ],
    )


async def _resolve_session_batch(session_id: str, default: str = "01") -> str:
    try:
        score_response = await get_user_score_detail(session_id)
        if score_response.get("code") == 0:
            raw_data = score_response.get("data", {}).get("userScoreDetail", {})
            if isinstance(raw_data, dict):
                batch = _normalize_batch(raw_data.get("batch"))
                if batch:
                    return batch
    except Exception:
        logger.warning("Failed to resolve session batch: session_id=%s", session_id, exc_info=True)
    return default


def _parse_score_detail_from_backend(raw_data: dict[str, Any]) -> ScoreDetail:
    province_raw = raw_data.get("province")
    province_name = (
        province_raw.get("name", "")
        if isinstance(province_raw, dict)
        else str(province_raw or raw_data.get("provinceName") or "")
    )
    subject_list: list[str] = []
    for item in raw_data.get("subjectList", []) or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            subject_list.append(name)
    sex_raw = raw_data.get("sex")
    sex_name = sex_raw.get("name", "") if isinstance(sex_raw, dict) else str(sex_raw or "")
    return ScoreDetail(
        province=province_name,
        total_score=int(raw_data.get("totalScore") or raw_data.get("total_score") or 0),
        subject_list=subject_list,
        sex=sex_name,
        volunteer_model=str(raw_data.get("volunteerModel") or raw_data.get("volunteer_model") or "major"),
    )


def _coerce_score_detail(raw_score_detail: Any) -> ScoreDetail | None:
    if isinstance(raw_score_detail, ScoreDetail):
        return raw_score_detail
    if not isinstance(raw_score_detail, dict) or not raw_score_detail:
        return None
    raw_data = raw_score_detail.get("userScoreDetail")
    nested_data = raw_score_detail.get("data")
    if not isinstance(raw_data, dict) and isinstance(nested_data, dict):
        raw_data = nested_data.get("userScoreDetail")
    if not isinstance(raw_data, dict):
        raw_data = raw_score_detail
    return _parse_score_detail_from_backend(raw_data)


async def _create_pending_intent_confirmation_result_from_preview_payload(
    session_id: str,
    payload: dict[str, Any] | None,
) -> _RuntimeCompiledPendingResult:
    """Create a unified pending card from structured intent preview output."""
    candidate = _intent_preview_candidate_from_payload(session_id, payload)
    if candidate is None:
        return _RuntimeCompiledPendingResult(
            source="intent_preview_payload",
            blocked_reasons=["missing_intent_preview_candidate"],
        )
    batch = await _resolve_session_batch(session_id)
    selected_data = _selected_data_from_intent_preview_candidate(candidate, batch=batch)
    plan_attempt = _UserGoalFixConfirmationAttempt()
    plan_selected_data = _selected_data_with_existing_positive_context(
        selected_data,
        candidate.existing_merged,
    )
    if candidate.intent_mode == "constraint":
        fix_candidate = await _constraint_user_goal_fix_candidate_from_preview(
            session_id,
            selected_data=plan_selected_data,
            merged=candidate.merged,
            batch=batch,
            summary=candidate.summary,
            constraint_intent_type=candidate.constraint_intent_type,
            attempt=plan_attempt,
        )
        if fix_candidate is not None:
            fix_result = await _create_pending_fix_confirmation_result_from_user_goal_candidate(
                session_id,
                fix_candidate,
                attempt=plan_attempt,
            )
            if fix_result.card is not None:
                return fix_result
        if plan_attempt.blocked_by_compiled_contract:
            return _RuntimeCompiledPendingResult(
                source="intent_preview_payload",
                blocked_reasons=["compiled_plan_fix_blocked"],
            )
    compiled = proposal_compiler.compile_intent_preview_proposal(
        session_id=session_id,
        selected_data=selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=batch,
        summary=candidate.summary,
        constraint_intent_type=candidate.constraint_intent_type,
    )
    compiled_sink_metadata = proposal_compiler.intent_sink_metadata_or_none(
        compiled,
        session_id=session_id,
        source="intent_preview_payload",
    )
    if compiled_sink_metadata is None:
        return _RuntimeCompiledPendingResult(
            source="intent_preview_payload",
            blocked_reasons=["compiled_intent_sink_blocked"],
        )
    intent_response = await _create_pending_intent_confirmation_response(
        session_id,
        selected_data=selected_data,
        merged=candidate.merged,
        intent_mode=candidate.intent_mode,
        batch=batch,
        fallback_mechanism_line=plan_attempt.fallback_mechanism_line,
        fallback_detail_lines=plan_attempt.fallback_detail_lines,
        summary_override=candidate.summary,
        existing_summary=candidate.existing_summary,
        impact_payload=candidate.payload,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    for followup in intent_response.followups:
        if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
            return _RuntimeCompiledPendingResult(
                card=followup,
                source="intent_preview_payload",
            )
    return _RuntimeCompiledPendingResult(
        source="intent_preview_payload",
        blocked_reasons=["intent_pending_sink_returned_empty"],
    )


def _intent_preview_candidate_from_payload(
    session_id: str,
    payload: dict[str, Any] | None,
) -> _IntentPreviewCandidate | None:
    if not isinstance(payload, dict):
        return None
    payload = _normalize_intent_preview_payload_for_parse(payload)
    try:
        preview = parse_intent_analysis_payload(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return None
    if preview.analysisStage != "confirmed":
        return None
    if preview.status not in {"ready", "existing_only"}:
        return None
    selected_values = [
        item.value
        for item in preview.items
        if item.selected and isinstance(item.value, dict) and item.value
    ]
    if not selected_values:
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning(
            "Failed to merge structured intent preview values: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not merged:
        return None
    intent_mode = str(preview.intentMode or "preference").strip()
    if intent_mode not in {"preference", "constraint"}:
        intent_mode = "preference"
    raw_constraint_intent_type = getattr(preview, "constraintIntentType", "default")
    intent_resolution = proposal_compiler.resolve_intent_preview_input(
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
    )
    if not intent_resolution.allowed:
        logger.info(
            "Skip intent preview card before compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
            session_id,
            raw_constraint_intent_type,
            intent_resolution.blocking_reasons,
            merged,
        )
        return None
    constraint_intent_type = intent_resolution.constraint_intent_type
    intent_mode = intent_resolution.intent_mode
    existing_merged = _merge_intent_preview_item_values(list(preview.existingItems))
    selected_display_summary = _intent_summary_from_item_content(
        list(preview.items),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    existing_summary = _intent_summary_from_item_content(
        list(preview.existingItems),
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    ) or _summarize_intent_values(existing_merged, intent_mode=intent_mode)
    summary = (
        selected_display_summary
        or _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        or preview.title
        or "本次点击采纳后生效的内容。"
    )
    admission_path_display = _admission_path_display(
        payload.get("admissionPath") or payload.get("admission_path")
    )
    if admission_path_display and admission_path_display not in summary:
        summary = f"{summary}；{admission_path_display}" if summary else admission_path_display
    return _IntentPreviewCandidate(
        payload=payload,
        preview=preview,
        selected_values=selected_values,
        merged=merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
        existing_merged=existing_merged,
        selected_display_summary=selected_display_summary,
        existing_summary=existing_summary,
        summary=summary,
    )


def _selected_data_from_intent_preview_candidate(
    candidate: _IntentPreviewCandidate,
    *,
    batch: str,
) -> dict[str, Any]:
    selected_data = {
        "selected": candidate.selected_values,
        "intentMode": candidate.intent_mode,
        "constraintIntentType": candidate.constraint_intent_type,
        "batch": batch,
    }
    if candidate.selected_display_summary:
        selected_data["displaySummary"] = candidate.selected_display_summary
    admission_path = _normalize_admission_path(
        candidate.payload.get("admissionPath") or candidate.payload.get("admission_path")
    )
    if admission_path:
        selected_data["admissionPath"] = admission_path
    return selected_data


def _normalize_intent_preview_payload_for_parse(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ("items", "existingItems"):
        items = normalized.get(key)
        if not isinstance(items, list):
            continue
        normalized_items: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            normalized_item = dict(item)
            if not str(normalized_item.get("content") or "").strip():
                label = str(normalized_item.get("label") or "").strip()
                if label:
                    normalized_item["content"] = label
            normalized_items.append(normalized_item)
        normalized[key] = normalized_items
    return normalized


def _tool_calls_are_readonly_explore_or_compare(messages: list[Any] | None) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return False
    readonly_tools = set(_INTENT_INTEREST_ANALYSIS_TOOL_NAMES) | {
        "compare_major_options",
        "compare_majors",
        "compare_majors_adhoc",
        "compare_schools",
        "compare_schools_adhoc",
        "get_major_introduction",
        "get_major_introductions",
        "get_school_introduction",
    }
    return all(name in readonly_tools for name in tool_names)


async def _resolve_intent_mode_from_message(message_id: Any) -> str:
    if not message_id:
        return "preference"
    try:
        msg_resp = await get_message_by_id(message_id)
        msg_data = (msg_resp or {}).get("data", {})
        content_raw = msg_data.get("content", "")
        content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        if isinstance(content_obj, dict):
            intent_mode = str(content_obj.get("intentMode") or "").strip()
            if intent_mode in {"preference", "constraint"}:
                return intent_mode
    except Exception:
        logger.warning("Failed to resolve intent mode from card: message_id=%s", message_id, exc_info=True)
    return "preference"


async def _create_pending_plan_confirmation_response(
    session_id: str,
    confirmation_candidate: dict[str, Any],
    *,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> WSResponse | None:
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if not compiled_proposal_id:
        logger.warning(
            "Block plan pending sink without compiled proposal: session_id=%s action_family=%s",
            session_id,
            str(confirmation_candidate.get("action_family") or "").strip(),
        )
        return None
    replaced_pending = await _load_pending_confirmation_state(session_id)
    pending_state = _build_plan_pending_state(
        session_id,
        confirmation_candidate,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    await _save_pending_confirmation_state(session_id, pending_state)

    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    summary = _plan_confirmation_candidate_summary_for_user(confirmation_candidate)
    unit_kind = _plan_confirmation_unit_kind(confirmation_candidate)
    content = summary or "确认后会执行本次方案调整。"
    is_ordered_group_action = action_family in {"move_ordered_unit", "remove_ordered_unit"} and unit_kind != "志愿"
    if action_family == "move_ordered_unit" and is_ordered_group_action:
        compact_content = _compact_plan_reply_text(content)
        if "不是按单条志愿位置" not in compact_content and "按专业组顺序计算" not in compact_content:
            content = (
                content.rstrip()
                + "\n\n位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；组内专业会保持连续。"
            )
    if action_family == "remove_ordered_unit" and is_ordered_group_action:
        compact_content = _compact_plan_reply_text(content)
        if "组内专业" not in compact_content and "后续专业组会前移" not in compact_content:
            content = content.rstrip() + "\n\n执行后该专业组内的专业会一并移出，后续专业组会前移。"
    execution_payload = pending_state.get("executionPayload")
    intent_payload = execution_payload.get("intentPayload") if isinstance(execution_payload, dict) else None
    intent_summary = _summarize_selected_intent_payload(intent_payload)
    if intent_summary and intent_summary not in content:
        intent_lines = [part.strip() for part in intent_summary.split("；") if part.strip()]
        intent_content = "\n".join(f"- {part}" for part in intent_lines)
        content = (
            content.rstrip()
            + "\n\n同时更新后续报考参考：\n"
            + intent_content
        )
    title_by_action = {
        "add_units": "确认加入方案",
        "remove_units": "确认移出志愿",
        "move_unit": "确认移动志愿",
        "move_ordered_unit": "确认移动志愿" if unit_kind == "志愿" else "确认移动专业组",
        "remove_ordered_unit": "确认移出志愿" if unit_kind == "志愿" else "确认移出专业组",
        "replace_units": "确认替换志愿",
        "sort_ordered_plan": "确认方案排序",
        "regenerate_order": "确认重排方案",
        "generate_plan": "确认生成方案",
    }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "plan_mutation",
        "actionFamily": action_family,
        "title": title_by_action.get(action_family) or "请确认本次方案调整",
        "summary": summary or "确认后会执行本次方案调整。",
        "content": content,
        "impactTitle": "确认说明",
        "impact": "完成确认前不会改动当前方案；点“确认执行”最清楚，直接回复“确认/执行”也会按当前有效预览处理。",
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    if isinstance(intent_payload, dict) and intent_payload.get("selected"):
        payload["impact"] = _format_plan_card_intent_impact(intent_payload)
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _runtime_plan_compiled_proposal_from_candidate(
    *,
    session_id: str,
    confirmation_candidate: dict[str, Any] | None,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(confirmation_candidate, dict):
        return None
    compiled_source = proposal_compiler.compile_runtime_plan_confirmation_source(
        session_id=session_id,
        confirmation_candidate=confirmation_candidate,
        source=source,
        summary=_plan_confirmation_candidate_summary_for_user(confirmation_candidate),
    )
    return compiled_source.compiled


async def _create_runtime_compiled_plan_pending(
    session_id: str,
    confirmation_candidate: dict[str, Any] | None,
    *,
    source: str,
    compiled: dict[str, Any] | None,
) -> _RuntimeCompiledPendingResult:
    if not isinstance(confirmation_candidate, dict):
        return _RuntimeCompiledPendingResult(
            source=source,
            blocked_reasons=["missing_plan_confirmation_candidate"],
        )
    if not isinstance(compiled, dict):
        return _RuntimeCompiledPendingResult(
            source=source,
            blocked_reasons=["missing_compiled_plan_proposal"],
        )
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    if action_family == "generate_plan":
        score_detail = await _load_session_score_detail_for_generation(session_id)
        if not _score_detail_ready_for_generate_plan(score_detail):
            return _RuntimeCompiledPendingResult(
                source=source,
                blocked_reasons=["missing_generate_plan_score_detail"],
            )
    compiled_sink_metadata = proposal_compiler.plan_sink_metadata_or_none(
        compiled,
        session_id=session_id,
        source=source,
    )
    if compiled_sink_metadata is None:
        _contract_ok, contract_reasons = proposal_compiler.plan_sink_contract(compiled)
        return _RuntimeCompiledPendingResult(
            source=source,
            blocked_reasons=["compiled_plan_sink_blocked", *contract_reasons],
        )
    card = await _create_pending_plan_confirmation_response(
        session_id,
        confirmation_candidate,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    if card is None:
        return _RuntimeCompiledPendingResult(
            source=source,
            blocked_reasons=["compiled_plan_pending_sink_returned_empty"],
        )
    includes_intent_update = bool(
        isinstance(confirmation_candidate.get("intent_update"), dict)
        and confirmation_candidate.get("intent_update", {}).get("selected")
    )
    return _RuntimeCompiledPendingResult(
        card=card,
        primary_reply=_plan_confirmation_card_primary_reply(confirmation_candidate),
        source=source,
        plan_includes_intent_update=includes_intent_update,
        workspace_refresh_targets=_compiled_workspace_refresh_targets(compiled),
    )


def _score_detail_ready_for_generate_plan(score_detail: ScoreDetail | None) -> bool:
    if score_detail is None:
        return False
    return bool(
        str(getattr(score_detail, "province", "") or "").strip()
        and _as_int(getattr(score_detail, "total_score", 0)) > 0
        and [item for item in getattr(score_detail, "subject_list", []) or [] if str(item or "").strip()]
    )


async def _load_session_score_detail_for_generation(session_id: str) -> ScoreDetail | None:
    try:
        score_response = await get_user_score_detail(session_id)
    except Exception:
        logger.warning(
            "Failed to load score detail before generate-plan pending sink: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not isinstance(score_response, dict) or score_response.get("code") != 0:
        return None
    raw_data = score_response.get("data", {}).get("userScoreDetail", {})
    if not isinstance(raw_data, dict) or not raw_data:
        return None
    return _parse_score_detail_from_backend(raw_data)


async def _create_apply_then_generate_plan_pending_result(
    *,
    session_id: str,
    user_prompt: str,
    applied_pending_state: dict[str, Any],
) -> _RuntimeCompiledPendingResult:
    current_version = 0
    try:
        state_resp = await get_planning_state(session_id)
        current_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
    except Exception:
        logger.warning(
            "Failed to load planning state before apply-then-generate pending: session_id=%s",
            session_id,
            exc_info=True,
        )
    generated_source = proposal_compiler.compile_apply_then_generate_plan_source(
        session_id=session_id,
        user_prompt=user_prompt,
        pending_state=applied_pending_state,
        source_version_guard=current_version,
    )
    if not generated_source.compiled or not generated_source.confirmation_candidate:
        return _RuntimeCompiledPendingResult(
            source="apply_pending_then_new_request",
            blocked_reasons=list(generated_source.blocking_reasons),
        )
    return await _create_runtime_compiled_plan_pending(
        session_id,
        generated_source.confirmation_candidate,
        source="apply_pending_then_new_request",
        compiled=generated_source.compiled,
    )


async def _user_requested_fix_proposal_preview(
    *,
    content: str,
    request_context: RequestContext,
    latest_plan_result: dict[str, Any],
) -> bool:
    facts = latest_plan_result.get("facts") if isinstance(latest_plan_result.get("facts"), dict) else {}
    if not proposal_compiler.ready_fix_proposals(facts):
        return False
    if _structured_review_result_is_readonly(latest_plan_result):
        return False
    context = _latest_plan_semantic_route_context(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=json.dumps(latest_plan_result, ensure_ascii=False, default=str),
                        tool_call_id="current-fix-proposal-preview-request-check",
                    )
                ]
            )
        ]
    )
    if not context:
        return False
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=context,
        )
    except Exception:
        logger.warning("Fix proposal preview request check failed", exc_info=True)
        return False
    action_family = str(getattr(decision, "actionFamily", "") or "").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    return action_family == "preview_fix_proposal" and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD


async def _infer_plan_target_issue_codes_from_context(
    *,
    content: str,
    request_context: RequestContext,
    recent_plan_context: dict[str, Any] | None,
    expected_action_family: str,
    target_strategies: list[str],
) -> list[str]:
    if not recent_plan_context:
        return []
    fix_facts = recent_plan_context.get("fixProposals")
    if not isinstance(fix_facts, dict) or not isinstance(fix_facts.get("proposals"), list):
        return []
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=recent_plan_context,
        )
    except Exception:
        logger.warning("Plan target issue-code inference failed", exc_info=True)
        return []
    return proposal_compiler.semantic_decision_target_issue_codes_for_context(
        decision,
        allowed_action_families={expected_action_family, "preview_fix_proposal", "analyze_adjustment"},
        confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
        target_strategies=target_strategies,
        context=recent_plan_context,
    )


async def _infer_fix_proposal_target_scope(
    *,
    content: str,
    request_context: RequestContext,
    latest_plan_result: dict[str, Any],
) -> tuple[list[str], list[str], bool]:
    """Infer the user's repair target and whether that target was explicit.

    Non-empty strategy/issue-code lists are used to select the matching ready
    proposal. The boolean distinguishes "no explicit target" from "explicit
    target exists, but no ready proposal can satisfy it"; the latter must not
    fall back to the first unrelated ready proposal.
    """

    precheck = proposal_compiler.resolve_fix_proposal_target_scope_precheck(latest_plan_result)
    if not precheck.needs_semantic_decision:
        return precheck.target_strategies, precheck.target_issue_codes, precheck.explicit
    context = _latest_plan_semantic_route_context(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=json.dumps(latest_plan_result, ensure_ascii=False, default=str),
                        tool_call_id="current-fix-proposal-preview",
                    )
                ]
            )
        ]
    )
    if not context:
        return [], [], False
    try:
        decision = await classify_plan_semantic_action(
            content,
            request_context=request_context,
            recent_plan_context=context,
        )
    except Exception:
        logger.warning(
            "Fix proposal target strategy inference failed",
            exc_info=True,
        )
        return [], [], False
    scope = proposal_compiler.resolve_fix_proposal_target_scope_from_decision(
        decision,
        allowed_action_families={"preview_fix_proposal", "review_plan", "analyze_adjustment"},
        confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
    )
    return scope.target_strategies, scope.target_issue_codes, scope.explicit


def _build_fix_proposal_pending_state(
    session_id: str,
    proposal: dict[str, Any],
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    user_goal_request: dict[str, Any] | None = None,
    intent_payload: dict[str, Any] | None = None,
    replaced_pending: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
    title = _normalize_fix_proposal_user_text(str(proposal.get("title") or "处理方案提醒").strip())
    summary = str(proposal.get("summary") or proposal.get("impact") or title).strip()
    state = {
        "type": "pendingConfirmation",
        "pendingId": pending_id,
        "sessionId": str(session_id),
        "kind": "plan_mutation",
        "status": "active",
        "actionFamily": "apply_fix_proposal",
        "summary": summary or title,
        "userGoal": title,
        "executionPayload": {
            "toolName": "apply_planning_fix_proposal",
            "proposalId": proposal_id,
            "proposalSource": proposal_source or "review_check",
            "sourceVersionGuard": source_version_guard,
            "strategy": str(proposal.get("strategy") or "").strip(),
            "proposalTitle": title,
            "proposalSummary": summary,
            "regenerateOrderedPlan": True,
            "rerunReview": True,
        },
        "createdAt": now,
        "updatedAt": now,
        "sourceBackendVersion": source_version_guard,
    }
    if user_goal_request:
        state["executionPayload"]["userGoalRequest"] = user_goal_request
    if isinstance(intent_payload, dict) and intent_payload.get("selected"):
        state["executionPayload"]["intentPayload"] = intent_payload
    compiled_proposal_id = ""
    if isinstance(compiled_sink_metadata, dict):
        compiled_proposal_id = str(compiled_sink_metadata.get("compiledProposalId") or "").strip()
    if compiled_proposal_id:
        state["compiledProposalId"] = compiled_proposal_id
        state["compilerSink"] = {
            "compiledProposalId": compiled_proposal_id,
            "sinkType": str(compiled_sink_metadata.get("sinkType") or "fix_proposal").strip() or "fix_proposal",
        }
        state["executionPayload"]["compiledProposalId"] = compiled_proposal_id
    if replaced_pending and replaced_pending.get("pendingId"):
        state["replacesPendingId"] = replaced_pending.get("pendingId")
    return state


def _normalize_fix_proposal_user_text(text: str) -> str:
    normalized = str(text or "").replace("修复建议", "处理建议").replace("修复", "处理").strip()
    replacements = (
        ("处理高收费志愿", "高收费志愿"),
        ("处理高收费", "高收费志愿"),
        ("处理中外合作办学项目", "中外合作项目"),
        ("处理中外合作", "中外合作项目"),
        ("处理非意向托底专业", "非意向兜底专业"),
        ("处理非意向托底", "非意向兜底专业"),
        ("处理数量校验", "补足志愿数量"),
        ("处理录取率梯度断层", "补齐录取率梯度"),
        ("处理录取率倒挂", "调整录取率顺序"),
        ("处理兜底专业不足", "补兜底专业"),
        ("处理组内安全垫不足", "补兜底专业"),
        ("数量校验", "志愿数量"),
        ("冲稳保配比暂时无法自动处理", "冲稳保结构暂时还调不齐"),
        ("录取率梯度断层暂时无法自动处理", "录取率梯度暂时还补不齐"),
        ("暂时无法自动补齐", "暂时还补不齐"),
        ("暂时无法自动处理", "暂时还不能直接处理"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _clean_fix_proposal_title(value: Any) -> str:
    title = _clean_review_fallback_text(value)
    title = re.sub(r"(?:需要你先取舍或放宽条件|需要你先决定取舍或放宽条件)$", "", title).strip()
    title = re.sub(r"(?:暂时还?不能直接处理|暂时还?补不齐|暂时无法自动处理|暂时无法自动补齐)$", "", title).strip()
    title = re.sub(r"(?:暂时|当前)$", "", title).strip()
    if title in {"补足志愿数量", "志愿数量"}:
        return "志愿数量"
    if title in {"补兜底专业", "兜底专业", "兜底"}:
        return "兜底专业"
    return title


def _fix_proposal_action_details(proposal: dict[str, Any], limit: int = 2) -> list[str]:
    details: list[str] = []
    seen: set[str] = set()
    for action in proposal.get("actions") or []:
        if not isinstance(action, dict):
            continue
        detail = _normalize_user_facing_terms(
            _normalize_fix_proposal_user_text(str(action.get("detail") or "").strip())
        )
        if not detail or "->" not in detail:
            continue
        compact = _compact_plan_reply_text(detail)
        if compact in seen:
            continue
        details.append(detail)
        seen.add(compact)
        if len(details) >= limit:
            break
    return details


def _format_fix_proposal_card_content(
    proposal: dict[str, Any],
    *,
    intent_payload: dict[str, Any] | None = None,
) -> str:
    def clean(value: Any) -> str:
        return _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))

    lines: list[str] = []
    intent_summary = _summarize_selected_intent_payload(intent_payload)
    if intent_summary:
        intent_parts = [part.strip() for part in intent_summary.split("；") if part.strip()]
        if intent_parts:
            lines.append(f"- 采纳内容：{'；'.join(intent_parts[:3])}")
            if len(intent_parts) > 3:
                lines.append(f"- 另有 {len(intent_parts) - 3} 条，确认后会一并作为后续参考")
    title = clean(proposal.get("title"))
    summary = clean(proposal.get("summary"))
    impact = clean(proposal.get("impact"))
    action_summaries = [
        clean(item)
        for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])
        if clean(item)
    ]
    deduped_action_summaries: list[str] = []
    seen_action_summaries: set[str] = set()
    title_compact = _compact_plan_reply_text(title)
    summary_compact = _compact_plan_reply_text(summary)
    for action_summary in action_summaries:
        compact = _compact_plan_reply_text(action_summary)
        if compact and (
            compact == title_compact
            or compact == summary_compact
            or compact in title_compact
            or compact in summary_compact
        ):
            continue
        if compact in seen_action_summaries:
            continue
        seen_action_summaries.add(compact)
        deduped_action_summaries.append(action_summary)
    if title:
        lines.append(f"- 处理内容：{title}")
    if summary and summary != title:
        lines.append(f"- 对应提醒：{summary}")
    if deduped_action_summaries:
        lines.append(f"- 调整方式：{'；'.join(deduped_action_summaries[:2])}")
    action_details = _fix_proposal_action_details(proposal)
    if action_details:
        lines.append(f"- 替换预览：{'；'.join(action_details)}")
    if impact:
        lines.append(f"- 影响范围：{impact}")
    return "\n".join(lines).strip() or "确认后会按这条处理建议调整当前方案。"


def _fix_proposal_pending_primary_reply(proposal: dict[str, Any]) -> str:
    title = _normalize_fix_proposal_user_text(str(proposal.get("title") or "这条处理建议").strip())
    summary = _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip()).strip("。；; ")
    lines = [f"已列出这条调整预览：{title}。"]
    if summary and summary != title:
        lines.extend(["", f"这条建议主要是：{summary}。"])
    lines.extend(
        [
            "",
            "具体调整内容在下面卡片里。确认前不会改动当前方案；点“确认执行”后，我会按这条建议处理，并重新刷新方案和审查结果。",
        ]
    )
    return _sanitize_reply_for_user("\n".join(lines))


async def _create_pending_fix_proposal_confirmation_response(
    session_id: str,
    proposal: dict[str, Any],
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    user_goal_request: dict[str, Any] | None = None,
    intent_payload: dict[str, Any] | None = None,
    compiled_sink_metadata: dict[str, Any] | None = None,
) -> WSResponse | None:
    proposal_id = str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip()
    if not proposal_id or source_version_guard <= 0:
        return None
    replaced_pending = await _load_pending_confirmation_state(session_id)
    pending_state = _build_fix_proposal_pending_state(
        session_id,
        proposal,
        source_version_guard=source_version_guard,
        proposal_source=proposal_source,
        user_goal_request=user_goal_request,
        intent_payload=intent_payload,
        replaced_pending=replaced_pending if isinstance(replaced_pending, dict) else None,
        compiled_sink_metadata=compiled_sink_metadata,
    )
    await _save_pending_confirmation_state(session_id, pending_state)
    title = _normalize_user_facing_terms(
        _normalize_fix_proposal_user_text(str(proposal.get("title") or "确认处理这条方案提醒").strip())
    )
    summary = _normalize_user_facing_terms(str(pending_state.get("summary") or title))
    card_payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_state["pendingId"],
        "kind": "plan_mutation",
        "actionFamily": "apply_fix_proposal",
        "title": "确认处理方案提醒",
        "summary": summary,
        "content": _format_fix_proposal_card_content(proposal, intent_payload=intent_payload),
        "impactTitle": "确认说明",
        "impact": (
            _format_plan_card_intent_impact(intent_payload)
            if isinstance(intent_payload, dict) and intent_payload.get("selected")
            else "确认前不会改动当前方案；确认后会按这条处理建议调整方案，并重新刷新方案和审查结果。"
        ),
        "proposalId": proposal_id,
        "strategy": str(proposal.get("strategy") or "").strip(),
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(card_payload, ensure_ascii=False),
    )


async def _create_runtime_compiled_review_fix_pending(
    session_id: str,
    proposal: dict[str, Any] | None,
    *,
    source_version_guard: int,
    proposal_source: str = "review_check",
    compiled: dict[str, Any] | None,
) -> _RuntimeCompiledPendingResult:
    if not isinstance(proposal, dict):
        return _RuntimeCompiledPendingResult(
            source="review_fix_proposal",
            blocked_reasons=["missing_review_fix_proposal"],
        )
    if not isinstance(compiled, dict):
        return _RuntimeCompiledPendingResult(
            source="review_fix_proposal",
            blocked_reasons=["missing_compiled_review_fix_proposal"],
        )
    contract_ok, contract_reasons = proposal_compiler.fix_proposal_sink_contract(compiled)
    if not contract_ok:
        logger.info(
            "Block review fix proposal pending before sink: session_id=%s proposal_id=%s reasons=%s",
            session_id,
            proposal_compiler.proposal_id(proposal),
            contract_reasons,
        )
        return _RuntimeCompiledPendingResult(
            source="review_fix_proposal",
            blocked_reasons=["compiled_fix_sink_blocked", *contract_reasons],
        )
    card = await _create_pending_fix_proposal_confirmation_response(
        session_id,
        proposal,
        source_version_guard=source_version_guard,
        proposal_source=proposal_source,
        compiled_sink_metadata={
            "compiledProposalId": compiled["compiledProposalId"],
            "sinkType": "fix_proposal",
        },
    )
    if card is None:
        return _RuntimeCompiledPendingResult(
            source="review_fix_proposal",
            blocked_reasons=["compiled_fix_pending_sink_returned_empty"],
        )
    return _RuntimeCompiledPendingResult(
        card=card,
        primary_reply=_fix_proposal_pending_primary_reply(proposal),
        source="review_fix_proposal",
        workspace_refresh_targets=_compiled_workspace_refresh_targets(
            compiled,
            fallback_targets=["review"],
        ),
    )


def _plan_confirmation_unit_kind(confirmation_candidate: dict[str, Any]) -> str:
    plan_payload = confirmation_candidate.get("plan_payload")
    if not isinstance(plan_payload, str) or not plan_payload.strip():
        return ""
    try:
        payload = json.loads(plan_payload)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    unit_kind = str(facts.get("unit_kind") or facts.get("unitKind") or "").strip()
    return unit_kind if unit_kind in {"志愿", "专业组"} else ""


_EXECUTE_PLAN_ACTION_VIEW_FAMILIES = proposal_compiler.EXECUTE_PLAN_ACTION_VIEW_FAMILIES
_LOW_PRIORITY_LOG_ACTION_FAMILIES = {
    "query_state",
    "query_ordered",
    "query_candidates",
}


def _extract_execute_plan_action_family(part: ToolCallPart) -> str | None:
    payload = _extract_execute_plan_payload(part)
    if not isinstance(payload, dict):
        return None
    return str(payload.get("action_family") or "").strip() or None


def _extract_execute_plan_payload(part: ToolCallPart) -> dict[str, Any] | None:
    if part.tool_name != "execute_plan_action":
        return None
    args = _parse_tool_call_args(part.args)
    plan_payload = args.get("plan_payload")
    if not isinstance(plan_payload, str) or not plan_payload.strip():
        raw_args = getattr(part, "args", None)
        if isinstance(raw_args, str) and raw_args.strip():
            try:
                direct_payload = json.loads(raw_args)
            except Exception:
                direct_payload = None
            if isinstance(direct_payload, dict) and str(direct_payload.get("action_family") or "").strip():
                return direct_payload
        return None
    try:
        payload = json.loads(plan_payload)
    except Exception:
        logger.warning("Failed to parse execute_plan_action payload", exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _parse_tool_return_json(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        try:
            data = json.loads(content)
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    return None


def _pending_card_kind(card: WSResponse | None) -> str:
    payload = _parse_tool_return_json(getattr(card, "content", "") or "") if card is not None else None
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("kind") or "").strip()


def _enforce_single_pending_confirmation_followup(followups: list[WSResponse]) -> list[WSResponse]:
    pending_indexes = [
        index
        for index, item in enumerate(followups)
        if isinstance(item, WSResponse) and item.type == "pendingConfirmationCard"
    ]
    if len(pending_indexes) <= 1:
        return followups
    keep_index = pending_indexes[-1]
    return [
        item
        for index, item in enumerate(followups)
        if index == keep_index or index not in pending_indexes
    ]


def _max_tuition_from_user_goal_request(user_goal_request: dict[str, Any] | None) -> int:
    if not isinstance(user_goal_request, dict):
        return 0
    goal_type = str(user_goal_request.get("goalType") or user_goal_request.get("goal_type") or "").strip()
    if goal_type != "tuition_budget_scope":
        return 0
    context = user_goal_request.get("context")
    if not isinstance(context, dict):
        return 0
    return _as_int(context.get("maxTuitionPerYear") or context.get("max_tuition_per_year"))


def _extract_recent_intent_analysis_payload(messages: list[Any] | None) -> dict[str, Any] | None:
    """Return the latest structured Intent analysis payload from persisted history.

    The user-facing chat text intentionally omits internal selection values, but
    follow-up analysis such as "这个偏好会影响当前方案吗" still needs the exact
    prior intent facts. Persisted pydantic-ai history keeps tool returns, so we
    recover from that structured source instead of guessing from natural text.
    """
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        if any(key in data for key in ("items", "existingItems", "impactAnalysis", "impactText")):
            return data
    return None


def _extract_tool_arg_text_values(args: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = args.get(key)
        raw_values = raw if isinstance(raw, list) else [raw] if raw else []
        for item in raw_values:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)
    return values


def _extract_positive_major_intent_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(raw: Any) -> None:
        for value in _as_text_list(raw):
            if value and value not in values:
                values.append(value)

    def collect_from_major_intents(major_intents: Any) -> None:
        if not isinstance(major_intents, dict):
            return
        for key in ("level3", "level2", "level1"):
            add(major_intents.get(key))

    def collect_from_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        value = item.get("value")
        if isinstance(value, dict):
            collect_from_major_intents(value.get("major_intents"))
        collect_from_major_intents(item.get("major_intents"))

    collect_from_major_intents(payload.get("major_intents"))
    value = payload.get("value")
    if isinstance(value, dict):
        collect_from_major_intents(value.get("major_intents"))
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and item.get("selected") is False:
                continue
            collect_from_item(item)
    return values


def _extract_positive_school_intent_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(raw: Any) -> None:
        for value in _as_text_list(raw):
            if value and value not in values:
                values.append(value)

    def collect_from_school_intents(school_intents: Any) -> None:
        if not isinstance(school_intents, dict):
            return
        add(school_intents.get("colleges") or school_intents.get("schoolNames") or school_intents.get("schools"))

    def collect_from_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        value = item.get("value")
        if isinstance(value, dict):
            collect_from_school_intents(value.get("school_intents"))
        collect_from_school_intents(item.get("school_intents"))

    collect_from_school_intents(payload.get("school_intents"))
    value = payload.get("value")
    if isinstance(value, dict):
        collect_from_school_intents(value.get("school_intents"))
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and item.get("selected") is False:
                continue
            collect_from_item(item)
    return values


def _extract_positive_region_intent_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(raw: Any) -> None:
        for value in _as_text_list(raw):
            if value and value not in values:
                values.append(value)

    def collect_from_city_intents(city_intents: Any) -> None:
        if not isinstance(city_intents, dict):
            return
        for key in ("province", "city", "area"):
            add(city_intents.get(key))

    def collect_from_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        value = item.get("value")
        if isinstance(value, dict):
            collect_from_city_intents(value.get("city_intents"))
        collect_from_city_intents(item.get("city_intents"))

    collect_from_city_intents(payload.get("city_intents"))
    value = payload.get("value")
    if isinstance(value, dict):
        collect_from_city_intents(value.get("city_intents"))
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and item.get("selected") is False:
                continue
            collect_from_item(item)
    return values


def _extract_positive_career_intent_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(raw: Any) -> None:
        for value in _as_text_list(raw):
            if value and value not in values:
                values.append(value)

    def collect_from_career_intents(career_intents: Any) -> None:
        if not isinstance(career_intents, dict):
            return
        add(career_intents.get("positive"))

    def collect_from_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        value = item.get("value")
        if isinstance(value, dict):
            collect_from_career_intents(value.get("career_intents"))
        collect_from_career_intents(item.get("career_intents"))

    collect_from_career_intents(payload.get("career_intents"))
    add(payload.get("career_directions") or payload.get("careerDirections"))
    value = payload.get("value")
    if isinstance(value, dict):
        collect_from_career_intents(value.get("career_intents"))
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and item.get("selected") is False:
                continue
            collect_from_item(item)
    return values


def _empty_recent_entity_context() -> dict[str, list[str]]:
    return {"major": [], "school": [], "region": [], "career": []}


def _append_unique_values(target: list[str], values: list[str]) -> None:
    for value in values:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)


def _latest_previous_turn_messages(messages: list[Any] | None) -> list[Any]:
    latest: list[Any] = []
    for message in reversed(messages or []):
        latest.append(message)
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart)
            for part in (getattr(message, "parts", []) or [])
        ):
            break
    return list(reversed(latest))


def _extract_structured_entity_context_from_tool_history(messages: list[Any] | None) -> dict[str, list[str]]:
    """Recover recent readonly entities from structured tool calls/returns.

    This supports follow-ups like "那两个都加吧" after an explain/compare turn.
    It deliberately uses tool args/results instead of assistant prose.
    """

    messages = _latest_previous_turn_messages(messages)
    context = _empty_recent_entity_context()

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _ENTITY_CONTEXT_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        _append_unique_values(
            context["major"],
            _extract_tool_arg_text_values(data, ("major_names", "majorNames", "major_name", "majorName"))
            + _extract_positive_major_intent_values(data),
        )
        _append_unique_values(
            context["school"],
            _extract_tool_arg_text_values(
                data,
                (
                    "school_names",
                    "schoolNames",
                    "school_name",
                    "schoolName",
                    "school_name1",
                    "school_name2",
                    "schoolName1",
                    "schoolName2",
                    "collegeName",
                ),
            )
            + _extract_positive_school_intent_values(data),
        )
        _append_unique_values(
            context["region"],
            _extract_tool_arg_text_values(
                data,
                ("region_names", "regionNames", "province", "provinces", "city", "cities", "area", "areas"),
            )
            + _extract_positive_region_intent_values(data),
        )
        _append_unique_values(
            context["career"],
            _extract_tool_arg_text_values(
                data,
                (
                    "career_directions",
                    "careerDirections",
                    "career_direction",
                    "careerDirection",
                    "direction_slots",
                    "directionSlots",
                    "direction_slot",
                    "directionSlot",
                ),
            )
            + _extract_positive_career_intent_values(data),
        )

    for part in reversed(_iter_tool_call_parts(messages)):
        if part.tool_name not in _ENTITY_CONTEXT_TOOL_NAMES:
            continue
        args = _parse_tool_call_args(part.args)
        _append_unique_values(
            context["major"],
            _extract_tool_arg_text_values(
                args,
                ("major_names", "majorNames", "major_name", "majorName", "major_name1", "major_name2"),
            )
            + _extract_positive_major_intent_values(args),
        )
        _append_unique_values(
            context["school"],
            _extract_tool_arg_text_values(
                args,
                (
                    "school_names",
                    "schoolNames",
                    "school_name",
                    "schoolName",
                    "school_name1",
                    "school_name2",
                    "schoolName1",
                    "schoolName2",
                    "collegeName",
                ),
            )
            + _extract_positive_school_intent_values(args),
        )
        _append_unique_values(
            context["region"],
            _extract_tool_arg_text_values(
                args,
                ("region_names", "regionNames", "province", "provinces", "city", "cities", "area", "areas"),
            )
            + _extract_positive_region_intent_values(args),
        )
        _append_unique_values(
            context["career"],
            _extract_tool_arg_text_values(
                args,
                (
                    "career_directions",
                    "careerDirections",
                    "career_direction",
                    "careerDirection",
                    "direction_slots",
                    "directionSlots",
                    "direction_slot",
                    "directionSlot",
                ),
            )
            + _extract_positive_career_intent_values(args),
        )
    return {key: values[:6] for key, values in context.items() if values}


def _extract_structured_major_context_from_tool_history(messages: list[Any] | None) -> list[str]:
    return _extract_structured_entity_context_from_tool_history(messages).get("major", [])


def _runtime_intent_entity_profile_context(history: list[Any] | None) -> dict[str, Any]:
    recent_entity_context = _extract_structured_entity_context_from_tool_history(history)
    if not recent_entity_context:
        return {}
    recent_major_context = recent_entity_context.get("major", [])
    hints = [
        {
            "type": f"{entity_type}_context",
            "source": "recent_readonly_tool",
            "entityType": entity_type,
            "values": values,
        }
        for entity_type, values in recent_entity_context.items()
        if values
    ]
    result: dict[str, Any] = {
        "recentEntityContext": recent_entity_context,
        "referenceResolutionHints": hints,
    }
    if recent_major_context:
        result["recentMajorContext"] = recent_major_context
        if hints:
            hints[0]["source"] = "recent_readonly_major_tool" if hints[0].get("entityType") == "major" else hints[0]["source"]
    return result


def _extract_confirmable_intent_payload_from_interest_tool(messages: list[Any] | None) -> dict[str, Any] | None:
    """Recover a structured intent preview carried by a misrouted Explore tool."""

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        if str(data.get("analysisStage") or "").strip() != "confirmed":
            continue
        if str(data.get("status") or "").strip() not in {"ready", "existing_only"}:
            continue
        items = data.get("items")
        if not isinstance(items, list) or not any(isinstance(item, dict) and item.get("selected") is not False for item in items):
            continue
        return data
    return None


def _planning_state_profile_for_turn_decision(
    *,
    planning_summary: PlanningSummary | None,
    pending_state: dict[str, Any] | None,
    score_detail: ScoreDetail | None,
) -> dict[str, Any]:
    ordered_total = _as_int(getattr(planning_summary, "ordered_total", 0))
    working_total = _as_int(getattr(planning_summary, "working_total", 0))
    candidate_available_total = _as_int(getattr(planning_summary, "candidate_available_total", 0))
    return {
        "scoreReady": bool(score_detail and _as_int(getattr(score_detail, "total_score", 0)) > 0),
        "formalPlanPresent": ordered_total > 0 or working_total > 0,
        "candidatePoolPresent": candidate_available_total > 0 or working_total > 0,
        "majorGroupPlanPresent": bool(
            str(getattr(planning_summary, "volunteer_model", "") or "").strip() == "majorGroup"
        ),
        "pendingExists": bool(
            isinstance(pending_state, dict)
            and str(pending_state.get("status") or "").strip() == "active"
        ),
    }


def _turn_decision_cache_key(
    content: str,
    payload: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "content": str(content or ""),
            "planningStateProfile": payload.get("planningStateProfile") or {},
            "pendingState": payload.get("pendingState") or {},
            "historyContext": payload.get("historyContext") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _record_observability_duration(
    request_context: RequestContext,
    key: str,
    duration_ms: int,
) -> None:
    observability = getattr(request_context, "agent_observability", None)
    if not isinstance(observability, dict):
        return
    value = max(0, int(duration_ms))
    current = observability.get(key)
    if isinstance(current, (int, float)):
        observability[key] = int(current) + value
    else:
        observability[key] = value


def _increment_observability_counter(
    request_context: RequestContext,
    key: str,
) -> None:
    observability = getattr(request_context, "agent_observability", None)
    if not isinstance(observability, dict):
        return
    current = observability.get(key)
    observability[key] = int(current) + 1 if isinstance(current, (int, float)) else 1


def _observability_timing_fields(request_context: RequestContext) -> dict[str, Any]:
    observability = getattr(request_context, "agent_observability", None)
    fields: dict[str, Any] = {}
    if not isinstance(observability, dict):
        observability = {}
    timing_keys = (
        "turnDecisionDurationMs",
        "turnDecisionCacheHitCount",
        "turnDecisionTimeoutCount",
        "intentEntityProfileDurationMs",
        "intentSideEffectDurationMs",
    )
    fields.update(
        {
            key: int(observability[key])
            for key in timing_keys
            if isinstance(observability.get(key), (int, float))
        }
    )
    shadow_task = getattr(request_context, "_zhiyuan_agent_poc_shadow_task", None)
    if isinstance(shadow_task, asyncio.Task) and shadow_task.done():
        if shadow_task.cancelled():
            return fields
        with contextlib.suppress(Exception):
            task_shadow = shadow_task.result()
            if isinstance(task_shadow, dict):
                setattr(request_context, "_zhiyuan_agent_poc_shadow", task_shadow)
    shadow = getattr(request_context, "_zhiyuan_agent_poc_shadow", None)
    if isinstance(shadow, dict):
        fields["zhiyuanAgentPocShadow"] = shadow
    return fields


async def _classify_turn_decision_cached(
    content: str,
    *,
    request_context: RequestContext,
    payload: dict[str, Any],
) -> Any:
    cache = getattr(request_context, "_turn_decision_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(request_context, "_turn_decision_cache", cache)
    cache_key = _turn_decision_cache_key(content, payload)
    if cache_key in cache:
        _increment_observability_counter(request_context, "turnDecisionCacheHitCount")
        return cache[cache_key]
    started_at = time.monotonic()
    try:
        if _TURN_DECISION_TIMEOUT_SECONDS > 0:
            decision = await asyncio.wait_for(
                classify_turn_decision(content, payload=payload),
                timeout=_TURN_DECISION_TIMEOUT_SECONDS,
            )
        else:
            decision = await classify_turn_decision(content, payload=payload)
    except asyncio.TimeoutError:
        _record_observability_duration(
            request_context,
            "turnDecisionDurationMs",
            int((time.monotonic() - started_at) * 1000),
        )
        _increment_observability_counter(request_context, "turnDecisionTimeoutCount")
        raise
    _record_observability_duration(
        request_context,
        "turnDecisionDurationMs",
        int((time.monotonic() - started_at) * 1000),
    )
    cache[cache_key] = decision
    return decision


def _store_current_turn_decision(request_context: RequestContext, decision: Any) -> None:
    if isinstance(getattr(request_context, "agent_observability", None), dict):
        request_context.agent_observability["turnDecision"] = _turn_decision_snapshot(decision)
    setattr(request_context, "_turn_decision_object", decision)


def _pending_state_allows_runtime_intent_hard_cut(pending_state: dict[str, Any] | None) -> bool:
    if not isinstance(pending_state, dict) or str(pending_state.get("status") or "").strip() != "active":
        return True
    return str(pending_state.get("kind") or "").strip() == "intent_change"


def _turn_decision_allows_runtime_intent_hard_cut(
    decision: Any,
    *,
    pending_state: dict[str, Any] | None = None,
) -> bool:
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    task_layer = str(getattr(decision, "taskLayer", "") or "").strip()
    scope_anchor = str(getattr(decision, "scopeAnchor", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    if (
        confidence >= 0.65
        and side_effect == "intent_pending"
        and task_layer in {"intent", "mixed"}
        and scope_anchor == "future_reference"
        and scenario in {"intent_update", "region_preference_update", ""}
    ):
        return True

    return False


def _turn_decision_allows_runtime_intent_soft_candidate(decision: Any) -> bool:
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    return (
        confidence >= 0.65
        and side_effect in {"plan_preview", "readonly_or_plan_preview"}
        and scenario in {"intent_update", "region_preference_update"}
    )


def _turn_decision_blocks_runtime_intent_hard_cut(
    decision: Any,
) -> bool:
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    task_layer = str(getattr(decision, "taskLayer", "") or "").strip()
    scope_anchor = str(getattr(decision, "scopeAnchor", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    if confidence < 0.65:
        return False
    if side_effect in {
        "readonly",
        "readonly_while_pending",
        "apply_pending_then_readonly",
        "conflict_with_existing_pending",
        "needs_plan_first",
        "profile_change_replan",
        "profile_replan_adhoc",
        "profile_replan_ambiguous",
    }:
        return True
    if side_effect in {"plan_preview", "readonly_or_plan_preview"}:
        # TurnDecision can over-anchor future intent updates to current_plan.
        # Keep only intent-update scenarios as soft candidates; high-confidence
        # current-plan atomic mutations must stay in the plan path.
        return not _turn_decision_allows_runtime_intent_soft_candidate(decision)
    if task_layer in {"explore", "policy"} and side_effect != "intent_pending":
        return True
    if scope_anchor in {"current_plan", "candidate_pool", "current_profile", "current_major_group"} and side_effect != "intent_pending":
        return True
    return scenario in {
        "apply_pending_then_readonly_query",
        "plan_query",
        "plan_query_while_pending",
        "profile_adhoc_replan",
        "profile_scope_ambiguous",
        "profile_update_replan",
        "state_query_while_pending",
        "profile_change_state_query",
        "major_group_local_policy_query",
    }


def _should_defer_runtime_intent_hard_cut_to_current_plan_action(
    content: str,
    *,
    planning_summary: PlanningSummary | None,
) -> bool:
    if proposal_compiler.content_has_future_reference_anchor(content):
        return False
    if not _planning_summary_has_formal_plan(planning_summary):
        return False
    return proposal_compiler.content_has_current_plan_mutation_anchor(content)


def _profile_is_durable_constraint_intent(profile: Any) -> bool:
    strength = _model_value(profile, "preferenceStrength", {})
    if isinstance(strength, dict) and (
        _as_text_list(strength.get("only_keep"))
        or _as_text_list(strength.get("must_have"))
        or _as_text_list(strength.get("exclude_hard"))
    ):
        return True
    return bool(_runtime_intent_profile_physical_constraints(profile))


def _turn_decision_blocks_full_agent_intent_pending(decision: Any | None) -> bool:
    if decision is None:
        return False
    return _turn_decision_blocks_runtime_intent_hard_cut(decision)


def _atomic_add_units_scope_can_override_intent(decision: Any) -> bool:
    if str(getattr(decision, "actionFamily", "") or "").strip() != "add_units":
        return True
    volunteer_ids = _as_text_list(getattr(decision, "volunteerIds", []) or [])
    unit_ids = _as_text_list(getattr(decision, "unitIds", []) or [])
    major_keyword = str(getattr(decision, "majorKeyword", "") or "").strip()
    school_keyword = str(getattr(decision, "schoolKeyword", "") or "").strip()
    major_tags = _as_text_list(getattr(decision, "majorTags", []) or [])
    school_tags = _as_text_list(getattr(decision, "schoolTags", []) or [])
    tier = str(getattr(decision, "tier", "") or "").strip()
    if volunteer_ids or unit_ids:
        return True
    if school_keyword and major_keyword:
        return True
    if major_keyword or major_tags:
        return True
    return bool(school_tags and tier)


_RUNTIME_INTENT_DEFERABLE_ATOMIC_ACTION_FAMILIES = {
    "add_units",
    "remove_units",
    "move_unit",
    "move_ordered_unit",
    "remove_ordered_unit",
    "replace_units",
    "sort_ordered_plan",
    "regenerate_order",
}


async def _semantic_atomic_plan_action_should_defer_runtime_intent(
    *,
    content: str,
    request_context: RequestContext,
    history: list[Any] | None,
    turn_decision: Any | None,
) -> tuple[bool, dict[str, Any]]:
    if proposal_compiler.content_has_future_reference_anchor(content):
        return False, {"reason": "future_reference_anchor"}
    try:
        decision = await classify_plan_atomic_action_dsl(
            content,
            request_context=request_context,
            recent_plan_context=_latest_plan_semantic_route_context(history),
        )
    except Exception:
        logger.warning(
            "Runtime intent atomic plan action arbitration failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return False, {"reason": "atomic_plan_action_dsl_failed"}
    action_family = str(getattr(decision, "actionFamily", "none") or "none").strip()
    if action_family not in _RUNTIME_INTENT_DEFERABLE_ATOMIC_ACTION_FAMILIES:
        return False, {
            "reason": "non_mutating_atomic_plan_action_family",
            "source": "plan_atomic_action_dsl",
            "actionFamily": action_family,
            "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        }
    if not _atomic_add_units_scope_can_override_intent(decision):
        return False, {
            "reason": "weak_add_units_scope",
            "source": "plan_atomic_action_dsl",
            "actionFamily": action_family,
            "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        }

    planning_version = 0
    planning_summary = getattr(request_context, "planning_summary", None)
    if planning_summary is not None:
        with contextlib.suppress(TypeError, ValueError):
            planning_version = int(getattr(planning_summary, "version", 0) or 0)
    compiled_source = proposal_compiler.compile_runtime_atomic_plan_action_source(
        content=content,
        action_family=getattr(decision, "actionFamily", "none"),
        confidence=float(getattr(decision, "confidence", 0.0) or 0.0),
        turn_decision=turn_decision,
        require_turn_decision=False,
        volunteer_ids=list(getattr(decision, "volunteerIds", []) or []),
        unit_ids=list(getattr(decision, "unitIds", []) or []),
        source_major_names=list(getattr(decision, "sourceMajorNames", []) or []),
        source_position=getattr(decision, "sourcePosition", None),
        position_scope=getattr(decision, "positionScope", None),
        target_position=getattr(decision, "targetPosition", None),
        sort_field=getattr(decision, "sortField", None),
        review_issue_code=getattr(decision, "reviewIssueCode", None),
        tier=getattr(decision, "tier", None),
        province_keyword=getattr(decision, "provinceKeyword", None),
        school_keyword=getattr(decision, "schoolKeyword", None),
        major_keyword=getattr(decision, "majorKeyword", None),
        school_tags=list(getattr(decision, "schoolTags", []) or []),
        major_tags=list(getattr(decision, "majorTags", []) or []),
        min_tuition_per_year=getattr(decision, "minTuitionPerYear", None),
        max_tuition_per_year=getattr(decision, "maxTuitionPerYear", None),
        preference_fit=getattr(decision, "preferenceFit", None),
        preserve_count=bool(getattr(decision, "preserveCount", False)),
        limit=int(getattr(decision, "limit", 5) or 5),
        planning_version=planning_version,
        allow_mutation_anchor_turn_decision_override=True,
    )
    arbitration = {
        "source": "plan_atomic_action_dsl",
        "matched": bool(compiled_source.matched),
        "actionFamily": action_family,
        "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        "blockingReasons": list(compiled_source.blocking_reasons),
        "planActionDsl": dict(compiled_source.plan_action_dsl),
        "turnDecisionDsl": dict(compiled_source.turn_decision_dsl),
    }
    return bool(compiled_source.matched), arbitration


def _full_agent_intent_pending_blocked_by_turn_decision_reply(decision: Any | None) -> str:
    if decision is None:
        return (
            "这轮没有通过结构化路由校验，所以不会创建待采纳意向卡，也不会改动当前方案。"
            "如果你要正式更新后续报考参考或调整当前方案，请再明确说明一次，我会先重新生成可确认内容。"
        )
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    if side_effect in {"readonly", "readonly_while_pending"}:
        return "这轮识别为只读查看或说明诉求，不会创建待采纳意向卡，也不会改动当前方案。"
    if scenario in {"plan_query", "plan_query_while_pending"}:
        return "这轮识别为当前方案查询诉求，不会创建待采纳意向卡，也不会改动当前方案。"
    return (
        "这轮识别为当前方案调整诉求，但没有形成可执行的方案调整预览，"
        "所以不会创建长期意向卡，也不会改动当前方案。\n\n"
        "需要先定位当前方案中的命中项并生成调整预览；确认前不会执行。"
    )


def _blocked_intent_preview_for_plan_route_reply(
    decision: Any | None,
    preview_payload: dict[str, Any] | None,
) -> str:
    source = proposal_compiler.compile_blocked_intent_preview_for_plan_route_reply_source(
        turn_decision=decision,
        preview_payload=preview_payload,
    )
    if source.matched and source.primary_reply:
        return source.primary_reply
    return _full_agent_intent_pending_blocked_by_turn_decision_reply(decision)


def _model_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _profile_text_values(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    for item in raw_values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


_SCHOOL_NATURE_INTENT_ALIASES = {
    "公办": "公办",
    "公立": "公办",
    "公办院校": "公办",
    "公办学校": "公办",
    "公办大学": "公办",
    "公立院校": "公办",
    "公立学校": "公办",
    "公立大学": "公办",
    "民办": "民办",
    "私立": "民办",
    "民办院校": "民办",
    "民办学校": "民办",
    "民办大学": "民办",
    "私立院校": "民办",
    "私立学校": "民办",
    "私立大学": "民办",
}


def _normalize_school_nature_intent_value(value: Any) -> str:
    compact = re.sub(r"\s+", "", str(value or "").strip())
    if compact in _SCHOOL_NATURE_INTENT_ALIASES:
        return _SCHOOL_NATURE_INTENT_ALIASES[compact]
    if "公办" in compact or "公立" in compact:
        return "公办"
    if "民办" in compact or "私立" in compact:
        return "民办"
    return ""


def _profile_confidence_value(value: Any) -> float:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"high", "高", "高置信"}:
            return 0.9
        if normalized in {"medium", "中", "中等", "中置信"}:
            return 0.65
        if normalized in {"low", "低", "低置信"}:
            return 0.35
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _runtime_intent_profile_tuition_budget(profile: Any) -> dict[str, list[int]]:
    raw_budget = _model_value(profile, "tuitionBudget", {}) or {}
    if not isinstance(raw_budget, dict):
        return {}
    result: dict[str, list[int]] = {}
    min_tuition = _as_int(raw_budget.get("minTuitionPerYear") or raw_budget.get("min_tuition_per_year"))
    max_tuition = _as_int(raw_budget.get("maxTuitionPerYear") or raw_budget.get("max_tuition_per_year"))
    if min_tuition > 0:
        result["min_tuition_per_year"] = [min_tuition]
    if max_tuition > 0:
        result["max_tuition_per_year"] = [max_tuition]
    if min_tuition > 0 and max_tuition > 0 and min_tuition > max_tuition:
        return {}
    return result


def _runtime_intent_profile_physical_constraints(profile: Any) -> dict[str, list[str]]:
    raw_constraints = _model_value(profile, "physicalConstraints", {}) or {}
    if not isinstance(raw_constraints, dict):
        return {}
    special_limits = [
        value
        for value in _as_text_list(raw_constraints.get("specialLimits") or raw_constraints.get("special_limits"))
        if not _normalize_school_nature_intent_value(value)
    ]
    return {"special_limits": special_limits} if special_limits else {}


_TURN_DECISION_TARGET_ISSUE_SPECIAL_LIMITS = {
    "high_tuition": "高收费",
    "cooperative_program": "中外合作",
    "admission_limit": "限报条件",
    "special_enrollment": "特殊类型招生",
}


def _turn_decision_target_issue_special_limits(
    turn_decision: Any | None,
) -> list[str]:
    if turn_decision is None:
        return []
    special_limits: list[str] = []
    for issue in _as_text_list(getattr(turn_decision, "targetIssue", []) or []):
        label = _TURN_DECISION_TARGET_ISSUE_SPECIAL_LIMITS.get(str(issue or "").strip())
        if label and label not in special_limits:
            special_limits.append(label)
    return special_limits


def _runtime_intent_profile_from_turn_decision_target_issue(
    turn_decision: Any | None,
) -> Any | None:
    if turn_decision is None:
        return None
    if not _turn_decision_allows_runtime_intent_hard_cut(turn_decision):
        return None
    confidence = float(getattr(turn_decision, "confidence", 0.0) or 0.0)
    if confidence < 0.9:
        return None
    special_limits = _turn_decision_target_issue_special_limits(turn_decision)
    if not special_limits:
        return None
    spans = [
        {
            "entity": label,
            "entityType": "budget",
            "polarity": "negative",
            "strength": "exclude_hard",
        }
        for label in special_limits
    ]
    payload = {
        "entityType": "budget",
        "majorValues": [],
        "regionValues": [],
        "schools": [],
        "careerValues": [],
        "tuitionBudget": {},
        "physicalConstraints": {"specialLimits": special_limits},
        "preferenceStrength": {"exclude_hard": special_limits},
        "entityPolaritySpans": spans,
        "contextResolution": {},
        "admissionPath": None,
        "confidence": confidence,
        "reason": "structured_turn_decision_target_issue_fallback",
    }
    return SimpleNamespace(**payload, model_dump=lambda: dict(payload))


def _add_profile_value(payload: dict[str, list[str]], key: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    bucket = payload.setdefault(key, [])
    if text not in bucket:
        bucket.append(text)


def _profile_major_payload_key(entity: str, *, batch: str, negative: bool) -> tuple[str, str]:
    try:
        resolved = resolve_major_entity(entity, batch)
        best = resolved.best
        if best is None and compact_major_text(entity) in CATEGORY_PREFERRED_MAJOR_ALIASES:
            best = next(
                (
                    candidate
                    for candidate in resolved.candidates
                    if str(getattr(candidate, "level", "") or "") == "level2"
                ),
                None,
            )
    except Exception:
        best = None
    level = str(getattr(best, "level", "") or "level3").strip()
    if level not in {"level1", "level2", "level3"}:
        level = "level3"
    name = str(getattr(best, "canonical_name", "") or entity).strip()
    return (f"negative_{level}" if negative else level), name


_ABSTRACT_REGION_PROFILE_VALUES = {
    "长三角",
    "珠三角",
    "江浙沪",
    "南方",
    "北方",
    "华东",
    "华北",
    "华中",
    "华南",
    "东北",
    "西北",
    "西南",
    "东南",
    "中南",
}


def _profile_region_payload_key(entity: str, *, negative: bool) -> tuple[str, str]:
    try:
        resolved_entity = resolve_region_entity(entity)
        best = resolved_entity.best
    except Exception:
        best = None
    if best is not None and str(best.level or "") in {"province", "city", "area"}:
        level = str(best.level or "").strip()
        key = f"negative_{level}" if negative else level
        return key, str(best.canonical_name or entity).strip()
    normalized = str(entity or "").strip()
    if normalized in _ABSTRACT_REGION_PROFILE_VALUES:
        return ("negative_area" if negative else "area"), normalized
    return ("negative_area" if negative else "area"), normalized


def _normalize_career_profile_values(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in _as_text_list(values):
        slots = normalize_career_slots([value])
        resolved = slots[0] if slots else value
        if resolved and resolved not in normalized:
            normalized.append(resolved)
    return normalized


def _is_career_profile_value(value: Any) -> bool:
    return bool(normalize_career_slots([str(value or "").strip()]))


def _runtime_intent_profile_records(profile: Any) -> list[tuple[str, str, str, bool]]:
    raw_major_values = _profile_text_values(_model_value(profile, "majorValues", []))
    major_values = {value for value in raw_major_values if not _is_career_profile_value(value)}
    region_values = set(_profile_text_values(_model_value(profile, "regionValues", [])))
    school_values = set()
    for value in _profile_text_values(_model_value(profile, "schools", [])):
        school_values.add(_normalize_school_nature_intent_value(value) or value)
    career_values = set(_profile_text_values(_model_value(profile, "careerValues", [])))
    career_values.update(value for value in raw_major_values if _is_career_profile_value(value))
    records: list[tuple[str, str, str, bool]] = []
    seen: set[tuple[str, str, bool]] = set()
    covered_entities: set[tuple[str, str]] = set()

    def add(entity_type: str, entity: str, strength: str, negative: bool) -> None:
        entity_type = str(entity_type or "").strip()
        entity = str(entity or "").strip()
        strength = str(strength or "").strip()
        if not entity_type or not entity:
            return
        school_nature = _normalize_school_nature_intent_value(entity)
        if school_nature:
            entity_type = "school"
            entity = school_nature
        covered_entities.add((entity_type, entity))
        key = (entity_type, entity, negative)
        if key in seen:
            return
        seen.add(key)
        records.append((entity_type, entity, strength, negative))

    for span in _model_value(profile, "entityPolaritySpans", []) or []:
        if not isinstance(span, dict):
            continue
        entity = str(span.get("entity") or "").strip()
        entity_type = str(span.get("entityType") or "").strip()
        school_nature = _normalize_school_nature_intent_value(entity)
        if school_nature:
            entity_type = "school"
            entity = school_nature
        if entity_type == "major" and entity not in major_values and entity in career_values:
            entity_type = "career"
        if entity_type not in {"major", "school", "region", "career"}:
            if entity in major_values:
                entity_type = "major"
            elif entity in school_values:
                entity_type = "school"
            elif entity in region_values:
                entity_type = "region"
            elif entity in career_values:
                entity_type = "career"
        polarity = str(span.get("polarity") or "").strip()
        strength = str(span.get("strength") or "").strip()
        add(entity_type, entity, strength, polarity == "negative" or strength.startswith("exclude_"))

    preference_strength = _model_value(profile, "preferenceStrength", {}) or {}
    if isinstance(preference_strength, dict):
        for strength, raw_values in preference_strength.items():
            strength_text = str(strength or "").strip()
            negative = strength_text in {"exclude_soft", "exclude_hard"}
            for entity in _profile_text_values(raw_values):
                school_nature = _normalize_school_nature_intent_value(entity)
                if school_nature:
                    add("school", school_nature, strength_text, negative)
                elif entity in major_values:
                    add("major", entity, strength_text, negative)
                elif entity in school_values:
                    add("school", entity, strength_text, negative)
                elif entity in region_values:
                    add("region", entity, strength_text, negative)
                elif entity in career_values:
                    add("career", entity, strength_text, negative)

    for entity in major_values:
        if ("major", entity) not in covered_entities:
            add("major", entity, "preferred", False)
    for entity in school_values:
        if ("school", entity) not in covered_entities:
            add("school", entity, "preferred", False)
    for entity in region_values:
        if ("region", entity) not in covered_entities:
            add("region", entity, "preferred", False)
    for entity in career_values:
        if ("career", entity) not in covered_entities:
            add("career", entity, "preferred", False)
    return records


def _runtime_intent_profile_selected_values(
    profile: Any,
    *,
    batch: str,
) -> tuple[list[dict[str, Any]], str, str]:
    major_payload: dict[str, list[str]] = {}
    school_payload: dict[str, list[str]] = {}
    city_payload: dict[str, list[str]] = {}
    career_payload: dict[str, list[str]] = {}
    tuition_budget_payload = _runtime_intent_profile_tuition_budget(profile)
    physical_constraints_payload = _runtime_intent_profile_physical_constraints(profile)
    has_only_keep = False
    has_must_have = False
    has_hard_negative = False
    if physical_constraints_payload:
        has_hard_negative = True

    for entity_type, entity, strength, negative in _runtime_intent_profile_records(profile):
        if strength == "only_keep":
            has_only_keep = True
        elif strength == "must_have":
            has_must_have = True
        elif strength == "exclude_hard" or (negative and strength != "exclude_soft"):
            has_hard_negative = True
        if entity_type == "major":
            key, value = _profile_major_payload_key(entity, batch=batch, negative=negative)
            _add_profile_value(major_payload, key, value)
        elif entity_type == "school":
            values = _normalize_school_intent_names([entity], batch)
            value = values[0] if values else entity
            _add_profile_value(school_payload, "negative_colleges" if negative else "colleges", value)
        elif entity_type == "region":
            key, value = _profile_region_payload_key(entity, negative=negative)
            _add_profile_value(city_payload, key, value)
        elif entity_type == "career":
            for value in _normalize_career_profile_values([entity]):
                _add_profile_value(career_payload, "negative" if negative else "positive", value)

    selected_values: list[dict[str, Any]] = []
    if major_payload:
        selected_values.append({"major_intents": major_payload})
    if school_payload:
        selected_values.append({"school_intents": school_payload})
    if city_payload:
        selected_values.append({"city_intents": city_payload})
    if career_payload:
        selected_values.append({"career_intents": career_payload})
    if tuition_budget_payload:
        selected_values.append({"tuition_budget": tuition_budget_payload})
    if physical_constraints_payload:
        selected_values.append({"physical_constraints": physical_constraints_payload})

    if has_only_keep:
        return selected_values, "constraint", "only_keep"
    if has_must_have:
        return selected_values, "constraint", "must_have"
    if has_hard_negative:
        return selected_values, "constraint", "default"
    return selected_values, "preference", "default"


def _intent_preview_payload_from_entity_profile(
    *,
    session_id: str,
    profile: Any,
    batch: str,
) -> dict[str, Any] | None:
    selected_values, intent_mode, constraint_intent_type = _runtime_intent_profile_selected_values(
        profile,
        batch=batch,
    )
    if not selected_values:
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning(
            "Failed to merge runtime intent profile values for plan reroute: session_id=%s",
            session_id,
            exc_info=True,
        )
        return None
    if not merged:
        return None
    summary = (
        _intent_entity_profile_strength_display_summary(profile, batch=batch)
        or _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        or "本次选择的报考想法。"
    )
    items: list[dict[str, Any]] = []
    for selected in selected_values:
        if not isinstance(selected, dict) or not selected:
            continue
        try:
            item_merged = merge_selected_values([selected])
        except Exception:
            item_merged = selected
        item_summary = _summarize_intent_values(
            item_merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        ) or summary
        items.append(
            {
                "content": item_summary,
                "selected": True,
                "value": selected,
            }
        )
    if not items:
        return None
    admission_path = str(_model_value(profile, "admissionPath", "") or "").strip()
    payload = {
        "status": "ready",
        "sessionId": session_id,
        "title": "确认这条报考想法",
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "analysisStage": "confirmed",
        "items": items,
        "existingItems": [],
        "message": summary,
        "batch": batch,
        "entityProfile": (
            profile.model_dump()
            if hasattr(profile, "model_dump")
            else dict(profile)
            if isinstance(profile, dict)
            else {}
        ),
    }
    if admission_path:
        payload["admissionPath"] = admission_path
    return payload


def _split_runtime_intent_selected_values(
    selected_values: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    major_intents: dict[str, Any] = {}
    school_intents: dict[str, Any] = {}
    city_intents: dict[str, Any] = {}
    career_intents: dict[str, Any] = {}
    for item in selected_values:
        if not isinstance(item, dict):
            continue
        for source, target in (
            ("major_intents", major_intents),
            ("school_intents", school_intents),
            ("city_intents", city_intents),
            ("career_intents", career_intents),
        ):
            payload = item.get(source)
            if not isinstance(payload, dict):
                continue
            for key, raw_values in payload.items():
                values = _as_text_list(raw_values)
                if not values:
                    continue
                bucket = target.setdefault(str(key or "").strip(), [])
                for value in values:
                    if value not in bucket:
                        bucket.append(value)
    return (
        major_intents or None,
        school_intents or None,
        city_intents or None,
        career_intents or None,
    )


def _selected_values_have_negative_intent(selected_values: list[dict[str, Any]]) -> bool:
    for item in selected_values:
        if not isinstance(item, dict):
            continue
        for payload in item.values():
            if not isinstance(payload, dict):
                continue
            for key, raw_values in payload.items():
                if str(key or "").strip().startswith("negative_") and _as_text_list(raw_values):
                    return True
    return False


def _selected_values_entity_bucket_count(selected_values: list[dict[str, Any]]) -> int:
    buckets = {
        key
        for item in selected_values
        if isinstance(item, dict)
        for key, value in item.items()
        if isinstance(value, dict) and any(_as_text_list(raw_values) for raw_values in value.values())
    }
    return len(buckets)


def _selected_values_have_tuition_budget(selected_values: list[dict[str, Any]]) -> bool:
    for item in selected_values:
        if not isinstance(item, dict):
            continue
        budget = item.get("tuition_budget")
        if not isinstance(budget, dict):
            continue
        if _positive_int_from_structured_value(budget.get("min_tuition_per_year") or budget.get("minTuitionPerYear")) > 0:
            return True
        if _positive_int_from_structured_value(budget.get("max_tuition_per_year") or budget.get("maxTuitionPerYear")) > 0:
            return True
    return False


def _selected_values_have_physical_constraint(selected_values: list[dict[str, Any]]) -> bool:
    for item in selected_values:
        if not isinstance(item, dict):
            continue
        constraints = item.get("physical_constraints") or item.get("physicalConstraints")
        if not isinstance(constraints, dict):
            continue
        if _as_text_list(constraints.get("special_limits") or constraints.get("specialLimits")):
            return True
    return False


def _selected_values_have_only_non_major_positive_scope(selected_values: list[dict[str, Any]]) -> bool:
    has_positive = False
    for item in selected_values:
        if not isinstance(item, dict):
            return False
        for group_key, payload in item.items():
            if group_key == "major_intents":
                return False
            if not isinstance(payload, dict):
                return False
            for key, raw_values in payload.items():
                if str(key or "").startswith("negative_") or str(key or "") == "negative":
                    if _as_text_list(raw_values):
                        return False
                    continue
                if _as_text_list(raw_values):
                    has_positive = True
    return has_positive


def _selected_values_have_only_positive_career_scope(selected_values: list[dict[str, Any]]) -> bool:
    has_positive = False
    for item in selected_values:
        if not isinstance(item, dict):
            return False
        for group_key, payload in item.items():
            if group_key != "career_intents":
                return False
            if not isinstance(payload, dict):
                return False
            for key, raw_values in payload.items():
                values = _as_text_list(raw_values)
                if str(key or "").strip() == "negative":
                    if values:
                        return False
                    continue
                if values:
                    has_positive = True
    return has_positive


def _runtime_intent_profile_can_trust_turn_decision_side_effect(
    *,
    turn_decision: Any | None,
    profile: Any | None,
    selected_values: list[dict[str, Any]],
    intent_mode: str,
    constraint_intent_type: str,
) -> bool:
    if turn_decision is None:
        return False
    confidence = float(getattr(turn_decision, "confidence", 0.0) or 0.0)
    context_resolution = _model_value(profile, "contextResolution", {}) if profile is not None else {}
    context_resolution = context_resolution if isinstance(context_resolution, dict) else {}
    context_used = bool(context_resolution.get("used"))
    context_source = str(context_resolution.get("source") or "").strip()
    context_confidence = _profile_confidence_value(context_resolution.get("confidence"))
    trusted_context_resolution = (
        context_used
        and context_source in {"recentEntityContext", "recentMajorContext"}
        and context_confidence >= 0.8
    )
    if confidence < 0.9 and not (confidence >= 0.85 and trusted_context_resolution):
        return False
    if str(getattr(turn_decision, "taskLayer", "") or "").strip() not in {"intent", "mixed"}:
        return False
    if str(getattr(turn_decision, "sideEffect", "") or "").strip() != "intent_pending":
        return False
    if str(getattr(turn_decision, "scopeAnchor", "") or "").strip() != "future_reference":
        return False
    if str(getattr(turn_decision, "scenario", "") or "").strip() not in {
        "intent_update",
        "region_preference_update",
        "",
    }:
        return False
    if not selected_values:
        return False
    if intent_mode == "constraint" or constraint_intent_type != "default":
        return confidence >= 0.9
    if _selected_values_have_negative_intent(selected_values):
        return confidence >= 0.9
    if _selected_values_have_tuition_budget(selected_values):
        return confidence >= 0.9
    if _selected_values_have_physical_constraint(selected_values):
        return confidence >= 0.9
    if _selected_values_have_only_positive_career_scope(selected_values):
        return trusted_context_resolution
    if _selected_values_have_only_non_major_positive_scope(selected_values):
        return confidence >= 0.9 or trusted_context_resolution
    if _selected_values_entity_bucket_count(selected_values) >= 2:
        return True
    return False


async def _classify_runtime_intent_profile_side_effect(
    *,
    request_context: RequestContext,
    content: str,
    profile: Any,
    selected_values: list[dict[str, Any]],
    intent_mode: str,
) -> Any | None:
    major_intents, school_intents, city_intents, career_intents = _split_runtime_intent_selected_values(selected_values)
    started_at = time.monotonic()
    try:
        decision = await _classify_intent_side_effect(
            latest_utterance=content,
            major_intents=major_intents,
            school_intents=school_intents,
            city_intents=city_intents,
            career_intents=career_intents,
            intent_mode=intent_mode,
        )
    except Exception:
        _record_observability_duration(
            request_context,
            "intentSideEffectDurationMs",
            int((time.monotonic() - started_at) * 1000),
        )
        logger.warning(
            "Runtime intent hard cut side-effect arbitration failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return None
    _record_observability_duration(
        request_context,
        "intentSideEffectDurationMs",
        int((time.monotonic() - started_at) * 1000),
    )
    observability = getattr(request_context, "agent_observability", None)
    if isinstance(observability, dict):
        observability["runtimeIntentSideEffectDecision"] = (
            decision.model_dump() if hasattr(decision, "model_dump") else dict(decision) if isinstance(decision, dict) else {}
        )
    return decision


async def _create_pending_intent_confirmation_from_entity_profile(
    session_id: str,
    *,
    profile: Any,
    batch: str,
) -> WSResponse | None:
    selected_values, intent_mode, constraint_intent_type = _runtime_intent_profile_selected_values(
        profile,
        batch=batch,
    )
    if not selected_values:
        return None
    try:
        merged = merge_selected_values(selected_values)
    except Exception:
        logger.warning("Failed to merge runtime intent profile values: session_id=%s", session_id, exc_info=True)
        return None
    if not merged:
        return None

    admission_path = str(_model_value(profile, "admissionPath", "") or "").strip()
    standard_summary = _summarize_intent_values(
        merged,
        intent_mode=intent_mode,
        constraint_intent_type=constraint_intent_type,
    )
    strength_summary = _intent_entity_profile_strength_display_summary(profile, batch=batch)
    summary = (
        strength_summary
        if strength_summary and _intent_profile_strength_summary_can_cover_merged(merged)
        else standard_summary
    )
    if admission_path == "strongbase":
        summary = f"{summary}；强基路径" if summary else "强基路径"
    if not summary:
        summary = "本次选择的报考想法。"
    selected_data = {
        "selected": selected_values,
        "intentMode": intent_mode,
        "constraintIntentType": constraint_intent_type,
        "batch": batch,
        "displaySummary": summary,
        "entityProfile": (
            profile.model_dump()
            if hasattr(profile, "model_dump")
            else dict(profile)
            if isinstance(profile, dict)
            else {}
        ),
    }
    if admission_path:
        selected_data["admissionPath"] = admission_path
    compiled = proposal_compiler.compile_intent_preview_proposal(
        session_id=session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary=summary,
        constraint_intent_type=constraint_intent_type,
    )
    compiled_sink_metadata = proposal_compiler.intent_sink_metadata_or_none(
        compiled,
        session_id=session_id,
        source="intent_entity_profile",
    )
    if compiled_sink_metadata is None:
        return None
    intent_response = await _create_pending_intent_confirmation_response(
        session_id,
        selected_data=selected_data,
        merged=merged,
        intent_mode=intent_mode,
        batch=batch,
        summary_override=summary,
        impact_payload={
            **merged,
            "admissionPath": admission_path,
        },
        compiled_sink_metadata=compiled_sink_metadata,
    )
    for followup in intent_response.followups:
        if isinstance(followup, WSResponse) and followup.type == "pendingConfirmationCard":
            return followup
    return None


async def _create_runtime_intent_hard_cut_pending_from_prompt(
    *,
    session_id: str,
    request_context: RequestContext,
    content: str,
    history: list[Any] | None = None,
    min_profile_confidence: float = 0.55,
    profile: Any | None = None,
    turn_decision: Any | None = None,
) -> WSResponse | None:
    """Create intent pending for the pre-agent TurnDecision hard-cut path."""

    if profile is None:
        profile_started_at = time.monotonic()
        try:
            profile = await extract_intent_entity_profile(
                content,
                context=_runtime_intent_entity_profile_context(history),
            )
        except Exception:
            _record_observability_duration(
                request_context,
                "intentEntityProfileDurationMs",
                int((time.monotonic() - profile_started_at) * 1000),
            )
            logger.warning(
                "Explicit intent profile extraction failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        _record_observability_duration(
            request_context,
            "intentEntityProfileDurationMs",
            int((time.monotonic() - profile_started_at) * 1000),
        )
    selected_values, intent_mode, constraint_intent_type = _runtime_intent_profile_selected_values(
        profile,
        batch=str(getattr(request_context, "batch", "") or "01"),
    )
    if not selected_values:
        fallback_profile = _runtime_intent_profile_from_turn_decision_target_issue(turn_decision)
        if fallback_profile is not None:
            profile = fallback_profile
            selected_values, intent_mode, constraint_intent_type = _runtime_intent_profile_selected_values(
                profile,
                batch=str(getattr(request_context, "batch", "") or "01"),
            )
            observability = getattr(request_context, "agent_observability", None)
            if isinstance(observability, dict):
                observability["runtimeIntentEntityProfileFallback"] = {
                    "source": "turn_decision_target_issue",
                    "targetIssue": _as_text_list(getattr(turn_decision, "targetIssue", []) or []),
                }
    if float(_model_value(profile, "confidence", 0.0) or 0.0) < min_profile_confidence:
        return None
    if not selected_values:
        return None
    side_effect_decision = None
    readonly_school_or_candidate_query = proposal_compiler.content_has_readonly_school_or_candidate_query_anchor(content)
    if (
        not readonly_school_or_candidate_query
        and _runtime_intent_profile_can_trust_turn_decision_side_effect(
            turn_decision=turn_decision,
            profile=profile,
            selected_values=selected_values,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
    ):
        observability = getattr(request_context, "agent_observability", None)
        if isinstance(observability, dict):
            observability["runtimeIntentSideEffectDecision"] = {
                "decision": "intent_preview",
                "confidence": float(getattr(turn_decision, "confidence", 0.0) or 0.0),
                "constraintIntentType": constraint_intent_type,
                "source": "turn_decision_profile_fast_path",
                "reason": "High-confidence TurnDecision and structured intent profile are sufficient for runtime intent pending.",
            }
            observability["runtimeIntentSideEffectSkipped"] = True
    else:
        if readonly_school_or_candidate_query:
            observability = getattr(request_context, "agent_observability", None)
            if isinstance(observability, dict):
                observability["runtimeIntentSideEffectFastPathBlocked"] = {
                    "reason": "readonly_school_or_candidate_query_anchor",
                }
        side_effect_decision = await _classify_runtime_intent_profile_side_effect(
            request_context=request_context,
            content=content,
            profile=profile,
            selected_values=selected_values,
            intent_mode=intent_mode,
        )
        if side_effect_decision is None:
            return None
        if not (
            str(getattr(side_effect_decision, "decision", "") or "").strip() == "intent_preview"
            and float(getattr(side_effect_decision, "confidence", 0.0) or 0.0) >= 0.7
        ):
            logger.info(
                "Runtime intent hard cut skipped by side-effect arbitration: session_id=%s decision=%s confidence=%s reason=%s",
                session_id,
                str(getattr(side_effect_decision, "decision", "") or "").strip(),
                float(getattr(side_effect_decision, "confidence", 0.0) or 0.0),
                str(getattr(side_effect_decision, "reason", "") or ""),
            )
            return None
    card = await _create_pending_intent_confirmation_from_entity_profile(
        session_id,
        profile=profile,
        batch=str(getattr(request_context, "batch", "") or "01"),
    )
    if card is None:
        return None
    observability = getattr(request_context, "agent_observability", None)
    if isinstance(observability, dict):
        observability["runtimeIntentHardCut"] = {
            "source": "turn_decision_entity_profile",
            "entityType": str(_model_value(profile, "entityType", "") or "").strip(),
            "pendingKind": _pending_card_kind(card),
            "entityProfileContext": _runtime_intent_entity_profile_context(history),
        }
        observability["latestIntentEntityProfile"] = (
            profile.model_dump()
            if hasattr(profile, "model_dump")
            else dict(profile)
            if isinstance(profile, dict)
            else {}
        )
    return card


async def _maybe_handle_runtime_intent_hard_cut(
    *,
    session_id: str,
    user_id: str,
    content: str,
    history: list[Any] | None,
    history_store: ChatHistoryStore,
    request_context: RequestContext,
    planning_summary: PlanningSummary | None,
    pending_state: dict[str, Any] | None,
    score_detail: ScoreDetail | None,
    turn_started_at: float,
    turn_decision: Any | None = None,
    current_plan_mutation_reroute: Callable[[Any], Awaitable[ChatServiceResponseEnvelope | None]] | None = None,
) -> ChatServiceResponseEnvelope | None:
    if not _pending_state_allows_runtime_intent_hard_cut(pending_state):
        return None
    planning_state_profile = _planning_state_profile_for_turn_decision(
        planning_summary=planning_summary,
        pending_state=pending_state,
        score_detail=score_detail,
    )
    decision = turn_decision
    if decision is None:
        try:
            decision = await _classify_turn_decision_cached(
                content,
                request_context=request_context,
                payload={
                    "planningStateProfile": planning_state_profile,
                    "pendingState": pending_state if isinstance(pending_state, dict) else {},
                },
            )
        except Exception:
            logger.warning("Runtime intent hard cut TurnDecision failed: session_id=%s", session_id, exc_info=True)
            return None
    decision_allows_hard_cut = _turn_decision_allows_runtime_intent_hard_cut(
        decision,
        pending_state=pending_state,
    )
    durable_target_issue_profile = _runtime_intent_profile_from_turn_decision_target_issue(decision)
    if (
        decision_allows_hard_cut
        and durable_target_issue_profile is not None
        and not _should_defer_runtime_intent_hard_cut_to_current_plan_action(
            content,
            planning_summary=planning_summary,
        )
    ):
        card = await _create_runtime_intent_hard_cut_pending_from_prompt(
            session_id=session_id,
            request_context=request_context,
            content=content,
            history=history,
            min_profile_confidence=0.75,
            profile=durable_target_issue_profile,
            turn_decision=decision,
        )
        if card is not None:
            _store_current_turn_decision(request_context, decision)
            primary_text = _pending_confirmation_primary_reply_from_card(card)
            if not primary_text:
                primary_text = "已列出这次报考想法预览。\n\n点“采纳”前不会生效。"
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "intent",
                "routingPath": "runtime_intent_hard_cut",
                "routeDecision": {
                    "source": "turn_decision_target_issue",
                    "matched": True,
                    "taskLayer": str(getattr(decision, "taskLayer", "") or "").strip(),
                    "sideEffect": str(getattr(decision, "sideEffect", "") or "").strip(),
                    "scopeAnchor": str(getattr(decision, "scopeAnchor", "") or "").strip(),
                    "scenario": str(getattr(decision, "scenario", "") or "").strip(),
                    "targetIssue": _as_text_list(getattr(decision, "targetIssue", []) or []),
                    "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
                    "hardCutAccepted": True,
                    "entityProfileFallback": True,
                },
                "pendingType": "intent",
                "actionFamily": "apply_selected_intents",
                "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                **_observability_timing_fields(request_context),
                "toolCalls": ["turn_decision", "proposal_compiler.intent"],
                "postProcessingApplied": ["runtime_intent_hard_cut", "turn_decision_target_issue_profile"],
                "status": "success",
                "errorType": None,
            }
            await _save_direct_guard_history(
                history_store,
                session_id,
                history,
                content,
                primary_text,
                model_name="runtime-intent-hard-cut",
                turn_event=turn_event,
                request_context=request_context,
                user_id=user_id,
            )
            _log_conversation_turn_event(**turn_event)
            return ChatServiceResponseEnvelope(primary=primary_text, followups=[card])
    if decision_allows_hard_cut and _should_defer_runtime_intent_hard_cut_to_current_plan_action(
        content,
        planning_summary=planning_summary,
    ):
        observability = getattr(request_context, "agent_observability", None)
        if isinstance(observability, dict):
            observability["runtimeIntentHardCutDeferred"] = {
                "reason": "current_plan_mutation_anchor",
                "formalPlanPresent": True,
            }
        return None
    if decision_allows_hard_cut:
        atomic_should_defer, atomic_arbitration = await _semantic_atomic_plan_action_should_defer_runtime_intent(
            content=content,
            request_context=request_context,
            history=history,
            turn_decision=decision,
        )
        if atomic_should_defer:
            observability = getattr(request_context, "agent_observability", None)
            if isinstance(observability, dict):
                observability["runtimeIntentHardCutDeferred"] = {
                    "reason": "semantic_atomic_plan_action",
                    "formalPlanPresent": _planning_summary_has_formal_plan(planning_summary),
                    "arbitration": atomic_arbitration,
                }
            if _planning_summary_has_formal_plan(planning_summary):
                return None
            needs_plan_first_resolution = proposal_compiler.compile_no_plan_atomic_action_boundary_source(
                content,
                action_family=str(atomic_arbitration.get("actionFamily") or ""),
            )
            if needs_plan_first_resolution.side_effect == "needs_plan_first":
                reply_text = _needs_plan_first_guard_reply(content, needs_plan_first_resolution)
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan",
                    "routingPath": "needs_plan_first_guard",
                    "routeDecision": {
                        "source": "plan_atomic_action_dsl",
                        "matched": True,
                        "route": needs_plan_first_resolution.side_effect,
                        "referenceResolution": needs_plan_first_resolution.reference_resolution,
                        "targetIssues": list(needs_plan_first_resolution.target_issues),
                        "displayPayload": dict(needs_plan_first_resolution.display_payload),
                        "replyPlan": dict(needs_plan_first_resolution.reply_plan),
                        "blockingReasons": list(needs_plan_first_resolution.blocking_reasons),
                        "arbitration": atomic_arbitration,
                    },
                    "pendingType": None,
                    "actionFamily": str(atomic_arbitration.get("actionFamily") or ""),
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    history_store,
                    session_id,
                    history,
                    content,
                    reply_text,
                    model_name="needs-plan-first-atomic-action-guard",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                return ChatServiceResponseEnvelope(primary=reply_text)
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    turn_decision_blocks_intent = _turn_decision_blocks_runtime_intent_hard_cut(decision)
    if (
        not decision_allows_hard_cut
        and turn_decision_blocks_intent
        and side_effect not in {"plan_preview", "readonly_or_plan_preview"}
    ):
        return None
    durable_constraint_intent = False
    profile: Any | None = None
    if (
        not decision_allows_hard_cut
        and turn_decision_blocks_intent
        and side_effect in {"plan_preview", "readonly_or_plan_preview"}
    ):
        profile_started_at = time.monotonic()
        try:
            profile = await extract_intent_entity_profile(
                content,
                context=_runtime_intent_entity_profile_context(history),
            )
        except Exception:
            _record_observability_duration(
                request_context,
                "intentEntityProfileDurationMs",
                int((time.monotonic() - profile_started_at) * 1000),
            )
            logger.warning(
                "Runtime intent hard cut durable constraint profile extraction failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            profile = None
        else:
            _record_observability_duration(
                request_context,
                "intentEntityProfileDurationMs",
                int((time.monotonic() - profile_started_at) * 1000),
            )
        durable_constraint_intent = (
            profile is not None
            and float(_model_value(profile, "confidence", 0.0) or 0.0) >= 0.75
            and _profile_is_durable_constraint_intent(profile)
        )
        if profile is not None:
            observability = getattr(request_context, "agent_observability", None)
            if isinstance(observability, dict):
                observability["latestIntentEntityProfile"] = (
                    profile.model_dump()
                    if hasattr(profile, "model_dump")
                    else dict(profile)
                    if isinstance(profile, dict)
                    else {}
                )
                observability["latestIntentPreviewPayload"] = _intent_preview_payload_from_entity_profile(
                    session_id=session_id,
                    profile=profile,
                    batch=str(getattr(request_context, "batch", "") or "01"),
                )
        if durable_constraint_intent and current_plan_mutation_reroute is not None:
            _store_current_turn_decision(request_context, decision)
            rerouted = await current_plan_mutation_reroute(profile)
            if rerouted is not None:
                return rerouted
        if durable_constraint_intent and _should_defer_runtime_intent_hard_cut_to_current_plan_action(
            content,
            planning_summary=planning_summary,
        ):
            observability = getattr(request_context, "agent_observability", None)
            if isinstance(observability, dict):
                observability["runtimeIntentHardCutDeferred"] = {
                    "reason": "current_plan_action_anchor_after_durable_profile",
                    "formalPlanPresent": True,
                    "turnDecisionSideEffect": side_effect,
                    "turnDecisionScenario": scenario,
                }
            return None
    if (
        not decision_allows_hard_cut
        and turn_decision_blocks_intent
        and side_effect in {"plan_preview", "readonly_or_plan_preview"}
        and not durable_constraint_intent
    ):
        return None
    if not decision_allows_hard_cut and (
        (
            side_effect
            in {
                "apply_pending_then_new_request",
                "apply_pending_then_readonly",
                "conflict_with_existing_pending",
                "profile_change_replan",
                "profile_replan_adhoc",
                "profile_replan_ambiguous",
                "readonly_while_pending",
            }
        )
        or scenario
        in {
            "apply_intent_then_generate_plan",
            "apply_pending_then_readonly_query",
            "plan_query",
            "plan_query_while_pending",
            "profile_adhoc_replan",
            "profile_scope_ambiguous",
            "profile_update_replan",
            "state_query_while_pending",
            "profile_change_state_query",
        }
    ):
        return None

    card = await _create_runtime_intent_hard_cut_pending_from_prompt(
        session_id=session_id,
        request_context=request_context,
        content=content,
        history=history,
        min_profile_confidence=0.55 if decision_allows_hard_cut else 0.75,
        profile=profile if durable_constraint_intent else None,
        turn_decision=decision,
    )
    if card is None:
        return None
    _store_current_turn_decision(request_context, decision)
    primary_text = _pending_confirmation_primary_reply_from_card(card)
    if not primary_text:
        primary_text = "已列出这次报考想法预览。\n\n点“采纳”前不会生效。"
    turn_event = {
        "sessionId": session_id,
        "userId": user_id,
        "scene": "intent",
        "routingPath": "runtime_intent_hard_cut",
        "routeDecision": {
            "source": "turn_decision",
            "matched": True,
            "taskLayer": str(getattr(decision, "taskLayer", "") or "").strip(),
            "sideEffect": str(getattr(decision, "sideEffect", "") or "").strip(),
            "scopeAnchor": str(getattr(decision, "scopeAnchor", "") or "").strip(),
            "scenario": str(getattr(decision, "scenario", "") or "").strip(),
            "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
            "hardCutAccepted": decision_allows_hard_cut,
            "entityProfileFallback": not decision_allows_hard_cut,
        },
        "pendingType": "intent",
        "actionFamily": "apply_selected_intents",
        "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
        **_observability_timing_fields(request_context),
        "toolCalls": ["turn_decision", "intent_entity_profile", "proposal_compiler.intent"],
        "postProcessingApplied": ["runtime_intent_hard_cut"],
        "status": "success",
        "errorType": None,
    }
    await _save_direct_guard_history(
        history_store,
        session_id,
        history,
        content,
        primary_text,
        model_name="runtime-intent-hard-cut",
        turn_event=turn_event,
        request_context=request_context,
        user_id=user_id,
    )
    _log_conversation_turn_event(**turn_event)
    return ChatServiceResponseEnvelope(primary=primary_text, followups=[card])


def _select_conversation_action_family(tool_returns: list[ToolReturnPart]) -> str | None:
    """Choose the action family that best describes the completed turn.

    A plan turn may briefly read state before producing a mutation preview. For
    observability, report the last non-query plan action instead of the first
    low-signal query action.
    """
    families: list[str] = []
    for part in tool_returns:
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family:
            families.append(action_family)
    if not families:
        return None
    for action_family in reversed(families):
        if action_family not in _LOW_PRIORITY_LOG_ACTION_FAMILIES:
            return action_family
    return families[-1]


def _latest_readonly_plan_execution_result(messages: list[Any] | None) -> dict[str, Any] | None:
    readonly_pairs = {
        ("review_plan", "review_result"),
        ("analyze_adjustment", "adjustment_analysis"),
        ("query_state", "status_overview"),
    }
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if (action_family, result_kind) in readonly_pairs:
            return data
    return None


def _latest_review_plan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family == "review_plan" and result_kind == "review_result":
            return data
    return None


def _latest_readonly_plan_query_reply(messages: list[Any] | None) -> str | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "query_volunteer_plan":
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            for key in ("reply", "summary", "message"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _compact_readonly_plan_query_reply(reply: str | None) -> str:
    text = _sanitize_reply_for_user(_normalize_user_facing_terms(str(reply or "").strip()))
    if not text:
        return ""
    match = re.search(
        r"(?P<title>当前方案|当前排序方案|当前已加入方案|候选)里共命中了\s*"
        r"(?P<count>\d+)\s*条(?:符合[“\"](?P<condition>[^”\"]+)[”\"]|和[“\"]?(?P<keyword>[^”\"。]+)[”\"]?相关的(?:志愿|机会))",
        text,
    )
    if match:
        title = match.group("title") or "当前方案"
        count = match.group("count")
        condition = match.group("condition") or match.group("keyword") or "这个条件"
        examples_text = text.split("：", 1)[1] if "：" in text else ""
        examples = [item.strip(" ；;。") for item in re.split(r"；|;", examples_text) if item.strip()]
        scope_label = "候选里" if title == "候选" else "当前方案里"
        item_label = "机会" if title == "候选" else "志愿"
        lines = [f"我查了一下，{scope_label}有 {count} 条和“{condition}”相关的{item_label}。"]
        if examples:
            lines.append("比较典型的有：")
            for item in examples[:3]:
                lines.append(f"- {item}")
        lines.append("这类结果建议重点看学费、录取率、培养方式和是否真的能接受；如果要调整，我会先给你一版调整预览，确认前不会改方案。")
        return "\n".join(lines)
    if len(text) <= 260:
        return text
    return f"{text[:260].rstrip()}...\n\n这只是当前查询到的局部结果；如果要继续调整，我会先给你一版调整预览，确认前不会改方案。"


def _latest_readonly_explore_reply(messages: list[Any] | None) -> str | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES and part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            if (
                part.tool_name in _INTENT_PREVIEW_TOOL_NAMES
                and str(data.get("analysisStage") or "").strip() != "interest"
            ):
                continue
            for key in ("message", "summary", "reply", "state_summary"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _latest_readonly_tool_reply(messages: list[Any] | None) -> str | None:
    """Return substantive read-only tool content for unbacked-confirmation guards."""
    query_reply = _latest_readonly_plan_query_reply(messages)
    if query_reply:
        return _compact_readonly_plan_query_reply(query_reply)

    explore_reply = _latest_readonly_explore_reply(messages)
    if explore_reply:
        return explore_reply

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "answer_admission_policy_question":
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            for key in ("reply", "summary", "message", "answer"):
                value = str(data.get(key) or "").strip()
                if value:
                    return _sanitize_reply_for_user(_normalize_user_facing_terms(value))
            continue
        text = str(part.content or "").strip()
        if text:
            return _sanitize_reply_for_user(_normalize_user_facing_terms(text))
    return None


def _turn_has_readonly_explore_result(messages: list[Any] | None) -> bool:
    return bool(_latest_readonly_explore_reply(messages))


def _reply_contains_readonly_plan_query_facts(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "当前方案里共命中",
            "候选里共命中",
            "当前方案里暂时没有命中",
            "候选里暂时没有命中",
            "下面仅展示",
            "符合“",
        )
    )


def _summarize_tool_calls_for_observability(
    tool_calls: list[ToolCallPart],
    tool_returns: list[ToolReturnPart],
) -> list[dict[str, Any]]:
    """Build compact tool-call metadata for structured logs.

    Persisted history keeps full tool args/results. This summary only carries
    route/action/result fields needed by effect/perf reports.
    """
    returns_by_call_id: dict[str, dict[str, Any]] = {}
    for part in tool_returns:
        call_id = str(part.tool_call_id or "")
        if not call_id:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            returns_by_call_id[call_id] = data

    summarized: list[dict[str, Any]] = []
    for part in tool_calls:
        call_id = str(part.tool_call_id or "")
        args = _parse_tool_call_args(part.args)
        returned = returns_by_call_id.get(call_id) or {}
        item: dict[str, Any] = {"name": part.tool_name}
        if call_id:
            item["toolCallId"] = call_id

        returned_data = returned.get("data") if isinstance(returned.get("data"), dict) else {}
        returned_result = returned_data.get("result") if isinstance(returned_data.get("result"), dict) else {}
        action_family = str(
            args.get("action_family")
            or returned.get("action_family")
            or returned_data.get("action_family")
            or returned_result.get("action_family")
            or ""
        ).strip()
        stage = str(args.get("current_stage") or returned.get("stage") or "").strip()
        if part.tool_name == "execute_plan_action":
            raw_payload = args.get("plan_payload")
            if isinstance(raw_payload, str) and raw_payload.strip():
                try:
                    plan_payload = json.loads(raw_payload)
                except Exception:
                    plan_payload = {}
                if isinstance(plan_payload, dict):
                    action_family = action_family or str(plan_payload.get("action_family") or "").strip()
                    stage = stage or str(plan_payload.get("stage") or "").strip()

        if action_family:
            item["actionFamily"] = action_family
        if stage:
            item["stage"] = stage

        result_kind = str(returned.get("result_kind") or "").strip()
        if result_kind:
            item["resultKind"] = result_kind
        if "applied" in returned:
            item["applied"] = bool(returned.get("applied"))
        message_code = str(returned.get("messageCode") or "").strip()
        if message_code:
            item["messageCode"] = message_code
        if returned:
            item["success"] = result_kind != "error"

        summarized.append(item)
    return summarized


def _latest_confirm_pending_tool_result(
    tool_calls: list[ToolCallPart],
    tool_returns: list[ToolReturnPart],
) -> dict[str, Any]:
    returns_by_call_id: dict[str, dict[str, Any]] = {}
    for part in tool_returns:
        call_id = str(part.tool_call_id or "")
        if not call_id:
            continue
        data = _parse_tool_return_json(part.content)
        if data:
            returns_by_call_id[call_id] = data
    for part in reversed(tool_calls):
        if str(part.tool_name or "") != "confirm_pending":
            continue
        result = returns_by_call_id.get(str(part.tool_call_id or ""))
        return result if isinstance(result, dict) else {}
    return {}


def _direct_confirm_routing_path(confirm_result: dict[str, Any]) -> str:
    data = confirm_result.get("data") if isinstance(confirm_result.get("data"), dict) else {}
    if str(data.get("action") or "").strip() != "confirm":
        return "zhiyuan_agent_direct"
    kind = str(data.get("kind") or "").strip()
    if kind == "plan_mutation":
        return "direct_pending_plan_confirm"
    if kind == "intent_change":
        return "direct_pending_intent_confirm"
    return "zhiyuan_agent_direct"


def _direct_confirm_workspace_refresh_targets(confirm_result: dict[str, Any]) -> list[str]:
    data = confirm_result.get("data") if isinstance(confirm_result.get("data"), dict) else {}
    if str(data.get("action") or "").strip() != "confirm" or data.get("applied") is not True:
        return []
    kind = str(data.get("kind") or "").strip()
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if kind in {"plan_mutation", "plan_generation"}:
        return ["ordered", "review"]
    if kind == "intent_change" and (result.get("has_plan") is True or result.get("plan_regenerated") is True):
        return ["ordered", "review"]
    return []


def _summarize_full_agent_tool_trial(tool_names: list[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for name in tool_names:
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    repeated = [name for name, count in counts.items() if count > 1]
    return {
        "toolNames": list(tool_names),
        "toolNameCounts": counts,
        "repeatedToolNames": repeated,
        "hasRepeatedToolCalls": bool(repeated),
        "hasToolCalls": bool(tool_names),
    }


def _tool_calls_include_plan_workspace_refresh(messages: list[Any] | None) -> list[str]:
    compiled = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=_execute_plan_action_results(messages),
        tool_call_names=[part.tool_name for part in _iter_tool_call_parts(messages)],
        execute_plan_action_call_families=_execute_plan_action_call_families(messages),
    )
    return _dedupe_workspace_targets(compiled.workspace_refresh_targets)


def _tool_context_has_execute_plan_return(messages: list[Any] | None) -> bool:
    return any(part.tool_name == "execute_plan_action" for part in _iter_tool_return_parts(messages))


def _execute_plan_action_results(messages: list[Any] | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if isinstance(data, dict) and data:
            results.append(data)
    return results


def _execute_plan_action_call_families(messages: list[Any] | None) -> list[str]:
    families: list[str] = []
    for part in _iter_tool_call_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        action_family = _extract_execute_plan_action_family(part)
        families.append(action_family or "")
    return families


def _current_turn_workspace_refresh_targets(
    *,
    tool_context_messages: list[Any] | None,
    new_messages: list[Any] | None,
    all_messages: list[Any] | None,
    content: str,
) -> list[str]:
    """Extract workspace refresh only from the current turn."""

    targets = _tool_calls_include_plan_workspace_refresh(tool_context_messages)
    if not targets:
        targets = _tool_calls_include_plan_workspace_refresh(new_messages)
    compiled = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=_execute_plan_action_results(tool_context_messages),
        initial_refresh_targets=targets,
        allow_explanation_refresh=_semantic_query_state_should_run_review(content),
        include_call_fallback=False,
    )
    return _dedupe_workspace_targets(compiled.workspace_refresh_targets)


def _current_turn_workspace_view_targets(
    *,
    tool_context_messages: list[Any] | None,
    all_messages: list[Any] | None,
    content: str,
    turn_decision: Any | None = None,
) -> list[str]:
    current_result = _latest_execute_plan_action_result(tool_context_messages)
    boundary = _latest_user_turn_boundary(all_messages)
    prior_messages = list(all_messages[:boundary] if boundary is not None else [])
    prior_attempt = _latest_plan_mutation_attempt_result(prior_messages)
    compiled = proposal_compiler.compile_runtime_workspace_presentation_source(
        execute_plan_results=_execute_plan_action_results(tool_context_messages),
        include_call_fallback=False,
        include_result_view_targets=False,
        include_post_plan_attempt_view=True,
        current_result=current_result,
        prior_plan_attempt_result=prior_attempt if isinstance(prior_attempt, dict) else None,
        turn_decision=turn_decision,
    )
    return _dedupe_workspace_targets(compiled.workspace_view_targets)


def _plan_result_is_readonly_workspace_no_refresh(action_family: str, result_kind: str) -> bool:
    return proposal_compiler.workspace_plan_result_is_readonly_no_refresh(action_family, result_kind)


def _tool_calls_include_plan_execution(messages: list[Any] | None) -> bool:
    return any(part.tool_name == "execute_plan_action" for part in _iter_tool_call_parts(messages))


def _tool_returns_successful_plan_apply(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if (
            data.get("applied") is True
            and str(data.get("stage") or "").strip() == "apply"
            and action_family in _PENDING_PLAN_ACTION_FAMILIES
        ):
            return True
    return False


def _tool_returns_plan_mutation_context(messages: list[Any] | None) -> bool:
    """Return true when this turn is actually about a plan mutation flow.

    Read-only plan queries may still mention confirming a pending intent. Those
    should not receive the "no executable plan preview" boundary, otherwise the
    user sees a plan-adjustment warning for a preference confirmation.
    """
    mutation_families = set(_PENDING_PLAN_ACTION_FAMILIES)
    mutation_families.update({"analyze_adjustment", "preview_fix_proposal"})
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family in mutation_families:
            return True
    return False


def _tool_returns_mutating_plan_preview(messages: list[Any] | None) -> bool:
    return _extract_plan_confirmation_candidate(messages) is not None


def _latest_fix_proposal_confirmation_source(
    messages: list[Any] | None,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    payloads_by_call_id: dict[str, dict[str, Any]] = {}
    for call in _iter_tool_call_parts(messages):
        payload = _extract_execute_plan_payload(call)
        if isinstance(payload, dict):
            payloads_by_call_id[str(call.tool_call_id or "")] = payload
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        plan_payload = payloads_by_call_id.get(str(part.tool_call_id or "")) or {}
        confirmation_source = proposal_compiler.runtime_fix_proposal_confirmation_source_from_result(
            data,
            plan_payload=plan_payload,
        )
        if confirmation_source is not None:
            latest = confirmation_source
    return latest


def _latest_fix_proposal_preview_result(
    messages: list[Any] | None,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        action_family = str(data.get("action_family") or "").strip()
        if action_family == "preview_fix_proposal" and result_kind == "fix_proposal_preview":
            latest = data
    return latest


def _full_agent_plan_display_source(
    *,
    action_family: str | None,
    tool_context_messages: list[Any] | None,
    pending_card_created: bool,
    turn_decision: Any | None,
) -> proposal_compiler.RuntimeSemanticPlanDisplaySource | None:
    family = str(action_family or "").strip()
    if family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal"}:
        return None
    latest_result = _latest_execute_plan_action_result(tool_context_messages)
    if not isinstance(latest_result, dict) or not latest_result:
        return None
    result_family = str(latest_result.get("action_family") or latest_result.get("actionFamily") or "").strip()
    if result_family and result_family != family:
        return None
    prefer_conditional_options = bool(
        _turn_decision_is_plan_review_or_repair_preview(turn_decision)
    )
    display_source = proposal_compiler.compile_runtime_semantic_plan_display_source(
        action_family=family,
        result=latest_result,
        pending_card_created=pending_card_created,
        prefer_conditional_options=prefer_conditional_options,
    )
    if not display_source.matched:
        return None
    return display_source


def _latest_plan_next_missing_inputs_payload(
    messages: list[Any] | None,
    *,
    action_family: str | None = None,
) -> dict[str, Any] | None:
    target_family = str(action_family or "").strip()
    latest_payload: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "plan_next_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        family = str(data.get("action_family") or "").strip()
        if target_family and family != target_family:
            continue
        missing_inputs = [
            str(item or "").strip()
            for item in (data.get("missing_inputs") or data.get("missingInputs") or [])
            if str(item or "").strip()
        ]
        if not missing_inputs:
            continue
        normalized = normalize_plan_action_payload(dict(data))
        normalized["missing_inputs"] = missing_inputs
        latest_payload = normalized
    return latest_payload


def _latest_turn_allows_plan_followup_confirmation(messages: list[Any] | None) -> bool:
    """Whether a short confirmation should continue a structured plan follow-up.

    This covers turns such as review/analyze replies that only offered to
    generate a preview. They have no active pending action yet, so a short
    "确认/可以" must not be consumed as an apply confirmation.
    """
    turn_messages = _messages_after_index(messages, _latest_user_turn_boundary(messages))
    if _extract_plan_confirmation_candidate(turn_messages) is not None:
        return False
    for part in _iter_tool_return_parts(turn_messages):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        proposals = fix_facts.get("proposals") if isinstance(fix_facts, dict) else None
        if (
            action_family == "review_plan"
            and result_kind == "review_result"
            and isinstance(proposals, list)
            and proposals
        ):
            return True
        if action_family == "preview_fix_proposal" and result_kind in {
            "fix_proposal_preview",
            "preview_only",
        }:
            return True
    return False


def _latest_plan_semantic_route_context(messages: list[Any] | None) -> dict[str, Any]:
    """Return structured plan facts for semantic routing.

    This intentionally uses only prior tool results and assistant-side state,
    never raw user wording.  The semantic classifier may use these facts to
    decide whether the next user turn asks for a repair preview.
    """
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal", "query_state"}:
            continue
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
        proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
        strategy_counts: dict[str, int] = {}
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            strategy = str(proposal.get("strategy") or "").strip()
            if strategy:
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        proposal_summaries: list[dict[str, Any]] = []
        ordered_proposals = sorted(
            [proposal for proposal in proposals if isinstance(proposal, dict)],
            key=lambda proposal: (
                0 if str(proposal.get("status") or "").strip() == "ready" else 1,
                0 if str(proposal.get("status") or "").strip() == "preview_only" else 1,
            ),
        )
        for proposal in ordered_proposals[:8]:
            if not isinstance(proposal, dict):
                continue
            proposal_summaries.append(
                {
                    "proposalId": str(proposal.get("proposal_id") or proposal.get("proposalId") or "").strip(),
                    "status": str(proposal.get("status") or "").strip(),
                    "strategy": str(proposal.get("strategy") or "").strip(),
                    "sourceCheckCodes": [
                        str(code or "").strip()
                        for code in (proposal.get("source_check_codes") or proposal.get("sourceCheckCodes") or [])
                        if str(code or "").strip()
                    ],
                    "title": _normalize_fix_proposal_user_text(str(proposal.get("title") or "").strip()),
                    "summary": _normalize_fix_proposal_user_text(str(proposal.get("summary") or "").strip()),
                }
            )
        return {
            "lastActionFamily": action_family,
            "lastResultKind": result_kind,
            "summary": _normalize_fix_proposal_user_text(str(data.get("summary") or data.get("state_summary") or "").strip()),
            "replyFocus": data.get("reply_focus") if isinstance(data.get("reply_focus"), list) else [],
            "fixProposals": {
                "readyCount": _as_int(fix_facts.get("ready_count")),
                "blockedCount": _as_int(fix_facts.get("blocked_count")),
                "previewOnlyCount": _as_int(fix_facts.get("preview_only_count")),
                "proposalSource": str(
                    fix_facts.get("proposal_source")
                    or fix_facts.get("proposalSource")
                    or ""
                ).strip(),
                "strategyCounts": strategy_counts,
                "strategies": list(strategy_counts.keys()),
                "proposals": proposal_summaries,
            },
        }
    return {}


def _latest_review_fix_proposal_route_context(messages: list[Any] | None) -> dict[str, Any]:
    """Return the latest review/analysis context that carries fix proposals.

    A later failed atomic mutation can appear after a successful review in the
    same model turn. For repair recovery we still need the review facts; the
    failed mutation should not erase the structured review issue scope.
    """

    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family not in {"review_plan", "analyze_adjustment", "preview_fix_proposal"}:
            continue
        if result_kind not in {"review_result", "adjustment_analysis", "fix_proposal_preview"}:
            continue
        context = _latest_plan_semantic_route_context(
            [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="execute_plan_action",
                            content=json.dumps(data, ensure_ascii=False, default=str),
                            tool_call_id="review-fix-proposal-route-context",
                        )
                    ]
                )
            ]
        )
        fix_facts = context.get("fixProposals") if isinstance(context, dict) else None
        if isinstance(fix_facts, dict) and (
            _as_int(fix_facts.get("readyCount")) > 0
            or _as_int(fix_facts.get("blockedCount")) > 0
            or _as_int(fix_facts.get("previewOnlyCount")) > 0
            or bool(fix_facts.get("proposals"))
        ):
            return context
    return {}


def _has_plan_semantic_route_context(
    planning_summary: PlanningSummary | None,
    recent_plan_context: dict[str, Any] | None,
) -> bool:
    if planning_summary is None:
        return False
    if (
        int(getattr(planning_summary, "ordered_total", 0) or 0) > 0
        or int(getattr(planning_summary, "working_total", 0) or 0) > 0
        or int(getattr(planning_summary, "review_risk_count", 0) or 0) > 0
        or int(getattr(planning_summary, "review_warn_count", 0) or 0) > 0
    ):
        return True
    fix_facts = (recent_plan_context or {}).get("fixProposals")
    return isinstance(fix_facts, dict) and any(
        _as_int(fix_facts.get(key)) > 0
        for key in ("readyCount", "blockedCount", "previewOnlyCount")
    )


def _semantic_preview_fix_proposal_route_allowed(
    decision: Any,
    recent_plan_context: dict[str, Any] | None,
) -> bool:
    return proposal_compiler.review_context_supports_fix_preview_route(
        decision,
        recent_plan_context,
    )


def _semantic_decision_requests_fix_preview(
    decision: Any,
    *,
    require_issue_code_for_non_preview: bool,
) -> bool:
    return proposal_compiler.semantic_decision_requests_fix_preview(
        decision,
        confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
    )


def _plan_context_has_fix_proposals(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict) or not context:
        return False
    fix_facts = context.get("fixProposals")
    if not isinstance(fix_facts, dict):
        return False
    return (
        _as_int(fix_facts.get("readyCount")) > 0
        or _as_int(fix_facts.get("blockedCount")) > 0
        or _as_int(fix_facts.get("previewOnlyCount")) > 0
        or bool(fix_facts.get("proposals"))
    )


def _tool_calls_include_plan_chain(messages: list[Any] | None) -> bool:
    plan_tool_names = {
        "collect_plan_context_inputs",
        "plan_next_action",
        "execute_plan_action",
        "query_volunteer_plan",
    }
    return any(part.tool_name in plan_tool_names for part in _iter_tool_call_parts(messages))


def _turn_has_structured_plan_result(messages: list[Any] | None) -> bool:
    """Whether the latest turn already has structured Plan facts.

    This is used only by post-processing recovery guards. When a review or
    adjustment tool has returned structured facts, we should not start an
    unrelated Intent recovery just because the model used confirmation-like
    wording in its final prose.
    """

    turn_messages = _messages_after_index(messages, _latest_user_turn_boundary(messages))
    if not turn_messages:
        turn_messages = list(messages or [])
    for part in _iter_tool_return_parts(turn_messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family in {
            "review_plan",
            "analyze_adjustment",
            "preview_fix_proposal",
            "query_state",
            "query_ordered",
            "query_candidates",
        }:
            return True
        if result_kind in {
            "review_result",
            "adjustment_analysis",
            "fix_proposal_preview",
            "status_overview",
            "ordered_query",
            "candidate_query",
        }:
            return True
    return False


async def _candidate_query_should_bypass_semantic_plan_action(
    content: str,
    *,
    request_context: RequestContext,
) -> bool:
    """Let read-only candidate opportunity queries stay on the local query path.

    This uses the shared LLM-backed candidate filter extractor instead of a
    phrase shortcut. The semantic plan-action shortcut is only for review and
    repair explanations; candidate opportunity lookup should be answered by
    `query_volunteer_plan(scope="candidate")` in the full agent path.
    """

    try:
        result = await extract_candidate_query_filters_async(
            content,
            batch=getattr(request_context, "batch", None),
        )
    except Exception:
        logger.warning(
            "Candidate query semantic bypass extraction failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return False
    if not bool((result or {}).get("should_query_candidate")):
        return False
    try:
        confidence = float((result or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.7:
        return False
    filters = (result or {}).get("filters") if isinstance(result, dict) else {}
    if not isinstance(filters, dict):
        return False
    return any(bool(filters.get(key)) for key in (
        "tiers",
        "province_names",
        "city_names",
        "school_keywords",
        "major_keywords",
        "school_tags",
        "major_tags",
    ))


def _tool_calls_include_intent_preview(messages: list[Any] | None) -> bool:
    return any(part.tool_name in _INTENT_PREVIEW_TOOL_NAMES for part in _iter_tool_call_parts(messages))


def _semantic_decision_requests_intent_preview(decision: dict[str, Any] | None) -> bool:
    if not isinstance(decision, dict):
        return False
    return (
        str(decision.get("decision") or "").strip() == "intent_preview"
        and float(decision.get("confidence") or 0.0) >= 0.7
    )


def _tool_calls_allow_unbacked_intent_recovery(
    messages: list[Any] | None,
    *,
    semantic_intent_preview: bool = False,
) -> bool:
    tool_names = [str(part.tool_name or "").strip() for part in _iter_tool_call_parts(messages)]
    if not tool_names:
        return True
    if all("intent" in name for name in tool_names if name):
        return True
    if semantic_intent_preview and _tool_calls_include_plan_chain(messages):
        return _extract_plan_confirmation_candidate(messages) is None
    return False


def _reply_indicates_unresolved_readonly_plan_query(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "没有稳定收敛",
            "没能稳定收敛",
            "没有拿到稳定结果",
            "没有稳定结果",
            "先不继续重复查询",
            "不继续重复查询",
            "换一个更具体的条件",
            "这轮查询没有稳定",
        )
    )


def _plan_chain_allows_intent_recovery(
    messages: list[Any] | None,
    *,
    reply: str | None = None,
) -> bool:
    """Allow structured intent recovery after a read-only Plan misroute.

    This is a guardrail for turns such as "排除某地域，再看候选": if the model
    only queried plan/candidate data and produced no confirmable preview, the
    service can ask the Intent tool to recover a pending update from the current
    utterance. The recovery itself still decides whether a real intent exists.
    """
    if not _tool_calls_include_plan_chain(messages):
        return False
    if _tool_calls_include_intent_preview(messages):
        return False
    if _extract_plan_confirmation_candidate(messages) is not None:
        return False
    if _latest_turn_has_plan_mutation_preview(messages):
        return False
    if not _latest_turn_looks_readonly(messages):
        return False
    return _reply_indicates_unresolved_readonly_plan_query(reply)


def _plan_chain_failed_without_pending_preview(messages: list[Any] | None) -> bool:
    """Detect a misrouted Plan chain that produced no actionable preview.

    This is intentionally based on structured tool results, not on user wording.
    If the main agent sent an explicit preference/constraint update through a
    Plan action and that Plan action failed before producing a pending preview,
    the service can ask the Intent tool to recover the structured intent.
    """

    if not _tool_calls_include_plan_chain(messages):
        return False
    if _extract_plan_confirmation_candidate(messages) is not None:
        return False
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        action_family = str(data.get("action_family") or "").strip()
        if result_kind == "error":
            reply_focus = {
                str(item or "").strip()
                for item in (data.get("reply_focus") or [])
                if str(item or "").strip()
            }
            if reply_focus & {
                "missing_inputs",
                "needs_candidate_selection",
                "needs_volunteer_selection",
                "replacement_scope_required",
                "replacement_scope_unresolved",
                "replacement_scope_insufficient",
                "unsupported_action",
                "stale_pending",
                "confirmation_invalid",
            }:
                return False
            if action_family in _PENDING_PLAN_ACTION_FAMILIES:
                return False
            return True
        if action_family == "preview_fix_proposal" and result_kind in {"no_change", "preview_only"}:
            facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
            fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
            proposals = fix_facts.get("proposals") if isinstance(fix_facts, dict) else None
            if not proposals:
                return True
    return False


def _tool_returns_intent_non_pending(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("status") or "").strip() in {"existing_only", "empty"}:
            return True
        text = str(getattr(part, "content", "") or "")
        if _is_existing_only_intent_notice_text(text):
            return True
    return False


def _latest_existing_only_intent_payload(messages: list[Any] | None) -> dict[str, Any] | None:
    payload = _extract_recent_intent_analysis_payload(messages)
    if not isinstance(payload, dict):
        return None
    if str(payload.get("status") or "").strip() != "existing_only":
        return None
    if str(payload.get("analysisStage") or "").strip() != ANALYSIS_STAGE_CONFIRMED:
        return None
    return payload


def _build_existing_only_no_plan_reply(payload: dict[str, Any] | None) -> str:
    merged = _merge_existing_intent_payload(payload)
    summary = _summarize_intent_values(
        merged,
        intent_mode=str((payload or {}).get("intentMode") or "constraint").strip() or "constraint",
        constraint_intent_type=str(
            (payload or {}).get("constraintIntentType")
            or (payload or {}).get("constraint_intent_type")
            or "default"
        ).strip() or "default",
    )
    lines = ["这条报考想法已经记录过，本轮不用重复采纳。"]
    if summary:
        lines.append(f"当前记录：{summary}。")
    lines.append("现在还没有可调整的方案或候选结果，所以这一步不会直接改方案。")
    lines.append("下一步可以先生成候选和方案；有方案后，我再按这条想法帮你检查哪些需要保留、替换或移出。")
    return _sanitize_reply_for_user("\n".join(lines))


def _tool_returns_interest_stage_intent_analysis(messages: list[Any] | None) -> bool:
    for part in _iter_tool_return_parts(messages):
        if part.tool_name in _INTENT_INTEREST_ANALYSIS_TOOL_NAMES:
            data = _parse_tool_return_json(part.content)
            if isinstance(data, dict):
                analysis_stage = str(data.get("analysisStage") or "").strip()
                status = str(data.get("status") or "").strip()
                if analysis_stage == ANALYSIS_STAGE_CONFIRMED and status in {"ready", "existing_only"}:
                    continue
            return True
        if part.tool_name not in _INTENT_PREVIEW_TOOL_NAMES:
            continue
        data = _parse_tool_return_json(part.content)
        if str((data or {}).get("analysisStage") or "").strip() == "interest":
            return True
    return False


def _normalize_pending_intent_reply(reply: str) -> str:
    if not isinstance(reply, str):
        return reply
    normalized = reply
    replacements = (
        ("好的，我记下了你对", "我先把你对"),
        ("好的，我已经记下了你对", "我先把你对"),
        ("我记下了你对", "我先把你对"),
        ("我已经记下了你对", "我先把你对"),
        ("好的，我记下了", "我先整理一下"),
        ("好的，我已经记下了", "我先整理一下"),
        ("我已经按你的偏好记录下来", "我先把这个想法整理出来，等你点“采纳”后再作为后续参考"),
        ("我已经记录下来", "我先把这个想法整理出来，等你点“采纳”后再作为后续参考"),
        ("我先把这个偏好整理成待确认参考，你确认后我再正式生效。", "我先把这个想法列出来，点“采纳”前不会生效。"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if normalized != reply and "确认" not in normalized:
        normalized = normalized.rstrip("。") + "。如果要按这个方向作为后续参考，请点“采纳”。"
    return normalized


def _normalize_unbacked_recorded_wording(reply: str) -> str:
    """Avoid implying that a read-only conclusion has been saved as user intent."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    normalized = reply
    replacements = (
        ("这个判断可以先记下来", "这个判断可以先作为当前分析结论参考"),
        ("这个结论可以先记下来", "这个结论可以先作为当前分析结论参考"),
        ("这个方向可以先记下来", "这个方向可以先作为当前讨论方向参考"),
        ("我先帮你把思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先帮你把这个思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先把思路记下来", "我先把这个思路作为当前对话参考"),
        ("我先把这个思路记下来", "我先把这个思路作为当前对话参考"),
        ("把思路记下来", "把这个思路作为当前对话参考"),
        ("帮你把思路记下来", "把这个思路作为当前对话参考"),
        ("记下来，不会自动修改你的方案", "作为当前对话参考，不会改动当前方案"),
        ("不会自动修改你的方案", "不会改动当前方案"),
        ("先记下来", "先作为当前结论参考"),
        ("我先记下来", "我先按当前结论理解"),
        ("我会先记下来", "我会先按当前结论理解"),
        ("确认采纳前都不会生效", "如果要正式采用，我会先列出要采用的内容或调整预览；确认前不会执行"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"(?m)^好的，明白了。你倾向(.+?)这个方向，",
        r"好的，先按刚才的分析结论理解：\1这个方向",
        normalized,
    )
    normalized = re.sub(
        r"(?m)^好的，明白了。你更倾向(.+?)这个方向，",
        r"好的，先按刚才的分析结论理解：\1这个方向",
        normalized,
    )
    return normalized


_FALSE_APOLOGY_PREFIX_RE = re.compile(
    r"^\s*抱歉[，,]\s*刚才[^。！？!?]*(?:没有|没)[^。！？!?]*(?:回应|回答|答复)[^。！？!?]*[。！？!?]\s*(?:让我重新[^。！？!?]*[。！？!?]\s*)?",
    re.MULTILINE,
)


def _history_has_prior_assistant_reply(history: list[Any] | None) -> bool:
    for message in history or []:
        if isinstance(message, ModelResponse):
            if any(isinstance(part, TextPart) and str(part.content or "").strip() for part in message.parts):
                return True
            continue
        if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "assistant":
            if str(message.get("content") or "").strip():
                return True
    return False


def _normalize_false_apology_reply(reply: str, history: list[Any] | None) -> str:
    """Remove model-invented self-correction in clean first-turn contexts."""
    if not isinstance(reply, str) or not reply.strip() or _history_has_prior_assistant_reply(history):
        return reply
    normalized = _FALSE_APOLOGY_PREFIX_RE.sub("", reply, count=1).lstrip()
    return normalized or reply


def _normalize_general_confirmation_protocol_wording(reply: str) -> str:
    """Keep tool-less meta answers aligned with the card-confirmation protocol."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    normalized = reply
    confirmation_boundary = "我会先把要采用的内容列出来，点“采纳”前不会覆盖原来的想法，也不会自动改候选或方案"
    replacements = (
        (
            "直接告诉我就行",
            "直接告诉我，我会先把要采用的内容列出来，等你点“采纳”后再生效",
        ),
        (
            "你直接告诉我新的想法就行",
            "你可以直接告诉我新的想法，我会先把要采用的内容列出来，等你点“采纳”后再生效",
        ),
        (
            "直接告诉我新的想法就行",
            "可以直接告诉我新的想法，我会先把要采用的内容列出来，点“采纳”前不会生效",
        ),
        (
            "我就能按新的要求重新筛选",
            "点“采纳”前不会自动改候选或方案；采纳后我再按新的要求继续看候选和方案",
        ),
        (
            "我就能重新调整推荐口径和候选志愿",
            "我会先把要采用的内容列出来；采纳后再调整推荐口径和候选志愿",
        ),
        (
            "我会重新整理，不会锁定之前的偏好",
            "我会先重新列出要采用的内容；点“采纳”前不会覆盖之前的想法，也不会自动改候选或方案",
        ),
        (
            "随时可以在对话里改",
            "随时可以在对话里提出调整；我会先把要采用的内容列出来，点“采纳”前不会生效",
        ),
        (
            "在我们这里，随时能改",
            f"在我们这里，随时可以提出调整；{confirmation_boundary}",
        ),
        (
            "随时能改",
            f"随时可以提出调整；{confirmation_boundary}",
        ),
        (
            "都是可以根据新想法调整的",
            f"都可按新想法调整；{confirmation_boundary}",
        ),
        (
            "可以根据新想法调整",
            f"可按新想法调整；{confirmation_boundary}",
        ),
        (
            "调整偏好后，系统会重新筛选符合条件的院校和专业",
            "如果要正式更新这个想法，我会先列出来让你采纳；采纳后，再按新的想法重新筛选符合条件的院校和专业",
        ),
        (
            "调整后会重新匹配候选机会，已生成的方案也可以同步更新",
            "如果要正式调整，我会先列出调整内容；采纳后再重新匹配候选机会，已生成的方案也会按确认后的动作更新",
        ),
        (
            "修改偏好后可以重新生成或局部调整",
            "如果要按新偏好重新生成或局部调整方案，我会先给出确认预览",
        ),
        (
            "改了之后，重新生成或调整方案即可",
            "采纳后，再按新偏好重新生成或调整方案",
        ),
        (
            "增删、替换、调整顺序都可以",
            "增删、替换、调整顺序都可以，但都会先给确认预览，点击采纳前不会改动方案",
        ),
        (
            "可以重新生成方案",
            "可以重新生成方案，执行前也会先让你确认",
        ),
        (
            "再决定是否更新到后续推荐中",
            "再决定是否列出来让你采纳；点“采纳”前不会更新到后续推荐中",
        ),
        (
            "我先帮你整理成待确认偏好",
            "我可以先把这个想法列出来，点“采纳”前不会写入后续报考参考",
        ),
        (
            "先帮你整理成待确认偏好",
            "先把这个想法列出来，点“采纳”前不会写入后续报考参考",
        ),
        (
            "把这个偏好先记下来",
            "把这个想法列出来，点“采纳”前不会作为后续参考",
        ),
        (
            "把偏好先记下来",
            "把想法列出来，点“采纳”前不会作为后续参考",
        ),
        (
            "先保存这个思路",
            "先把这个思路列出来让你采纳",
        ),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"(?:有的话可以)?(?:直接)?告诉我[，,]?我帮你记成后续参考[。！？]?",
        "如果要正式采用，我会先把要采用的内容列出来；点“采纳”前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"我(?:先|会先|可以先)?帮你记成后续参考[。！？]?",
        "我会先把要采用的内容列出来；点“采纳”前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"我可以先整理成待确认(?:偏好|要求|意向|内容)[，,]?\s*确认后",
        "我可以先把要采用的内容列出来；点“采纳”前不会生效。采纳后",
        normalized,
    )
    normalized = re.sub(
        r"我可以把(?P<topic>[^。！？\n]{0,100}?)整理成待确认(?:偏好|要求|意向|内容)[，,]?\s*确认后(?P<verb>会|再)",
        r"我可以先把\g<topic>列出来；点“采纳”前不会生效，采纳后\g<verb>",
        normalized,
    )
    normalized = normalized.replace("我可以先整理成待确认偏好", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以先整理成待确认要求", "我可以先把这个报考条件列出来")
    normalized = normalized.replace("我可以先整理成待确认意向", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以先整理成待确认内容", "我可以先把要采用的内容列出来")
    normalized = normalized.replace("我先帮你整理成待确认偏好", "我先把这个想法列出来")
    normalized = normalized.replace("我先帮你整理成待确认要求", "我先把这个报考条件列出来")
    normalized = normalized.replace("我先帮你整理成待确认内容", "我先把要采用的内容列出来")
    normalized = normalized.replace("待确认偏好", "待采纳想法")
    normalized = normalized.replace("待确认要求", "待采纳报考条件")
    normalized = normalized.replace("待确认意向", "待采纳想法")
    normalized = re.sub(
        r"我可以整理成确认(?:偏好|要求|内容)[。；;]?\s*你确认后[，,]",
        "我可以先把要采用的内容列出来；点“采纳”前不会生效。采纳后，",
        normalized,
    )
    normalized = normalized.replace("我可以整理成确认偏好", "我可以先把这个想法列出来")
    normalized = normalized.replace("我可以整理成确认要求", "我可以先把这个报考条件列出来")
    normalized = normalized.replace("我可以整理成确认内容", "我可以先把要采用的内容列出来")
    normalized = normalized.replace("确认卡片，采纳后", "待采纳内容；采纳后")
    normalized = normalized.replace("不会生效。，采纳后", "不会生效；点击采纳后")
    normalized = normalized.replace("不会生效。，点击采纳后", "不会生效；点击采纳后")
    if any(marker in normalized for marker in ("确认卡片", "待采纳内容", "列出来让你采纳", "要采用的内容列出来")):
        consistency_replacements = (
            ("，改完立刻生效", ""),
            ("改完立刻生效", "采纳后生效"),
            ("你确认后，我会", "采纳后，我会"),
            ("确认后，我会", "采纳后，我会"),
            ("你确认后再", "采纳后再"),
            ("确认后再", "采纳后再"),
            ("确认后会", "采纳后会"),
            ("如果孩子现在就有新想法，直接告诉我，我立刻帮你调整方案。", "如果孩子现在有新想法，我会先列出要采用的内容或调整预览；点“采纳”前不会改候选或方案。"),
            ("我立刻帮你调整方案", "我会先列出调整内容，采纳后再调整方案"),
            ("立刻帮你调整方案", "先列出调整内容，采纳后再调整方案"),
            ("我直接帮你调整方案", "我会先列出调整内容，采纳后再调整方案"),
            ("直接帮你调整方案", "先列出调整内容，采纳后再调整方案"),
            ("确认前", "采纳前"),
        )
        for source, target in consistency_replacements:
            normalized = normalized.replace(source, target)
    has_confirmation_boundary = (
        "采纳/确认前不会生效" in normalized
        or "采纳前不会生效" in normalized
        or "确认前不会生效" in normalized
        or "采纳后再" in normalized
    )
    if (
        "确认卡片" not in normalized
        and not has_confirmation_boundary
        and _reply_discusses_changeable_intent_or_plan(normalized)
    ):
        compact_normalized = _compact_plan_reply_text(normalized)
        explicit_unadopted_impact = any(
            marker in compact_normalized
            for marker in (
                "影响当前方案",
                "需要替换",
                "需要补充",
                "需要移除",
                "需要删除",
            )
        )
        boundary_prefix = "采纳/确认前不会生效，" if explicit_unadopted_impact else ""
        normalized = (
            normalized.rstrip()
            + "\n\n如果后面要正式更新想法、报考条件或方案，可以直接说清楚要采用的内容；"
            f"{boundary_prefix}我会先列明具体影响或调整预览，再让你决定是否采用。"
        )
    return _normalize_user_facing_terms(normalized)


def _reply_discusses_changeable_intent_or_plan(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    has_changeable_subject = any(marker in compact for marker in ("偏好", "排除项", "方案内容", "当前方案", "志愿"))
    has_changeable_action = any(marker in compact for marker in ("可以改", "可以调整", "随时都可以调整", "随时可以调整", "增删", "替换", "调整顺序", "重新生成"))
    return has_changeable_subject and has_changeable_action


def _reply_is_existing_only_intent_notice(reply: str) -> bool:
    return _is_existing_only_intent_notice_text(str(reply or ""))


def _is_existing_only_intent_notice_text(text: str) -> bool:
    normalized = str(text or "")
    compact = _compact_plan_reply_text(normalized)
    if not compact:
        return False
    has_existing_notice = any(
        marker in compact
        for marker in (
            "这个想法当前已经在报考参考里",
            "当前已经在后续报考参考",
            "已经作为后续报考参考",
            "已作为参考",
        )
    )
    has_no_duplicate_notice = any(marker in compact for marker in ("本轮不用重复采纳", "本轮不会重复新增"))
    return has_existing_notice and has_no_duplicate_notice


def _reply_claims_intent_recorded_without_pending(reply: str) -> bool:
    return proposal_compiler.runtime_reply_claims_intent_recorded_without_pending(reply)


def _recorded_intent_claim_without_pending_reply(reply: str) -> str:
    subject = ""
    for pattern in (
        r"[“\"]([^”\"\n]{1,80})[”\"]",
        r"把([^。！？\n]{1,80}?)(?:作为后续|写入|记下来)",
    ):
        match = re.search(pattern, reply or "")
        if match:
            subject = str(match.group(1) or "").strip(" ，,。")
            if subject:
                break
    subject_prefix = f"这次关于“{subject}”的想法" if subject else "这次想法"
    return (
        f"{subject_prefix}还没有写入后续报考参考，也没有生成可采纳内容。"
        "如果要正式采用，我会先列清楚要采用的内容或调整预览；"
        "你确认或点“采纳”前，不会写入后续报考参考，也不会改动当前方案。"
    )


def _reply_looks_like_unbacked_intent_preview(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    claimed_clickable_card = _reply_claims_clickable_intent_card(reply)
    has_pending_heading = (
        "待确认内容" in compact
        or "待采纳内容" in compact
        or "整理成待确认" in compact
        or "列出要采纳" in compact
        or "准备采纳的方向" in compact
        or "准备采纳的内容" in compact
        or "准备采用的方向" in compact
        or "准备采用的内容" in compact
    )
    has_specific_intent_items = any(
        marker in reply
        for marker in (
            "倾向：",
            "倾向:",
            "- 倾向",
            "排除：",
            "排除:",
            "- 排除",
            "偏好专业",
            "排除专业",
            "偏好地域",
            "地域偏好",
            "院校偏好",
            "排除省份",
            "排除城市",
            "排除地域",
            "排除地区",
            "避开的地域",
            "避开的地区",
            "避开地域",
            "避开地区",
            "不优先考虑",
            "只保留专业",
            "只保留专业门类",
            "只保留专业类",
            "只保留：",
            "只保留:",
            "优先范围：",
            "优先范围:",
            "排除范围：",
            "排除范围:",
            "排除：",
            "排除:",
            "优先保留",
            "过滤掉",
        )
    )
    has_text_confirmation_request = any(
        marker in compact
        for marker in (
            "回复确认",
            "直接回复确认",
            "请点采纳",
            "点采纳",
            "点击采纳",
            "采纳前不会生效",
            "确认就",
            "确认是否",
            "请确认是否",
            "是否采纳",
            "如果你确认",
            "你确认后",
            "确认采纳",
            "确认这个",
            "按上面执行",
            "你确认要这样记",
            "确认要这样记",
        )
    )
    has_unbacked_confirm_effect = (
        any(marker in compact for marker in ("确认后", "如果你确认", "你确认", "确认要这样记"))
        and any(
            marker in compact
            for marker in (
                "后续参考",
                "偏好",
                "排除",
                "过滤",
                "优先保留",
                "记入",
                "记录",
                "避开",
                "不优先",
                "地域",
                "地区",
                "城市",
                "省份",
            )
        )
    )
    if claimed_clickable_card:
        return True
    if has_pending_heading and not has_specific_intent_items:
        return False
    if not has_pending_heading and not has_text_confirmation_request:
        return False
    if not has_pending_heading and not has_specific_intent_items:
        return False
    return has_text_confirmation_request or has_unbacked_confirm_effect


def _line_looks_like_unbacked_intent_confirmation(compact: str) -> bool:
    if "确认" not in compact:
        return False
    return any(
        marker in compact
        for marker in (
            "后续报考参考",
            "后续参考",
            "推荐口径",
            "生成或调整方案",
            "作为后续",
            "作为偏好",
            "作为要求",
            "偏好",
            "排除",
            "过滤",
            "优先保留",
            "记入",
            "记录",
            "避开",
            "不优先",
            "地域",
            "地区",
            "城市",
            "省份",
        )
    )


def _remove_unbacked_intent_confirmation_copy(reply: str) -> str:
    if not isinstance(reply, str) or not reply.strip():
        return reply

    normalized_lines: list[str] = []
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", raw_line)
        if len(sentence_parts) <= 1:
            compact = re.sub(r"\s+", "", stripped)
            if _line_looks_like_unbacked_intent_confirmation(compact):
                continue
        if not sentence_parts:
            normalized_lines.append(raw_line.rstrip())
            continue
        kept_parts = []
        for part in sentence_parts:
            compact_part = re.sub(r"\s+", "", part)
            if _line_looks_like_unbacked_intent_confirmation(compact_part):
                continue
            kept_parts.append(part)
        line = "".join(kept_parts).rstrip()
        if line.strip():
            normalized_lines.append(line)

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def _reply_claims_clickable_intent_card(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    if not any(marker in compact for marker in ("确认卡片", "待采纳内容")):
        return False
    has_card_created_claim = any(
        marker in compact
        for marker in (
            "已经生成",
            "已生成",
            "生成了",
            "已经为你生成",
            "已为你生成",
            "已经为你整理",
            "已为你整理",
            "已经整理",
            "已整理",
            "我已把",
            "这张确认卡片",
            "已经列出",
            "已列出",
            "已经为你列出",
            "已为你列出",
            "这次待采纳内容",
        )
    )
    has_click_effect = any(
        marker in compact
        for marker in (
            "点击采纳",
            "点击卡片",
            "采纳后",
            "才会生效",
            "不会生效",
            "写入后续",
            "后续报考参考",
        )
    )
    return has_card_created_claim and has_click_effect


def _normalize_unbacked_intent_preview_reply(reply: str) -> str:
    """Avoid fake pending intent previews when the model did not call preview tools."""
    if not _reply_looks_like_unbacked_intent_preview(reply):
        return reply
    if "待确认内容" not in _compact_plan_reply_text(reply):
        stripped = _remove_unbacked_intent_confirmation_copy(reply).strip()
        if stripped and not _reply_looks_like_unbacked_intent_preview(stripped):
            return _normalize_user_facing_terms(
                stripped.rstrip()
                + "\n\n补充说明：这轮还没有列出可采纳的内容，也不会写入后续参考或改动方案；"
                "如果要正式采用，我会先把要采用的内容列出来，点“采纳”后才会生效。"
            )
        return (
            "这轮我还没有列出可采纳的内容，所以不会把这些想法写入后续报考参考。"
            "如果你想正式采用，请直接说明要保留或避开的方向，"
            "我会先列清楚要采纳的内容，等你点“采纳”后再生效。"
        )
    normalized = re.sub(r"\*\*待确认内容\*\*", "**这轮先按咨询结论理解**", reply)
    normalized = re.sub(r"(?m)^我先把.*整理成待确认(?:偏好|要求|内容)[：:]?\s*$", "我先把这轮结论说明清楚：", normalized)
    replacements = (
        ("回复\"确认\"就按上面执行；", "如果你想正式采用，我会先把要采用的内容列出来；采纳前不会生效。"),
        ("回复“确认”就按上面执行；", "如果你想正式采用，我会先把要采用的内容列出来；采纳前不会生效。"),
        ("直接回复“确认”", "请点“采纳”"),
        ("直接回复\"确认\"", "请点“采纳”"),
        ("确认后，", "如果后续正式记成要求，"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    if "这轮没有生成可点击的确认卡片" not in normalized:
        normalized = (
            normalized.rstrip()
            + "\n\n补充说明：这轮还没有列出可采纳的内容，也不会写入后续参考或改动方案；"
            "如果要正式采用，我会先把要采用的内容列出来，点“采纳”后才会生效。"
        )
    return _normalize_user_facing_terms(normalized)


_DOWNGRADED_INTENT_PENDING_CLAIM_RE = re.compile(
    r"(?:我(?:先|会先|可以)?|这边)?(?:先)?(?:帮你)?把(?P<topic>[^。！？\n]{0,80}?)"
    r"(?:整理|记录)(?:成|为)?(?:一条|一个|一份)?待确认(?:偏好|要求|意向|内容)"
    r"(?:[，,]?(?:(?:你|等你|如果你)?确认后)[^。！？\n]*[。！？]?)?"
)
_DOWNGRADED_INTENT_DIRECT_CONFIRM_RE = re.compile(
    r"我可以把(?P<topic>[^。！？\n]{0,80}?)(?:整理|记)(?:成|为)(?P<target>排除条件|后续参考|偏好|要求)"
    r"[。！？]?(?:(?:你|等你|如果你)?确认后)[^。！？\n]*[。！？]?"
)


def _normalize_downgraded_intent_preview_reply(reply: str) -> str:
    """When intent arbitration downgrades to analysis-only, do not imply a card already exists."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    compact = _compact_plan_reply_text(reply)
    has_fake_pending_claim = "整理成待确认" in compact or any(
        marker in compact for marker in ("待确认偏好", "待确认要求", "待确认意向", "待确认内容")
    )
    has_no_card_effect_claim = any(
        marker in compact
        for marker in (
            "点击卡片采纳后",
            "点击采纳后",
            "确认后会",
            "确认后系统会",
            "候选池会变小",
            "不会再进入候选",
            "不再进入候选",
            "过滤掉",
            "自动过滤",
            "按这个口径来筛选",
        )
    )
    if not has_fake_pending_claim and not has_no_card_effect_claim:
        return reply

    def _replace_claim(match: re.Match[str]) -> str:
        topic = str(match.group("topic") or "这个想法").strip(" ：:，,。")
        if not topic:
            topic = "这个想法"
        return f"如果你想把{topic}作为后续参考，我可以先列出来让你采纳；采纳前不会生效。"

    normalized = _DOWNGRADED_INTENT_PENDING_CLAIM_RE.sub(_replace_claim, reply)

    def _replace_direct_confirm(match: re.Match[str]) -> str:
        topic = str(match.group("topic") or "这个想法").strip(" ：:，,。")
        target = str(match.group("target") or "后续参考").strip()
        if not topic:
            topic = "这个想法"
        return f"如果你想把{topic}作为{target}，我会先列出来让你采纳；采纳前不会生效。"

    normalized = _DOWNGRADED_INTENT_DIRECT_CONFIRM_RE.sub(_replace_direct_confirm, normalized)
    normalized = normalized.replace("点击卡片采纳后会一并过滤掉", "如果后续采纳，会把这些方向作为排除参考")
    normalized = normalized.replace("点击采纳后会一并过滤掉", "如果后续采纳，会把这些方向作为排除参考")
    normalized = normalized.replace("点击卡片采纳后会", "如果后续采纳，会")
    normalized = normalized.replace("点击采纳后会", "如果后续采纳，会")
    normalized = normalized.replace("后续生成方案时，系统会按这个口径来筛选。", "后续生成或调整方案时，会把这个口径作为推荐和检查参考；基础候选池不会因此变小。")
    normalized = normalized.replace("后续生成方案时，系统会按这个口径来筛选", "后续生成或调整方案时，会把这个口径作为推荐和检查参考；基础候选池不会因此变小")
    normalized = normalized.replace("这些方向都不会再进入候选", "后续推荐和方案检查会把这些方向作为排除参考，基础候选池不会因此变小")
    normalized = normalized.replace("会收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
    normalized = normalized.replace("收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
    normalized = normalized.replace("候选池会变小", "基础候选池不会因此变小")
    normalized = normalized.replace("不会再进入候选", "会作为排除参考")
    normalized = normalized.replace("不再进入候选", "会作为排除参考")
    normalized = normalized.replace("自动过滤后续推荐", "作为后续推荐和方案检查的排除参考")
    normalized = re.sub(
        r"自动过滤(?P<target>[^。！？\n]{1,50}?(?:相关选项|相关方向|相关志愿|选项|方向|志愿))",
        r"把\g<target>作为后续推荐、方案检查和方案调整的排除参考",
        normalized,
    )
    normalized = normalized.replace("自动过滤", "作为后续推荐、方案检查和方案调整的排除参考")
    normalized = normalized.replace("过滤掉", "作为排除参考")
    normalized = normalized.replace("你确认后我再作为后续参考去筛方案", "点击采纳后，我再作为后续参考去看候选和方案")
    normalized = normalized.replace("你确认后我再作为后续参考", "点击采纳后，我再作为后续参考")
    normalized = re.sub(
        r"你确认要把(?P<topic>[^。！？\n]{0,80}?)作为后续参考吗？采纳/确认前不会生效。",
        r"如果你想把\g<topic>作为后续参考，我会先列出来让你采纳；采纳前不会生效。",
        normalized,
    )
    normalized = re.sub(
        r"(?:要不要|需要不需要)(?:我)?先整理成[^。！？\n？?]{0,40}(?:要求|偏好|排除条件)[？?]\s*确认后[，,]",
        "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。如果后续采纳，",
        normalized,
    )
    normalized = normalized.replace("确认后，我会", "如果后续采纳，我会")
    normalized = normalized.replace("确认后会", "如果后续采纳，会")
    normalized = normalized.replace("点击采纳后，我再作为后续参考去看候选和方案", "如果后续采纳，我再作为后续参考去看候选和方案")
    normalized = normalized.replace("点击采纳后，我再作为后续参考", "如果后续采纳，我再作为后续参考")
    normalized = normalized.replace("告诉我，我帮你记成后续参考。", "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。")
    normalized = normalized.replace("直接告诉我，我帮你记成后续参考。", "如果要正式采用，我会先把要采用的内容列出来；采纳前不会生效。")
    normalized = normalized.replace("整理成待确认偏好", "列出来让你采纳")
    normalized = normalized.replace("整理成待确认要求", "列出来让你采纳")
    normalized = normalized.replace("整理成待确认意向", "列出来让你采纳")
    if "基础候选池" not in normalized and any(marker in normalized for marker in ("排除参考", "筛选", "过滤")):
        normalized = normalized.rstrip() + "\n\n补充说明：基础候选池不会因为偏好或要求采纳而永久变小；采纳后只是作为后续推荐、方案检查和方案调整的参考。"
    return _normalize_user_facing_terms(normalized)


def _intent_side_effect_decision_focus_summary(decision: dict[str, Any] | None) -> str:
    if not isinstance(decision, dict):
        return ""
    preference_strength = decision.get("preferenceStrength")
    if not isinstance(preference_strength, dict):
        preference_strength = {}
    spans = decision.get("entityPolaritySpans")
    if not isinstance(spans, list):
        spans = []

    positive_values: list[str] = []
    negative_values: list[str] = []

    def add(target: list[str], value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)

    for strength in ("primary", "preferred", "acceptable", "must_have", "only_keep"):
        for value in _as_text_list(preference_strength.get(strength)):
            add(positive_values, value)
    for strength in ("exclude_soft", "exclude_hard"):
        for value in _as_text_list(preference_strength.get(strength)):
            add(negative_values, value)

    for span in spans:
        if not isinstance(span, dict):
            continue
        entity = str(span.get("entity") or "").strip()
        if not entity:
            continue
        strength = str(span.get("strength") or "").strip()
        polarity = str(span.get("polarity") or "").strip()
        if polarity == "negative" or strength in {"exclude_soft", "exclude_hard"}:
            add(negative_values, entity)
        elif polarity == "positive" or strength in {"primary", "preferred", "acceptable", "must_have", "only_keep"}:
            add(positive_values, entity)

    parts: list[str] = []
    if positive_values:
        parts.append(f"偏好方向：{'、'.join(positive_values[:6])}")
    if negative_values:
        parts.append(f"不优先方向：{'、'.join(negative_values[:6])}")
    return "；".join(parts)


def _append_downgraded_intent_focus_summary(reply: str, decision: dict[str, Any] | None) -> str:
    summary = _intent_side_effect_decision_focus_summary(decision)
    if not summary or not isinstance(reply, str) or not reply.strip():
        return reply
    compact_reply = _compact_plan_reply_text(reply)
    summary_terms = [
        term
        for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", summary)
        if len(term) >= 2
    ]
    if summary_terms and all(term in compact_reply for term in summary_terms):
        return reply
    return _normalize_user_facing_terms(f"{reply.rstrip()}\n\n这次识别到的方向：{summary}。")


def _result_explicitly_has_no_executable_preview(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    combined = _compact_plan_reply_text(
        " ".join(
            str(data.get(key) or "")
            for key in ("summary", "reply", "message", "preview_summary", "previewSummary")
        )
    )
    if not combined:
        return False
    return any(
        marker in combined
        for marker in (
            "没有生成可执行调整内容",
            "没有生成可执行的调整内容",
            "没有形成可执行的调整预览",
            "还没有生成可执行的调整内容",
            "没有生成可点击的方案待采纳内容",
        )
    )


def _append_pending_intent_boundary(reply: str, *, has_pending_intent: bool) -> str:
    """Keep pending intent analysis visibly non-mutating across follow-up turns."""
    if not has_pending_intent or not isinstance(reply, str) or not reply.strip():
        return reply
    compact = _compact_plan_reply_text(reply)
    if any(marker in compact for marker in ("尚未确认", "待确认内容", "确认前不会写入后续参考")):
        return reply
    if any(marker in compact for marker in ("已正式生效", "已经生效")):
        return reply
    normalized = reply
    for source, target in (
        ("已经记录到后续参考", "仍在等待采纳"),
        ("已记录到后续参考", "仍在等待采纳"),
        ("已经写入后续报考参考", "仍在等待采纳"),
        ("已写入后续报考参考", "仍在等待采纳"),
        ("已经记下来", "仍在等待采纳"),
        ("已记下来", "仍在等待采纳"),
        ("已记录", "待采纳"),
        ("已经记录", "待采纳"),
        ("已加入", "待采纳"),
        ("已经加入", "待采纳"),
    ):
        normalized = normalized.replace(source, target)
    return (
        normalized.rstrip()
        + "\n\n补充说明：这次内容还没有采纳，点“采纳”前不会写入后续报考参考，采纳/确认前不会生效；"
        "如果要正式采用，请点击“采纳”。"
    )


_PENDING_INTENT_FOLLOWUP_USER_TOKENS = (
    "先不确认",
    "不确认",
    "暂不确认",
    "还没确认",
    "看看影响",
    "看影响",
    "有什么影响",
    "会不会影响",
    "影响方案",
    "这个偏好",
    "这个要求",
    "这个意向",
    "刚才的偏好",
    "刚才的要求",
    "上面的偏好",
    "上面的要求",
)

_PENDING_INTENT_FOLLOWUP_REPLY_TOKENS = (
    "这个偏好",
    "这个要求",
    "这个意向",
    "该偏好",
    "该要求",
    "待确认偏好",
    "待确认要求",
    "待确认意向",
    "偏好会影响",
    "要求会影响",
    "意向会影响",
)


def _is_pending_intent_followup_turn(content: str, reply: str) -> bool:
    """Whether an existing pending intent is relevant to this read-only turn.

    A session may contain an old backend pending-intent cache while the user asks
    an unrelated Explore question. In that case appending a confirmation
    boundary is confusing. Keep the boundary only when this turn explicitly
    references the pending preference/requirement or its impact.
    """
    compact_content = _compact_plan_reply_text(content)
    compact_reply = _compact_plan_reply_text(reply)
    return any(token in compact_content for token in _PENDING_INTENT_FOLLOWUP_USER_TOKENS) or any(
        token in compact_reply for token in _PENDING_INTENT_FOLLOWUP_REPLY_TOKENS
    )


def _pending_reference_values_from_state(pending_state: dict[str, Any] | None, entity_type: str) -> list[str]:
    if not isinstance(pending_state, dict):
        return []

    def add_values(target: list[str], values: Any) -> None:
        if isinstance(values, str):
            text = values.strip()
            if text:
                target.append(text)
            return
        if isinstance(values, dict):
            for item in values.values():
                add_values(target, item)
            return
        if isinstance(values, (list, tuple, set)):
            for item in values:
                add_values(target, item)

    execution_payload = pending_state.get("executionPayload") if isinstance(pending_state, dict) else None
    selected_data = execution_payload.get("selectedData") if isinstance(execution_payload, dict) else None
    entity_profile = selected_data.get("entityProfile") if isinstance(selected_data, dict) else None

    values: list[str] = []
    if isinstance(entity_profile, dict):
        if entity_type == "major":
            add_values(values, entity_profile.get("majorValues"))
        elif entity_type == "school":
            add_values(values, entity_profile.get("schools") or entity_profile.get("schoolValues"))
        for span in entity_profile.get("entityPolaritySpans") or []:
            if not isinstance(span, dict):
                continue
            if str(span.get("entityType") or "").strip() == entity_type:
                polarity = str(span.get("polarity") or "").strip()
                if polarity in {"", "positive"}:
                    add_values(values, span.get("entity"))
        strength = entity_profile.get("preferenceStrength")
        if isinstance(strength, dict):
            for key in ("primary", "preferred", "acceptable"):
                add_values(values, strength.get(key))

    merged = execution_payload.get("merged") if isinstance(execution_payload, dict) else None
    selected = selected_data.get("selected") if isinstance(selected_data, dict) else None
    selected = selected if isinstance(selected, list) else []
    if isinstance(merged, dict):
        selected.append(merged)
    for item in selected:
        if not isinstance(item, dict):
            continue
        if entity_type == "major":
            major_intents = item.get("major_intents") if isinstance(item.get("major_intents"), dict) else {}
            add_values(values, major_intents.get("level3") or major_intents.get("level2") or major_intents.get("level1"))
        elif entity_type == "school":
            school_intents = item.get("school_intents") if isinstance(item.get("school_intents"), dict) else {}
            add_values(values, school_intents.get("schoolNames") or school_intents.get("names") or school_intents.get("schools"))

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result[:3]


def _plan_query_profile_from_candidate_filters(
    extracted: dict[str, Any] | None,
    *,
    reason: str,
) -> PlanQueryProfileResult | None:
    if not bool((extracted or {}).get("should_query_candidate")):
        return None
    try:
        confidence = float((extracted or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.7:
        return None
    filters = (extracted or {}).get("filters") if isinstance(extracted, dict) else {}
    if not isinstance(filters, dict):
        return None
    structured_filters = {
        "tiers": [str(item or "").strip() for item in (filters.get("tiers") or []) if str(item or "").strip()],
        "provinceNames": [
            str(item or "").strip()
            for item in (filters.get("province_names") or [])
            if str(item or "").strip()
        ],
        "cityNames": [
            str(item or "").strip()
            for item in (filters.get("city_names") or [])
            if str(item or "").strip()
        ],
        "schoolKeywords": [
            str(item or "").strip()
            for item in (filters.get("school_keywords") or [])
            if str(item or "").strip()
        ],
        "majorKeywords": [
            str(item or "").strip()
            for item in (filters.get("major_keywords") or [])
            if str(item or "").strip()
        ],
        "schoolTags": [
            str(item or "").strip()
            for item in (filters.get("school_tags") or [])
            if str(item or "").strip()
        ],
        "majorTags": [
            str(item or "").strip()
            for item in (filters.get("major_tags") or [])
            if str(item or "").strip()
        ],
    }
    structured_filters = {key: value for key, value in structured_filters.items() if value}
    for target, source in (
        ("minTuitionPerYear", "min_tuition_per_year"),
        ("maxTuitionPerYear", "max_tuition_per_year"),
    ):
        if filters.get(source):
            structured_filters[target] = filters.get(source)
    if not structured_filters:
        return None

    runtime_filters: dict[str, Any] = {"limit": 5, "item_type": "school"}
    if structured_filters.get("tiers"):
        runtime_filters["tiers"] = structured_filters["tiers"]
        runtime_filters["tier"] = structured_filters["tiers"][0]
    if structured_filters.get("provinceNames"):
        runtime_filters["province_names"] = structured_filters["provinceNames"]
        runtime_filters["province_keyword"] = structured_filters["provinceNames"][0]
    if structured_filters.get("cityNames"):
        runtime_filters["city_names"] = structured_filters["cityNames"]
        runtime_filters["city_keyword"] = structured_filters["cityNames"][0]
    if structured_filters.get("schoolKeywords"):
        runtime_filters["school_keywords"] = structured_filters["schoolKeywords"]
        runtime_filters["school_keyword"] = structured_filters["schoolKeywords"][0]
    if structured_filters.get("majorKeywords"):
        runtime_filters["major_keywords"] = structured_filters["majorKeywords"]
        runtime_filters["major_keyword"] = structured_filters["majorKeywords"][0]
    if structured_filters.get("schoolTags"):
        runtime_filters["school_tags"] = structured_filters["schoolTags"]
    if structured_filters.get("majorTags"):
        runtime_filters["major_tags"] = structured_filters["majorTags"]
    if structured_filters.get("minTuitionPerYear"):
        runtime_filters["min_tuition_per_year"] = structured_filters["minTuitionPerYear"]
    if structured_filters.get("maxTuitionPerYear"):
        runtime_filters["max_tuition_per_year"] = structured_filters["maxTuitionPerYear"]

    return PlanQueryProfileResult(
        queryType="readonly_plan_query",
        scopeAnchor="candidate_pool",
        sideEffect="readonly",
        dimensions=["item_list"],
        condition={
            "target": "candidate_pool",
            "filters": structured_filters,
            "sort": {"field": "recommendation", "order": "desc"},
            "page": 1,
            "pageSize": 5,
        },
        filters=runtime_filters,
        projection={"mode": "school_list", "limit": 5},
        replyFocus=["candidate_snapshot", "local_candidate_query", "school_list_query"],
        pendingReferenceType="none",
        confidence=confidence,
        reason=reason,
    )


async def _candidate_filter_plan_query_profile_fallback(
    content: str,
    *,
    request_context: RequestContext,
) -> PlanQueryProfileResult | None:
    try:
        extracted = await extract_candidate_query_filters_async(
            content,
            batch=getattr(request_context, "batch", None),
        )
    except Exception:
        logger.warning(
            "Candidate filter PlanQuery fallback extraction failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return None
    return _plan_query_profile_from_candidate_filters(
        extracted if isinstance(extracted, dict) else None,
        reason="candidate_filter_extraction_fallback",
    )


async def _compile_runtime_plan_query_from_profile(
    *,
    content: str,
    request_context: RequestContext,
    planning_version: int = 0,
    pending_state: dict[str, Any] | None = None,
    pending_exists: bool = False,
) -> tuple[proposal_compiler.RuntimePlanQueryCompiledSource, Any | None]:
    try:
        query_profile = await classify_plan_query_profile(
            content,
            payload={
                "planningStateProfile": _planning_state_profile_for_turn_decision(
                    planning_summary=getattr(request_context, "planning_summary", None),
                    pending_state=pending_state if isinstance(pending_state, dict) else None,
                    score_detail=getattr(request_context, "score_detail", None),
                ),
                "pendingState": pending_state if isinstance(pending_state, dict) else {},
            },
        )
    except Exception:
        logger.warning(
            "Plan query profile classification failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return proposal_compiler.RuntimePlanQueryCompiledSource(
            blocking_reasons=["plan_query_profile_classification_failed"],
        ), None

    confidence = float(getattr(query_profile, "confidence", 0.0) or 0.0)
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        fallback_profile = await _candidate_filter_plan_query_profile_fallback(
            content,
            request_context=request_context,
        )
        if fallback_profile is not None:
            compiled_query = proposal_compiler.compile_runtime_plan_query_profile_source(
                content=content,
                query_profile=fallback_profile,
                planning_version=planning_version,
                pending_exists=pending_exists,
                pending_state=pending_state if isinstance(pending_state, dict) else None,
            )
            if compiled_query.matched:
                return compiled_query, fallback_profile
        return proposal_compiler.RuntimePlanQueryCompiledSource(
            blocking_reasons=["low_confidence_plan_query_profile"],
        ), query_profile
    compiled_query = proposal_compiler.compile_runtime_plan_query_profile_source(
        content=content,
        query_profile=query_profile,
        planning_version=planning_version,
        pending_exists=pending_exists,
        pending_state=pending_state if isinstance(pending_state, dict) else None,
    )
    if not compiled_query.matched:
        fallback_profile = await _candidate_filter_plan_query_profile_fallback(
            content,
            request_context=request_context,
        )
        if fallback_profile is not None:
            fallback_compiled = proposal_compiler.compile_runtime_plan_query_profile_source(
                content=content,
                query_profile=fallback_profile,
                planning_version=planning_version,
                pending_exists=pending_exists,
                pending_state=pending_state if isinstance(pending_state, dict) else None,
            )
            if fallback_compiled.matched:
                return fallback_compiled, fallback_profile
    return compiled_query, query_profile


def _turn_decision_allows_plan_query_profile(
    decision: Any,
    *,
    pending_exists: bool = False,
) -> bool:
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    task_layer = str(getattr(decision, "taskLayer", "") or "").strip()
    side_effect = str(getattr(decision, "sideEffect", "") or "").strip()
    scope_anchor = str(getattr(decision, "scopeAnchor", "") or "").strip()
    scenario = str(getattr(decision, "scenario", "") or "").strip()
    if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
        return False
    if task_layer != "plan" or scope_anchor not in {"current_plan", "candidate_pool"}:
        return False
    if scenario not in {"plan_query", "plan_query_while_pending"} and not (
        scenario == "" and scope_anchor == "candidate_pool" and side_effect in {"readonly", "readonly_while_pending"}
    ):
        return False
    if pending_exists:
        return side_effect in {"readonly", "readonly_while_pending"}
    return side_effect == "readonly"


def _turn_decision_is_candidate_pool_readonly_query(decision: Any | None) -> bool:
    if decision is None:
        return False
    getter = decision.get if isinstance(decision, dict) else lambda key, default=None: getattr(decision, key, default)
    confidence = float(getter("confidence", 0.0) or 0.0)
    task_layer = str(getter("taskLayer", "") or "").strip()
    side_effect = str(getter("sideEffect", "") or "").strip()
    scope_anchor = str(getter("scopeAnchor", "") or "").strip()
    scenario = str(getter("scenario", "") or "").strip()
    return (
        confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
        and task_layer == "plan"
        and side_effect == "readonly"
        and scope_anchor == "candidate_pool"
        and scenario in {"plan_query", "plan_query_while_pending"}
    )


def _prompt_looks_like_candidate_pool_query(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return (
        any(marker in compact for marker in ("候选", "候选列表", "候选里", "当前能选", "能选的结果"))
        and any(marker in compact for marker in ("看", "查", "刷新", "结果", "有没有", "多不多", "机会"))
    )


def _candidate_pool_missing_info_reply(
    content: str | None,
    missing_inputs: list[str] | None = None,
) -> str:
    focus_clause = "按你说的筛选方向"
    missing = {str(item or "").strip() for item in (missing_inputs or []) if str(item or "").strip()}
    need_score = bool({"score", "rank", "score_or_rank", "rank_or_score"} & missing) or not missing
    need_text = "高考分数和全省位次" if need_score else "省份、分数/位次、选科等基础信息"
    return (
        f"当前还不能{focus_clause}刷新候选列表或展示候选结果，因为候选池还没有生成，"
        f"并且缺少{need_text}。"
        f"你补充{need_text}后，我再{focus_clause}刷新候选结果。"
        "这轮不会加入方案，也不会改动当前方案。"
    )


def _conditional_candidate_readonly_boundary_reply(
    content: str | None,
    *,
    reason_code: str,
    missing_inputs: list[str] | None = None,
) -> str:
    focus_clause = "这类候选"
    missing = {str(item or "").strip() for item in (missing_inputs or []) if str(item or "").strip()}

    if reason_code == "selection_scope":
        return (
            "这轮先按候选可行性查看处理，暂时还没有定位到要加入方案的具体候选，"
            "所以不会加入方案，也不会改动当前方案。"
            "你可以补充学校、专业、地域等筛选范围，或先在候选列表里点选目标；"
            "我再按新的范围帮你确认是否值得加入。"
        )
    if reason_code == "missing_inputs":
        need_score = bool({"score", "rank", "score_or_rank", "rank_or_score"} & missing) or not missing
        need_text = "高考分数、全省位次和选科等基础信息" if need_score else "省份、分数/位次、选科等基础信息"
        return (
            f"这轮先按候选可行性查看处理，但当前还不能判断{focus_clause}是否适合加入方案，"
            f"因为还缺少{need_text}。"
            f"你补充{need_text}后，我再继续看这类候选值不值得加入。"
            "这轮不会加入方案，也不会改动当前方案。"
        )
    return (
        f"这轮先按候选可行性查看处理，当前候选里暂时没有稳定命中适合直接加入方案的{focus_clause}，"
        "所以不会加入方案，也不会改动当前方案。"
        "你可以继续补充筛选范围，或先看看当前候选结果后再决定要不要加入。"
    )


async def _classify_plan_query_turn_decision(
    *,
    content: str,
    request_context: RequestContext,
    pending_state: dict[str, Any] | None = None,
) -> Any | None:
    try:
        decision = await _classify_turn_decision_cached(
            content,
            request_context=request_context,
            payload={
                "planningStateProfile": _planning_state_profile_for_turn_decision(
                    planning_summary=getattr(request_context, "planning_summary", None),
                    pending_state=pending_state if isinstance(pending_state, dict) else None,
                    score_detail=getattr(request_context, "score_detail", None),
                ),
                "pendingState": pending_state if isinstance(pending_state, dict) else {},
            },
        )
        _store_current_turn_decision(request_context, decision)
        return decision
    except Exception:
        logger.warning(
            "Plan query TurnDecision failed: session_id=%s",
            getattr(request_context, "sessionid", ""),
            exc_info=True,
        )
        return None


def _build_pending_readonly_impact_reply(pending_state: dict[str, Any]) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    action_family = str((pending_state or {}).get("actionFamily") or "").strip()
    summary = str((pending_state or {}).get("summary") or "").strip()
    execution_payload = pending_state.get("executionPayload") if isinstance(pending_state, dict) else None
    intent_payload = execution_payload.get("intentPayload") if isinstance(execution_payload, dict) else None
    intent_summary = _summarize_selected_intent_payload(intent_payload) if isinstance(intent_payload, dict) else ""

    if kind == "plan_mutation":
        lines = [
            "当前有一项方案调整还没有执行。",
            "",
            "**对当前方案的影响**",
        ]
        lines.append(f"- {summary}" if summary else "- 完成确认前不会改动当前方案；确认后才会执行这次方案调整。")
        if intent_summary:
            lines.append(f"- 同时会更新后续报考参考：{intent_summary}。")
        lines.extend(
            [
                "",
                "**现在的状态**",
                "- 你还没有确认时，当前方案不会移出、加入、移动或重排任何志愿。",
                "- 可以继续只看影响或让我解释范围；这不会让待确认动作自动生效。",
            ]
        )
        return "\n".join(lines)

    if kind == "intent_change":
        lines = [
            "当前有一项待采纳的想法或报考条件，还没有采纳。",
            "",
            "**对当前方案的影响**",
            "- 点击采纳前不会写入后续报考参考，也不会改动当前方案。",
        ]
        if summary:
            lines.append(f"- 待采纳内容：{summary}。")
        lines.append("- 采纳后才会作为后续推荐、方案检查和方案调整的参考；基础候选池不会因此永久变小。")
        return "\n".join(lines)

    return "当前有一项待采纳内容还没有生效。完成确认前不会改动当前方案。"


def _post_apply_evidence_workspace_targets(
    evidence_plan: dict[str, Any] | None,
    fallback_targets: list[str] | None = None,
) -> list[str]:
    raw_targets = []
    if isinstance(evidence_plan, dict):
        raw_targets = evidence_plan.get("workspaceRefreshTargets") or evidence_plan.get("workspace_refresh_targets") or []
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets = _dedupe_workspace_targets([str(target) for target in raw_targets])
    if targets:
        return targets
    return _dedupe_workspace_targets([str(target) for target in (fallback_targets or [])])


def _planning_summary_has_formal_plan(planning_summary: PlanningSummary | None) -> bool:
    if planning_summary is None:
        return False
    return (
        _as_int(getattr(planning_summary, "ordered_total", 0)) > 0
        or _as_int(getattr(planning_summary, "working_total", 0)) > 0
    )


def _workspace_targets_from_followups(followups: list[WSResponse]) -> set[str]:
    targets: set[str] = set()
    for item in followups:
        content = getattr(item, "content", None)
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except Exception:
            continue
        if isinstance(payload, dict):
            target = str(payload.get("targetView") or "").strip()
            if target:
                targets.add(target)
    return targets


def _pending_apply_turn_event(
    *,
    session_id: str,
    user_id: str,
    scene: str,
    routing_path: str,
    pending_type: str,
    action_family: str | None,
    started_at: float,
    status: str,
    error_type: str | None = None,
    post_apply_evidence_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_decision = {
        "source": "proposal_compiler",
        "matched": True,
        "route": (
            "apply_pending_then_readonly"
            if post_apply_evidence_plan is not None
            else "apply_pending_then_new_request"
            if action_family == "apply_pending_then_new_request"
            else "apply_existing_pending"
        ),
    }
    if post_apply_evidence_plan is not None:
        route_decision["postApplyEvidencePlan"] = post_apply_evidence_plan
    return {
        "sessionId": session_id,
        "userId": user_id,
        "scene": scene,
        "routingPath": routing_path,
        "routeDecision": route_decision,
        "pendingType": pending_type,
        "actionFamily": action_family,
        "toolCallCount": 0,
        "totalDurationMs": int((time.monotonic() - started_at) * 1000),
        "postProcessingApplied": ["post_apply_evidence_plan"] if post_apply_evidence_plan is not None else [],
        "status": status,
        "errorType": error_type,
    }


def _post_apply_evidence_target_issues(evidence_plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(evidence_plan, dict):
        return []
    issues: list[str] = []
    for item in evidence_plan.get("targetIssues") or evidence_plan.get("target_issues") or []:
        value = str(item or "").strip()
        if value and value not in issues:
            issues.append(value)
    return issues


async def _load_post_apply_planning_summary(session_id: str) -> PlanningSummary | None:
    try:
        response = await get_planning_workspace_state(session_id)
    except Exception:
        logger.warning("Failed to fetch post-apply planning workspace: session_id=%s", session_id, exc_info=True)
        return None
    if not isinstance(response, dict) or response.get("code") != 0:
        return None
    try:
        return PlanningSummary.from_backend_state(response.get("data", {}))
    except Exception:
        logger.warning("Failed to parse post-apply planning workspace: session_id=%s", session_id, exc_info=True)
        return None


def _build_pending_apply_then_readonly_evidence_reply(
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None,
    planning: PlanningSummary | None,
) -> str | None:
    if planning is None:
        return None
    kind = str((pending_state or {}).get("kind") or "").strip()
    if kind != "plan_mutation":
        return None

    target_issues = _post_apply_evidence_target_issues(evidence_plan)
    if not target_issues:
        target_issues = ["current_plan_state"]

    total = planning.ordered_total or planning.working_total
    target = (
        planning.ordered_target_total
        or planning.working_target_total
        or max(planning.ordered_total, planning.working_total, total)
    )
    lines = ["已先执行这项待确认调整。基于执行后刷新到的当前方案："]
    missing: list[str] = []

    if any(issue in target_issues for issue in ("remaining_count", "current_plan_state", "post_apply_state")):
        if total > 0:
            if target > 0:
                lines.append(f"- 当前方案 {total} 个志愿（目标 {target} 个）。")
            else:
                lines.append(f"- 当前方案 {total} 个志愿。")
        else:
            missing.append("志愿数量")

    if "tier_distribution" in target_issues:
        tier = planning.tier_counts or {}
        chong = _as_int(tier.get("冲"))
        wen = _as_int(tier.get("稳"))
        bao = _as_int(tier.get("保"))
        if chong or wen or bao:
            lines.append(f"- 梯度分布：冲 {chong} 个、稳 {wen} 个、保 {bao} 个。")
        else:
            missing.append("梯度分布")

    if "risk_review" in target_issues:
        risk_count = _as_int(planning.review_risk_count)
        warn_count = _as_int(planning.review_warn_count)
        if risk_count or warn_count:
            lines.append(f"- 审查结果：风险 {risk_count} 项、提醒 {warn_count} 项。")
            if planning.risk_summaries:
                lines.append(f"- 需要留意：{'、'.join(planning.risk_summaries[:2])}。")
        elif total > 0:
            lines.append("- 审查结果：暂时没有明显风险。")
        else:
            missing.append("风险审查")

    if len(lines) == 1:
        return None
    if missing:
        lines.append(f"其中{'、'.join(missing)}暂时没有从刷新后的工作台读到，建议打开当前方案继续核对。")
    return "\n".join(lines)


def _append_pending_apply_then_readonly_result(
    reply: str,
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None = None,
    planning: PlanningSummary | None = None,
) -> str:
    evidence_reply = _build_pending_apply_then_readonly_evidence_reply(
        pending_state,
        evidence_plan,
        planning,
    )
    if evidence_reply:
        base = str(reply or "").strip()
        if not base:
            return evidence_reply
        if evidence_reply in base:
            return base
        return f"{base}\n\n{evidence_reply}"
    return _append_pending_apply_then_readonly_followup(reply, pending_state, evidence_plan)


def _append_pending_apply_then_readonly_followup(
    reply: str,
    pending_state: dict[str, Any],
    evidence_plan: dict[str, Any] | None = None,
) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    target_issues = []
    if isinstance(evidence_plan, dict):
        target_issues = [str(item).strip() for item in (evidence_plan.get("targetIssues") or []) if str(item).strip()]
    issue_names = {
        "remaining_count": "剩余数量",
        "tier_distribution": "梯度分布",
        "risk_review": "风险变化",
        "current_plan_state": "当前方案状态",
        "post_apply_state": "生效后的状态",
    }
    issue_text = "、".join(issue_names.get(issue, issue) for issue in target_issues if issue_names.get(issue, issue))
    if kind == "intent_change":
        followup = (
            "已先采纳这项报考参考。关于采纳后对当前方案的具体影响，"
            "需要基于新的报考参考重新检查当前方案；这轮不会直接给出未经检查的数量、梯度或风险结论。"
        )
    elif kind == "plan_mutation":
        followup = (
            "已先执行这项待确认调整。关于执行后还剩多少、梯度是否稳定或风险是否变化，"
            "需要基于刷新后的新方案继续检查；这轮不会直接给出未经检查的数量、梯度或风险结论。"
        )
    else:
        followup = (
            "已先采纳这项待确认内容。关于生效后的具体结果，需要基于最新状态继续检查；"
            "这轮不会直接给出未经检查的结论。"
        )
    if issue_text:
        followup = f"{followup}后续检查范围：{issue_text}。"
    base = str(reply or "").strip()
    if not base:
        return followup
    if followup in base:
        return base
    return f"{base}\n\n{followup}"


def _build_pending_conflict_new_request_reply(pending_state: dict[str, Any]) -> str:
    kind = str((pending_state or {}).get("kind") or "").strip()
    summary = str((pending_state or {}).get("summary") or "").strip()
    if kind == "plan_mutation":
        lines = [
            "当前已经有一项方案调整正在等待确认。",
        ]
        lines.append(f"待确认调整：{summary}。" if summary else "这项调整确认前不会改动当前方案。")
        lines.extend(
            [
                "这轮新诉求不会直接覆盖它，也不会再生成第二张待确认卡。",
                "你可以先确认执行、取消这项调整，或明确说要放弃当前待确认内容后重新提新的调整。",
            ]
        )
        return "\n".join(lines)
    if kind == "intent_change":
        lines = [
            "当前已经有一项想法或报考条件正在等待采纳。",
        ]
        lines.append(f"待采纳内容：{summary}。" if summary else "这项内容采纳前不会写入后续报考参考。")
        lines.extend(
            [
                "这轮新诉求不会直接覆盖它，也不会再生成第二张待采纳卡。",
                "你可以先点“采纳”、取消这项内容，或明确说要放弃当前待采纳内容后重新整理新的条件。",
            ]
        )
        return "\n".join(lines)
    return (
        "当前已经有一项内容正在等待确认。这轮新诉求不会直接覆盖它，也不会再生成第二张待确认卡。"
        "请先确认、取消，或明确说要放弃当前待确认内容后重新整理。"
    )


def _last_user_visible_text_response(messages: list[Any] | None) -> ModelResponse | None:
    for message in reversed(messages or []):
        if not isinstance(message, ModelResponse) or _is_route_observability_message(message):
            continue
        if any(isinstance(part, TextPart) and str(part.content or "").strip() for part in getattr(message, "parts", []) or []):
            return message
    return None


def _message_text_content(message: Any) -> str:
    parts: list[str] = []
    for part in getattr(message, "parts", []) or []:
        if isinstance(part, TextPart) and isinstance(part.content, str):
            text = part.content.strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _short_assistant_confirmation_summary(text: str, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _pending_confirmation_card_metadata_from_text(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get("type") != "pendingConfirmationCard":
        return {}
    return data


def _assistant_confirmation_kind_from_text(text: str) -> str | None:
    card = _pending_confirmation_card_metadata_from_text(text)
    if card:
        kind = str(card.get("kind") or "").strip()
        if kind in {"intent_change", "plan_mutation"}:
            return kind

    compact = _compact_plan_reply_text(text)
    if not compact:
        return None
    intent_title_markers = (
        "确认采纳这次偏好",
        "确认采纳这次要求",
        "确认采纳这次意向",
    )
    plan_title_markers = (
        "确认加入方案",
        "确认移出志愿",
        "确认移动志愿",
        "确认移动专业组",
        "确认移出专业组",
        "确认替换志愿",
        "确认方案排序",
        "确认重排方案",
        "确认补齐方案",
        "确认生成方案",
        "请确认本次方案调整",
    )
    has_intent_title = any(_compact_plan_reply_text(marker) in compact for marker in intent_title_markers)
    has_plan_title = any(_compact_plan_reply_text(marker) in compact for marker in plan_title_markers)
    if has_intent_title and not has_plan_title:
        return "intent_change"
    if has_plan_title and not has_intent_title:
        return "plan_mutation"
    return None


def _pending_summary_overlaps_assistant_text(pending_summary: str, assistant_text: str) -> bool:
    compact_text = _compact_plan_reply_text(assistant_text)
    if not compact_text:
        return False
    compact_summary = _compact_plan_reply_text(pending_summary)
    if compact_summary and compact_summary in compact_text:
        return True
    for part in re.split(r"[\n；;。.!！?？,，]+", str(pending_summary or "")):
        compact_part = _compact_plan_reply_text(part)
        if len(compact_part) >= 6 and compact_part in compact_text:
            return True
    return False


def _evaluate_short_text_pending_consistency(
    pending_state: dict[str, Any],
    history: list[Any] | None,
) -> tuple[str, str | None, str]:
    """Check only assistant-generated confirmation artifacts, not user intent."""
    pending_id = str(pending_state.get("pendingId") or "").strip()
    latest_response = _last_user_visible_text_response(history)
    latest_text = _message_text_content(latest_response) if latest_response is not None else ""
    assistant_summary = _short_assistant_confirmation_summary(latest_text)
    if not latest_text:
        return "unknown", None, ""
    latest_model_name = str(getattr(latest_response, "model_name", "") or "")
    blocked_prefix = "pending-confirmation-consistency-blocked"
    if latest_model_name == blocked_prefix or latest_model_name.startswith(f"{blocked_prefix}:"):
        blocked_pending_id = latest_model_name.split(":", 1)[1].strip() if ":" in latest_model_name else ""
        if not blocked_pending_id or blocked_pending_id == pending_id:
            return "conflict", "previous_consistency_blocked", assistant_summary

    pending_kind = str(pending_state.get("kind") or "").strip()
    card = _pending_confirmation_card_metadata_from_text(latest_text)
    if card:
        card_pending_id = str(card.get("pendingId") or "").strip()
        card_kind = str(card.get("kind") or "").strip()
        if card_pending_id and pending_id and card_pending_id != pending_id:
            return "conflict", "assistant_confirmation_pending_id_conflict", assistant_summary
        if card_kind in {"intent_change", "plan_mutation"}:
            if card_kind == pending_kind:
                return "matched", None, assistant_summary
            return "conflict", "assistant_confirmation_type_conflict", assistant_summary

    assistant_kind = _assistant_confirmation_kind_from_text(latest_text)
    if assistant_kind is None:
        return "unknown", None, assistant_summary
    if assistant_kind == pending_kind:
        return (
            "matched" if _pending_summary_overlaps_assistant_text(str(pending_state.get("summary") or ""), latest_text) else "unknown",
            None,
            assistant_summary,
        )
    return "conflict", "assistant_confirmation_type_conflict", assistant_summary


def _messages_after_index(messages: list[Any] | None, index: int | None) -> list[Any]:
    if not messages:
        return []
    if index is None:
        return list(messages)
    return list(messages[index + 1:])


def _latest_user_turn_boundary(messages: list[Any] | None) -> int | None:
    if not messages:
        return None
    return _latest_user_prompt_index(list(messages))


def _latest_turn_tool_names(messages: list[Any] | None) -> list[str]:
    boundary = _latest_user_turn_boundary(messages)
    return [part.tool_name for part in _iter_tool_call_parts(_messages_after_index(messages, boundary))]


def _latest_turn_has_intent_preview(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    return _tool_calls_include_intent_preview(_messages_after_index(messages, boundary))


def _latest_turn_has_plan_mutation_preview(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    turn_messages = _messages_after_index(messages, boundary)
    for part in _iter_tool_return_parts(turn_messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        effective_family = action_family
        result_kind = str(data.get("result_kind") or "").strip()
        result_stage = str(data.get("stage") or "").strip()
        if effective_family in _PENDING_PLAN_ACTION_FAMILIES and result_stage == "preview":
            return True
    return False


def _latest_turn_looks_readonly(messages: list[Any] | None) -> bool:
    if _latest_turn_is_readonly_interruption_fallback(messages):
        return True
    tool_names = _latest_turn_tool_names(messages)
    if not tool_names:
        return False
    readonly_tool_names = {
        "query_volunteer_plan",
        "collect_plan_context_inputs",
        "analyze_current_interest",
        "analyze_current_interest_profile",
        "analyze_current_school_interest",
        "analyze_current_major_interest",
        "analyze_current_region_interest",
        "analyze_current_career_direction",
        "compare_majors",
        "compare_majors_adhoc",
        "compare_major_options",
        "compare_schools",
        "compare_schools_adhoc",
        "get_major_introduction",
        "get_major_introductions",
        "get_school_introduction",
        "query_admission_score",
        "query_score_line",
        "validate_major_subjects",
        "validate_plan_params",
    }
    if any(name in _INTENT_PREVIEW_TOOL_NAMES for name in tool_names):
        return False
    if _latest_turn_has_plan_mutation_preview(messages):
        return False
    for name in tool_names:
        if name == "plan_next_action":
            continue
        if name == "execute_plan_action":
            continue
        if name not in readonly_tool_names:
            return False
    for part in _iter_tool_return_parts(_messages_after_index(messages, _latest_user_turn_boundary(messages))):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        action_family = str((data or {}).get("action_family") or "").strip()
        if action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES and action_family not in {"analyze_adjustment", "preview_fix_proposal"}:
            return False
        if bool((data or {}).get("applied")) and action_family not in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES:
            return False
    return True


def _latest_turn_is_readonly_interruption_fallback(messages: list[Any] | None) -> bool:
    boundary = _latest_user_turn_boundary(messages)
    for message in _messages_after_index(messages, boundary):
        if not isinstance(message, ModelResponse):
            continue
        if str(getattr(message, "model_name", "") or "") == "agent-interruption-readonly-fallback":
            return True
    return False


def _no_pending_intent_confirmation_guard_reply() -> str:
    return "我这边没有找到上一轮仍在等待采纳的内容。你可以直接说想保留、排除或重点关注的方向，我会先列出来让你采纳。"


def _pending_requires_card_click_reply(kind: str | None = None) -> str:
    if kind == "plan_mutation":
        return "这次方案调整还没有执行。请以最新内容为准；确认前不会改动方案。如果内容已失效，可以重新说明要调整的内容，我会重新给出预览。"
    if kind == "intent_change":
        return "这次想法或报考条件已经列出来，正在等待采纳。请以最新内容为准；采纳前不会写入后续报考参考。如果内容已失效，可以重新说明你的想法。"
    return "这次更新还没有生效。请以最新内容为准；确认前不会生效。如果内容已失效，可以重新说明要更新的内容。"


def _pending_confirmation_type_mismatch_reply(active_kind: str, requested_kind: str) -> str:
    if active_kind == "plan_mutation" and requested_kind == "intent_change":
        return "当前等待确认的是方案调整，不是想法或报考条件更新。如果要确认方案调整，可以点“确认执行”或只回复“确认”；如果要更新想法，请重新说明具体内容。"
    if active_kind == "intent_change" and requested_kind == "plan_mutation":
        return "当前等待确认的是想法或报考条件更新，不是方案调整。如果要采纳这次内容，可以点“采纳”或只回复“确认”；如果要调整方案，请重新说明具体动作。"
    return "当前等待确认的内容和这次确认的对象不一致，请点最新内容里的按钮，或重新说明要确认的内容。"


def _readonly_closure_ack_reply() -> str:
    return "先按刚才的分析结论理解。这轮没有待确认的偏好或方案动作，也不会改动方案；后面想继续看具体学校、专业或方案调整，随时告诉我。"


_PENDING_PLAN_ACTION_FAMILIES = proposal_compiler.PENDING_PLAN_ACTION_FAMILIES

_NO_EXECUTABLE_PLAN_PREVIEW_REPLY = (
    "这次没有形成可执行的调整预览，方案不会因为这轮回复而改变。"
    "如果还需要处理这类问题，可以重新说明要调整的目标，我会按最新方案重新给出预览。"
)


def _latest_execute_plan_action_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if isinstance(data, dict) and data:
            return data
    return None


def _latest_non_actionable_plan_mutation_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
            continue
        if _build_plan_confirmation_candidate_from_payload(data) is not None:
            continue
        result_kind = str(data.get("result_kind") or "").strip()
        if result_kind in {"preview_only", "error"}:
            return data
    return None


_PLAN_EXECUTION_RESULT_KINDS = {
    "status_overview",
    "ordered_snapshot",
    "candidate_snapshot",
    "generation_result",
    "adjustment_analysis",
    "fix_proposal_preview",
    "mutation_result",
    "review_result",
    "preview_only",
    "no_change",
    "error",
}


def _plan_execution_result_is_non_actionable(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    action_family = str(data.get("action_family") or "").strip()
    result_kind = str(data.get("result_kind") or "").strip()
    if result_kind == "adjustment_analysis":
        return not _adjustment_analysis_has_actionable_suggestions(data)
    if data.get("applied") is True:
        return False
    if _result_explicitly_has_no_executable_preview(data):
        return True
    if result_kind in {"error", "no_change"}:
        return True
    if result_kind == "preview_only":
        return action_family not in _PENDING_PLAN_ACTION_FAMILIES
    if result_kind and result_kind not in _PLAN_EXECUTION_RESULT_KINDS:
        return True
    return False


def _latest_non_actionable_plan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in {"execute_plan_action", "plan_next_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if part.tool_name == "plan_next_action" and isinstance(data, dict):
            action_family = str(data.get("action_family") or "").strip()
            missing_inputs = [
                str(item or "").strip()
                for item in (data.get("missing_inputs") or data.get("missingInputs") or [])
                if str(item or "").strip()
            ]
            if action_family in _PENDING_PLAN_ACTION_FAMILIES and missing_inputs:
                normalized = normalize_plan_action_payload(dict(data))
                normalized["result_kind"] = "error"
                normalized["missing_inputs"] = missing_inputs
                normalized.setdefault("reply_focus", ["missing_inputs"])
                return normalized
            continue
        if _plan_execution_result_is_non_actionable(data):
            return data
    return None


def _latest_readonly_plan_query_misroute_candidate(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        result_kind = str(data.get("result_kind") or "").strip()
        if action_family == "query_state" and result_kind == "status_overview":
            return data
    return None


def _latest_profile_change_replan_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if isinstance(data, dict) and _requests_profile_change_replan(data):
            return data
    return None


def _latest_empty_status_overview_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name != "execute_plan_action":
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        if str(data.get("action_family") or "").strip() != "query_state":
            continue
        if str(data.get("result_kind") or "").strip() != "status_overview":
            continue
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        if _as_int(facts.get("current_total")) <= 0:
            return data
    return None


def _non_actionable_plan_preview_boundary(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict) or not result:
        return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY
    if _requests_profile_change_replan(result):
        return _build_profile_change_replan_reply(None)
    action_family = str(result.get("action_family") or "").strip()
    result_kind = str(result.get("result_kind") or "").strip()
    reply_focus = {str(item or "").strip() for item in (result.get("reply_focus") or []) if str(item or "").strip()}
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    if action_family == "preview_fix_proposal" and result_kind == "fix_proposal_preview" and facts:
        return _sanitize_reply_for_user(
            _normalize_user_facing_terms(
                "\n".join(
                    _build_fix_proposal_preview_fallback_lines(
                        facts,
                        summary=str(result.get("summary") or "").strip(),
                    )
                )
            )
        )
    if action_family == "review_plan" and result_kind == "error":
        summary = _clean_review_fallback_text(result.get("summary"))
        lines = [
            "这轮没有拿到完整的方案审查结果，当前方案不会因为这次回复发生变化。",
        ]
        if summary and "调整预览" not in summary:
            lines.append(summary)
        lines.append("你可以稍后重新审查，或直接说想重点看哪类风险，我再按当前方案重新检查。")
        return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))
    position_resolution = str(facts.get("position_resolution") or "").strip()
    if action_family in {"move_ordered_unit", "move_unit"} and position_resolution in {"empty_plan", "source_position_out_of_range"}:
        return (
            "这轮只是说明当前不能按这个位置移动，不会改动方案。"
            "需要先生成或补齐方案后，再按位置生成移动预览。"
        )
    if action_family in {"remove_ordered_unit", "remove_units"} and position_resolution in {"empty_plan", "source_position_out_of_range"}:
        return (
            "这轮只是说明当前不能按这个位置删除，不会改动方案。"
            "需要先生成或补齐方案后，再按位置生成删除预览。"
        )
    if action_family in {"remove_ordered_unit", "remove_units"} and position_resolution == "range_empty":
        return (
            "这轮已经检查过这个位置范围，当前没有命中需要删除的内容，所以不会改动方案。"
            "如果你想删除别的范围，可以再说明位置、冲稳保区间或具体学校专业。"
        )
    if "needs_candidate_selection" in reply_focus:
        return (
            "这轮还没有定位到要加入方案的具体候选志愿，不会改动当前方案。"
            "可以补充学校、专业、地域等范围，我再给你确认预览；或先在候选里选中目标。"
        )
    if "needs_volunteer_selection" in reply_focus:
        return (
            "这轮还没有生成可执行的调整内容，也没有定位到当前方案里要处理的具体志愿，不会改动当前方案。"
            "可以补充学校、专业组或专业名称后，我会重新定位影响范围并列出调整预览。"
        )
    if "replacement_scope_required" in reply_focus or "replacement_scope_unresolved" in reply_focus:
        return (
            "这轮还缺少替换方向，不会改动方案。"
            "你可以补充想换成的专业、院校、地域或风险层次，我再给你预览。"
        )
    if "replacement_scope_insufficient" in reply_focus:
        return (
            "当前可选范围里没有足够合适的替换项，不会改动方案。"
            "可以放宽地域、专业、院校层次或风险要求后再试。"
        )
    if "missing_inputs" in reply_focus:
        missing_inputs = {
            str(item or "").strip()
            for item in (result.get("missing_inputs") or result.get("missingInputs") or [])
            if str(item or "").strip()
        }
        if action_family in {"move_unit", "move_ordered_unit"} and "target_position" in missing_inputs:
            scope_label = _plan_action_scope_label_from_payload(result)
            target_text = f"“{scope_label}”" if scope_label else "这批志愿"
            return (
                f"我理解你想调整{target_text}的位置，但还需要明确移动到哪里，"
                "比如放到第几位、某个志愿前后，或按录取率/推荐系数整体重排。"
                "这轮不会改动方案；你补充规则后，我再列出调整预览。"
            )
        if action_family in {"move_unit", "move_ordered_unit"} and missing_inputs:
            return (
                "这轮还没有唯一定位到要移动的志愿，或者还缺少目标位置，不会改动方案。"
                "可以补充学校专业、专业组位置，以及要移动到哪里，我再给你预览。"
            )
        summary = str(result.get("summary") or "").strip()
        if summary:
            return (
                "这轮还没有生成可执行的调整内容，缺少生成或加入方案所需的基础信息，"
                "比如省份、分数/位次、选科等，所以不会改动当前方案。"
                "你可以补充缺少的信息后，我会重新定位影响范围并列出调整预览。"
            )
    return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY


def _adjustment_analysis_has_actionable_suggestions(result: dict[str, Any]) -> bool:
    facts = result.get("facts")
    if not isinstance(facts, dict):
        return False
    actionable_counts = facts.get("actionable_suggestion_counts")
    if isinstance(actionable_counts, dict):
        return any(int(actionable_counts.get(key) or 0) > 0 for key in ("add", "reorder", "replace", "remove"))
    return bool(facts.get("has_actionable_suggestions"))


def _plan_action_has_filter_selection_scope(filters: Any) -> bool:
    if not isinstance(filters, dict):
        return False
    for key, value in filters.items():
        if key in {"limit", "preserve_count", "preserveCount", "require_capacity_check", "requireCapacityCheck"}:
            continue
        if key in {"school_tags", "major_tags"} and str(value or "").strip() == "[]":
            continue
        if str(value or "").strip():
            return True
    return False


def _plan_action_scope_label_from_payload(payload: dict[str, Any]) -> str:
    """Build a short user-visible label from structured action scope only."""
    if not isinstance(payload, dict):
        return ""
    atomic_actions = payload.get("atomic_actions") or payload.get("atomicActions") or []
    if not isinstance(atomic_actions, list):
        atomic_actions = []

    labels: list[str] = []

    def add(value: Any, suffix: str = "") -> None:
        text = str(value or "").strip()
        if not text:
            return
        label = f"{text}{suffix}"
        if label not in labels:
            labels.append(label)

    def add_list(value: Any, suffix: str = "") -> None:
        if isinstance(value, list):
            values: list[Any] = value
        else:
            text = str(value or "").strip()
            if not text:
                return
            values = [text]
            if text.startswith("["):
                with contextlib.suppress(Exception):
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        values = parsed
        for item in values:
            add(item, suffix)

    for atomic in atomic_actions:
        if not isinstance(atomic, dict):
            continue
        filters = atomic.get("filters")
        if isinstance(filters, dict):
            add(filters.get("province_keyword") or filters.get("province"), "志愿")
            add(filters.get("city_keyword") or filters.get("city"), "志愿")
            add(filters.get("school_keyword") or filters.get("school"), "相关志愿")
            add(filters.get("major_keyword") or filters.get("major"), "相关志愿")
            add(filters.get("tier"), "区志愿")
            add_list(filters.get("school_tags"), "相关志愿")
            add_list(filters.get("major_tags"), "相关志愿")
            add_list(filters.get("program_types") or filters.get("program_type"), "相关志愿")
        add_list(atomic.get("source_major_names") or atomic.get("sourceMajorNames"), "相关志愿")
        add_list(atomic.get("volunteer_ids") or atomic.get("volunteerIds"))
        add_list(atomic.get("unit_ids") or atomic.get("unitIds"))
    return "、".join(labels[:3])


def _replace_plan_payload_lacks_replacement_scope(payload: dict[str, Any]) -> bool:
    if str(payload.get("action_family") or "").strip() != "replace_units":
        return False
    atomic_actions = payload.get("atomic_actions")
    if not isinstance(atomic_actions, list) or not atomic_actions:
        return True
    for atomic in atomic_actions:
        if not isinstance(atomic, dict):
            continue
        if _atomic_has_review_issue_target(atomic):
            return False
        if _plan_action_has_filter_selection_scope(atomic.get("filters")):
            return False
    return True


def _atomic_volunteer_ids(atomic: dict[str, Any]) -> list[str]:
    volunteer_ids = atomic.get("volunteer_ids") or atomic.get("volunteerIds")
    if isinstance(volunteer_ids, list):
        return [str(item or "").strip() for item in volunteer_ids if str(item or "").strip()]
    text = str(volunteer_ids or "").strip()
    return [text] if text else []


def _atomic_unit_ids(atomic: dict[str, Any]) -> list[str]:
    unit_ids = atomic.get("unit_ids") or atomic.get("unitIds")
    if isinstance(unit_ids, list):
        return [str(item or "").strip() for item in unit_ids if str(item or "").strip()]
    text = str(unit_ids or "").strip()
    return [text] if text else []


def _atomic_source_major_names(atomic: dict[str, Any]) -> list[str]:
    source_major_names = atomic.get("source_major_names") or atomic.get("sourceMajorNames")
    if isinstance(source_major_names, list):
        return [str(item or "").strip() for item in source_major_names if str(item or "").strip()]
    text = str(source_major_names or "").strip()
    return [text] if text else []


def _atomic_has_review_issue_target(atomic: dict[str, Any]) -> bool:
    review_issue_target = atomic.get("review_issue_target") or atomic.get("reviewIssueTarget")
    return isinstance(review_issue_target, dict) and bool(str(review_issue_target.get("code") or "").strip())


def _atomic_has_filter_scope(atomic: dict[str, Any]) -> bool:
    filters = atomic.get("filters")
    return _plan_action_has_filter_selection_scope(filters if isinstance(filters, dict) else None)


_COMPOSITE_CLARIFICATION_MIN_TUITION_FILTER_KEYS = frozenset(
    {
        "min_tuition_per_year",
        "minTuitionPerYear",
        "tuition_min_per_year",
        "tuitionMinPerYear",
    }
)

_COMPOSITE_CLARIFICATION_MAX_TUITION_FILTER_KEYS = frozenset(
    {
        "max_tuition_per_year",
        "maxTuitionPerYear",
        "tuition_cap",
        "tuitionCap",
        "max_tuition",
        "maxTuition",
    }
)

_COMPOSITE_CLARIFICATION_PREFERENCE_FIT_FILTER_KEYS = frozenset(
    {
        "preference_fit",
        "preferenceFit",
        "intent_relation",
        "intentRelation",
    }
)

_COMPOSITE_CLARIFICATION_PREFERENCE_FIT_VALUES = frozenset(
    {
        "aligned",
        "preferred",
        "positive",
        "意向",
        "匹配",
        "unrelated",
        "irrelevant",
        "non_intent",
        "not_intent",
        "not_aligned",
        "not_preferred",
        "不沾边",
        "非意向",
        "不相关",
        "不匹配",
        "conflict",
        "negative",
        "excluded",
        "排除",
        "冲突",
    }
)


def _filter_has_positive_numeric_value(filters: dict[str, Any], keys: frozenset[str]) -> bool:
    for key in keys:
        value = filters.get(key)
        try:
            if int(float(str(value or "").strip())) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _filter_has_preference_fit_value(filters: dict[str, Any]) -> bool:
    for key in _COMPOSITE_CLARIFICATION_PREFERENCE_FIT_FILTER_KEYS:
        value = filters.get(key)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and (
                text in _COMPOSITE_CLARIFICATION_PREFERENCE_FIT_VALUES
                or text.lower() in _COMPOSITE_CLARIFICATION_PREFERENCE_FIT_VALUES
            ):
                return True
    return False


def _atomic_has_current_plan_selector(atomic: dict[str, Any]) -> bool:
    return bool(
        _atomic_volunteer_ids(atomic)
        or _atomic_unit_ids(atomic)
        or _atomic_source_major_names(atomic)
        or _atomic_has_review_issue_target(atomic)
    )


def _atomic_has_relation_and_tuition_filter_scope(atomic: dict[str, Any]) -> bool:
    filters = atomic.get("filters")
    if not isinstance(filters, dict):
        return False
    has_tuition_bound = (
        _filter_has_positive_numeric_value(filters, _COMPOSITE_CLARIFICATION_MIN_TUITION_FILTER_KEYS)
        or _filter_has_positive_numeric_value(filters, _COMPOSITE_CLARIFICATION_MAX_TUITION_FILTER_KEYS)
    )
    return _filter_has_preference_fit_value(filters) and has_tuition_bound


def _atomic_action_can_override_structured_clarification(action_family: str, atomic: Any) -> bool:
    if not isinstance(atomic, dict):
        return False
    if action_family == "add_units":
        return bool(_atomic_volunteer_ids(atomic))
    if action_family == "remove_units":
        return _atomic_has_current_plan_selector(atomic) or _atomic_has_relation_and_tuition_filter_scope(atomic)
    if action_family == "replace_units":
        if _atomic_has_review_issue_target(atomic):
            return True
        return _atomic_has_current_plan_selector(atomic) and _atomic_has_filter_scope(atomic)
    if action_family in {"move_unit", "move_ordered_unit", "remove_ordered_unit"}:
        return _atomic_action_has_execution_scope(action_family, atomic)
    return False


def _atomic_has_position(atomic: dict[str, Any], *keys: str) -> bool:
    return any(atomic.get(key) is not None for key in keys)


def _atomic_action_has_execution_scope(action_family: str, atomic: Any) -> bool:
    if not isinstance(atomic, dict):
        return False
    if action_family == "add_units":
        return bool(_atomic_volunteer_ids(atomic)) or _atomic_has_filter_scope(atomic)
    if action_family == "remove_units":
        return (
            bool(_atomic_volunteer_ids(atomic))
            or bool(_atomic_source_major_names(atomic))
            or _atomic_has_review_issue_target(atomic)
            or _atomic_has_filter_scope(atomic)
        )
    if action_family == "move_unit":
        return bool(_atomic_volunteer_ids(atomic)) and _atomic_has_position(atomic, "target_position", "targetPosition")
    if action_family == "move_ordered_unit":
        has_source = (
            bool(_atomic_unit_ids(atomic))
            or _atomic_has_position(atomic, "source_position", "sourcePosition")
        )
        return has_source and _atomic_has_position(atomic, "target_position", "targetPosition")
    if action_family == "remove_ordered_unit":
        return bool(_atomic_unit_ids(atomic)) or _atomic_has_position(atomic, "source_position", "sourcePosition")
    if action_family == "replace_units":
        has_source = (
            bool(_atomic_volunteer_ids(atomic))
            or bool(_atomic_source_major_names(atomic))
            or _atomic_has_review_issue_target(atomic)
        )
        if _atomic_has_review_issue_target(atomic):
            return True
        return has_source and _atomic_has_filter_scope(atomic)
    return False


def _plan_payload_has_executable_mutation_scope(payload: dict[str, Any]) -> bool:
    action_family = str(payload.get("action_family") or "").strip()
    if action_family in {"generate_plan", "regenerate_order", "sort_ordered_plan"}:
        return True
    atomic_actions = payload.get("atomic_actions")
    if isinstance(atomic_actions, list) and any(
        _atomic_action_has_execution_scope(action_family, item)
        for item in atomic_actions
    ):
        return True
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    resolved_payload = facts.get("resolved_apply_payload") if isinstance(facts, dict) else None
    if isinstance(resolved_payload, dict) and resolved_payload is not payload:
        resolved_with_context = dict(payload)
        resolved_with_context.update(resolved_payload)
        resolved_facts = dict(facts)
        resolved_facts.pop("resolved_apply_payload", None)
        if resolved_facts:
            resolved_with_context["facts"] = resolved_facts
        else:
            resolved_with_context.pop("facts", None)
        return _plan_payload_has_executable_mutation_scope(resolved_with_context)
    return False


def _plan_payload_can_override_structured_clarification(payload: dict[str, Any]) -> bool:
    action_family = str(payload.get("action_family") or "").strip()
    atomic_actions = payload.get("atomic_actions")
    if isinstance(atomic_actions, list) and any(
        _atomic_action_can_override_structured_clarification(action_family, item)
        for item in atomic_actions
    ):
        return True
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    resolved_payload = facts.get("resolved_apply_payload") if isinstance(facts, dict) else None
    if isinstance(resolved_payload, dict) and resolved_payload is not payload:
        resolved_with_context = dict(payload)
        resolved_with_context.update(resolved_payload)
        resolved_facts = dict(facts)
        resolved_facts.pop("resolved_apply_payload", None)
        if resolved_facts:
            resolved_with_context["facts"] = resolved_facts
        else:
            resolved_with_context.pop("facts", None)
        return _plan_payload_can_override_structured_clarification(resolved_with_context)
    return False


def _plan_payload_lacks_position_target(payload: dict[str, Any]) -> bool:
    if str(payload.get("action_family") or "").strip() not in {"move_ordered_unit", "remove_ordered_unit"}:
        return False
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    if str(facts.get("position_resolution") or "").strip() in {"empty_plan", "source_position_out_of_range", "range_empty", "missing_source_position"}:
        return True
    return False


def _build_plan_confirmation_candidate_from_payload(payload: dict[str, Any], summary: str | None = None) -> dict[str, Any] | None:
    payload = normalize_plan_action_payload(payload)
    if (
        proposal_compiler.structured_proposal_needs_clarification(payload)
        and not _plan_payload_can_override_structured_clarification(payload)
    ):
        return None
    preview_action_family = str(payload.get("action_family") or "").strip()
    action_family = preview_action_family
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return None
    if str(payload.get("result_kind") or "").strip() == "no_change":
        return None
    if payload.get("missing_inputs"):
        return None
    if action_family == "replace_units" and not payload.get("atomic_actions"):
        return None
    if not _plan_payload_has_executable_mutation_scope(payload):
        return None
    if _replace_plan_payload_lacks_replacement_scope(payload):
        return None
    if _plan_payload_lacks_position_target(payload):
        return None
    apply_payload = dict(payload)
    facts = apply_payload.get("facts") if isinstance(apply_payload.get("facts"), dict) else {}
    source_backend_version = _as_int(
        payload.get("source_backend_version")
        or payload.get("planning_version")
        or facts.get("source_backend_version")
        or facts.get("planning_version")
    )
    resolved_payload = facts.get("resolved_apply_payload") if isinstance(facts, dict) else None
    if isinstance(resolved_payload, dict):
        apply_payload.update(resolved_payload)
    resolved_action_family = str(apply_payload.get("action_family") or "").strip()
    if resolved_action_family in _PENDING_PLAN_ACTION_FAMILIES:
        action_family = resolved_action_family
    apply_payload["action_family"] = action_family
    if not _plan_payload_has_executable_mutation_scope(apply_payload):
        return None
    apply_payload.pop("current_stage", None)
    apply_payload.pop("user_confirmed", None)
    apply_payload["stage"] = "apply"
    apply_payload["requires_confirmation"] = False
    apply_payload["should_refresh_workspace"] = True
    apply_payload["should_rerun_review"] = True
    if source_backend_version > 0:
        apply_payload["planning_version"] = source_backend_version
    pending = {
        "action_family": action_family,
        "user_goal": payload.get("user_goal") or "",
        "summary": summary or payload.get("preview_summary") or "",
        "plan_payload": json.dumps(apply_payload, ensure_ascii=False),
    }
    intent_update = facts.get("intent_update") if isinstance(facts, dict) else None
    if isinstance(intent_update, dict) and intent_update.get("selected"):
        pending["intent_update"] = intent_update
    if source_backend_version > 0:
        pending["source_backend_version"] = source_backend_version
        pending["planning_version"] = source_backend_version
    created_turn = _as_int(payload.get("created_turn"))
    if created_turn > 0:
        pending["created_turn"] = created_turn
    return pending


def _parse_tool_call_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _merge_plan_next_payload_for_pending_candidate(
    call_payload: dict[str, Any],
    latest_plan_next_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep pending execution payload as complete as the structured plan.

    The model can call ``plan_next_action`` with the full structured plan and
    then pass a thinner payload to ``execute_plan_action`` for preview. Pending
    confirmation must persist the executable structure, not the thinner copy.
    """
    if not isinstance(call_payload, dict):
        return {}
    action_family = str(call_payload.get("action_family") or "").strip()
    if not action_family:
        return dict(call_payload)
    if (
        not isinstance(latest_plan_next_payload, dict)
        or str(latest_plan_next_payload.get("action_family") or "").strip() != action_family
    ):
        return dict(call_payload)

    merged = dict(latest_plan_next_payload)
    merged.update(call_payload)
    if (
        not call_payload.get("atomic_actions")
        and latest_plan_next_payload.get("atomic_actions")
    ):
        merged["atomic_actions"] = latest_plan_next_payload.get("atomic_actions")
    return merged


def _extract_plan_confirmation_candidate(messages: list[Any] | None) -> dict[str, Any] | None:
    """Find a current-turn plan preview that can be persisted as a confirmation card."""
    pending_calls: dict[str, dict[str, Any]] = {}
    latest_plan_next_payload: dict[str, Any] | None = None
    latest_candidate: dict[str, Any] | None = None
    has_non_actionable_adjustment_analysis = False
    user_turns_since_candidate = 0
    current_user_turn = 0

    for message in messages or []:
        if isinstance(message, ModelResponse):
            for part in getattr(message, "parts", []) or []:
                if not isinstance(part, ToolCallPart) or part.tool_name != "execute_plan_action":
                    continue
                payload = _extract_execute_plan_payload(part)
                if not isinstance(payload, dict):
                    continue
                call_id = str(part.tool_call_id or "")
                if call_id:
                    pending_calls[call_id] = payload

        if not isinstance(message, ModelRequest):
            continue
        user_prompt_parts = [
            part for part in getattr(message, "parts", []) or []
            if isinstance(part, UserPromptPart)
        ]
        if user_prompt_parts:
            current_user_turn += 1
            pending_calls.clear()
            latest_plan_next_payload = None
            has_non_actionable_adjustment_analysis = False
            if latest_candidate is not None:
                user_turns_since_candidate += 1
                if user_turns_since_candidate > 3:
                    latest_candidate = None
                    user_turns_since_candidate = 0
            continue
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, ToolReturnPart):
                continue
            result = _parse_tool_return_json(part.content)
            if not result:
                continue
            if part.tool_name == "plan_next_action":
                if result.get("stage") == "preview":
                    latest_plan_next_payload = normalize_plan_action_payload(dict(result))
                continue
            if part.tool_name != "execute_plan_action":
                continue
            action_family = str(result.get("action_family") or "").strip()
            result_kind = str(result.get("result_kind") or "").strip()
            if _plan_execution_result_is_non_actionable(result):
                call_payload = pending_calls.get(str(part.tool_call_id or "")) or {}
                if action_family in {"query_state", "query_ordered", "query_candidates"}:
                    pending_calls.clear()
                    continue
                latest_candidate = None
                user_turns_since_candidate = 0
                pending_calls.clear()
                latest_plan_next_payload = None
                if action_family == "analyze_adjustment" and result_kind == "adjustment_analysis":
                    has_non_actionable_adjustment_analysis = True
                continue
            call_id = str(part.tool_call_id or "")
            call_payload = pending_calls.get(call_id) or {}
            result_stage = str(result.get("stage") or call_payload.get("stage") or "").strip()
            is_preview_result = (
                result_kind == "preview_only"
                and result_stage == "preview"
            )
            if is_preview_result and _result_explicitly_has_no_executable_preview(result):
                latest_candidate = None
                user_turns_since_candidate = 0
                pending_calls.clear()
                latest_plan_next_payload = None
                continue
            call_action_family = str(call_payload.get("action_family") or "").strip()
            effective_action_family = action_family or call_action_family
            call_stage = str(call_payload.get("stage") or "").strip()
            if (
                not is_preview_result
                and effective_action_family in _EXECUTE_PLAN_ACTION_VIEW_FAMILIES
                and isinstance(latest_plan_next_payload, dict)
            ):
                candidate = _build_plan_confirmation_candidate_from_payload(
                    latest_plan_next_payload,
                    summary=latest_plan_next_payload.get("preview_summary")
                    or latest_plan_next_payload.get("summary")
                    or "",
                )
                if candidate is not None:
                    if current_user_turn > 0:
                        candidate["created_turn"] = current_user_turn
                    latest_candidate = candidate
                    user_turns_since_candidate = 0
                pending_calls.clear()
                continue
            if not is_preview_result and (
                result.get("applied") is True
                or call_stage == "apply"
            ):
                if effective_action_family in _PENDING_PLAN_ACTION_FAMILIES:
                    latest_candidate = None
                    user_turns_since_candidate = 0
                    pending_calls.clear()
                continue
            if not is_preview_result:
                continue
            if effective_action_family not in _PENDING_PLAN_ACTION_FAMILIES:
                continue
            if not call_payload:
                continue
            pending_payload = _merge_plan_next_payload_for_pending_candidate(
                normalize_plan_action_payload(dict(call_payload)),
                latest_plan_next_payload,
            )
            result_facts = result.get("facts")
            if isinstance(result_facts, dict) and result_facts:
                pending_payload["facts"] = result_facts
                result_version = _as_int(
                    result_facts.get("source_backend_version")
                    or result_facts.get("planning_version")
                )
                if result_version > 0:
                    pending_payload["planning_version"] = result_version
            top_level_version = _as_int(result.get("source_backend_version") or result.get("planning_version"))
            if top_level_version > 0:
                pending_payload["planning_version"] = top_level_version
            candidate = _build_plan_confirmation_candidate_from_payload(
                pending_payload,
                summary=result.get("summary") or call_payload.get("preview_summary") or "",
            )
            if candidate is None:
                continue
            if (
                has_non_actionable_adjustment_analysis
                and str(candidate.get("action_family") or "").strip() == "generate_plan"
            ):
                continue
            if current_user_turn > 0:
                candidate["created_turn"] = current_user_turn
            latest_candidate = candidate
            user_turns_since_candidate = 0

    return latest_candidate


def _latest_structured_goal_plan_preview(messages: list[Any] | None) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "plan_next_action":
            continue
        result = _parse_tool_return_json(part.content)
        if not isinstance(result, dict):
            continue
        if str(result.get("stage") or "").strip() != "preview":
            continue
        if proposal_compiler.structured_goal_from_composite_proposal(result) is None:
            continue
        latest = result
    return latest


def _latest_goal_scoped_plan_preview(messages: list[Any] | None) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for part in _iter_tool_return_parts(messages):
        if part.tool_name != "plan_next_action":
            continue
        result = _parse_tool_return_json(part.content)
        if not isinstance(result, dict):
            continue
        if str(result.get("stage") or "").strip() != "preview":
            continue
        composite = result.get("composite_proposal") or result.get("compositeProposal")
        if not isinstance(composite, dict):
            continue
        goal = composite.get("goal")
        if not isinstance(goal, dict):
            continue
        goal_type = str(goal.get("goal_type") or goal.get("goalType") or "").strip()
        if goal_type not in proposal_compiler.STRUCTURED_USER_GOAL_TYPES:
            continue
        latest = result
    return latest


def _structured_goal_clarification_reply(source: dict[str, Any] | None) -> str | None:
    resolution = proposal_compiler.resolve_structured_goal_clarification(source)
    if not resolution.needed:
        return None
    note = resolution.questions[0] if resolution.questions else ""
    scope_text = "、".join(resolution.scope_values)
    if note:
        return (
            f"我先确认一下范围：{note}\n\n"
            "这轮不会改动当前方案。你可以补充一下具体按哪个专业层级处理，"
            "我再给你列出调整预览。"
        )
    if scope_text:
        return (
            f"我先确认一下“{scope_text}”具体按哪个范围处理。\n\n"
            "这轮不会改动当前方案。你补充清楚后，我再给你列出调整预览。"
        )
    return "这次调整范围还不够明确，这轮不会改动当前方案。你补充清楚后，我再给你列出调整预览。"


def _latest_plan_mutation_attempt_result(messages: list[Any] | None) -> dict[str, Any] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        if part.tool_name not in {"execute_plan_action", "plan_next_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        action_family = str(data.get("action_family") or "").strip()
        if action_family in _PENDING_PLAN_ACTION_FAMILIES:
            return data
    return None


_READONLY_CLOSURE_ACK_PHRASES = {
    "嗯那就这样",
    "那就这样",
    "那先这样",
    "先这样",
    "先这样吧",
    "就这样",
    "就这样吧",
    "好先这样",
    "好的先这样",
    "行先这样",
    "嗯先这样",
    "嗯就这样",
    "先按这个吧",
    "先按刚才的吧",
}


def _pending_semantic_decision(action: str, confidence: float = 1.0, reason: str = "") -> SimpleNamespace:
    return SimpleNamespace(action=action, confidence=confidence, reason=reason)


def _normalize_confirmation_only_text(content: str, *, strip_fullwidth_question: bool = False) -> str:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    punctuation = "。.!！?？" if strip_fullwidth_question else "。.!！?"
    normalized = normalized.strip(punctuation)
    return normalized


def _is_readonly_closure_ack(content: str) -> bool:
    normalized = _normalize_confirmation_only_text(content, strip_fullwidth_question=True)
    if not normalized:
        return False
    return normalized in _READONLY_CLOSURE_ACK_PHRASES


def _no_pending_confirmation_guard_reply() -> str:
    return (
        "我这边没有上一轮待确认，也没有待执行的方案调整或报考想法。"
        "下一步可以直接说想审查方案、生成调整预览、调整排序，或说明要保留/避开的方向；"
        "涉及正式更新时，我会先列出内容或预览，确认前不会改方案。"
    )


async def _save_direct_guard_history(
    history_store: ChatHistoryStore,
    session_id: str,
    history: list[Any] | None,
    content: str,
    reply: str,
    *,
    model_name: str,
    turn_event: dict[str, Any] | None = None,
    request_context: RequestContext | None = None,
    user_id: str = "",
) -> None:
    new_messages = [
        ModelRequest(parts=[UserPromptPart(content=content)]),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]
    try:
        history_to_save = list(history or [])
        saved_messages = _append_turn_observability_messages(
            new_messages,
            turn_event,
            request_context=request_context,
            session_id=session_id,
            user_id=user_id,
            prompt_length=len(content or ""),
        )
        history_to_save.extend(saved_messages)
        await history_store.save(session_id, history_to_save)
    except Exception:
        logger.exception("Failed to save direct guard history: session_id=%s model=%s", session_id, model_name)


def _sanitize_reply_for_user(reply: str) -> str:
    """清理回复中不应暴露给用户的内部标记。"""
    import re
    original_reply = reply
    for pattern, replacement in _USER_REPLY_ENGLISH_WORD_REPLACEMENTS:
        reply = pattern.sub(replacement, reply)
    # 移除 [LLM_INTERNAL] 开头的整行
    reply = re.sub(r'\n?\[LLM_INTERNAL\][^\n]*', '', reply)
    # 移除行内的 [LLM_INTERNAL] 标记
    reply = re.sub(r'\[LLM_INTERNAL\]\s*', '', reply)
    if any(marker in reply for marker in _USER_REPLY_FORCED_CHOICE_MARKERS):
        cleaned_lines: list[str] = []
        for line in reply.splitlines():
            if not any(marker in line for marker in _USER_REPLY_FORCED_CHOICE_MARKERS):
                cleaned_lines.append(line)
                continue
            sentence_parts = re.findall(r"[^。！？.!?\n]+[。！？.!?]?", line)
            kept = [
                part
                for part in sentence_parts
                if not any(marker in part for marker in _USER_REPLY_FORCED_CHOICE_MARKERS)
            ]
            cleaned_line = "".join(kept).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        reply = "\n".join(cleaned_lines)
    # 3.0.3 确认协议下，采纳偏好/要求不会把基础候选池永久改小。
    # 旧兼容路径或模型复述里可能残留“按要求过滤后候选还剩多少”的句子，
    # 这类统计只允许出现在显式候选查询结果里，不应作为采纳确认后的后续使用说明。
    reply = re.sub(
        r'(?m)^\s*[-*]?\s*后续使用[：:][^\n]*(?:按这条要求过滤后|候选大约|整体候选)[^\n]*(?:\n|$)',
        '',
        reply,
    )
    reply = re.sub(
        r'(?m)^\s*[^\n]*(?:按这条要求过滤后)[^\n]*(?:候选大约|整体候选)[^\n]*(?:\n|$)',
        '',
        reply,
    )
    compact = _compact_plan_reply_text(reply)
    candidate_pool_semantics_claim = any(
        marker in compact
        for marker in (
            "收窄候选范围",
            "候选池会收窄",
            "候选池会大幅收窄",
            "候选池会变小",
            "这些方向都不会再进入候选",
            "不再进入候选",
            "自动过滤",
        )
    )
    if any(
        marker in compact
        for marker in (
            "偏好",
            "要求",
            "意向",
            "采纳",
            "确认",
            "后续推荐",
            "后续生成方案",
            "影响分析",
            "先看影响",
            "作为后续参考",
        )
    ) or ("影响" in compact and candidate_pool_semantics_claim):
        before_candidate_pool_semantics = reply
        reply = re.sub(
            r"(?:你的)?候选池会(?:大幅|明显|显著)?(?:收窄|变窄)",
            "基础候选池不会因此变小",
            reply,
        )
        reply = reply.replace("会收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
        reply = reply.replace("收窄候选范围", "不会改小基础候选池；会作为后续推荐、方案检查和方案调整参考")
        reply = reply.replace("候选池会变小", "基础候选池不会因此变小")
        reply = reply.replace("这些方向都不会再进入候选", "后续推荐和方案检查会把这些方向作为排除参考，基础候选池不会因此变小")
        reply = reply.replace("不再进入候选", "会作为排除参考")
        reply = re.sub(
            r"自动过滤(?P<target>[^。！？\n]{1,50}?(?:相关选项|相关方向|相关志愿|选项|方向|志愿))",
            r"把\g<target>作为后续推荐、方案检查和方案调整的排除参考",
            reply,
        )
        reply = reply.replace("自动过滤后续推荐", "作为后续推荐和方案检查的排除参考")
        reply = reply.replace("自动过滤", "作为后续推荐、方案检查和方案调整的排除参考")
        reply = reply.replace("偏好卡片", "待采纳内容")
        reply = reply.replace("要求卡片", "待采纳内容")
        reply = re.sub(
            r"确认后我可以把(?P<topic>[^。！？\n]{0,80}?)整理成确认卡片[，,]?(?P<tail>[^。！？\n]{0,80})[。！？]?",
            r"如果你想正式采用，我可以先把\g<topic>列出来；采纳前不会生效。",
            reply,
        )
        if any(marker in reply for marker in ("整理成确认卡片", "整理成待采纳内容", "整理成待采纳报考条件", "列出来让你采纳")):
            reply = reply.replace("确认后，后续", "采纳后，后续")
            reply = reply.replace("确认后,后续", "采纳后，后续")
            reply = reply.replace("确认后再", "采纳后再")
            reply = reply.replace("确认后会", "采纳后会")
            reply = reply.replace("确认后才会生效", "采纳后才会生效")
            reply = reply.replace("确认后才正式生效", "采纳后才正式生效")
            reply = reply.replace("要不要先确认这些方向？", "要不要我先列出来让你采纳？")
        if (
            reply != before_candidate_pool_semantics
            and "基础候选池" not in reply
            and any(marker in reply for marker in ("排除参考", "方案检查", "方案调整参考"))
        ):
            reply = (
                reply.rstrip()
                + "\n\n补充说明：基础候选池不会因为偏好或要求采纳而永久变小；"
                "采纳后只是作为后续推荐、方案检查和方案调整的参考。"
            )
    reply = _normalize_user_facing_terms(reply)
    reply = re.sub(r"([。！？])\1+", r"\1", reply)
    reply = re.sub(r"(?<=[\u4e00-\u9fff])([.!?])\1+", r"\1", reply)
    if reply != original_reply:
        reply = reply.strip()
    return reply.strip()


def _is_basic_plan_status_question(content: str) -> bool:
    normalized = re.sub(r"\s+", "", (content or "").strip())
    normalized = normalized.strip("。.!！?？")
    if not normalized:
        return False
    return normalized in {
        "方案有了么",
        "方案有了吗",
        "有方案了吗",
        "方案生成了吗",
        "方案出来了吗",
        "当前方案有了吗",
        "现在有方案了吗",
        "现在方案有了吗",
        "看看现在的方案",
        "看看方案",
        "看下方案",
        "看一下方案",
        "方案怎么样了",
        "方案情况",
        "当前方案怎么样",
        "我的方案",
    }


def _prompt_explicitly_readonly(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _READONLY_USER_PROMPT_MARKERS)


def _prompt_is_score_batch_risk_policy_question(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    has_score_boundary = any(
        marker in compact
        for marker in (
            "本科线",
            "批次线",
            "压线",
            "刚过线",
            "刚压",
            "过线不多",
            "只高一点",
        )
    )
    has_risk_request = any(
        marker in compact
        for marker in (
            "别给我画大饼",
            "不要画大饼",
            "画大饼",
            "保底",
            "兜底",
            "保本科",
            "滑档",
            "风险",
        )
    )
    return has_score_boundary and has_risk_request


def _prompt_is_major_group_keep_safest_policy_question(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    has_group_anchor = any(marker in compact for marker in ("专业组", "组内", "这一组", "这个组"))
    has_keep_safest = any(marker in compact for marker in ("只保留", "保留")) and any(
        marker in compact for marker in ("最稳", "更稳", "稳的专业", "安全垫")
    )
    has_question = any(marker in compact for marker in ("行不行", "可不可以", "能不能", "是否", "要不要"))
    explicit_apply = any(marker in compact for marker in ("直接执行", "确认执行", "现在就改", "直接改", "就这么改"))
    return has_group_anchor and has_keep_safest and has_question and not explicit_apply


def _prompt_requires_readonly_policy_answer(content: str | None) -> bool:
    return _prompt_is_score_batch_risk_policy_question(content) or _prompt_is_major_group_keep_safest_policy_question(content)


def _build_score_batch_risk_policy_reply() -> str:
    return (
        "如果分数刚压本科线，不能按“能上本科”乐观处理，要按压线风险来做预案。"
        "建议把目标拆成三层：第一层少量冲本科批里过线要求低、招生计划稳定的机会；第二层重点放稳妥保本科，优先看往年位次、录取最低分和计划变化，不只看分数；"
        "第三层准备兜底方案，包括能接受的民办本科、中外合作或高质量专科，避免只押一个本科批结果导致滑档。"
        "保底位要留足安全垫，专业也要现实一些，不能只放热门专业。下一步需要核对所在省当年本科线、一分一段位次、批次规则和当前方案里的冲稳保比例，再决定本科和专科兜底怎么配。"
    )


def _build_major_group_keep_safest_policy_reply() -> str:
    return (
        "专业组里只保留最稳的专业，可以作为降低组内风险的思路，但不能直接当成长期就业偏好。"
        "在院校专业组模式下，要先看这个专业组的投档规则、组内专业录取率、计划数、专业备注和是否服从调剂；"
        "如果只保留最稳的专业，可能降低被不想读专业分配的风险，但也可能减少组内可选空间，影响专业满足率或让这个专业组不再值得保留。"
        "更稳妥的做法是先读取具体专业组，判断哪些专业是安全垫、哪些专业风险偏高，再决定是保留一个兜底专业、删掉高风险专业，还是生成可确认的调整预览。"
        "确认前不应改动当前方案，也不应写成后续报考参考里的职业或专业偏好。"
    )


def _score_batch_policy_reply_is_sufficient(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    has_boundary = "本科线" in compact or "批次线" in compact
    has_pressure = any(marker in compact for marker in ("压线", "刚过线", "过线不多", "只高一点"))
    has_floor = any(marker in compact for marker in ("保底", "兜底", "保本科", "滑档"))
    return has_boundary and has_pressure and has_floor and "风险" in compact


def _major_group_policy_reply_is_sufficient(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return False
    has_group = "专业组" in compact and "专业" in compact
    has_safety = any(marker in compact for marker in ("录取率", "最稳", "更稳", "安全垫", "兜底"))
    has_boundary = any(marker in compact for marker in ("风险", "调剂", "确认", "当前方案"))
    return has_group and has_safety and has_boundary


def _reply_is_readonly_policy_misroute(reply: str | None) -> bool:
    compact = _compact_plan_reply_text(str(reply or ""))
    if not compact:
        return True
    if any(
        marker in compact
        for marker in (
            "不会写入后续报考参考",
            "还没有生成可执行的调整内容",
            "没有生成可执行的调整内容",
            "这轮还没有生成可点击的方案待采纳内容",
            "待确认内容",
            "待采纳内容",
            "稳定就业导向",
        )
    ):
        return True
    return _reply_looks_like_unbacked_intent_preview(str(reply or "")) or _reply_looks_like_unbacked_plan_action_boundary(str(reply or ""))


def _readonly_policy_fallback_reply_for_prompt(
    content: str | None,
    reply: str | None,
    tool_context_messages: list[Any] | None,
) -> str | None:
    if _prompt_is_score_batch_risk_policy_question(content):
        if _score_batch_policy_reply_is_sufficient(reply) and not _reply_is_readonly_policy_misroute(reply):
            return None
        tool_reply = _latest_readonly_tool_reply(tool_context_messages)
        if _score_batch_policy_reply_is_sufficient(tool_reply):
            return tool_reply
        return _build_score_batch_risk_policy_reply()
    if _prompt_is_major_group_keep_safest_policy_question(content):
        if _major_group_policy_reply_is_sufficient(reply) and not _reply_is_readonly_policy_misroute(reply):
            return None
        return _build_major_group_keep_safest_policy_reply()
    return None


def _prompt_rejects_current_plan_action(content: str | None) -> bool:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _PLAN_ACTION_NEGATIVE_ACK_MARKERS)


def _build_basic_plan_status_reply(planning: PlanningSummary) -> str:
    total = planning.ordered_total or planning.working_total
    target = (
        planning.ordered_target_total
        or planning.working_target_total
        or max(planning.ordered_total, planning.working_total, total)
    )
    if total <= 0:
        return (
            '当前还没有生成方案。'
            '你可以直接说“帮我生成一版方案”，'
            '我会根据你的成绩和偏好先生成一版方案给你看，确认后再生成正式顺序。'
        )

    if planning.ordered_total >= target:
        count_text = f'你的方案已经填满了 {planning.ordered_total} 个志愿'
    elif planning.ordered_total > 0:
        count_text = f'你的方案目前有 {planning.ordered_total} 个志愿（目标 {target} 个）'
    else:
        count_text = f'当前已加入方案 {planning.working_total} 个志愿（目标 {target} 个），还没有生成正式顺序'

    lines = [f'{count_text}。']

    tier = planning.tier_counts
    if tier:
        chong = tier.get('冲', 0)
        wen = tier.get('稳', 0)
        bao = tier.get('保', 0)
        if chong or wen or bao:
            lines.append(f'其中冲 {chong} 个、稳 {wen} 个、保 {bao} 个。')

    if planning.sample_schools:
        school_text = '、'.join(planning.sample_schools[:4])
        lines.append(f'涉及院校包括{school_text}等。')

    pref_parts = []
    if planning.positive_regions:
        pref_parts.append(f'地区偏好{chr(0x3001).join(planning.positive_regions[:3])}')
    if planning.positive_majors:
        pref_parts.append(f'专业偏好{chr(0x3001).join(planning.positive_majors[:3])}')
    if pref_parts:
        lines.append(f'你的{chr(0x3001).join(pref_parts)}。')

    risk_total = planning.review_risk_count + planning.review_warn_count
    if risk_total > 0 and planning.risk_summaries:
        risk_desc = '、'.join(planning.risk_summaries[:2])
        if planning.review_risk_count > 0:
            lines.append(f'\n需要留意的风险：{risk_desc}。')
        else:
            lines.append(f'\n有几点提醒：{risk_desc}。')
    elif risk_total == 0 and planning.ordered_total > 0:
        lines.append('\n审查结果良好，暂时没有明显风险。')

    lines.append('\n你可以说“帮我审查一下”看详细情况，或者告诉我想怎么调整。')
    return ''.join(lines)


def _needs_plan_first_guard_reply(
    content: str | None,
    resolution: proposal_compiler.NeedsPlanFirstResolution | None = None,
) -> str:
    if resolution is not None and resolution.primary_reply:
        return resolution.primary_reply
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if "民办" in compact or "公办" in compact:
        focus = "公办/民办这类要求"
    elif "中外合作" in compact:
        focus = "中外合作这类要求"
    elif any(marker in compact for marker in ("保底", "稳", "冲", "风险", "太冲")):
        focus = "冲稳保或风险这类要求"
    else:
        focus = "这类方案范围要求"
    return (
        "当前还没有生成正式方案，所以没法判断或调整“刚才/当前方案”里的具体志愿。"
        f"这轮不会把{focus}写成新的报考偏好，也不会改动当前方案。"
        "也就是说，这轮不会改动方案。"
        "你可以先让我生成一版方案；有了正式方案后，我再按这条要求检查或调整。"
    )


def _no_formal_plan_review_boundary_reply(
    content: str | None,
    *,
    pending_state: dict[str, Any] | None = None,
) -> str:
    compact = re.sub(r"\s+", "", str(content or "").strip())
    path_parts: list[str] = []
    if "强基" in compact:
        path_parts.append("强基")
    if "普通批" in compact:
        path_parts.append("普通批")
    if "提前批" in compact:
        path_parts.append("提前批")
    path_text = "、".join(path_parts) if path_parts else "这条路径"
    pending_note = ""
    if isinstance(pending_state, dict) and str(pending_state.get("status") or "").strip() == "active":
        summary = str(pending_state.get("summary") or "").strip()
        if summary:
            pending_note = f"当前还有一项待采纳内容：{summary}；点采纳前不会生效。"
        else:
            pending_note = "当前还有一项待采纳内容；点采纳前不会生效。"
    return (
        f"现在还没有正式的{path_text}志愿方案，所以不能按“这版方案”做正式方案审查，"
        "这轮也不会自动生成或改动普通批方案。"
        f"{pending_note}"
        "就当前思路看，可以把强基作为额外冲刺路径，同时另做普通批方案承接；"
        "等正式方案生成后，再检查冲稳保、专业接受度和风险会更准确。"
    )


_READONLY_INTERRUPTION_TOOL_NAMES = {
    "query_volunteer_plan",
    "analyze_current_interest",
    "analyze_current_interest_profile",
    "analyze_current_school_interest",
    "analyze_current_major_interest",
    "analyze_current_region_interest",
    "analyze_current_career_direction",
    "compare_majors",
    "compare_majors_adhoc",
    "compare_major_options",
    "compare_schools",
    "compare_schools_adhoc",
    "get_major_introduction",
    "get_major_introductions",
    "get_school_introduction",
    "query_admission_score",
    "query_score_line",
    "validate_major_subjects",
    "validate_plan_params",
    "answer_admission_policy_question",
    "search_official_admission_sources",
}


def _agent_observability_tool_names(agent_observability: dict[str, Any] | None) -> list[str]:
    if not isinstance(agent_observability, dict):
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    raw_first = agent_observability.get("firstToolNames")
    if isinstance(raw_first, list):
        for name in raw_first:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    for node in agent_observability.get("nodeTimings") or []:
        if not isinstance(node, dict):
            continue
        raw_names = node.get("toolNames")
        if not isinstance(raw_names, list):
            continue
        for name in raw_names:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    raw_counts = agent_observability.get("toolNameCounts")
    if isinstance(raw_counts, dict):
        for name in raw_counts:
            text = str(name or "").strip()
            if text and text not in seen:
                ordered.append(text)
                seen.add(text)
    return ordered


def _agent_interruption_looks_readonly(
    content: str,
    agent_observability: dict[str, Any] | None,
) -> bool:
    tool_names = _agent_observability_tool_names(agent_observability)
    if tool_names:
        if any(name in _INTENT_PREVIEW_TOOL_NAMES for name in tool_names):
            return False
        if any(name in _READONLY_INTERRUPTION_TOOL_NAMES for name in tool_names):
            return True

    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    if _prompt_explicitly_readonly(content):
        return True
    return any(
        marker in compact
        for marker in (
            "哪个更适合",
            "哪个更稳",
            "哪个更实际",
            "会不会太",
            "能不能",
            "是不是",
            "怎么样",
            "怎么判断",
            "有什么影响",
            "看看影响",
            "先看看",
            "先查一下",
            "帮我看下",
            "帮我看看",
        )
    )


def _interrupted_prompt_prefers_plan_status_fallback(
    content: str,
    planning: PlanningSummary | None,
) -> bool:
    if planning is None or (planning.ordered_total <= 0 and planning.working_total <= 0):
        return False
    compact = re.sub(r"\s+", "", str(content or "").strip())
    if not compact:
        return False
    return any(marker in compact for marker in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS) or any(
        marker in compact
        for marker in (
            "这版",
            "当前这版",
            "太冲",
            "冒险",
            "保底",
            "公办",
            "民办",
            "中外合作",
            "学费",
            "省外",
            "本省",
        )
    )


def _describe_interrupted_readonly_request(
    content: str,
    batch: str | None = "01",
    agent_observability: dict[str, Any] | None = None,
) -> str:
    tool_names = set(_agent_observability_tool_names(agent_observability))
    compact = str(content or "").strip()
    if "analyze_current_region_interest" in tool_names:
        return f"你刚才问的是“{compact}”" if compact else "你刚才问的是地域选择相关问题"

    major_names: list[str] = []
    seen: set[str] = set()
    for mention in resolve_major_mentions_from_text(content, batch):
        name = str(getattr(mention, "canonical_name", "") or "").strip()
        if name and name not in seen:
            major_names.append(name)
            seen.add(name)
    if len(major_names) >= 2:
        return f"你刚才问的是 {major_names[0]} 和 {major_names[1]} 的比较"
    if len(major_names) == 1:
        return f"你刚才问的是 {major_names[0]} 相关问题"
    if compact:
        return f"你刚才问的是“{compact}”"
    return "你刚才这个问题"


def _build_agent_interruption_fallback_reply(
    content: str,
    planning: PlanningSummary | None,
    agent_observability: dict[str, Any] | None = None,
    *,
    batch: str | None = "01",
) -> str | None:
    """Return a safe user-facing reply when the model run is interrupted.

    This is intentionally conservative: it only uses already loaded planning
    summary facts and never claims that a tool action was completed.
    """
    if not isinstance(agent_observability, dict) or not agent_observability.get("failedNode"):
        return None

    if (
        _agent_interruption_looks_readonly(content, agent_observability)
        and not _interrupted_prompt_prefers_plan_status_fallback(content, planning)
    ):
        subject = _describe_interrupted_readonly_request(content, batch, agent_observability)
        return (
            "这轮模型服务中断了，我没有改动你的方案，也没有把偏好写入后续参考。"
            f"{subject}，这次没能完整生成分析结论；"
            "你可以继续围绕刚才的问题追问，我会按只读分析处理。"
        )

    prefix = (
        "这轮模型服务中断了，我先不改动你的方案或偏好。"
        "为了不让你一直等，我先根据已经读取到的信息给一个安全版结论："
    )
    if planning is not None and (planning.ordered_total > 0 or planning.working_total > 0):
        status_reply = _build_basic_plan_status_reply(planning).strip()
        if status_reply:
            return f"{prefix}\n\n{status_reply}"

    return (
        "这轮模型服务中断了，我先不改动你的方案或偏好。"
        "你可以再发一次刚才的问题，我会继续按当前会话信息处理；"
        "如果涉及方案调整，我仍会先给预览，等你确认后再执行。"
    )


def _should_guard_plan_reply(content: str) -> bool:
    return any(keyword in content for keyword in _PLAN_STYLE_GUARD_PROMPT_KEYWORDS)


def _normalize_user_facing_terms(reply: str) -> str:
    """Remove internal product terms from user-facing replies."""
    if not isinstance(reply, str):
        return reply
    replacements = (
        ("待确认卡片", "待采纳内容"),
        ("采纳卡片", "待采纳内容"),
        ("方案确认卡片", "方案调整预览"),
        ("确认卡片缺少校验信息", "这次操作缺少校验信息"),
        ("这张确认卡片缺少校验信息", "这次操作缺少校验信息"),
        ("这张确认卡片已经失效", "这次待采纳内容已经失效"),
        ("这张确认卡片和当前待确认操作不一致", "这次操作和当前待采纳内容不一致"),
        ("这张确认卡片的操作类型不完整", "这次操作类型不完整"),
        ("这张确认卡片缺少可执行内容", "这次待采纳内容缺少可执行内容"),
        ("确认卡片还没有采纳", "这次内容还没有采纳"),
        ("这张确认卡片还没有采纳", "这次内容还没有采纳"),
        ("确认卡片里的“采纳”", "“采纳”"),
        ("点击卡片里的“采纳”", "点击“采纳”"),
        ("点击最新确认卡片", "点最新内容里的“采纳”"),
        ("最新确认卡片", "最新待采纳内容"),
        ("最新采纳卡片", "最新待采纳内容"),
        ("重新生成确认卡片", "重新列出待采纳内容"),
        ("生成确认卡片", "列出待采纳内容"),
        ("整理成确认卡片", "列出来让你采纳"),
        ("确认卡片", "待采纳内容"),
        ("点击卡片采纳", "点“采纳”"),
        ("点击卡片确认", "点“确认执行”"),
        ("点击卡片", "点“采纳”"),
        ("卡片采纳后", "采纳后"),
        ("卡片确认", "确认"),
        ("硬性要求", "报考要求"),
        ("硬要求", "报考要求"),
        ("硬约束", "报考要求"),
        ("软偏好", "优先考虑的方向"),
        ("软意向", "优先考虑的方向"),
        ("约束", "要求"),
        ("志愿组", "专业组"),
        ("加入画像", "记成后续报考参考"),
        ("纳入画像", "纳入后续报考参考"),
        ("写入画像", "记成后续报考参考"),
        ("更新画像", "更新后续报考参考"),
        ("新的画像结论", "新的报考参考结论"),
        ("画像结论", "报考参考结论"),
        ("画像系统", "报考参考信息"),
        ("当前画像", "当前报考参考信息"),
        ("已有画像", "已有报考参考信息"),
        ("用户画像", "报考参考信息"),
        ("学生画像", "学生报考参考信息"),
        ("画像", "报考参考信息"),
        ("工具识别时", "这里需要注意的是"),
        ("工具识别", "这里"),
        ("工具返回", "查询结果"),
        ("工具调用", "处理过程"),
        ("被系统标记为", "属于"),
        ("系统标记为", "归为"),
        ("系统检测到", "我看到"),
        ("系统识别到", "我看到"),
        ("系统发现", "我看到"),
        ("系统建议", "建议"),
        ("系统提示", "当前提示"),
        ("系统给不出直接处理", "这类提醒需要你先取舍后再处理"),
        ("系统给不出", "当前还不能直接给出"),
        ("核心原因不是系统做不到，而是", "核心原因是"),
        ("不是系统做不到，而是", "主要是"),
        ("不是系统搜不到，而是", "主要是"),
        ("系统现在给不了你", "当前还没有"),
        ("系统搜不到", "当前没找到"),
        ("系统做不到", "当前条件还不够"),
        ("系统同样能替换", "也可以先列出替换预览"),
        ("系统同样能", "也可以先"),
        ("系统预估", "目前看"),
        ("系统不会擅自", "不会擅自"),
        ("系统不会", "不会"),
        ("系统需要你明确取舍范围", "需要你明确取舍范围"),
        ("系统需要你", "需要你"),
        ("系统需要找到", "需要先找到"),
        ("系统暂时给不出自动替换方案", "当前还不能直接给出替换预览"),
        ("系统暂时给不出", "当前还不能直接给出"),
        ("系统给不出自动替换方案", "当前还不能直接给出替换预览"),
        ("系统都需要你", "都需要你"),
        ("系统目前都没法直接处理", "这些提醒需要你先取舍后再处理"),
        ("系统目前都无法直接处理", "这些提醒需要你先取舍后再处理"),
        ("系统目前在", "当前在"),
        ("系统目前没找到", "当前还没找到"),
        ("系统目前没有找到", "当前还没找到"),
        ("系统会尝试", "我会先尝试"),
        ("系统只能", "当前只能"),
        ("系统可以一键", "可以先"),
        ("系统可以", "可以"),
        ("系统不知道", "我还不知道"),
        ("系统想帮你", "我可以先"),
        ("系统会帮你生成", "我会先列出"),
        ("系统会帮你", "我会"),
        ("系统会生成", "我会先列出"),
        ("系统会替换", "我会先列出替换预览"),
        ("系统暂时没法一键帮你处理", "这类提醒需要你先取舍后再处理"),
        ("系统暂时没法", "当前还不能"),
        ("系统给了", "我整理出"),
        ("系统给出", "我整理出"),
        ("系统能直接处理的是", "可以先看调整预览的是"),
        ("系统能直接处理的", "可以先看调整预览的"),
        ("系统能直接处理", "可以先看调整预览"),
        ("系统能直接执行", "可以先列出调整预览"),
        ("系统能执行", "可以先列出调整预览"),
        ("系统没法自动执行", "这类情况需要你先取舍"),
        ("系统没法执行", "这类情况需要你先取舍"),
        ("系统换不动", "当前还缺少合适的替换方案"),
        ("系统目前没法", "当前还不能"),
        ("系统没法", "当前还不能"),
        ("系统暂时补不进", "当前还缺少合适的补位选择"),
        ("系统补不进", "当前还缺少合适的补位选择"),
        ("能否自动修复", "怎么处理"),
        ("能否自动处理", "怎么处理"),
        ("能自动处理吗", "可以怎么处理"),
        ("系统尝试", "我查了一下"),
        ("系统判断", "当前判断"),
        ("系统凑不出", "当前凑不出"),
        ("系统暂时无法", "当前暂时无法"),
        ("系统无法", "当前还不能"),
        ("自动补齐", "直接补齐"),
        ("自动补足", "先看是否能补足"),
        ("自动把", "直接把"),
        ("自动调整方案", "调整预览"),
        ("自动替换方案", "替换预览"),
        ("自动执行", "确认后再执行"),
        ("自动应用", "直接执行"),
        ("自动修复", "直接处理"),
        ("自动处理", "直接处理"),
        ("可立即处理", "可以先列出调整预览"),
        ("可执行的调整预览", "可确认的调整预览"),
        ("可执行的处理预览", "可确认的处理预览"),
        ("可执行的替换预览", "可确认的替换预览"),
        ("可执行的移除预览", "可确认的移除预览"),
        ("可执行的补充预览", "可确认的补充预览"),
        ("可执行预览", "调整预览"),
        ("可执行的处理内容", "可确认的处理内容"),
        ("可以直接处理", "可以先列出调整预览"),
        ("可以自动处理", "可以先列出调整预览"),
        ("哪些可以自动处理", "哪些可以先出调整预览"),
        ("已就绪，点确认就能执行", "可以先看调整预览，确认前不会改方案"),
        ("点确认就能执行", "确认前不会改方案"),
        ("点确认就执行", "确认前不会改方案"),
        ("确认就能执行", "确认前不会改方案"),
        ("确认就执行", "确认前不会改方案"),
        ("直接确认应用", "确认后再执行"),
        ("修复预览", "调整预览"),
        ("修复结果", "处理结果"),
        ("修复方向", "处理方向"),
        ("修复", "处理"),
        ("处理高收费志愿", "高收费志愿"),
        ("处理高收费", "高收费志愿"),
        ("处理中外合作办学项目", "中外合作项目"),
        ("处理中外合作", "中外合作项目"),
        ("处理非意向托底专业", "非意向兜底专业"),
        ("处理非意向托底", "非意向兜底专业"),
        ("处理数量校验", "补足志愿数量"),
        ("处理录取率梯度断层", "补齐录取率梯度"),
        ("处理录取率倒挂", "调整录取率顺序"),
        ("处理兜底专业不足", "补兜底专业"),
        ("处理组内安全垫不足", "补兜底专业"),
        ("数量校验", "志愿数量"),
        ("冲稳保配比暂时无法自动处理", "冲稳保结构暂时还调不齐"),
        ("录取率梯度断层暂时无法自动处理", "录取率梯度暂时还补不齐"),
        ("预览参考状态", "处理方向参考"),
        ("被卡住了", "需要你先决定"),
        ("被卡住", "需要你先决定"),
        ("卡住了", "需要你先决定"),
        ("卡住", "需要你先决定"),
        ("暂时动不了", "需要你先取舍或放宽条件"),
        ("没法直接一键处理", "需要你先取舍后再处理"),
        ("无法直接一键处理", "需要你先取舍后再处理"),
        ("不能直接一键处理", "需要你先取舍后再处理"),
        ("一键处理", "直接处理"),
        ("一键替换", "替换"),
        ("一键按", "按"),
        ("候选机会池子已经见底了", "当前符合条件的可选志愿已经不多"),
        ("候选机会池子", "可选志愿范围"),
        ("给我个明确态度，我立刻处理", "你确定取舍范围后，我先列出调整预览"),
        ("给我个明确态度", "你可以先确定取舍范围"),
        ("给出明确态度", "明确取舍范围"),
        ("给个明确态度", "明确取舍范围"),
        ("给一个明确态度", "明确取舍范围"),
        ("才敢动", "再处理"),
        ("我立刻处理", "我先列出调整预览"),
        ("我就能换", "我可以先列出替换预览"),
        ("我就能处理", "我可以先列出调整预览"),
        ("我就能直接处理", "我可以先列出调整预览"),
        ("我就能帮你生成", "我会先列出"),
        ("我就能出替换方案", "我可以先列出替换预览"),
        ("我就能给你生成具体的调整预览", "我可以先列出具体调整预览"),
        ("我立刻出具体方案", "我先列出具体调整预览"),
        ("我立刻出", "我先列出"),
        ("我这边能出", "我可以先列出"),
        ("给句准话", "明确取舍范围"),
        ("技术 bug", "方案本身出错"),
        ("技术难点", "需要先注意的一点"),
        ("技术问题", "处理条件还不充分"),
        ("巧妇难为无米之炊", "当前可选志愿范围不够"),
        ("无法批量处理", "不能一次性处理完"),
        ("组内安全垫专业", "兜底专业"),
        ("组内安全垫", "兜底专业"),
        ("安全垫专业", "兜底专业"),
        ("安全垫", "兜底"),
        ("暂时无法自动补强安全垫", "当前暂时缺少合适的补位选择"),
        ("暂时无法自动补强", "当前暂时缺少合适的补位选择"),
        ("放宽约束", "放宽报考条件"),
        ("补充候选", "补充可选志愿"),
        ("需要人工调整", "需要你先取舍或手动调整"),
        ("人工调整", "手动调整"),
        ("候选池", "可选范围"),
        ("候选供给", "可选志愿"),
        ("系统阻塞", "需要你先决定是否接受调整范围变化"),
        ("被系统阻塞", "需要你先决定是否接受调整范围变化"),
        ("阻塞原因", "需要注意"),
        ("无法生成确认卡片", "还不能直接执行"),
        ("不能生成确认卡片", "还不能直接执行"),
        ("无法生成确认", "还不能直接执行"),
        ("不能生成确认", "还不能直接执行"),
        ("替换预览会改变专业组数量，需要你先取舍后再处理", "替换可能会影响整组志愿的搭配，需要你先确认哪些一定不要、哪些可以接受"),
        ("调整预览会改变专业组数量，需要你先取舍后再处理", "替换可能会影响整组志愿的搭配，需要你先确认哪些一定不要、哪些可以接受"),
        ("处理预览没有为目标专业组补足组内安全垫专业，暂不允许确认应用", "当前还没找到适合补进该专业组的兜底专业，建议先看是否放宽专业或院校范围"),
        ("处理预览没有为目标专业组补足兜底专业，暂不允许确认应用", "当前还没找到适合补进该专业组的兜底专业，建议先看是否放宽专业或院校范围"),
        ("替换预览会改变专业组数量，暂不允许确认应用", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("调整预览会改变专业组数量，暂不允许确认应用", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("替换会改变专业组数量，当前不建议直接确认", "替换可能会影响整组志愿的搭配，需要你先确认是否接受这类调整"),
        ("替换会改变专业组数量", "替换可能会影响整组志愿的搭配"),
        ("替换同样会影响专业组数量", "替换同样会影响整组志愿搭配"),
        ("会影响专业组数量", "会影响整组志愿搭配"),
        ("替换后专业组数量会变", "替换后专业组搭配会变"),
        ("会改变专业组数量", "可能会影响整组志愿的搭配"),
        ("暂不允许确认应用", "需要你先看清影响后再决定"),
        ("自动确认", "直接确认"),
        ("系统暂不支持", "当前不建议"),
        ("暂不能自动处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂不能直接处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂时不能直接处理", "建议你先查看具体影响，或调整筛选范围后再试"),
        ("暂时不建议直接处理", "建议先看清影响后再决定"),
        ("blocked", "需要你先决定是否接受调整范围变化"),
        ("preview_only", "先作为处理方向参考"),
        ("草稿方案", "方案"),
        ("方案草稿", "方案"),
        ("草稿", "方案"),
        ("已应用修复建议", "已按处理建议更新方案"),
        ("修复建议：", "处理内容："),
        ("修复建议", "处理建议"),
        ("修复类型：", "处理方式："),
        ("应用前预览：", "处理前预览："),
        ("复验结果：本次对应问题已通过复验。", "检查结果：这次对应的问题已通过检查。"),
        ("复验结果：仍需要继续检查相关风险。", "检查结果：还需要继续关注相关风险。"),
    )
    normalized = reply
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("待采纳内容采纳", "采纳")
    normalized = normalized.replace("点“采纳”里的“采纳”", "点“采纳”")
    normalized = normalized.replace("点击“采纳”里的“采纳”", "点击“采纳”")
    normalized = normalized.replace("请按最新待采纳内容操作", "请以最新内容为准操作")
    normalized = normalized.replace("以最新待采纳内容为准", "以最新内容为准")
    normalized = normalized.replace("必须满足或必须避开的报考条件过滤", "按已确认的报考条件过滤")
    normalized = normalized.replace("必须满足或必须避开的报考条件命中项", "已确认报考条件命中的志愿")
    normalized = normalized.replace("对英语能力有需要确认的报考条件", "对英语能力有明确要求")
    normalized = normalized.replace("对英语能力有必须满足或必须避开的报考条件", "对英语能力有明确要求")
    normalized = re.sub(
        r"对([^，。！？\n]{1,12})有必须满足或必须避开的报考条件",
        r"对\1有明确要求",
        normalized,
    )
    normalized = normalized.replace("有必须满足或必须避开的报考条件", "有需要确认的报考条件")
    normalized = normalized.replace("报考参考信息信息", "报考参考信息")
    normalized = normalized.replace("当前当前", "当前")
    normalized = normalized.replace("不足，当前暂时", "不足，暂时")
    normalized = normalized.replace("直接直接", "直接")
    normalized = normalized.replace("所以 需要你先决定是否接受调整范围变化 了", "所以需要你先决定是否接受这类调整")
    normalized = normalized.replace("需要你先决定是否接受调整范围变化 了", "需要你先决定是否接受这类调整")
    normalized = normalized.replace("需要你先决定原因", "需要你先决定")
    normalized = normalized.replace("暂被阻塞", "暂时不能直接处理")
    normalized = normalized.replace("被阻塞", "暂时不能直接处理")
    normalized = normalized.replace("暂时还不可以先看调整预览", "暂时需要你先取舍或放宽条件")
    normalized = normalized.replace("直接处理方向", "处理方向")
    normalized = normalized.replace("直接处理建议", "处理建议")
    normalized = normalized.replace("可以直接处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("可以立即处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("能直接处理的有", "可以先看调整预览的有")
    normalized = normalized.replace("能直接处理的", "可以先看调整预览的")
    normalized = normalized.replace("能直接处理", "可以先看调整预览")
    normalized = normalized.replace("可以直接处理", "可以先列出调整预览")
    normalized = normalized.replace("可以立即处理", "可以先列出调整预览")
    normalized = normalized.replace("能自动的", "可以先看调整预览的")
    normalized = normalized.replace("能自动", "可以先看调整预览")
    normalized = normalized.replace("暂时自动不了", "需要你先取舍或放宽条件")
    normalized = normalized.replace("我可以直接帮你", "我可以帮你")
    normalized = normalized.replace("我直接帮你生成", "我先列出")
    normalized = normalized.replace("直接帮你生成", "先列出")
    normalized = normalized.replace("我直接生成", "我先列出")
    normalized = normalized.replace("直接生成一个", "先列出一个")
    normalized = normalized.replace("我可以在方案里把这些志愿整体移除", "我会先列出移除预览")
    normalized = re.sub(
        r"我可以直接帮你(?=(?:对比分析|对比|分析|解释|看一下|看下|看看|看|查一下|查))",
        "我可以帮你",
        normalized,
    )
    normalized = normalized.replace("直接执行方向", "处理方向")
    normalized = normalized.replace("直接执行，不需要你逐条挑", "确认后再执行，不需要你逐条挑")
    normalized = normalized.replace("你确认后就能直接执行", "确认后再执行")
    normalized = normalized.replace("你确认后就能执行", "确认后再执行")
    normalized = normalized.replace("确认后就能直接执行", "确认后再执行")
    normalized = normalized.replace("确认后就能执行", "确认后再执行")
    normalized = normalized.replace("需要你先取舍或放宽条件原因", "需要你先取舍或放宽条件")
    normalized = normalized.replace("当前还缺少合适的替换方案。候选", "当前还缺少合适的替换方案，候选")
    normalized = normalized.replace("没法自动替换", "不能直接替换")
    normalized = normalized.replace("没法一键帮你处理", "需要你先取舍后再处理")
    normalized = normalized.replace("没法直接帮你", "需要你先取舍后再")
    normalized = normalized.replace("当前还不能直接帮你", "需要你先取舍后再")
    normalized = normalized.replace("当前还不能一键替换", "需要你先取舍后再处理")
    normalized = normalized.replace("当前还不能一键帮你处理", "需要你先取舍后再处理")
    normalized = normalized.replace("核心原因不是处理条件还不充分，而是", "核心原因是")
    normalized = normalized.replace("不是处理条件还不充分，而是", "主要是")
    normalized = normalized.replace("不是方案本身出错，而是", "主要是")
    normalized = re.sub(
        r"需要你先取舍后再[“\"]?一键(?:替换|处理|删除|移出)[”\"]?",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = re.sub(
        r"需要你先取舍后再[“\"]?(?:替换|处理|删除|移出)[”\"]?",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = normalized.replace("暂时无法调整配比", "当前还缺少足够合适的志愿来调整配比")
    normalized = normalized.replace("暂时无法补齐录取率梯度", "当前还缺少足够合适的志愿来补齐录取率梯度")
    normalized = normalized.replace("暂时无法补齐梯度", "当前还缺少足够合适的志愿来补齐梯度")
    normalized = normalized.replace("目前当前还不能", "当前还不能")
    normalized = normalized.replace("目前当前还缺少", "当前还缺少")
    normalized = normalized.replace("目前当前", "当前")
    normalized = normalized.replace("当前还不能直接", "需要你先取舍后再")
    normalized = normalized.replace("暂时无法", "当前还不能")
    normalized = re.sub(
        r"(?:当前还不能|当前还无法)(?:一键)?(?:帮你)?(?:直接)?(?:替换|处理|删|删除|移出)",
        "需要你先取舍后再处理",
        normalized,
    )
    normalized = re.sub(
        r"当前还不能(?:自动|直接)?(?:把)?([^，。！？\n]{0,18}?)(?:调到|补足|补齐|处理)",
        r"当前还缺少足够条件处理\1",
        normalized,
    )
    normalized = re.sub(
        r"当前还缺少足够条件处理(?:帮你)?(?:保底|补保底|补几个保底志愿|补充保区候选)",
        "当前还缺少合适的保底志愿",
        normalized,
    )
    normalized = normalized.replace("当前还缺少足够条件处理冲区志愿", "当前还缺少足够合适的志愿来调整冲稳保结构")
    normalized = re.sub(
        r"当前还缺少足够条件处理([^，。！？\n]{1,24})",
        r"当前还缺少足够条件来处理\1",
        normalized,
    )
    normalized = normalized.replace("当前还缺少足够条件处理", "当前还缺少足够条件来处理")
    normalized = re.sub(
        r"可执行的([^，。！？\n]{0,12}?)(?:调整|处理|替换|移除|补充)?方案",
        lambda match: f"可确认的{match.group(1)}调整预览",
        normalized,
    )
    normalized = re.sub(
        r"(?:当前还缺少合适的补位选择|当前还不能补不进)(?:更合适的)?兜底专业",
        "当前还缺少更合适的兜底专业",
        normalized,
    )
    normalized = normalized.replace("需要先人工精简", "需要你先手动精简")
    normalized = normalized.replace("人工精简", "手动精简")
    normalized = re.sub(r"(?:能不能换|能否换|能不能处理)[：:]\s*想换，但", "处理方式：", normalized)
    normalized = re.sub(r"(?:卡在哪|为什么动不了)[：:]", "需要先看清：", normalized)
    normalized = re.sub(
        r"(你(?:给|先给)我[^。！？\n]{0,20}?明确[^。！？\n]{0,20}?，?)(?:我(?:立刻|马上|就能|可以直接)[^。！？\n]{0,30}?)([。！？]?)",
        r"你可以先明确取舍范围，我会先列出调整预览\2",
        normalized,
    )
    normalized = re.sub(
        r"(?:我(?:立刻|马上|就能|可以直接)(?:帮你)?(?:处理|换|调整|执行))",
        "我先列出调整预览",
        normalized,
    )
    normalized = normalized.replace("你现在的可选范围里", "当前候选志愿里")
    normalized = normalized.replace("当前可用于规划的可选范围里", "当前候选志愿里")
    normalized = normalized.replace("可选范围里", "候选志愿里")
    normalized = normalized.replace("暂时还不可以先看调整预览", "暂时需要你先取舍或放宽条件")
    normalized = re.sub(r"[✅⏳📝⚠️❗️⭐️]+", "", normalized)
    normalized = normalized.replace("您", "你")
    if any(token in normalized for token in ("方案", "志愿", "候选")):
        plan_add_replacements = (
            ("添加预览", "加入方案预览"),
            ("添加建议", "加入方案建议"),
            ("确认要添加吗", "确认加入方案吗"),
            ("确认添加吗", "确认加入方案吗"),
            ("要添加吗", "要加入方案吗"),
            ("执行添加", "执行加入方案"),
            ("执行后会将该志愿补入方案", "执行后会将该志愿加入方案"),
        )
        for source, target in plan_add_replacements:
            normalized = normalized.replace(source, target)
    return normalized


def _plan_reply_needs_normalization(reply: str) -> bool:
    """Only guard severe user-experience failures, not natural model formatting."""
    if any(marker in reply for marker in _PLAN_STYLE_SEVERE_MARKERS):
        return True
    if "专业组" in reply and re.search(r"前\s*\d+\s*位概况", reply):
        return True
    return any(line.strip() in _PLAN_STYLE_DANGLING_EXACT_LINES for line in reply.splitlines())


def _normalize_plan_reply_style(reply: str) -> str:
    """Thin service guard for severe Plan reply wording; natural Markdown/lists are allowed."""
    if not reply.strip():
        return reply

    normalized_lines: list[str] = []
    skip_unit_position_list = False
    for raw_line in reply.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            skip_unit_position_list = False
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        if (
            "专业组" in reply
            and re.search(r"前\s*\d+\s*位概况", stripped)
        ):
            skip_unit_position_list = True
            continue
        if skip_unit_position_list and re.match(r"^\d+[.、]\s*", stripped):
            continue
        if skip_unit_position_list and (
            "—" in stripped or "-" in stripped or "专业组" in stripped or "第" in stripped
        ):
            continue
        skip_unit_position_list = False
        if stripped in _PLAN_STYLE_DANGLING_EXACT_LINES:
            continue
        line = raw_line.replace("补偿预览", "补齐建议")
        if any(marker in line for marker in _PLAN_STYLE_SEVERE_MARKERS if marker != "补偿预览"):
            sentence_parts = re.findall(r"[^。！？.!?]+[。！？.!?]?", line)
            kept_parts = [
                part
                for part in sentence_parts
                if not any(marker in part for marker in _PLAN_STYLE_SEVERE_MARKERS if marker != "补偿预览")
            ]
            line = "".join(kept_parts).strip()
        if not line.strip():
            continue
        normalized_lines.append(line.rstrip())

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()

    if not any(line.strip() for line in normalized_lines):
        return "我先给出当前判断。你可以继续看结论、调整建议，或在确认后执行具体改动。"

    return "\n".join(normalized_lines)


def _append_plan_preview_confirmation_boundary(
    reply: str,
    new_messages: list[Any] | None,
) -> str:
    """Make current-turn Plan previews explicit when the model skipped execute_plan_action."""
    if not reply.strip():
        non_actionable_result = _latest_non_actionable_plan_result(new_messages)
        if non_actionable_result:
            return _non_actionable_plan_preview_boundary(non_actionable_result)
        return reply
    confirmation_candidate = _extract_plan_confirmation_candidate(new_messages)
    if _tool_returns_successful_plan_apply(new_messages):
        return reply
    asks_confirmation = _reply_has_plan_confirmation_request(reply)
    if not confirmation_candidate:
        non_actionable_result = _latest_non_actionable_plan_result(new_messages)
        fix_proposal_preview_result = _latest_fix_proposal_preview_result(new_messages)
        readonly_explore_reply = _latest_readonly_explore_reply(new_messages)
        if asks_confirmation:
            if readonly_explore_reply:
                compact_explore = _compact_plan_reply_text(readonly_explore_reply)
                if "不会改动当前方案" not in compact_explore and "不会直接改" not in compact_explore:
                    return f"{readonly_explore_reply.rstrip()}\n\n{_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY}"
                return readonly_explore_reply
            if not non_actionable_result and not fix_proposal_preview_result and not _tool_returns_plan_mutation_context(new_messages):
                return reply
            reply = _remove_unbacked_plan_confirmation_copy(reply)
            boundary = _non_actionable_plan_preview_boundary(
                non_actionable_result
                or fix_proposal_preview_result
                or _latest_non_actionable_plan_mutation_result(new_messages)
            )
            stripped_reply = reply.strip()
            if not stripped_reply:
                return boundary
            return f"{stripped_reply}\n\n{boundary}"
        if non_actionable_result and any(marker in reply for marker in ("补偿环节", "技术问题", "无法进入可执行")):
            stripped = _remove_unbacked_plan_confirmation_copy(reply).strip()
            if not stripped or any(marker in stripped for marker in ("补偿环节", "技术问题", "无法进入可执行")):
                return _NO_EXECUTABLE_PLAN_PREVIEW_REPLY
            return f"{stripped}\n\n{_non_actionable_plan_preview_boundary(non_actionable_result)}"
        if non_actionable_result and _reply_is_internal_plan_error(reply):
            return _non_actionable_plan_preview_boundary(non_actionable_result)
        return reply
    action_family = str(confirmation_candidate.get("action_family") or "")
    if action_family not in _PENDING_PLAN_ACTION_FAMILIES:
        return reply
    unit_kind = _plan_confirmation_candidate_unit_kind(confirmation_candidate)
    if action_family in {"move_ordered_unit", "remove_ordered_unit"} and unit_kind != "志愿":
        compact_reply = _compact_plan_reply_text(reply)
        if "不是按单条志愿位置" not in compact_reply and "按专业组顺序计算" not in compact_reply:
            reply = (
                reply.rstrip()
                + "\n\n位置说明：这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；组内专业会保持连续。"
            )
    if _reply_conflicts_with_plan_confirmation_candidate(reply):
        return _build_plan_confirmation_preview_reply(confirmation_candidate)
    if asks_confirmation:
        return reply
    return reply.rstrip() + "\n\n如果你确认要这样做，我再执行；现在还不会改动方案。"


def _reply_is_internal_plan_error(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    compact = _compact_plan_reply_text(reply)
    return compact in {"会话不存在", "sessionnotfound", "chat session not found"} or bool(
        re.fullmatch(r"(?:错误|异常)[:：]?.{0,30}", compact)
    )


def _plan_confirmation_candidate_unit_kind(confirmation_candidate: dict[str, Any] | None) -> str:
    if not isinstance(confirmation_candidate, dict):
        return ""
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return ""
    try:
        data = json.loads(payload)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    unit_kind = str(facts.get("unit_kind") or facts.get("unitKind") or "").strip()
    return unit_kind if unit_kind in {"志愿", "专业组"} else ""


def _plan_confirmation_candidate_is_explicit_atomic_target(
    confirmation_candidate: dict[str, Any] | None,
) -> bool:
    if not isinstance(confirmation_candidate, dict):
        return False
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    if action_family not in {"add_units", "remove_units", "replace_units"}:
        return False
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return False
    try:
        data = json.loads(payload)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("composite_proposal") or data.get("compositeProposal"):
        return False
    if isinstance(data.get("intent_update"), dict) or isinstance(data.get("intentUpdate"), dict):
        return False
    atomic_actions = data.get("atomic_actions") if isinstance(data.get("atomic_actions"), list) else []
    for action in atomic_actions:
        if not isinstance(action, dict):
            continue
        volunteer_ids = _as_text_list(action.get("volunteer_ids") or action.get("volunteerIds"))
        if volunteer_ids:
            return True
    return False


def _pending_state_constraint_intent_type(pending_state: dict[str, Any] | None) -> str:
    if not isinstance(pending_state, dict):
        return ""
    direct = str(
        pending_state.get("constraintIntentType")
        or pending_state.get("constraint_intent_type")
        or ""
    ).strip()
    if direct:
        return direct
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        return ""
    for source in (
        execution_payload,
        execution_payload.get("selectedData"),
        execution_payload.get("intentPayload"),
    ):
        if not isinstance(source, dict):
            continue
        value = str(
            source.get("constraintIntentType")
            or source.get("constraint_intent_type")
            or ""
        ).strip()
        if value:
            return value
    return ""


def _plan_confirmation_candidate_payload(
    confirmation_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(confirmation_candidate, dict):
        return {}
    payload = confirmation_candidate.get("plan_payload")
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _plan_candidate_intent_update(
    confirmation_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(confirmation_candidate, dict):
        return {}
    direct = confirmation_candidate.get("intent_update") or confirmation_candidate.get("intentUpdate")
    if isinstance(direct, dict) and direct:
        return direct
    payload = _plan_confirmation_candidate_payload(confirmation_candidate)
    if not payload:
        return {}
    for source in (
        payload,
        payload.get("facts") if isinstance(payload.get("facts"), dict) else None,
    ):
        if not isinstance(source, dict):
            continue
        value = source.get("intent_update") or source.get("intentUpdate")
        if isinstance(value, dict) and value:
            return value
    return {}


def _plan_candidate_structured_goal_type(
    confirmation_candidate: dict[str, Any] | None,
) -> str:
    payload = _plan_confirmation_candidate_payload(confirmation_candidate)
    if not payload:
        return ""
    composite = payload.get("composite_proposal") or payload.get("compositeProposal")
    if not isinstance(composite, dict):
        return ""
    goal = composite.get("goal")
    if not isinstance(goal, dict):
        return ""
    return str(goal.get("goal_type") or goal.get("goalType") or "").strip()


def _merged_selected_intent_payload(intent_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    merged = _merge_selected_intent_payload(intent_payload)
    return merged if merged else intent_payload


def _plain_plan_candidate_conflicts_with_active_only_keep_intent(
    pending_state: dict[str, Any] | None,
    confirmation_candidate: dict[str, Any] | None,
) -> bool:
    """Prevent an active only-keep intent from being replaced by a derived removal list.

    The unified path for only-keep goals is Intent/UserGoal -> Java FixProposal.
    A plain execute_plan_action/remove_units card that only carries generated
    negative complements is a model-side expansion, not a safe replacement for
    the active pending only-keep state.
    """
    if not isinstance(pending_state, dict) or not isinstance(confirmation_candidate, dict):
        return False
    if str(pending_state.get("status") or "").strip() != "active":
        return False
    if str(pending_state.get("kind") or "").strip() != "intent_change":
        return False
    if _pending_state_constraint_intent_type(pending_state) != "only_keep":
        return False
    if _plan_candidate_structured_goal_type(confirmation_candidate) == "only_keep_scope":
        return False

    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    if action_family not in {"remove_units", "replace_units", "add_units", "generate_plan"}:
        return False
    intent_update = _plan_candidate_intent_update(confirmation_candidate)
    if not intent_update:
        return False
    candidate_constraint_type = str(
        intent_update.get("constraintIntentType")
        or intent_update.get("constraint_intent_type")
        or ""
    ).strip()
    if candidate_constraint_type == "only_keep":
        return False
    merged_intent = _merged_selected_intent_payload(intent_update)
    return _intent_payload_has_negative_value(merged_intent) and not _intent_payload_has_positive_value(merged_intent)


def _compact_plan_reply_text(reply: str) -> str:
    return re.sub(r'[\s"“”‘’`\'「」『』【】\[\]（）()<>《》:：,，。.!！？?、]+', "", str(reply or ""))


def _reply_has_plan_confirmation_request(reply: str) -> bool:
    return proposal_compiler.runtime_reply_has_plan_confirmation_request(reply)


def _reply_conflicts_with_plan_confirmation_candidate(reply: str) -> bool:
    compact = _compact_plan_reply_text(reply)
    return any(
        marker in compact
        for marker in (
            "无法进入可执行",
            "没有上一轮待确认",
            "还没有拿到可执行",
            "系统在补偿环节遇到",
            "技术问题",
            "现在还不会改动方案",
        )
    )


def _build_plan_confirmation_preview_reply(confirmation_candidate: dict[str, Any]) -> str:
    summary = str(confirmation_candidate.get("summary") or "").strip()
    summary = summary.replace("补偿", "补齐")
    title = "调整预览已生成。"
    boundary = "如果你确认要这样做，我再执行；现在还不会改动方案。"
    body = f"\n\n{summary}" if summary else ""
    return f"{title}{body}\n\n{boundary}"


def _plan_summary_is_low_information(summary: str) -> bool:
    compact = _compact_plan_reply_text(summary)
    if not compact:
        return True
    return any(
        marker in compact
        for marker in (
            "这轮我先把影响范围和可选方向说明清楚",
            "不会直接改动当前方案",
            "需要你确认后才会执行",
        )
    ) and not any(
        marker in compact
        for marker in (
            "补入",
            "移出",
            "替换",
            "移动",
            "排序",
            "生成",
            "补齐",
            "当前位置",
            "目标位置",
            "源志愿",
            "源专业组",
            "志愿：",
        )
    )


def _fallback_plan_confirmation_candidate_summary(confirmation_candidate: dict[str, Any]) -> str:
    action_family = str(confirmation_candidate.get("action_family") or "").strip()
    user_goal = str(confirmation_candidate.get("user_goal") or "").strip()
    action_text = {
        "generate_plan": "根据当前候选和当前报考信息生成或补齐方案。",
        "add_units": "把符合条件的候选加入当前方案。",
        "remove_units": "从当前方案里移出命中的志愿。",
        "replace_units": "用更合适的候选替换当前方案里的命中项。",
        "sort_ordered_plan": "按指定规则重新排列当前方案。",
        "regenerate_order": "重新生成当前排序方案。",
        "move_unit": "移动当前方案里的指定志愿。",
        "move_ordered_unit": "移动当前排序里的指定位置。",
        "remove_ordered_unit": "移出当前排序里的指定位置。",
    }.get(action_family, "按这次要求生成一版调整预览。")
    if user_goal:
        return f"{action_text}\n\n本次要求：{user_goal}"
    return action_text


def _plan_confirmation_candidate_summary_for_user(confirmation_candidate: dict[str, Any]) -> str:
    summary = str(confirmation_candidate.get("summary") or confirmation_candidate.get("preview_summary") or "").strip()
    summary = _normalize_user_facing_terms(summary.replace("补偿", "补齐"))
    if _plan_summary_is_low_information(summary):
        return _fallback_plan_confirmation_candidate_summary(confirmation_candidate)
    return summary


def _plan_confirmation_card_primary_reply(confirmation_candidate: dict[str, Any]) -> str:
    summary = _plan_confirmation_candidate_summary_for_user(confirmation_candidate)
    if summary:
        summary = re.sub(r"(?:需要你)?确认后才会执行[。；;]?", "", summary).strip("；;。 \n")
        reply = f"已列出调整预览：{summary}。"
    else:
        reply = "已列出调整预览。"
    return _sanitize_reply_for_user(f"{reply}\n\n确认前不会改动当前方案。")


def _remove_current_turn_mutating_plan_preview(messages: list[Any] | None) -> None:
    """Rewrite mutating Plan preview returns so they cannot become stale pending state.

    This is a side-effect safety boundary for explicit read-only prompts. It does
    not route the request; it only prevents a model/tool detour from leaving a
    confirmable add/remove/move/sort preview after the user said to only inspect.
    """
    for part in _iter_tool_return_parts(messages):
        if part.tool_name not in {"plan_next_action", "execute_plan_action"}:
            continue
        data = _parse_tool_return_json(part.content)
        if not data:
            continue
        action_family = str(data.get("action_family") or "").strip()
        effective_family = action_family
        result_kind = str(data.get("result_kind") or "").strip()
        if effective_family not in _PENDING_PLAN_ACTION_FAMILIES:
            continue
        if result_kind != "preview_only" and data.get("stage") != "preview":
            continue
        data["stage"] = "apply"
        data["action_family"] = "query_candidates" if effective_family == "add_units" else "query_ordered"
        data["result_kind"] = "candidate_snapshot" if effective_family == "add_units" else "ordered_snapshot"
        data["applied"] = True
        data["requires_confirmation"] = False
        data["should_rerun_review"] = False
        data["should_refresh_workspace"] = False
        data["workspace_refresh_targets"] = []
        data["reply_focus"] = [str(data["result_kind"])]
        data["summary"] = _READONLY_MUTATION_GUARD_REPLY
        data.pop("preview_summary", None)
        part.content = json.dumps(data, ensure_ascii=False)


def _remove_unbacked_plan_confirmation_copy(reply: str) -> str:
    return proposal_compiler.strip_unbacked_plan_confirmation_copy(reply)


def _guard_unbacked_plan_confirmation_reply(reply: str) -> str:
    """Replace unsupported Plan confirmation copy with an explicit no-card boundary."""
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="plan_confirmation",
    )
    if not source.matched:
        return reply
    stripped = source.stripped_reply.strip()
    if not stripped or _reply_has_plan_confirmation_request(stripped):
        return _UNBACKED_PLAN_CONFIRMATION_REPLY
    return f"{stripped}\n\n{_UNBACKED_PLAN_CONFIRMATION_REPLY}"


def _guard_plan_preview_reply_without_card(reply: str) -> str:
    confirmation_source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="plan_confirmation",
    )
    if confirmation_source.matched:
        return _guard_unbacked_plan_confirmation_reply(reply)
    preview_source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="plan_preview_without_card",
    )
    if not preview_source.matched:
        return _guard_unbacked_plan_confirmation_reply(reply)
    stripped = preview_source.stripped_reply.strip()
    if not stripped or stripped == reply.strip() or _reply_has_plan_confirmation_request(stripped):
        return _UNBACKED_PLAN_CONFIRMATION_REPLY
    return _sanitize_reply_for_user(f"{stripped}\n\n{_UNBACKED_PLAN_CONFIRMATION_REPLY}")


def _normalize_unbacked_no_tool_action_boundary(reply: str) -> str:
    """Use a neutral no-change boundary when no executable action was created.

    `_UNBACKED_PLAN_CONFIRMATION_REPLY` is appropriate while the service is
    still trying to route a missing Plan preview. If all structured boundary paths end
    with no tools, no pending card, and no preview, surfacing that text reads as
    an execution failure even when the user only set a discussion boundary.
    """
    source = proposal_compiler.compile_runtime_reply_guard_source(
        reply=reply,
        guard_context="no_tool_action_boundary",
    )
    if not source.matched:
        return reply
    return _NO_TOOL_NO_ACTION_BOUNDARY_REPLY


def _clean_review_fallback_text(value: Any) -> str:
    text = _normalize_user_facing_terms(_normalize_fix_proposal_user_text(str(value or "").strip()))
    text = text.replace("压根找不到", "暂时没找到")
    text = text.replace("暂时无法直接处理", "暂时不能直接处理")
    text = text.replace("暂时无法自动处理", "暂时不能直接处理")
    text = text.replace("暂时不能直接处理", "需要你先取舍或放宽条件")
    text = text.replace("建议你先查看具体影响，或调整筛选范围后再试", "需要你先看影响或放宽条件")
    text = text.replace("当前候选里", "当前候选志愿里")
    text = text.replace("当前可用于规划的候选池里", "当前候选志愿里")
    text = text.replace("当前可用于规划的可选范围里", "当前候选志愿里")
    text = re.sub(r"@(\d+)", r"第\1位", text)
    return text.strip("。；;，, ：:").strip()


def _append_unique_review_part(parts: list[str], value: str, *, limit: int = 2) -> None:
    text = _clean_review_fallback_text(value)
    if not text:
        return
    text = text.replace("补入兜底专业", "补兜底专业")
    compact = _compact_plan_reply_text(text)
    for existing in parts:
        existing_compact = _compact_plan_reply_text(existing)
        if compact == existing_compact or compact in existing_compact or existing_compact in compact:
            return
    if len(parts) < limit:
        parts.append(text)


def _review_fallback_problem_text(values: Any, *, limit: int = 3) -> str:
    if not isinstance(values, list):
        return ""
    items: list[str] = []
    for value in values:
        text = _clean_review_fallback_text(value)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return "；".join(items)


def _review_fallback_examples_text(values: Any, *, limit: int = 2) -> str:
    if not isinstance(values, list):
        return ""
    def shorten_example(value: str) -> str:
        text = _clean_review_fallback_text(value)
        if not text:
            return ""
        text = re.sub(r"\([^()]{18,}\)", "", text)
        text = re.sub(r"（[^（）]{18,}）", "", text)
        def keep_only_tier_label(match: re.Match[str]) -> str:
            content = (match.group(1) or match.group(2) or "").strip()
            return f"({content})" if content in {"冲", "稳", "保"} else ""

        text = re.sub(r"\(([^()]{1,20})\)|（([^（）]{1,20})）", keep_only_tier_label, text)
        text = re.sub(r"\s+", "", text)
        return text[:72].rstrip("；，,。")

    lines: list[str] = []
    seen_summaries: set[str] = set()
    seen_example_signatures: set[tuple[str, ...]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        summary = _clean_review_fallback_text(item.get("summary"))
        compact_summary = _compact_plan_reply_text(summary)
        if compact_summary and compact_summary in seen_summaries:
            continue
        if compact_summary:
            seen_summaries.add(compact_summary)
        count_text = _clean_review_fallback_text(item.get("count_text"))
        examples: list[str] = []
        for example in (item.get("items") or [])[:2]:
            text = shorten_example(example)
            if text:
                examples.append(text)
        example_signature = tuple(_compact_plan_reply_text(example) for example in examples)
        if example_signature and example_signature in seen_example_signatures:
            continue
        if example_signature:
            seen_example_signatures.add(example_signature)
        parts = [part for part in (summary, count_text) if part]
        if examples:
            parts.append("例如：" + "；".join(examples))
        if parts:
            lines.append("，".join(parts))
        if len(lines) >= limit:
            break
    return "；".join(lines)


def _review_fallback_target_issue_labels(facts: dict[str, Any]) -> list[str]:
    labels = {
        "high_tuition": "高收费",
        "cooperative_program": "中外合作",
        "admission_limit": "限报条件",
        "special_enrollment": "特殊招生",
        "probability_inversion": "录取率倒挂",
        "probability_gap": "录取率梯度断层",
        "major_group_safety_intent_alignment": "非意向托底专业",
        "group_inner_safety_guard": "组内安全垫",
        "safety_guard": "保底安全垫",
        "edge_score": "边缘分风险",
        "count_validation": "志愿数量",
    }
    result: list[str] = []
    issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    for code in issue_codes:
        label = labels.get(str(code or "").strip())
        if label and label not in result:
            result.append(label)
    return result


def _build_target_issue_review_fallback_lines(facts: dict[str, Any]) -> list[str]:
    explicit_target_issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    if not explicit_target_issue_codes:
        return []

    issue_labels = _review_fallback_target_issue_labels(facts)
    examples = _review_fallback_examples_text(facts.get("issue_hit_plan_examples"), limit=3)
    problems = _review_fallback_problem_text(facts.get("main_problems"), limit=3)
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts, limit=2)

    if not issue_labels and not examples and not problems:
        return []

    label_text = "、".join(issue_labels) if issue_labels else "这类问题"
    lines = [f"我按你关注的{label_text}看了一下：", ""]
    if examples:
        lines.append(f"- 当前方案里有命中项：{examples}。")
    elif problems:
        lines.append(f"- 当前看到的问题：{problems}。")
    else:
        lines.append("- 当前审查里暂时没有看到明确命中的志愿。")

    if ready_lines:
        lines.extend(["", "可以先看调整预览的："])
        for item in ready_lines[:2]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "需要先取舍的："])
        for item in needs_decision_lines[:2]:
            lines.append(f"- {item}。")

    lines.extend([
        "",
        "如果要正式调整，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _review_fallback_fix_proposal_lines(fix_facts: dict[str, Any], *, limit: int = 3) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    needs_decision: list[str] = []
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        title = _clean_fix_proposal_title(proposal.get("title")) or "处理方向"
        status = str(proposal.get("status") or "").strip()
        strategy = _FIX_PROPOSAL_STRATEGY_TEXT.get(str(proposal.get("strategy") or "").strip(), "")
        summary = _clean_review_fallback_text(proposal.get("summary"))
        reason = _clean_review_fallback_text(proposal.get("blocking_reason") or proposal.get("blockingReason"))
        shortages = []
        for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
            if not isinstance(shortage, dict):
                continue
            message = _clean_review_fallback_text(shortage.get("message"))
            if message and message not in shortages:
                shortages.append(message)
        detail_parts: list[str] = []
        if status == "ready":
            _append_unique_review_part(detail_parts, strategy)
            action_summaries = [
                _clean_review_fallback_text(item)
                for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])[:1]
                if _clean_review_fallback_text(item)
            ]
            for action_summary in action_summaries:
                _append_unique_review_part(detail_parts, action_summary)
            if not detail_parts:
                _append_unique_review_part(detail_parts, summary)
        else:
            for part in (reason, *shortages[:1], summary):
                _append_unique_review_part(detail_parts, part)
                if detail_parts:
                    break
        line = title
        if detail_parts:
            line += "：" + "；".join(detail_parts[:2])
        if status == "ready":
            if line not in ready:
                ready.append(line)
        elif line not in needs_decision:
            needs_decision.append(line)
        if len(ready) >= limit and len(needs_decision) >= limit:
            break
    return ready[:limit], needs_decision[:limit]


def _append_review_fix_proposal_sections(
    lines: list[str],
    ready_lines: list[str],
    needs_decision_lines: list[str],
) -> None:
    if ready_lines:
        lines.extend(["", "可以先看调整预览的："])
        for item in ready_lines[:3]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "需要你先取舍或放宽条件的："])
        for item in needs_decision_lines[:3]:
            lines.append(f"- {item}。")


def _review_fallback_proposal_reason(proposal: dict[str, Any]) -> str:
    reason = _clean_review_fallback_text(proposal.get("blocking_reason") or proposal.get("blockingReason"))
    shortages: list[str] = []
    for shortage in proposal.get("candidate_shortages") or proposal.get("candidateShortages") or []:
        if not isinstance(shortage, dict):
            continue
        message = _clean_review_fallback_text(shortage.get("message"))
        if message and message not in shortages:
            shortages.append(message)
    summary = _clean_review_fallback_text(proposal.get("summary"))
    for part in (reason, *shortages[:1], summary):
        if part:
            return part
    return "需要你先决定取舍范围，暂时不适合直接改方案"


def _review_fallback_proposal_next_step(proposal: dict[str, Any]) -> str:
    title = _clean_review_fallback_text(proposal.get("title"))
    strategy = str(proposal.get("strategy") or "").strip()
    combined = f"{title} {_clean_review_fallback_text(proposal.get('summary'))}"
    if "高收费" in combined:
        return "先确认高收费项目是全部不要、部分保留，还是预算可以接受"
    if "中外合作" in combined:
        return "先确认中外合作项目是否接受；如果不接受，我再列替换预览"
    if "非意向" in combined or "兜底" in combined:
        return "先确认更看重学校层次还是专业匹配；如果排斥这类兜底专业，再看是否整组替换"
    if strategy in {"rebalance_tier_ratio", "fill_probability_gap", "add_safety_items"}:
        return "可以先放宽地域、专业或院校层次范围，再重新审查可补机会"
    if "数量" in combined or "超" in combined:
        return "先手动精简 1 个最不想去的志愿，再重新审查"
    return "先告诉我你能接受哪些取舍，我再列调整预览"


def _build_review_unavailable_guidance_fallback_lines(facts: dict[str, Any]) -> list[str]:
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    blocked: list[dict[str, Any]] = [
        proposal
        for proposal in proposals
        if isinstance(proposal, dict)
        and str(proposal.get("status") or "").strip() in {"blocked", "preview_only"}
    ]
    if not blocked:
        return _build_review_result_fallback_lines(facts)

    lines = ["我看了一下，不能直接处理的点主要卡在“取舍范围还没定”或“可替换机会不够”。", ""]
    for index, proposal in enumerate(blocked[:4], start=1):
        title = _clean_fix_proposal_title(proposal.get("title")) or "这条提醒"
        reason = _review_fallback_proposal_reason(proposal)
        next_step = _review_fallback_proposal_next_step(proposal)
        lines.append(f"{index}. **{title}**")
        lines.append(f"- 为什么现在不直接改：{reason}。")
        lines.append(f"- 你可以怎么调：{next_step}。")
        lines.append("")

    lines.append("你可以先选最想处理的一类，我会先列出调整预览，确认前不会改动当前方案。")
    return lines


def _build_review_result_fallback_lines(facts: dict[str, Any]) -> list[str]:
    targeted_lines = _build_target_issue_review_fallback_lines(facts)
    if targeted_lines:
        return targeted_lines

    risk_count = _as_int(facts.get("risk_count"))
    warn_count = _as_int(facts.get("warn_count"))
    plan_total = _as_int(facts.get("plan_total"))
    target_total = _as_int(facts.get("target_total"))
    tier_text = _format_status_tier_counts(facts.get("tier_counts"))
    lines = ["我已经完成当前方案审查，先说结论：", ""]
    status_parts = [f"风险 {risk_count} 项", f"提醒 {warn_count} 项"]
    if plan_total > 0:
        target = target_total or plan_total
        status_parts.insert(0, f"方案 {plan_total}/{target} 个志愿")
    if tier_text:
        status_parts.append(f"冲稳保 {tier_text}")
    lines.append("- " + "，".join(status_parts) + "。")

    problems = _review_fallback_problem_text(facts.get("main_problems"))
    if problems:
        lines.append(f"- 主要需要留意：{problems}。")

    examples = _review_fallback_examples_text(facts.get("issue_hit_plan_examples"))
    if examples:
        lines.append(f"- 典型例子：{examples}。")

    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}
    conflict = _clean_review_fallback_text(str(relation.get("conflict_examples") or "").removeprefix("需关注冲突："))
    if conflict:
        lines.append(f"- 和已确认想法冲突的例子：{conflict}。")

    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    _append_review_fix_proposal_sections(lines, ready_lines, needs_decision_lines)

    lines.extend([
        "",
        "如果你想继续处理，可以先选一类让我展开影响；需要改方案时，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _build_adjustment_analysis_fallback_lines(facts: dict[str, Any]) -> list[str]:
    requested_focus = {
        str(item or "").strip()
        for item in (facts.get("requested_reply_focus") or [])
        if str(item or "").strip()
    }
    if "shortage_boundary" in requested_focus:
        return _build_shortage_boundary_fallback_lines(facts)

    lines = ["我看了当前方案的优化空间和可处理方向，先说结论：", ""]
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    examples = _review_fallback_examples_text(facts.get("review_issue_hit_plan_examples"))
    problems = _review_fallback_problem_text(facts.get("main_problems"), limit=2)

    actionable_counts = facts.get("actionable_suggestion_counts") if isinstance(facts.get("actionable_suggestion_counts"), dict) else {}
    has_actionable = any(
        _as_int(actionable_counts.get(key)) > 0
        for key in ("add", "reorder", "replace", "remove")
    ) or bool(ready_lines)

    if has_actionable:
        if ready_lines:
            _append_review_fix_proposal_sections(lines, ready_lines, [])
        else:
            lines.append("- 有可继续细看的调整方向，但需要先生成预览；确认前不会改动当前方案。")
    else:
        lines.append("- 这轮先拿到的是分析结论，还没有形成可以直接执行的完整调整清单。")

    if problems:
        lines.append(f"- 主要卡点：{problems}。")
    if examples:
        lines.append(f"- 可以优先关注的例子：{examples}。")
    if needs_decision_lines:
        _append_review_fix_proposal_sections(lines, [], needs_decision_lines)

    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    total = _as_int(supply.get("total") or supply.get("candidate_total") or supply.get("candidateTotal"))
    tier_counts = supply.get("tier_counts") or supply.get("tierCounts")
    tier_text = _format_status_tier_counts(tier_counts)
    if total > 0 or tier_text:
        supply_parts = []
        if total > 0:
            supply_parts.append(f"候选志愿约 {total} 个")
        if tier_text:
            supply_parts.append(f"冲稳保供给 {tier_text}")
        lines.append(f"- 候选情况：{'，'.join(supply_parts)}。")

    lines.extend([
        "",
        "如果你想继续处理，可以先明确最想动的一类；我会先列出调整预览，确认前不会改动当前方案。",
    ])
    return lines


def _build_shortage_boundary_fallback_lines(facts: dict[str, Any]) -> list[str]:
    lines = ["我看了当前方案和可补机会，先说结论：", ""]
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    tier_counts = supply.get("tier_counts") or supply.get("tierCounts") or facts.get("tier_counts")
    tier_text = _format_status_tier_counts(tier_counts)
    missing_tiers = [
        str(item or "").strip()
        for item in (
            supply.get("missing_supply_tiers")
            or supply.get("missingSupplyTiers")
            or []
        )
        if str(item or "").strip()
    ]
    total = _as_int(supply.get("total") or supply.get("candidate_total") or supply.get("candidateTotal"))

    if tier_text:
        lines.append(f"- 当前可选范围里的冲稳保供给大致是：{tier_text}。")
    if total > 0:
        lines.append(f"- 当前可用于规划的候选志愿约 {total} 个。")
    if missing_tiers:
        lines.append(f"- 主要缺口在 {'、'.join(missing_tiers)} 区间，说明不是简单把比例调一下就能补上。")

    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _shortage_boundary_fix_proposal_lines(fix_facts)
    if ready_lines:
        lines.extend(["", "可以先看预览的方向："])
        for item in ready_lines[:2]:
            lines.append(f"- {item}。")
    if needs_decision_lines:
        lines.extend(["", "暂时补不上的原因："])
        for item in needs_decision_lines[:2]:
            lines.append(f"- {item}。")

    if not tier_text and total <= 0 and not missing_tiers and not ready_lines and not needs_decision_lines:
        problems = _review_fallback_problem_text(facts.get("main_problems"), limit=2)
        if problems:
            lines.append(f"- 当前主要卡在：{problems}。")
        else:
            lines.append("- 这轮先拿到的是能不能补齐的边界判断，还没有形成可以直接执行的完整调整清单。")

    lines.extend([
        "",
        "如果你想继续处理，可以先放宽地域、专业或院校层次范围后再让我重新审查；需要改方案时，我会先列出预览，确认前不会改动当前方案。",
    ])
    return lines


def _shortage_boundary_fix_proposal_lines(fix_facts: dict[str, Any]) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    needs_decision: list[str] = []
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        strategy = str(proposal.get("strategy") or "").strip()
        strategy_label = _FIX_PROPOSAL_STRATEGY_TEXT.get(strategy, "")
        if strategy == "fill_probability_gap":
            strategy_label = "补一段更合适的录取概率区间"
        if not strategy_label:
            strategy_label = "这个方向"
        status = str(proposal.get("status") or "").strip()
        detail = ""
        if status == "ready":
            action_summaries = [
                _clean_review_fallback_text(item)
                for item in (proposal.get("action_summaries") or proposal.get("actionSummaries") or [])[:1]
                if _clean_review_fallback_text(item)
            ]
            detail = action_summaries[0] if action_summaries else _clean_review_fallback_text(proposal.get("summary"))
        else:
            detail = _review_fallback_proposal_reason(proposal)
        line = strategy_label
        if detail and _compact_plan_reply_text(detail) != _compact_plan_reply_text(strategy_label):
            line += f"：{detail}"
        target = ready if status == "ready" else needs_decision
        if line not in target:
            target.append(line)
    return ready[:2], needs_decision[:2]


def _build_fix_proposal_preview_fallback_lines(
    facts: dict[str, Any],
    *,
    summary: str = "",
) -> list[str]:
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    ready_lines, needs_decision_lines = _review_fallback_fix_proposal_lines(fix_facts)
    supply = facts.get("candidate_supply") if isinstance(facts.get("candidate_supply"), dict) else {}
    missing_tiers = [
        str(item or "").strip()
        for item in (
            supply.get("missing_supply_tiers")
            or supply.get("missingSupplyTiers")
            or []
        )
        if str(item or "").strip()
    ]

    lines: list[str] = []
    if ready_lines:
        lines.extend(["我看了当前方案，下面这些方向可以先出调整预览："])
        for item in ready_lines[:3]:
            lines.append(f"- {item}。")
    else:
        lines.extend(["我看了能不能直接补齐或调整，当前还没有足够合适的可执行预览。"])

    if missing_tiers:
        lines.append(f"- 当前缺口主要在：{'、'.join(dict.fromkeys(missing_tiers))}。")
    if needs_decision_lines:
        lines.extend(["", "暂时不能直接处理的原因："])
        for item in needs_decision_lines[:4]:
            lines.append(f"- {item}。")
    elif summary:
        lines.extend(["", _clean_review_fallback_text(summary)])

    lines.extend([
        "",
        "下一步可以先放宽地域、专业、院校层次或预算等条件，再重新审查可补机会；如果你愿意明确取舍，我再按新的范围列调整预览。确认前不会改动当前方案。",
    ])
    return lines


def _fix_proposal_matches_any_target_scope(
    proposal: dict[str, Any],
    target_strategies: list[str],
    target_issue_codes: list[str],
) -> bool:
    return (
        proposal_compiler.fix_proposal_matches_target_scope(proposal, target_strategies, [])
        or proposal_compiler.fix_proposal_matches_target_scope(proposal, [], target_issue_codes)
    )


def _targeted_fix_proposal_unavailable_reply(
    result: dict[str, Any],
    *,
    target_strategies: list[str] | None = None,
    target_issue_codes: list[str] | None = None,
) -> str:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    normalized_strategies = proposal_compiler.normalize_fix_proposal_target_strategies(
        target_strategies
        or result.get("target_strategies")
        or result.get("targetStrategies")
        or []
    )
    normalized_issue_codes = proposal_compiler.normalize_fix_proposal_target_issue_codes(
        target_issue_codes
        or result.get("target_issue_codes")
        or result.get("targetIssueCodes")
        or []
    )
    matched = [
        proposal
        for proposal in proposals
        if isinstance(proposal, dict)
        and _fix_proposal_matches_any_target_scope(
            proposal,
            normalized_strategies,
            normalized_issue_codes,
        )
    ]
    if not matched:
        return ""

    ready = [
        proposal
        for proposal in matched
        if str(proposal.get("status") or "").strip() == "ready"
    ]
    if ready:
        return ""

    proposal = matched[0]
    title = _clean_fix_proposal_title(proposal.get("title")) or "你想处理的这类问题"
    strategy = _FIX_PROPOSAL_STRATEGY_TEXT.get(str(proposal.get("strategy") or "").strip(), "")
    reason = _review_fallback_proposal_reason(proposal)
    next_step = _review_fallback_proposal_next_step(proposal)
    label = strategy or title
    lines = [
        f"我看了你想处理的“{label}”，这轮还没有足够合适的可执行预览，所以不会改动当前方案。",
        "",
        f"- 当前看到的问题：{title}。",
        f"- 主要原因：{reason}。",
        f"- 可以怎么推进：{next_step}。",
        "",
        "如果你愿意放宽范围或接受对应取舍，我再按新的范围重新列调整预览；确认前不会改动当前方案。",
    ]
    return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))


def _review_reply_needs_structured_fallback(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "review_plan":
        return False
    if str(result.get("result_kind") or "").strip() != "review_result":
        return False
    if any(marker in reply for marker in _REVIEW_REPLY_QUALITY_MARKERS):
        return True
    compact = _compact_plan_reply_text(reply)
    if compact.count("当前候选志愿里") >= 3 or compact.count("建议你先") >= 4:
        return True
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    explicit_target_issue_codes = facts.get("target_issue_codes") or facts.get("targetIssueCodes") or []
    if explicit_target_issue_codes:
        return False
    risk_count = _as_int(facts.get("risk_count"))
    warn_count = _as_int(facts.get("warn_count"))
    main_problems = [
        _clean_review_fallback_text(item)
        for item in (facts.get("main_problems") or [])
        if _clean_review_fallback_text(item)
    ]
    if risk_count + warn_count > 1:
        has_review_count = bool(re.search(r"风险\s*\d+\s*项", reply) and re.search(r"提醒\s*\d+\s*项", reply))
        mentioned_problem_count = 0
        for problem in main_problems[:4]:
            problem_compact = _compact_plan_reply_text(problem)
            if problem_compact and problem_compact in compact:
                mentioned_problem_count += 1
        if not has_review_count and main_problems and mentioned_problem_count < min(2, len(main_problems)):
            return True
    return False


def _review_reply_overclaims_admission_safety(reply: str, result: dict[str, Any] | None) -> bool:
    """审查/调整分析结果不能被表述成录取安全承诺。"""
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("result_kind") or "").strip() not in {"review_result", "adjustment_analysis"}:
        return False
    compact = _compact_plan_reply_text(reply)
    if not compact:
        return False
    if re.search(r"(?:不能|无法|不|并不|不是)(?:保证|代表|说明|等于|意味着|说)?不会滑档", compact):
        return False
    absolute_safety = (
        re.search(r"(不会|不可能|避免|杜绝)(?:出现)?滑档", compact) is not None
        or re.search(r"不会(?:导致|造成|引发|有)?滑档", compact) is not None
        or re.search(r"没有(?:会)?导致滑档", compact) is not None
        or re.search(r"(保证|确保|一定|肯定)(?:不会)?(?:录取|不滑档|稳录|安全)", compact) is not None
        or "不会退档" in compact
        or "没有滑档风险" in compact
        or "零滑档风险" in compact
        or "整体结构是安全" in compact
        or "方案结构是安全" in compact
        or "整体结构安全" in compact
        or "方案结构安全" in compact
    )
    if not absolute_safety:
        return False
    return True


def _review_reply_needs_boundary(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "review_plan":
        return False
    if str(result.get("result_kind") or "").strip() != "review_result":
        return False
    compact = _compact_plan_reply_text(reply)
    return bool(compact) and "审查" not in compact


def _adjustment_reply_needs_structured_fallback(reply: str, result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict) or not isinstance(reply, str):
        return False
    if str(result.get("action_family") or "").strip() != "analyze_adjustment":
        return False
    if str(result.get("result_kind") or "").strip() != "adjustment_analysis":
        return False
    markers = (
        "补充建议 0 条",
        "调序建议 0 条",
        "替换建议 0 条",
        "移除建议 0 条",
        "候选供给：",
        "下面列 2 条代表例子",
        "fix_proposals",
    )
    if any(marker in reply for marker in markers):
        return True
    if re.search(r"@\d+", reply):
        return True
    compact = _compact_plan_reply_text(reply)
    return len(compact) > 900 and "调整分析已完成" in reply


def _review_prompt_prefers_unavailable_guidance(user_prompt: str | None) -> bool:
    compact = _compact_plan_reply_text(str(user_prompt or ""))
    if not compact:
        return False
    wants_reason = any(marker in compact for marker in ("为什么", "原因", "处理不了", "不能处理", "没法处理", "怎么处理", "怎么调", "怎么改"))
    repair_context = any(marker in compact for marker in ("提醒", "审查", "风险", "处理", "调整", "修复"))
    return wants_reason and repair_context


def _prompt_requests_plan_constraint_adjustment(user_prompt: str | None) -> bool:
    compact = _compact_plan_reply_text(str(user_prompt or ""))
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "别放",
            "不要放",
            "不放",
            "避开",
            "排除",
            "去掉",
            "拿掉",
            "换掉",
            "控制在",
            "限制在",
            "不超过",
            "低于",
            "以内",
        )
    )


def _result_prefers_unavailable_guidance(result: dict[str, Any], *, user_prompt: str | None = None) -> bool:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    requested_focus = {
        str(item or "").strip()
        for item in (facts.get("requested_reply_focus") or result.get("requested_reply_focus") or [])
        if str(item or "").strip()
    }
    if "unavailable_guidance" in requested_focus:
        return True
    return _review_prompt_prefers_unavailable_guidance(user_prompt)


def _result_has_unavailable_fix_proposals(result: dict[str, Any]) -> bool:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    fix_facts = facts.get("fix_proposals") if isinstance(facts.get("fix_proposals"), dict) else {}
    if _as_int(fix_facts.get("blocked_count")) + _as_int(fix_facts.get("preview_only_count")) > 0:
        return True
    proposals = fix_facts.get("proposals") if isinstance(fix_facts.get("proposals"), list) else []
    return any(
        isinstance(proposal, dict)
        and str(proposal.get("status") or "").strip() in {"blocked", "preview_only"}
        for proposal in proposals
    )


def _result_needs_unavailable_guidance_fallback(result: dict[str, Any], *, user_prompt: str | None = None) -> bool:
    if str(result.get("result_kind") or "").strip() not in {"review_result", "adjustment_analysis"}:
        return False
    return _result_has_unavailable_fix_proposals(result) and _result_prefers_unavailable_guidance(
        result,
        user_prompt=user_prompt,
    )


def _build_plan_timeout_fallback_reply(result: dict[str, Any], *, user_prompt: str | None = None) -> str | None:
    result_kind = str(result.get("result_kind") or "").strip()
    if str(result.get("action_family") or "").strip() == "review_plan" and result_kind == "error":
        return _non_actionable_plan_preview_boundary(result)
    if result_kind not in {
        "review_result",
        "adjustment_analysis",
        "fix_proposal_preview",
        "status_overview",
        "generation_result",
        "ordered_snapshot",
        "candidate_snapshot",
        "mutation_result",
        "no_change",
    }:
        return None

    summary = str(
        result.get("summary")
        or result.get("state_summary")
        or result.get("review_summary")
        or ""
    ).strip()
    if not summary:
        return None

    lead_map = {
        "review_result": "我已经帮你检查了方案，主要情况如下：",
        "adjustment_analysis": "调整分析已完成，结果如下：",
        "fix_proposal_preview": "我已经整理好当前方案的处理预览：",
        "status_overview": "方案情况如下：",
        "generation_result": "方案已经生成好了：",
        "ordered_snapshot": "你的方案情况如下：",
        "candidate_snapshot": "候选机会查询结果：",
        "mutation_result": "方案调整已完成：",
    }
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}
    coverage = str(relation.get("coverage") or "").strip()
    aligned_examples = str(relation.get("aligned_examples") or "").strip()
    conflict_examples = str(relation.get("conflict_examples") or "").strip()
    next_step_hints = result.get("next_step_hints") if isinstance(result.get("next_step_hints"), list) else []
    plan_query_lines = _build_plan_query_fallback_lines(result, summary=summary)
    if plan_query_lines is not None:
        return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(plan_query_lines)))

    rendered_status_overview = result_kind == "status_overview" and bool(facts)
    rendered_review_result = result_kind == "review_result" and bool(facts)
    if rendered_status_overview:
        lines = _build_status_overview_fallback_lines(facts)
    elif rendered_review_result:
        if _review_prompt_prefers_unavailable_guidance(user_prompt):
            lines = _build_review_unavailable_guidance_fallback_lines(facts)
        else:
            lines = _build_review_result_fallback_lines(facts)
    elif result_kind == "adjustment_analysis" and bool(facts):
        if _result_needs_unavailable_guidance_fallback(result, user_prompt=user_prompt):
            lines = _build_review_unavailable_guidance_fallback_lines(facts)
        else:
            lines = _build_adjustment_analysis_fallback_lines(facts)
    elif result_kind == "fix_proposal_preview" and bool(facts):
        lines = _build_fix_proposal_preview_fallback_lines(facts, summary=summary)
    else:
        lines = [lead_map.get(result_kind, "这轮方案分析已经执行完了，我先把核心结果直接给你："), "", summary]
    if coverage and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {coverage}")
    if aligned_examples and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {aligned_examples}")
    if conflict_examples and not rendered_status_overview and not rendered_review_result:
        lines.append(f"- {conflict_examples}")
    if next_step_hints:
        first_hint = str(next_step_hints[0] or "").strip()
        if first_hint and not first_hint.startswith("[LLM_INTERNAL]"):
            lines.extend(["", first_hint])
    return _sanitize_reply_for_user(_normalize_user_facing_terms("\n".join(lines)))


def _clean_status_item_for_user(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("(unknown)", "")
    text = re.sub(r"@(\d+)", r"第\1位", text)
    return text


def _format_status_tier_counts(tier_counts: Any) -> str:
    if not isinstance(tier_counts, dict):
        return ""
    parts = []
    for key in ("冲", "稳", "保"):
        value = tier_counts.get(key)
        if value is None:
            continue
        parts.append(f"{key}{value}")
    return " / ".join(parts)


def _plan_query_projection_mode(facts: dict[str, Any]) -> str:
    dsl = facts.get("plan_query_dsl") if isinstance(facts.get("plan_query_dsl"), dict) else {}
    projection = dsl.get("projection") if isinstance(dsl.get("projection"), dict) else {}
    return str(projection.get("mode") or "").strip()


def _plan_query_focus(facts: dict[str, Any], result: dict[str, Any]) -> set[str]:
    focus: list[Any] = []
    if isinstance(result.get("reply_focus"), list):
        focus.extend(result.get("reply_focus") or [])
    requested = facts.get("requested_reply_focus") if isinstance(facts.get("requested_reply_focus"), list) else []
    focus.extend(requested)
    mode = _plan_query_projection_mode(facts)
    if mode:
        focus.append(mode)
    return {str(item or "").strip() for item in focus if str(item or "").strip()}


def _format_query_filter_values(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, list):
        cleaned = [str(item or "").strip() for item in values if str(item or "").strip()]
    else:
        text = str(values or "").strip()
        cleaned = [text] if text else []
    if not cleaned:
        return ""
    return "、".join(dict.fromkeys(cleaned))


def _plan_query_filter_summary(facts: dict[str, Any]) -> str:
    filters: dict[str, Any] = {}
    query_filters = facts.get("query_filters")
    if isinstance(query_filters, dict):
        filters.update(query_filters)
    dsl = facts.get("plan_query_dsl") if isinstance(facts.get("plan_query_dsl"), dict) else {}
    dsl_filters = dsl.get("filters") if isinstance(dsl.get("filters"), dict) else {}
    for key, value in dsl_filters.items():
        filters.setdefault(key, value)

    parts: list[str] = []
    tier_text = _format_query_filter_values(filters.get("tiers") or filters.get("tier"))
    if tier_text:
        parts.append(f"档位：{tier_text}")
    province_text = _format_query_filter_values(filters.get("province_names") or filters.get("province_keyword"))
    if province_text:
        parts.append(f"省份：{province_text}")
    city_text = _format_query_filter_values(filters.get("city_names") or filters.get("city_keyword"))
    if city_text:
        parts.append(f"城市：{city_text}")
    school_text = _format_query_filter_values(filters.get("school_keywords") or filters.get("school_keyword"))
    if school_text:
        parts.append(f"院校关键词：{school_text}")
    major_text = _format_query_filter_values(filters.get("major_keywords") or filters.get("major_keyword"))
    if major_text:
        parts.append(f"专业关键词：{major_text}")
    school_tag_text = _format_query_filter_values(filters.get("school_tags"))
    if school_tag_text:
        parts.append(f"院校标签：{school_tag_text}")
    major_tag_text = _format_query_filter_values(filters.get("major_tags"))
    if major_tag_text:
        parts.append(f"专业标签：{major_tag_text}")
    min_tuition = filters.get("min_tuition_per_year")
    if min_tuition:
        parts.append(f"学费：不低于{min_tuition}元/年")
    max_tuition = filters.get("max_tuition_per_year")
    if max_tuition:
        parts.append(f"学费：不超过{max_tuition}元/年")
    return "；".join(parts)


def _summary_indicates_no_query_result(summary: str) -> bool:
    text = str(summary or "")
    return any(marker in text for marker in ("命中数量：0", "没有候选结果", "暂时没有命中", "没有命中符合"))


def _build_plan_query_fallback_lines(result: dict[str, Any], *, summary: str) -> list[str] | None:
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    focus = _plan_query_focus(facts, result)
    if not focus:
        return None
    result_kind = str(result.get("result_kind") or "").strip()
    if result_kind == "status_overview" and "count_summary" in focus:
        current_total = int(facts.get("current_total") or 0)
        target_total = int(facts.get("target_total") or 0)
        tier_text = _format_status_tier_counts(facts.get("tier_counts"))
        if current_total <= 0:
            return ["当前还没有生成正式方案。"]
        target = target_total or current_total
        lines = [f"当前方案一共有 {current_total}/{target} 个志愿。"]
        if tier_text:
            lines.append(f"冲稳保分布：{tier_text}。")
        gap_hint = str(facts.get("count_gap_hint") or "").strip()
        if gap_hint:
            lines.append(gap_hint)
        return lines
    if result_kind in {"ordered_snapshot", "candidate_snapshot"} and (
        focus & {"school_list_query", "school_presence_query", "plan_slice_query", "candidate_slice_query", "plan_filter_query", "tuition", "safety_check"}
    ):
        lines = [summary]
        filter_summary = _plan_query_filter_summary(facts)
        if filter_summary:
            if _summary_indicates_no_query_result(summary):
                lines.append(f"我这次按这些条件查：{filter_summary}，暂时没有命中结果。")
            elif result_kind == "candidate_snapshot" or "school_list_query" in focus or "school_presence_query" in focus:
                lines.append(f"查询条件：{filter_summary}。")
        if "safety_check" in focus:
            facts_tier = str(facts.get("tier") or "").strip()
            matched_count = int(facts.get("matched_count") or 0)
            if facts_tier and matched_count > 0:
                lines.append(f"这次判断基于当前命中的 {matched_count} 条{facts_tier}档结果；是否足够安全仍以录取率梯度和审查结果一起看。")
        return lines
    return None


def _build_status_overview_fallback_lines(facts: dict[str, Any]) -> list[str]:
    current_total = int(facts.get("current_total") or 0)
    target_total = int(facts.get("target_total") or 0)
    risk_count = int(facts.get("risk_count") or 0)
    warn_count = int(facts.get("warn_count") or 0)
    tier_text = _format_status_tier_counts(facts.get("tier_counts"))
    top_items = [_clean_status_item_for_user(item) for item in (facts.get("top_items") or [])]
    top_items = [item for item in top_items if item]
    relation = facts.get("intent_relation") if isinstance(facts.get("intent_relation"), dict) else {}

    if current_total <= 0:
        return [
            "当前还没有生成正式方案。",
            "",
            "你可以直接说“帮我生成一版方案”，我会按你的成绩和偏好先生成方案，再继续做审查和调整。",
        ]

    target = target_total or current_total
    lines = [
        "我看了当前方案，核心情况如下：",
        "",
        f"- 完整度：{current_total}/{target} 个志愿。"
    ]
    if tier_text:
        lines.append(f"- 冲稳保：{tier_text}。")
    if risk_count > 0 or warn_count > 0:
        lines.append(f"- 审查：风险 {risk_count} 项，提醒 {warn_count} 项。")
    else:
        lines.append("- 审查：暂时没有明显风险。")

    coverage = str(relation.get("coverage") or "").removeprefix("承接情况：").strip()
    if coverage:
        lines.append(f"- 偏好承接：{coverage}")
    aligned_examples = _clean_status_item_for_user(
        str(relation.get("aligned_examples") or "").removeprefix("贴近偏好：")
    )
    if aligned_examples:
        lines.append(f"- 贴近偏好的例子：{aligned_examples}")
    conflict_examples = _clean_status_item_for_user(
        str(relation.get("conflict_examples") or "").removeprefix("需关注冲突：")
    )
    if conflict_examples:
        lines.append(f"- 需要关注的冲突：{conflict_examples}")
    if top_items:
        lines.append(f"- 前排示例：{'；'.join(top_items[:3])}。")

    reminders = [str(item or "").strip() for item in (facts.get("main_reminders") or []) if str(item or "").strip()]
    if reminders:
        lines.append(f"- 重点提醒：{'；'.join(reminders[:2])}。")

    lines.extend([
        "",
        "下一步可以继续看审查明细，或直接告诉我想往更稳、某个地域、某类专业方向调整。",
    ])
    return lines


def build_timeout_fallback_from_recent_plan_execution(
    session_id: str,
    user_prompt: str,
) -> ChatServiceResponseEnvelope | None:
    result = consume_recent_plan_execution_result(session_id, user_prompt)
    if not result:
        return None
    reply = _build_plan_timeout_fallback_reply(result, user_prompt=user_prompt)
    if not reply:
        return None
    workspace_refresh_targets = _dedupe_workspace_targets(
        [str(target) for target in (result.get("workspace_refresh_targets") or [])]
    )
    if workspace_refresh_targets:
        return ChatServiceResponseEnvelope(
            primary=reply,
            followups=[
                _build_silent_workspace_refresh_response(session_id, target)
                for target in workspace_refresh_targets
            ],
        )
    return ChatServiceResponseEnvelope(primary=reply)


async def build_interruption_fallback_from_recent_plan_execution(
    session_id: str,
    user_prompt: str,
) -> ChatServiceResponseEnvelope | None:
    result = consume_recent_plan_execution_result(session_id, user_prompt)
    if not result:
        return None

    reply = _build_plan_timeout_fallback_reply(result, user_prompt=user_prompt)
    if not reply:
        return None
    workspace_refresh_targets = _dedupe_workspace_targets(
        [str(target) for target in (result.get("workspace_refresh_targets") or [])]
    )
    followups = [
        _build_silent_workspace_refresh_response(session_id, target)
        for target in workspace_refresh_targets
    ]
    return ChatServiceResponseEnvelope(primary=reply, followups=followups)


def _replace_text_reply(messages: list[Any] | None, old_reply: str, new_reply: str) -> None:
    if old_reply == new_reply:
        return
    for message in messages or []:
        if not isinstance(message, ModelResponse):
            continue
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, TextPart) and part.content == old_reply:
                part.content = new_reply


def _build_direct_plan_action_messages(
    user_prompt: str,
    *,
    tool_call_id: str,
    plan_payload: dict[str, Any],
    result_text: str,
    reply: str,
    model_name: str,
) -> list[Any]:
    return [
        ModelRequest(parts=[UserPromptPart(content=user_prompt)]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_plan_action",
                    args={"plan_payload": json.dumps(plan_payload, ensure_ascii=False)},
                    tool_call_id=tool_call_id,
                )
            ],
            model_name=model_name,
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute_plan_action",
                    content=result_text,
                    tool_call_id=tool_call_id,
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
    ]


@dataclass
class _StructuredPlanRerouteResult:
    reply: str
    messages: list[Any]
    route_decision: dict[str, Any]
    pending_result: _RuntimeCompiledPendingResult | None = None
    workspace_refresh_targets: list[str] = field(default_factory=list)


def _reply_looks_like_unbacked_plan_action_boundary(reply: str) -> bool:
    return proposal_compiler.runtime_reply_looks_like_unbacked_plan_action_boundary(reply)


def _compact_zhiyuan_agent_poc_reply(reply: Any, *, limit: int = 500) -> str:
    text = str(reply or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _zhiyuan_agent_poc_next_steps(tool_returns: list[ToolReturnPart]) -> list[str]:
    next_steps: list[str] = []
    for part in tool_returns:
        data = _parse_tool_return_json(part.content)
        if not isinstance(data, dict):
            continue
        next_step = str(data.get("next_step") or "").strip()
        if next_step and next_step not in next_steps:
            next_steps.append(next_step)
    return next_steps


def _zhiyuan_agent_poc_first_tool_args(tool_calls: list[ToolCallPart]) -> dict[str, Any]:
    if not tool_calls:
        return {}
    args = _parse_tool_call_args(tool_calls[0].args)
    result: dict[str, Any] = {}
    for key in ("intent_type", "topic_type", "scope", "path", "constraint_type"):
        value = args.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    if isinstance(args.get("positive"), dict) and args["positive"]:
        result["positive"] = args["positive"]
    if isinstance(args.get("negative"), dict) and args["negative"]:
        result["negative"] = args["negative"]
    if isinstance(args.get("filters"), dict) and args["filters"]:
        result["filters"] = args["filters"]
    return result


def _summarize_zhiyuan_agent_poc_shadow(
    *,
    reply: Any,
    messages: list[Any],
    usage: Any,
    duration_ms: int,
) -> dict[str, Any]:
    tool_calls = _iter_tool_call_parts(messages)
    tool_returns = _iter_tool_return_parts(messages)
    tool_names = [str(part.tool_name or "") for part in tool_calls if str(part.tool_name or "")]
    return {
        "enabled": True,
        "status": "success",
        "routingPath": "zhiyuan_agent_poc",
        "firstToolNames": tool_names[:1],
        "toolCallNames": tool_names,
        "toolCallCount": getattr(usage, "tool_calls", None),
        "llmRequests": getattr(usage, "requests", None),
        "inputTokens": getattr(usage, "input_tokens", None),
        "outputTokens": getattr(usage, "output_tokens", None),
        "totalTokens": getattr(usage, "total_tokens", None),
        "nextSteps": _zhiyuan_agent_poc_next_steps(tool_returns),
        "firstToolArgs": _zhiyuan_agent_poc_first_tool_args(tool_calls),
        "durationMs": duration_ms,
        "replyPreview": _compact_zhiyuan_agent_poc_reply(reply),
    }


def _zhiyuan_agent_poc_shadow_error(exc: BaseException, *, duration_ms: int) -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "error",
        "routingPath": "zhiyuan_agent_poc",
        "durationMs": duration_ms,
        "errorType": type(exc).__name__,
        "errorMessage": _compact_zhiyuan_agent_poc_reply(str(exc), limit=240),
    }


def _zhiyuan_agent_direct_rollout_bucket(session_id: str, user_id: str = "") -> float:
    seed = f"{session_id}:{user_id}".encode("utf-8", errors="ignore")
    digest = hashlib.sha256(seed).hexdigest()[:8]
    return int(digest, 16) % 10000 / 100.0


def _score_available_for_zhiyuan_agent_direct(request_context: RequestContext) -> bool:
    sandbox = getattr(request_context, "sandbox", None)
    score = sandbox.peek("score.json") if sandbox is not None else None
    if isinstance(score, dict):
        return bool(
            score.get("available")
            and str(score.get("province") or "").strip()
            and _as_int(score.get("total_score")) > 0
        )
    score_detail = getattr(request_context, "score_detail", None)
    return bool(
        score_detail is not None
        and str(getattr(score_detail, "province", "") or "").strip()
        and _as_int(getattr(score_detail, "total_score", 0)) > 0
    )


def _latest_direct_confirm_pending_payload(
    messages: list[Any] | None,
) -> tuple[dict[str, Any], str] | None:
    for part in reversed(_iter_tool_return_parts(messages)):
        tool_name = str(part.tool_name or "").strip()
        payload = _parse_tool_return_json(part.content)
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if str(payload.get("next_step") or "").strip() != "confirm":
            continue
        if not data.get("pending_created"):
            continue
        pending_id = str(data.get("pending_id") or data.get("pendingId") or "").strip()
        if not pending_id:
            continue
        return payload, tool_name
    return None


def _pending_id_from_tool_payload(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("pending_id") or data.get("pendingId") or "").strip()


def _pending_state_from_sandbox(
    request_context: RequestContext,
    *,
    pending_id: str,
) -> dict[str, Any] | None:
    sandbox = getattr(request_context, "sandbox", None)
    if sandbox is None:
        return None
    pending_file = sandbox.peek("pending.json")
    if not isinstance(pending_file, dict):
        return None
    raw = pending_file.get("raw")
    if not isinstance(raw, dict):
        return None
    if str(raw.get("status") or "").strip() != "active":
        return None
    raw_pending_id = str(raw.get("pendingId") or raw.get("pending_id") or "").strip()
    if pending_id and raw_pending_id and raw_pending_id != pending_id:
        return None
    return raw


def _clean_structured_pending_card_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[\s。；;，,]*(?:采纳/)?确认前不会生效[。.!！]*", "", cleaned).strip()
    cleaned = re.sub(r"[\s。；;，,]*点[“\"]?采纳[”\"]?前不会生效[。.!！]*", "", cleaned).strip()
    cleaned = re.sub(r"[\s。；;，,]*确认后我会执行这次方案调整[。.!！]*", "", cleaned).strip()
    return cleaned


def _build_structured_intent_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    if not isinstance(pending_state, dict):
        return None
    pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
    if not pending_id:
        return None
    if str(pending_state.get("kind") or "").strip() != "intent_change":
        return None
    execution_payload = pending_state.get("executionPayload")
    if not isinstance(execution_payload, dict):
        execution_payload = {}
    selected_data = execution_payload.get("selectedData")
    if not isinstance(selected_data, dict):
        selected_data = {}
    intent_mode = str(
        execution_payload.get("intentMode")
        or selected_data.get("intentMode")
        or "constraint"
    ).strip() or "constraint"
    if intent_mode != "constraint":
        intent_mode = "constraint"
    constraint_intent_type = str(
        execution_payload.get("constraintIntentType")
        or execution_payload.get("constraint_intent_type")
        or selected_data.get("constraintIntentType")
        or selected_data.get("constraint_intent_type")
        or "default"
    ).strip() or "default"
    summary = _clean_structured_pending_card_text(
        str(pending_state.get("summary") or fallback_summary or "").strip()
    )
    if not summary:
        merged = execution_payload.get("merged")
        if isinstance(merged, dict):
            summary = _clean_structured_pending_card_text(
                _summarize_intent_values(
                    merged,
                    intent_mode=intent_mode,
                    constraint_intent_type=constraint_intent_type,
                )
            )
    if not summary:
        summary = "本次选择的报考要求。"
    impact_payload = execution_payload.get("merged") if isinstance(execution_payload.get("merged"), dict) else {}
    if constraint_intent_type:
        impact_payload = {
            **impact_payload,
            "constraintIntentType": constraint_intent_type,
        }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_id,
        "kind": "intent_change",
        "actionFamily": str(pending_state.get("actionFamily") or "apply_selected_intents").strip()
        or "apply_selected_intents",
        "intentMode": "constraint",
        "title": "采纳这次报考条件",
        "summary": summary,
        "content": _format_intent_card_content(summary),
        "constraintIntentType": constraint_intent_type,
        "clickable": True,
        "status": "active",
        "confirmText": "采纳",
        "cancelText": "暂不采纳",
        "impactTitle": "采纳后的作用",
        "impact": _format_intent_card_impact(
            impact_payload,
            intent_mode=intent_mode,
        ),
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _build_structured_plan_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    if not isinstance(pending_state, dict):
        return None
    pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
    if not pending_id:
        return None
    kind = str(pending_state.get("kind") or "").strip()
    if kind != "plan_mutation":
        return None
    action_family = str(pending_state.get("actionFamily") or pending_state.get("action_family") or "").strip()
    summary = _clean_structured_pending_card_text(
        str(pending_state.get("summary") or fallback_summary or "").strip()
    )
    affected_scope = _clean_structured_pending_card_text(
        str(pending_state.get("affectedScope") or pending_state.get("affected_scope") or "").strip()
    )
    content = summary or affected_scope or "确认后会执行本次方案调整。"
    if affected_scope and affected_scope not in content:
        content = f"{content}\n\n影响范围：{affected_scope}"
    title_by_action = {
        "add_units": "确认加入方案",
        "remove_units": "确认移出志愿",
        "remove_ordered_unit": "确认移出志愿",
        "replace_units": "确认替换志愿",
        "move_unit": "确认移动志愿",
        "move_ordered_unit": "确认移动志愿",
        "sort_ordered_plan": "确认方案排序",
        "regenerate_order": "确认重排方案",
        "generate_plan": "确认生成方案",
    }
    payload = {
        "type": "pendingConfirmationCard",
        "pendingId": pending_id,
        "kind": "plan_mutation",
        "actionFamily": action_family,
        "title": title_by_action.get(action_family) or "请确认本次方案调整",
        "summary": summary or "确认后会执行本次方案调整。",
        "content": content,
        "impactTitle": "确认说明",
        "impact": "确认前不会改动当前方案；点“确认执行”后才会按这次预览处理。",
        "clickable": True,
        "status": "active",
        "confirmText": "确认执行",
        "cancelText": "暂不执行",
    }
    return WSResponse(
        type="pendingConfirmationCard",
        session_id=session_id,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _build_structured_pending_card(
    session_id: str,
    pending_state: dict[str, Any],
    *,
    fallback_summary: str = "",
) -> WSResponse | None:
    kind = str((pending_state or {}).get("kind") or "").strip()
    if kind == "intent_change":
        return _build_structured_intent_pending_card(
            session_id,
            pending_state,
            fallback_summary=fallback_summary,
        )
    if kind == "plan_mutation":
        return _build_structured_plan_pending_card(
            session_id,
            pending_state,
            fallback_summary=fallback_summary,
        )
    return None


class ChatService:
    """会话管理 + Agent 编排。SQLite 持久化会话历史。"""

    # 每 _LOG_INTERVAL 轮输出一次 session 累计 token 消耗摘要
    _LOG_INTERVAL = 5
    _INITIAL_PROGRESS_DELAY_SECONDS = 1.5
    _INITIAL_PROGRESS_HINT = "正在理解你的问题，并结合当前信息整理回答..."
    _EARLY_CONTEXT_PROGRESS_DELAY_SECONDS = 1.2
    _EARLY_CONTEXT_PROGRESS_HINT = "正在读取当前会话信息..."
    _LONG_PROGRESS_MODEL_WAIT_HINTS = (
        (12.0, "还在分析你的问题，正在整理可用信息，请稍等..."),
        (25.0, "这轮回答比平时慢一些，我会继续保留当前会话状态；没有明确确认前不会改动偏好或方案。"),
        (60.0, "还在整理完整结论，我会继续保留当前会话状态；如果超时，会先给你安全提示。"),
    )
    _LONG_PROGRESS_TOOL_HINTS = (
        (12.0, "还在处理，这轮需要结合当前信息整理结论，请稍等..."),
        (25.0, "这轮分析耗时较长，我会继续等待结果，并尽量给出已确认的信息和下一步建议..."),
        (60.0, "已经整理出部分分析信息，正在补全结论；我会继续保留当前会话状态。"),
    )
    _LONG_PROGRESS_HINTS = _LONG_PROGRESS_TOOL_HINTS
    _MIN_PROGRESS_INTERVAL_SECONDS = 8.0

    def __init__(self, llm_client: LLMClient, history_store: ChatHistoryStore):
        self.llm_client = llm_client
        self.agent = ChatAgent(llm_client)
        self._zhiyuan_agent_poc_shadow_enabled = _env_bool("ZHIYUAN_AGENT_POC_SHADOW", False)
        self._zhiyuan_agent_direct_enabled = _env_bool("ZHIYUAN_AGENT_ENABLED", False)
        self._zhiyuan_agent_rollout_percent = min(
            100.0,
            max(0.0, _env_float("ZHIYUAN_AGENT_ROLLOUT_PERCENT", 0.0)),
        )
        self.zhiyuan_agent_poc: ZhiyuanAgent | None = (
            ZhiyuanAgent(llm_client)
            if (
                self._zhiyuan_agent_poc_shadow_enabled
                or self._zhiyuan_agent_direct_enabled
                or self._zhiyuan_agent_rollout_percent > 0
            )
            else None
        )
        self.history_store = history_store
        self.history_config = HistoryConfig()
        self._usage_trackers: dict[str, UsageTracker] = {}

    # ── 公开接口：session 级 usage 查询 ───────────────────────────

    def get_usage_summary(self, session_id: str) -> dict | None:
        """返回指定 session 的累计 token 消耗摘要，供上层计费/监控使用。"""
        tracker = self._usage_trackers.get(session_id)
        return tracker.summary() if tracker else None

    def get_usage_tracker(self, session_id: str) -> UsageTracker | None:
        """获取指定 session 的 UsageTracker 实例。"""
        return self._usage_trackers.get(session_id)

    async def _maybe_run_zhiyuan_agent_poc_shadow(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        request_context: RequestContext,
        message_history: list[Any] | None,
    ) -> dict[str, Any] | None:
        if not self._zhiyuan_agent_poc_shadow_enabled or self.zhiyuan_agent_poc is None:
            return None
        if _ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE <= 0:
            return None
        if _ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE < 1.0 and random.random() >= _ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE:
            shadow = {
                "enabled": True,
                "status": "sampled_out",
                "routingPath": "zhiyuan_agent_poc",
                "sampleRate": _ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE,
            }
            setattr(request_context, "_zhiyuan_agent_poc_shadow", shadow)
            return shadow

        shadow_context = replace(
            request_context,
            conversation_phase=(
                request_context.conversation_phase.model_copy(deep=True)
                if request_context.conversation_phase is not None
                else None
            ),
            progress_callback=None,
            agent_observability={},
            allow_explore_inner_llm=False,
            enable_intent_side_effect_arbitration=False,
            dry_run_state_mutations=True,
            sandbox=build_request_sandbox(
                session_id=session_id,
                batch=getattr(request_context, "batch", None),
                score_detail=getattr(request_context, "score_detail", None),
                init_profile=getattr(request_context, "init_profile", None),
                planning_summary=getattr(request_context, "planning_summary", None),
                pending=getattr(getattr(request_context, "conversation_phase", None), "pending", None),
            ),
        )

        shadow = {
            "enabled": True,
            "status": "running",
            "routingPath": "zhiyuan_agent_poc",
            "sampleRate": _ZHIYUAN_AGENT_POC_SHADOW_SAMPLE_RATE,
        }
        setattr(request_context, "_zhiyuan_agent_poc_shadow", shadow)
        task = asyncio.create_task(
            self._run_zhiyuan_agent_poc_shadow_task(
                session_id=session_id,
                user_id=user_id,
                content=content,
                request_context=request_context,
                shadow_context=shadow_context,
                message_history=message_history,
            )
        )
        setattr(request_context, "_zhiyuan_agent_poc_shadow_task", task)
        return shadow

    async def _run_zhiyuan_agent_poc_shadow_task(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        request_context: RequestContext,
        shadow_context: RequestContext,
        message_history: list[Any] | None,
    ) -> dict[str, Any]:
        if self.zhiyuan_agent_poc is None:
            shadow = {
                "enabled": True,
                "status": "disabled",
                "routingPath": "zhiyuan_agent_poc",
            }
            setattr(request_context, "_zhiyuan_agent_poc_shadow", shadow)
            return shadow
        started_at = time.monotonic()
        try:
            run_coro = self.zhiyuan_agent_poc.run_with_message_deltas(
                user_prompt=content,
                message_history=message_history,
                deps=shadow_context,
            )
            if _ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS > 0:
                reply, new_messages, _all_messages, usage = await asyncio.wait_for(
                    run_coro,
                    timeout=_ZHIYUAN_AGENT_POC_SHADOW_TIMEOUT_SECONDS,
                )
            else:
                reply, new_messages, _all_messages, usage = await run_coro
            shadow = _summarize_zhiyuan_agent_poc_shadow(
                reply=reply,
                messages=new_messages,
                usage=usage,
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            shadow = _zhiyuan_agent_poc_shadow_error(
                exc,
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
            logger.warning(
                "ZhiyuanAgent PoC shadow failed: session_id=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=not isinstance(exc, asyncio.TimeoutError),
            )

        setattr(request_context, "_zhiyuan_agent_poc_shadow", shadow)
        _log_zhiyuan_agent_poc_shadow_event(
            sessionId=session_id,
            userId=user_id,
            promptLength=len(content or ""),
            shadow=shadow,
        )
        with contextlib.suppress(Exception):
            await _append_zhiyuan_agent_poc_shadow_history(
                self.history_store,
                session_id=session_id,
                user_id=user_id,
                prompt_length=len(content or ""),
                shadow=shadow,
            )
        return shadow

    def _should_use_zhiyuan_agent_direct(self, *, session_id: str, user_id: str) -> bool:
        if bool(getattr(self, "_zhiyuan_agent_direct_enabled", False)):
            return True
        rollout_percent = float(getattr(self, "_zhiyuan_agent_rollout_percent", 0.0) or 0.0)
        if rollout_percent <= 0:
            return False
        return _zhiyuan_agent_direct_rollout_bucket(session_id, user_id) < rollout_percent

    async def _pending_state_for_direct_card(
        self,
        *,
        session_id: str,
        request_context: RequestContext,
        pending_id: str,
    ) -> dict[str, Any] | None:
        pending_state = _pending_state_from_sandbox(request_context, pending_id=pending_id)
        if isinstance(pending_state, dict):
            return pending_state
        pending_state = await _load_pending_confirmation_state(session_id)
        if not isinstance(pending_state, dict):
            return None
        if str(pending_state.get("status") or "").strip() != "active":
            return None
        loaded_pending_id = str(pending_state.get("pendingId") or pending_state.get("pending_id") or "").strip()
        if pending_id and loaded_pending_id and pending_id != loaded_pending_id:
            return None
        return pending_state

    async def _maybe_handle_zhiyuan_agent_direct_route(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        message_history: list[Any] | None,
        turn_started_at: float,
        on_progress: ProgressCallback | None,
    ) -> str | ChatServiceResponseEnvelope | None:
        if not self._should_use_zhiyuan_agent_direct(session_id=session_id, user_id=user_id):
            return None
        if self.zhiyuan_agent_poc is None:
            return None
        if not _score_available_for_zhiyuan_agent_direct(request_context):
            return None

        direct_started_at = time.monotonic()
        try:
            run_coro = self.zhiyuan_agent_poc.run_with_message_deltas(
                user_prompt=content,
                message_history=message_history,
                deps=request_context,
                on_progress=on_progress,
            )
            if _ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS > 0:
                reply, new_messages, all_messages, usage = await asyncio.wait_for(
                    run_coro,
                    timeout=_ZHIYUAN_AGENT_DIRECT_TIMEOUT_SECONDS,
                )
            else:
                reply, new_messages, all_messages, usage = await run_coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
            safe_reply = "这轮处理没有完成，请稍后重试。没有明确确认前，不会改动报考条件或方案。"
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=safe_reply)], model_name="zhiyuan-agent-direct-error"),
            ]
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "unknown",
                "routingPath": "zhiyuan_agent_direct",
                "routeDecision": {
                    "source": "zhiyuan_agent",
                    "matched": True,
                    "route": "direct",
                    "error": type(exc).__name__,
                },
                "pendingType": None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "totalDurationMs": total_duration_ms,
                "directAgentDurationMs": int((time.monotonic() - direct_started_at) * 1000),
                **_observability_timing_fields(request_context),
                "toolCalls": [],
                "postProcessingApplied": ["zhiyuan_agent_direct"],
                "status": "error",
                "errorType": type(exc).__name__,
            }
            _log_conversation_turn_event(**turn_event)
            try:
                history_to_save = list(history or [])
                history_to_save.extend(
                    _append_turn_observability_messages(
                        new_messages,
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save ZhiyuanAgent direct error history: session_id=%s", session_id)
            logger.warning(
                "ZhiyuanAgent direct route failed: session_id=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=not isinstance(exc, asyncio.TimeoutError),
            )
            return safe_reply

        tracker = self._usage_trackers.get(session_id)
        if tracker is None:
            tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
        tracker.record(usage)

        pending_card: WSResponse | None = None
        pending_state: dict[str, Any] | None = None
        pending_payload_info = _latest_direct_confirm_pending_payload(new_messages)
        pending_tool_name = ""
        if pending_payload_info is not None:
            pending_payload, pending_tool_name = pending_payload_info
            pending_id = _pending_id_from_tool_payload(pending_payload)
            pending_state = await self._pending_state_for_direct_card(
                session_id=session_id,
                request_context=request_context,
                pending_id=pending_id,
            )
            if isinstance(pending_state, dict):
                pending_card = _build_structured_pending_card(
                    session_id,
                    pending_state,
                    fallback_summary=str(pending_payload.get("message") or ""),
                )

        final_reply = str(reply or "").strip()
        if pending_card is not None:
            primary_from_card = _pending_confirmation_primary_reply_from_card(pending_card)
            use_card_primary = final_reply in {"", "已完成处理。", "已完成处理"}
            if primary_from_card and use_card_primary:
                if final_reply:
                    _replace_text_reply(new_messages, final_reply, primary_from_card)
                    _replace_text_reply(all_messages, final_reply, primary_from_card)
                final_reply = primary_from_card
        final_reply = _sanitize_reply_for_user(final_reply or "已完成处理。")

        tool_calls = _iter_tool_call_parts(new_messages)
        tool_returns = _iter_tool_return_parts(new_messages)
        observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
        confirm_pending_result = _latest_confirm_pending_tool_result(tool_calls, tool_returns)
        direct_routing_path = _direct_confirm_routing_path(confirm_pending_result)
        direct_workspace_refresh_targets = _direct_confirm_workspace_refresh_targets(confirm_pending_result)
        pending_kind = str((pending_state or {}).get("kind") or "").strip()
        if not pending_kind and isinstance(confirm_pending_result.get("data"), dict):
            pending_kind = str(confirm_pending_result["data"].get("kind") or "").strip()
        action_family = str((pending_state or {}).get("actionFamily") or "").strip() or None
        if not action_family and isinstance(confirm_pending_result.get("data"), dict):
            action_family = str(confirm_pending_result["data"].get("action_family") or "").strip() or None
        scene = "plan" if pending_kind == "plan_mutation" else "intent" if pending_kind == "intent_change" else "unknown"
        total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": scene,
            "routingPath": direct_routing_path,
            "routeDecision": {
                "source": "zhiyuan_agent",
                "matched": True,
                "route": "direct_confirm_pending" if direct_routing_path != "zhiyuan_agent_direct" else "direct",
                "firstToolNames": [part.tool_name for part in tool_calls[:1]],
                "confirmToolName": pending_tool_name or None,
                "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
            },
            "pendingType": "plan" if pending_kind == "plan_mutation" else "intent" if pending_kind == "intent_change" else None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(usage, "requests", None),
            "inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
            "toolCallCount": getattr(usage, "tool_calls", None),
            "totalDurationMs": total_duration_ms,
            "directAgentDurationMs": int((time.monotonic() - direct_started_at) * 1000),
            **_observability_timing_fields(request_context),
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["zhiyuan_agent_direct"],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    list(new_messages),
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save ZhiyuanAgent direct history: session_id=%s", session_id)

        if pending_card is not None:
            return ChatServiceResponseEnvelope(
                primary=final_reply,
                followups=[pending_card],
            )
        if direct_workspace_refresh_targets:
            return ChatServiceResponseEnvelope(
                primary=final_reply,
                followups=[
                    _build_silent_workspace_refresh_response(session_id, target)
                    for target in _dedupe_workspace_targets(direct_workspace_refresh_targets)
                ],
            )
        return final_reply

    async def _execute_semantic_plan_payload(
        self,
        *,
        request_context: RequestContext,
        plan_payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any], int]:
        started_at = time.monotonic()
        result_text = await execute_plan_action(
            SimpleNamespace(deps=request_context),
            json.dumps(plan_payload, ensure_ascii=False),
        )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return result_text, _parse_tool_return_json(result_text) or {}, duration_ms

    async def _maybe_handle_profile_change_replan_state_query(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        pending_state: dict[str, Any] | None,
        turn_started_at: float,
    ) -> str | None:
        profile_change_dsl = _latest_profile_change_replan_dsl(history)
        if profile_change_dsl is None:
            return None
        pending_exists = isinstance(pending_state, dict) and str(pending_state.get("status") or "active").strip() == "active"
        try:
            turn_decision = await _classify_turn_decision_cached(
                content,
                request_context=request_context,
                payload={
                    "planningStateProfile": _planning_state_profile_for_turn_decision(
                        planning_summary=getattr(request_context, "planning_summary", None),
                        pending_state=pending_state if isinstance(pending_state, dict) else None,
                        score_detail=getattr(request_context, "score_detail", None),
                    ),
                    "pendingState": pending_state if isinstance(pending_state, dict) else {},
                    "historyContext": [
                        {
                            "type": "profileChangeReplanDsl",
                            "value": profile_change_dsl,
                        }
                    ],
                },
            )
        except Exception:
            logger.warning(
                "Profile change state query TurnDecision failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            turn_decision = None

        decision_source = "turn_decision+proposal_compiler"
        confidence = 0.0
        reply_focus: list[str] = []
        if turn_decision is not None and _turn_decision_is_profile_change_state_query(
            turn_decision,
            pending_exists=pending_exists,
        ):
            confidence = float(getattr(turn_decision, "confidence", 0.0) or 0.0)
        else:
            # Compatibility fallback while the old plan-semantic node is being
            # retired for profile-state questions. The compiler still receives
            # only the structured query scenario below.
            try:
                decision = await classify_plan_semantic_action(
                    content,
                    request_context=request_context,
                    recent_plan_context=_latest_plan_semantic_route_context(history),
                )
            except Exception:
                logger.warning(
                    "Profile change state query classification failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                return None
            confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
            focus = _reply_focus_set(decision)
            if confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD or "profile_change_state_query" not in focus:
                return None
            decision_source = "semantic_plan_action+proposal_compiler"
            reply_focus = list(focus)

        resolution = proposal_compiler.resolve_profile_change_replan_state_query(
            profile_change_dsl=profile_change_dsl,
            query_scenario="profile_change_state_query",
        )
        if not resolution.matched:
            return None
        reply = _build_profile_change_replan_state_query_reply(
            profile_change_dsl=profile_change_dsl,
            pending_state=pending_state,
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "profile_change_replan_state_query",
            "routeDecision": {
                "source": decision_source,
                "matched": True,
                "confidence": confidence,
                "route": resolution.route,
                "sideEffect": "readonly_while_pending" if pending_exists else "readonly",
                "replyFocus": reply_focus,
                "turnDecision": (
                    {
                        "taskLayer": str(getattr(turn_decision, "taskLayer", "") or "").strip(),
                        "sideEffect": str(getattr(turn_decision, "sideEffect", "") or "").strip(),
                        "scopeAnchor": str(getattr(turn_decision, "scopeAnchor", "") or "").strip(),
                        "scenario": str(getattr(turn_decision, "scenario", "") or "").strip(),
                        "confidence": float(getattr(turn_decision, "confidence", 0.0) or 0.0),
                    }
                    if turn_decision is not None
                    else None
                ),
                "profileChangeReplanDsl": profile_change_dsl,
                "blockingReasons": list(resolution.blocking_reasons),
            },
            "pendingType": (
                "plan"
                if isinstance(pending_state, dict) and str(pending_state.get("kind") or "").strip() == "plan_mutation"
                else "intent"
                if isinstance(pending_state, dict) and str(pending_state.get("kind") or "").strip() == "intent_change"
                else None
            ),
            "actionFamily": None,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": 0,
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolCalls": [],
            "postProcessingApplied": ["profile_change_replan_state_query"],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        await _save_direct_guard_history(
            self.history_store,
            session_id,
            history,
            content,
            reply,
            model_name="profile-change-replan-state-query",
            turn_event=turn_event,
            request_context=request_context,
            user_id=user_id,
        )
        return reply

    async def _maybe_handle_pending_readonly_plan_query(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        pending_state: dict[str, Any] | None,
        turn_started_at: float,
        turn_decision: Any | None = None,
    ) -> ChatServiceResponseEnvelope | str | None:
        if not (
            isinstance(pending_state, dict)
            and str(pending_state.get("status") or "").strip() == "active"
        ):
            return None
        planning_version = 0
        planning_summary = getattr(request_context, "planning_summary", None)
        if planning_summary is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(getattr(planning_summary, "version", 0) or 0)
        if turn_decision is None:
            turn_decision = await _classify_plan_query_turn_decision(
                content=content,
                request_context=request_context,
                pending_state=pending_state,
            )
        if not _turn_decision_allows_plan_query_profile(turn_decision, pending_exists=True):
            return None
        compiled_query, query_profile = await _compile_runtime_plan_query_from_profile(
            content=content,
            request_context=request_context,
            planning_version=planning_version,
            pending_state=pending_state,
            pending_exists=True,
        )
        if not compiled_query.matched:
            return None
        plan_payload = compiled_query.plan_payload
        result_text, result, tool_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary") or result.get("state_summary") or ""
        ).strip()
        if not reply:
            return None
        pending_kind = str(pending_state.get("kind") or "").strip()
        if pending_kind == "intent_change":
            reply = _append_pending_intent_boundary(reply, has_pending_intent=True)
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        action_family = str(plan_payload.get("action_family") or "").strip()
        tool_call_id = f"pending-readonly-{action_family or 'plan-query'}"
        new_messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=tool_call_id,
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="pending-readonly-plan-query",
        )
        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "pending_readonly_plan_query",
            "routeDecision": {
                "source": "proposal_compiler",
                "matched": True,
                "route": "readonly_while_pending",
                "sideEffect": "readonly_while_pending",
                "actionFamily": action_family,
                "turnDecision": {
                    "taskLayer": str(getattr(turn_decision, "taskLayer", "") or "").strip(),
                    "sideEffect": str(getattr(turn_decision, "sideEffect", "") or "").strip(),
                    "scopeAnchor": str(getattr(turn_decision, "scopeAnchor", "") or "").strip(),
                    "scenario": str(getattr(turn_decision, "scenario", "") or "").strip(),
                    "confidence": float(getattr(turn_decision, "confidence", 0.0) or 0.0),
                },
                "queryProfile": query_profile.model_dump() if hasattr(query_profile, "model_dump") else None,
                "planQueryDsl": compiled_query.plan_query_dsl if compiled_query.matched else None,
            },
            "pendingType": "plan" if pending_kind == "plan_mutation" else "intent" if pending_kind == "intent_change" else None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolDurationMs": tool_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["pending_readonly_plan_query"],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save pending readonly plan query history: session_id=%s", session_id)
        return reply

    async def _maybe_handle_direct_readonly_plan_slice_query(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
    ) -> ChatServiceResponseEnvelope | str | None:
        planning_version = 0
        planning_summary = getattr(request_context, "planning_summary", None)
        if planning_summary is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(getattr(planning_summary, "version", 0) or 0)
        turn_decision = await _classify_plan_query_turn_decision(
            content=content,
            request_context=request_context,
            pending_state=None,
        )
        if not _turn_decision_allows_plan_query_profile(turn_decision, pending_exists=False):
            return None
        compiled_query, query_profile = await _compile_runtime_plan_query_from_profile(
            content=content,
            request_context=request_context,
            planning_version=planning_version,
            pending_exists=False,
        )
        if not compiled_query.matched:
            return None
        plan_payload = compiled_query.plan_payload
        result_text, result, tool_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary") or result.get("state_summary") or ""
        ).strip()
        if not reply:
            return None
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        action_family = str(plan_payload.get("action_family") or "").strip()
        if compiled_query.matched and compiled_query.route == "readonly_plan_slice_query":
            routing_path = "direct_readonly_plan_slice_query"
            route_name = "readonly_plan_slice_query"
            model_name = "direct-readonly-plan-slice-query"
            post_processing = "direct_readonly_plan_slice_query"
        elif compiled_query.matched:
            routing_path = "direct_readonly_plan_query"
            route_name = compiled_query.route
            model_name = "direct-readonly-plan-query"
            post_processing = "direct_readonly_plan_query"
        else:
            routing_path = "direct_readonly_plan_slice_query"
            route_name = "readonly_plan_slice_query"
            model_name = "direct-readonly-plan-slice-query"
            post_processing = "direct_readonly_plan_slice_query"
        tool_call_id = f"direct-readonly-{action_family or 'plan-query'}"
        new_messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=tool_call_id,
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name=model_name,
        )
        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": routing_path,
            "routeDecision": {
                "source": "proposal_compiler",
                "matched": compiled_query.matched,
                "route": route_name,
                "sideEffect": "readonly",
                "actionFamily": action_family,
                "turnDecision": {
                    "taskLayer": str(getattr(turn_decision, "taskLayer", "") or "").strip(),
                    "sideEffect": str(getattr(turn_decision, "sideEffect", "") or "").strip(),
                    "scopeAnchor": str(getattr(turn_decision, "scopeAnchor", "") or "").strip(),
                    "scenario": str(getattr(turn_decision, "scenario", "") or "").strip(),
                    "confidence": float(getattr(turn_decision, "confidence", 0.0) or 0.0),
                },
                "queryProfile": query_profile.model_dump() if hasattr(query_profile, "model_dump") else None,
                "planQueryDsl": compiled_query.plan_query_dsl if compiled_query.matched else None,
            },
            "pendingType": None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolDurationMs": tool_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": [post_processing],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save direct readonly plan slice query history: session_id=%s", session_id)
        return reply

    async def _maybe_handle_direct_local_plan_action(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
    ) -> ChatServiceResponseEnvelope | str | None:
        planning_version = 0
        planning_summary = getattr(request_context, "planning_summary", None)
        if planning_summary is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(getattr(planning_summary, "version", 0) or 0)
        try:
            decision = await classify_local_plan_action_dsl(
                content,
                request_context=request_context,
            )
        except Exception:
            logger.warning(
                "Local plan action DSL classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        action_family = str(getattr(decision, "actionFamily", "none") or "none").strip()
        unsupported_action = str(getattr(decision, "unsupportedAction", "") or "").strip()
        if confidence < _LOCAL_PLAN_ACTION_DSL_CONFIDENCE_THRESHOLD:
            return None
        if action_family == "none" and unsupported_action in _LOCAL_PLAN_UNSUPPORTED_ACTIONS:
            reply = (
                f"你这次的诉求是：{content.strip()}\n\n"
                "这属于锁定/固定当前方案位置的动作。当前还没有可执行的锁定动作，"
                "所以不会创建确认卡，也不会改动方案。\n\n"
                "你可以先核对当前位置；后续如果要做已支持的排序调整，"
                "可以说明目标档位和目标位置。"
            )
            reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-local-plan-action-unsupported"),
            ]
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "plan",
                "routingPath": "direct_local_plan_action_unsupported",
                "routeDecision": {
                    "source": "proposal_compiler",
                    "matched": True,
                    "route": "local_plan_action_unsupported",
                    "sideEffect": "plan_preview_or_clarification",
                    "actionFamily": unsupported_action,
                    "unsupportedAction": unsupported_action,
                    "confidence": confidence,
                    "reason": str(getattr(decision, "reason", "") or ""),
                },
                "pendingType": None,
                "actionFamily": unsupported_action,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "toolCallCount": 0,
                "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                "toolDurationMs": 0,
                "toolCalls": [],
                "postProcessingApplied": ["direct_local_plan_action_unsupported"],
                "status": "success",
                "errorType": None,
            }
            _log_conversation_turn_event(**turn_event)
            try:
                history_to_save = list(history or [])
                history_to_save.extend(
                    _append_turn_observability_messages(
                        new_messages,
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save direct local unsupported plan action history: session_id=%s", session_id)
            return reply
        if action_family == "none":
            return None
        compiled_source = proposal_compiler.compile_runtime_local_plan_action_source(
            content=content,
            action_family=action_family,
            tier=getattr(decision, "tier", None),
            sort_field=getattr(decision, "sortField", None),
            rank=getattr(decision, "rank", None),
            target_ordinal=getattr(decision, "targetOrdinal", None),
            target_rank=getattr(decision, "targetRank", None),
            planning_version=planning_version,
        )
        plan_payload = compiled_source.plan_payload
        if not compiled_source.matched or not plan_payload:
            return None

        result_text, result, tool_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary") or result.get("state_summary") or ""
        ).strip()
        if not reply:
            return None
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        action_family = str(result.get("action_family") or plan_payload.get("action_family") or "").strip()
        tool_call_id = f"direct-local-plan-action-{action_family or 'move'}"
        new_messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=tool_call_id,
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="direct-local-plan-action",
        )

        compiled_plan_pending_card: WSResponse | None = None
        plan_confirmation_candidate = _extract_plan_confirmation_candidate(new_messages)
        if plan_confirmation_candidate is not None:
            compiled_plan_proposal = _runtime_plan_compiled_proposal_from_candidate(
                session_id=session_id,
                confirmation_candidate=plan_confirmation_candidate,
                source="direct_local_plan_action",
            )
            compiled_pending = await _create_runtime_compiled_plan_pending(
                session_id,
                plan_confirmation_candidate,
                source="direct_local_plan_action",
                compiled=compiled_plan_proposal,
            )
            compiled_plan_pending_card = compiled_pending.card
            if compiled_plan_pending_card is not None and compiled_pending.primary_reply:
                _replace_text_reply(new_messages, reply, compiled_pending.primary_reply)
                reply = compiled_pending.primary_reply

        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        workspace_refresh_targets = _dedupe_workspace_targets(
            [str(target) for target in (result.get("workspace_refresh_targets") or [])]
        )
        if compiled_plan_pending_card is None and _plan_result_is_readonly_workspace_no_refresh(
            action_family,
            str(result.get("result_kind") or "").strip(),
        ):
            workspace_refresh_targets = []
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "direct_local_plan_action",
            "routeDecision": {
                "source": "proposal_compiler",
                "matched": True,
                "route": compiled_source.route,
                "sideEffect": "plan_preview" if compiled_plan_pending_card is not None else "readonly",
                "actionFamily": action_family,
                "planActionDsl": compiled_source.plan_action_dsl,
                "confidence": confidence,
                "reason": str(getattr(decision, "reason", "") or ""),
            },
            "pendingType": "plan" if compiled_plan_pending_card is not None else None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolDurationMs": tool_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["direct_local_plan_action"],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save direct local plan action history: session_id=%s", session_id)

        followups = [
            _build_silent_workspace_refresh_response(session_id, target)
            for target in workspace_refresh_targets
        ]
        if compiled_plan_pending_card is not None:
            followups.append(compiled_plan_pending_card)
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def _maybe_handle_direct_atomic_plan_action(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
    ) -> ChatServiceResponseEnvelope | str | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        turn_decision = getattr(request_context, "_turn_decision_object", None)
        if turn_decision is None:
            turn_decision = await _classify_plan_query_turn_decision(
                content=content,
                request_context=request_context,
                pending_state=None,
            )
            if turn_decision is None:
                return None
        mutation_anchor_override = _should_defer_runtime_intent_hard_cut_to_current_plan_action(
            content,
            planning_summary=getattr(request_context, "planning_summary", None),
        )
        turn_decision_probe = proposal_compiler.compile_runtime_atomic_plan_action_source(
            content=content,
            action_family="none",
            confidence=1.0,
            turn_decision=turn_decision,
            require_turn_decision=True,
            planning_version=0,
            allow_mutation_anchor_turn_decision_override=mutation_anchor_override,
        )
        turn_decision_blocks = [
            reason
            for reason in turn_decision_probe.blocking_reasons
            if reason.startswith("unsupported_current_plan_mutation_")
            or reason == "missing_turn_decision"
            or reason == "low_turn_decision_confidence"
        ]
        if turn_decision_blocks:
            return None
        recent_plan_context = _latest_plan_semantic_route_context(history)
        try:
            decision = await classify_plan_atomic_action_dsl(
                content,
                request_context=request_context,
                recent_plan_context=recent_plan_context,
            )
        except Exception:
            logger.warning(
                "Atomic plan action DSL classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        planning_version = 0
        planning_summary = getattr(request_context, "planning_summary", None)
        if planning_summary is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(getattr(planning_summary, "version", 0) or 0)
        compiled_source = proposal_compiler.compile_runtime_atomic_plan_action_source(
            content=content,
            action_family=getattr(decision, "actionFamily", "none"),
            confidence=float(getattr(decision, "confidence", 0.0) or 0.0),
            turn_decision=turn_decision,
            require_turn_decision=True,
            volunteer_ids=list(getattr(decision, "volunteerIds", []) or []),
            unit_ids=list(getattr(decision, "unitIds", []) or []),
            source_major_names=list(getattr(decision, "sourceMajorNames", []) or []),
            source_position=getattr(decision, "sourcePosition", None),
            position_scope=getattr(decision, "positionScope", None),
            target_position=getattr(decision, "targetPosition", None),
            sort_field=getattr(decision, "sortField", None),
            review_issue_code=getattr(decision, "reviewIssueCode", None),
            tier=getattr(decision, "tier", None),
            province_keyword=getattr(decision, "provinceKeyword", None),
            school_keyword=getattr(decision, "schoolKeyword", None),
            major_keyword=getattr(decision, "majorKeyword", None),
            school_tags=list(getattr(decision, "schoolTags", []) or []),
            major_tags=list(getattr(decision, "majorTags", []) or []),
            min_tuition_per_year=getattr(decision, "minTuitionPerYear", None),
            max_tuition_per_year=getattr(decision, "maxTuitionPerYear", None),
            preference_fit=getattr(decision, "preferenceFit", None),
            preserve_count=bool(getattr(decision, "preserveCount", False)),
            limit=int(getattr(decision, "limit", 5) or 5),
            planning_version=planning_version,
            allow_mutation_anchor_turn_decision_override=mutation_anchor_override,
        )
        if not compiled_source.matched:
            if isinstance(getattr(request_context, "agent_observability", None), dict):
                request_context.agent_observability["atomicPlanActionCompiler"] = {
                    "matched": False,
                    "blockingReasons": list(compiled_source.blocking_reasons),
                    "turnDecisionDsl": dict(compiled_source.turn_decision_dsl),
                    "actionFamily": str(getattr(decision, "actionFamily", "none") or "none"),
                    "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
                }
            return None

        plan_started_at = time.monotonic()
        plan_text = await plan_next_action(
            SimpleNamespace(deps=request_context),
            **compiled_source.plan_next_action_args,
        )
        plan_duration_ms = int((time.monotonic() - plan_started_at) * 1000)
        plan_payload = _parse_tool_return_json(plan_text) or {}
        if not isinstance(plan_payload, dict) or not plan_payload:
            return None
        result_text, result, execute_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary") or result.get("preview_summary") or ""
        ).strip()
        if not reply:
            return None
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        plan_tool_call_id = "direct-atomic-plan-action-plan"
        execute_tool_call_id = "direct-atomic-plan-action-execute"
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=content)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="plan_next_action",
                        args=dict(compiled_source.plan_next_action_args),
                        tool_call_id=plan_tool_call_id,
                    )
                ],
                model_name="direct-atomic-plan-action",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="plan_next_action",
                        content=plan_text,
                        tool_call_id=plan_tool_call_id,
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": json.dumps(plan_payload, ensure_ascii=False)},
                        tool_call_id=execute_tool_call_id,
                    )
                ],
                model_name="direct-atomic-plan-action",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=result_text,
                        tool_call_id=execute_tool_call_id,
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name="direct-atomic-plan-action"),
        ]

        compiled_plan_pending_card: WSResponse | None = None
        compiled_pending_workspace_refresh_targets: list[str] = []
        plan_confirmation_candidate = _extract_plan_confirmation_candidate(new_messages)
        pending_result = _RuntimeCompiledPendingResult(source="direct_atomic_plan_action")
        if plan_confirmation_candidate is not None:
            compiled_plan_proposal = _runtime_plan_compiled_proposal_from_candidate(
                session_id=session_id,
                confirmation_candidate=plan_confirmation_candidate,
                source="direct_atomic_plan_action",
            )
            pending_result = await _create_runtime_compiled_plan_pending(
                session_id,
                plan_confirmation_candidate,
                source="direct_atomic_plan_action",
                compiled=compiled_plan_proposal,
            )
            compiled_plan_pending_card = pending_result.card
            compiled_pending_workspace_refresh_targets = list(pending_result.workspace_refresh_targets)
            if compiled_plan_pending_card is not None and pending_result.primary_reply:
                _replace_text_reply(new_messages, reply, pending_result.primary_reply)
                reply = pending_result.primary_reply

        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        action_family = str(result.get("action_family") or plan_payload.get("action_family") or compiled_source.action_family)
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "direct_atomic_plan_action",
            "routeDecision": {
                "source": "proposal_compiler",
                "matched": True,
                "route": compiled_source.route,
                "sideEffect": "plan_preview" if compiled_plan_pending_card is not None else "readonly",
                "actionFamily": action_family,
                "planActionDsl": compiled_source.plan_action_dsl,
                "turnDecisionDsl": compiled_source.turn_decision_dsl,
                "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
                "reason": str(getattr(decision, "reason", "") or ""),
                "blockingReasons": list(compiled_source.blocking_reasons) + list(pending_result.blocked_reasons),
            },
            "pendingType": "plan" if compiled_plan_pending_card is not None else None,
            "actionFamily": action_family,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolDurationMs": plan_duration_ms + execute_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["direct_atomic_plan_action"],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save direct atomic plan action history: session_id=%s", session_id)

        followups: list[WSResponse] = [
            _build_silent_workspace_refresh_response(session_id, target)
            for target in _dedupe_workspace_targets(compiled_pending_workspace_refresh_targets)
        ]
        if compiled_plan_pending_card is not None:
            followups.append(compiled_plan_pending_card)
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def _maybe_create_current_plan_mutation_preview_from_intent_payload(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        preview_payload: dict[str, Any] | None,
    ) -> _StructuredPlanRerouteResult | None:
        candidate = _intent_preview_candidate_from_payload(session_id, preview_payload)
        if candidate is None:
            return None

        planning_version = 0
        planning_summary = getattr(request_context, "planning_summary", None)
        if planning_summary is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(getattr(planning_summary, "version", 0) or 0)
        compiled_source = proposal_compiler.compile_runtime_current_plan_mutation_from_intent_preview_source(
            content=content,
            turn_decision=getattr(request_context, "_turn_decision_object", None),
            merged_intent=candidate.merged,
            intent_mode=candidate.intent_mode,
            constraint_intent_type=candidate.constraint_intent_type,
            summary=candidate.summary,
            planning_version=planning_version,
        )
        if not compiled_source.matched:
            return None
        plan_payload = compiled_source.plan_payload

        result_text, result, _tool_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(
            result.get("summary") or result.get("state_summary") or ""
        ).strip()
        if not reply:
            return None
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        new_messages = _build_direct_plan_action_messages(
            content,
            tool_call_id="turn-decision-intent-preview-remove-units",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="turn-decision-intent-preview-plan-mutation",
        )
        confirmation_candidate = _extract_plan_confirmation_candidate(new_messages)
        pending_result = _RuntimeCompiledPendingResult(
            source="turn_decision_intent_preview_plan_mutation",
        )
        if confirmation_candidate is not None:
            compiled_plan_proposal = _runtime_plan_compiled_proposal_from_candidate(
                session_id=session_id,
                confirmation_candidate=confirmation_candidate,
                source="turn_decision_intent_preview_plan_mutation",
            )
            pending_result = await _create_runtime_compiled_plan_pending(
                session_id,
                confirmation_candidate,
                source="turn_decision_intent_preview_plan_mutation",
                compiled=compiled_plan_proposal,
            )
            if pending_result.card is not None and pending_result.primary_reply:
                _replace_text_reply(new_messages, reply, pending_result.primary_reply)
                reply = pending_result.primary_reply

        route_decision = {
            "source": "proposal_compiler",
            "sourceInputs": ["turn_decision", "intent_preview_payload"],
            "matched": True,
            "route": compiled_source.route,
            "sideEffect": "plan_preview" if pending_result.card is not None else "readonly",
            "actionFamily": compiled_source.action_family,
            "blockedIntentPending": True,
            "currentPlanMutationDsl": compiled_source.mutation_dsl,
            "sourceVersionGuard": compiled_source.source_version_guard,
            "blockingReasons": [*compiled_source.blocking_reasons, *pending_result.blocked_reasons],
        }
        return _StructuredPlanRerouteResult(
            reply=reply,
            messages=new_messages,
            route_decision=route_decision,
            pending_result=pending_result,
            workspace_refresh_targets=list(pending_result.workspace_refresh_targets),
        )

    async def _maybe_create_current_plan_mutation_preview_from_entity_profile(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        profile: Any | None,
    ) -> _StructuredPlanRerouteResult | None:
        if profile is None:
            return None
        preview_payload = _intent_preview_payload_from_entity_profile(
            session_id=session_id,
            profile=profile,
            batch=str(getattr(request_context, "batch", "") or "01"),
        )
        if preview_payload is None:
            return None
        return await self._maybe_create_current_plan_mutation_preview_from_intent_payload(
            session_id=session_id,
            content=content,
            request_context=request_context,
            preview_payload=preview_payload,
        )

    async def _maybe_reroute_runtime_intent_profile_to_plan_response(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
        profile: Any | None,
    ) -> ChatServiceResponseEnvelope | None:
        reroute = await self._maybe_create_current_plan_mutation_preview_from_entity_profile(
            session_id=session_id,
            content=content,
            request_context=request_context,
            profile=profile,
        )
        if reroute is None:
            return None
        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(reroute.messages),
            _iter_tool_return_parts(reroute.messages),
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "runtime_intent_profile_plan_reroute",
            "routeDecision": reroute.route_decision,
            "pendingType": "plan" if reroute.pending_result and reroute.pending_result.card is not None else None,
            "actionFamily": reroute.route_decision.get("actionFamily"),
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            **_observability_timing_fields(request_context),
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": ["runtime_intent_profile_plan_reroute"],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    reroute.messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save runtime intent profile plan reroute history: session_id=%s", session_id)
        followups: list[WSResponse] = [
            _build_silent_workspace_refresh_response(session_id, target)
            for target in _dedupe_workspace_targets(reroute.workspace_refresh_targets)
        ]
        if reroute.pending_result is not None and reroute.pending_result.card is not None:
            followups.append(reroute.pending_result.card)
        return ChatServiceResponseEnvelope(primary=reroute.reply, followups=followups)

    async def _maybe_handle_semantic_plan_action(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        turn_started_at: float,
        on_progress: ProgressCallback | None,
    ) -> ChatServiceResponseEnvelope | str | None:
        active_pending = resolve_pending_confirmation(request_context)
        if active_pending is not None:
            return None
        recent_plan_context = _latest_plan_semantic_route_context(history)
        if not _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            recent_plan_context,
        ):
            return None

        classification_started_at = time.monotonic()
        try:
            decision = await classify_plan_semantic_action(
                content,
                request_context=request_context,
                recent_plan_context=recent_plan_context,
            )
        except Exception:
            logger.warning(
                "Semantic plan action classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        classification_duration_ms = int((time.monotonic() - classification_started_at) * 1000)
        pre_semantic_route_duration_ms = int((time.monotonic() - turn_started_at) * 1000)

        action_family = str(getattr(decision, "actionFamily", "none") or "none")
        original_action_family = action_family
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        turn_decision = getattr(request_context, "_turn_decision_object", None)
        framework_review_or_repair_preview = _turn_decision_is_plan_review_or_repair_preview(turn_decision)
        framework_turn_decision = (
            _turn_decision_snapshot(turn_decision)
            if framework_review_or_repair_preview
            else {}
        )
        framework_reply_focus = [
            str(item or "").strip()
            for item in (framework_turn_decision.get("targetIssue") or [])
            if str(item or "").strip()
        ]
        semantic_promoted_query_state_to_review = False
        if (
            action_family == "query_state"
            and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
            and _semantic_query_state_should_run_review(content)
        ):
            action_family = "review_plan"
            semantic_promoted_query_state_to_review = True
        if (
            action_family == "analyze_adjustment"
            and not framework_review_or_repair_preview
            and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
        ):
            if await _candidate_query_should_bypass_semantic_plan_action(
                content,
                request_context=request_context,
            ):
                return None
        profile_replan_source = _compile_profile_replan_from_decision(
            decision,
            request_context=request_context,
        )
        if (
            confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
            and _semantic_decision_is_profile_replan(decision)
            and profile_replan_source.matched
        ):
            reply = _build_profile_change_replan_reply(
                content,
                request_context=request_context,
                profile_change_dsl=profile_replan_source.profile_change_dsl,
            )
            routing_path = _profile_replan_routing_path(
                profile_replan_source,
                prefix="semantic",
            )
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name=routing_path.replace("_", "-")),
            ]
            total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "plan",
                "routingPath": routing_path,
                "routeDecision": {
                    "source": "semantic_plan_action",
                    "matched": True,
                    "confidence": confidence,
                    "route": action_family,
                    "sideEffect": profile_replan_source.side_effect,
                    "reason": str(getattr(decision, "reason", "") or ""),
                    "replyFocus": list(getattr(decision, "replyFocus", []) or []),
                    "profileScenario": str(getattr(decision, "profileScenario", "none") or "none"),
                    "profileChangeReplanDsl": profile_replan_source.profile_change_dsl,
                    "evidencePlan": profile_replan_source.evidence_plan,
                },
                "pendingType": None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "toolCallCount": 0,
                "totalDurationMs": total_duration_ms,
                "classificationDurationMs": classification_duration_ms,
                "preSemanticRouteDurationMs": pre_semantic_route_duration_ms,
                **_observability_timing_fields(request_context),
                "unattributedDurationMs": max(
                    0,
                    total_duration_ms - classification_duration_ms,
                ),
                "toolCalls": [],
                "postProcessingApplied": [routing_path],
                "status": "success",
                "errorType": None,
            }
            _log_conversation_turn_event(**turn_event)
            try:
                history_to_save = list(history or [])
                history_to_save.extend(
                    _append_turn_observability_messages(
                        new_messages,
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save profile change replan history: session_id=%s", session_id)
            return reply
        short_review_followup = (
            action_family == "review_plan"
            and bool(recent_plan_context)
            and len(str(content or "").strip()) <= 12
        )
        has_existing_plan_context = _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            None,
        )
        targeted_review = (
            action_family == "review_plan"
            and has_existing_plan_context
            and _semantic_targeted_review_allowed(decision)
        )
        promoted_review_query = (
            action_family == "review_plan"
            and has_existing_plan_context
            and semantic_promoted_query_state_to_review
        )
        current_state_query = (
            action_family == "query_state"
            and has_existing_plan_context
        )
        review_analysis_followup = (
            action_family == "analyze_adjustment"
            and bool(recent_plan_context)
            and isinstance(recent_plan_context.get("fixProposals"), dict)
        )
        current_plan_analysis = (
            action_family == "analyze_adjustment"
            and not recent_plan_context
            and has_existing_plan_context
            and _semantic_current_plan_analysis_allowed(decision)
            and _semantic_current_plan_analysis_matches_prompt(decision, content)
        )
        framework_review_or_repair_preview_route = (
            framework_review_or_repair_preview
            and has_existing_plan_context
            and action_family in {"review_plan", "analyze_adjustment"}
            and confidence >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
        )
        if framework_review_or_repair_preview_route and action_family == "analyze_adjustment":
            action_family = "review_plan"
        if (
            action_family != "preview_fix_proposal"
            and not framework_review_or_repair_preview_route
            and not review_analysis_followup
            and not current_plan_analysis
            and not current_state_query
            and not short_review_followup
            and not targeted_review
            and not promoted_review_query
        ) or confidence < _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD:
            return None
        needs_review_before_preview = False
        target_strategies = [
            str(strategy or "").strip()
            for strategy in list(getattr(decision, "targetStrategies", []) or [])
            if str(strategy or "").strip()
        ]
        target_issue_codes = [
            str(code or "").strip()
            for code in list(getattr(decision, "targetIssueCodes", []) or [])
            if str(code or "").strip()
        ]
        requested_reply_focus = [
            str(item or "").strip()
            for item in list(getattr(decision, "replyFocus", []) or [])
            if str(item or "").strip()
        ]
        use_target_scope_for_payload = (
            action_family != "review_plan"
            or targeted_review
            or framework_review_or_repair_preview_route
        )
        if action_family == "preview_fix_proposal":
            preview_allowed = _semantic_preview_fix_proposal_route_allowed(
                decision,
                recent_plan_context,
            )
            if not preview_allowed:
                has_existing_plan = _has_plan_semantic_route_context(
                    getattr(request_context, "planning_summary", None),
                    None,
                )
                if recent_plan_context or not has_existing_plan:
                    return None
                needs_review_before_preview = True

        if on_progress is not None:
            with contextlib.suppress(Exception):
                if action_family == "review_plan":
                    await on_progress("正在重新检查当前方案...")
                else:
                    await on_progress("正在根据当前方案提醒整理调整预览...")

        plan_payload = {
            "stage": "review" if action_family == "review_plan" else "apply",
            "action_family": action_family,
            "user_goal": content,
            "requires_confirmation": False,
        }
        if target_strategies and use_target_scope_for_payload:
            plan_payload["target_strategies"] = target_strategies
        if target_issue_codes and use_target_scope_for_payload:
            plan_payload["target_issue_codes"] = target_issue_codes
        if requested_reply_focus and use_target_scope_for_payload:
            plan_payload["reply_focus"] = requested_reply_focus
        if getattr(request_context, "planning_summary", None) is not None:
            try:
                plan_payload["planning_version"] = int(request_context.planning_summary.version or 0)
            except (TypeError, ValueError):
                pass

        tool_duration_ms = 0
        executed_tool_results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        needs_review_before_target_resolution = (
            action_family == "analyze_adjustment"
            and bool(target_strategies)
            and not target_issue_codes
            and not recent_plan_context
            and has_existing_plan_context
        )
        if needs_review_before_preview or needs_review_before_target_resolution:
            review_payload = {
                "stage": "review",
                "action_family": "review_plan",
                "user_goal": content,
                "requires_confirmation": False,
            }
            if target_strategies:
                review_payload["target_strategies"] = target_strategies
            if target_issue_codes:
                review_payload["target_issue_codes"] = target_issue_codes
            if requested_reply_focus:
                review_payload["reply_focus"] = requested_reply_focus
            if "planning_version" in plan_payload:
                review_payload["planning_version"] = plan_payload["planning_version"]
            review_result_text, review_result, review_duration_ms = await self._execute_semantic_plan_payload(
                request_context=request_context,
                plan_payload=review_payload,
            )
            tool_duration_ms += review_duration_ms
            executed_tool_results.append((review_result_text, review_result, review_payload))
            review_context = _latest_plan_semantic_route_context(
                [
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="execute_plan_action",
                                content=review_result_text,
                                tool_call_id="semantic-review-before-preview",
                            )
                        ]
                    )
                ]
            )
            if needs_review_before_preview and not _semantic_preview_fix_proposal_route_allowed(decision, review_context):
                return None
            if needs_review_before_target_resolution:
                inferred_issue_codes = await _infer_plan_target_issue_codes_from_context(
                    content=content,
                    request_context=request_context,
                    recent_plan_context=review_context,
                    expected_action_family=action_family,
                    target_strategies=target_strategies,
                )
                if inferred_issue_codes:
                    target_issue_codes = inferred_issue_codes
                    plan_payload["target_issue_codes"] = target_issue_codes
            recent_plan_context = review_context
        result_text, result, result_duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        tool_duration_ms += result_duration_ms
        executed_tool_results.append((result_text, result, plan_payload))
        llm_started_at = time.monotonic()
        synthesis_usage = None
        synthesis_applied = False
        if action_family in {"preview_fix_proposal", "analyze_adjustment", "review_plan"}:
            try:
                reply, synthesis_usage = await _synthesize_semantic_plan_action_reply(
                    self.llm_client,
                    user_prompt=content,
                    result=result,
                    recent_plan_context=recent_plan_context,
                )
                synthesis_applied = bool(reply)
            except Exception:
                logger.warning(
                    "Semantic plan action reply synthesis failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                reply = ""
        else:
            reply = ""
        llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
            reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply or "已查看当前方案的处理建议。"))
        elif _result_needs_unavailable_guidance_fallback(result, user_prompt=content):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        elif _review_reply_needs_structured_fallback(reply, result):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        elif _adjustment_reply_needs_structured_fallback(reply, result):
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or reply
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        if synthesis_usage is not None:
            tracker = self._usage_trackers.get(session_id)
            if tracker is None:
                tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
            with contextlib.suppress(Exception):
                tracker.record(synthesis_usage)
        model_name = "semantic-plan-action-synthesis" if synthesis_applied else "semantic-plan-action-fallback"
        if len(executed_tool_results) == 1:
            tool_call_id = f"semantic-{action_family}"
            new_messages = _build_direct_plan_action_messages(
                content,
                tool_call_id=tool_call_id,
                plan_payload=plan_payload,
                result_text=result_text,
                reply=reply,
                model_name=model_name,
            )
        else:
            tool_call_parts: list[ToolCallPart] = []
            tool_return_parts: list[ToolReturnPart] = []
            for index, (executed_result_text, _executed_result, executed_payload) in enumerate(executed_tool_results):
                tool_call_id = f"semantic-{str(executed_payload.get('action_family') or action_family)}-{index}"
                tool_call_parts.append(
                    ToolCallPart(
                        tool_name="execute_plan_action",
                        args={"plan_payload": json.dumps(executed_payload, ensure_ascii=False)},
                        tool_call_id=tool_call_id,
                    )
                )
                tool_return_parts.append(
                    ToolReturnPart(
                        tool_name="execute_plan_action",
                        content=executed_result_text,
                        tool_call_id=tool_call_id,
                    )
                )
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=tool_call_parts, model_name=model_name),
                ModelRequest(parts=tool_return_parts),
                ModelResponse(parts=[TextPart(content=reply)], model_name=model_name),
            ]

        compiled_fix_pending_card: WSResponse | None = None
        compiled_fix_workspace_refresh_targets: list[str] = []
        latest_plan_result = _latest_fix_proposal_confirmation_source(new_messages)
        if compiled_fix_pending_card is None and action_family == "preview_fix_proposal" and isinstance(latest_plan_result, dict):
            compiled_source = proposal_compiler.compile_runtime_review_fix_source(
                session_id=session_id,
                latest_plan_result=latest_plan_result,
                target_strategies=target_strategies,
                target_issue_codes=target_issue_codes,
            )
            ready_proposal = compiled_source.proposal
            if compiled_source.target_match_empty:
                latest_plan_result["target_match_empty"] = True
            if ready_proposal is not None and compiled_source.source_version_guard > 0:
                compiled_pending = await _create_runtime_compiled_review_fix_pending(
                    session_id,
                    ready_proposal,
                    source_version_guard=compiled_source.source_version_guard,
                    proposal_source=compiled_source.proposal_source,
                    compiled=compiled_source.compiled,
                )
                compiled_fix_pending_card = compiled_pending.card
                compiled_fix_workspace_refresh_targets = compiled_pending.workspace_refresh_targets
                if compiled_fix_pending_card is not None:
                    primary_reply = compiled_pending.primary_reply
                    if primary_reply:
                        _replace_text_reply(new_messages, reply, primary_reply)
                        reply = primary_reply
            elif latest_plan_result.get("target_match_empty"):
                targeted_unavailable_reply = _targeted_fix_proposal_unavailable_reply(
                    latest_plan_result,
                    target_strategies=compiled_source.selection.target_strategies,
                    target_issue_codes=compiled_source.selection.target_issue_codes,
                )
                if targeted_unavailable_reply:
                    _replace_text_reply(new_messages, reply, targeted_unavailable_reply)
                    reply = targeted_unavailable_reply

        if compiled_fix_pending_card is None:
            guarded_reply = _guard_plan_preview_reply_without_card(reply)
            if guarded_reply != reply:
                _replace_text_reply(new_messages, reply, guarded_reply)
                reply = guarded_reply

        action_family_result = str(result.get("action_family") or "preview_fix_proposal")
        observed_tool_calls = _summarize_tool_calls_for_observability(
            _iter_tool_call_parts(new_messages),
            _iter_tool_return_parts(new_messages),
        )
        display_source = proposal_compiler.compile_runtime_semantic_plan_display_source(
            action_family=action_family,
            result=result,
            pending_card_created=compiled_fix_pending_card is not None,
            prefer_conditional_options=framework_review_or_repair_preview_route,
        )
        display_payload = display_source.display_payload
        total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        unattributed_duration_ms = max(
            0,
            total_duration_ms
            - classification_duration_ms
            - tool_duration_ms
            - (llm_duration_ms if synthesis_applied else 0),
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": "semantic_plan_action",
                "routeDecision": {
                    "source": "semantic_plan_action",
                    "matched": True,
                    "confidence": confidence,
                    "route": action_family,
                    "originalRoute": original_action_family,
                    "sideEffect": (
                        "readonly_or_plan_preview"
                        if framework_review_or_repair_preview_route
                        else "readonly"
                    ),
                    "outputType": (
                        "readonly_or_plan_mutation"
                        if framework_review_or_repair_preview_route
                        else "readonly"
                    ),
                    "reason": str(getattr(decision, "reason", "") or ""),
                    "targetStrategies": list(getattr(decision, "targetStrategies", []) or []),
                    "targetIssueCodes": list(getattr(decision, "targetIssueCodes", []) or []),
                    "replyFocus": framework_reply_focus,
                    **({"turnDecision": framework_turn_decision} if framework_turn_decision else {}),
                    "recentPlanContext": recent_plan_context,
                    "displayPayload": display_payload,
                    "replyPlan": display_source.reply_plan,
                },
            "pendingType": None,
            "actionFamily": action_family_result,
            "replyFocus": framework_reply_focus,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(synthesis_usage, "requests", None),
            "inputTokens": getattr(synthesis_usage, "input_tokens", None),
            "outputTokens": getattr(synthesis_usage, "output_tokens", None),
            "totalTokens": getattr(synthesis_usage, "total_tokens", None),
            "toolCallCount": len(observed_tool_calls),
            "totalDurationMs": total_duration_ms,
            "llmDurationMs": llm_duration_ms if synthesis_applied else None,
            "toolDurationMs": tool_duration_ms,
            "classificationDurationMs": classification_duration_ms,
            "preSemanticRouteDurationMs": pre_semantic_route_duration_ms,
            **_observability_timing_fields(request_context),
            "unattributedDurationMs": unattributed_duration_ms,
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": [
                "semantic_plan_action",
                *(
                    ["semantic_query_state_promoted_to_review"]
                    if semantic_promoted_query_state_to_review
                    else []
                ),
                *(
                    ["turn_decision_review_repair_preview_reroute"]
                    if framework_review_or_repair_preview_route
                    else []
                ),
                "llm_reply_synthesis" if synthesis_applied else "fallback_reply",
            ],
            "status": "success" if result.get("result_kind") != "error" else "error",
            "errorType": result.get("result_kind") if result.get("result_kind") == "error" else None,
        }
        _log_conversation_turn_event(**turn_event)

        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save semantic plan action history: session_id=%s", session_id)

        followups: list[WSResponse] = []
        if compiled_fix_pending_card is not None:
            followups.append(compiled_fix_pending_card)
        workspace_refresh_targets = _dedupe_workspace_targets(
            [
                *compiled_fix_workspace_refresh_targets,
                *[str(target) for target in (result.get("workspace_refresh_targets") or [])],
            ]
        )
        workspace_presentation = proposal_compiler.compile_runtime_workspace_presentation_source(
            execute_plan_results=_execute_plan_action_results(new_messages),
            initial_refresh_targets=workspace_refresh_targets,
            allow_explanation_refresh=_semantic_query_state_should_run_review(content),
            conditional_review_requested=display_payload.get("presentation") == "conditional_options",
            include_call_fallback=False,
        )
        workspace_refresh_targets = _dedupe_workspace_targets(
            workspace_presentation.workspace_refresh_targets
        )
        followups.extend(
            _build_silent_workspace_refresh_response(session_id, target)
            for target in workspace_refresh_targets
        )
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def _maybe_handle_profile_replan_turn_decision(
        self,
        *,
        session_id: str,
        user_id: str,
        content: str,
        history: list[Any] | None,
        request_context: RequestContext,
        pending_state: dict[str, Any] | None,
        turn_started_at: float,
    ) -> str | None:
        if resolve_pending_confirmation(request_context) is not None:
            return None
        if not _has_plan_semantic_route_context(
            getattr(request_context, "planning_summary", None),
            None,
        ):
            return None
        decision = getattr(request_context, "_turn_decision_object", None)
        if decision is None:
            try:
                profile_change_replan_dsl = _latest_profile_change_replan_dsl(history)
                decision_payload = {
                    "planningStateProfile": _planning_state_profile_for_turn_decision(
                        planning_summary=getattr(request_context, "planning_summary", None),
                        pending_state=pending_state if isinstance(pending_state, dict) else None,
                        score_detail=getattr(request_context, "score_detail", None),
                    ),
                    "pendingState": pending_state if isinstance(pending_state, dict) else {},
                }
                if profile_change_replan_dsl is not None:
                    decision_payload["historyContext"] = [
                        {
                            "type": "profileChangeReplanDsl",
                            "value": profile_change_replan_dsl,
                        }
                    ]
                decision = await _classify_turn_decision_cached(
                    content,
                    request_context=request_context,
                    payload=decision_payload,
                )
            except Exception:
                logger.warning(
                    "Profile replan TurnDecision failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                return None
        if not _turn_decision_is_profile_replan(decision):
            return None
        _store_current_turn_decision(request_context, decision)
        profile_replan_source = _compile_profile_replan_from_decision(
            decision,
            request_context=request_context,
        )
        if not profile_replan_source.matched:
            return None
        reply = _build_profile_change_replan_reply(
            content,
            request_context=request_context,
            profile_change_dsl=profile_replan_source.profile_change_dsl,
        )
        routing_path = _profile_replan_routing_path(
            profile_replan_source,
            prefix="turn_decision",
        )
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=content)]),
            ModelResponse(parts=[TextPart(content=reply)], model_name=routing_path.replace("_", "-")),
        ]
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": "plan",
            "routingPath": routing_path,
            "routeDecision": {
                "source": "turn_decision+proposal_compiler",
                "matched": True,
                "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
                "taskLayer": str(getattr(decision, "taskLayer", "") or "").strip(),
                "sideEffect": profile_replan_source.side_effect,
                "scopeAnchor": "current_profile",
                "scenario": str(getattr(decision, "scenario", "") or "").strip(),
                "reason": str(getattr(decision, "reason", "") or ""),
                "profileScenario": str(getattr(decision, "profileScenario", "none") or "none"),
                "profileChangeReplanDsl": profile_replan_source.profile_change_dsl,
                "evidencePlan": profile_replan_source.evidence_plan,
            },
            "pendingType": None,
            "actionFamily": None,
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "toolCallCount": 0,
            "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
            "toolCalls": ["turn_decision"],
            "postProcessingApplied": [routing_path],
            "status": "success",
            "errorType": None,
        }
        _log_conversation_turn_event(**turn_event)
        try:
            history_to_save = list(history or [])
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save TurnDecision profile change replan history: session_id=%s", session_id)
        return reply

    async def _maybe_reroute_review_to_fix_preview(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _StructuredPlanRerouteResult | None:
        """Reroute a broad review result into a structured repair preview.

        The reroute is based on the current turn's structured review result plus
        the semantic action classifier. It does not infer intent from fixed user
        phrases.
        """

        if resolve_pending_confirmation(request_context) is not None:
            return None
        if _extract_plan_confirmation_candidate(tool_context_messages) is not None:
            return None
        current_plan_context = _latest_plan_semantic_route_context(tool_context_messages)
        if not _plan_context_has_fix_proposals(current_plan_context):
            current_plan_context = _latest_review_fix_proposal_route_context(tool_context_messages)
        if not current_plan_context:
            return None
        last_action_family = str(current_plan_context.get("lastActionFamily") or "").strip()
        last_result_kind = str(current_plan_context.get("lastResultKind") or "").strip()
        if last_action_family not in {"review_plan", "analyze_adjustment"}:
            return None
        if last_result_kind not in {"review_result", "adjustment_analysis"}:
            return None
        fix_facts = current_plan_context.get("fixProposals")
        if not isinstance(fix_facts, dict) or not isinstance(fix_facts.get("proposals"), list):
            return None
        if _prompt_asks_review_explanation_only(content):
            return None

        try:
            decision = await classify_plan_semantic_action(
                content,
                request_context=request_context,
                recent_plan_context=current_plan_context,
            )
        except Exception:
            logger.warning(
                "Post-review fix preview classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        planning_version = 0
        if getattr(request_context, "planning_summary", None) is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(request_context.planning_summary.version or 0)
        compiled_source = proposal_compiler.compile_runtime_review_to_fix_preview_source(
            content=content,
            current_plan_context=current_plan_context,
            decision=decision,
            planning_version=planning_version,
            confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
        )
        if not compiled_source.matched:
            return None
        plan_payload = compiled_source.plan_payload
        target_strategies = compiled_source.target_strategies
        target_issue_codes = compiled_source.target_issue_codes

        try:
            result_text = await execute_plan_action(
                SimpleNamespace(deps=request_context),
                json.dumps(plan_payload, ensure_ascii=False),
            )
            result = _parse_tool_return_json(result_text) or {}
        except Exception:
            logger.warning(
                "Post-review fix preview execution failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None

        facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
        selected_proposal = proposal_compiler.select_ready_fix_proposal_for_compiled_source(
            facts,
            target_strategies=target_strategies,
            target_issue_codes=target_issue_codes,
        )
        selected_proposal_id = ""
        if isinstance(selected_proposal, dict):
            selected_proposal_id = str(
                selected_proposal.get("proposal_id") or selected_proposal.get("proposalId") or ""
            ).strip()
        if selected_proposal_id and "selected_proposal_id" not in result and "selectedProposalId" not in result:
            result["selected_proposal_id"] = selected_proposal_id
            result_text = json.dumps(result, ensure_ascii=False, default=str)

        try:
            reply, _usage = await _synthesize_semantic_plan_action_reply(
                self.llm_client,
                user_prompt=content,
                result=result,
                recent_plan_context=current_plan_context,
            )
        except Exception:
            logger.warning(
                "Post-review fix preview reply synthesis failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            reply = ""
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
        if not reply:
            reply = "我已把可以处理的调整预览列出来，确认前不会改动当前方案。"
        result_updated = False
        if target_strategies and "target_strategies" not in result and "targetStrategies" not in result:
            result["target_strategies"] = target_strategies
            result_updated = True
        if target_issue_codes and "target_issue_codes" not in result and "targetIssueCodes" not in result:
            result["target_issue_codes"] = target_issue_codes
            result_updated = True
        if result_updated:
            result_text = json.dumps(result, ensure_ascii=False, default=str)
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=f"post-review-fix-preview-{uuid.uuid4().hex[:8]}",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="post-review-fix-preview",
        )
        return _StructuredPlanRerouteResult(
            reply=reply,
            messages=messages,
            route_decision={
                "source": "post_review_fix_preview",
                "matched": True,
                "confidence": compiled_source.confidence,
                "route": compiled_source.route or "post_review_fix_preview",
                "reason": str(getattr(decision, "reason", "") or ""),
                "targetStrategies": list(target_strategies),
                "targetIssueCodes": list(target_issue_codes),
            },
        )

    async def _maybe_refocus_broad_review_result(
        self,
        *,
        session_id: str,
        content: str,
        request_context: RequestContext,
        tool_context_messages: list[Any] | None,
    ) -> _StructuredPlanRerouteResult | None:
        """Re-run broad review with semantic target scope for narrow read-only questions."""

        if resolve_pending_confirmation(request_context) is not None:
            return None
        latest_review = _latest_review_plan_result(tool_context_messages)
        if not isinstance(latest_review, dict):
            return None
        if _prompt_asks_review_explanation_only(content):
            return None
        facts = latest_review.get("facts") if isinstance(latest_review.get("facts"), dict) else {}
        if facts.get("target_issue_codes") or facts.get("targetIssueCodes"):
            return None
        context = _latest_plan_semantic_route_context(tool_context_messages)
        try:
            decision = await classify_plan_semantic_action(
                content,
                request_context=request_context,
                recent_plan_context=context,
            )
        except Exception:
            logger.warning(
                "Review refocus classification failed: session_id=%s",
                session_id,
                exc_info=True,
            )
            return None
        planning_version = 0
        if getattr(request_context, "planning_summary", None) is not None:
            with contextlib.suppress(TypeError, ValueError):
                planning_version = int(request_context.planning_summary.version or 0)
        compiled_source = proposal_compiler.compile_runtime_review_refocus_source(
            content=content,
            latest_review_result=latest_review,
            recent_plan_context=context,
            decision=decision,
            planning_version=planning_version,
            confidence_threshold=_SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD,
        )
        if not compiled_source.matched:
            return None
        plan_payload = compiled_source.plan_payload
        target_issue_codes = compiled_source.target_issue_codes
        if on_progress := getattr(request_context, "progress_callback", None):
            with contextlib.suppress(Exception):
                await on_progress("正在按你关注的这类问题重新检查方案...")
        result_text, result, _duration_ms = await self._execute_semantic_plan_payload(
            request_context=request_context,
            plan_payload=plan_payload,
        )
        reply = ""
        try:
            reply, _usage = await _synthesize_semantic_plan_action_reply(
                self.llm_client,
                user_prompt=content,
                result=result,
                recent_plan_context=context,
            )
        except Exception:
            logger.warning(
                "Review refocus reply synthesis failed: session_id=%s",
                session_id,
                exc_info=True,
            )
        if not reply:
            reply = _build_plan_timeout_fallback_reply(result, user_prompt=content) or str(result.get("summary") or "").strip()
        if not reply:
            return None
        reply = _sanitize_reply_for_user(_normalize_user_facing_terms(reply))
        messages = _build_direct_plan_action_messages(
            content,
            tool_call_id=f"refocus-review-{uuid.uuid4().hex[:8]}",
            plan_payload=plan_payload,
            result_text=result_text,
            reply=reply,
            model_name="review-target-refocus",
        )
        return _StructuredPlanRerouteResult(
            reply=reply,
            messages=messages,
            route_decision={
                "source": "review_target_refocus",
                "matched": True,
                "confidence": compiled_source.confidence,
                "route": compiled_source.route or "review_target_refocus",
                "targetIssueCodes": target_issue_codes,
            },
        )

    # ── 消息处理 ──────────────────────────────────────────────────

    async def handle_message(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
        score_detail: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str | WSResponse | ChatServiceResponseEnvelope:
        """处理一条用户消息，返回 Agent 回复（str 或 WSResponse）。"""
        handle_started_at = time.monotonic()
        turn_started_at = handle_started_at
        context_progress_sent = False

        async def _timed_result(awaitable: Any) -> tuple[Any, int]:
            started_at = time.monotonic()
            try:
                result = await awaitable
            except Exception as exc:
                return exc, int((time.monotonic() - started_at) * 1000)
            return result, int((time.monotonic() - started_at) * 1000)

        async def emit_context_progress() -> None:
            nonlocal context_progress_sent
            if context_progress_sent or on_progress is None:
                return
            context_progress_sent = True
            await on_progress(self._EARLY_CONTEXT_PROGRESS_HINT)

        async def delayed_context_progress() -> None:
            if on_progress is None:
                return
            await asyncio.sleep(self._EARLY_CONTEXT_PROGRESS_DELAY_SECONDS)
            if context_progress_sent:
                return
            await emit_context_progress()

        context_progress_task: asyncio.Task[None] | None = None
        if on_progress is not None:
            context_progress_task = asyncio.create_task(delayed_context_progress())

        async def finish_context_progress() -> None:
            if context_progress_task is not None:
                context_progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await context_progress_task

        initial_state_load_started_at = time.monotonic()
        history_load_duration_ms: int | None = None
        pending_load_duration_ms: int | None = None
        history_task = asyncio.create_task(_timed_result(self.history_store.load(session_id)))
        pending_state_task = asyncio.create_task(_timed_result(_load_pending_confirmation_state(session_id)))
        try:
            history_result, backend_pending_result = await asyncio.gather(
                history_task,
                pending_state_task,
            )
            history, history_load_duration_ms = history_result
            backend_pending_state, pending_load_duration_ms = backend_pending_result
        except Exception:
            logger.exception("Failed to load chat history or pending state: session_id=%s", session_id)
            history = None
            backend_pending_state = None
        else:
            if isinstance(history, Exception):
                logger.exception("Failed to load chat history: session_id=%s", session_id)
                history = None
            if isinstance(backend_pending_state, Exception):
                logger.warning("Failed to load pending confirmation state: session_id=%s", session_id, exc_info=True)
                backend_pending_state = None
        initial_state_load_duration_ms = int((time.monotonic() - initial_state_load_started_at) * 1000)
        if isinstance(backend_pending_state, dict) and str(backend_pending_state.get("status") or "").strip() == "active":
            await finish_context_progress()

        logger.info(
            "ChatService handling message: session_id=%s user_id=%s content_len=%d history_len=%d",
            session_id, user_id, len(content),
            len(history) if history else 0,
        )
        clear_recent_plan_execution_result(session_id, content)

        past_turn_count = _count_user_turns(history)
        current_turn = past_turn_count + 1

        # 打印原始 history 内容，便于调试格式
        # if history:
        #     for i, msg in enumerate(history):
        #         logger.info("history[%d] type=%s", i, type(msg).__name__)
        #         #logger.info("history[%d] type=%s content=%s", i, type(msg).__name__, msg)

        runtime_history_build_started_at = time.monotonic()
        backend_pending = _pending_confirmation_from_state(backend_pending_state)
        runtime_history = build_runtime_history(
            history,
            latest_user_content=content,
            has_active_pending=backend_pending is not None,
            config=self.history_config,
        )
        chat_history = runtime_history.chat_history
        recent_intent_analysis = _extract_recent_intent_analysis_payload(runtime_history.model_history)
        if recent_intent_analysis is None:
            recent_intent_analysis = _extract_recent_intent_analysis_payload(history)
        runtime_history_build_duration_ms = int((time.monotonic() - runtime_history_build_started_at) * 1000)
        logger.info(
            "Runtime history prepared: session_id=%s full_len=%d runtime_len=%d full_chars=%d runtime_chars=%d dropped_tool_returns=%d has_pending=%s",
            session_id,
            runtime_history.full_len,
            runtime_history.runtime_len,
            runtime_history.full_text_chars,
            runtime_history.runtime_text_chars,
            runtime_history.dropped_tool_return_count,
            runtime_history.has_pending,
        )

        # 获取用户成绩详情
        parsed_score_detail = _coerce_score_detail(score_detail)
        parsed_init_profile = None
        parsed_planning_summary = None
        planning_data: dict[str, Any] | None = None
        score_response = None
        init_response = None
        planning_response = None
        backend_context_load_started_at = time.monotonic()
        context_load_tasks: list[asyncio.Task[Any]] = []
        if not score_detail:
            context_load_tasks.append(asyncio.create_task(get_user_score_detail(session_id)))
        context_load_tasks.extend(
            [
                asyncio.create_task(get_user_init_profile(session_id)),
                asyncio.create_task(get_planning_workspace_state(session_id)),
            ]
        )
        if context_load_tasks:
            results = await asyncio.gather(*context_load_tasks, return_exceptions=True)
            result_index = 0
            if not score_detail:
                score_response = results[result_index]
                result_index += 1
            init_response = results[result_index]
            planning_response = results[result_index + 1]
        backend_context_load_duration_ms = int((time.monotonic() - backend_context_load_started_at) * 1000)

        if not score_detail:
            if isinstance(score_response, Exception):
                logger.warning("Failed to fetch user score detail: %s", score_response)
            elif isinstance(score_response, dict) and score_response.get("code") == 0:
                raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                if raw_data:
                    parsed_score_detail = _parse_score_detail_from_backend(raw_data)
                    logger.info(
                        "Fetched score_detail: province=%s total_score=%d subjects=%s sex=%s",
                        parsed_score_detail.province,
                        parsed_score_detail.total_score,
                        parsed_score_detail.subject_list,
                        parsed_score_detail.sex,
                    )

        if isinstance(init_response, Exception):
            logger.warning("Failed to fetch user init profile: %s", init_response)
        elif isinstance(init_response, dict) and init_response.get("code") == 0:
            init_data = init_response.get("data", {}).get("userInitProfile", {})
            if init_data:
                parsed_init_profile = UserProfile.from_backend_format(init_data)
                logger.info(
                    "Fetched init_profile: strength_subjects=%s majors=%s neg_majors=%s provinces=%s",
                    parsed_init_profile.strength_subjects,
                    parsed_init_profile.major.level2,
                    parsed_init_profile.major.negative_level2,
                    parsed_init_profile.city.province,
                )

        if isinstance(planning_response, Exception):
            logger.warning("Failed to fetch planning state: %s", planning_response)
        elif isinstance(planning_response, dict) and planning_response.get("code") == 0:
            planning_data = planning_response.get("data", {})
            parsed_planning_summary = PlanningSummary.from_backend_state(planning_data)
            if parsed_planning_summary:
                logger.info(
                    "Fetched planning summary: phase=%s version=%s working_total=%s ordered_total=%s review_risk=%s",
                    parsed_planning_summary.phase,
                    parsed_planning_summary.version,
                    parsed_planning_summary.working_total,
                    parsed_planning_summary.ordered_total,
                    parsed_planning_summary.review_risk_count,
                )

        # 构建统一的 ConversationPhase
        request_context_build_started_at = time.monotonic()
        conversation_phase = ConversationPhase.from_pending_confirmation(
            backend_pending,
            planning_summary=parsed_planning_summary,
            turn_count=past_turn_count,
        )
        conversation_phase.turn_count = current_turn
        stale_pending_notice = ""
        state_sync = PlanningStateSync()
        version_result = state_sync.check_version(conversation_phase, parsed_planning_summary)
        if not version_result.is_current:
            logger.info(
                "Planning version drift at turn start: session_id=%s local=%s remote=%s drift=%s",
                session_id,
                version_result.local_version,
                version_result.remote_version,
                version_result.drift,
            )
        if conversation_phase.pending is not None and conversation_phase.pending.kind == "plan_mutation":
            stale_event = state_sync.invalidate_if_stale(
                conversation_phase,
                current_turn=current_turn,
                planning_summary=parsed_planning_summary,
            )
            if stale_event.should_clear_pending:
                logger.info(
                    "Clearing stale plan pending before model run: session_id=%s cause=%s message=%s",
                    session_id,
                    getattr(stale_event.cause, "value", None),
                    stale_event.message,
                )
                stale_pending_notice = stale_event.message or "上一轮方案预览已经失效。"
                await _expire_active_pending_confirmation_state(
                    session_id,
                    reason=str(getattr(stale_event.cause, "value", None) or "stale_pending"),
                )
                conversation_phase.clear_pending()
                backend_pending_state = None
                backend_pending = None

        # 创建 RequestContext
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=chat_history,
            batch=batch,
            score_detail=parsed_score_detail,
            init_profile=parsed_init_profile,
            planning_summary=parsed_planning_summary,
            sandbox=build_request_sandbox(
                session_id=session_id,
                batch=batch,
                score_detail=parsed_score_detail,
                init_profile=parsed_init_profile,
                planning_state=planning_data if isinstance(planning_data, dict) else None,
                planning_summary=parsed_planning_summary,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                pending=backend_pending,
            ),
            conversation_phase=conversation_phase,
            progress_callback=on_progress,
            allow_explore_inner_llm=False,
            enable_intent_side_effect_arbitration=True,
            recent_intent_analysis=recent_intent_analysis,
            latest_profile_change_replan_dsl=_latest_profile_change_replan_dsl(
                history if isinstance(history, list) else None
            ),
            stale_pending_notice=stale_pending_notice,
        )
        active_pending = resolve_pending_confirmation(request_context)
        active_pending_kind = str(getattr(active_pending, "kind", "") or "").strip()
        if request_context.sandbox is not None:
            await request_context.sandbox.warm(DEFAULT_WARM_PATHS)
        request_context_build_duration_ms = int((time.monotonic() - request_context_build_started_at) * 1000)
        await self._maybe_run_zhiyuan_agent_poc_shadow(
            session_id=session_id,
            user_id=user_id,
            content=content,
            request_context=request_context,
            message_history=runtime_history.model_history,
        )
        zhiyuan_agent_direct_reply = await self._maybe_handle_zhiyuan_agent_direct_route(
            session_id=session_id,
            user_id=user_id,
            content=content,
            history=history if isinstance(history, list) else None,
            request_context=request_context,
            message_history=runtime_history.model_history,
            turn_started_at=turn_started_at,
            on_progress=on_progress,
        )
        if zhiyuan_agent_direct_reply is not None:
            await finish_context_progress()
            return zhiyuan_agent_direct_reply
        guard_pipeline_started_at = time.monotonic()

        async def runtime_intent_profile_plan_reroute(
            profile: Any,
        ) -> ChatServiceResponseEnvelope | None:
            return await self._maybe_reroute_runtime_intent_profile_to_plan_response(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history if isinstance(history, list) else None,
                request_context=request_context,
                turn_started_at=turn_started_at,
                profile=profile,
            )

        profile_change_state_reply = await self._maybe_handle_profile_change_replan_state_query(
            session_id=session_id,
            user_id=user_id,
            content=content,
            history=history if isinstance(history, list) else None,
            request_context=request_context,
            pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
            turn_started_at=turn_started_at,
        )
        if profile_change_state_reply is not None:
            await finish_context_progress()
            return profile_change_state_reply

        backend_pending_id = str((backend_pending_state or {}).get("pendingId") or "").strip()
        backend_pending_kind = str((backend_pending_state or {}).get("kind") or "").strip()
        backend_pending_status = str((backend_pending_state or {}).get("status") or "").strip()
        runtime_intent_hard_cut_checked = False
        pending_turn_decision: Any | None = None
        if backend_pending_id and backend_pending_status == "active":
            pending_turn_resolution = proposal_compiler.resolve_pending_turn_action(
                content,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
            )
            if pending_turn_resolution.action == "reject_pending":
                reply = await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "cancel",
                            "kind": backend_pending_kind,
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                )
                await finish_context_progress()
                return reply
            if pending_turn_resolution.action == "confirm_pending":
                reply = await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": backend_pending_kind,
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                )
                await finish_context_progress()
                return reply

            pending_turn_decision = await _classify_active_pending_turn_decision(
                content=content,
                request_context=request_context,
                planning_summary=parsed_planning_summary,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                score_detail=parsed_score_detail,
            )
            if backend_pending_kind == "intent_change":
                runtime_intent_hard_cut_checked = True
                runtime_intent_hard_cut_reply = await _maybe_handle_runtime_intent_hard_cut(
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    history=history,
                    history_store=self.history_store,
                    request_context=request_context,
                    planning_summary=parsed_planning_summary,
                    pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                    score_detail=parsed_score_detail,
                    turn_started_at=turn_started_at,
                    turn_decision=pending_turn_decision,
                    current_plan_mutation_reroute=runtime_intent_profile_plan_reroute,
                )
                if runtime_intent_hard_cut_reply is not None:
                    await finish_context_progress()
                    return runtime_intent_hard_cut_reply

            structured_pending_resolution = proposal_compiler.compile_runtime_pending_turn_decision_source(
                content,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                turn_decision=pending_turn_decision,
            )
            if structured_pending_resolution.action == "apply_pending_then_readonly":
                reply = await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": backend_pending_kind,
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                    post_apply_intent="apply_pending_then_readonly",
                    post_apply_evidence_plan=structured_pending_resolution.post_apply_evidence_plan,
                )
                await finish_context_progress()
                return reply

            if structured_pending_resolution.action == "apply_pending_then_new_request":
                reply = await self.handle_pending_confirmation(
                    session_id,
                    user_id,
                    json.dumps(
                        {
                            "action": "confirm",
                            "kind": backend_pending_kind,
                            "pendingId": backend_pending_id,
                        },
                        ensure_ascii=False,
                    ),
                    confirmation_entry="short_text",
                    user_prompt_content=content,
                    post_apply_intent="apply_pending_then_new_request",
                )
                await finish_context_progress()
                return reply

            if structured_pending_resolution.action == "conflict_with_existing_pending":
                if on_progress is not None:
                    with contextlib.suppress(Exception):
                        await on_progress(self._INITIAL_PROGRESS_HINT)
                reply = _build_pending_conflict_new_request_reply(backend_pending_state or {})
                turn_decision_snapshot = _turn_decision_snapshot(pending_turn_decision)
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan" if backend_pending_kind == "plan_mutation" else "intent",
                    "routingPath": "pending_conflict_new_request_guard",
                    "routeDecision": {
                        "source": "proposal_compiler",
                        "matched": True,
                        "route": structured_pending_resolution.action,
                        "sideEffect": structured_pending_resolution.side_effect,
                        "turnDecision": turn_decision_snapshot,
                        "blockingReasons": list(structured_pending_resolution.blocking_reasons),
                    },
                    "pendingType": structured_pending_resolution.pending_type or None,
                    "actionFamily": str((backend_pending_state or {}).get("actionFamily") or "") or None,
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="pending-conflict-new-request-guard",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                await finish_context_progress()
                return reply

            if structured_pending_resolution.action == "ask_pending_impact":
                if on_progress is not None:
                    with contextlib.suppress(Exception):
                        await on_progress(self._INITIAL_PROGRESS_HINT)
                reply = _build_pending_readonly_impact_reply(backend_pending_state or {})
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan" if backend_pending_kind == "plan_mutation" else "intent",
                    "routingPath": "pending_readonly_impact",
                    "routeDecision": {
                        "source": "proposal_compiler",
                        "matched": True,
                        "route": structured_pending_resolution.action,
                        "sideEffect": structured_pending_resolution.side_effect,
                        "turnDecision": _turn_decision_snapshot(pending_turn_decision)
                        if pending_turn_decision is not None
                        else None,
                        "blockingReasons": list(structured_pending_resolution.blocking_reasons),
                    },
                    "pendingType": structured_pending_resolution.pending_type or None,
                    "actionFamily": str((backend_pending_state or {}).get("actionFamily") or "") or None,
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="pending-readonly-impact",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                await finish_context_progress()
                return reply

            pending_readonly_plan_query_reply = await self._maybe_handle_pending_readonly_plan_query(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history,
                request_context=request_context,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                turn_started_at=turn_started_at,
                turn_decision=pending_turn_decision,
            )
            if pending_readonly_plan_query_reply is not None:
                await finish_context_progress()
                return pending_readonly_plan_query_reply

            no_formal_plan_review = proposal_compiler.resolve_no_formal_plan_review_boundary(
                content,
                planning_summary=parsed_planning_summary,
            )
            if no_formal_plan_review.side_effect == "readonly":
                reply = _no_formal_plan_review_boundary_reply(
                    content,
                    pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                )
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan",
                    "routingPath": "no_formal_plan_review_boundary",
                    "routeDecision": {
                        "source": "proposal_compiler",
                        "matched": True,
                        "route": no_formal_plan_review.side_effect,
                        "sideEffect": no_formal_plan_review.side_effect,
                        "referenceResolution": no_formal_plan_review.reference_resolution,
                        "replyFocus": list(no_formal_plan_review.reply_focus),
                        "blockingReasons": list(no_formal_plan_review.blocking_reasons),
                    },
                    "pendingType": None,
                    "actionFamily": None,
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="no-formal-plan-review-boundary",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                await finish_context_progress()
                return reply

        if active_pending is None and _latest_turn_looks_readonly(history) and _is_readonly_closure_ack(content):
            reply = _readonly_closure_ack_reply()
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=content)]),
                ModelResponse(parts=[TextPart(content=reply)], model_name="direct-readonly-closure-ack"),
            ]
            try:
                history_to_save = list(history or [])
                history_to_save.extend(new_messages)
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save readonly closure ack history: session_id=%s", session_id)
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="explore",
                routingPath="readonly_closure_ack",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            await finish_context_progress()
            return reply

        if (
            active_pending is None
            and proposal_compiler.pending_turn_looks_no_active_pending_confirmation(content)
            and not _latest_turn_allows_plan_followup_confirmation(history)
        ):
            reply = _no_pending_confirmation_guard_reply()
            await _save_direct_guard_history(
                self.history_store,
                session_id,
                history,
                content,
                reply,
                model_name="no-pending-confirmation-guard",
                request_context=request_context,
                user_id=user_id,
            )
            _log_conversation_turn_event(
                sessionId=session_id,
                userId=user_id,
                scene="plan",
                routingPath="no_pending_confirmation_guard",
                pendingType=None,
                actionFamily=None,
                totalDurationMs=int((time.monotonic() - turn_started_at) * 1000),
                status="success",
                errorType=None,
            )
            await finish_context_progress()
            return reply

        if active_pending is None:
            no_formal_plan_review = proposal_compiler.resolve_no_formal_plan_review_boundary(
                content,
                planning_summary=parsed_planning_summary,
            )
            if no_formal_plan_review.side_effect == "readonly":
                reply = _no_formal_plan_review_boundary_reply(content)
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan",
                    "routingPath": "no_formal_plan_review_boundary",
                    "routeDecision": {
                        "source": "proposal_compiler",
                        "matched": True,
                        "route": no_formal_plan_review.side_effect,
                        "sideEffect": no_formal_plan_review.side_effect,
                        "referenceResolution": no_formal_plan_review.reference_resolution,
                        "replyFocus": list(no_formal_plan_review.reply_focus),
                        "blockingReasons": list(no_formal_plan_review.blocking_reasons),
                    },
                    "pendingType": None,
                    "actionFamily": None,
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="no-formal-plan-review-boundary",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                await finish_context_progress()
                return reply

            needs_plan_first_resolution = proposal_compiler.resolve_needs_plan_first_guard(
                content,
                planning_summary=parsed_planning_summary,
                recent_intent_summary=_recent_intent_summary_for_no_plan_guard(
                    backend_pending_state if isinstance(backend_pending_state, dict) else None,
                    recent_intent_analysis if isinstance(recent_intent_analysis, dict) else None,
                ),
            )
            if needs_plan_first_resolution.side_effect == "needs_plan_first":
                reply = _needs_plan_first_guard_reply(content, needs_plan_first_resolution)
                turn_event = {
                    "sessionId": session_id,
                    "userId": user_id,
                    "scene": "plan",
                    "routingPath": "needs_plan_first_guard",
                    "routeDecision": {
                        "source": "proposal_compiler",
                        "matched": True,
                        "route": needs_plan_first_resolution.side_effect,
                        "referenceResolution": needs_plan_first_resolution.reference_resolution,
                        "targetIssues": list(needs_plan_first_resolution.target_issues),
                        "displayPayload": dict(needs_plan_first_resolution.display_payload),
                        "replyPlan": dict(needs_plan_first_resolution.reply_plan),
                        "blockingReasons": list(needs_plan_first_resolution.blocking_reasons),
                    },
                    "pendingType": None,
                    "actionFamily": None,
                    "totalDurationMs": int((time.monotonic() - turn_started_at) * 1000),
                    "status": "success",
                    "errorType": None,
                }
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    history,
                    content,
                    reply,
                    model_name="needs-plan-first-guard",
                    turn_event=turn_event,
                    request_context=request_context,
                    user_id=user_id,
                )
                _log_conversation_turn_event(**turn_event)
                await finish_context_progress()
                return reply

            if active_pending is None or active_pending_kind == "intent_change":
                runtime_intent_hard_cut_reply = await _maybe_handle_runtime_intent_hard_cut(
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    history=history,
                    history_store=self.history_store,
                    request_context=request_context,
                    planning_summary=parsed_planning_summary,
                    pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                    score_detail=parsed_score_detail,
                    turn_started_at=turn_started_at,
                    current_plan_mutation_reroute=runtime_intent_profile_plan_reroute,
                )
                if runtime_intent_hard_cut_reply is not None:
                    await finish_context_progress()
                    return runtime_intent_hard_cut_reply

            profile_replan_turn_reply = await self._maybe_handle_profile_replan_turn_decision(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history,
                request_context=request_context,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                turn_started_at=turn_started_at,
            )
            if profile_replan_turn_reply is not None:
                await finish_context_progress()
                return profile_replan_turn_reply

            if (
                int(getattr(parsed_planning_summary, "ordered_total", 0) or 0) > 0
                or int(getattr(parsed_planning_summary, "working_total", 0) or 0) > 0
            ):
                direct_atomic_plan_action_reply = await self._maybe_handle_direct_atomic_plan_action(
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    history=history,
                    request_context=request_context,
                    turn_started_at=turn_started_at,
                )
                if direct_atomic_plan_action_reply is not None:
                    await finish_context_progress()
                    return direct_atomic_plan_action_reply
                direct_plan_slice_reply = await self._maybe_handle_direct_readonly_plan_slice_query(
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    history=history,
                    request_context=request_context,
                    turn_started_at=turn_started_at,
                )
                if direct_plan_slice_reply is not None:
                    await finish_context_progress()
                    return direct_plan_slice_reply
                direct_local_plan_action_reply = await self._maybe_handle_direct_local_plan_action(
                    session_id=session_id,
                    user_id=user_id,
                    content=content,
                    history=history,
                    request_context=request_context,
                    turn_started_at=turn_started_at,
                )
                if direct_local_plan_action_reply is not None:
                    await finish_context_progress()
                    return direct_local_plan_action_reply

        if (
            active_pending is not None
            and active_pending_kind == "intent_change"
            and not runtime_intent_hard_cut_checked
        ):
            runtime_intent_hard_cut_reply = await _maybe_handle_runtime_intent_hard_cut(
                session_id=session_id,
                user_id=user_id,
                content=content,
                history=history,
                history_store=self.history_store,
                request_context=request_context,
                planning_summary=parsed_planning_summary,
                pending_state=backend_pending_state if isinstance(backend_pending_state, dict) else None,
                score_detail=parsed_score_detail,
                turn_started_at=turn_started_at,
                current_plan_mutation_reroute=runtime_intent_profile_plan_reroute,
            )
            if runtime_intent_hard_cut_reply is not None:
                await finish_context_progress()
                return runtime_intent_hard_cut_reply

        semantic_plan_action_reply = await self._maybe_handle_semantic_plan_action(
            session_id=session_id,
            user_id=user_id,
            content=content,
            history=history,
            request_context=request_context,
            turn_started_at=turn_started_at,
            on_progress=on_progress,
        )
        if semantic_plan_action_reply is not None:
            await finish_context_progress()
            return semantic_plan_action_reply

        progress_sent = False
        tool_progress_sent = False
        last_progress_at: float | None = None

        async def emit_progress(hint: str, *, is_tool_progress: bool = False) -> None:
            nonlocal progress_sent, tool_progress_sent, last_progress_at
            progress_sent = True
            if is_tool_progress:
                tool_progress_sent = True
            last_progress_at = time.monotonic()
            if on_progress is not None:
                await on_progress(hint)

        async def progress_wrapper(hint: str) -> None:
            await emit_progress(hint, is_tool_progress=True)

        async def delayed_initial_progress() -> None:
            if on_progress is None:
                return
            await asyncio.sleep(self._INITIAL_PROGRESS_DELAY_SECONDS)
            if progress_sent:
                return
            await emit_progress(self._INITIAL_PROGRESS_HINT)

        progress_started_at = time.monotonic()

        async def delayed_long_progress() -> None:
            if on_progress is None:
                return
            model_wait_hints = dict(self._LONG_PROGRESS_MODEL_WAIT_HINTS)
            tool_hints = dict(self._LONG_PROGRESS_TOOL_HINTS)
            delay_points = sorted(set(model_wait_hints) | set(tool_hints))
            for delay_seconds in delay_points:
                wait_seconds = max(0.0, progress_started_at + delay_seconds - time.monotonic())
                await asyncio.sleep(wait_seconds)
                now = time.monotonic()
                if (
                    last_progress_at is not None
                    and now - last_progress_at < self._MIN_PROGRESS_INTERVAL_SECONDS
                ):
                    continue
                hint = (
                    tool_hints.get(delay_seconds)
                    if tool_progress_sent
                    else model_wait_hints.get(delay_seconds)
                )
                if not hint:
                    continue
                await emit_progress(hint)

        initial_progress_task: asyncio.Task[None] | None = None
        long_progress_task: asyncio.Task[None] | None = None
        if on_progress is not None:
            initial_progress_task = asyncio.create_task(delayed_initial_progress())
            long_progress_task = asyncio.create_task(delayed_long_progress())

        llm_started_at = time.monotonic()
        pre_full_agent_duration_ms = int((llm_started_at - handle_started_at) * 1000)
        guard_pipeline_duration_ms = int((llm_started_at - guard_pipeline_started_at) * 1000)
        try:
            reply, new_messages, all_messages, usage = await self.agent.run_with_message_deltas(
                user_prompt=content,
                message_history=runtime_history.model_history,
                deps=request_context,
                on_progress=progress_wrapper if on_progress is not None else None,
            )
        except BaseException as exc:
            llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
            total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            turn_event = {
                "sessionId": session_id,
                "userId": user_id,
                "scene": "unknown",
                "routingPath": "full_agent",
                "routeDecision": {
                    "source": "full_agent",
                    "matched": False,
                    "confidence": "model",
                    "route": "unknown",
                    "fallbackReason": "agent_run_interrupted",
                    "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
                },
                "pendingType": "plan" if active_pending_kind == "plan_mutation" else "intent" if active_pending_kind == "intent_change" else None,
                "actionFamily": None,
                "modelProvider": _llm_config_value(self.llm_client, "provider"),
                "modelName": _llm_config_value(self.llm_client, "model_name"),
                "llmRequests": None,
                "inputTokens": None,
                "outputTokens": None,
                "totalTokens": None,
                "toolCallCount": None,
                "totalDurationMs": total_duration_ms,
                "llmDurationMs": llm_duration_ms,
                "toolDurationMs": None,
                "preFullAgentDurationMs": pre_full_agent_duration_ms,
                "historyLoadDurationMs": history_load_duration_ms,
                "pendingLoadDurationMs": pending_load_duration_ms,
                "initialStateLoadDurationMs": initial_state_load_duration_ms,
                "runtimeHistoryBuildDurationMs": runtime_history_build_duration_ms,
                "backendContextLoadDurationMs": backend_context_load_duration_ms,
                "requestContextBuildDurationMs": request_context_build_duration_ms,
                "guardPipelineDurationMs": guard_pipeline_duration_ms,
                **_observability_timing_fields(request_context),
                "postFullAgentDurationMs": max(
                    0,
                    total_duration_ms - pre_full_agent_duration_ms - llm_duration_ms,
                ),
                "unattributedDurationMs": max(0, total_duration_ms - llm_duration_ms),
                "toolCalls": [],
                "postProcessingApplied": [],
                "status": status,
                "errorType": type(exc).__name__,
            }
            _log_conversation_turn_event(**turn_event)
            with contextlib.suppress(Exception, asyncio.CancelledError):
                failed_history = list(history or [])
                failed_history.extend(
                    _append_turn_observability_messages(
                        [ModelRequest(parts=[UserPromptPart(content=content)])],
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
                await self.history_store.save(session_id, failed_history)
            recent_plan_fallback = None
            if not isinstance(exc, asyncio.CancelledError):
                with contextlib.suppress(Exception):
                    recent_plan_fallback = await build_interruption_fallback_from_recent_plan_execution(
                        session_id,
                        content,
                    )
            recent_intent_payload = None
            if not isinstance(exc, asyncio.CancelledError):
                recent_intent_payload = (
                    request_context.agent_observability.get("latestIntentPreviewPayload")
                    if isinstance(request_context.agent_observability, dict)
                    else None
                )
            interruption_blocks_intent_pending = _turn_decision_blocks_full_agent_intent_pending(
                getattr(request_context, "_turn_decision_object", None)
            )
            if isinstance(recent_intent_payload, dict) and not interruption_blocks_intent_pending:
                interruption_pending_result: _RuntimeCompiledPendingResult | None = None
                with contextlib.suppress(Exception):
                    interruption_pending_result = await _create_pending_intent_confirmation_result_from_preview_payload(
                        session_id,
                        recent_intent_payload,
                    )
                interruption_intent_card = (
                    interruption_pending_result.card
                    if isinstance(interruption_pending_result, _RuntimeCompiledPendingResult)
                    else None
                )
                if interruption_intent_card is not None:
                    primary_text = (
                        _pending_confirmation_primary_reply_from_card(interruption_intent_card)
                        or _intent_card_primary_reply_from_preview_payload(recent_intent_payload)
                    )
                    recovery_messages = [
                        ModelRequest(parts=[UserPromptPart(content=content)]),
                        ModelResponse(
                            parts=[TextPart(content=primary_text)],
                            model_name="agent-interruption-intent-preview-result",
                        ),
                    ]
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await self.history_store.save(
                            session_id,
                            list(history or [])
                            + _append_turn_observability_messages(
                                recovery_messages,
                                turn_event,
                                request_context=request_context,
                                session_id=session_id,
                                user_id=user_id,
                                prompt_length=len(content or ""),
                            ),
                        )
                    if context_progress_task is not None:
                        context_progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await context_progress_task
                    recovery_followups = [
                        _build_silent_workspace_refresh_response(session_id, target)
                        for target in (
                            interruption_pending_result.workspace_refresh_targets
                            if isinstance(interruption_pending_result, _RuntimeCompiledPendingResult)
                            else []
                        )
                    ]
                    recovery_followups.append(interruption_intent_card)
                    return ChatServiceResponseEnvelope(primary=primary_text, followups=recovery_followups)
                if _intent_preview_missing_required_constraint_scope(recent_intent_payload):
                    primary_text = _intent_preview_incomplete_constraint_reply(recent_intent_payload)
                    recovery_messages = [
                        ModelRequest(parts=[UserPromptPart(content=content)]),
                        ModelResponse(
                            parts=[TextPart(content=primary_text)],
                            model_name="agent-interruption-intent-preview-guard",
                        ),
                    ]
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await self.history_store.save(
                            session_id,
                            list(history or [])
                            + _append_turn_observability_messages(
                                recovery_messages,
                                turn_event,
                                request_context=request_context,
                                session_id=session_id,
                                user_id=user_id,
                                prompt_length=len(content or ""),
                            ),
                        )
                    if context_progress_task is not None:
                        context_progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await context_progress_task
                    return primary_text
            if recent_plan_fallback is not None:
                recovery_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(
                        parts=[TextPart(content=recent_plan_fallback.primary)],
                        model_name="agent-interruption-plan-preview-recovery",
                    ),
                ]
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await self.history_store.save(
                        session_id,
                        list(history or [])
                        + _append_turn_observability_messages(
                            recovery_messages,
                            turn_event,
                            request_context=request_context,
                            session_id=session_id,
                            user_id=user_id,
                            prompt_length=len(content or ""),
                        ),
                    )
                if context_progress_task is not None:
                    context_progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await context_progress_task
                return recent_plan_fallback
            fallback_reply = _build_agent_interruption_fallback_reply(
                content,
                parsed_planning_summary,
                request_context.agent_observability,
                batch=batch,
            )
            if fallback_reply and not isinstance(exc, asyncio.CancelledError):
                fallback_model_name = (
                    "agent-interruption-readonly-fallback"
                    if _agent_interruption_looks_readonly(content, request_context.agent_observability)
                    else "agent-interruption-fallback"
                )
                fallback_messages = [
                    ModelRequest(parts=[UserPromptPart(content=content)]),
                    ModelResponse(parts=[TextPart(content=fallback_reply)], model_name=fallback_model_name),
                ]
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await self.history_store.save(
                        session_id,
                        list(history or [])
                        + _append_turn_observability_messages(
                            fallback_messages,
                            turn_event,
                            request_context=request_context,
                            session_id=session_id,
                            user_id=user_id,
                            prompt_length=len(content or ""),
                        ),
                    )
                if context_progress_task is not None:
                    context_progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await context_progress_task
                return fallback_reply
            raise
        finally:
            for progress_task in (initial_progress_task, long_progress_task):
                if progress_task is not None:
                    progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
            if context_progress_task is not None:
                context_progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await context_progress_task
        llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)

        # ── Token usage 追踪 ──────────────────────────────────────
        tracker = self._usage_trackers.get(session_id)
        if tracker is None:
            tracker = UsageTracker(session_id=session_id)
            self._usage_trackers[session_id] = tracker
        tracker.record(usage)

        logger.info(
            "Token usage [turn]: session_id=%s input=%d output=%d total=%d requests=%d tools=%d",
            session_id, usage.input_tokens, usage.output_tokens,
            usage.total_tokens, usage.requests, usage.tool_calls,
        )
        if tracker.turn_count % self._LOG_INTERVAL == 0:
            logger.info("Token usage [session cumulative]: %s", tracker.summary())

        tool_context_messages = _select_current_tool_context_messages(
            new_messages,
            all_messages,
            runtime_history,
        )

        plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)

        intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
        intent_preview_used = intent_preview_used_current_turn
        intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
        intent_side_effect_decision = request_context.agent_observability.get("intentSideEffectDecision")
        intent_interest_stage_result = _tool_returns_interest_stage_intent_analysis(tool_context_messages)
        semantic_intent_readonly_suggested = _semantic_intent_decision_suggests_readonly(
            intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None
        )
        semantic_intent_readonly_honored = _semantic_intent_decision_requires_readonly(
            intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None
        )
        readonly_interest_analysis_used = bool(
            semantic_intent_readonly_suggested
            and not intent_preview_used_current_turn
            and _tool_calls_are_readonly_explore_or_compare(tool_context_messages)
        )
        has_readonly_explore_result = _turn_has_readonly_explore_result(tool_context_messages)
        intent_preview_downgraded = (
            intent_interest_stage_result
            or semantic_intent_readonly_honored
            or readonly_interest_analysis_used
        )
        if intent_preview_downgraded and getattr(request_context, "conversation_phase", None) is not None:
            request_context.conversation_phase.clear_pending()
            active_pending_kind = ""
        readonly_prompt = _prompt_explicitly_readonly(content)
        readonly_policy_prompt = _prompt_requires_readonly_policy_answer(content)
        negative_plan_ack = _prompt_rejects_current_plan_action(content)
        if readonly_policy_prompt:
            readonly_prompt = True
        readonly_mutation_preview_guarded = False
        if (readonly_prompt or negative_plan_ack) and _tool_returns_mutating_plan_preview(tool_context_messages):
            _remove_current_turn_mutating_plan_preview(new_messages)
            _remove_current_turn_mutating_plan_preview(all_messages)
            if isinstance(reply, str) and _reply_has_plan_confirmation_request(reply):
                guarded_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                if not guarded_reply or _reply_has_plan_confirmation_request(guarded_reply):
                    guarded_reply = _READONLY_MUTATION_GUARD_REPLY
                else:
                    compact_guarded = _compact_plan_reply_text(guarded_reply)
                    if not any(
                        marker in compact_guarded
                        for marker in (
                            "不会加入、删除、移动或重排方案",
                            "不会改动当前方案",
                            "不会直接改",
                            "不直接改",
                        )
                    ):
                        guarded_reply = f"{guarded_reply.rstrip()}\n\n{_READONLY_MUTATION_GUARD_REPLY}"
                _replace_text_reply(new_messages, reply, guarded_reply)
                _replace_text_reply(all_messages, reply, guarded_reply)
                reply = guarded_reply
            readonly_mutation_preview_guarded = True
        if (
            (plan_chain_used or _should_guard_plan_reply(content))
            and isinstance(reply, str)
            and _plan_reply_needs_normalization(reply)
        ):
            normalized_reply = _normalize_plan_reply_style(reply)
            _replace_text_reply(new_messages, reply, normalized_reply)
            _replace_text_reply(all_messages, reply, normalized_reply)
            reply = normalized_reply

        if plan_chain_used and isinstance(reply, str) and not readonly_mutation_preview_guarded:
            bounded_reply = _append_plan_preview_confirmation_boundary(reply, tool_context_messages)
            if bounded_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_reply)
                _replace_text_reply(all_messages, reply, bounded_reply)
                reply = bounded_reply

        if intent_preview_used and not intent_preview_downgraded and isinstance(reply, str):
            pending_intent_reply = _normalize_pending_intent_reply(reply)
            if pending_intent_reply != reply:
                _replace_text_reply(new_messages, reply, pending_intent_reply)
                _replace_text_reply(all_messages, reply, pending_intent_reply)
                reply = pending_intent_reply

        if intent_preview_downgraded and isinstance(reply, str):
            readonly_downgrade_reply = (
                _latest_readonly_explore_reply(tool_context_messages)
                if semantic_intent_readonly_honored or readonly_interest_analysis_used
                else None
            )
            downgraded_intent_reply = _normalize_downgraded_intent_preview_reply(
                readonly_downgrade_reply or reply
            )
            downgraded_intent_reply = _append_downgraded_intent_focus_summary(
                downgraded_intent_reply,
                intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None,
            )
            if downgraded_intent_reply != reply:
                _replace_text_reply(new_messages, reply, downgraded_intent_reply)
                _replace_text_reply(all_messages, reply, downgraded_intent_reply)
                reply = downgraded_intent_reply

        if isinstance(reply, str):
            false_apology_reply = _normalize_false_apology_reply(reply, history)
            if false_apology_reply != reply:
                _replace_text_reply(new_messages, reply, false_apology_reply)
                _replace_text_reply(all_messages, reply, false_apology_reply)
                reply = false_apology_reply

        if isinstance(reply, str):
            protocol_reply = _normalize_general_confirmation_protocol_wording(reply)
            if protocol_reply != reply:
                _replace_text_reply(new_messages, reply, protocol_reply)
                _replace_text_reply(all_messages, reply, protocol_reply)
                reply = protocol_reply

        if isinstance(reply, str):
            user_facing_reply = _normalize_user_facing_terms(reply)
            if user_facing_reply != reply:
                _replace_text_reply(new_messages, reply, user_facing_reply)
                _replace_text_reply(all_messages, reply, user_facing_reply)
                reply = user_facing_reply

        latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
        has_pending_intent_context = (intent_preview_used and not intent_preview_downgraded) or (
            active_pending_kind == "intent_change"
            and not latest_turn_readonly
            and not plan_chain_used
            and _is_pending_intent_followup_turn(content, reply)
        )
        if readonly_policy_prompt and intent_preview_used_current_turn:
            intent_preview_downgraded = True
            has_pending_intent_context = False
            if getattr(request_context, "conversation_phase", None) is not None:
                request_context.conversation_phase.clear_pending()
                active_pending_kind = ""
        if isinstance(reply, str) and (_reply_is_existing_only_intent_notice(reply) or intent_non_pending):
            has_pending_intent_context = False
        semantic_intent_preview_requested = _semantic_decision_requests_intent_preview(
            intent_side_effect_decision if isinstance(intent_side_effect_decision, dict) else None
        )
        allow_unbacked_intent_recovery = _tool_calls_allow_unbacked_intent_recovery(
            tool_context_messages,
            semantic_intent_preview=semantic_intent_preview_requested,
        )
        if isinstance(reply, str) and not intent_preview_used and not has_pending_intent_context and allow_unbacked_intent_recovery:
            unbacked_intent_reply = _normalize_unbacked_intent_preview_reply(reply)
            if unbacked_intent_reply != reply:
                _replace_text_reply(new_messages, reply, unbacked_intent_reply)
                _replace_text_reply(all_messages, reply, unbacked_intent_reply)
                reply = unbacked_intent_reply
            unbacked_recorded_reply = _normalize_unbacked_recorded_wording(reply)
            if unbacked_recorded_reply != reply:
                _replace_text_reply(new_messages, reply, unbacked_recorded_reply)
                _replace_text_reply(all_messages, reply, unbacked_recorded_reply)
                reply = unbacked_recorded_reply

        if isinstance(reply, str) and has_pending_intent_context and not intent_non_pending:
            bounded_intent_reply = _append_pending_intent_boundary(
                reply,
                has_pending_intent=has_pending_intent_context,
            )
            if bounded_intent_reply != reply:
                _replace_text_reply(new_messages, reply, bounded_intent_reply)
                _replace_text_reply(all_messages, reply, bounded_intent_reply)
                reply = bounded_intent_reply

        if isinstance(reply, str) and _reply_contains_readonly_plan_query_facts(reply):
            compact_query_reply = _compact_readonly_plan_query_reply(reply)
            if compact_query_reply and compact_query_reply != reply:
                _replace_text_reply(new_messages, reply, compact_query_reply)
                _replace_text_reply(all_messages, reply, compact_query_reply)
                reply = compact_query_reply

        workspace_refresh_targets = _current_turn_workspace_refresh_targets(
            tool_context_messages=tool_context_messages,
            new_messages=new_messages,
            all_messages=all_messages,
            content=content,
        )
        if negative_plan_ack:
            workspace_refresh_targets = []
        # Intent preview only prepares a pending preference/constraint. Do not
        # refresh the workspace until the user confirms or explicitly selects
        # the intent card; otherwise the UI looks as if an unconfirmed intent
        # has already changed candidate results.

        workspace_view_targets = _current_turn_workspace_view_targets(
            tool_context_messages=tool_context_messages,
            all_messages=all_messages,
            content=content,
            turn_decision=getattr(request_context, "_turn_decision_object", None),
        )
        if negative_plan_ack:
            workspace_view_targets = []
        tool_calls = _iter_tool_call_parts(tool_context_messages)
        tool_returns = _iter_tool_return_parts(tool_context_messages)
        called_tool_names = [part.tool_name for part in tool_calls]
        observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
        full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
        if any(name in {"collect_plan_context_inputs", "plan_next_action", "execute_plan_action", "query_volunteer_plan"} for name in called_tool_names):
            scene = "plan"
        elif any("intent" in name for name in called_tool_names):
            scene = "intent"
        elif any(name.startswith("analyze_current_") for name in called_tool_names):
            scene = "explore"
        else:
            scene = "unknown"
        action_family = _select_conversation_action_family(tool_returns)
        pending_intent_card: WSResponse | None = None
        compiled_plan_pending_card: WSResponse | None = None
        plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
        structured_plan_reroute: dict[str, Any] | None = None
        compiled_plan_includes_intent_update = False
        compiled_fix_pending_card: WSResponse | None = None
        compiled_pending_workspace_refresh_targets: list[str] = []
        turn_decision_object = getattr(request_context, "_turn_decision_object", None)
        missing_turn_decision_blocks_intent_pending = (
            turn_decision_object is None
            and proposal_compiler.full_agent_intent_pending_requires_turn_decision(
                getattr(request_context, "planning_summary", None)
            )
        )
        turn_decision_blocks_intent_pending = (
            missing_turn_decision_blocks_intent_pending
            or _turn_decision_blocks_full_agent_intent_pending(turn_decision_object)
        )
        full_agent_intent_pending_blocked = False
        full_agent_intent_pending_turn_decision_override = False
        profile_change_replan_result = _latest_profile_change_replan_result(tool_context_messages)
        profile_change_replan_source = _compile_profile_replan_from_payload(
            profile_change_replan_result,
            request_context=request_context,
        )
        if (
            profile_change_replan_result is not None
            and isinstance(reply, str)
            and profile_change_replan_source.matched
            and profile_change_replan_source.side_effect == "profile_change_replan"
        ):
            profile_change_reply = _build_profile_change_replan_reply(
                content,
                request_context=request_context,
                profile_change_dsl=profile_change_replan_source.profile_change_dsl,
            )
            _replace_text_reply(new_messages, reply, profile_change_reply)
            _replace_text_reply(all_messages, reply, profile_change_reply)
            reply = profile_change_reply
        elif (
            plan_confirmation_candidate is None
            and isinstance(reply, str)
            and _latest_empty_status_overview_result(tool_context_messages) is not None
        ):
            try:
                profile_change_decision = await classify_plan_semantic_action(
                    content,
                    request_context=request_context,
                    recent_plan_context=_latest_plan_semantic_route_context(tool_context_messages),
                )
            except Exception:
                logger.warning(
                    "Profile change replan post-query classification failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                profile_change_decision = None
            if (
                profile_change_decision is not None
                and float(getattr(profile_change_decision, "confidence", 0.0) or 0.0)
                >= _SEMANTIC_PLAN_ACTION_CONFIDENCE_THRESHOLD
                and _semantic_decision_is_current_student_profile_replan(profile_change_decision)
            ):
                profile_change_source = _compile_profile_replan_from_decision(
                    profile_change_decision,
                    request_context=request_context,
                )
                if not (
                    profile_change_source.matched
                    and profile_change_source.side_effect == "profile_change_replan"
                ):
                    profile_change_source = None
                if profile_change_source is not None:
                    profile_change_reply = _build_profile_change_replan_reply(
                        content,
                        request_context=request_context,
                        profile_change_dsl=profile_change_source.profile_change_dsl,
                    )
                    _replace_text_reply(new_messages, reply, profile_change_reply)
                    _replace_text_reply(all_messages, reply, profile_change_reply)
                    reply = profile_change_reply
        if (
            pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
            and not plan_chain_used
            and not intent_preview_used
            and not intent_preview_downgraded
            and not readonly_interest_analysis_used
            and not readonly_prompt
            and resolve_pending_confirmation(request_context) is None
        ):
            confirmable_interest_payload = _extract_confirmable_intent_payload_from_interest_tool(
                tool_context_messages
            )
            if confirmable_interest_payload is not None:
                confirmable_interest_payload = _align_intent_preview_payload_with_semantic_decision(
                    session_id=session_id,
                    payload=confirmable_interest_payload,
                    semantic_decision=(
                        intent_side_effect_decision
                        if isinstance(intent_side_effect_decision, dict)
                        else None
                    ),
                    observability=request_context.agent_observability
                    if isinstance(request_context.agent_observability, dict)
                    else None,
                )
                interest_arbitration = _compile_full_agent_intent_preview_turn_decision_arbitration(
                    turn_decision=turn_decision_object,
                    semantic_decision=(
                        intent_side_effect_decision
                        if isinstance(intent_side_effect_decision, dict)
                        else None
                    ),
                    preview_payload=confirmable_interest_payload,
                )
                interest_turn_decision_override = bool(interest_arbitration.allow_intent_pending)
                if interest_turn_decision_override:
                    full_agent_intent_pending_turn_decision_override = True
                    if isinstance(request_context.agent_observability, dict):
                        request_context.agent_observability["intentPreviewTurnDecisionArbitration"] = (
                            interest_arbitration.arbitration_dsl
                        )
                effective_turn_decision_blocks_interest = (
                    turn_decision_blocks_intent_pending and not interest_turn_decision_override
                )
                if effective_turn_decision_blocks_interest:
                    intent_preview_downgraded = True
                    has_pending_intent_context = False
                    full_agent_intent_pending_blocked = True
                    blocked_reply = _blocked_intent_preview_for_plan_route_reply(
                        turn_decision_object,
                        confirmable_interest_payload,
                    )
                    _replace_text_reply(new_messages, reply, blocked_reply)
                    _replace_text_reply(all_messages, reply, blocked_reply)
                    reply = blocked_reply
                if not effective_turn_decision_blocks_interest:
                    pending_result = await _create_pending_intent_confirmation_result_from_preview_payload(
                        session_id,
                        confirmable_interest_payload,
                    )
                    pending_intent_card = pending_result.card
                    compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                        [
                            *compiled_pending_workspace_refresh_targets,
                            *pending_result.workspace_refresh_targets,
                        ]
                    )
                    if pending_intent_card is not None:
                        pending_intent_reply = _pending_confirmation_primary_reply_from_card(
                            pending_intent_card
                        )
                        if pending_intent_reply:
                            _replace_text_reply(new_messages, reply, pending_intent_reply)
                            _replace_text_reply(all_messages, reply, pending_intent_reply)
                            reply = pending_intent_reply
        goal_scoped_plan_preview = _latest_goal_scoped_plan_preview(tool_context_messages)
        structured_goal_clarification_reply = _structured_goal_clarification_reply(goal_scoped_plan_preview)
        if structured_goal_clarification_reply and plan_confirmation_candidate is None:
            if isinstance(reply, str):
                clean_clarification_reply = _sanitize_reply_for_user(
                    structured_goal_clarification_reply
                )
                _replace_text_reply(new_messages, reply, clean_clarification_reply)
                _replace_text_reply(all_messages, reply, clean_clarification_reply)
                reply = clean_clarification_reply
        if (
            pending_intent_card is None
            and plan_confirmation_candidate is None
            and isinstance(reply, str)
        ):
            guarded_reply = _guard_unbacked_plan_confirmation_reply(reply)
            if guarded_reply != reply:
                if intent_interest_stage_result and not plan_chain_used:
                    stripped_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                    if stripped_reply and not _reply_has_plan_confirmation_request(stripped_reply):
                        guarded_reply = stripped_reply
                        compact_guarded = _compact_plan_reply_text(guarded_reply)
                        if "不会改动当前方案" not in compact_guarded and "不会直接改" not in compact_guarded:
                            guarded_reply = f"{guarded_reply.rstrip()}\n\n{_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY}"
                    else:
                        explore_reply = _latest_readonly_explore_reply(tool_context_messages)
                        if explore_reply:
                            compact_explore = _compact_plan_reply_text(explore_reply)
                            guarded_reply = explore_reply
                            if "不会改动当前方案" not in compact_explore and "不会直接改" not in compact_explore:
                                guarded_reply = f"{guarded_reply.rstrip()}\n\n{_READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY}"
                        else:
                            guarded_reply = _READONLY_ANALYSIS_NO_PLAN_PREVIEW_REPLY
                else:
                    readonly_plan_result = _latest_readonly_plan_execution_result(tool_context_messages)
                    if has_readonly_explore_result:
                        readonly_plan_result = None
                    if readonly_plan_result is None:
                        readonly_plan_result = _latest_fix_proposal_preview_result(tool_context_messages)
                    if readonly_plan_result is not None:
                        guarded_reply = _build_plan_timeout_fallback_reply(
                            readonly_plan_result,
                            user_prompt=content,
                        ) or guarded_reply
                    else:
                        readonly_tool_reply = _latest_readonly_tool_reply(tool_context_messages)
                        if readonly_tool_reply:
                            stripped_reply = _remove_unbacked_plan_confirmation_copy(reply).strip()
                            if (
                                stripped_reply
                                and not _reply_has_plan_confirmation_request(stripped_reply)
                                and _reply_contains_readonly_plan_query_facts(stripped_reply)
                            ):
                                guarded_reply = stripped_reply
                            elif not stripped_reply:
                                guarded_reply = readonly_tool_reply
                            else:
                                guarded_reply = stripped_reply
                _replace_text_reply(new_messages, reply, guarded_reply)
                _replace_text_reply(all_messages, reply, guarded_reply)
                reply = guarded_reply
        if (
            plan_confirmation_candidate is None
            and isinstance(reply, str)
            and active_pending_kind in {"intent_change", "plan_mutation"}
            and _reply_looks_like_unbacked_plan_action_boundary(reply)
            and not list(_iter_tool_call_parts(tool_context_messages))
            and isinstance(backend_pending_state, dict)
            and backend_pending_state
        ):
            pending_context_reply = _build_pending_readonly_impact_reply(backend_pending_state)
            if active_pending_kind == "intent_change":
                pending_context_reply = (
                    pending_context_reply.rstrip()
                    + "\n\n如果这就是你想采用的方向，请先点“采纳”；采纳后我再按这条参考检查或调整当前方案。"
                )
            _replace_text_reply(new_messages, reply, pending_context_reply)
            _replace_text_reply(all_messages, reply, pending_context_reply)
            reply = pending_context_reply
        candidate_pool_missing_info_boundary_applied = False
        if (
            structured_plan_reroute is None
            and plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
            and plan_chain_used
            and not readonly_prompt
            and not negative_plan_ack
            and not intent_preview_downgraded
        ):
            rerouted_plan_action = await self._maybe_refocus_broad_review_result(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if rerouted_plan_action is not None:
                reply = rerouted_plan_action.reply
                new_messages = rerouted_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _current_turn_workspace_view_targets(
                    tool_context_messages=tool_context_messages,
                    all_messages=all_messages,
                    content=content,
                    turn_decision=turn_decision_object,
                )
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                structured_plan_reroute = rerouted_plan_action.route_decision
        if (
            plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
            and plan_chain_used
        ):
            missing_plan_next_payload = _latest_plan_next_missing_inputs_payload(
                tool_context_messages,
            )
            if missing_plan_next_payload is not None:
                missing_plan_result = {
                    "applied": False,
                    "action_family": missing_plan_next_payload.get("action_family"),
                    "stage": missing_plan_next_payload.get("stage"),
                    "result_kind": "error",
                    "missing_inputs": missing_plan_next_payload.get("missing_inputs") or [],
                    "atomic_actions": missing_plan_next_payload.get("atomic_actions") or [],
                    "summary": missing_plan_next_payload.get("summary")
                    or missing_plan_next_payload.get("preview_summary")
                    or "",
                    "reply_focus": [
                        "missing_inputs",
                        *[
                            "needs_candidate_selection"
                            for item in (missing_plan_next_payload.get("missing_inputs") or [])
                            if str(item or "").strip() == "selection_scope"
                        ],
                    ],
                }
                conditional_candidate_boundary = proposal_compiler.resolve_conditional_candidate_readonly_boundary(
                    result=missing_plan_result
                )
                if conditional_candidate_boundary.matched:
                    missing_plan_reply = _conditional_candidate_readonly_boundary_reply(
                        content,
                        reason_code=conditional_candidate_boundary.reason_code,
                        missing_inputs=conditional_candidate_boundary.missing_inputs,
                    )
                else:
                    missing_plan_reply = _non_actionable_plan_preview_boundary(
                        missing_plan_result
                    )
                _replace_text_reply(new_messages, reply, missing_plan_reply)
                _replace_text_reply(all_messages, reply, missing_plan_reply)
                reply = missing_plan_reply
        if (
            structured_plan_reroute is None
            and plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
            and plan_chain_used
            and (
                _turn_decision_is_candidate_pool_readonly_query(turn_decision_object)
                or _turn_decision_is_candidate_pool_readonly_query(
                    request_context.agent_observability.get("turnDecision")
                    if isinstance(request_context.agent_observability, dict)
                    else None
                )
                or _prompt_looks_like_candidate_pool_query(content)
            )
        ):
            candidate_missing_payload = _latest_plan_next_missing_inputs_payload(
                tool_context_messages,
                action_family="generate_plan",
            )
            latest_plan_result = _latest_execute_plan_action_result(tool_context_messages)
            latest_action_family = str((latest_plan_result or {}).get("action_family") or "").strip()
            latest_result_kind = str((latest_plan_result or {}).get("result_kind") or "").strip()
            latest_reply_focus = [
                str(item or "").strip()
                for item in (
                    (latest_plan_result or {}).get("reply_focus")
                    or (latest_plan_result or {}).get("replyFocus")
                    or []
                )
                if str(item or "").strip()
            ]
            if candidate_missing_payload is not None or (
                latest_action_family in {"generate_plan", "query_candidates", "query_state"}
                and (
                    latest_result_kind == "error"
                    or "missing_inputs" in latest_reply_focus
                )
            ):
                raw_missing_inputs = (
                    candidate_missing_payload.get("missing_inputs")
                    if isinstance(candidate_missing_payload, dict)
                    else (latest_plan_result or {}).get("missing_inputs")
                    or (latest_plan_result or {}).get("missingInputs")
                    or []
                )
                candidate_missing_reply = _candidate_pool_missing_info_reply(
                    content,
                    missing_inputs=[
                        str(item or "").strip()
                        for item in raw_missing_inputs
                        if str(item or "").strip()
                    ],
                )
                _replace_text_reply(new_messages, reply, candidate_missing_reply)
                _replace_text_reply(all_messages, reply, candidate_missing_reply)
                reply = candidate_missing_reply
                candidate_pool_missing_info_boundary_applied = True
        if (
            structured_plan_reroute is None
            and plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and isinstance(reply, str)
            and intent_preview_used_current_turn
            and not intent_preview_downgraded
            and _latest_existing_only_intent_payload(tool_context_messages) is not None
            and not _has_plan_semantic_route_context(
                getattr(request_context, "planning_summary", None),
                _latest_plan_semantic_route_context(getattr(request_context, "chat_history", None)),
            )
        ):
            no_plan_reply = _build_existing_only_no_plan_reply(
                _latest_existing_only_intent_payload(tool_context_messages)
            )
            _replace_text_reply(new_messages, reply, no_plan_reply)
            _replace_text_reply(all_messages, reply, no_plan_reply)
            reply = no_plan_reply
        if (
            structured_plan_reroute is None
            and plan_confirmation_candidate is None
            and not intent_preview_downgraded
        ):
            rerouted_plan_action = await self._maybe_reroute_review_to_fix_preview(
                session_id=session_id,
                content=content,
                request_context=request_context,
                tool_context_messages=tool_context_messages,
            )
            if rerouted_plan_action is not None:
                reply = rerouted_plan_action.reply
                new_messages = rerouted_plan_action.messages
                all_messages = list(runtime_history.model_history or []) + list(new_messages)
                tool_context_messages = _select_current_tool_context_messages(
                    new_messages,
                    all_messages,
                    runtime_history,
                )
                plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                intent_preview_used = intent_preview_used_current_turn
                intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                has_pending_intent_context = False
                workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                    tool_context_messages=tool_context_messages,
                    new_messages=new_messages,
                    all_messages=all_messages,
                    content=content,
                )
                workspace_view_targets = _current_turn_workspace_view_targets(
                    tool_context_messages=tool_context_messages,
                    all_messages=all_messages,
                    content=content,
                    turn_decision=turn_decision_object,
                )
                if negative_plan_ack:
                    workspace_refresh_targets = []
                    workspace_view_targets = []
                tool_calls = _iter_tool_call_parts(tool_context_messages)
                tool_returns = _iter_tool_return_parts(tool_context_messages)
                called_tool_names = [part.tool_name for part in tool_calls]
                observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                scene = "plan"
                action_family = _select_conversation_action_family(tool_returns)
                plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                structured_plan_reroute = rerouted_plan_action.route_decision
        if plan_confirmation_candidate is None and not structured_goal_clarification_reply and not intent_preview_downgraded:
            if compiled_fix_pending_card is None and pending_intent_card is None:
                latest_plan_result = _latest_fix_proposal_confirmation_source(tool_context_messages)
                if latest_plan_result is None:
                    preview_result = _latest_fix_proposal_preview_result(tool_context_messages)
                    if isinstance(preview_result, dict):
                        latest_plan_result = preview_result
                if isinstance(latest_plan_result, dict):
                    target_strategies, target_issue_codes, target_scope_explicit = await _infer_fix_proposal_target_scope(
                        content=content,
                        request_context=request_context,
                        latest_plan_result=latest_plan_result,
                    )
                    compiled_source = proposal_compiler.compile_runtime_review_fix_source(
                        session_id=session_id,
                        latest_plan_result=latest_plan_result,
                        target_strategies=target_strategies,
                        target_issue_codes=target_issue_codes,
                        target_scope_explicit=target_scope_explicit,
                    )
                    ready_proposal = compiled_source.proposal
                    if compiled_source.target_match_empty:
                        latest_plan_result["target_match_empty"] = True
                    if ready_proposal is not None:
                        latest_plan_result["selected_proposal_id"] = (
                            compiled_source.selection.selected_proposal_id
                            or proposal_compiler.proposal_id(ready_proposal)
                        )
                    if ready_proposal is not None and compiled_source.source_version_guard > 0:
                        compiled_pending = await _create_runtime_compiled_review_fix_pending(
                            session_id,
                            ready_proposal,
                            source_version_guard=compiled_source.source_version_guard,
                            proposal_source=compiled_source.proposal_source,
                            compiled=compiled_source.compiled,
                        )
                        compiled_fix_pending_card = compiled_pending.card
                        compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                            [
                                *compiled_pending_workspace_refresh_targets,
                                *compiled_pending.workspace_refresh_targets,
                            ]
                        )
                        if compiled_fix_pending_card is not None and isinstance(reply, str):
                            primary_fix_reply = compiled_pending.primary_reply
                            if primary_fix_reply:
                                _replace_text_reply(new_messages, reply, primary_fix_reply)
                                _replace_text_reply(all_messages, reply, primary_fix_reply)
                                reply = primary_fix_reply
                    elif (
                        compiled_fix_pending_card is None
                        and latest_plan_result.get("target_match_empty")
                        and isinstance(reply, str)
                    ):
                        targeted_unavailable_reply = _targeted_fix_proposal_unavailable_reply(
                            latest_plan_result,
                            target_strategies=compiled_source.selection.target_strategies,
                            target_issue_codes=compiled_source.selection.target_issue_codes,
                        )
                        if targeted_unavailable_reply:
                            _replace_text_reply(new_messages, reply, targeted_unavailable_reply)
                            _replace_text_reply(all_messages, reply, targeted_unavailable_reply)
                            reply = targeted_unavailable_reply
                    elif compiled_fix_pending_card is None:
                        clarification_reply = _structured_goal_clarification_reply(latest_plan_result)
                        if clarification_reply:
                            reply = _sanitize_reply_for_user(clarification_reply)
        if (
            plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and not structured_goal_clarification_reply
            and not intent_preview_downgraded
        ):
            structured_goal_preview = _latest_structured_goal_plan_preview(tool_context_messages)
            structured_source = goal_scoped_plan_preview or structured_goal_preview
            structured_attempt = _UserGoalFixConfirmationAttempt()
            structured_fix_candidate = await _structured_user_goal_fix_candidate_from_source(
                session_id,
                structured_source,
                context_source="plan_next_action_structured_goal",
                attempt=structured_attempt,
            )
            if structured_fix_candidate is not None:
                compiled_pending = await _create_pending_fix_confirmation_result_from_user_goal_candidate(
                    session_id,
                    structured_fix_candidate,
                    attempt=structured_attempt,
                )
                compiled_fix_pending_card = compiled_pending.card
                compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                    [
                        *compiled_pending_workspace_refresh_targets,
                        *compiled_pending.workspace_refresh_targets,
                    ]
                )
            elif structured_attempt.blocked_by_compiled_contract:
                compiled_fix_pending_card = None
            elif structured_attempt.fallback_to_intent:
                structured_intent_candidate = await _structured_goal_intent_candidate_from_source(
                    session_id,
                    structured_source,
                    fallback_mechanism_line=structured_attempt.fallback_mechanism_line,
                    fallback_detail_lines=structured_attempt.fallback_detail_lines,
                )
                if structured_intent_candidate is not None:
                    pending_intent_card = await _create_pending_intent_confirmation_from_structured_goal_candidate(
                        session_id,
                        structured_intent_candidate,
                    )
                    pending_intent_reply = _intent_card_primary_reply_from_card(
                        pending_intent_card
                    )
                    if pending_intent_reply and isinstance(reply, str):
                        _replace_text_reply(new_messages, reply, pending_intent_reply)
                        _replace_text_reply(all_messages, reply, pending_intent_reply)
                        reply = pending_intent_reply
            if compiled_fix_pending_card is not None and isinstance(reply, str):
                preview_payload = _parse_tool_return_json(
                    getattr(compiled_fix_pending_card, "content", "") or ""
                )
                primary_structured_goal_reply = ""
                if isinstance(preview_payload, dict):
                    card_summary = str(preview_payload.get("summary") or "").strip()
                    card_content = str(preview_payload.get("content") or "").strip()
                    preview_lines = ["已列出这次调整预览。"]
                    if card_summary:
                        preview_lines.extend(["", card_summary])
                    elif card_content:
                        preview_lines.extend(["", card_content])
                    preview_lines.extend(
                        [
                            "",
                            "具体调整内容在下面卡片里。确认前不会改动当前方案；点“确认执行”后，我会按这条建议处理，并重新刷新方案和审查结果。",
                        ]
                    )
                    primary_structured_goal_reply = _sanitize_reply_for_user("\n".join(preview_lines))
                    if primary_structured_goal_reply:
                        _replace_text_reply(new_messages, reply, primary_structured_goal_reply)
                        _replace_text_reply(all_messages, reply, primary_structured_goal_reply)
                        reply = primary_structured_goal_reply
        if (
            plan_confirmation_candidate
            and _plain_plan_candidate_conflicts_with_active_only_keep_intent(
                backend_pending_state if isinstance(backend_pending_state, dict) else None,
                plan_confirmation_candidate,
            )
        ):
            plan_confirmation_candidate = None
            pending_context_reply = _build_pending_readonly_impact_reply(
                backend_pending_state if isinstance(backend_pending_state, dict) else {}
            )
            if isinstance(reply, str):
                guarded_pending_reply = (
                    pending_context_reply.rstrip()
                    + "\n\n如果这就是你想采用的方向，请先点“采纳”；采纳后我再按这条参考检查或调整当前方案。"
                )
                guarded_pending_reply = _sanitize_reply_for_user(guarded_pending_reply)
                _replace_text_reply(new_messages, reply, guarded_pending_reply)
                _replace_text_reply(all_messages, reply, guarded_pending_reply)
                reply = guarded_pending_reply
        if plan_confirmation_candidate and intent_preview_downgraded:
            plan_confirmation_candidate = None
        if plan_confirmation_candidate:
            compiled_plan_proposal = _runtime_plan_compiled_proposal_from_candidate(
                session_id=session_id,
                confirmation_candidate=plan_confirmation_candidate,
                source="main_plan_confirmation_candidate",
            )
            compiled_pending = await _create_runtime_compiled_plan_pending(
                session_id,
                plan_confirmation_candidate,
                source="main_plan_confirmation_candidate",
                compiled=compiled_plan_proposal,
            )
            compiled_plan_pending_card = compiled_pending.card
            compiled_plan_includes_intent_update = compiled_pending.plan_includes_intent_update
            compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                [
                    *compiled_pending_workspace_refresh_targets,
                    *compiled_pending.workspace_refresh_targets,
                ]
            )
            if compiled_plan_pending_card is not None and isinstance(reply, str):
                primary_preview_reply = compiled_pending.primary_reply
                _replace_text_reply(new_messages, reply, primary_preview_reply)
                _replace_text_reply(all_messages, reply, primary_preview_reply)
                reply = primary_preview_reply
        if (
            intent_preview_used_current_turn
            and not intent_preview_downgraded
            and not compiled_plan_includes_intent_update
            and turn_decision_blocks_intent_pending
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
        ):
            preview_payload_for_plan = _extract_recent_intent_analysis_payload(tool_context_messages)
            if not preview_payload_for_plan and not plan_chain_used:
                preview_payload_for_plan = _extract_recent_intent_analysis_payload(all_messages)
            aligned_preview_payload_for_plan = _align_intent_preview_payload_with_semantic_decision(
                session_id=session_id,
                payload=preview_payload_for_plan,
                semantic_decision=(
                    intent_side_effect_decision
                    if isinstance(intent_side_effect_decision, dict)
                    else None
                ),
                observability=request_context.agent_observability
                if isinstance(request_context.agent_observability, dict)
                else None,
            )
            preview_arbitration = _compile_full_agent_intent_preview_turn_decision_arbitration(
                turn_decision=turn_decision_object,
                semantic_decision=(
                    intent_side_effect_decision
                    if isinstance(intent_side_effect_decision, dict)
                    else None
                ),
                preview_payload=aligned_preview_payload_for_plan,
            )
            if preview_arbitration.allow_intent_pending:
                full_agent_intent_pending_turn_decision_override = True
                if isinstance(request_context.agent_observability, dict):
                    request_context.agent_observability["intentPreviewTurnDecisionArbitration"] = (
                        preview_arbitration.arbitration_dsl
                    )
            else:
                intent_plan_reroute = await self._maybe_create_current_plan_mutation_preview_from_intent_payload(
                    session_id=session_id,
                    content=content,
                    request_context=request_context,
                    preview_payload=aligned_preview_payload_for_plan,
                )
                if intent_plan_reroute is not None:
                    reply = intent_plan_reroute.reply
                    new_messages = intent_plan_reroute.messages
                    all_messages = list(runtime_history.model_history or []) + list(new_messages)
                    tool_context_messages = _select_current_tool_context_messages(
                        new_messages,
                        all_messages,
                        runtime_history,
                    )
                    plan_chain_used = _tool_calls_include_plan_chain(tool_context_messages)
                    intent_preview_used_current_turn = _tool_calls_include_intent_preview(tool_context_messages)
                    intent_preview_used = intent_preview_used_current_turn
                    intent_non_pending = _tool_returns_intent_non_pending(tool_context_messages)
                    latest_turn_readonly = _latest_turn_looks_readonly(tool_context_messages)
                    has_pending_intent_context = False
                    workspace_refresh_targets = _current_turn_workspace_refresh_targets(
                        tool_context_messages=tool_context_messages,
                        new_messages=new_messages,
                        all_messages=all_messages,
                        content=content,
                    )
                    workspace_view_targets = _current_turn_workspace_view_targets(
                        tool_context_messages=tool_context_messages,
                        all_messages=all_messages,
                        content=content,
                        turn_decision=turn_decision_object,
                    )
                    tool_calls = _iter_tool_call_parts(tool_context_messages)
                    tool_returns = _iter_tool_return_parts(tool_context_messages)
                    called_tool_names = [part.tool_name for part in tool_calls]
                    observed_tool_calls = _summarize_tool_calls_for_observability(tool_calls, tool_returns)
                    full_agent_tool_trial = _summarize_full_agent_tool_trial(called_tool_names)
                    scene = "plan"
                    action_family = _select_conversation_action_family(tool_returns)
                    plan_confirmation_candidate = _extract_plan_confirmation_candidate(tool_context_messages)
                    structured_plan_reroute = intent_plan_reroute.route_decision
                    full_agent_intent_pending_blocked = True
                    compiled_plan_pending_card = (
                        intent_plan_reroute.pending_result.card
                        if intent_plan_reroute.pending_result is not None
                        else None
                    )
                    compiled_plan_includes_intent_update = bool(
                        intent_plan_reroute.pending_result.plan_includes_intent_update
                        if intent_plan_reroute.pending_result is not None
                        else False
                    )
                    compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                        [
                            *compiled_pending_workspace_refresh_targets,
                            *intent_plan_reroute.workspace_refresh_targets,
                        ]
                    )
                    if compiled_plan_pending_card is not None:
                        plan_confirmation_candidate = None
                else:
                    intent_preview_downgraded = True
                    has_pending_intent_context = False
                    full_agent_intent_pending_blocked = True
                    blocked_reply = _blocked_intent_preview_for_plan_route_reply(
                        turn_decision_object,
                        aligned_preview_payload_for_plan,
                    )
                    _replace_text_reply(new_messages, reply, blocked_reply)
                    _replace_text_reply(all_messages, reply, blocked_reply)
                    reply = blocked_reply
        if intent_preview_used_current_turn and not intent_preview_downgraded and not compiled_plan_includes_intent_update:
            preview_payload = _extract_recent_intent_analysis_payload(tool_context_messages)
            if not preview_payload and not plan_chain_used:
                preview_payload = _extract_recent_intent_analysis_payload(all_messages)
            preview_payload = _align_intent_preview_payload_with_semantic_decision(
                session_id=session_id,
                payload=preview_payload,
                semantic_decision=(
                    intent_side_effect_decision
                    if isinstance(intent_side_effect_decision, dict)
                    else None
                ),
                observability=request_context.agent_observability
                if isinstance(request_context.agent_observability, dict)
                else None,
            )
            if compiled_fix_pending_card is None and pending_intent_card is None:
                pending_result = await _create_pending_intent_confirmation_result_from_preview_payload(
                    session_id,
                    preview_payload,
                )
                pending_intent_card = pending_result.card
                compiled_pending_workspace_refresh_targets = _dedupe_workspace_targets(
                    [
                        *compiled_pending_workspace_refresh_targets,
                        *pending_result.workspace_refresh_targets,
                    ]
                )
            if pending_intent_card is not None and isinstance(reply, str):
                primary_text = _pending_confirmation_primary_reply_from_card(pending_intent_card)
                if not primary_text:
                    primary_text = _intent_card_primary_reply_from_preview_payload(preview_payload)
                _replace_text_reply(new_messages, reply, "")
                _replace_text_reply(all_messages, reply, "")
                reply = primary_text
            elif (
                pending_intent_card is None
                and isinstance(reply, str)
                and _intent_preview_missing_required_constraint_scope(preview_payload)
            ):
                fallback_reply = _intent_preview_incomplete_constraint_reply(preview_payload)
                _replace_text_reply(new_messages, reply, fallback_reply)
                _replace_text_reply(all_messages, reply, fallback_reply)
                reply = fallback_reply
        if isinstance(reply, str) and readonly_policy_prompt:
            readonly_policy_reply = _readonly_policy_fallback_reply_for_prompt(
                content,
                reply,
                tool_context_messages,
            )
            if readonly_policy_reply:
                readonly_policy_reply = _sanitize_reply_for_user(readonly_policy_reply)
                _replace_text_reply(new_messages, reply, readonly_policy_reply)
                _replace_text_reply(all_messages, reply, readonly_policy_reply)
                reply = readonly_policy_reply
                pending_intent_card = None
                compiled_plan_pending_card = None
                compiled_fix_pending_card = None
                plan_confirmation_candidate = None
                structured_plan_reroute = None
                workspace_refresh_targets = []
        non_actionable_plan_preview_boundary_applied = False
        if (
            plan_confirmation_candidate is None
            and compiled_plan_pending_card is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
            and plan_chain_used
            and not readonly_prompt
            and not negative_plan_ack
            and not intent_preview_downgraded
            and not candidate_pool_missing_info_boundary_applied
        ):
            non_actionable_mutation_result = _latest_non_actionable_plan_mutation_result(
                tool_context_messages
            )
            latest_plan_execution_result = _latest_execute_plan_action_result(tool_context_messages)
            latest_action_family = str(
                (latest_plan_execution_result or {}).get("action_family") or ""
            ).strip()
            latest_result_kind = str(
                (latest_plan_execution_result or {}).get("result_kind") or ""
            ).strip()
            latest_result_is_readonly_query = (
                (latest_action_family, latest_result_kind)
                in {
                    ("query_state", "status_overview"),
                    ("query_ordered", "ordered_snapshot"),
                    ("query_candidates", "candidate_snapshot"),
                }
            )
            if non_actionable_mutation_result is not None and (
                latest_result_is_readonly_query
                or _plan_execution_result_is_non_actionable(latest_plan_execution_result)
            ):
                conditional_candidate_boundary = proposal_compiler.resolve_conditional_candidate_readonly_boundary(
                    result=non_actionable_mutation_result
                )
                if conditional_candidate_boundary.matched:
                    boundary_reply = _conditional_candidate_readonly_boundary_reply(
                        content,
                        reason_code=conditional_candidate_boundary.reason_code,
                        missing_inputs=conditional_candidate_boundary.missing_inputs,
                    )
                else:
                    boundary_reply = _non_actionable_plan_preview_boundary(non_actionable_mutation_result)
                boundary_reply = _sanitize_reply_for_user(_normalize_user_facing_terms(boundary_reply))
                _replace_text_reply(new_messages, reply, boundary_reply)
                _replace_text_reply(all_messages, reply, boundary_reply)
                reply = boundary_reply
                workspace_refresh_targets = []
                workspace_view_targets = []
                non_actionable_plan_preview_boundary_applied = True
        if isinstance(reply, str):
            final_user_reply = _sanitize_reply_for_user(reply)
            if (
                compiled_plan_pending_card is None
                and compiled_fix_pending_card is None
                and pending_intent_card is None
                and _reply_claims_intent_recorded_without_pending(final_user_reply)
            ):
                final_user_reply = _recorded_intent_claim_without_pending_reply(final_user_reply)
                final_user_reply = _sanitize_reply_for_user(final_user_reply)
            if final_user_reply != reply:
                _replace_text_reply(new_messages, reply, final_user_reply)
                _replace_text_reply(all_messages, reply, final_user_reply)
                reply = final_user_reply
            latest_review_result = _latest_readonly_plan_execution_result(tool_context_messages)
            if (
                latest_review_result is not None
                and not has_readonly_explore_result
                and _result_needs_unavailable_guidance_fallback(latest_review_result, user_prompt=content)
            ):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif latest_review_result is not None and not has_readonly_explore_result and _review_reply_overclaims_admission_safety(reply, latest_review_result):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif latest_review_result is not None and not has_readonly_explore_result and _review_reply_needs_structured_fallback(reply, latest_review_result):
                structured_review_reply = _build_plan_timeout_fallback_reply(
                    latest_review_result,
                    user_prompt=content,
                ) or reply
                structured_review_reply = _sanitize_reply_for_user(structured_review_reply)
                if structured_review_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_review_reply)
                    _replace_text_reply(all_messages, reply, structured_review_reply)
                    reply = structured_review_reply
            elif latest_review_result is not None and not has_readonly_explore_result and _review_reply_needs_boundary(reply, latest_review_result):
                bounded_review_reply = _sanitize_reply_for_user(
                    f"已完成方案审查。\n\n{reply.lstrip()}"
                )
                if bounded_review_reply != reply:
                    _replace_text_reply(new_messages, reply, bounded_review_reply)
                    _replace_text_reply(all_messages, reply, bounded_review_reply)
                    reply = bounded_review_reply
            latest_adjustment_result = _latest_readonly_plan_execution_result(tool_context_messages)
            if (
                latest_adjustment_result is not None
                and not has_readonly_explore_result
                and _adjustment_reply_needs_structured_fallback(reply, latest_adjustment_result)
            ):
                structured_adjustment_reply = _build_plan_timeout_fallback_reply(
                    latest_adjustment_result,
                    user_prompt=content,
                ) or reply
                structured_adjustment_reply = _sanitize_reply_for_user(structured_adjustment_reply)
                if structured_adjustment_reply != reply:
                    _replace_text_reply(new_messages, reply, structured_adjustment_reply)
                    _replace_text_reply(all_messages, reply, structured_adjustment_reply)
                    reply = structured_adjustment_reply
        if (
            structured_plan_reroute is None
            and compiled_plan_pending_card is None
            and plan_confirmation_candidate is None
            and compiled_fix_pending_card is None
            and pending_intent_card is None
            and isinstance(reply, str)
            and _reply_looks_like_unbacked_plan_action_boundary(reply)
            and not list(_iter_tool_call_parts(tool_context_messages))
        ):
            no_action_reply = _normalize_unbacked_no_tool_action_boundary(reply)
            if no_action_reply != reply:
                _replace_text_reply(new_messages, reply, no_action_reply)
                _replace_text_reply(all_messages, reply, no_action_reply)
                reply = no_action_reply
        if compiled_plan_pending_card is not None or compiled_fix_pending_card is not None:
            pending_type = "plan"
        elif pending_intent_card is not None:
            pending_type = "intent"
        else:
            pending_type = "plan" if active_pending_kind == "plan_mutation" else "intent" if active_pending_kind == "intent_change" else None
        post_processing_applied = ["structured_plan_reroute"] if structured_plan_reroute else []
        if full_agent_intent_pending_blocked:
            post_processing_applied.append("turn_decision_blocked_full_agent_intent_pending")
        if full_agent_intent_pending_turn_decision_override:
            post_processing_applied.append("turn_decision_aligned_full_agent_intent_preview")
        if non_actionable_plan_preview_boundary_applied:
            post_processing_applied.append("non_actionable_plan_preview_boundary")
        full_agent_display_source = _full_agent_plan_display_source(
            action_family=action_family,
            tool_context_messages=tool_context_messages,
            pending_card_created=compiled_plan_pending_card is not None or compiled_fix_pending_card is not None,
            turn_decision=turn_decision_object,
        )
        full_agent_display_payload = (
            full_agent_display_source.display_payload
            if full_agent_display_source is not None
            else {}
        )
        full_agent_reply_plan = (
            full_agent_display_source.reply_plan
            if full_agent_display_source is not None
            else {}
        )
        full_agent_conditional_options = (
            full_agent_display_payload.get("presentation") == "conditional_options"
        )
        full_agent_turn_decision_snapshot = (
            _turn_decision_snapshot(turn_decision_object)
            if turn_decision_object is not None
            else {}
        )
        full_agent_reply_focus = [
            str(item or "").strip()
            for item in full_agent_turn_decision_snapshot.get("targetIssue", [])
            if str(item or "").strip()
        ]
        total_duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        post_full_agent_duration_ms = max(
            0,
            total_duration_ms - pre_full_agent_duration_ms - llm_duration_ms,
        )
        turn_event = {
            "sessionId": session_id,
            "userId": user_id,
            "scene": scene,
            "routingPath": "full_agent",
            "routeDecision": {
                "source": "full_agent",
                "matched": True,
                "confidence": "model",
                "route": scene,
                **(
                    {
                        "sideEffect": "readonly_or_plan_preview",
                        "outputType": "readonly_or_plan_mutation",
                    }
                    if full_agent_conditional_options
                    else {}
                ),
                **(
                    {"displayPayload": full_agent_display_payload}
                    if full_agent_display_payload
                    else {}
                ),
                **(
                    {"replyPlan": full_agent_reply_plan}
                    if full_agent_reply_plan
                    else {}
                ),
                **(
                    {"replyFocus": full_agent_reply_focus}
                    if full_agent_reply_focus
                    else {}
                ),
                **(
                    {"turnDecision": full_agent_turn_decision_snapshot}
                    if full_agent_turn_decision_snapshot
                    else {}
                ),
                "fallbackReason": "structured_plan_reroute" if structured_plan_reroute else "no_direct_route",
                "structuredReroute": structured_plan_reroute,
                "toolTrial": full_agent_tool_trial,
                "agentRun": dict(getattr(request_context, "agent_observability", {}) or {}),
            },
            "pendingType": pending_type,
            "actionFamily": action_family,
            **({"replyFocus": full_agent_reply_focus} if full_agent_reply_focus else {}),
            "modelProvider": _llm_config_value(self.llm_client, "provider"),
            "modelName": _llm_config_value(self.llm_client, "model_name"),
            "llmRequests": getattr(usage, "requests", None),
            "inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
            "toolCallCount": getattr(usage, "tool_calls", None),
            "totalDurationMs": total_duration_ms,
            "llmDurationMs": llm_duration_ms,
            "toolDurationMs": None,
            "preFullAgentDurationMs": pre_full_agent_duration_ms,
            "historyLoadDurationMs": history_load_duration_ms,
            "pendingLoadDurationMs": pending_load_duration_ms,
            "initialStateLoadDurationMs": initial_state_load_duration_ms,
            "runtimeHistoryBuildDurationMs": runtime_history_build_duration_ms,
            "backendContextLoadDurationMs": backend_context_load_duration_ms,
            "requestContextBuildDurationMs": request_context_build_duration_ms,
            "guardPipelineDurationMs": guard_pipeline_duration_ms,
            **_observability_timing_fields(request_context),
            "postFullAgentDurationMs": post_full_agent_duration_ms,
            "unattributedDurationMs": max(0, total_duration_ms - llm_duration_ms),
            "toolCalls": observed_tool_calls,
            "postProcessingApplied": post_processing_applied,
            "status": "success",
            "errorType": None,
        }
        if full_agent_display_source is not None:
            post_processing_applied.append(full_agent_display_source.route)
        _log_conversation_turn_event(
            **turn_event,
        )

        # ── 保存历史 ──────────────────────────────────────────────
        try:
            history_to_save = list(history or [])
            if history_to_save and new_messages:
                history_to_save.extend(
                    _append_turn_observability_messages(
                        new_messages,
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )
                )
            elif new_messages:
                history_to_save = _append_turn_observability_messages(
                    list(new_messages),
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
            else:
                runtime_len = len(runtime_history.model_history or [])
                inferred_new_messages = list(all_messages[runtime_len:]) if len(all_messages) >= runtime_len else []
                inferred_new_messages = _append_turn_observability_messages(
                    inferred_new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(content or ""),
                )
                if history_to_save and inferred_new_messages:
                    history_to_save.extend(inferred_new_messages)
                elif inferred_new_messages:
                    history_to_save = inferred_new_messages
                elif not history_to_save:
                    history_to_save = _append_turn_observability_messages(
                        list(all_messages),
                        turn_event,
                        request_context=request_context,
                        session_id=session_id,
                        user_id=user_id,
                        prompt_length=len(content or ""),
                    )

            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save chat history: session_id=%s", session_id)

        logger.debug(
            "Conversation turn event: %s",
            json.dumps(turn_event, ensure_ascii=False, default=str),
        )

        logger.info(
            "ChatService completed: session_id=%s reply=%s new_history_len=%d",
            session_id, reply, len(all_messages),
        )
        followups: list[WSResponse] = []
        if compiled_pending_workspace_refresh_targets:
            workspace_refresh_targets = _dedupe_workspace_targets(
                [
                    *workspace_refresh_targets,
                    *compiled_pending_workspace_refresh_targets,
                ]
            )
        if workspace_refresh_targets:
            logger.info(
                "ChatService attaching planning workspace refresh after planning action: session_id=%s targets=%s",
                session_id,
                workspace_refresh_targets,
            )
            followups.extend(
                _build_silent_workspace_refresh_response(session_id, target)
                for target in workspace_refresh_targets
            )
        if workspace_view_targets:
            already = set(workspace_refresh_targets)
            for target in workspace_view_targets:
                if target not in already:
                    followups.append(
                        _build_workspace_action_response(session_id, target, refresh=False)
                    )
        if compiled_plan_pending_card is not None:
            followups.append(compiled_plan_pending_card)
        if compiled_fix_pending_card is not None:
            followups.append(compiled_fix_pending_card)
        if pending_intent_card is not None:
            followups.append(pending_intent_card)
        followups = _enforce_single_pending_confirmation_followup(followups)
        if isinstance(reply, str):
            reply = _sanitize_reply_for_user(reply)
            if not followups and _reply_claims_intent_recorded_without_pending(reply):
                reply = _sanitize_reply_for_user(_recorded_intent_claim_without_pending_reply(reply))
        if followups and isinstance(reply, str) and not reply.strip():
            if pending_intent_card is not None:
                fallback_primary = _pending_confirmation_primary_reply_from_card(pending_intent_card)
                if fallback_primary:
                    reply = fallback_primary
        if followups and not isinstance(reply, WSResponse):
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def handle_intent_select(
        self, session_id: str, user_id: str, content: str,
        batch: str | None = None,
    ) -> str | WSResponse:
        """处理意向确认选择请求，按用户勾选结果局部采纳。"""
        logger.info(
            "ChatService handling intent selection: session_id=%s content_len=%d",
            session_id, len(content),
        )
        try:
            selected_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return "消息格式错误，请重试。"

        # Try to determine batch from score detail if not provided
        if not batch:
            try:
                score_response = await get_user_score_detail(session_id)
                if score_response.get("code") == 0:
                    raw_data = score_response.get("data", {}).get("userScoreDetail", {})
                    if raw_data:
                        batch = _normalize_batch(raw_data.get("batch", "01"))
            except Exception:
                logger.warning("Failed to fetch batch for intent selection: session_id=%s", session_id)

        action_type = (selected_data.get("actionType") or "").strip()
        if action_type:
            logger.info(
                "ChatService handling interest follow-up action: session_id=%s action_type=%s",
                session_id,
                action_type,
            )
            followup_json = await handle_interest_analysis_action_result(
                session_id=session_id,
                batch=batch or "01",
                action_type=action_type,
            )
            try:
                followup_result = parse_explore_followup_result(followup_json)
            except Exception:
                logger.warning(
                    "Failed to parse explore follow-up result: session_id=%s action_type=%s",
                    session_id,
                    action_type,
                    exc_info=True,
                )
                return "处理这一步时发生错误，请稍后重试。"
            if action_type in {"prefer_confirm", "constrain_confirm"} and followup_result.analysisPayload:
                pending_result = await _create_pending_intent_confirmation_result_from_preview_payload(
                    session_id,
                    followup_result.analysisPayload,
                )
                pending_card = pending_result.card
                if pending_card is not None:
                    primary_text = (
                        _pending_confirmation_primary_reply_from_card(pending_card)
                        or _intent_card_primary_reply_from_preview_payload(followup_result.analysisPayload)
                    )
                    followups = [
                        _build_silent_workspace_refresh_response(session_id, target)
                        for target in pending_result.workspace_refresh_targets
                    ]
                    followups.append(pending_card)
                    return ChatServiceResponseEnvelope(
                        primary=primary_text,
                        followups=followups,
                    )
            return render_explore_followup_result(followup_result)

        selected_values = selected_data.get("selected", [])
        if not selected_values:
            return "你这次没有采纳任何意向调整。"
        try:
            merged = merge_selected_values(selected_values)
        except Exception:
            logger.warning("Failed to merge selected intents: session_id=%s", session_id, exc_info=True)
            return "处理这一步时发生错误，请稍后重试。"
        intent_mode = await _resolve_intent_mode_from_message(selected_data.get("message_id"))
        raw_constraint_intent_type = selected_data.get("constraintIntentType") or selected_data.get("constraint_intent_type")
        intent_resolution = proposal_compiler.resolve_intent_select_input(
            selected_values=[item for item in selected_values if isinstance(item, dict) and item],
            merged=merged,
            intent_mode=intent_mode,
            raw_constraint_intent_type=str(raw_constraint_intent_type or "default"),
        )
        if not intent_resolution.allowed:
            logger.info(
                "Skip compiled intent select before compiled input: session_id=%s constraint=%s reasons=%s merged=%s",
                session_id,
                raw_constraint_intent_type,
                intent_resolution.blocking_reasons,
                merged,
            )
            return ChatServiceResponseEnvelope(primary="", followups=[])
        intent_mode = intent_resolution.intent_mode
        constraint_intent_type = intent_resolution.constraint_intent_type
        summary = _display_summary_from_intent_payload(selected_data) or _summarize_intent_values(
            merged,
            intent_mode=intent_mode,
            constraint_intent_type=constraint_intent_type,
        )
        if not summary:
            summary = "本次选择的要求内容。" if intent_mode == "constraint" else "本次选择的偏好内容。"
        compiled = proposal_compiler.compile_intent_select_proposal(
            session_id=session_id,
            selected_data=selected_data,
            merged=merged,
            intent_mode=intent_mode,
            batch=batch or "01",
            constraint_intent_type=constraint_intent_type,
            summary=summary,
        )
        compiled_sink_metadata = proposal_compiler.intent_sink_metadata_or_none(
            compiled,
            session_id=session_id,
            source="intent_select",
        )
        if compiled_sink_metadata is None:
            return "这次待采纳内容缺少校验信息，请重新选择后再试。"
        return await _create_pending_intent_confirmation_response(
            session_id=session_id,
            selected_data=selected_data,
            merged=merged,
            intent_mode=intent_mode,
            batch=batch or "01",
            compiled_sink_metadata=compiled_sink_metadata,
        )

    async def _handle_structured_pending_confirmation(
        self,
        *,
        session_id: str,
        user_id: str,
        pending_state: dict[str, Any],
        pending_id: str,
        message_id: Any,
        confirmation_entry: str,
        user_prompt_content: str | None,
        confirmation_history: list[Any] | None,
        turn_started_at: float,
        post_apply_intent: str,
        post_apply_evidence_plan: dict[str, Any] | None,
        emit_pending_event: Callable[..., None],
    ) -> str | ChatServiceResponseEnvelope | None:
        execution_payload = pending_state.get("executionPayload")
        if not isinstance(execution_payload, dict):
            return None
        action_family = str(pending_state.get("actionFamily") or "").strip()
        tool_name = str(execution_payload.get("toolName") or "").strip()
        active_pending = _pending_confirmation_from_state(pending_state)
        if active_pending is None:
            return None
        if active_pending.kind == "plan_mutation":
            if action_family == "apply_fix_proposal" or tool_name == "apply_planning_fix_proposal":
                return None

        workspace_data: dict[str, Any] | None = None
        parsed_planning_summary: PlanningSummary | None = None
        try:
            workspace_response = await get_planning_workspace_state(session_id)
        except Exception:
            logger.warning(
                "Failed to fetch workspace before structured pending confirmation: session_id=%s",
                session_id,
                exc_info=True,
            )
            workspace_response = None
        if isinstance(workspace_response, dict) and workspace_response.get("code") == 0:
            raw_workspace = workspace_response.get("data")
            if isinstance(raw_workspace, dict):
                workspace_data = raw_workspace
                parsed_planning_summary = PlanningSummary.from_backend_state(workspace_data)

        conversation_phase = ConversationPhase.from_pending_confirmation(
            active_pending,
            planning_summary=parsed_planning_summary,
        )
        request_context = RequestContext(
            userid=user_id,
            sessionid=session_id,
            chat_history=[],
            batch=str(execution_payload.get("batch") or "01"),
            planning_summary=parsed_planning_summary,
            sandbox=build_request_sandbox(
                session_id=session_id,
                batch=str(execution_payload.get("batch") or "01"),
                planning_state=workspace_data,
                planning_summary=parsed_planning_summary,
                pending_state=pending_state,
                pending=active_pending,
            ),
            conversation_phase=conversation_phase,
            allow_explore_inner_llm=False,
            confirmed_via_card=confirmation_entry == "card",
            confirmed_via_pending=True,
            confirmation_entry=confirmation_entry,
        )

        result_text = await zhiyuan_agent_confirm_pending(
            SimpleNamespace(deps=request_context),
            action="confirm",
        )
        result = _parse_tool_return_json(result_text) or {}
        result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        apply_result = result_data.get("result") if isinstance(result_data.get("result"), dict) else {}
        applied = bool(result_data.get("applied"))
        reply = str(result.get("message") or "").strip() or (
            "已执行这次方案调整。" if applied else "这次方案调整没有执行成功，请重新生成预览后再确认。"
        )
        if post_apply_intent == "apply_pending_then_readonly" and applied:
            post_apply_planning_summary = await _load_post_apply_planning_summary(session_id)
            reply = _append_pending_apply_then_readonly_result(
                reply,
                pending_state,
                post_apply_evidence_plan,
                post_apply_planning_summary,
            )
        reply = _sanitize_reply_for_user(reply)

        await _mark_pending_confirmation_message_status(
            session_id,
            message_id,
            pending_id=pending_id,
            status="applied" if applied else "expired",
        )

        result_code = (
            "applied"
            if applied
            else str(apply_result.get("reason") or result_data.get("error") or "structured_pending_apply_failed")
        )
        emit_pending_event(
            result="applied" if applied else "failed",
            result_code=result_code,
        )

        pending_type = "intent" if active_pending.kind == "intent_change" else "plan"
        scene = pending_type
        tool_call_id = f"{confirmation_entry}-{action_family or pending_type}-structured-confirm"
        new_messages = [
            ModelRequest(parts=[UserPromptPart(content=user_prompt_content or "[待确认内容]")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="confirm_pending",
                        args={"action": "confirm"},
                        tool_call_id=tool_call_id,
                    )
                ],
                model_name=f"pending-confirmation-{confirmation_entry}",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="confirm_pending",
                        content=result_text,
                        tool_call_id=tool_call_id,
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content=reply)], model_name=f"pending-confirmation-{confirmation_entry}"),
        ]
        turn_event = _pending_apply_turn_event(
            session_id=session_id,
            user_id=user_id,
            scene=scene,
            routing_path=(
                f"pending_{pending_type}_structured_short_text_confirm"
                if confirmation_entry == "short_text"
                else f"{pending_type}_structured_confirmation_card_confirm"
            ),
            pending_type=pending_type,
            action_family=action_family,
            started_at=turn_started_at,
            status="success" if applied else "error",
            error_type=None if applied else result_code,
            post_apply_evidence_plan=post_apply_evidence_plan if applied else None,
        )
        try:
            history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
            history_to_save = list(history)
            history_to_save.extend(
                _append_turn_observability_messages(
                    new_messages,
                    turn_event,
                    request_context=request_context,
                    session_id=session_id,
                    user_id=user_id,
                    prompt_length=len(user_prompt_content or ""),
                )
            )
            await self.history_store.save(session_id, history_to_save)
        except Exception:
            logger.exception("Failed to save structured pending confirmation history: session_id=%s", session_id)

        _log_conversation_turn_event(**turn_event)

        followups: list[WSResponse] = []
        if applied:
            if active_pending.kind == "intent_change":
                fallback_targets = ["ordered", "review"]
            elif action_family in {"add_units", "replace_units"}:
                fallback_targets = ["ordered", "candidate", "review"]
            else:
                fallback_targets = ["ordered", "review"]
            for target in _post_apply_evidence_workspace_targets(
                post_apply_evidence_plan,
                fallback_targets,
            ):
                followups.append(_build_silent_workspace_refresh_response(session_id, target))
        if followups:
            return ChatServiceResponseEnvelope(primary=reply, followups=followups)
        return reply

    async def handle_pending_confirmation(
        self,
        session_id: str,
        user_id: str,
        content: str,
        *,
        confirmation_entry: str = "card",
        user_prompt_content: str | None = None,
        post_apply_intent: str | None = None,
        post_apply_evidence_plan: dict[str, Any] | None = None,
    ) -> str | ChatServiceResponseEnvelope:
        """Handle explicit confirmation-card actions.

        This is the migration bridge before durable pending_id endpoints land:
        the card click is explicit, while the executable payload is still
        recovered from recent persisted plan preview history.
        """
        try:
            selected_data = json.loads(content) if isinstance(content, str) else {}
        except (json.JSONDecodeError, TypeError):
            return "消息格式错误，请重试。"
        if not isinstance(selected_data, dict):
            return "消息格式错误，请重试。"

        action = str(selected_data.get("action") or "").strip().lower()
        kind = str(selected_data.get("kind") or "").strip()
        pending_id = str(selected_data.get("pendingId") or selected_data.get("pending_id") or "").strip()
        message_id = selected_data.get("message_id")
        confirmation_entry = "short_text" if confirmation_entry == "short_text" else "card"
        post_apply_intent = str(post_apply_intent or "").strip()
        post_apply_evidence_plan = (
            dict(post_apply_evidence_plan)
            if post_apply_intent == "apply_pending_then_readonly" and isinstance(post_apply_evidence_plan, dict)
            else None
        )
        pending_state = await _load_pending_confirmation_state(session_id)
        turn_started_at = time.monotonic()
        active_pending_id = str((pending_state or {}).get("pendingId") or "").strip()
        active_status = str((pending_state or {}).get("status") or "").strip()
        if not pending_id:
            return "这次操作缺少校验信息，请重新生成预览后再确认。"
        if not pending_state or active_status != "active" or active_pending_id != pending_id:
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="expired",
            )
            return "这次待采纳内容已经失效。请以最新内容为准，或重新说明想怎么调整。"
        if kind and kind != str(pending_state.get("kind") or ""):
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="expired",
            )
            return "这次操作和当前等待采纳的内容不一致，请以最新内容为准。"

        if action in {"cancel", "reject"}:
            cancelled_state = dict(pending_state)
            cancelled_state["status"] = "cancelled"
            cancelled_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            await _save_pending_confirmation_state(session_id, cancelled_state)
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="cancelled",
            )
            return "已取消本次待采纳内容。你可以继续说明想怎么调整，我会重新给出预览。"
        if action not in {"confirm", "accept", "apply"}:
            return "这次操作类型不完整，请刷新后重试。"
        active_kind = str(pending_state.get("kind") or "").strip()
        consistency_status = "not_checked"
        assistant_confirmation_summary = ""
        blocked_reason = None
        confirmation_history: list[Any] | None = None

        def emit_pending_event(*, result: str, result_code: str | None = None) -> None:
            _log_pending_confirmation_event(
                eventType="pending_confirmation_apply",
                sessionId=session_id,
                userId=user_id,
                pendingId=pending_id,
                kind=active_kind,
                actionFamily=str(pending_state.get("actionFamily") or "").strip() or None,
                confirmationEntry=confirmation_entry,
                pendingSummary=str(pending_state.get("summary") or "").strip(),
                assistantConfirmationSummary=assistant_confirmation_summary,
                consistencyStatus=consistency_status,
                blockedReason=blocked_reason,
                sourceBackendVersion=pending_state.get("sourceBackendVersion"),
                result=result,
                resultCode=result_code,
            )

        if confirmation_entry == "short_text":
            try:
                confirmation_history = await self.history_store.load(session_id) or []
            except Exception:
                logger.exception("Failed to load history for pending confirmation consistency check: session_id=%s", session_id)
                confirmation_history = []
            consistency_status, blocked_reason, assistant_confirmation_summary = _evaluate_short_text_pending_consistency(
                pending_state,
                confirmation_history,
            )
            if blocked_reason:
                reply = "为避免确认错内容，请点最新内容里的“采纳”，或重新说明要确认的内容，我会重新列出待采纳内容。"
                await _save_direct_guard_history(
                    self.history_store,
                    session_id,
                    confirmation_history,
                    user_prompt_content or content,
                    reply,
                    model_name=f"pending-confirmation-consistency-blocked:{pending_id}",
                )
                emit_pending_event(result="blocked", result_code=blocked_reason)
                return reply

        if active_kind not in {"intent_change", "plan_mutation"}:
            return "这类待采纳内容暂时还不能在这里处理，请刷新后重试。"

        structured_pending_reply = await self._handle_structured_pending_confirmation(
            session_id=session_id,
            user_id=user_id,
            pending_state=pending_state,
            pending_id=pending_id,
            message_id=message_id,
            confirmation_entry=confirmation_entry,
            user_prompt_content=user_prompt_content,
            confirmation_history=confirmation_history,
            turn_started_at=turn_started_at,
            post_apply_intent=post_apply_intent,
            post_apply_evidence_plan=post_apply_evidence_plan,
            emit_pending_event=emit_pending_event,
        )
        if structured_pending_reply is not None:
            return structured_pending_reply
        if active_kind == "intent_change":
            return "这次待采纳内容缺少可执行内容，请重新生成。"

        if active_kind != "plan_mutation":
            return "这类待采纳内容暂时还不能在这里处理，请刷新后重试。"

        execution_payload = pending_state.get("executionPayload")
        if not isinstance(execution_payload, dict):
            return "这次方案调整缺少可执行内容，请重新生成预览。"
        action_family = str(pending_state.get("actionFamily") or "").strip()
        tool_name = str(execution_payload.get("toolName") or "").strip()
        if action_family == "apply_fix_proposal" or tool_name == "apply_planning_fix_proposal":
            started_at = time.monotonic()
            proposal_source = str(
                execution_payload.get("proposalSource")
                or execution_payload.get("proposal_source")
                or "review_check"
            ).strip() or "review_check"
            proposal_id = str(
                execution_payload.get("proposalId")
                or execution_payload.get("proposal_id")
                or ""
            ).strip()
            source_version_guard = _as_int(
                execution_payload.get("sourceVersionGuard")
                or execution_payload.get("source_version_guard")
                or pending_state.get("sourceBackendVersion")
                or pending_state.get("source_backend_version")
            )
            if not proposal_id or source_version_guard <= 0:
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code="missing_fix_proposal_apply_args",
                )
                emit_pending_event(result="failed", result_code="missing_fix_proposal_apply_args")
                return "这次处理建议缺少必要信息，请重新查看方案审查结果后再处理。"

            regenerate_ordered_plan = execution_payload.get("regenerateOrderedPlan")
            if regenerate_ordered_plan is None:
                regenerate_ordered_plan = execution_payload.get("regenerate_ordered_plan")
            rerun_review = execution_payload.get("rerunReview")
            if rerun_review is None:
                rerun_review = execution_payload.get("rerun_review")
            user_goal_request = execution_payload.get("userGoalRequest")
            if not isinstance(user_goal_request, dict):
                user_goal_request = None
            intent_payload = execution_payload.get("intentPayload")
            intent_apply_note = ""
            if proposal_source == "user_goal" and isinstance(intent_payload, dict) and intent_payload.get("selected"):
                effective_batch = _normalize_batch(intent_payload.get("batch") or "01")
                selected_data_for_apply = {
                    "selected": intent_payload.get("selected") or [],
                    "intentMode": str(intent_payload.get("intentMode") or "constraint").strip() or "constraint",
                    "constraintIntentType": str(
                        intent_payload.get("constraintIntentType")
                        or intent_payload.get("constraint_intent_type")
                        or "default"
                    ).strip() or "default",
                    "batch": effective_batch,
                }
                intent_result_json = await _apply_selected_intents(
                    session_id=session_id,
                    batch=effective_batch,
                    selected_data=selected_data_for_apply,
                )
                try:
                    intent_state_result = parse_intent_state_update_result(intent_result_json)
                except Exception:
                    logger.warning(
                        "Failed to parse user-goal intent confirmation result: session_id=%s",
                        session_id,
                        exc_info=True,
                    )
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="intent_apply_parse_failed",
                    )
                    return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
                if not getattr(intent_state_result, "applied", False):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code=str(getattr(intent_state_result, "messageCode", None) or "intent_apply_failed"),
                    )
                    return "这次报考条件没有写入成功，方案暂不调整。请稍后重试，或重新列出待采纳内容。"
                intent_apply_note = "后续报考参考已同步更新。"
                try:
                    state_resp = await get_planning_state(session_id)
                    current_version = _as_int(((state_resp or {}).get("data") or {}).get("version"))
                except Exception:
                    logger.warning("Failed to reload planning state before user-goal apply: session_id=%s", session_id, exc_info=True)
                    current_version = 0
                if current_version <= 0 or not user_goal_request:
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="missing_user_goal_apply_args",
                    )
                    return "这次方案调整缺少必要信息，请重新生成调整预览后再确认。"
                refreshed_user_goal_request = dict(user_goal_request)
                refreshed_user_goal_request["sourceVersionGuard"] = current_version
                try:
                    proposal_result = await generate_user_goal_planning_fix_proposals(
                        1,
                        session_id,
                        refreshed_user_goal_request,
                    )
                except Exception:
                    logger.warning(
                        "Failed to refresh user-goal proposal before apply: session_id=%s",
                        session_id,
                        exc_info=True,
                    )
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_refresh_exception",
                    )
                    return "当前方案已经更新，需要重新生成调整预览后再确认。"
                proposal_data = proposal_result.get("data") if isinstance(proposal_result, dict) else None
                if proposal_result.get("code") != 0 or not isinstance(proposal_data, dict):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_refresh_failed",
                    )
                    return "当前方案已经更新，需要重新生成调整预览后再确认。"
                refreshed_proposal = proposal_compiler.select_ready_fix_proposal(
                    {"fix_proposals": proposal_data},
                    target_strategies=[str(refreshed_user_goal_request.get("goalType") or "").strip()],
                )
                if not isinstance(refreshed_proposal, dict):
                    await _mark_pending_confirmation_failed(
                        session_id,
                        pending_state,
                        message_id,
                        pending_id=pending_id,
                        result_code="user_goal_proposal_no_ready",
                    )
                    return "这次想法已写入后续报考参考，但当前方案暂时没有可直接执行的调整项。你可以重新查看方案或放宽条件后再调整。"
                proposal_id = str(
                    refreshed_proposal.get("proposalId")
                    or refreshed_proposal.get("proposal_id")
                    or ""
                ).strip()
                source_version_guard = _as_int(
                    refreshed_proposal.get("sourceVersionGuard")
                    or refreshed_proposal.get("source_version_guard")
                    or proposal_data.get("sourceVersionGuard")
                    or current_version
                )
                user_goal_request = refreshed_user_goal_request
            try:
                result_json = await apply_planning_fix_proposal(
                    1,
                    session_id,
                    proposal_id=proposal_id,
                    source_version_guard=source_version_guard,
                    regenerate_ordered_plan=regenerate_ordered_plan is not False,
                    rerun_review=rerun_review is not False,
                    proposal_source=proposal_source,
                    user_goal_request=user_goal_request,
                )
            except Exception:
                logger.warning(
                    "Failed to apply pending fix proposal: session_id=%s proposal_id=%s",
                    session_id,
                    proposal_id,
                    exc_info=True,
                )
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code="fix_proposal_apply_exception",
                )
                emit_pending_event(result="failed", result_code="fix_proposal_apply_exception")
                return "这次处理建议没有执行成功。请重新查看方案审查结果后再试。"

            result_data = result_json.get("data") if isinstance(result_json, dict) else None
            if not isinstance(result_data, dict):
                result_data = {}
            result_code = str(result_json.get("code") if isinstance(result_json, dict) else "").strip()
            applied = result_code == "0" and str(result_data.get("status") or "").strip() == "applied"
            if not applied:
                await _mark_pending_confirmation_failed(
                    session_id,
                    pending_state,
                    message_id,
                    pending_id=pending_id,
                    result_code=str(result_json.get("msg") if isinstance(result_json, dict) else "")
                    or "fix_proposal_apply_failed",
                )
                emit_pending_event(result="failed", result_code="fix_proposal_apply_failed")
                return str(
                    (result_json or {}).get("msg")
                    if isinstance(result_json, dict)
                    else ""
                ).strip() or "这次处理建议没有执行成功。请重新查看方案审查结果后再试。"

            reply = _format_fix_proposal_apply_result(result_data)
            if intent_apply_note:
                reply = f"{reply}\n\n{intent_apply_note}"
            tuition_apply_note = ""
            max_tuition_per_year = _max_tuition_from_user_goal_request(user_goal_request)
            if proposal_source == "user_goal" and max_tuition_per_year > 0:
                try:
                    tuition_result = await update_session_tuition_range(
                        session_id,
                        min_tuition=0,
                        max_tuition=max_tuition_per_year,
                    )
                except Exception:
                    logger.warning(
                        "Failed to update tuition range after user-goal apply: session_id=%s max_tuition=%s",
                        session_id,
                        max_tuition_per_year,
                        exc_info=True,
                    )
                    tuition_result = {}
                if isinstance(tuition_result, dict) and str(tuition_result.get("code")) == "0":
                    tuition_apply_note = f"后续候选筛选也会按每年不超过 {max_tuition_per_year} 元继续参考。"
                else:
                    tuition_apply_note = "这次方案调整已处理，但学费范围没有同步成功；后续候选筛选可能还需要手动刷新预算。"
            if tuition_apply_note:
                reply = f"{reply}\n\n{tuition_apply_note}"
            if post_apply_intent == "apply_pending_then_readonly":
                post_apply_planning_summary = await _load_post_apply_planning_summary(session_id)
                reply = _append_pending_apply_then_readonly_result(
                    reply,
                    pending_state,
                    post_apply_evidence_plan,
                    post_apply_planning_summary,
                )
            applied_state = dict(pending_state)
            applied_state["status"] = "applied"
            applied_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            applied_state["resultCode"] = "applied"
            applied_state["resultData"] = result_data
            if post_apply_evidence_plan is not None:
                applied_state["postApplyEvidencePlan"] = post_apply_evidence_plan
            await _save_pending_confirmation_state(session_id, applied_state)
            await _mark_pending_confirmation_message_status(
                session_id,
                message_id,
                pending_id=pending_id,
                status="applied",
            )

            tool_args = {
                "proposal_id": proposal_id,
                "proposal_source": proposal_source,
                "source_version_guard": source_version_guard,
                "regenerate_ordered_plan": regenerate_ordered_plan is not False,
                "rerun_review": rerun_review is not False,
            }
            if user_goal_request:
                tool_args["user_goal_request"] = user_goal_request
            result_text = json.dumps(result_json, ensure_ascii=False)
            new_messages = [
                ModelRequest(parts=[UserPromptPart(content=user_prompt_content or "[确认处理方案提醒]")]),
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="apply_planning_fix_proposal",
                            args=tool_args,
                            tool_call_id=f"{confirmation_entry}-apply-fix-proposal-confirmation",
                        )
                    ],
                    model_name=f"pending-confirmation-{confirmation_entry}",
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="apply_planning_fix_proposal",
                            content=result_text,
                            tool_call_id=f"{confirmation_entry}-apply-fix-proposal-confirmation",
                        )
                    ]
                ),
                ModelResponse(parts=[TextPart(content=reply)], model_name=f"pending-confirmation-{confirmation_entry}"),
            ]
            turn_event = _pending_apply_turn_event(
                session_id=session_id,
                user_id=user_id,
                scene="plan",
                routing_path="pending_plan_short_text_confirm" if confirmation_entry == "short_text" else "plan_confirmation_card_confirm",
                pending_type="plan",
                action_family=action_family,
                started_at=started_at,
                status="success",
                post_apply_evidence_plan=post_apply_evidence_plan,
            )
            try:
                history = confirmation_history if confirmation_history is not None else await self.history_store.load(session_id) or []
                history_to_save = list(history)
                history_to_save.extend(_append_route_observability_message(new_messages, turn_event))
                await self.history_store.save(session_id, history_to_save)
            except Exception:
                logger.exception("Failed to save pending fix proposal confirmation history: session_id=%s", session_id)

            _log_conversation_turn_event(**turn_event)
            emit_pending_event(result="applied", result_code="applied")
            followups = []
            for target in _post_apply_evidence_workspace_targets(post_apply_evidence_plan, ["ordered"]):
                if target == "ordered":
                    followups.append(
                        _build_silent_workspace_refresh_response(
                            session_id,
                            "ordered",
                            extra_payload={
                                "title": "方案已更新",
                                "content": "已按这条处理建议刷新方案，可以查看调整后的排序方案。",
                                "actionText": "查看方案",
                            },
                        )
                    )
                else:
                    followups.append(_build_silent_workspace_refresh_response(session_id, target))
            if proposal_source == "user_goal":
                already = _workspace_targets_from_followups(followups)
                if "candidate" not in already:
                    followups.append(
                        _build_silent_workspace_refresh_response(
                            session_id,
                            "candidate",
                            extra_payload={
                                "preserveView": True,
                                "title": "候选推荐已更新",
                                "content": "这次报考条件已采纳，候选和推荐信息会按新的条件刷新。",
                                "actionText": "查看候选",
                            },
                        )
                    )
                if "review" not in already:
                    followups.append(
                        _build_silent_workspace_refresh_response(
                            session_id,
                            "review",
                            extra_payload={
                                "preserveView": True,
                                "title": "审查结果已刷新",
                                "content": "方案调整后已重新检查风险和提醒。",
                                "actionText": "查看审查",
                            },
                        )
                    )
            return ChatServiceResponseEnvelope(
                primary=_sanitize_reply_for_user(reply),
                followups=followups,
            )

        await _mark_pending_confirmation_failed(
            session_id,
            pending_state,
            message_id,
            pending_id=pending_id,
            result_code="missing_structured_plan_payload",
        )
        emit_pending_event(result="failed", result_code="missing_structured_plan_payload")
        return "这次方案调整缺少可执行内容，请重新生成预览。"
