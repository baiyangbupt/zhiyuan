"""Tests for ChatAgent init profile instructions."""

from types import SimpleNamespace

from app.agent.instructions.assembler import build_instructions as _build_instructions
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

    assert "当前会话已存在统一规划状态" in instructions
    assert "用户当前方案已有 20 个志愿" in instructions
    assert "主要问题：保区占比过低" in instructions
    assert "待处理建议：补充保区志愿" in instructions


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
    assert "## 任务层判断" in instructions
    assert "## 副作用边界" in instructions
    assert "只读查询、解释和分析可以直接做" in instructions
    assert "必须先确认" in instructions
    assert "现在方案怎么样" in instructions
    assert "还差几个怎么补" in instructions
    assert "按录取率排序 / 按院校层次排序 / 按推荐系数排序" in instructions
    assert "不要机械复读工具原始 JSON" in instructions
    assert "不要写“你现在必须决定”" in instructions
    assert "不要把它改写成另一份更长的'系统播报摘要'" in instructions


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

    assert "统一优先走 Plan 编排工具" in instructions
    assert "直接调用 `plan_next_action(action_family=\"query_state\")`" in instructions
    assert "不要先单独调用 `collect_plan_context_inputs`" in instructions
    assert "`query_volunteer_plan` 只用于局部命中查询" in instructions
    assert "还差几个怎么补" in instructions
    assert "必须走 Plan 主链路" in instructions
    assert "不要先用 `query_state` 做状态播报" in instructions
    assert "直接规划对应 action 的 preview" in instructions
    assert "当前方案志愿数为0" in instructions
    assert "不能编造" in instructions
    assert "当前 planning 状态的优先级高于历史对话" in instructions
    assert "即使历史里答过，也要重新读取当前 plan 状态" in instructions
    assert "高副作用动作" in instructions
    assert "`move_ordered_unit` 或 `remove_ordered_unit`" in instructions
    assert "删除第 N 个专业组" in instructions
    assert "专业组顺序" in instructions
    assert "专业组/志愿组" not in instructions
    assert "target_position=M" in instructions
    assert "青岛电影学院的新闻学" in instructions
    assert "query_volunteer_plan" in instructions
    assert "不提供固定/锁定志愿入口" in instructions
    assert "execute_plan_action" in instructions
    assert "`result_kind`/`reply_focus`/`next_step_hints`/`facts`" in instructions
    assert "result_kind=\"preview_only\"" in instructions
    assert "result_kind=\"no_change\"" in instructions
    assert "不要当成失败重试" in instructions
    assert "不是新的长期偏好或要求" in instructions
    assert "不要调用 Intent 状态工具" in instructions
    assert "不要调用 Intent 状态工具" in instructions
    assert "公办/民办占比" in instructions
    assert "不要升级成 `review_plan` 或改方案预览" in instructions
    assert "如果用户只是问是否存在某类风险" in instructions
    assert "不要自动规划删除、替换或补偿" in instructions
    assert "本轮审查结果是风险与提醒数量的权威事实" in instructions
    assert "不要再拿历史上下文里的旧方案概览" in instructions
    assert "单纯方案审查 `review_plan` 不要先调用 `collect_plan_context_inputs`" in instructions


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

    assert "适合什么方向" in instructions
    assert "默认按 Explore + career 处理" in instructions
    assert "`analyze_current_career_direction`" in instructions
    assert "`analyze_current_school_interest`" in instructions
    assert "`analyze_current_major_interest`" in instructions
    assert "`analyze_current_region_interest`" in instructions
    assert "`preview_current_major_intent_confirmation`" in instructions
    assert "`preview_current_school_intent_confirmation`" in instructions
    assert "`preview_current_region_intent_confirmation`" in instructions
    assert "`preview_current_career_intent_confirmation`" in instructions
    assert "不要在同一轮里先调 preview 又立刻调 `update_volunteer_intent_state(action=\"confirm\")`" in instructions
    assert "电子信息工程适合我吗" in instructions
    assert "先看学生本人适配度，再看方向/对象特点，再看当前方案承接" in instructions
    assert "用户意向与方向探索不要混在一起" in instructions
    assert "想学网络与新媒体" in instructions
    assert "先走 Intent 确认预览" in instructions
    assert "两个具体专业/专业类做只读比较" in instructions
    assert "`compare_major_options`" in instructions
    assert "`compare_majors` 或 `compare_majors_adhoc`" in instructions
    assert "`get_major_introductions`" in instructions
    assert "不要并行或连续多次调用 `get_major_introduction`" in instructions
    assert "默认不查当前方案和候选机会" in instructions
    assert "include_plan_context=true" in instructions
    assert "不要先调用 `analyze_current_major_interest`" in instructions
    assert "不要在同一轮再追加 `get_major_introduction`" in instructions
    assert "Explore 专用工具已经返回当前方案概况" in instructions
    assert "不要再补调 `plan_next_action(action_family=\"query_state\")`" in instructions
    assert "直接传结构化参数" in instructions
    assert "不要在同一轮重复调用同一个 preview 工具" in instructions
    assert "只使用 canonical key" in instructions
    assert "不要说“画像、加入画像、写入画像、更新画像”" in instructions


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
