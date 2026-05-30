from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.base_agent import BaseAgent
from app.agent.context import RequestContext
from app.agent.instructions import build_instructions
from app.agent.tool_reply_policy import decide_tool_reply
from app.llm.client import LLMClient
from app.tools.major_compare_tool import compare_major_options, compare_majors, compare_majors_adhoc
from app.tools.major_info_tool import get_major_introduction, get_major_introductions
from app.tools.major_recommend_tool import get_major_recommendations, get_major_recommendations_adhoc
from app.tools.intent_state_tool import (
    update_volunteer_intent_state,
)
from app.tools.intent_preview_tool import (
    analyze_current_career_direction,
    analyze_current_interest,
    analyze_current_major_interest,
    analyze_current_region_interest,
    analyze_current_school_interest,
    preview_current_career_intent_confirmation,
    preview_current_intent_confirmation,
    preview_current_major_intent_confirmation,
    preview_current_region_intent_confirmation,
    preview_current_school_intent_confirmation,
)
from app.tools.plan_context_tool import collect_plan_context_inputs
from app.tools.plan_execution_tool import execute_plan_action
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.plan_query_tool import query_volunteer_plan
from app.tools.plan_validation_tool import validate_major_subjects, validate_plan_params
from app.tools.school_compare_tool import compare_schools, compare_schools_adhoc
from app.tools.school_info_tool import get_school_introduction
from app.tools.school_recommend_tool import get_school_recommendations
from app.tools.score_query_tool import query_admission_score, query_score_line

# 工具名 → 用户可见的中文进度提示
_TOOL_PROGRESS_HINTS: dict[str, str] = {
    "query_admission_score":            "正在查看这个分数附近的录取机会...",
    "query_score_line":                 "正在查学校和专业的历年录取分数...",
    "compare_majors":                   "正在对比这几个专业的差异...",
    "compare_majors_adhoc":             "正在对比这几个专业的差异...",
    "compare_major_options":            "正在对比这些专业的差异...",
    "compare_schools":                  "正在对比这几所院校的情况...",
    "compare_schools_adhoc":            "正在对比这几所院校的情况...",
    "get_major_recommendations":        "正在结合你的情况筛选适合重点看的专业...",
    "get_major_recommendations_adhoc":  "正在结合你的情况筛选适合重点看的专业...",
    "get_school_recommendations":       "正在结合你的情况筛选适合重点看的院校...",
    "get_major_introduction":           "正在查这个专业的学习内容和就业情况...",
    "get_major_introductions":          "正在对照这些专业的学习内容和就业情况...",
    "get_school_introduction":          "正在查这所院校的基础信息...",
    "query_volunteer_plan":             "正在查看你当前方案里的志愿...",
    "analyze_current_interest":         "正在结合你的问题做初步分析...",
    "analyze_current_school_interest":  "正在看这个院校方向是否适合你...",
    "analyze_current_major_interest":   "正在看这个专业方向是否适合你...",
    "analyze_current_region_interest":  "正在看这个地域选择对方案的影响...",
    "analyze_current_career_direction": "正在看这条发展方向是否适合你...",
    "preview_current_intent_confirmation": "正在把你的想法整理成待确认的报考偏好...",
    "preview_current_major_intent_confirmation": "正在把你的专业想法整理成待确认偏好...",
    "preview_current_school_intent_confirmation": "正在把你的院校想法整理成待确认偏好...",
    "preview_current_region_intent_confirmation": "正在把你的地域想法整理成待确认偏好...",
    "preview_current_career_intent_confirmation": "正在把你的发展方向整理成待确认偏好...",
    "update_volunteer_intent_state":    "正在按你的确认更新后续参考偏好...",
    "collect_plan_context_inputs":      "正在读取你的方案、偏好和审查结果...",
    "plan_next_action":                 "正在读取当前方案并整理这次请求...",
    "execute_plan_action":              "正在处理你的方案，请稍等...",
    "validate_major_subjects":          "正在检查专业对选科有没有要求...",
    "validate_plan_params":             "正在检查生成方案需要的信息是否完整...",
}

class ChatAgent(BaseAgent[str]):
    """高考志愿填报聊天 Agent。"""

    def __init__(self, llm_client: LLMClient):
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        super().__init__(
            llm_client=llm_client,
            instructions=build_instructions,
            output_type=str,
            skill_dirs=[str(skills_dir)],
            expose_skill_tools=False,
            deps_type=RequestContext,
            tools=[
                get_major_introduction,
                get_major_introductions,
                compare_major_options,
                compare_majors,
                compare_majors_adhoc,
                get_major_recommendations,
                get_major_recommendations_adhoc,
                get_school_introduction,
                compare_schools,
                compare_schools_adhoc,
                get_school_recommendations,
                query_volunteer_plan,
                collect_plan_context_inputs,
                plan_next_action,
                execute_plan_action,
                validate_major_subjects,
                validate_plan_params,
                analyze_current_career_direction,
                analyze_current_interest,
                analyze_current_major_interest,
                analyze_current_region_interest,
                analyze_current_school_interest,
                preview_current_intent_confirmation,
                preview_current_major_intent_confirmation,
                preview_current_school_intent_confirmation,
                preview_current_region_intent_confirmation,
                preview_current_career_intent_confirmation,
                update_volunteer_intent_state,
                query_admission_score,
                query_score_line,
            ],
        )

    def get_progress_hint(self, tool_name: str) -> str | None:
        """将工具名映射为用户可见的中文进度提示。"""
        return _TOOL_PROGRESS_HINTS.get(tool_name)

    def should_return_directly_from_tool(self, tool_names: list[str], tool_returns: list[Any], deps: Any | None = None) -> bool:
        """Use a centralized policy for safe direct tool replies."""
        return decide_tool_reply(tool_names, tool_returns, deps).should_return_directly

    def render_direct_tool_output(
        self,
        tool_names: list[str],
        tool_returns: list[Any],
        deps: Any | None = None,
    ) -> str | None:
        decision = decide_tool_reply(tool_names, tool_returns, deps)
        if decision.should_return_directly:
            return decision.reply
        return super().render_direct_tool_output(tool_names, tool_returns, deps)
