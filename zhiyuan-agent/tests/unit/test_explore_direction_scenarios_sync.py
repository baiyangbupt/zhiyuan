"""Scenario tests for direction-oriented Explore analysis.

These tests keep the LLM mocked and verify that direction Explore provides
meaningful analysis facts and next-step progression instead of only listing
schools or directly writing intent state.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.schemas.user_profile import UserProfile
from app.tools.explore_direction_tool import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    _build_impact_preview_from_analysis,
    preview_direction_analysis_from_request,
    preview_direction_comparison_from_request,
    resolve_career_direction_slots,
    should_use_generic_direction_analysis,
)
from app.tools.intent_preview_tool import analyze_current_career_direction
from app.tools.explore_direction_tool import preview_generic_direction_analysis_from_request


def _run(coro):
    return asyncio.run(coro)


class _CapturingDirectionAgent:
    def __init__(self, output: dict):
        self.output = output
        self.prompts: list[str] = []

    async def run(self, prompt: str, model_settings: dict | None = None):
        self.prompts.append(prompt)
        return SimpleNamespace(output=json.dumps(self.output, ensure_ascii=False))


def _request_context(
    *,
    session_id: str = "401",
    text: str = "体制内适不适合我",
    profile: UserProfile | None = None,
) -> RequestContext:
    return RequestContext(
        userid="u1",
        sessionid=session_id,
        batch="01",
        chat_history=[{"role": "user", "content": text}],
        score_detail=ScoreDetail(
            province="北京",
            total_score=612,
            subject_list=["物理", "化学", "生物"],
            sex="女",
            volunteer_model="majorGroup",
        ),
        init_profile=profile or UserProfile.model_validate(
            {
                "major": {"level2": ["计算机类"], "negative_level2": ["土木类"]},
                "city": {"province": ["北京", "天津"], "negative_province": ["新疆"]},
            }
        ),
        planning_summary=PlanningSummary(
            phase="reviewed",
            version=3,
            draft_total=30,
            ordered_total=30,
            review_warn_count=1,
            review_risk_count=0,
        ),
    )


def test_direction_impact_preview_deduplicates_repeated_points():
    text = _build_impact_preview_from_analysis(
        {
            "summaryTitle": "先看方向承接",
            "currentPlanFit": ["当前选科没有直接挡住", "当前选科没有直接挡住"],
            "candidateOpportunity": ["候选里还有机会", "候选里还有机会"],
        }
    )

    assert text.count("当前选科没有直接挡住") == 1
    assert text.count("候选里还有机会") == 1


def _planning_state_with_direction_examples() -> dict:
    return {
        "data": {
            "orderedPlanState": {
                "summary": {
                    "unitTotal": 2,
                    "targetUnitCount": 3,
                    "unitTierCounts": {"冲": 1, "稳": 1, "保": 0},
                },
                "items": [
                    {
                        "volunteerId": "ordered-1",
                        "schoolName": "北京师范大学",
                        "majorName": "法学",
                        "schoolCategory": "师范",
                        "majorCategory": "法学",
                        "provinceName": "北京",
                        "tier": "稳",
                        "schoolRankTags": ["双一流", "部委院校"],
                        "majorRankTags": ["专业热度80"],
                    },
                    {
                        "volunteerId": "ordered-2",
                        "schoolName": "北京工业大学",
                        "majorName": "计算机科学与技术",
                        "schoolNature": "公办",
                        "provinceName": "北京",
                        "tier": "冲",
                        "schoolRankTags": ["保研", "省重点"],
                    },
                ]
            },
            "candidatePoolState": {
                "requiredCount": 3,
                "items": [
                    {
                        "volunteerId": "candidate-1",
                        "schoolName": "中国政法大学",
                        "majorName": "行政管理",
                        "schoolCategory": "政法",
                        "majorNameExtra": "",
                        "majorCategory": "公共管理",
                        "provinceName": "北京",
                        "tier": "冲",
                        "schoolRankTags": ["双一流"],
                    },
                    {
                        "volunteerId": "candidate-study-1",
                        "schoolName": "北京科技大学",
                        "majorName": "信息管理与信息系统",
                        "schoolCategory": "理工",
                        "majorCategory": "管理科学与工程类",
                        "provinceName": "北京",
                        "tier": "稳",
                        "schoolRankTags": ["硕士点", "保研"],
                    },
                    {
                        "volunteerId": "candidate-2",
                        "schoolName": "天津师范大学",
                        "majorName": "思想政治教育",
                        "schoolCategory": "师范",
                        "majorDiscipline": "马克思主义理论",
                        "provinceName": "天津",
                        "tier": "稳",
                        "majorPlanTags": ["师范专业"],
                    },
                    {
                        "volunteerId": "ordered-1",
                        "schoolName": "北京师范大学",
                        "majorName": "法学",
                        "schoolCategory": "师范",
                        "provinceName": "北京",
                        "tier": "稳",
                    },
                ]
            },
            "reviewState": {
                "summary": {"riskCount": 0, "warnCount": 1},
                "checks": [
                    {"passed": False, "summary": "保底数量还可以继续补强"},
                ],
            },
        }
    }


def _planning_state_with_market_examples() -> dict:
    return {
        "data": {
            "orderedPlanState": {
                "items": [
                    {
                        "volunteerId": "ordered-market-1",
                        "schoolName": "北京工业大学",
                        "majorName": "计算机科学与技术",
                        "schoolCategory": "理工",
                        "majorCategory": "计算机类",
                        "provinceName": "北京",
                        "tier": "稳",
                        "schoolRankTags": ["省重点"],
                        "majorRankTags": ["就业面较宽"],
                    }
                ]
            },
            "candidatePoolState": {
                "items": [
                    {
                        "volunteerId": "candidate-market-1",
                        "schoolName": "天津财经大学",
                        "majorName": "金融学",
                        "schoolCategory": "财经",
                        "majorCategory": "金融学类",
                        "provinceName": "天津",
                        "tier": "稳",
                        "majorPlanTags": ["就业方向明确"],
                    }
                ]
            },
        }
    }


def _planning_state_with_future_development(career_types: list[str]) -> dict:
    payload = _planning_state_with_direction_examples()
    payload["data"]["profileState"] = {
        "latentProfile": {
            "futureDevelopment": {
                "careerTypes": career_types,
            }
        }
    }
    return payload


def test_direction_explore_public_service_uses_student_plan_candidate_facts_and_progresses():
    agent = _CapturingDirectionAgent(
        {
            "summaryTitle": "结合你的选科和当前方案，体制内方向可以作为重点了解方向",
            "currentPlanFit": [
                "你是北京物化生考生，当前方案里北京师范大学-法学已经能承接一部分体制内方向。",
                "这条路需要看专业路径和院校属性，不适合只按学校名判断。",
            ],
            "currentPlanConflict": [
                "如果把体制内作为强目标，当前方案里还需要继续确认相关专业占比是否够。"
            ],
            "candidateOpportunity": [
                "候选里中国政法大学-行政管理、天津师范大学-思想政治教育可以继续展开比较。"
            ],
            "nextActionHints": [
                "下一步可以先看这些机会是否符合你的地域和录取梯度，再决定要不要记成偏好。"
            ],
        }
    )

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool._get_direction_analysis_agent", return_value=agent),
    ):
        resp = _run(preview_direction_analysis_from_request(_request_context(), CAREER_SYSTEM_PUBLIC_SERVICE))
    assert "北京物化生考生" in resp
    assert "当前方案已有 2/3 个志愿" in resp
    assert "冲稳保分布：冲1 / 稳1 / 保0" in resp
    assert "风险 0 项、提醒 1 项" in resp
    assert "保底数量还可以继续补强" in resp
    assert "北京师范大学-法学" in resp
    assert "中国政法大学-行政管理" in resp
    assert "代表样本有：北京师范大学-法学" in resp
    assert "下一步" in resp
    assert "记成后续偏好" in resp

    prompt = agent.prompts[0]
    assert "当前用户原话：体制内适不适合我" in prompt
    assert "学生基础信息：省份=北京；分数=612；选科=物理、化学、生物；性别=女；模式=majorGroup" in prompt
    assert "意向专业大类=计算机类" in prompt
    assert "排除专业大类=土木类" in prompt
    assert "ordered_total=30" in prompt
    assert "学生适配事实" in prompt
    assert "你现在的兴趣又明显偏向计算机类" in prompt
    assert "北京师范大学-法学" in prompt
    assert "中国政法大学-行政管理" in prompt
    assert "planOverview" in prompt
    assert '"targetTotal": 3' in prompt
    assert "evidenceExamples" in prompt
    assert "schoolCategory:师范" in prompt or "schoolCategory:政法" in prompt


def test_direction_examples_rank_stronger_evidence_before_broad_category_tags():
    request_context = _request_context(session_id="401-rank", text="体制内和读研分别有哪些支撑")
    request_context.allow_explore_inner_llm = False

    with patch(
        "app.tools.explore_direction_tool.get_planning_state",
        new=AsyncMock(return_value=_planning_state_with_direction_examples()),
    ):
        resp = _run(
            preview_direction_comparison_from_request(
                request_context,
                [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_FURTHER_STUDY],
            )
        )

    assert "候选里和“深造发展导向”更相关" in resp
    assert "北京科技大学-信息管理与信息系统" in resp
    further_study_line = next(line for line in resp.splitlines() if "候选里和“深造发展导向”更相关" in line)
    assert further_study_line.index("北京科技大学-信息管理与信息系统") < further_study_line.index("中国政法大学-行政管理")


def test_direction_explore_skips_inner_llm_when_chat_service_disables_it():
    request_context = _request_context(session_id="401b", text="体制内适不适合我")
    request_context.allow_explore_inner_llm = False

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", new=AsyncMock()) as generation_mock,
    ):
        resp = _run(preview_direction_analysis_from_request(request_context, CAREER_SYSTEM_PUBLIC_SERVICE))

    generation_mock.assert_not_awaited()
    assert "体制内/考公导向" in resp
    assert "当前方案已有 2/3 个志愿" in resp
    assert "你的当前选科是物理、化学、生物" in resp
    assert "当前方案里已经有一部分内容能承接这条方向" in resp
    assert "代表样本有：北京师范大学-法学" in resp
    assert "下一步" in resp


def test_direction_explore_fallback_still_analyzes_when_llm_generation_fails():
    async def _raise_generation(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", side_effect=_raise_generation),
    ):
        resp = _run(
            preview_direction_analysis_from_request(
                _request_context(session_id="402", text="稳定就业是不是更适合我"),
                CAREER_STABLE_EMPLOYMENT,
            )
        )

    assert "稳定就业导向" in resp
    assert "你现在还没有成型的排序方案" in resp
    assert "你的当前选科是物理、化学、生物" in resp
    assert "就业确定性、岗位稳定性和路径清晰度" in resp
    assert "候选里暂时没看到特别密集的新机会" in resp
    assert "如果你愿意把它记成后续偏好" in resp
    assert "MBTI" in resp
    assert "霍兰德" in resp


def test_direction_explore_comparison_supports_three_directions_with_distinct_facts():
    agent = _CapturingDirectionAgent(
        {
            "summaryTitle": "这三个方向可以一起比较，但侧重点不同",
            "currentPlanFit": [
                "深造看院校平台，稳定就业看岗位确定性，体制内看专业和院校属性。",
                "当前方案里北京工业大学更偏深造和稳定，北京师范大学-法学更偏体制内。",
            ],
            "currentPlanConflict": [
                "如果三条路都要兼顾，后续需要避免方案目标过散。"
            ],
            "candidateOpportunity": [
                "候选里政法、师范类机会可以继续补充体制内方向，双一流机会可以继续看深造。"
            ],
            "nextActionHints": [
                "下一步建议先选一个主方向，再看当前方案是否需要补强。"
            ],
        }
    )

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool._get_direction_analysis_agent", return_value=agent),
    ):
        resp = _run(
            preview_direction_comparison_from_request(
                _request_context(session_id="403", text="深造、稳定就业和体制内哪个更适合"),
                [CAREER_FURTHER_STUDY, CAREER_STABLE_EMPLOYMENT, CAREER_SYSTEM_PUBLIC_SERVICE],
            )
        )

    assert "方向判断" in resp
    assert "当前方案已有 2/3 个志愿" in resp
    assert "冲稳保分布：冲1 / 稳1 / 保0" in resp
    assert "三个方向可以一起比较" in resp
    assert "深造看院校平台" in resp
    assert "和“体制内/考公导向”更贴近的大约有 1 个志愿" in resp
    assert "北京师范大学-法学" in resp
    assert "和“深造发展导向”更贴近的大约有 2 个志愿" in resp
    assert "北京工业大学" in resp
    assert "先选一个主方向" in resp

    prompt = agent.prompts[0]
    assert "学生适配事实" in prompt
    assert "深造发展导向" in prompt
    assert "稳定就业导向" in prompt
    assert "体制内/考公导向" in prompt
    assert prompt.count('"slot"') >= 6
    assert "如果是多方向，允许比较多个方向，不要默认只有两个" in prompt


def test_direction_explore_comparison_skips_inner_llm_when_chat_service_disables_it():
    request_context = _request_context(session_id="403b", text="深造、稳定就业和体制内哪个更适合")
    request_context.allow_explore_inner_llm = False

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", new=AsyncMock()) as generation_mock,
    ):
        resp = _run(
            preview_direction_comparison_from_request(
                request_context,
                [CAREER_FURTHER_STUDY, CAREER_STABLE_EMPLOYMENT, CAREER_SYSTEM_PUBLIC_SERVICE],
            )
        )

    generation_mock.assert_not_awaited()
    assert "方向判断" in resp
    assert "当前方案已有 2/3 个志愿" in resp
    assert "这类问题更适合先看你本人更适合哪条路径" in resp
    assert "和“体制内/考公导向”更贴近的大约有 1 个志愿" in resp
    assert "代表样本有：北京师范大学-法学" in resp
    assert "候选里和“体制内/考公导向”更相关" in resp


def test_direction_explore_comparison_fallback_includes_professional_assessment_hint():
    async def _raise_generation(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}})),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", side_effect=_raise_generation),
    ):
        resp = _run(
            preview_direction_comparison_from_request(
                _request_context(session_id="406", text="体制内和读研哪个更适合我"),
                [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_FURTHER_STUDY],
            )
        )

    assert "MBTI" in resp
    assert "霍兰德" in resp


def test_direction_explore_public_service_fallback_explains_student_fit_before_plan_examples():
    async def _raise_generation(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", side_effect=_raise_generation),
    ):
        resp = _run(
            preview_direction_analysis_from_request(
                _request_context(session_id="407", text="以后想走体制内，这条路适合我吗"),
                CAREER_SYSTEM_PUBLIC_SERVICE,
            )
        )

    assert "你的当前选科是物理、化学、生物" in resp
    assert "你现在的兴趣又明显偏向计算机类" in resp
    assert "当前方案里已经有一部分内容能承接这条方向" in resp
    assert resp.index("你的当前选科是物理、化学、生物") < resp.index("当前方案里已经有一部分内容能承接这条方向")


def test_direction_explore_further_study_fallback_uses_existing_future_development_signal():
    async def _raise_generation(*args, **kwargs):
        raise RuntimeError("llm unavailable")

    with (
        patch(
            "app.tools.explore_direction_tool.get_planning_state",
            new=AsyncMock(return_value=_planning_state_with_future_development([CAREER_FURTHER_STUDY])),
        ),
        patch("app.tools.explore_direction_tool._generate_direction_analysis_content", side_effect=_raise_generation),
    ):
        resp = _run(
            preview_direction_analysis_from_request(
                _request_context(session_id="408", text="以后读研是不是更适合我"),
                CAREER_FURTHER_STUDY,
            )
        )

    assert "长期发展倾向里已经出现了“深造发展导向”" in resp
    assert "深造方向更适合重点比较培养平台、升学通道和长期学习投入" in resp


def test_direction_explore_analysis_does_not_write_plan_edit_cache():
    from app.tools import explore_direction_tool as module

    with patch(
        "app.tools.explore_direction_tool.get_planning_state",
        new=AsyncMock(return_value={"data": {"orderedPlanState": {"items": []}, "candidatePoolState": {"items": []}}}),
    ):
        _run(
            preview_direction_analysis_from_request(
                _request_context(session_id="408b", text="体制内适不适合我"),
                CAREER_SYSTEM_PUBLIC_SERVICE,
            )
        )

    assert not hasattr(module, "save_intent_change_cache")


def test_direction_explore_wrapper_routes_model_resolved_multiple_slots_to_comparison():
    ctx = SimpleNamespace(
        deps=_request_context(session_id="404", text="我到底更适合读研还是稳定就业")
    )

    with (
        patch(
            "app.tools.intent_preview_tool._resolve_career_direction_slots",
            new=AsyncMock(return_value=[CAREER_FURTHER_STUDY, CAREER_STABLE_EMPLOYMENT]),
        ) as resolver_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
            new=AsyncMock(return_value="多方向比较结果"),
        ) as comparison_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
            new=AsyncMock(return_value="单方向结果"),
        ) as single_mock,
    ):
        resp = _run(analyze_current_career_direction(ctx))

    assert resp == "多方向比较结果"
    resolver_mock.assert_awaited_once_with(ctx.deps)
    comparison_mock.assert_awaited_once_with(ctx.deps, [CAREER_FURTHER_STUDY, CAREER_STABLE_EMPLOYMENT])
    single_mock.assert_not_awaited()


def test_direction_explore_uses_explicit_generic_flag_without_resolver():
    ctx = SimpleNamespace(
        deps=_request_context(session_id="404-generic", text="等成绩出来再定，今天先看大方向")
    )

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock()) as resolver_mock,
        patch("app.tools.intent_preview_tool._should_use_generic_direction_analysis", new=AsyncMock()) as generic_resolver_mock,
        patch(
            "app.tools.intent_preview_tool._preview_generic_direction_analysis_from_request",
            new=AsyncMock(return_value="泛方向分析结果"),
        ) as generic_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
            new=AsyncMock(),
        ) as comparison_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
            new=AsyncMock(),
        ) as single_mock,
    ):
        resp = _run(analyze_current_career_direction(ctx, generic_direction=True))

    assert resp == "泛方向分析结果"
    resolver_mock.assert_not_awaited()
    generic_resolver_mock.assert_not_awaited()
    generic_mock.assert_awaited_once_with(ctx.deps)
    comparison_mock.assert_not_awaited()
    single_mock.assert_not_awaited()


def test_direction_explore_uses_explicit_direction_slots_without_resolver():
    ctx = SimpleNamespace(
        deps=_request_context(session_id="404-explicit", text="大城市就业和考编哪个更现实")
    )

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock()) as resolver_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
            new=AsyncMock(return_value="方向对比结果"),
        ) as comparison_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
            new=AsyncMock(return_value="单方向结果"),
        ) as single_mock,
    ):
        resp = _run(
            analyze_current_career_direction(
                ctx,
                career_directions=[CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_MARKET_EMPLOYMENT],
            )
        )

    assert resp == "方向对比结果"
    resolver_mock.assert_not_awaited()
    comparison_mock.assert_awaited_once_with(
        ctx.deps,
        [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_MARKET_EMPLOYMENT],
    )
    single_mock.assert_not_awaited()


def test_direction_explore_market_employment_keeps_city_and_industry_signal():
    agent = _CapturingDirectionAgent(
        {
            "summaryTitle": "大城市就业更要同时看产业机会和专业技能",
            "currentPlanFit": [
                "北京工业大学-计算机科学与技术能承接一部分市场化就业方向。",
                "这条路要看城市产业、实习机会和技能可迁移性。",
            ],
            "currentPlanConflict": [
                "如果只看学校层次、不看行业和岗位面，判断会偏粗。"
            ],
            "candidateOpportunity": [
                "天津财经大学-金融学可以作为财经类就业机会继续比较。"
            ],
            "nextActionHints": [
                "下一步可以把它和考编方向放在一起比较。"
            ],
        }
    )

    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=_planning_state_with_market_examples())),
        patch("app.tools.explore_direction_tool._get_direction_analysis_agent", return_value=agent),
    ):
        resp = _run(
            preview_direction_analysis_from_request(
                _request_context(session_id="409", text="大城市就业这条路现实吗"),
                CAREER_MARKET_EMPLOYMENT,
            )
        )

    assert "市场化就业导向" in resp
    assert "北京工业大学-计算机科学与技术" in resp
    assert "城市产业、实习机会和技能可迁移性" in resp
    assert "天津财经大学-金融学" in resp

    prompt = agent.prompts[0]
    assert "market_employment" in prompt
    assert "majorCategory:计算机类" in prompt
    assert "schoolCategory:财经" in prompt


def test_direction_explore_ignores_invalid_explicit_slots_and_falls_back_to_resolver():
    ctx = SimpleNamespace(
        deps=_request_context(session_id="404-invalid", text="这个以后怎么样")
    )

    with (
        patch(
            "app.tools.intent_preview_tool._resolve_career_direction_slots",
            new=AsyncMock(return_value=[CAREER_STABLE_EMPLOYMENT]),
        ) as resolver_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_comparison_from_request",
            new=AsyncMock(),
        ) as comparison_mock,
        patch(
            "app.tools.intent_preview_tool.preview_direction_analysis_from_request",
            new=AsyncMock(return_value="稳定就业分析"),
        ) as single_mock,
    ):
        resp = _run(
            analyze_current_career_direction(
                ctx,
                career_directions=["unknown"],  # type: ignore[list-item]
            )
        )

    assert resp == "稳定就业分析"
    resolver_mock.assert_awaited_once_with(ctx.deps)
    comparison_mock.assert_not_awaited()
    single_mock.assert_awaited_once_with(ctx.deps, CAREER_STABLE_EMPLOYMENT)


def test_direction_explore_resolver_empty_result_asks_for_clearer_direction_without_state_change():
    ctx = SimpleNamespace(
        deps=_request_context(session_id="405", text="这个以后怎么样")
    )

    with (
        patch("app.tools.intent_preview_tool._resolve_career_direction_slots", new=AsyncMock(return_value=[])),
        patch("app.tools.intent_preview_tool.preview_direction_comparison_from_request", new=AsyncMock()) as comparison_mock,
        patch("app.tools.intent_preview_tool.preview_direction_analysis_from_request", new=AsyncMock()) as single_mock,
    ):
        resp = _run(analyze_current_career_direction(ctx))

    assert "还没完全判断出" in resp
    assert "体制内" in resp
    assert "稳定就业" in resp
    assert "读研" in resp
    comparison_mock.assert_not_awaited()
    single_mock.assert_not_awaited()


def test_career_direction_route_reuses_combined_decision_for_generic_fallback():
    request_context = _request_context(session_id="405b", text="等成绩出来再定，今天先看大方向")
    route_agent = _CapturingDirectionAgent(
        {
            "positive": [],
            "negative": [],
            "shouldAnalyze": True,
            "reason": "用户在问泛方向适配，不是具体改方案。",
        }
    )

    with patch("app.tools.explore_direction_tool._get_career_direction_resolver_agent", return_value=route_agent):
        slots = _run(resolve_career_direction_slots(request_context))
        should_analyze = _run(should_use_generic_direction_analysis(request_context))

    assert slots == []
    assert should_analyze is True
    assert len(route_agent.prompts) == 1
    assert "等成绩出来再定" in route_agent.prompts[0]


def test_generic_direction_explore_fallback_starts_with_student_fit_not_school_listing():
    request_context = _request_context(session_id="406", text="适合什么方向")
    request_context.score_detail = SimpleNamespace(
        province="北京",
        total_score=605,
        subject_list=["物理", "化学", "生物"],
        sex="女",
        volunteer_model="majorGroup",
    )
    request_context.init_profile = SimpleNamespace(
        major=SimpleNamespace(level1=["工学"], level2=["计算机类", "电子信息类"], negative_level2=["土木类"]),
        city=SimpleNamespace(province=["北京"], negative_province=[]),
        strength_subjects=["物理"],
    )

    planning_state = _planning_state_with_direction_examples()
    with (
        patch("app.tools.explore_direction_tool.get_planning_state", new=AsyncMock(return_value=planning_state)),
        patch(
            "app.tools.explore_direction_tool._generate_generic_direction_analysis_content",
            side_effect=RuntimeError("llm unavailable"),
        ),
    ):
        resp = _run(preview_generic_direction_analysis_from_request(request_context))

    assert "你的当前选科是物理、化学、生物" in resp
    assert "你已经明确对计算机类、电子信息类这类方向有兴趣" in resp
    assert "当前方案" in resp


def test_generic_direction_explore_skips_inner_llm_when_chat_service_disables_it():
    request_context = _request_context(session_id="406b", text="适合什么方向")
    request_context.allow_explore_inner_llm = False
    request_context.score_detail = SimpleNamespace(
        province="北京",
        total_score=605,
        subject_list=["物理", "化学", "生物"],
        sex="女",
        volunteer_model="majorGroup",
    )
    request_context.init_profile = SimpleNamespace(
        major=SimpleNamespace(level1=["工学"], level2=["计算机类"], negative_level2=[]),
        city=SimpleNamespace(province=["北京"], negative_province=[]),
        strength_subjects=["物理"],
    )

    with (
        patch("app.tools.explore_direction_tool.get_planning_workspace_state", new=AsyncMock(return_value=_planning_state_with_direction_examples())),
        patch("app.tools.explore_direction_tool.query_planning_candidate_pool", new=AsyncMock(return_value={"data": {"items": []}})),
        patch("app.tools.explore_direction_tool._generate_generic_direction_analysis_content", new=AsyncMock()) as generation_mock,
    ):
        resp = _run(preview_generic_direction_analysis_from_request(request_context))

    generation_mock.assert_not_awaited()
    assert "泛方向" not in resp
    assert "你的当前选科是物理、化学、生物" in resp
    assert "计算机类" in resp
