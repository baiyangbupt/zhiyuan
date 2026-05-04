"""Tests for ChatAgent init profile instructions."""

from types import SimpleNamespace

from app.agent.chat_agent import _build_instructions
from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.schemas.user_profile import UserProfile


def test_build_instructions_includes_strength_subjects_from_init_profile():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s1",
            score_detail=ScoreDetail(
                province="北京",
                total_score=650,
                subject_list=["物理", "化学", "生物"],
                sex="男",
            ),
            init_profile=UserProfile(
                strength_subjects=["数学", "物理"],
            ),
        )
    )

    instructions = _build_instructions(ctx)

    assert "优势学科：数学、物理" in instructions


def test_build_instructions_includes_planning_summary():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s1",
            planning_summary=PlanningSummary(
                phase="reviewed",
                version=8,
                draft_total=24,
                ordered_total=20,
                review_warn_count=2,
                review_risk_count=1,
                risk_summaries=["保区占比过低"],
                pending_action_count=1,
                pending_action_summaries=["补充保区志愿"],
            ),
        )
    )

    instructions = _build_instructions(ctx)

    assert "当前规划阶段：reviewed" in instructions
    assert "当前草稿志愿数：24" in instructions
    assert "当前主要风险：保区占比过低" in instructions
    assert "当前待处理建议：1项" in instructions


def test_build_instructions_includes_planning_tool_policy():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s1",
        )
    )

    instructions = _build_instructions(ctx)

    assert "preview_current_major_intent_confirmation" in instructions
    assert "preview_current_school_intent_confirmation" in instructions
    assert "preview_current_region_intent_confirmation" in instructions
    assert "preview_current_career_intent_confirmation" in instructions
    assert "analyze_volunteer_intent_change" not in instructions
    assert "先判断任务层" in instructions
    assert "再判断副作用边界" in instructions
    assert "只读查询、解释和分析可以直接做" in instructions
    assert "必须先确认" in instructions
    assert "现在方案怎么样" in instructions
    assert "哪里还不合理" in instructions
    assert "怎么优化" in instructions
    assert "这版怎么排更合适" in instructions
    assert "怎么顺更合理" in instructions
    assert "该怎么选更稳" in instructions
    assert "还差几个怎么补" in instructions
    assert "帮我重排一下" in instructions
    assert "帮我顺一下" in instructions
    assert "帮我理一下顺序" in instructions
    assert "不要自动展开成长篇分析或强迫式决策题" in instructions
    assert "优先直接进入 plan 链读取当前状态输入" in instructions
    assert "可以使用小标题、轻量 Markdown 或要点列表" in instructions
    assert "不要机械复读工具原始 JSON" in instructions
    assert "可以自然给出下一步选项" in instructions
    assert "先给总体结论，再提最关键问题" in instructions
    assert "不要写“你现在必须决定”“必须选一个”“没有第三个选项”" in instructions
    assert "不要把它改写成另一份更长的‘系统播报摘要’" in instructions


def test_build_instructions_includes_plan_orchestration_boundaries():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s2",
            planning_summary=PlanningSummary(
                phase="profile_ready",
                version=1,
                draft_total=0,
                ordered_total=0,
                review_warn_count=0,
                review_risk_count=0,
            ),
        )
    )

    instructions = _build_instructions(ctx)

    assert "统一优先走 `collect_plan_context_inputs` -> `plan_next_action` -> `execute_plan_action`" in instructions
    assert "规划并执行 `query_state` 类动作" in instructions
    assert "`query_volunteer_plan` 只用于回答" in instructions
    assert "还差几个怎么补" in instructions
    assert "不要调用 `query_volunteer_plan`" in instructions
    assert "优先直接传结构化参数，如 `school_keywords`、`major_keywords`、`province_names`" in instructions
    assert "规划成 `preview_compensation`、`add_units` 或相关补齐动作" in instructions
    assert "草稿志愿数=0 且排序志愿数=0" in instructions
    assert "不能编造" in instructions
    assert "当前 planning 状态的优先级高于历史对话" in instructions
    assert "即使历史里已经回答过，也要重新读取一次当前 plan 状态" in instructions
    assert "优先规划成 `generate_plan` 动作" in instructions
    assert "规划并执行 `review_plan` 动作" in instructions
    assert "规划并执行 `analyze_adjustment` 动作" in instructions
    assert "规划并执行 `preview_compensation` 动作" in instructions
    assert "规划并执行 `regenerate_order` 动作" in instructions
    assert "默认是在问当前方案的分析和建议" in instructions
    assert "也按整体重排理解" in instructions
    assert "`add_units / remove_units / move_unit / replace_units`" in instructions
    assert "execute_plan_action" in instructions
    assert "`result_kind`、`reply_focus`、`next_step_hints` 和 `facts`" in instructions
    assert "不要直接说内部词“补偿预览”" in instructions
    assert "必须先确认用户是否允许整体更新当前排序" in instructions
    assert "高副作用 Plan 动作在确认前也必须走工具链" in instructions
    assert "得到 `preview_only` 结果" in instructions
    assert "不要只用纯文本问‘确认吗’" in instructions
    assert "未确认时也要留下 preview tool result" in instructions
    assert "先处理高收费 / 先处理中外合作" in instructions
    assert "默认按当前 review 命中的整批问题项规划 `remove_units` preview" in instructions
    assert "可以把这些显示引用作为 `volunteer_ids` 传给 `plan_next_action`" in instructions
    assert "只有在 `plan_next_action` 或 `execute_plan_action` 返回 preview 且 `missing_inputs` 为空时" in instructions
    assert "不要把 plan 问题重新降级成 intent 提取问题" in instructions
    assert "这本身不是新的长期偏好或要求" in instructions
    assert "不要调用 Intent 状态工具写缓存或更新报考参考信息" in instructions
    assert "不要把这类 Plan 动作误当成意向写入" in instructions


