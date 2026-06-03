from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent.context import RequestContext, ScoreDetail
from app.tools.admission_fit_match_tool import match_admission_rule_to_student


def _ctx(subjects: list[str] | None = None, total_score: int = 620):
    return SimpleNamespace(
        deps=RequestContext(
            userid="u1",
            sessionid="s1",
            score_detail=ScoreDetail(
                province="北京",
                total_score=total_score,
                subject_list=subjects or ["物理", "化学", "生物"],
                sex="男",
            ),
        )
    )


@pytest.mark.asyncio
async def test_match_subject_requirement_passes_when_student_subjects_cover_required():
    payload = json.loads(
        await match_admission_rule_to_student(
            _ctx(),
            school_name="北京工业大学",
            major_name="计算机科学与技术",
            fit_dimensions=["subjects"],
            required_subjects=["物理", "化学"],
            rule_source_urls=["https://example.edu.cn/admission"],
        )
    )

    assert payload["verdict"] == "match"
    assert payload["no_mutation"] is True
    assert "选科匹配" in payload["summary"]


@pytest.mark.asyncio
async def test_match_subject_requirement_fails_when_required_subject_missing():
    payload = json.loads(
        await match_admission_rule_to_student(
            _ctx(subjects=["历史", "政治", "地理"]),
            school_name="北京工业大学",
            major_name="计算机科学与技术",
            fit_dimensions=["subjects"],
            required_subjects=["物理", "化学"],
        )
    )

    assert payload["verdict"] == "not_match"
    assert "选科不匹配" in payload["summary"]


@pytest.mark.asyncio
async def test_match_budget_marks_risk_when_tuition_exceeds_budget():
    payload = json.loads(
        await match_admission_rule_to_student(
            _ctx(),
            school_name="目标院校",
            major_name="中外合作专业",
            fit_dimensions=["budget"],
            tuition_per_year=60000,
            budget_per_year=30000,
        )
    )

    assert payload["verdict"] == "risk"
    assert "学费约60000元/年" in payload["summary"]


@pytest.mark.asyncio
async def test_match_requires_structured_rule_facts_before_conclusion():
    payload = json.loads(
        await match_admission_rule_to_student(
            _ctx(),
            school_name="目标院校",
            major_name="目标专业",
            fit_dimensions=["subjects", "score_rank"],
        )
    )

    assert payload["verdict"] == "needs_info"
    assert "官方选科要求" in json.dumps(payload["checks"], ensure_ascii=False)
    assert "院校/专业近年位次或分数" in json.dumps(payload["checks"], ensure_ascii=False)
