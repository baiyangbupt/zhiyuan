import json

from app.schemas.career_intent import CareerIntentResult
from app.tools.career_intent_tool import (
    CAREER_FURTHER_STUDY,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    _build_system_message,
)
from app.tools.extraction_json import parse_extraction_json


def test_career_intent_schema_accepts_positive_and_negative_slots():
    payload = parse_extraction_json(
        json.dumps(
            {
                "positive": [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_FURTHER_STUDY],
                "negative": [CAREER_STABLE_EMPLOYMENT],
            },
            ensure_ascii=False,
        ),
        CareerIntentResult,
    )

    assert payload.positive == [CAREER_SYSTEM_PUBLIC_SERVICE, CAREER_FURTHER_STUDY]
    assert payload.negative == [CAREER_STABLE_EMPLOYMENT]


def test_career_intent_prompt_contains_only_three_slots_and_explore_guard():
    prompt = _build_system_message(
        [
            {"role": "user", "content": "体制内适不适合我"},
        ]
    )

    assert CAREER_SYSTEM_PUBLIC_SERVICE in prompt
    assert CAREER_STABLE_EMPLOYMENT in prompt
    assert CAREER_FURTHER_STUDY in prompt
    assert "这属于探索阶段，不代表已经形成偏好或要求" in prompt
    assert "不能创造新槽位" in prompt


def test_career_intent_prompt_keeps_non_career_entities_out():
    prompt = _build_system_message(
        [
            {"role": "user", "content": "想去北京，看看北邮"},
        ]
    )

    assert "不要把专业、学校、城市抽成这里的方向槽位" in prompt