def test_build_instructions_includes_pending_plan_action_confirmation_payload():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s2",
            pending_plan_action={
                "action_family": "regenerate_order",
                "user_goal": "整体重排当前方案",
                "summary": "会整体重排当前方案。",
                "plan_payload": '{"stage":"apply","action_family":"regenerate_order"}',
            },
        )
    )

    instructions = _build_instructions(ctx)

    assert "当前存在上一轮待确认的方案动作" in instructions
    assert "动作类型：regenerate_order" in instructions
    assert "确认后执行 payload" in instructions
    assert "直接调用 `execute_plan_action`" in instructions


def test_build_instructions_includes_explore_first_direction_fit_guidance():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s2",
        )
    )

    instructions = _build_instructions(ctx)

    assert "我适合什么方向" in instructions
    assert "不要直接根据已记录信息和常识口头列方向清单" in instructions
    assert "`analyze_current_career_direction`" in instructions
    assert "`analyze_current_school_interest`" in instructions
    assert "`analyze_current_major_interest`" in instructions
    assert "`analyze_current_region_interest`" in instructions
    assert "`preview_current_major_intent_confirmation`" in instructions
    assert "`preview_current_school_intent_confirmation`" in instructions
    assert "`preview_current_region_intent_confirmation`" in instructions
    assert "`preview_current_career_intent_confirmation`" in instructions
    assert "不要在同一轮里先调 `preview_current_*_intent_confirmation` 又立刻调 `update_volunteer_intent_state(action=\"confirm\")`" in instructions
    assert "电子信息工程适合我吗" in instructions
    assert "先看学生本人适配度，再看方向/对象本身特点，再看当前方案承接" in instructions
    assert "允许轻量 Markdown" in instructions
    assert "不要把分析压成连续长段落" in instructions
    assert "Intent 最终回复也允许轻量 Markdown" in instructions
    assert "不要把“识别到的偏好/要求、方案关联、候选机会、下一步确认”压成一整段碎片句" in instructions
    assert "用户意向与方向探索不要混在一起" in instructions
    assert "想学网络与新媒体" in instructions
    assert "按主题调用对应的 `preview_current_*_intent_confirmation` 高层入口" in instructions
    assert "不要零工具调用后反问用户是在写入还是看方案" in instructions
    assert "调用 `preview_current_*_intent_confirmation` 时应尽量直接把结构化 intent 参数一并传入" in instructions
    assert "不要自造 `interested`、`priority`、`include` 这类新 key" in instructions
    assert "只有用户明确说“当前方案里有没有、帮我加进方案、补几个、换成、调方案、看候选里还有哪些”" in instructions
    assert "不要说“画像、加入画像、写入画像、更新画像”" in instructions
    assert "不能说“我记下了/我已经记录”" in instructions


def test_build_instructions_includes_first_turn_onboarding_guidance():
    ctx = SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s3",
            chat_history=[{"role": "user", "content": "看看"}],
        )
    )

    instructions = _build_instructions(ctx)

    assert "这是用户进入当前会话后的起手阶段" in instructions
    assert "结合当前会话状态、已有报考参考信息、planning 状态和你准备调用的 skill" in instructions
    assert "对话框适合直接提问、工作台适合查看方案和候选" in instructions
    assert "不要固定成同一套例子" in instructions
