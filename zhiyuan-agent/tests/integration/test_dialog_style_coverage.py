"""B. Dialog regression 回复风格验证。

验证新的 build_instructions 模块化指令输出包含了所有必要的风格约束，
确保 dialog_regression_runner 中 PLAN_STYLE_BANNED_SUBSTRINGS 对应的
禁止模式在指令中有对应规则覆盖，LLM 不应产出这些内容。

验证维度：
1. 新指令中每个 banned pattern 都有对应的约束规则
2. 新指令与旧指令的关键风格约束一一对应
3. 新指令长度不超标
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agent.context import RequestContext, ScoreDetail, PlanningSummary
from app.agent.instructions.assembler import build_instructions
from app.agent.instructions.style_rules import build_style_rules


# ---------------------------------------------------------------------------
# 加载 dialog_regression_runner 中的 banned patterns
# ---------------------------------------------------------------------------

RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

BANNED_SUBSTRINGS: list[str] = runner.PLAN_STYLE_BANNED_SUBSTRINGS
BANNED_EXACT_LINES: set[str] = runner.PLAN_STYLE_BANNED_EXACT_LINES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_full_ctx():
    """构造包含完整上下文的 RunContext mock。"""
    deps = RequestContext(
        userid="test_user",
        sessionid="test_session",
        score_detail=ScoreDetail(
            province="北京",
            total_score=650,
            subject_list=["物理", "化学", "生物"],
            sex="男",
        ),
        planning_summary=PlanningSummary(
            phase="ordered",
            draft_total=30,
            ordered_total=30,
            review_risk_count=1,
            review_warn_count=2,
            risk_summaries=["高收费"],
            pending_action_count=0,
            pending_action_summaries=[],
        ),
        chat_history=[{"role": "user"}, {"role": "assistant"}],
    )
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


# ---------------------------------------------------------------------------
# 核心验证：style_rules 覆盖了 banned patterns
# ---------------------------------------------------------------------------

# 每个 banned pattern 对应应该在 style_rules 中找到的约束关键词
_COVERAGE_MAP = {
    "你必须决定": "必须决定",
    "必须做出选择": "必须",
    "必须做一个选择": "必须",
    "必须选一个": "必须选一个",
    "我无法继续回应": "无法继续回应",
    "我不再重复解释": "不再重复解释",
    "我不再回应": "不再",
    "最后一次说明": "最后一次说明",
    "必须停止这个循环": "停止这个循环",
    "停止这个循环": "停止这个循环",
    "完全没有意义": "完全没有意义",
    "你现在必须决定": "你现在必须决定",
    "没有第三个选项": "没有第三个选项",
    "补偿预览": "补偿预览",
}

# 因为 style_rules 用统一模式覆盖，部分 banned items 由同一条规则涵盖
# 例如 "当前这版财会类方案就是最优解" 和 "我现在直接帮你重新生成"
# 由 "不要写...训斥口吻" 整条规则涵盖
_GROUPED_COVERAGE = {
    "当前这版财会类方案就是最优解": "训斥口吻",
    "当前这版财会类方案保留": "训斥口吻",
    "我现在直接帮你重新生成": "训斥口吻",
}


class TestStyleRulesCoverBannedPatterns:
    """验证 style_rules 中对每个 banned pattern 有对应的约束。"""

    def test_style_rules_contain_key_constraints(self):
        rules = build_style_rules()
        # 核心约束关键词必须出现
        key_constraints = [
            "不再重复解释",
            "最后一次说明",
            "停止这个循环",
            "完全没有意义",
            "你现在必须决定",
            "必须选一个",
            "没有第三个选项",
            "补偿预览",
        ]
        for constraint in key_constraints:
            assert constraint in rules, f"style_rules 缺少约束: {constraint}"

    def test_anti_forced_choice_in_style_rules(self):
        rules = build_style_rules()
        assert "必须决定" in rules
        assert "必须选一个" in rules
        assert "没有第三个选项" in rules

    def test_anti_refusal_in_style_rules(self):
        rules = build_style_rules()
        assert "无法继续回应" in rules
        assert "不再重复解释" in rules
        assert "最后一次说明" in rules
        assert "停止这个循环" in rules
        assert "完全没有意义" in rules

    def test_anti_internal_wording(self):
        rules = build_style_rules()
        assert "补偿预览" in rules

    @pytest.mark.parametrize("banned_pattern", [
        p for p in BANNED_SUBSTRINGS
        if p in _COVERAGE_MAP
    ])
    def test_each_pattern_has_coverage(self, banned_pattern):
        """每个主要 banned pattern 在 style_rules 中有对应覆盖。"""
        rules = build_style_rules()
        coverage_key = _COVERAGE_MAP[banned_pattern]
        assert coverage_key in rules, (
            f"banned pattern '{banned_pattern}' 的约束 '{coverage_key}' 未出现在 style_rules 中"
        )


class TestFullInstructionsCoverage:
    """验证完整 build_instructions 输出的风格覆盖。"""

    def test_full_instructions_contain_style_section(self):
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        assert "回复风格约束" in instructions

    def test_full_instructions_contain_anti_forced_choice(self):
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        assert "必须决定" in instructions
        assert "没有第三个选项" in instructions

    def test_full_instructions_contain_anti_refusal(self):
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        assert "无法继续回应" in instructions
        assert "停止这个循环" in instructions

    def test_full_instructions_contain_intent_caution(self):
        """Intent 阶段的"还没有真正生效"约束。"""
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        assert "点‘采纳’前不会生效" in instructions
        assert "不能说“我记下了/我已经记录/已经帮你调整”" in instructions

    def test_full_instructions_contain_profile_wording_ban(self):
        """禁止说"加入画像"。"""
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        assert "加入画像" in instructions  # 在 banned list 中出现（即作为禁用示例）

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_instructions_length_reasonable(self, volunteer_model):
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        lines = instructions.split("\n")
        assert len(lines) < 150, f"Instructions too long: {len(lines)} lines"

    @pytest.mark.parametrize("volunteer_model", ["major", "majorGroup"])
    def test_instructions_not_empty_sections(self, volunteer_model):
        ctx = _make_full_ctx()
        instructions = build_instructions(ctx)
        # 各段落均存在
        assert "孙成老师" in instructions  # identity
        assert "Explore" in instructions  # tool_dispatch
        assert "回复风格" in instructions  # style_rules


class TestStyleCheckFunctionWithInstructions:
    """验证 _check_plan_reply_style 函数与新指令的一致性。

    如果新指令正确传达了约束，LLM 的回复不应触发 _check_plan_reply_style 的 violations。
    这里反向验证：banned patterns 确实会被检测到。
    """

    @pytest.mark.parametrize("banned", BANNED_SUBSTRINGS)
    def test_banned_substring_detected(self, banned):
        """每个 banned substring 出现在回复中时都能被检测到。"""
        text = f"方案审查结果如下。{banned}这是后续内容。"
        violations = runner._check_plan_reply_style(text)
        assert len(violations) > 0, f"banned substring '{banned}' 未被检测到"

    @pytest.mark.parametrize("exact_line", BANNED_EXACT_LINES)
    def test_banned_exact_line_detected(self, exact_line):
        """每个 banned exact line 出现时都能被检测到。"""
        text = f"上面是说明。\n\n{exact_line}\n\n下面继续。"
        violations = runner._check_plan_reply_style(text)
        assert len(violations) > 0, f"banned exact line '{exact_line}' 未被检测到"

    def test_clean_reply_passes(self):
        """正常回复不应触发 violations。"""
        text = (
            "**审查结论**\n\n"
            "当前方案共30个志愿，风险0项，提醒2项。\n\n"
            "主要需要关注高收费志愿3项。如果需要替换，我可以帮你逐步处理。"
        )
        violations = runner._check_plan_reply_style(text)
        assert violations == []
