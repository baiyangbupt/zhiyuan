import importlib.util
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[2] / "examples" / "dialog_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("dialog_regression_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_plan_reply_style_accepts_markdown_sections_and_lists():
    text = (
        "**审查结论**\n\n"
        "当前方案可用，风险0项，提醒3项。\n\n"
        "1. 冲稳保分布为8:18:19。\n"
        "2. 需要关注高收费和中外合作办学。"
    )

    assert runner._check_plan_reply_style(text) == []


def test_plan_reply_style_rejects_forced_choice_answer():
    text = "**方案审查结论**\n\n1. 风险0项\n2. 提醒4项\n\n你现在必须决定：选哪个？"

    violations = runner._check_plan_reply_style(text)

    assert any("你现在必须决定" in item for item in violations)
    assert any("选哪个" in item for item in violations)


def test_plan_reply_style_rejects_internal_compensation_preview_wording():
    violations = runner._check_plan_reply_style("这是补偿预览结果。")

    assert any("补偿预览" in item for item in violations)


def test_plan_reply_style_rejects_ab_forced_reply():
    violations = runner._check_plan_reply_style("请明确回复 A 或 B。")

    assert any("请明确回复" in item for item in violations)
    assert any("回复 A 或 B" in item for item in violations)


def test_plan_reply_style_rejects_dangling_exact_line():
    violations = runner._check_plan_reply_style("方案已经有了。\n\n你。")

    assert any("dangling line" in item for item in violations)
