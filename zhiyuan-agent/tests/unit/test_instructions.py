"""指令模块化测试。

验证 app/agent/instructions/ 各模块的输出正确性。
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from app.agent.context import (
    PlanningSummary,
    RequestContext,
    ScoreDetail,
    has_pending_intent_confirmation,
    resolve_pending_confirmation,
)
from app.agent.instructions.identity import build_identity
from app.agent.instructions.planning_context import build_planning_context
from app.agent.instructions.pending_context import build_pending_context
from app.agent.instructions.style_rules import build_style_rules
from app.agent.instructions.tool_dispatch_rules import build_tool_dispatch_rules
from app.tools.plan_orchestration_tool import plan_next_action
from app.tools.plan_query_tool import query_volunteer_plan
from app.agent.instructions.assembler import build_instructions
from app.models.conversation_phase import ConversationPhase, PendingConfirmation, PhaseState


def _make_deps(
    *,
    score: bool = False,
    profile: bool = False,
    planning: bool = False,
    pending: PendingConfirmation | None = None,
    history: list | None = None,
) -> RequestContext:
    """构造测试用 RequestContext。"""
    score_detail = None
    if score:
        score_detail = ScoreDetail(
            province="北京",
            total_score=650,
            subject_list=["物理", "化学", "生物"],
            sex="男",
        )

    init_profile = None
    if profile:
        init_profile = MagicMock()
        init_profile.strength_subjects = ["物理", "数学"]
        init_profile.major.level2 = ["计算机科学与技术"]
        init_profile.major.negative_level2 = []
        init_profile.city.province = ["北京", "上海"]

    planning_summary = None
    if planning:
        planning_summary = PlanningSummary(
            phase="ordered",
            draft_total=50,
            ordered_total=50,
            review_risk_count=2,
            review_warn_count=3,
            risk_summaries=["高收费志愿3项", "概率倒挂1项"],
        )

    return RequestContext(
        userid="test_user",
        sessionid="test_session",
        score_detail=score_detail,
        init_profile=init_profile,
        planning_summary=planning_summary,
        conversation_phase=(
            ConversationPhase(
                state=PhaseState.PLAN_PREVIEWING if pending.kind == "plan_mutation" else PhaseState.INTENT_PREVIEWING,
                pending=pending,
            )
            if pending is not None
            else None
        ),
        chat_history=history,
    )


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_basic_role(self):
        deps = _make_deps()
        result = build_identity(deps)
        assert "孙成老师" in result
        assert "志愿填报" in result

    def test_with_score(self):
        deps = _make_deps(score=True)
        result = build_identity(deps)
        assert "北京" in result
        assert "650" in result
        assert "物理" in result

    def test_with_profile(self):
        deps = _make_deps(profile=True)
        result = build_identity(deps)
        assert "计算机科学与技术" in result
        assert "优势学科" in result
        assert "无需重复询问" in result


# ---------------------------------------------------------------------------
# planning_context
# ---------------------------------------------------------------------------

class TestPlanningContext:
    def test_empty_when_no_planning(self):
        deps = _make_deps()
        assert build_planning_context(deps) == ""

    def test_with_planning_state(self):
        deps = _make_deps(planning=True)
        result = build_planning_context(deps)
        assert "用户当前方案已有 50 个志愿" in result
        assert "50" in result
        assert "风险 2 项" in result
        assert "高收费" in result
        assert "待处理建议" not in result


# ---------------------------------------------------------------------------
# pending_context
# ---------------------------------------------------------------------------

class TestPendingContext:
    def test_empty_when_no_pending(self):
        deps = _make_deps()
        assert build_pending_context(deps) == ""

    def test_with_conversation_phase_pending(self):
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="generate_plan",
            preview_summary="将生成一版方案",
            execution_payload={"stage": "apply"},
        )
        deps = _make_deps(pending=pending)
        result = build_pending_context(deps)
        assert "generate_plan" in result
        assert "pendingConfirmation" in result
        assert "payload" not in result
        assert "追问审查解释、处理分类、影响范围、候选不足原因或当前方案状态" in result
        assert "按只读问题正常调用相应 Plan 工具或基于已知审查事实回答" in result

    def test_conversation_phase_without_pending_has_no_pending(self):
        deps = _make_deps()
        deps.conversation_phase = ConversationPhase(state=PhaseState.PLAN_IDLE)

        assert resolve_pending_confirmation(deps) is None
        assert not has_pending_intent_confirmation(deps)

    def test_resolve_pending_confirmation_prefers_phase(self):
        deps = _make_deps(
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="删除2个志愿",
                execution_payload={"stage": "apply", "action_family": "remove_units"},
            )
        )

        pending = resolve_pending_confirmation(deps)

        assert pending is not None
        assert pending.action_family == "remove_units"
        assert pending.execution_payload["action_family"] == "remove_units"

    def test_has_pending_intent_confirmation_reads_phase(self):
        deps = _make_deps(
            pending=PendingConfirmation(
                kind="intent_change",
                action_family="apply_selected_intents",
            )
        )

        assert has_pending_intent_confirmation(deps)


# ---------------------------------------------------------------------------
# style_rules
# ---------------------------------------------------------------------------

class TestStyleRules:
    def test_not_empty(self):
        result = build_style_rules()
        assert len(result) > 100
        assert "回复风格" in result
        assert "不要夹杂不必要的英文词" in result
        assert "点‘采纳’前不会生效" in result
        assert "首轮或干净上下文不要以“抱歉，刚才...”开头" in result
        assert "“草稿”/“draft” → 说“方案”或“已加入方案”" in result
        assert "备选方案" not in result


# ---------------------------------------------------------------------------
# tool_dispatch_rules
# ---------------------------------------------------------------------------

class TestToolDispatchRules:
    def test_not_empty(self):
        result = build_tool_dispatch_rules()
        assert len(result) > 200
        assert "Explore" in result
        assert "Intent" in result
        assert "Plan" in result

    def test_candidate_add_refs_are_plan_mutations(self):
        result = build_tool_dispatch_rules()
        assert "add_units" in result
        assert "用户原始引用" in result
        assert "广西师大统计" in result
        assert "不要改走学校/分数线 Explore 分析" in result

    def test_plan_local_abbreviation_lookup_uses_plan_query_tool(self):
        result = build_tool_dispatch_rules()
        assert "简称、模糊代称或口语化表达" in result
        assert "query_volunteer_plan" in result
        assert "不要自行把简称解释成地名或院校" in result

    def test_product_export_format_is_not_admission_policy(self):
        result = build_tool_dispatch_rules()
        assert "系统工作台功能" in result
        assert "不能调用 `answer_admission_policy_question`" in result
        assert "专业+大学模式导出" in result
        assert "学校 + 专业" in result
        assert "不按学校聚合" in result

    def test_school_major_move_and_remove_refs_are_plan_mutations(self):
        result = build_tool_dispatch_rules()
        assert "青岛电影学院的新闻学" in result
        assert "move_unit" in result
        assert "target_position" in result
        assert "query_volunteer_plan" in result
        assert "remove_units" in result
        assert "唯一性校验" in result
        assert 'position_scope="after"' in result

    def test_explore_tool_boundaries_reduce_redundant_tool_chains(self):
        result = build_tool_dispatch_rules()
        assert "两个具体专业/专业类做只读比较" in result
        assert "`compare_majors` 或 `compare_majors_adhoc`" in result
        assert "三个及以上具体专业/专业类" in result
        assert "`compare_major_options`" in result
        assert "不要拆成多次二元 `compare_majors`" in result
        assert "`get_major_introductions`" in result
        assert "不要并行或连续多次调用 `get_major_introduction`" in result
        assert "默认不查当前方案和候选机会" in result
        assert "include_plan_context=true" in result
        assert "不要先调用 `analyze_current_major_interest`" in result
        assert "不要在同一轮再追加 `get_major_introduction`" in result
        assert "只有用户明确同时问职业和地域时" in result
        assert "地域取舍按语义判断" in result
        assert "接受度、排斥度、是否纳入、是否值得、就读体验、家庭距离或保底空间" in result
        assert "不要先查当前方案或候选" in result
        assert "明确要列出当前方案或候选中命中的地域机会" in result
        assert "直接传 `career_directions`" in result
        assert "`system_public_service`" in result
        assert "`stable_employment`" in result
        assert "`further_study`" in result
        assert "`market_employment`" in result
        assert "先看大方向" in result
        assert "`analyze_current_career_direction(generic_direction=true)`" in result
        assert "`analyze_current_interest_profile` 一次做综合分析" in result
        assert "不要拆成 `analyze_current_career_direction` 与 `analyze_current_major_interest` 多轮试探" in result
        assert "返回后，本轮直接基于其结果综合答复" in result
        assert "不要再追加 career/major/region/school Explore 工具" in result
        assert "不能只列“可以聊什么”" in result
        assert "这轮只做分析，不会改动你的方案" in result
        assert "Explore 专用工具已经返回当前方案概况" in result
        assert "不要再补调 `plan_next_action(action_family=\"query_state\")`" in result

    def test_career_oriented_plan_optimization_is_not_plain_review(self):
        result = build_tool_dispatch_rules()
        assert "发展导向的方案优化情景" in result
        assert "先调用 `analyze_current_career_direction`" in result
        assert "只有用户明确要求审查风险时" in result
        assert "不能被审查报告淹没" in result
        assert "当前承接、主要短板、调整取舍、下一步是否生成调整预览" in result
        assert "绑定的是职业路径、升学路径、就业风格" in result
        assert "不要先当作普通 `review_plan`" in result

    def test_intent_preview_tool_boundaries_stop_after_preview(self):
        result = build_tool_dispatch_rules()
        assert "`preview_current_*_intent_confirmation` 返回后" in result
        assert "不要在同一轮重复调用同一个 preview 工具" in result
        assert "直接传结构化参数" in result
        assert "没有明确要求“先看影响、边界、利弊、风险或承接情况”" in result
        assert "必须走对应 Intent 预览入口" in result
        assert "先看影响" in result
        assert "不要把一级门类自动展开成所有下级专业" in result
        assert "不要自行补充未出现的相邻专业范围" in result
        assert "师范、护理、土木" in result
        assert "不要调用 `preview_current_school_intent_confirmation`" in result
        assert "句子很短或很口语化" in result
        assert "`negative_level1` / `negative_level2` / `negative_level3`" in result

    def test_plan_tool_boundaries_do_not_upgrade_queries_to_mutations(self):
        result = build_tool_dispatch_rules()
        assert "公办/民办占比" in result
        assert "高收费占比" in result
        assert "不要升级成 `review_plan` 或改方案预览" in result
        assert "如果用户只是问是否存在某类风险" in result
        assert "不要自动规划删除、替换或补偿" in result
        assert "费用、预算、中外合作、高收费、学费压力" in result
        assert "不要只用 `query_state` 返回普通方案概览" in result
        assert 'result_kind="review_result"' in result
        assert "本轮审查结果是风险与提醒数量的权威事实" in result
        assert "不要再拿历史上下文里的旧方案概览" in result
        assert "单纯方案审查 `review_plan` 不要先调用 `collect_plan_context_inputs` 或 `plan_next_action`" in result

    def test_plan_region_move_should_not_be_generic_sort(self):
        result = build_tool_dispatch_rules()
        assert "把北京/上海/某学校/某专业方向的志愿往前挪一些" in result
        assert "不是指定维度排序" in result
        assert "不要把它规划成 `sort_ordered_plan`" in result
        assert "目标位置" in result

    def test_plan_tuition_mutation_request_should_preview_only_when_explicit(self):
        result = build_tool_dispatch_rules()
        assert "fix_proposals" in result
        assert "不要默认删除" in result
        assert "只有用户明确要求" in result
        assert "才规划 `remove_units` preview" in result
        assert "才规划 `replace_units` preview" in result
        assert 'review_issue_target.code="high_tuition"' in result
        assert "不要停留在 `plan_next_action` 的 preview_summary" in result

    def test_policy_metric_explanation_should_not_be_plan_state_query(self):
        result = build_tool_dispatch_rules()
        assert "某个指标/规则在方案里应该怎么看" in result
        assert "分数、位次、批次线、录取概率等指标“在方案里怎么看/怎么参考”" in result
        assert "不是当前方案现状查询，应走 Policy" in result

    def test_policy_tuition_tradeoff_should_not_use_generic_interest(self):
        result = build_tool_dispatch_rules()
        assert "学校层次很好但学费高能不能冲" in result
        assert "属于学费预算取舍的 Policy 决策框架" in result
        assert "不要调用泛化兴趣分析工具" in result

    def test_plan_local_query_empty_result_should_not_be_worded_as_system_delay(self):
        result = build_tool_dispatch_rules()
        assert "暂时没有筛到/没有命中" in result
        assert "不能只回复“没有可查询的志愿”" in result
        assert "不要改写成“系统延迟、稍后再试、查询没拉出来”" in result

    def test_candidate_readonly_query_should_not_probe_plan_state_first(self):
        result = build_tool_dispatch_rules()
        assert "只读候选机会查询" in result
        assert 'query_volunteer_plan(scope="candidate")' in result
        assert '不要先调用 `plan_next_action(action_family="query_state")`' in result
        assert "只有用户明确要求加入、替换、补齐或调整当前方案时" in result

    def test_plan_adjustment_preview_boundary_prefers_fix_proposal_preview(self):
        result = build_tool_dispatch_rules()
        assert "区分“审查解释/调整分析”和“调整预览”" in result
        assert "用户只是想看懂审查提醒、区分哪些需要关注、哪些可处理、为什么候选不足" in result
        assert "`analyze_adjustment`" in result
        assert "不生成待确认调整" in result
        assert "语义上要看到一版可确认的调整内容" in result
        assert "不要把用户话术交给服务层兜底猜" in result
        assert "整体调稳、补稳、降低冒险程度" in result
        assert "`preview_fix_proposal`" in result
        assert "没有可执行建议" in result or "没有可执行补齐动作" in result

    def test_plan_composite_goal_requires_structured_goal_fields(self):
        result = build_tool_dispatch_rules()
        assert "复合方案调整" in result
        assert 'plan_goal_type="only_keep_scope"' in result
        assert 'constraint_intent_type="only_keep"' in result
        assert 'constraint_intent_type="must_have"' in result
        assert 'plan_goal_type="exclude_scope"' in result
        assert "不要只把“只保留/必须有/不要”等写进 `user_goal`" in result
        assert "不要把 `only_keep` 展开成未点名的负向专业" in result
        assert "具体专业 vs 专业类" in result

    def test_plan_preview_should_not_query_state_again(self):
        result = build_tool_dispatch_rules()
        assert '返回 `result_kind="preview_only"` 后' in result
        assert "不要再补调 `query_state`" in result
        assert "二次 `plan_next_action`" in result

    def test_explore_tool_should_not_repeat_same_tool(self):
        result = build_tool_dispatch_rules()
        assert "同一轮里同一个只读 Explore 工具只调用一次" in result
        assert "不要再次调用同一个 Explore 工具重试" in result

    def test_explore_readonly_should_not_promise_direct_intent_update(self):
        result = build_tool_dispatch_rules()
        assert "是否需要我先列出来让你采纳" in result
        assert "不要说“我可以直接设置/排除/过滤/更新后续推荐”" in result

    def test_style_rules_hide_tool_internals_from_user(self):
        result = build_style_rules()
        assert "不要向用户解释“工具返回/工具识别/工具调用偏了”" in result
        assert "工具返回、工具识别、工具调用" in result

    def test_style_rules_require_card_for_confirmation_wording(self):
        result = build_style_rules()
        assert "如果本轮没有生成可采纳内容" in result
        assert "不能说“你确认后我会过滤/执行/更新”" in result

    def test_plan_tool_docs_say_refs_do_not_need_pre_query(self):
        assert "不适合在移动/删除前作为“定位 ID”的前置步骤" in (query_volunteer_plan.__doc__ or "")
        assert "不应为了定位而先调用 query_volunteer_plan" in (plan_next_action.__doc__ or "")


# ---------------------------------------------------------------------------
# assembler — full integration
# ---------------------------------------------------------------------------

class TestAssembler:
    def _make_ctx(self, deps):
        """模拟 RunContext[RequestContext]。"""
        ctx = MagicMock()
        ctx.deps = deps
        return ctx

    def test_minimal_assembly(self):
        deps = _make_deps()
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "孙成老师" in result
        assert "Explore" in result
        assert "回复风格" in result

    def test_full_assembly(self):
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="remove_units",
            preview_summary="将删除3个志愿",
            execution_payload={"ids": ["v1"]},
        )
        deps = _make_deps(score=True, profile=True, planning=True, pending=pending)
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        # 所有段落都存在
        assert "650" in result
        assert "ordered" in result
        assert "remove_units" in result
        assert "Explore" in result
        assert "回复风格" in result

    def test_first_turn_guidance(self):
        deps = _make_deps(history=[])  # empty history → first turn
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "起手阶段" in result

    def test_no_first_turn_guidance(self):
        deps = _make_deps(history=[{"role": "user"}, {"role": "assistant"}])
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        assert "起手阶段" not in result

    def test_instructions_shorter_than_old(self):
        """新指令应显著短于旧版 ~175 行。"""
        deps = _make_deps(score=True, profile=True, planning=True)
        ctx = self._make_ctx(deps)
        result = build_instructions(ctx)
        lines = result.split("\n")
        # 旧版大约 175 行，新版目标 <120 行（考虑完整注入场景）
        assert len(lines) < 150
