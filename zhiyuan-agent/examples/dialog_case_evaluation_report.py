#!/usr/bin/env python3
"""Build case-level evaluation reports from dialog regression outputs.

This script only consumes saved JSON outputs. It does not call models.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

_INTERNAL_TERM_PATTERNS = (
    "volunteerId",
    "pending_plan_action",
    "pending_intent_change",
    "conversation_phase",
    "action_family",
    "toolCall",
    "level1",
    "level2",
    "level3",
    "id=",
)

_ACTION_TOKENS = ("建议", "下一步", "可以", "确认", "请查看", "如果你想", "告诉我", "继续")
_DOMAIN_TOKENS = ("方案", "候选", "审查", "排序", "移动", "意向", "查询", "专业", "志愿", "院校", "学校")
_STRUCTURE_TOKENS = ("\n-", "\n1.", "\n2.", "：\n", "###", "##")
_BOUNDARY_TOKENS = ("待确认", "确认后", "不会改", "不改方案", "只读", "先预览")
_RISK_TOKENS = ("风险", "提醒", "边界", "结论", "影响", "缺口")
_PREVIEW_HINT_TOKENS = ("预览", "示例", "代表样本", "下面仅展示", "前列", "共命中", "概况", "典型涉及")
_EMPTY_RESULT_TOKENS = (
    "暂时没有筛到",
    "暂时没有命中",
    "没有返回可用结果",
    "当前候选池没有返回",
    "没有正式方案",
    "还没有正式方案",
    "未生成正式方案",
    "没有生成正式方案",
    "志愿数量为 0",
    "0个志愿",
    "0 个志愿",
)
_PENDING_CONTEXT_TOKENS = ("待确认", "确认前不会正式生效", "确认后才会", "需要你确认后")
_PENDING_CONDITIONAL_TOKENS = (
    "确认后",
    "如果确认",
    "如果你确认",
    "如果你想",
    "如果想",
    "确认要",
    "确认才",
)
_READONLY_REFERENCE_BOUNDARY_TOKENS = (
    "没有待确认",
    "不会改动方案",
    "不会改动当前方案",
    "只做专业取舍分析",
    "只是查询",
    "只是方向分析",
)
_UNQUALIFIED_PENDING_EFFECTIVE_PATTERNS = (
    re.compile(r"把.+?(作为|记成|设为|更新为)"),
    re.compile(r"后(面|续).+?(都会按这个要求|会按这个要求|按这个要求来)"),
)
_EXPECTATION_META_PREFIXES = (
    "说明",
    "明确",
    "包含",
    "覆盖",
    "提到",
    "给出",
    "列出",
    "解释",
    "展示",
    "回复",
    "表达",
    "复述",
)
_FORBIDDEN_META_PREFIXES = (
    "不应说",
    "不应出现",
    "不要说",
    "不能说",
    "禁止出现",
    "避免出现",
    "不要出现",
    "不得出现",
)
_KEYPOINT_TERM_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("下一步", ("下一步", "可以继续", "继续问", "直接问我", "可以直接问我", "告诉我", "可以告诉我", "直接告诉我", "你也可以", "我可以帮你", "愿意补充")),
    ("导出顺序", ("导出顺序", "导出内容")),
    ("导出顺序影响", ("导出顺序", "导出内容")),
    ("待重新审查", ("待重新审查", "重新审查", "审查状态")),
    ("审查需要重新看", ("待重新审查", "重新审查", "审查状态")),
    ("重新", ("重新", "待重新审查")),
    ("审查", ("审查",)),
    ("确认前", ("确认前", "尚未确认")),
    ("确认后", ("确认后", "需要你确认后")),
    ("后续参考", ("后续参考", "作为参考", "后续查看候选和方案时会按")),
    ("不会写入", ("不会写入", "不会正式生效", "不会重复写入")),
    ("不会改", ("不会改", "不会直接改", "不会自动修改")),
    ("当前方案", ("当前方案", "现在这份方案", "这份方案")),
    ("候选", ("候选",)),
    ("数量", ("数量", "已有", "目标", "缺口", "当前方案已有")),
    ("缺口", ("缺口", "还差", "不足")),
    ("位置", ("位置", "当前在", "移动到", "目标", "第")),
    ("位置变化", ("位置", "当前在", "移动到", "目标", "第")),
    ("移动", ("移动", "移到", "改到")),
    ("加入", ("加入", "加进")),
    ("删除", ("删除", "移除", "去掉")),
    ("排序", ("排序", "重新排")),
    ("风险", ("风险", "提醒", "问题")),
    ("冲稳保", ("冲稳保", "冲区", "稳区", "保区", "冲", "稳", "保")),
    ("学校层次", ("学校层次", "院校层次", "学校排名", "院校排名", "公办", "民办")),
    ("院校层次", ("院校层次", "学校层次", "学校排名", "院校排名", "公办", "民办")),
    ("专业热度", ("专业热度", "热度", "计划数", "招生计划")),
    ("学习要求", ("学习要求", "学习内容", "入学后课程", "入学后训练", "课程训练", "核心课程", "核心能力", "美术训练", "手绘")),
    ("就业路径", ("就业路径", "就业方向", "就业面", "企业财务", "金融机构", "事务所", "风控", "考公", "体制内", "岗位口径", "岗位")),
    ("排序建议", ("排序建议", "默认优先级", "优先级", "按目标调整", "选择建议")),
    ("代表样本", ("代表样本", "示例", "典型涉及", "下面仅展示")),
    ("录取率", ("录取率", "录取概率")),
    ("推荐系数", ("推荐系数",)),
    ("体制内", ("体制内", "考公")),
    ("考公", ("考公", "体制内")),
    ("稳定就业", ("稳定就业", "就业确定性")),
    ("读研", ("读研", "深造")),
    ("偏好", ("偏好", "倾向")),
    ("排除", ("排除", "不要", "不考虑")),
    ("本次确认内容", ("本次确认内容", "确认内容")),
)

_DISTRIBUTION_SIGNALS: dict[str, tuple[str, ...]] = {
    "tier_distribution": ("冲稳保", "冲区", "稳区", "保区", "区间分布", "区间："),
    "school_level": ("学校层次", "院校层次", "学校排名", "院校排名", "985", "211", "双一流", "公办", "民办"),
    "major_heat": ("专业热度", "热门", "冷门", "计划数", "招生计划"),
    "quantity_space": ("数量", "缺口", "已有", "目标", "共命中", "排序总数", "方案数", "当前已有"),
    "representative_samples": ("代表样本", "示例", "典型涉及", "排序前列", "方案前列", "下面仅展示"),
}

_READONLY_BOUNDARY_TOKENS = (
    "没有待确认",
    "没有待执行",
    "没有上一轮待确认",
    "不会改动",
    "不会自动改动",
    "不会直接改",
    "不会自动修改",
    "不会写入",
    "不会记录",
    "不会加入",
    "不会执行",
    "不会改方案",
    "不改方案",
    "只是查询",
    "只是方向分析",
    "只做分析",
    "只做参考",
    "先不改",
    "先不要改",
    "先别动",
)
_PREVIEW_CONFIRM_BOUNDARY_TOKENS = (
    "确认前",
    "需要你确认后",
    "确认后才会",
    "确认后再",
    "如果确认",
    "确认执行",
    "待确认",
    "不需要重复确认",
    "不会重复写入",
    "已经在后续参考",
    "已在参考",
)
_USER_LANGUAGE_RISK_TOKENS = (
    "个性化量化评分",
    "系统分数",
    "系统评分",
    "increasingly",
    "baseline",
    " vs ",
    "TODO",
    "N/A",
    "level1",
    "level2",
    "level3",
    "payload",
    "action_family",
    "volunteerId",
)
_DECISION_BASIS_SIGNALS: dict[str, tuple[str, ...]] = {
    "target_identity": ("已定位", "定位结果", "共命中", "符合", "命中", "专业组", "候选里定位"),
    "plan_distribution": ("冲稳保", "冲区", "稳区", "保区", "数量", "缺口", "已有", "目标"),
    "school_level": ("学校层次", "院校层次", "院校排名", "学校排名", "公办", "民办", "双一流"),
    "major_heat": ("专业热度", "热门", "冷门", "计划数", "招生计划"),
    "candidate_reason": ("当前候选池", "具体专业分别查过", "专业名称口径", "可选范围", "没有返回可用结果"),
    "risk_or_gap": ("风险", "提醒", "短板", "缺口", "问题", "需要留意", "保底"),
    "representative_samples": ("代表样本", "示例", "典型涉及", "方案内", "候选里"),
    "career_path": ("就业路径", "就业方向", "就业面", "企业财务", "金融机构", "事务所", "风控", "考公", "体制内", "稳定就业", "就业确定性", "编制", "国企", "读研", "深造", "门槛", "试错成本", "岗位", "岗位口径"),
    "market_employment": ("市场化就业", "大城市就业", "企业就业", "城市产业", "实习机会", "技能", "行业机会", "岗位面"),
    "learning_requirement": ("学习要求", "学习内容", "入学后课程", "入学后训练", "课程训练", "核心课程", "核心能力", "美术训练", "手绘"),
    "admission_requirement": ("录取要求", "录取门槛", "选科", "高考分数", "不另考", "不强制", "不会卡"),
    "decision_recommendation": ("优先级", "排序建议", "选择建议", "默认优先级", "按目标调整", "具体建议", "建议"),
    "side_effect": ("影响", "导出顺序", "导出内容", "待重新审查", "方案顺序", "当前位置", "目标位置", "当前在", "移动到"),
}

_READONLY_BOUNDARY_REQUIRED_COVERAGE = {
    "plan_review_strategy",
    "plan_operations",
    "plan_query",
    "plan_analysis",
    "plan_status",
    "review_plan",
    "review_workspace",
    "risk_summary",
    "safe_plan",
    "avoid_risk",
    "sort_ordered_plan",
    "move_ordered_unit",
    "remove_ordered_unit",
    "remove_units",
    "add_units",
    "candidate_lookup",
    "soft_major_intent",
    "hard_major_constraint",
    "soft_region_intent",
    "negative_region_intent",
    "positive_major_intent",
    "explicit_major_requirement",
    "positive_region_intent",
    "explicit_region_requirement",
    "negative_region_requirement",
    "confirm_guard",
    "no_pending_guard",
    "readonly_closure_ack",
    "readonly_no_workspace_card",
    "readonly_no_pending_intent",
}
_READONLY_BOUNDARY_REQUIRED_PROMPT_TOKENS = (
    "方案",
    "志愿",
    "候选",
    "审查",
    "排序",
    "移动",
    "移到",
    "去掉",
    "删除",
    "加进",
    "加入",
    "别动",
    "先别",
    "先不改",
    "不改",
    "只分析",
    "只看看",
    "别直接",
    "不要直接",
)

_SOFT_EXPECTED_ROUTES: set[str] = set()

_EXPECTED_ROUTES_BY_COVERAGE: dict[str, str] = {
    "readonly_closure_ack": "readonly_closure_ack",
}

_EXPECTED_ACTIONS_BY_COVERAGE: dict[str, str] = {
    "plan_status": "query_state",
    "review_plan": "review_plan",
    "review_workspace": "review_plan",
    "school_major_lookup": "query_plan",
    "sort_ordered_plan": "sort_ordered_plan",
    "career_explore": "explore_topic",
    "major_compare": "compare_entities",
    "soft_major_intent": "preview_intent_change",
    "hard_major_constraint": "preview_intent_change",
    "positive_major_intent": "preview_intent_change",
    "explicit_major_requirement": "preview_intent_change",
    "positive_region_intent": "preview_intent_change",
    "explicit_region_requirement": "preview_intent_change",
    "negative_region_requirement": "preview_intent_change",
}

_ACTION_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "explore_topic": ("explore_topic",),
    "compare_entities": ("compare_entities",),
    "preview_intent_change": ("preview_intent_change",),
    "apply_selected_intents": ("apply_selected_intents",),
    "query_plan": ("query_plan",),
}

_TOOL_CHAIN_SLOW_MS = 10_000
_TOOL_CHAIN_VERY_SLOW_MS = 30_000
_TOOL_CHAIN_MANY_TOOLS = 3

_VERDICT_RANK = {"fail": 0, "needs_review": 1, "strong": 2}

_ASSERTION_FIELDS = (
    "assertContains",
    "assertContainsAny",
    "assertNotContains",
    "assertNoFollowups",
    "assertFollowupTarget",
    "assertFollowupRefresh",
)

_QUALITY_EXPECTATION_FIELDS = (
    "expectedKeyPoints",
    "expectedKeyPointGroups",
    "qualityFocus",
    "manualReviewFocus",
    "forbiddenPatterns",
    "minTextLengthWarn",
)

_SEMANTIC_FRAME_FIELDS = (
    "taskLayer",
    "topic",
    "verb",
    "sideEffect",
)

_SEMANTIC_EXPECTATION_PRESETS: dict[str, dict[str, Any]] = {
    "score_profile": {
        "taskLayer": "explore",
        "topic": "score",
        "verb": ["analyze", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "eligibility_constraints": {
        "taskLayer": "explore",
        "topic": ["policy", "requirement"],
        "verb": ["query", "analyze", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "major_preference": {
        "taskLayer": "explore",
        "topic": "major",
        "verb": ["analyze", "compare", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "region_preference": {
        "taskLayer": "explore",
        "topic": "region",
        "verb": ["analyze", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "career_direction": {
        "taskLayer": "explore",
        "topic": "career",
        "verb": ["analyze", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "budget_tuition": {
        "taskLayer": "explore",
        "topic": ["plan", "school", "major"],
        "verb": ["analyze", "explain", "recommend"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "plan_review_strategy": {
        "taskLayer": "plan",
        "topic": "plan",
        "verb": ["analyze", "review", "explain", "recommend", "query"],
        "sideEffect": "readonly",
        "minConfidence": 0.8,
    },
    "plan_operations": {
        "taskLayer": "plan",
        "topic": "plan",
        "verb": ["add", "remove", "move", "sort", "replace", "review", "analyze"],
        "sideEffect": "preview",
        "minConfidence": 0.8,
    },
    "followup_guard": {
        "taskLayer": ["general", "explore", "intent", "plan"],
        "topic": ["general", "plan", "major", "score", "requirement"],
        "verb": ["confirm", "reject", "clarify", "explain", "analyze"],
        "sideEffect": ["readonly", "none"],
        "minConfidence": 0.75,
    },
}

_SEMANTIC_EXPECTATION_OVERRIDES: tuple[tuple[set[str], dict[str, Any]], ...] = (
    (
        {"subject_combination", "liberal_arts_employment"},
        {
            "taskLayer": "explore",
            "topic": ["score", "career", "major"],
            "verb": ["analyze", "explain", "recommend"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {"score_profile"},
        {
            "taskLayer": "explore",
            "topic": "score",
            "verb": ["analyze", "explain", "recommend"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {"special_plan", "medical_check", "vision", "english_oral_test", "application_requirement", "extra_points"},
        {
            "taskLayer": "explore",
            "topic": ["policy", "requirement"],
            "verb": ["query", "analyze", "explain", "recommend"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {
            "soft_major_intent",
            "hard_major_constraint",
            "soft_region_intent",
            "negative_region_intent",
            "positive_major_intent",
            "explicit_major_requirement",
            "positive_region_intent",
            "explicit_region_requirement",
            "negative_region_requirement",
        },
        {
            "taskLayer": "intent",
            "topic": ["major", "region"],
            "verb": ["set_preference", "set_constraint", "remove_preference", "analyze", "explain"],
            "sideEffect": "preview",
            "minConfidence": 0.8,
        },
    ),
    (
        {"hard_major_constraint", "explicit_major_requirement"},
        {
            "taskLayer": "intent",
            "topic": "major",
            "verb": ["set_constraint", "remove_preference", "analyze", "explain"],
            "sideEffect": "preview",
            "minConfidence": 0.8,
        },
    ),
    (
        {"region_safety_tradeoff", "city_opportunity", "backup_region", "remote_area", "return_home"},
        {
            "taskLayer": "explore",
            "topic": "region",
            "verb": ["analyze", "explain", "recommend"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {"plan_query", "plan_analysis", "plan_status", "tuition_info", "school_level"},
        {
            "taskLayer": "plan",
            "topic": "plan",
            "verb": ["query", "analyze", "review", "explain"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {"plan_review", "risk_summary", "safe_plan", "avoid_risk"},
        {
            "taskLayer": "plan",
            "topic": "plan",
            "verb": ["review", "analyze", "explain"],
            "sideEffect": "readonly",
            "minConfidence": 0.8,
        },
    ),
    (
        {"sort_ordered_plan", "move_ordered_unit", "remove_units", "add_units", "majorGroup_model", "majorGroup_operations"},
        {
            "taskLayer": "plan",
            "topic": "plan",
            "verb": ["add", "remove", "move", "sort", "replace"],
            "sideEffect": "preview",
            "minConfidence": 0.8,
        },
    ),
    (
        {"no_pending_guard", "confirm_guard", "readonly_closure_ack", "vague_confirm", "readonly_no_workspace_card"},
        {
            "taskLayer": ["general", "plan"],
            "topic": ["general", "plan"],
            "verb": ["confirm", "reject", "clarify"],
            "sideEffect": ["readonly", "none"],
            "minConfidence": 0.75,
        },
    ),
)


def _merge_unique_list(base: Any, override: Any) -> list[Any]:
    result: list[Any] = []
    for value in base or []:
        if value not in result:
            result.append(value)
    for value in override or []:
        if value not in result:
            result.append(value)
    return result


def _merge_prompt_defaults(prompt_defaults: dict[str, Any], prompt: Any) -> dict[str, Any]:
    if isinstance(prompt, str):
        step = {"prompt": prompt}
    elif isinstance(prompt, dict):
        step = dict(prompt)
    else:
        step = {"prompt": str(prompt)}
    merged = deepcopy(prompt_defaults)
    merged.update(step)
    for key in ("assertNotContains", "assertThinkingNotContains", "forbiddenPatterns", "qualityFocus"):
        if key in prompt_defaults or key in step:
            merged[key] = _merge_unique_list(prompt_defaults.get(key), step.get(key))
    return merged


def _expand_case_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("cases file must be a JSON array or object with cases")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("cases file object must contain a cases array")
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    prompt_defaults = defaults.get("promptDefaults") if isinstance(defaults.get("promptDefaults"), dict) else {}
    case_defaults = {key: deepcopy(value) for key, value in defaults.items() if key != "promptDefaults"}
    cases: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("each case must be a JSON object")
        merged = deepcopy(case_defaults)
        merged.update(raw_case)
        for key in ("flow", "coverage"):
            if key in case_defaults or key in raw_case:
                merged[key] = _merge_unique_list(case_defaults.get(key), raw_case.get(key))
        raw_prompts = raw_case.get("prompts")
        if raw_prompts is None and "prompt" in raw_case:
            raw_prompts = [raw_case["prompt"]]
        if raw_prompts is None:
            raw_prompts = []
        if not isinstance(raw_prompts, list):
            raise ValueError(f"case {merged.get('name') or '<unnamed>'} prompts must be a JSON array")
        merged.pop("prompt", None)
        merged["prompts"] = [_merge_prompt_defaults(prompt_defaults, prompt) for prompt in raw_prompts]
        cases.append(merged)
    return cases


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_payload(path: str) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_normalize_text(item) for item in value if _normalize_text(item)]


def _normalize_expected_semantic_frame(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    expected: dict[str, Any] = {}
    for field in _SEMANTIC_FRAME_FIELDS:
        raw = value.get(field)
        if isinstance(raw, list):
            values = [_normalize_text(item) for item in raw]
            values = [item for item in values if item]
            if values:
                expected[field] = list(dict.fromkeys(values))
            continue
        text = _normalize_text(raw)
        if text:
            expected[field] = text
    min_confidence = value.get("minConfidence")
    if min_confidence is not None and min_confidence != "":
        try:
            expected["minConfidence"] = float(min_confidence)
        except (TypeError, ValueError):
            pass
    return expected


def _semantic_expectation_from_coverage(coverage: Any) -> dict[str, Any]:
    coverage_tags = set(_normalize_text_list(coverage))
    if not coverage_tags:
        return {}
    for tags, expected in _SEMANTIC_EXPECTATION_OVERRIDES:
        if coverage_tags & tags:
            return _normalize_expected_semantic_frame(expected)
    for tag in (
        "score_profile",
        "eligibility_constraints",
        "major_preference",
        "region_preference",
        "career_direction",
        "budget_tuition",
        "plan_review_strategy",
        "plan_operations",
        "followup_guard",
    ):
        if tag in coverage_tags:
            return _normalize_expected_semantic_frame(_SEMANTIC_EXPECTATION_PRESETS[tag])
    return {}


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", _normalize_text(value))


def _strip_known_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    value = _normalize_text(text)
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix) :].strip(" ：:，,。；;")
                changed = True
                break
    return value


def _as_int_ms(value: Any, *, seconds: bool = False) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if seconds:
        return int(number * 1000)
    return int(number)


def _latency_budget_from_prompt(prompt: dict[str, Any]) -> dict[str, int]:
    budget: dict[str, int] = {}
    warn_ms = _as_int_ms(prompt.get("warnElapsedSeconds"), seconds=True)
    max_ms = _as_int_ms(prompt.get("maxElapsedSeconds"), seconds=True)
    if warn_ms is not None:
        budget["warnElapsedMs"] = warn_ms
    if max_ms is not None:
        budget["maxElapsedMs"] = max_ms
    return budget


def _first_tag_mapping(tags: list[str], mapping: dict[str, str]) -> str | None:
    for tag in tags:
        if tag in mapping:
            return mapping[tag]
    return None


def _is_soft_expected_route(route: str | None) -> bool:
    return bool(route and route in _SOFT_EXPECTED_ROUTES)


def _expected_route_from_metadata(step_coverage: list[str], prompt_text: str) -> str | None:
    if "readonly_closure_ack" in step_coverage:
        return "readonly_closure_ack"
    if prompt_text in {"确认", "确认执行", "确认这个偏好", "确认这个要求"}:
        if any(
            tag in step_coverage
            for tag in (
                "soft_major_intent",
                "hard_major_constraint",
                "positive_major_intent",
                "explicit_major_requirement",
                "positive_region_intent",
                "explicit_region_requirement",
                "negative_region_requirement",
            )
        ):
            return "direct_pending_intent_confirm"
        if "preview_confirm_boundary" in step_coverage or "preview_confirm_apply" in step_coverage:
            return "direct_pending_plan_confirm"
    return _first_tag_mapping(step_coverage, _EXPECTED_ROUTES_BY_COVERAGE)


def _expected_action_from_metadata(step_coverage: list[str], prompt_text: str) -> str | None:
    if "readonly_closure_ack" in step_coverage:
        return None
    if prompt_text in {"确认", "确认执行"} and (
        "no_pending_guard" in step_coverage
        or "no_pending_intent" in step_coverage
        or "readonly_no_workspace_card" in step_coverage
        or "readonly_no_pending_intent" in step_coverage
    ):
        return None
    if prompt_text in {"确认这个偏好", "确认这个要求"} and (
        "soft_major_intent" in step_coverage
        or "hard_major_constraint" in step_coverage
        or "positive_major_intent" in step_coverage
        or "explicit_major_requirement" in step_coverage
    ):
        return "apply_selected_intents"
    if prompt_text == "确认" and "no_pending_guard" in step_coverage:
        return None
    return _first_tag_mapping(step_coverage, _EXPECTED_ACTIONS_BY_COVERAGE)


def _load_case_definitions(path: str) -> dict[str, dict[str, Any]]:
    """Load runner case metadata keyed by case#stepIndex.

    The report remains usable without case definitions, but these definitions
    let it summarize scenario coverage and apply per-step latency budgets.
    """
    data = _load_json(path)
    cases = _expand_case_payload(data) if isinstance(data, dict) and isinstance(data.get("defaults"), dict) else data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"expected case definition list in {path}")

    definitions: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_name = _normalize_text(case.get("name"))
        if not case_name:
            continue
        flow = _normalize_text_list(case.get("flow"))
        coverage = _normalize_text_list(case.get("coverage"))
        prompts = case.get("prompts") if isinstance(case.get("prompts"), list) else []
        for step_index, prompt in enumerate(prompts, start=1):
            if not isinstance(prompt, dict):
                continue
            step_coverage = coverage + [
                tag for tag in _normalize_text_list(prompt.get("coverage")) if tag not in coverage
            ]
            metadata: dict[str, Any] = {
                "case": case_name,
                "stepIndex": step_index,
                "recordKey": f"{case_name}#{step_index}",
                "sessionId": case.get("sessionId"),
                "flow": flow,
                "coverage": step_coverage,
                "prompt": _normalize_text(prompt.get("prompt")),
                "assertPlanStyle": bool(case.get("assertPlanStyle") or prompt.get("assertPlanStyle")),
            }
            latency_budget = _latency_budget_from_prompt(prompt)
            if latency_budget:
                metadata["latencyBudget"] = latency_budget
            prompt_text = _normalize_text(prompt.get("prompt"))
            expected_route = _normalize_text(prompt.get("expectedRoutingPath")) or _expected_route_from_metadata(step_coverage, prompt_text)
            expected_no_action = bool(prompt.get("expectedNoAction"))
            if expected_no_action:
                metadata["expectedNoAction"] = True
            expected_action = "" if expected_no_action else (
                _normalize_text(prompt.get("expectedActionFamily")) or _expected_action_from_metadata(step_coverage, prompt_text)
            )
            if expected_route:
                metadata["expectedRoutingPath"] = expected_route
            if expected_action:
                metadata["expectedActionFamily"] = expected_action
            expected_semantic_frame = _normalize_expected_semantic_frame(prompt.get("expectedSemanticFrame"))
            if expected_semantic_frame:
                metadata["expectedSemanticFrame"] = expected_semantic_frame
                metadata["expectedSemanticFrameSource"] = "explicit"
            else:
                inferred_semantic_frame = _semantic_expectation_from_coverage(metadata.get("coverage"))
                if inferred_semantic_frame:
                    metadata["expectedSemanticFrame"] = inferred_semantic_frame
                    metadata["expectedSemanticFrameSource"] = "inferred"
            assertions = {
                field: prompt.get(field)
                for field in _ASSERTION_FIELDS
                if field in prompt
            }
            if assertions:
                metadata["assertions"] = assertions
            quality_expectations = {
                field: prompt.get(field)
                for field in _QUALITY_EXPECTATION_FIELDS
                if field in prompt
            }
            if quality_expectations:
                metadata["qualityExpectations"] = quality_expectations
            definitions[metadata["recordKey"]] = metadata
    return definitions


def _merge_case_definition_indexes(paths: list[str]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for path in paths:
        definitions.update(_load_case_definitions(path))
    return definitions


def _merge_record_metadata(record: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return dict(record)
    merged = dict(record)
    merged["caseMetadata"] = dict(metadata)
    for key in (
        "sessionId",
        "flow",
        "coverage",
        "latencyBudget",
        "assertPlanStyle",
        "expectedRoutingPath",
        "expectedActionFamily",
        "expectedNoAction",
        "expectedSemanticFrame",
        "expectedSemanticFrameSource",
        "assertions",
        "qualityExpectations",
    ):
        value = metadata.get(key)
        if value not in (None, "", []):
            merged[key] = value
    if not _normalize_text(merged.get("prompt")) and _normalize_text(metadata.get("prompt")):
        merged["prompt"] = metadata["prompt"]
    return merged


def _extract_text(record: dict[str, Any]) -> str:
    return _normalize_text(record.get("responseText") or record.get("text") or record.get("reply") or "")


def _has_response_text_field(record: dict[str, Any]) -> bool:
    return any(key in record for key in ("responseText", "text", "reply"))


def _extract_error_text(record: dict[str, Any]) -> str:
    return _normalize_text(record.get("wsError") or record.get("error") or "")


def _extract_thinking(record: dict[str, Any]) -> str:
    thinking = record.get("thinkingText") or record.get("thinking") or ""
    if isinstance(thinking, list):
        return "\n".join(_normalize_text(item) for item in thinking if _normalize_text(item))
    return _normalize_text(thinking)


def _clamp_score(value: int) -> int:
    return max(0, min(5, value))


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _turn_observability(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("turnObservability")
    return value if isinstance(value, dict) else {}


def _extract_semantic_frame_observation(record: dict[str, Any]) -> dict[str, Any]:
    direct = record.get("semanticFrameObservation")
    if isinstance(direct, dict):
        return direct
    observability = _turn_observability(record)
    value = observability.get("semanticFrameObservation")
    if isinstance(value, dict):
        return value
    route_decision = record.get("routeDecision") or observability.get("routeDecision")
    if isinstance(route_decision, dict):
        value = route_decision.get("semanticFrameObservation")
        if isinstance(value, dict):
            return value
    return {}


def _semantic_frame_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    frame = observation.get("frame")
    return frame if isinstance(frame, dict) else {}


def _semantic_mapped_route_from_frame(frame: dict[str, Any]) -> str | None:
    """Map a SemanticIntentFrame to the nearest current routing path.

    This is intentionally report-only.  It lets semantic frame evaluations build a
    confusion matrix without changing ChatService routing behavior.
    """
    if not frame:
        return None
    layer = _normalize_text(frame.get("taskLayer"))
    verb = _normalize_text(frame.get("verb"))
    topic = _normalize_text(frame.get("topic"))
    side_effect = _normalize_text(frame.get("sideEffect"))

    if layer == "general":
        return None

    if side_effect == "apply" or verb == "confirm":
        if layer == "intent":
            return "direct_pending_intent_confirm"
        if layer == "plan":
            return "direct_pending_plan_confirm"
        return None

    if layer == "intent":
        if side_effect == "readonly":
            return "zhiyuan_agent_direct"
        return "zhiyuan_agent_direct"

    if layer == "explore":
        return "zhiyuan_agent_direct"

    if layer == "plan":
        if topic == "region" and verb in {"analyze", "explain"}:
            return "region_safety_tradeoff_route"
        if verb == "review":
            return "zhiyuan_agent_direct"
        if verb in {"add", "remove", "move", "sort", "replace", "generate"}:
            return "zhiyuan_agent_direct"
        if verb in {"query", "analyze", "explain", "recommend"}:
            return "zhiyuan_agent_direct"
        return "zhiyuan_agent_direct"

    return None


def _semantic_mapped_route(record: dict[str, Any]) -> str | None:
    observation = _extract_semantic_frame_observation(record)
    if observation.get("status") != "success":
        return None
    return _semantic_mapped_route_from_frame(_semantic_frame_from_observation(observation))


def _expected_semantic_frame(record: dict[str, Any]) -> dict[str, Any]:
    return _normalize_expected_semantic_frame(record.get("expectedSemanticFrame"))


def _semantic_frame_matches_expected(frame: dict[str, Any], expected: dict[str, Any]) -> tuple[bool | None, list[str]]:
    if not expected:
        return None, []
    if not frame:
        return False, ["missing_frame"]

    mismatches: list[str] = []
    for field in _SEMANTIC_FRAME_FIELDS:
        expected_raw = expected.get(field)
        expected_values = (
            [_normalize_text(item) for item in expected_raw]
            if isinstance(expected_raw, list)
            else [_normalize_text(expected_raw)]
        )
        expected_values = [item for item in expected_values if item]
        if not expected_values:
            continue
        actual_value = _normalize_text(frame.get(field))
        if actual_value not in expected_values:
            expected_text = "|".join(expected_values)
            mismatches.append(f"{field}:{expected_text}!={actual_value or '-'}")

    min_confidence = expected.get("minConfidence")
    if isinstance(min_confidence, (int, float)):
        try:
            actual_confidence = float(frame.get("confidence") or 0)
        except (TypeError, ValueError):
            actual_confidence = 0.0
        if actual_confidence < float(min_confidence):
            mismatches.append(f"confidence:{actual_confidence:.2f}<{float(min_confidence):.2f}")

    return not mismatches, mismatches


def _semantic_expectation_result(record: dict[str, Any]) -> dict[str, Any]:
    expected = _expected_semantic_frame(record)
    if not expected:
        return {}
    observation = _extract_semantic_frame_observation(record)
    status = _normalize_text(observation.get("status"))
    if status != "success":
        return {
            "expected": expected,
            "status": status or "missing",
            "matched": None,
            "mismatches": [],
        }
    frame = _semantic_frame_from_observation(observation)
    matched, mismatches = _semantic_frame_matches_expected(frame, expected)
    return {
        "expected": expected,
        "status": status or "missing",
        "matched": matched,
        "mismatches": mismatches,
    }


def _extract_routing_path(record: dict[str, Any]) -> str | None:
    direct = _normalize_text(record.get("routingPath"))
    if direct:
        return direct
    observability = _turn_observability(record)
    route = _normalize_text(observability.get("routingPath"))
    if route:
        return route
    route_decision = record.get("routeDecision") or observability.get("routeDecision")
    if isinstance(route_decision, dict):
        route = _normalize_text(route_decision.get("routingPath") or route_decision.get("route") or route_decision.get("name"))
        if route:
            return route
    return None


def _extract_action_families(record: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        text = _normalize_text(value)
        if text and text not in values:
            values.append(text)

    add(record.get("actionFamily"))
    observability = _turn_observability(record)
    for value in observability.get("actionFamilies") or []:
        add(value)
    for item in record.get("toolCalls") or observability.get("toolCalls") or []:
        if isinstance(item, dict):
            add(item.get("actionFamily"))
    return values


def _extract_tool_names(record: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        text = _normalize_text(value)
        if text and text not in values:
            values.append(text)

    observability = _turn_observability(record)
    for item in record.get("toolCalls") or observability.get("toolCalls") or []:
        if isinstance(item, dict):
            add(item.get("name"))
        else:
            add(item)
    return values


def _extract_tool_names_sequence(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for container in (
        record.get("toolCalls"),
        _turn_observability(record).get("toolCalls"),
    ):
        if not isinstance(container, list):
            continue
        for item in container:
            text = _normalize_text(item.get("name") if isinstance(item, dict) else item)
            if text:
                values.append(text)
        if values:
            return values
    return values


def _route_decision(record: dict[str, Any]) -> dict[str, Any]:
    direct = record.get("routeDecision")
    if isinstance(direct, dict):
        return direct
    observability = _turn_observability(record)
    value = observability.get("routeDecision")
    return value if isinstance(value, dict) else {}


def _extract_tool_trial(record: dict[str, Any]) -> dict[str, Any]:
    for value in (
        _route_decision(record).get("toolTrial"),
        _turn_observability(record).get("toolTrial"),
        record.get("toolTrial"),
    ):
        if isinstance(value, dict):
            tool_names = _normalize_text_list(value.get("toolNames"))
            tool_counts = {
                _normalize_text(key): int(count)
                for key, count in (value.get("toolNameCounts") or {}).items()
                if _normalize_text(key) and isinstance(count, int)
            } if isinstance(value.get("toolNameCounts"), dict) else {}
            if not tool_counts and tool_names:
                for name in tool_names:
                    tool_counts[name] = tool_counts.get(name, 0) + 1
            repeated = _normalize_text_list(value.get("repeatedToolNames"))
            if not repeated and tool_counts:
                repeated = [name for name, count in tool_counts.items() if count > 1]
            return {
                **value,
                "toolNames": tool_names,
                "toolNameCounts": tool_counts,
                "repeatedToolNames": repeated,
                "hasRepeatedToolCalls": bool(value.get("hasRepeatedToolCalls") or repeated),
                "hasToolCalls": bool(value.get("hasToolCalls") or tool_names),
            }

    tool_names = _extract_tool_names_sequence(record)
    counts: dict[str, int] = {}
    for name in tool_names:
        counts[name] = counts.get(name, 0) + 1
    repeated = [name for name, count in counts.items() if count > 1]
    return {
        "toolNames": tool_names,
        "toolNameCounts": counts,
        "repeatedToolNames": repeated,
        "hasRepeatedToolCalls": bool(repeated),
        "hasToolCalls": bool(tool_names),
        "source": "synthesized_from_toolCalls" if tool_names else "missing",
    }


def _agent_run_observability(record: dict[str, Any]) -> dict[str, Any]:
    value = _route_decision(record).get("agentRun")
    return value if isinstance(value, dict) else {}


def _slowest_agent_node(record: dict[str, Any]) -> dict[str, Any] | None:
    agent_run = _agent_run_observability(record)
    nodes = agent_run.get("nodeTimings")
    if not isinstance(nodes, list):
        return None
    valid_nodes = [node for node in nodes if isinstance(node, dict) and _as_int_ms(node.get("durationMs")) is not None]
    if not valid_nodes:
        return None
    return max(valid_nodes, key=lambda node: _as_int_ms(node.get("durationMs")) or 0)


def _record_case_id(record: dict[str, Any]) -> str:
    key = _normalize_text(record.get("recordKey"))
    if key:
        return key
    case = _normalize_text(record.get("case"))
    step_index = record.get("stepIndex")
    if case and step_index not in (None, ""):
        return f"{case}#{step_index}"
    return case or "-"


def _record_coverage_tags(record: dict[str, Any]) -> list[str]:
    return _normalize_text_list(record.get("coverage"))


def _infer_problem_type(record: dict[str, Any]) -> str:
    tags = set(_record_coverage_tags(record))
    prompt = _normalize_text(record.get("prompt"))
    if tags & {"skill_requirement", "major_semantics", "architecture_major"}:
        return "专业信息/学习要求咨询"
    if tags & {"major_compare", "major_preference"}:
        return "专业简称/懒输入比较"
    if tags & {
        "soft_major_intent",
        "hard_major_constraint",
        "soft_region_intent",
        "negative_region_intent",
        "positive_major_intent",
        "explicit_major_requirement",
        "positive_region_intent",
        "explicit_region_requirement",
        "negative_region_requirement",
    }:
        return "意向影响预览"
    if tags & {"career_explore", "career_direction"}:
        return "职业方向承接"
    if tags & {"sort_ordered_plan", "move_ordered_unit", "remove_units", "add_units", "majorGroup_operations"}:
        return "方案调整预览"
    if tags & {"plan_review", "review_plan", "risk_summary", "safe_plan", "avoid_risk"}:
        return "方案审查/风险分析"
    if tags & {"region_safety_tradeoff", "city_opportunity", "backup_region", "remote_area", "return_home"}:
        return "地域安全取舍"
    if tags & {"special_plan", "medical_check", "vision", "english_oral_test", "application_requirement", "extra_points"}:
        return "政策/资格/要求咨询"
    if "审查" in prompt:
        return "方案审查/风险分析"
    if any(token in prompt for token in ("排序", "移动", "去掉", "加进", "调稳", "别冒险")):
        return "方案调整预览"
    if any(token in prompt for token in ("考公", "就业", "读研", "体制内")):
        return "职业方向承接"
    return "未分类"


def _infer_expected_scene(record: dict[str, Any]) -> str:
    expected_route = _normalize_text(record.get("expectedRoutingPath"))
    expected_action = _normalize_text(record.get("expectedActionFamily"))
    tags = set(_record_coverage_tags(record))
    if expected_route.startswith("plan_") or expected_action in {
        "query_state",
        "review_plan",
        "sort_ordered_plan",
        "move_unit",
        "remove_units",
        "add_units",
    } or any(tag.startswith("plan") or tag in {"sort_ordered_plan", "move_ordered_unit", "remove_units", "add_units"} for tag in tags):
        return "plan"
    if "intent" in expected_route or expected_action == "preview_intent_change" or tags & {
        "soft_major_intent",
        "hard_major_constraint",
        "soft_region_intent",
        "negative_region_intent",
        "positive_major_intent",
        "explicit_major_requirement",
        "positive_region_intent",
        "explicit_region_requirement",
        "negative_region_requirement",
    }:
        return "intent"
    if expected_action in {"compare_entities", "explore_topic"} or tags & {
        "career_explore",
        "career_direction",
        "major_compare",
        "major_preference",
        "region_safety_tradeoff",
        "special_plan",
    }:
        return "explore"
    return "unknown"


def _record_result_label(record: dict[str, Any], issue_types: list[str]) -> str:
    error = _extract_error_text(record)
    if error:
        return f"error:{error[:80]}"
    elapsed_ms = _as_int_ms(record.get("elapsedMs"))
    if "timeout_or_error" in issue_types:
        return "timeout_or_error"
    if isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_VERY_SLOW_MS:
        return "very_slow"
    if isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_SLOW_MS:
        return "slow"
    return "completed"


def _tool_call_count(record: dict[str, Any], tool_trial: dict[str, Any]) -> int:
    observability = _turn_observability(record)
    for value in (
        record.get("toolCallCount"),
        observability.get("toolCallCount"),
        _route_decision(record).get("toolCallCount"),
    ):
        number = _as_int_ms(value)
        if number is not None:
            return number
    return len(tool_trial.get("toolNames") or [])


def _tool_calls_have_error_result(record: dict[str, Any]) -> bool:
    for item in _turn_observability(record).get("toolCalls") or record.get("toolCalls") or []:
        if not isinstance(item, dict):
            continue
        if item.get("success") is False:
            return True
        if _normalize_text(item.get("resultKind")) == "error":
            return True
    return False


def _llm_request_count(record: dict[str, Any]) -> int | None:
    observability = _turn_observability(record)
    route_decision = _route_decision(record)
    for value in (
        record.get("llmRequests"),
        observability.get("llmRequests"),
        route_decision.get("llmRequests"),
    ):
        number = _as_int_ms(value)
        if number is not None:
            return number
    return None



def _classify_bad_tool_trial(record: dict[str, Any], tool_trial: dict[str, Any]) -> list[str]:
    issue_types: list[str] = []
    elapsed_ms = _as_int_ms(record.get("elapsedMs"))
    first_hint_ms = _as_int_ms(record.get("firstMessageMs"))
    tool_call_count = _tool_call_count(record, tool_trial)
    has_tools = bool(tool_trial.get("hasToolCalls") or tool_trial.get("toolNames"))
    agent_run = _agent_run_observability(record)
    failed_node = _normalize_text(agent_run.get("failedNode"))
    first_tool_call_ms = _as_int_ms(agent_run.get("firstToolCallAtMs"))
    slowest_node = _slowest_agent_node(record)
    slowest_node_ms = _as_int_ms((slowest_node or {}).get("durationMs"))

    def add(value: str) -> None:
        if value not in issue_types:
            issue_types.append(value)

    if _extract_error_text(record):
        add("timeout_or_error")
    if failed_node:
        add("agent_run_interrupted")
    if failed_node and not has_tools:
        add("first_model_request_or_final_generation_interrupted")
    if _tool_calls_have_error_result(record):
        add("tool_result_error")
    if tool_trial.get("repeatedToolNames"):
        add("repeated_tool_calls")
    if has_tools and tool_call_count >= _TOOL_CHAIN_MANY_TOOLS:
        add("many_tool_calls")
    if has_tools and isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_SLOW_MS:
        add("slow_tool_chain")
    if has_tools and isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_VERY_SLOW_MS:
        add("very_slow_tool_chain")
    if not has_tools and isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_SLOW_MS:
        add("slow_agent_run")
        if elapsed_ms >= _TOOL_CHAIN_VERY_SLOW_MS:
            add("very_slow_agent_run")
        if not first_tool_call_ms:
            add("slow_before_first_tool_or_final_generation")
    if slowest_node and isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_SLOW_MS:
        add("slow_agent_node")
    if isinstance(first_tool_call_ms, int) and first_tool_call_ms >= _TOOL_CHAIN_SLOW_MS:
        add("late_first_tool_call")
    if isinstance(slowest_node_ms, int) and slowest_node_ms >= _TOOL_CHAIN_SLOW_MS:
        add("very_slow_agent_node")
    if has_tools and isinstance(elapsed_ms, int) and elapsed_ms >= _TOOL_CHAIN_SLOW_MS and not _extract_thinking(record):
        add("missing_progress_for_long_task")
    if has_tools and isinstance(first_hint_ms, int) and first_hint_ms >= _TOOL_CHAIN_SLOW_MS:
        add("late_first_hint")
    expected_route = _normalize_text(record.get("expectedRoutingPath"))
    route = _normalize_text(_extract_routing_path(record))
    if route and expected_route and expected_route != route:
        add("expected_route_mismatch")
    return issue_types


def _build_tool_chain_issue(record: dict[str, Any]) -> dict[str, Any] | None:
    route = _normalize_text(_extract_routing_path(record))
    tool_trial = _extract_tool_trial(record)
    issue_types = _classify_bad_tool_trial(record, tool_trial)
    has_tool_observability = bool(tool_trial.get("hasToolCalls") or tool_trial.get("toolNames"))
    if not route and not _extract_error_text(record) and not has_tool_observability:
        return None
    if not issue_types:
        return None

    return {
        "caseId": _record_case_id(record),
        "userPrompt": _normalize_text(record.get("prompt")),
        "problemType": _infer_problem_type(record),
        "expectedScene": _infer_expected_scene(record),
        "expectedRoutingPath": _normalize_text(record.get("expectedRoutingPath")) or None,
        "expectedActionFamily": _normalize_text(record.get("expectedActionFamily")) or None,
        "actualRoutingPath": route or None,
        "toolNames": tool_trial.get("toolNames") or [],
        "repeatedToolNames": tool_trial.get("repeatedToolNames") or [],
        "badToolTrial": True,
        "issueTypes": issue_types,
        "agentRun": _agent_run_observability(record) or None,
        "slowestAgentNode": _slowest_agent_node(record),
        "llmRequests": _llm_request_count(record),
        "toolCallCount": _tool_call_count(record, tool_trial),
        "elapsedMs": _as_int_ms(record.get("elapsedMs")),
        "firstHintMs": _as_int_ms(record.get("firstMessageMs")),
        "result": _record_result_label(record, issue_types),
    }


def _action_observed(record: dict[str, Any], expected_action: str) -> bool:
    if not expected_action:
        return False
    aliases = _ACTION_TOOL_ALIASES.get(expected_action, ())
    action_families = _extract_action_families(record)
    if expected_action in action_families or any(alias in action_families for alias in aliases):
        return True
    tool_names = set(_extract_tool_names(record))
    return any(tool_name in tool_names for tool_name in aliases)


def _distribution_coverage(text: str) -> list[str]:
    coverage: list[str] = []
    for name, tokens in _DISTRIBUTION_SIGNALS.items():
        if _contains_any(text, tokens):
            coverage.append(name)
    return coverage


def _is_preview_or_example_case(record: dict[str, Any], text: str) -> bool:
    case_name = _normalize_text(record.get("case")).lower()
    if "intent" in case_name:
        return False
    action_family = _normalize_text(record.get("actionFamily"))
    observed_actions = set(_extract_action_families(record))
    point_mutation_actions = {
        "move_unit",
        "move_ordered_unit",
        "add_units",
        "remove_units",
        "remove_ordered_unit",
        "replace_units",
    }
    if action_family in point_mutation_actions or observed_actions & point_mutation_actions:
        return False
    coverage = record.get("coverage")
    if isinstance(coverage, list) and "career_short_prompt" in {str(item) for item in coverage}:
        return False
    quality_focus = record.get("qualityFocus")
    if isinstance(quality_focus, list):
        focuses = {str(item) for item in quality_focus}
        if "multi_distribution" in focuses:
            return True
    prompt = _normalize_text(record.get("prompt"))
    if prompt in {"确认", "确认执行", "确认这个偏好", "确认这个要求"}:
        return False
    if _contains_any(text, _EMPTY_RESULT_TOKENS):
        return False
    combined = f"{prompt}\n{text}"
    return _contains_any(combined, _PREVIEW_HINT_TOKENS)


def _has_unqualified_pending_effective_wording(text: str) -> bool:
    if not _contains_any(text, _PENDING_CONTEXT_TOKENS):
        return False

    for raw_line in text.splitlines():
        line = raw_line.strip(" -\t")
        if not line:
            continue
        if _contains_any(line, _READONLY_REFERENCE_BOUNDARY_TOKENS):
            continue
        if _contains_any(line, _PENDING_CONDITIONAL_TOKENS):
            continue
        if any(pattern.search(line) for pattern in _UNQUALIFIED_PENDING_EFFECTIVE_PATTERNS):
            return True
    return False


def _is_no_action_ack_case(record: dict[str, Any], text: str) -> bool:
    if not record.get("expectedNoAction"):
        return False
    return (
        _contains_any(text, ("没有待确认", "没有待执行", "没有上一轮待确认"))
        and _contains_any(text, ("不会改动方案", "不会改动当前方案", "不会改动"))
    )


def _term_present(text: str, term: str) -> bool:
    compact_text = _compact_text(text)
    compact_term = _compact_text(term)
    if not compact_term:
        return True
    if compact_term in compact_text:
        return True
    for canonical, aliases in _KEYPOINT_TERM_ALIASES:
        if _compact_text(canonical) != compact_term:
            continue
        return any(_compact_text(alias) in compact_text for alias in aliases)
    return False


def _extract_key_terms(expectation: str) -> list[str]:
    value = _strip_known_prefix(expectation, _EXPECTATION_META_PREFIXES)
    if not value:
        return []
    parts = re.split(r"[、/,，,；;和及与或\s]+", value)
    terms = [part.strip(" ：:。()（）[]【】") for part in parts if part.strip(" ：:。()（）[]【】")]
    return terms or [value]


def _keypoint_satisfied(text: str, expectation: str) -> bool:
    value = _strip_known_prefix(expectation, _EXPECTATION_META_PREFIXES)
    if not value:
        return True
    if _term_present(text, value):
        return True
    terms = _extract_key_terms(expectation)
    if not terms:
        return True
    matched = sum(1 for term in terms if _term_present(text, term))
    if len(terms) <= 2:
        return matched == len(terms)
    return matched >= 2


def _expected_keypoint_warnings(record: dict[str, Any], text: str) -> list[str]:
    quality_expectations = record.get("qualityExpectations")
    if not isinstance(quality_expectations, dict):
        return []
    warnings: list[str] = []
    for item in _normalize_text_list(quality_expectations.get("expectedKeyPoints")):
        if not _keypoint_satisfied(text, item):
            warnings.append(f"missing_expected_keypoint:{item}")
    for group in quality_expectations.get("expectedKeyPointGroups") or []:
        if not isinstance(group, dict):
            continue
        label = _normalize_text(group.get("label"))
        alternatives = _normalize_text_list(group.get("any"))
        if alternatives and not any(_keypoint_satisfied(text, item) for item in alternatives):
            warnings.append(f"missing_expected_keypoint_group:{label or '/'.join(alternatives[:3])}")
    return warnings


def _forbidden_pattern_violations(record: dict[str, Any], text: str) -> list[str]:
    quality_expectations = record.get("qualityExpectations")
    if not isinstance(quality_expectations, dict):
        return []
    compact_text = _compact_text(text)
    violations: list[str] = []
    for item in _normalize_text_list(quality_expectations.get("forbiddenPatterns")):
        pattern = _strip_known_prefix(item, _FORBIDDEN_META_PREFIXES) or item
        if _compact_text(pattern) and _compact_text(pattern) in compact_text:
            violations.append(f"forbidden_pattern:{item}")
    return violations


def _quality_focuses(record: dict[str, Any]) -> set[str]:
    quality_expectations = record.get("qualityExpectations")
    if not isinstance(quality_expectations, dict):
        return set()
    return set(_normalize_text_list(quality_expectations.get("qualityFocus")))


def _readonly_boundary_required(record: dict[str, Any]) -> bool:
    """Only require explicit no-side-effect wording when the turn can be mistaken for an action.

    Pure explore questions such as "建筑城乡规划要不要美术基础" do not need to
    spend user-facing space saying "不会改方案"; plan/intent/mutation-adjacent
    questions still do.
    """
    if record.get("expectedNoAction"):
        return True
    tags = set(_record_coverage_tags(record))
    if tags & _READONLY_BOUNDARY_REQUIRED_COVERAGE:
        return True
    prompt = _normalize_text(record.get("prompt"))
    return _contains_any(prompt, _READONLY_BOUNDARY_REQUIRED_PROMPT_TOKENS)


def _min_text_length_warn(record: dict[str, Any]) -> int | None:
    quality_expectations = record.get("qualityExpectations")
    if not isinstance(quality_expectations, dict):
        return None
    return _as_int_ms(quality_expectations.get("minTextLengthWarn"))


def _decision_basis_coverage(text: str) -> list[str]:
    coverage: list[str] = []
    for name, tokens in _DECISION_BASIS_SIGNALS.items():
        if _contains_any(text, tokens):
            coverage.append(name)
    return coverage


def _quality_focus_warnings(record: dict[str, Any], text: str) -> list[str]:
    focuses = _quality_focuses(record)
    if not focuses:
        return []

    warnings: list[str] = []
    if (
        "readonly_boundary" in focuses
        and _readonly_boundary_required(record)
        and not _contains_any(text, _READONLY_BOUNDARY_TOKENS)
    ):
        warnings.append("missing_quality_focus:readonly_boundary")
    if "preview_confirm_boundary" in focuses and not _contains_any(text, _PREVIEW_CONFIRM_BOUNDARY_TOKENS):
        warnings.append("missing_quality_focus:preview_confirm_boundary")
    if "actionable_next_step" in focuses and not _contains_any(
        text,
        ("下一步", "可以继续", "如果", "直接说", "告诉我", "建议先", "需要你确认后", "确认后才会"),
    ):
        warnings.append("missing_quality_focus:actionable_next_step")
    if "user_language" in focuses and any(token in text for token in _USER_LANGUAGE_RISK_TOKENS):
        warnings.append("missing_quality_focus:user_language")
    if "rich_decision_basis" in focuses:
        basis = _decision_basis_coverage(text)
        required = 2
        if "multi_distribution" in focuses:
            required = 3
        if len(basis) < required:
            warnings.append(f"missing_quality_focus:rich_decision_basis:{len(basis)}<{required}")

    min_length = _min_text_length_warn(record)
    if min_length is not None and len(text) < min_length:
        warnings.append(f"text_too_short:{len(text)}<{min_length}")
    return warnings


def _quality_violations(record: dict[str, Any], text: str) -> list[str]:
    violations: list[str] = []
    error_text = _extract_error_text(record)
    if error_text:
        violations.append("ws_error:" + error_text)
    for field in ("assertionViolations", "contentViolations", "performanceViolations"):
        values = record.get(field) or []
        if isinstance(values, list):
            violations.extend(_normalize_text(value) for value in values if _normalize_text(value))
        elif _normalize_text(values):
            violations.append(_normalize_text(values))

    leaked_terms = [token for token in _INTERNAL_TERM_PATTERNS if token in text]
    if leaked_terms:
        violations.append("internal_terms:" + ",".join(leaked_terms[:5]))

    if "已生效" in text and "待确认" in text:
        violations.append("pending_boundary_conflict")

    if _has_unqualified_pending_effective_wording(text):
        violations.append("pending_intent_effective_wording")

    violations.extend(_forbidden_pattern_violations(record, text))

    if _is_preview_or_example_case(record, text):
        coverage = _distribution_coverage(text)
        if len(coverage) < 2:
            violations.append("thin_preview_distribution")

    elapsed_ms = record.get("elapsedMs")
    latency_budget = record.get("latencyBudget") if isinstance(record.get("latencyBudget"), dict) else {}
    max_elapsed_ms = latency_budget.get("maxElapsedMs")
    if isinstance(elapsed_ms, int) and isinstance(max_elapsed_ms, int) and elapsed_ms > max_elapsed_ms:
        violations.append(f"latency_max_exceeded:{elapsed_ms}>{max_elapsed_ms}")

    expected_route = _normalize_text(record.get("expectedRoutingPath"))
    actual_route = _extract_routing_path(record)
    if (
        expected_route
        and actual_route
        and actual_route != expected_route
        and not _is_soft_expected_route(expected_route)
    ):
        violations.append(f"route_mismatch:{expected_route}!={actual_route}")

    semantic_expectation = _semantic_expectation_result(record)
    if semantic_expectation and semantic_expectation.get("matched") is False:
        status = _normalize_text(semantic_expectation.get("status")) or "missing"
        mismatches = semantic_expectation.get("mismatches") or []
        if mismatches:
            violations.append("semantic_frame_mismatch:" + ",".join(mismatches[:4]))
        else:
            violations.append(f"semantic_frame_missing:{status}")

    expected_action = _normalize_text(record.get("expectedActionFamily"))
    actual_actions = _extract_action_families(record)
    if expected_action and actual_actions and not _action_observed(record, expected_action):
        violations.append(f"action_family_mismatch:{expected_action}!={','.join(actual_actions[:4])}")
    if record.get("expectedNoAction") and actual_actions:
        violations.append(f"unexpected_action:{','.join(actual_actions[:4])}")

    return violations


def _evaluation_warnings(record: dict[str, Any], text: str) -> list[str]:
    warnings: list[str] = []
    if not isinstance(record.get("caseMetadata"), dict):
        warnings.append("missing_case_metadata")

    for field in ("performanceWarnings",):
        values = record.get(field) or []
        if isinstance(values, list):
            warnings.extend(_normalize_text(value) for value in values if _normalize_text(value))
        elif _normalize_text(values):
            warnings.append(_normalize_text(values))

    elapsed_ms = record.get("elapsedMs")
    latency_budget = record.get("latencyBudget") if isinstance(record.get("latencyBudget"), dict) else {}
    warn_elapsed_ms = latency_budget.get("warnElapsedMs")
    max_elapsed_ms = latency_budget.get("maxElapsedMs")
    if isinstance(elapsed_ms, int) and isinstance(warn_elapsed_ms, int) and elapsed_ms > warn_elapsed_ms:
        if not isinstance(max_elapsed_ms, int) or elapsed_ms <= max_elapsed_ms:
            warnings.append(f"latency_warn_exceeded:{elapsed_ms}>{warn_elapsed_ms}")

    expected_route = _normalize_text(record.get("expectedRoutingPath"))
    expected_action = _normalize_text(record.get("expectedActionFamily"))
    if expected_route and not _extract_routing_path(record):
        warnings.append(f"missing_route_observability:{expected_route}")
    actual_route = _extract_routing_path(record)
    if (
        expected_route
        and actual_route
        and actual_route != expected_route
        and _is_soft_expected_route(expected_route)
    ):
        warnings.append(f"soft_route_not_matched:{expected_route}!={actual_route}")
    if expected_action and not _action_observed(record, expected_action):
        warnings.append(f"missing_action_observability:{expected_action}")
    semantic_expectation = _semantic_expectation_result(record)
    semantic_source = _normalize_text(record.get("expectedSemanticFrameSource"))
    if (
        semantic_expectation
        and semantic_source != "inferred"
        and semantic_expectation.get("status") in {"missing", "disabled", "scheduled", "timeout", "error"}
    ):
        warnings.append(f"semantic_frame_unverified:{semantic_expectation.get('status')}")

    thinking = _extract_thinking(record)
    if isinstance(elapsed_ms, int) and elapsed_ms >= 10000 and not thinking:
        warnings.append("missing_progress_for_long_task")
    warnings.extend(_expected_keypoint_warnings(record, text))
    warnings.extend(_quality_focus_warnings(record, text))
    return warnings


def _route_score(record: dict[str, Any]) -> int:
    expected_route = _normalize_text(record.get("expectedRoutingPath"))
    actual_route = _extract_routing_path(record)
    expected_action = _normalize_text(record.get("expectedActionFamily"))
    actual_actions = _extract_action_families(record)
    expected_no_action = bool(record.get("expectedNoAction"))

    score = 4
    if _is_soft_expected_route(expected_route):
        score = 4
    elif expected_route:
        if actual_route == expected_route:
            score = 5
        elif actual_route:
            score = 1
        else:
            score = 4
    elif actual_route:
        score = 4

    if expected_action:
        if _action_observed(record, expected_action):
            score += 1
        elif actual_actions:
            score -= 2
        else:
            score -= 1
    elif expected_no_action:
        if actual_actions:
            score -= 2
        else:
            score += 1
    elif actual_actions:
        score += 1

    return _clamp_score(score)


def _score_case(record: dict[str, Any]) -> dict[str, Any]:
    text = _extract_text(record)
    thinking = _extract_thinking(record)
    error_text = _extract_error_text(record)
    coverage = _distribution_coverage(text)
    violations = _quality_violations(record, text)
    warnings = _evaluation_warnings(record, text)

    if not text and not _has_response_text_field(record) and not error_text:
        return {
            "correctness": 0,
            "completeness": 0,
            "naturalness": 0,
            "actionability": 0,
            "latency": 0,
            "structure": 0,
            "route": _route_score(record),
            "distributionCoverage": coverage,
            "qualityViolations": [],
            "evaluationWarnings": warnings + ["missing_response_text:run_with_keep_response_text"],
            "routingPath": _extract_routing_path(record),
            "semanticFrameObservation": _extract_semantic_frame_observation(record),
            "semanticMappedRoute": _semantic_mapped_route(record),
            "semanticExpectation": _semantic_expectation_result(record),
            "actionFamilies": _extract_action_families(record),
            "toolNames": _extract_tool_names(record),
            "verdict": "unscored",
        }

    if not text:
        return {
            "correctness": 0,
            "completeness": 0,
            "naturalness": 0,
            "actionability": 0,
            "latency": 0,
            "structure": 0,
            "route": _route_score(record),
            "distributionCoverage": coverage,
            "qualityViolations": violations or (["ws_error:" + error_text] if error_text else ["empty_response"]),
            "evaluationWarnings": warnings,
            "routingPath": _extract_routing_path(record),
            "semanticFrameObservation": _extract_semantic_frame_observation(record),
            "semanticMappedRoute": _semantic_mapped_route(record),
            "semanticExpectation": _semantic_expectation_result(record),
            "actionFamilies": _extract_action_families(record),
            "toolNames": _extract_tool_names(record),
            "verdict": "fail",
        }

    score = {
        "correctness": 2,
        "completeness": 2,
        "naturalness": 2,
        "actionability": 1,
        "latency": 1,
        "structure": 1,
        "route": _route_score(record),
    }

    if _contains_any(text, _DOMAIN_TOKENS):
        score["correctness"] += 1
    if record.get("turnObservability") or record.get("followupCount") is not None:
        score["correctness"] += 1
    if not violations:
        score["correctness"] += 1
    else:
        score["correctness"] -= min(3, len(violations))

    if len(text) > 80:
        score["completeness"] += 1
    if len(text) > 180:
        score["completeness"] += 1
    if thinking:
        score["completeness"] += 1
    if _contains_any(text, _RISK_TOKENS):
        score["completeness"] += 1
    if _is_no_action_ack_case(record, text):
        score["completeness"] += 1
    if _is_preview_or_example_case(record, text):
        if len(coverage) >= 2:
            score["completeness"] += 1
        else:
            score["completeness"] -= 2

    if "\n" in text or "。" in text:
        score["naturalness"] += 1
    if len(text) <= 900:
        score["naturalness"] += 1
    if any(token in text for token in ("[object Object]", "undefined", "null", "false")):
        score["naturalness"] -= 2

    if _contains_any(text, _ACTION_TOKENS):
        score["actionability"] += 2
    if _contains_any(text, ("下一步", "可以继续", "继续问", "直接问我", "可以直接问我", "愿意补充", "补充一下", "优先看", "可以优先", "建议先")):
        score["actionability"] += 1
    if _contains_any(text, _BOUNDARY_TOKENS):
        score["actionability"] += 1
    if _contains_any(text, ("移动", "删除", "加入", "排序", "审查", "补偿", "记成偏好")):
        score["actionability"] += 1

    if _contains_any(text, _STRUCTURE_TOKENS):
        score["structure"] += 2
    if coverage:
        score["structure"] += 1
    if len(coverage) >= 3:
        score["structure"] += 1

    elapsed_ms = record.get("elapsedMs")
    if isinstance(elapsed_ms, int):
        if elapsed_ms <= 3000:
            score["latency"] = 5
        elif elapsed_ms <= 6000:
            score["latency"] = 4
        elif elapsed_ms <= 10000:
            score["latency"] = 3
        elif elapsed_ms <= 30000:
            score["latency"] = 2
        if elapsed_ms > 60000:
            score["latency"] = 0
    elif record.get("firstMessageMs") is not None or record.get("finalMessageMs") is not None:
        score["latency"] = 2

    scored = {key: _clamp_score(value) for key, value in score.items()}
    scored["distributionCoverage"] = coverage
    scored["qualityViolations"] = violations
    scored["evaluationWarnings"] = warnings
    scored["routingPath"] = _extract_routing_path(record)
    scored["semanticFrameObservation"] = _extract_semantic_frame_observation(record)
    scored["semanticMappedRoute"] = _semantic_mapped_route(record)
    scored["semanticExpectation"] = _semantic_expectation_result(record)
    scored["actionFamilies"] = _extract_action_families(record)
    scored["toolNames"] = _extract_tool_names(record)
    has_expected_keypoint_warning = any(
        _normalize_text(item).startswith("missing_expected_keypoint:")
        for item in warnings
    )
    has_quality_focus_warning = any(
        _normalize_text(item).startswith(("missing_quality_focus:", "text_too_short:"))
        for item in warnings
    )
    scored["verdict"] = (
        "fail"
        if violations
        else (
            "needs_review"
            if has_expected_keypoint_warning or has_quality_focus_warning
            else (
                "strong"
                if min(scored["correctness"], scored["completeness"], scored["actionability"], scored["route"]) >= 4
                else "needs_review"
            )
        )
    )
    return scored


def _normalize_flat_record(record: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    normalized = dict(record)
    case = _normalize_text(normalized.get("case"))
    normalized["case"] = case
    normalized["stepIndex"] = step_index
    normalized["recordKey"] = f"{case}#{step_index}"
    normalized["prompt"] = _normalize_text(normalized.get("prompt"))
    return normalized


def _flatten_runner_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    flattened: list[dict[str, Any]] = []
    case_counts: dict[str, int] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        case = _normalize_text(item.get("case"))
        case_counts[case] = case_counts.get(case, 0) + 1
        flattened.append(_normalize_flat_record(item, step_index=case_counts[case]))
    return flattened


def _flatten_provider_benchmark_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    agent_results = payload.get("agent")
    if not isinstance(agent_results, list):
        return []
    grouped: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for provider_result in agent_results:
        if not isinstance(provider_result, dict):
            continue
        provider = _normalize_text(provider_result.get("provider"))
        model = _normalize_text(provider_result.get("model"))
        provider_label = provider or model or "provider"
        for case in provider_result.get("cases") or []:
            if not isinstance(case, dict):
                continue
            case_name = _normalize_text(case.get("name") or f"session-{case.get('sessionId')}")
            for step_index, step in enumerate(case.get("steps") or [], start=1):
                if not isinstance(step, dict):
                    continue
                key = (provider, model, case_name, step_index)
                current = grouped.get(key)
                record = {
                    "case": case_name,
                    "stepIndex": step_index,
                    "recordKey": f"{case_name}#{step_index}",
                    "prompt": _normalize_text(step.get("prompt")),
                    "responseText": _normalize_text(step.get("text") or step.get("responseText")),
                    "thinkingText": _extract_thinking(step),
                    "elapsedMs": _as_int_ms(step.get("final_seconds"), seconds=True) if step.get("final_seconds") is not None else _as_int_ms(step.get("elapsedMs")),
                    "firstMessageMs": _as_int_ms(step.get("first_message_seconds"), seconds=True) if step.get("first_message_seconds") is not None else _as_int_ms(step.get("firstMessageMs")),
                    "finalMessageMs": _as_int_ms(step.get("final_seconds"), seconds=True) if step.get("final_seconds") is not None else _as_int_ms(step.get("finalMessageMs")),
                    "followupCount": step.get("followup_count") or step.get("followupCount"),
                    "followupTargets": list(step.get("followup_targets") or step.get("followupTargets") or []),
                    "followupRefreshes": list(step.get("followup_refreshes") or step.get("followupRefreshes") or []),
                    "assertionViolations": list(step.get("assertion_violations") or step.get("assertionViolations") or []),
                    "provider": provider,
                    "model": model,
                    "candidateName": provider_label,
                    "candidateKey": f"{provider_label}:{case_name}#{step_index}",
                    "run": case.get("run"),
                    "runCount": 1,
                }
                if current is None:
                    grouped[key] = record
                    continue
                current["runCount"] = int(current.get("runCount") or 1) + 1
                current_elapsed = [value for value in [current.get("elapsedMs"), record.get("elapsedMs")] if isinstance(value, int)]
                current_first = [value for value in [current.get("firstMessageMs"), record.get("firstMessageMs")] if isinstance(value, int)]
                current_final = [value for value in [current.get("finalMessageMs"), record.get("finalMessageMs")] if isinstance(value, int)]
                if current_elapsed:
                    current["elapsedMs"] = int(round(sum(current_elapsed) / len(current_elapsed)))
                if current_first:
                    current["firstMessageMs"] = int(round(sum(current_first) / len(current_first)))
                if current_final:
                    current["finalMessageMs"] = int(round(sum(current_final) / len(current_final)))
                if not current.get("responseText") and record.get("responseText"):
                    current["responseText"] = record["responseText"]
                if not current.get("thinkingText") and record.get("thinkingText"):
                    current["thinkingText"] = record["thinkingText"]
                for field in ("followupTargets", "followupRefreshes", "assertionViolations"):
                    existing = current.get(field)
                    incoming = record.get(field) or []
                    if isinstance(existing, list):
                        merged = list(existing)
                        for item in incoming:
                            if item not in merged:
                                merged.append(item)
                        current[field] = merged
                if record.get("followupCount") is not None:
                    current["followupCount"] = max(int(current.get("followupCount") or 0), int(record["followupCount"]))
    return list(grouped.values())


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = _flatten_runner_records(payload)
    if records:
        return records
    records = _flatten_provider_benchmark_records(payload)
    if records:
        return records
    if isinstance(payload.get("summary"), dict):
        return [payload]
    return []


def _build_case_index(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for record in _extract_records(payload):
        key = _normalize_text(record.get("recordKey") or record.get("case"))
        if not key:
            continue
        index.setdefault(key, []).append(record)
    return index


def _candidate_rows_for_case(
    candidate_indexes: dict[str, dict[str, list[dict[str, Any]]]],
    case_key: str,
) -> dict[str, dict[str, Any]]:
    rows_by_name: dict[str, dict[str, Any]] = {}
    for group_name, index in candidate_indexes.items():
        rows = index.get(case_key) or []
        for position, row in enumerate(rows, start=1):
            candidate_name = _normalize_text(row.get("candidateName"))
            if not candidate_name:
                provider = _normalize_text(row.get("provider"))
                model = _normalize_text(row.get("model"))
                candidate_name = provider or model or group_name
            name = candidate_name
            if name in rows_by_name:
                name = f"{candidate_name}#{position}"
            rows_by_name[name] = row
    return rows_by_name


def _metadata_for_case(
    case_key: str,
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = dict((definitions or {}).get(case_key) or {})
    for row in (current, baseline):
        if not row:
            continue
        if not metadata.get("flow"):
            metadata["flow"] = _normalize_text_list(row.get("flow"))
        if not metadata.get("coverage"):
            metadata["coverage"] = _normalize_text_list(row.get("coverage"))
        if not metadata.get("sessionId") and row.get("sessionId") is not None:
            metadata["sessionId"] = row.get("sessionId")
        if not metadata.get("latencyBudget") and isinstance(row.get("latencyBudget"), dict):
            metadata["latencyBudget"] = dict(row["latencyBudget"])
        if not metadata.get("expectedRoutingPath") and _normalize_text(row.get("expectedRoutingPath")):
            metadata["expectedRoutingPath"] = _normalize_text(row.get("expectedRoutingPath"))
        if not metadata.get("expectedActionFamily") and _normalize_text(row.get("expectedActionFamily")):
            metadata["expectedActionFamily"] = _normalize_text(row.get("expectedActionFamily"))
        if not metadata.get("expectedSemanticFrame"):
            expected_frame = _normalize_expected_semantic_frame(row.get("expectedSemanticFrame"))
            if expected_frame:
                metadata["expectedSemanticFrame"] = expected_frame
        if not metadata.get("expectedSemanticFrame"):
            expected_frame = _semantic_expectation_from_coverage(metadata.get("coverage"))
            if expected_frame:
                metadata["expectedSemanticFrame"] = expected_frame
    return metadata


def _build_case_report(
    case_key: str,
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    candidates: dict[str, dict[str, Any]],
    case_definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    case_name, _, step_suffix = case_key.partition("#")
    metadata = _metadata_for_case(case_key, baseline, current, case_definitions)
    baseline_row = _merge_record_metadata(baseline or {}, metadata) if baseline else None
    current_row = _merge_record_metadata(current or {}, metadata) if current else None
    report: dict[str, Any] = {
        "case": case_name or case_key,
        "stepIndex": int(step_suffix) if step_suffix.isdigit() else None,
        "prompt": _normalize_text((current_row or baseline_row or metadata).get("prompt")),
        "sessionId": metadata.get("sessionId"),
        "flow": metadata.get("flow") or [],
        "coverage": metadata.get("coverage") or [],
        "expectedRoutingPath": metadata.get("expectedRoutingPath"),
        "expectedActionFamily": metadata.get("expectedActionFamily"),
        "expectedNoAction": bool(metadata.get("expectedNoAction")),
        "expectedSemanticFrame": metadata.get("expectedSemanticFrame") or {},
        "latencyBudget": metadata.get("latencyBudget") or {},
        "assertions": metadata.get("assertions") or {},
        "qualityExpectations": metadata.get("qualityExpectations") or {},
        "baseline": {
            "reply": _extract_text(baseline_row or {}),
            "elapsedMs": (baseline_row or {}).get("elapsedMs"),
            "firstMessageMs": (baseline_row or {}).get("firstMessageMs"),
            "finalMessageMs": (baseline_row or {}).get("finalMessageMs"),
            "provider": (baseline_row or {}).get("provider"),
            "model": (baseline_row or {}).get("model"),
        },
        "current": {
            "reply": _extract_text(current_row or {}),
            "elapsedMs": (current_row or {}).get("elapsedMs"),
            "firstMessageMs": (current_row or {}).get("firstMessageMs"),
            "finalMessageMs": (current_row or {}).get("finalMessageMs"),
            "provider": (current_row or {}).get("provider"),
            "model": (current_row or {}).get("model"),
        },
        "candidates": [],
    }
    if baseline_row:
        report["baseline"]["score"] = _score_case(baseline_row)
    if current_row:
        report["current"]["score"] = _score_case(current_row)
        issue = _build_tool_chain_issue(current_row)
        if issue:
            report["current"]["toolChainIssue"] = issue
    for name, candidate in candidates.items():
        candidate_row = _merge_record_metadata(candidate, metadata)
        candidate_payload = {
            "name": name,
            "provider": candidate_row.get("provider"),
            "model": candidate_row.get("model"),
            "reply": _extract_text(candidate_row),
            "elapsedMs": candidate_row.get("elapsedMs"),
            "firstMessageMs": candidate_row.get("firstMessageMs"),
            "finalMessageMs": candidate_row.get("finalMessageMs"),
            "score": _score_case(candidate_row),
        }
        issue = _build_tool_chain_issue(candidate_row)
        if issue:
            candidate_payload["toolChainIssue"] = issue
        report["candidates"].append(candidate_payload)
    return report


def _score_dimension_average(scores: list[dict[str, Any]], dimension: str) -> float | None:
    values = [score.get(dimension) for score in scores if isinstance(score.get(dimension), int)]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def _latency_summary(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    elapsed = [row.get("elapsedMs") for row in rows if isinstance(row.get("elapsedMs"), int)]
    first = [row.get("firstMessageMs") for row in rows if isinstance(row.get("firstMessageMs"), int)]
    final = [row.get("finalMessageMs") for row in rows if isinstance(row.get("finalMessageMs"), int)]
    return {
        "elapsedMedianMs": _percentile(elapsed, 0.5),
        "elapsedP95Ms": _percentile(elapsed, 0.95),
        "elapsedMaxMs": max(elapsed) if elapsed else None,
        "firstMessageMedianMs": _percentile(first, 0.5),
        "finalMessageMedianMs": _percentile(final, 0.5),
    }


def _increment(counter: dict[str, int], key: Any) -> None:
    text = _normalize_text(key)
    if text:
        counter[text] = counter.get(text, 0) + 1


def _rows_for_summary(reports: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        if bucket == "current":
            current = report.get("current")
            if isinstance(current, dict) and current.get("score"):
                rows.append(current)
            continue
        for candidate in report.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("score"):
                rows.append(candidate)
    return rows


def _collect_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row["score"] for row in rows if isinstance(row.get("score"), dict)]


def _provider_model_key(row: dict[str, Any]) -> str:
    provider = _normalize_text(row.get("provider"))
    model = _normalize_text(row.get("model"))
    name = _normalize_text(row.get("name"))
    if provider and model:
        return f"{provider}/{model}"
    return provider or model or name or "unknown"


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = _collect_scores(rows)
    verdict_counts: dict[str, int] = {}
    violation_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    distribution_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    semantic_status_counts: dict[str, int] = {}
    semantic_layer_counts: dict[str, int] = {}
    semantic_topic_counts: dict[str, int] = {}
    semantic_verb_counts: dict[str, int] = {}
    semantic_side_effect_counts: dict[str, int] = {}
    semantic_mapped_route_counts: dict[str, int] = {}
    semantic_expected_counts: dict[str, int] = {}
    semantic_current_counts: dict[str, int] = {}
    semantic_expectation_counts: dict[str, int] = {}
    semantic_expectation_mismatch_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}

    for score in scores:
        _increment(verdict_counts, score.get("verdict"))
        for value in score.get("qualityViolations") or []:
            _increment(violation_counts, str(value).split(":", 1)[0])
        for value in score.get("evaluationWarnings") or []:
            _increment(warning_counts, str(value).split(":", 1)[0])
        for value in score.get("distributionCoverage") or []:
            _increment(distribution_counts, value)
        _increment(route_counts, score.get("routingPath"))
        observation = score.get("semanticFrameObservation")
        if isinstance(observation, dict):
            _increment(semantic_status_counts, observation.get("status"))
            frame = observation.get("frame")
            if isinstance(frame, dict):
                _increment(semantic_layer_counts, frame.get("taskLayer"))
                _increment(semantic_topic_counts, frame.get("topic"))
                _increment(semantic_verb_counts, frame.get("verb"))
                _increment(semantic_side_effect_counts, frame.get("sideEffect"))
        semantic_route = score.get("semanticMappedRoute")
        if semantic_route:
            _increment(semantic_mapped_route_counts, semantic_route)
            expected_route = _normalize_text(score.get("expectedRoutingPath"))
            current_route = _normalize_text(score.get("routingPath"))
            if expected_route:
                _increment(
                    semantic_expected_counts,
                    "match" if semantic_route == expected_route else f"mismatch:{expected_route}!={semantic_route}",
                )
            if current_route:
                _increment(
                    semantic_current_counts,
                    "match" if semantic_route == current_route else f"diff:{current_route}!={semantic_route}",
                )
        semantic_expectation = score.get("semanticExpectation")
        if isinstance(semantic_expectation, dict) and semantic_expectation:
            matched = semantic_expectation.get("matched")
            if matched is True:
                _increment(semantic_expectation_counts, "match")
            elif matched is False:
                _increment(semantic_expectation_counts, "mismatch")
                mismatches = semantic_expectation.get("mismatches") or []
                if mismatches:
                    for mismatch in mismatches:
                        _increment(semantic_expectation_mismatch_counts, str(mismatch).split(":", 1)[0])
                else:
                    _increment(semantic_expectation_mismatch_counts, str(semantic_expectation.get("status") or "missing"))
            else:
                _increment(semantic_expectation_counts, "not_applicable")
        for value in score.get("actionFamilies") or []:
            _increment(action_counts, value)
        for value in score.get("toolNames") or []:
            _increment(tool_counts, value)

    dimensions = {
        dimension: _score_dimension_average(scores, dimension)
        for dimension in ("correctness", "completeness", "naturalness", "actionability", "latency", "structure", "route")
    }
    return {
        "count": len(rows),
        "verdicts": verdict_counts,
        "qualityViolationsByType": violation_counts,
        "evaluationWarningsByType": warning_counts,
        "distributionCoverage": distribution_counts,
        "routeSummary": route_counts,
        "semanticFrameSummary": {
            "status": semantic_status_counts,
            "taskLayer": semantic_layer_counts,
            "topic": semantic_topic_counts,
            "verb": semantic_verb_counts,
            "sideEffect": semantic_side_effect_counts,
            "mappedRoute": semantic_mapped_route_counts,
            "expectedRouteComparison": semantic_expected_counts,
            "currentRouteComparison": semantic_current_counts,
            "expectedFrameComparison": semantic_expectation_counts,
            "expectedFrameMismatches": semantic_expectation_mismatch_counts,
        },
        "actionFamilySummary": action_counts,
        "toolSummary": tool_counts,
        "averageScores": dimensions,
        "latency": _latency_summary(rows),
    }


def _summarize_by_scenario(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        flow = report.get("flow") if isinstance(report.get("flow"), list) else []
        keys = flow or ["unclassified"]
        current = report.get("current")
        if not isinstance(current, dict) or not current.get("score"):
            continue
        for key in keys:
            grouped.setdefault(_normalize_text(key) or "unclassified", []).append(current)
    return {key: _summarize_rows(rows) for key, rows in sorted(grouped.items())}


def _summarize_by_coverage(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        coverage = report.get("coverage") if isinstance(report.get("coverage"), list) else []
        current = report.get("current")
        if not isinstance(current, dict) or not current.get("score"):
            continue
        for key in coverage:
            grouped.setdefault(_normalize_text(key), []).append(current)
    return {key: _summarize_rows(rows) for key, rows in sorted(grouped.items()) if key}


def _summarize_candidates(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        for candidate in report.get("candidates") or []:
            if not isinstance(candidate, dict) or not candidate.get("score"):
                continue
            grouped.setdefault(_provider_model_key(candidate), []).append(candidate)
    return {key: _summarize_rows(rows) for key, rows in sorted(grouped.items())}


def _issue_rows_for_reports(reports: list[dict[str, Any]], bucket: str = "current") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        if bucket == "current":
            current = report.get("current")
            if isinstance(current, dict) and isinstance(current.get("toolChainIssue"), dict):
                rows.append(current["toolChainIssue"])
            continue
        for candidate in report.get("candidates") or []:
            if isinstance(candidate, dict) and isinstance(candidate.get("toolChainIssue"), dict):
                row = dict(candidate["toolChainIssue"])
                row["candidate"] = _provider_model_key(candidate)
                rows.append(row)
    return rows


def _summarize_tool_chain_issues(reports: list[dict[str, Any]]) -> dict[str, Any]:
    current_issues = _issue_rows_for_reports(reports, "current")
    candidate_issues = _issue_rows_for_reports(reports, "candidates")
    issue_type_counts: dict[str, int] = {}
    problem_type_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    repeated_tool_counts: dict[str, int] = {}

    for row in current_issues:
        for issue_type in row.get("issueTypes") or []:
            _increment(issue_type_counts, issue_type)
        _increment(problem_type_counts, row.get("problemType"))
        _increment(route_counts, row.get("actualRoutingPath"))
        for value in row.get("toolNames") or []:
            _increment(tool_counts, value)
        for value in row.get("repeatedToolNames") or []:
            _increment(repeated_tool_counts, value)

    slow_or_timeout = [
        row
        for row in current_issues
        if row.get("result") in {"slow", "very_slow", "timeout_or_error"}
        or "timeout_or_error" in (row.get("issueTypes") or [])
    ]
    missing_progress = [
        row
        for row in current_issues
        if "missing_progress_for_long_task" in (row.get("issueTypes") or [])
        or "late_first_hint" in (row.get("issueTypes") or [])
    ]
    top_slow = sorted(
        current_issues,
        key=lambda item: item.get("elapsedMs") if isinstance(item.get("elapsedMs"), int) else -1,
        reverse=True,
    )[:10]
    return {
        "count": len(current_issues),
        "candidateCount": len(candidate_issues),
        "slowOrTimeoutCount": len(slow_or_timeout),
        "missingProgressCount": len(missing_progress),
        "byProblemType": problem_type_counts,
        "byIssueType": issue_type_counts,
        "byRoutingPath": route_counts,
        "byTool": tool_counts,
        "byRepeatedTool": repeated_tool_counts,
        "topSlow": top_slow,
        "issues": current_issues,
        "candidateIssues": candidate_issues,
    }



def _comparison_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    improved = same = regressed = incomparable = 0
    for report in reports:
        baseline_score = (report.get("baseline") or {}).get("score")
        current_score = (report.get("current") or {}).get("score")
        if not isinstance(baseline_score, dict) or not isinstance(current_score, dict):
            incomparable += 1
            continue
        base_rank = _VERDICT_RANK.get(_normalize_text(baseline_score.get("verdict")), -1)
        current_rank = _VERDICT_RANK.get(_normalize_text(current_score.get("verdict")), -1)
        if current_rank > base_rank:
            improved += 1
        elif current_rank < base_rank:
            regressed += 1
        else:
            same += 1
    return {
        "improved": improved,
        "same": same,
        "regressed": regressed,
        "incomparable": incomparable,
    }


def _summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    current_rows = _rows_for_summary(reports, "current")
    candidate_rows = _rows_for_summary(reports, "candidates")
    current_summary = _summarize_rows(current_rows)
    return {
        "totalCases": len(reports),
        "current": current_summary,
        "scenarioSummary": _summarize_by_scenario(reports),
        "coverageSummary": _summarize_by_coverage(reports),
        "candidateSummary": _summarize_candidates(reports),
        "candidateOverall": _summarize_rows(candidate_rows),
        "toolChainIssues": _summarize_tool_chain_issues(reports),
        "baselineComparison": _comparison_summary(reports),
        "acceptance": {
            "passedHardGates": not current_summary["qualityViolationsByType"],
            "failedCount": current_summary["verdicts"].get("fail", 0),
            "needsReviewCount": current_summary["verdicts"].get("needs_review", 0),
            "strongCount": current_summary["verdicts"].get("strong", 0),
        },
    }


def _format_score_for_markdown(score: dict[str, Any] | None) -> str:
    if not isinstance(score, dict):
        return ""
    verdict = _normalize_text(score.get("verdict")) or "unknown"
    coverage = ",".join(score.get("distributionCoverage") or [])
    violations = ",".join(score.get("qualityViolations") or [])
    dimensions = (
        f"C{score.get('correctness', '-')}/"
        f"F{score.get('completeness', '-')}/"
        f"A{score.get('actionability', '-')}/"
        f"L{score.get('latency', '-')}/"
        f"R{score.get('route', '-')}"
    )
    details = []
    if coverage:
        details.append(f"coverage={coverage}")
    if violations:
        details.append(f"violations={violations}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{verdict} {dimensions}{suffix}"


def _markdown_escape_table(text: Any) -> str:
    normalized = _normalize_text(text)
    return normalized.replace("|", "\\|").replace("\n", "<br>")


def _markdown_code_block(text: Any) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return ["_无_"]
    return ["```text", normalized, "```"]


def _format_list_for_markdown(values: Any) -> str:
    if isinstance(values, dict):
        if not values:
            return "_无_"
        return ", ".join(f"{key}={value}" for key, value in values.items())
    if isinstance(values, list):
        if not values:
            return "_无_"
        return ", ".join(_normalize_text(value) for value in values if _normalize_text(value)) or "_无_"
    text = _normalize_text(values)
    return text or "_无_"


def _score_table_rows(score: dict[str, Any] | None) -> list[str]:
    if not isinstance(score, dict):
        return ["| 维度 | 分数 |", "|---|---:|", "| 无 | - |"]
    rows = ["| 维度 | 分数 |", "|---|---:|"]
    labels = {
        "correctness": "正确性",
        "completeness": "完整度",
        "naturalness": "自然度",
        "actionability": "决策支持度",
        "structure": "结构清楚度",
        "latency": "延迟",
        "route": "路由",
    }
    for key, label in labels.items():
        rows.append(f"| {label} | {score.get(key, '-')} |")
    return rows


def _manual_review_items(item: dict[str, Any]) -> list[str]:
    score = item.get("current", {}).get("score") if isinstance(item.get("current"), dict) else {}
    quality_expectations = item.get("qualityExpectations") if isinstance(item.get("qualityExpectations"), dict) else {}
    items = [
        "用户核心诉求是否被正面回答。",
        "结论、依据、影响和下一步是否齐全。",
        "是否为了变快而丢失用户需要的信息。",
        "是否存在内部术语、确认边界或误执行风险。",
        "回复结构是否清楚且不像生硬模板。",
    ]
    if _is_preview_or_example_case({"case": item.get("case"), "prompt": item.get("prompt")}, item.get("current", {}).get("reply", "")):
        items.append("预览或举例是否覆盖学校层次、冲稳保、专业热度、数量空间和代表样本。")
    if isinstance(score, dict) and score.get("verdict") == "needs_review":
        items.append("该 case 被自动标为 needs_review，需要人工判断是否达到可上线质量。")
    if quality_expectations:
        items.append("对照 qualityExpectations 检查是否遗漏业务期望点。")
    return items


def _render_markdown_summary(summary: dict[str, Any]) -> list[str]:
    current_summary = summary.get("current", {}) if isinstance(summary.get("current"), dict) else {}
    candidate_summary = summary.get("candidateSummary", {}) if isinstance(summary.get("candidateSummary"), dict) else {}
    tool_chain_issues = (
        summary.get("toolChainIssues", {})
        if isinstance(summary.get("toolChainIssues"), dict)
        else {}
    )
    lines = [
        "# Dialog Case Evaluation Report",
        "",
        "## Summary",
        "",
        f"- totalCases: {summary.get('totalCases', 0)}",
        f"- current verdicts: {current_summary.get('verdicts', {})}",
        f"- quality violations: {current_summary.get('qualityViolationsByType', {})}",
        f"- evaluation warnings: {current_summary.get('evaluationWarningsByType', {})}",
        f"- latency: {current_summary.get('latency', {})}",
        f"- semantic frame: {current_summary.get('semanticFrameSummary', {})}",
        f"- acceptance: {summary.get('acceptance', {})}",
        "",
        "## Scenario Summary",
        "",
        "| flow | count | verdicts | violations | latency |",
        "|---|---:|---|---|---|",
    ]
    for flow, value in (summary.get("scenarioSummary") or {}).items():
        lines.append(
            f"| {_markdown_escape_table(flow)} | {value.get('count', 0)} | {_markdown_escape_table(value.get('verdicts', {}))} | {_markdown_escape_table(value.get('qualityViolationsByType', {}))} | {_markdown_escape_table(value.get('latency', {}))} |"
        )
    if candidate_summary:
        lines.extend(["", "## Candidate Summary", "", "| candidate | count | verdicts | latency |", "|---|---:|---|---|"])
        for name, value in candidate_summary.items():
            lines.append(
                f"| {_markdown_escape_table(name)} | {value.get('count', 0)} | {_markdown_escape_table(value.get('verdicts', {}))} | {_markdown_escape_table(value.get('latency', {}))} |"
            )
    if tool_chain_issues:
        lines.extend(
            [
                "",
                "## Tool Chain Issues",
                "",
                f"- count: {tool_chain_issues.get('count', 0)}",
                f"- slowOrTimeoutCount: {tool_chain_issues.get('slowOrTimeoutCount', 0)}",
                f"- missingProgressCount: {tool_chain_issues.get('missingProgressCount', 0)}",
                f"- byProblemType: {tool_chain_issues.get('byProblemType', {})}",
                f"- byIssueType: {tool_chain_issues.get('byIssueType', {})}",
                f"- byRepeatedTool: {tool_chain_issues.get('byRepeatedTool', {})}",
                "",
                "| case | prompt | problem | route | elapsed | tools | repeated | issueTypes |",
                "|---|---|---|---|---:|---|---|---|",
            ]
        )
        for issue in (tool_chain_issues.get("issues") or [])[:20]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_escape_table(issue.get("caseId")),
                        _markdown_escape_table(_normalize_text(issue.get("userPrompt"))[:60]),
                        _markdown_escape_table(issue.get("problemType")),
                        _markdown_escape_table(issue.get("actualRoutingPath")),
                        _markdown_escape_table(issue.get("elapsedMs")),
                        _markdown_escape_table(_format_list_for_markdown(issue.get("toolNames"))),
                        _markdown_escape_table(_format_list_for_markdown(issue.get("repeatedToolNames"))),
                        _markdown_escape_table(_format_list_for_markdown(issue.get("issueTypes"))),
                    ]
                )
                + " |"
            )
    return lines


def _render_markdown_table(reports: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = _render_markdown_summary(summary)
    lines.extend(["", "## Cases", "", "| case | flow | baseline | current | candidates |", "|---|---|---|---|---|"])
    for item in reports:
        baseline = item.get("baseline", {}).get("reply", "")
        current = item.get("current", {}).get("reply", "")
        candidate_text = "; ".join(
            f"{candidate.get('name')}: {_format_score_for_markdown(candidate.get('score'))} {candidate.get('reply', '')}"
            for candidate in item.get("candidates", [])
        )
        lines.append(
            f"| {_markdown_escape_table(item.get('case', ''))} | {_markdown_escape_table(','.join(item.get('flow') or []))} | {_markdown_escape_table(_format_score_for_markdown(item.get('baseline', {}).get('score')) + ' ' + baseline[:80])} | {_markdown_escape_table(_format_score_for_markdown(item.get('current', {}).get('score')) + ' ' + current[:80])} | {_markdown_escape_table(candidate_text[:120])} |"
        )
    return "\n".join(lines)


def _render_case_detail(item: dict[str, Any]) -> list[str]:
    current = item.get("current", {}) if isinstance(item.get("current"), dict) else {}
    baseline = item.get("baseline", {}) if isinstance(item.get("baseline"), dict) else {}
    score = current.get("score") if isinstance(current.get("score"), dict) else {}
    tool_chain_issue = (
        current.get("toolChainIssue")
        if isinstance(current.get("toolChainIssue"), dict)
        else {}
    )
    lines = [
        f"### {item.get('case', '')}#{item.get('stepIndex', '')}",
        "",
        f"- flow: {_format_list_for_markdown(item.get('flow'))}",
        f"- coverage: {_format_list_for_markdown(item.get('coverage'))}",
        f"- sessionId: {_normalize_text(item.get('sessionId')) or '-'}",
        f"- expected route/action: {_normalize_text(item.get('expectedRoutingPath')) or '-'} / {_normalize_text(item.get('expectedActionFamily')) or ('无动作' if item.get('expectedNoAction') else '-')}",
        f"- latency budget: {_format_list_for_markdown(item.get('latencyBudget'))}",
        f"- current latency: elapsed={current.get('elapsedMs')}ms, first={current.get('firstMessageMs')}ms, final={current.get('finalMessageMs')}ms",
        f"- score: {_format_score_for_markdown(score)}",
        f"- quality violations: {_format_list_for_markdown(score.get('qualityViolations') if isinstance(score, dict) else [])}",
        f"- evaluation warnings: {_format_list_for_markdown(score.get('evaluationWarnings') if isinstance(score, dict) else [])}",
        f"- distribution coverage: {_format_list_for_markdown(score.get('distributionCoverage') if isinstance(score, dict) else [])}",
        f"- routing/action/tool: {_normalize_text(score.get('routingPath') if isinstance(score, dict) else None) or '-'} / {_format_list_for_markdown(score.get('actionFamilies') if isinstance(score, dict) else [])} / {_format_list_for_markdown(score.get('toolNames') if isinstance(score, dict) else [])}",
        f"- semantic mapped route: {_normalize_text(score.get('semanticMappedRoute') if isinstance(score, dict) else None) or '-'}",
        f"- semantic frame: {_format_list_for_markdown(score.get('semanticFrameObservation') if isinstance(score, dict) else {})}",
        f"- tool chain issue: {_format_list_for_markdown(tool_chain_issue)}",
        "",
        "**用户输入**",
        "",
        *_markdown_code_block(item.get("prompt")),
        "",
        "**当前回复**",
        "",
        *_markdown_code_block(current.get("reply")),
        "",
        "**自动评分**",
        "",
        *_score_table_rows(score if isinstance(score, dict) else None),
    ]
    if _normalize_text(baseline.get("reply")):
        lines.extend(["", "**基线回复**", "", *_markdown_code_block(baseline.get("reply"))])
    candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
    if candidates:
        lines.extend(["", "**候选回复**", ""])
        for candidate in candidates:
            lines.append(f"- {candidate.get('name')}: {_format_score_for_markdown(candidate.get('score'))}")
            lines.extend(_markdown_code_block(candidate.get("reply")))
    assertions = item.get("assertions") if isinstance(item.get("assertions"), dict) else {}
    quality_expectations = item.get("qualityExpectations") if isinstance(item.get("qualityExpectations"), dict) else {}
    if assertions or quality_expectations:
        lines.extend(["", "**Case 期望**", ""])
        if assertions:
            lines.append(f"- assertions: {_format_list_for_markdown(assertions)}")
        if quality_expectations:
            lines.append(f"- qualityExpectations: {_format_list_for_markdown(quality_expectations)}")
    lines.extend(["", "**人工复核清单**", ""])
    for review_item in _manual_review_items(item):
        lines.append(f"- {review_item}")
    lines.append("")
    return lines


def _render_markdown_detail(reports: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = _render_markdown_summary(summary)
    lines.extend(["", "## Case Details", ""])
    for item in reports:
        lines.extend(_render_case_detail(item))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build case-level evaluation reports.")
    parser.add_argument("--baseline", help="baseline dialog regression JSON")
    parser.add_argument("--current", help="current dialog regression JSON")
    parser.add_argument("--candidates", action="append", default=[], help="candidate JSON in name=path form")
    parser.add_argument("--case-definitions", action="append", default=[], help="runner case definition JSON; can be repeated")
    parser.add_argument("--output", help="write report JSON to this path")
    parser.add_argument("--markdown", action="store_true", help="render a markdown table instead of JSON")
    parser.add_argument("--markdown-detail", action="store_true", help="render a detailed markdown report with full replies and review checklist")
    args = parser.parse_args()

    baseline_payload = _load_payload(args.baseline) if args.baseline else {}
    current_payload = _load_payload(args.current) if args.current else {}
    baseline_index = _build_case_index(baseline_payload)
    current_index = _build_case_index(current_payload)
    case_definitions = _merge_case_definition_indexes(args.case_definitions)

    candidate_indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in args.candidates:
        if "=" not in item:
            raise ValueError("--candidates must be in name=path form")
        name, path = item.split("=", 1)
        candidate_indexes[name] = _build_case_index(_load_payload(path))

    all_cases = sorted(set(baseline_index) | set(current_index) | {case for index in candidate_indexes.values() for case in index})
    reports = []
    for case_key in all_cases:
        baseline_rows = baseline_index.get(case_key) or []
        current_rows = current_index.get(case_key) or []
        candidate_rows = _candidate_rows_for_case(candidate_indexes, case_key)
        reports.append(
            _build_case_report(
                case_key,
                baseline_rows[0] if baseline_rows else None,
                current_rows[0] if current_rows else None,
                candidate_rows,
                case_definitions,
            )
        )

    payload = {"count": len(reports), "summary": _summarize_reports(reports), "cases": reports}
    if args.markdown_detail:
        text = _render_markdown_detail(reports, payload["summary"])
    elif args.markdown:
        text = _render_markdown_table(reports, payload["summary"])
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
