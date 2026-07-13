from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent.context import RequestContext, ScoreDetail
from app.tools.admission_policy_tool import answer_admission_policy_question


@pytest.fixture(autouse=True)
def _clear_bocha_key(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "")


def _ctx(
    *,
    province: str = "北京",
    total_score: int = 620,
    subjects: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s1",
            score_detail=ScoreDetail(
                province=province,
                total_score=total_score,
                subject_list=subjects or ["物理", "化学", "生物"],
                sex="男",
            ),
        )
    )


async def _payload(consultation_scope: str, rule_domain: str, question: str, **kwargs) -> dict:
    text = await answer_admission_policy_question(
        _ctx(),
        question=question,
        consultation_scope=consultation_scope,
        rule_domain=rule_domain,
        **kwargs,
    )
    return json.loads(text)


@pytest.mark.asyncio
async def test_rank_vs_score_policy_answer_covers_plan_reference():
    payload = await _payload("general_policy", "score_batch", "排名比分数靠谱吧，方案里要怎么看")

    assert payload["reply_strategy"] == "direct_reply"
    assert payload["no_mutation"] is True
    assert payload["source_strategy"] == "web_official"
    assert payload["source_lookup_required"] is True
    assert payload["source_lookup_available"] is False
    summary = payload["summary"]
    assert "排名/位次" in summary
    assert "分数" in summary
    assert "录取概率" in summary
    assert "冲稳保" in summary
    assert "方案" in summary


@pytest.mark.asyncio
async def test_pre_score_estimate_answer_requires_province_policy_source():
    payload = await _payload("province_policy", "score_batch", "批次线出来前先按模考估，后面咋调整")

    assert payload["source_strategy"] == "province_official"
    summary = payload["summary"]
    assert "模考" in summary
    assert "批次线" in summary
    assert "出分" in summary
    assert "一分一段" in summary
    assert "重算" in summary or "调整" in summary


@pytest.mark.asyncio
async def test_special_plan_answer_does_not_treat_rural_household_as_enough():
    payload = await _payload("province_policy", "eligibility", "农村户口那个专项能不能用，怎么判断", province="山东")

    assert payload["source_strategy"] == "province_official"
    summary = payload["summary"]
    assert "农村户口不等于一定有专项资格" in summary
    assert "户籍" in summary
    assert "学籍" in summary
    assert "资格审核" in summary
    assert "省级考试院" in payload["official_source_hint"]


@pytest.mark.asyncio
async def test_transfer_policy_answer_requires_school_rule_source():
    payload = await _payload("school_rule", "transfer_major", "想以后有转专业空间，填报上怎么看", school_name="北京工业大学")

    assert payload["source_strategy"] == "school_brochure"
    summary = payload["summary"]
    assert "转专业" in summary
    assert "成绩排名" in summary
    assert "接收名额" in summary
    assert "招生章程" in summary or "转专业办法" in summary


@pytest.mark.asyncio
async def test_tuition_tradeoff_answer_covers_budget_and_rush_boundary():
    payload = await _payload("school_user_fit", "tuition_budget", "如果学校好但学费高，可以冲吗", fit_dimensions=["budget"])

    assert payload["source_strategy"] == "profile_match"
    assert payload["fit_required"] is True
    summary = payload["summary"]
    assert "学费" in summary
    assert "四年成本" in summary
    assert "家庭预算" in summary
    assert "冲区" in summary
    assert "保区" in summary


@pytest.mark.asyncio
async def test_missing_info_checklist_uses_context_and_lists_core_gaps():
    payload = await _payload("missing_info", "general", "现在信息不全，先给我列缺啥")

    summary = payload["summary"]
    assert "省份（北京）" in summary
    assert "总分（620）" in summary
    assert "选科（物理、化学、生物）" in summary
    assert "位次或一分一段位置" in summary
    assert "体检受限项" in summary
    assert "家庭预算与可接受学费上限" in summary
    assert "missing_info" == payload["consultation_scope"]


@pytest.mark.asyncio
async def test_plan_policy_impact_continues_model_for_user_facing_summary():
    payload = await _payload("plan_policy_impact", "tuition_budget", "如果学校好但学费高，可以冲吗")

    assert payload["reply_strategy"] == "continue_model"
    assert payload["plan_lookup_required"] is True
    assert "结合规则和方案位置" in payload["summary"]
    assert "学费" in payload["summary"]


@pytest.mark.asyncio
async def test_school_user_fit_marks_source_and_profile_matching_requirements():
    payload = await _payload(
        "school_user_fit",
        "subject_requirement",
        "这个学校的计算机我物化生能不能报",
        school_name="北京工业大学",
        major_name="计算机科学与技术",
        fit_dimensions=["subjects", "score_rank"],
    )

    assert payload["fit_required"] is True
    assert payload["source_strategy"] == "profile_match"
    assert payload["source_lookup_required"] is True
    assert payload["source_lookup_available"] is False
    assert "当前学生成绩、选科、体检、资格和预算信息" in payload["required_sources"]
    assert "学校或专业与当前学生的适配性判断" in payload["summary"]


@pytest.mark.asyncio
async def test_policy_continues_model_when_source_lookup_is_available(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "sk-test")

    payload = await _payload("school_rule", "transfer_major", "北京工业大学转专业怎么看", school_name="北京工业大学")

    assert payload["source_lookup_required"] is True
    assert payload["source_lookup_available"] is True
    assert payload["reply_strategy"] == "continue_model"
