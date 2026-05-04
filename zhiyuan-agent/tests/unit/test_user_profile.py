"""Unit tests for UserProfile data models."""

import pytest
from app.schemas.user_profile import UserProfile, SchoolIntent, MajorIntent, CityIntent


def test_school_intent_default():
    intent = SchoolIntent()
    assert intent.colleges == []
    assert intent.colleges_emotion == []
    assert intent.negative_colleges == []
    assert intent.negative_colleges_emotion == []


def test_major_intent_default():
    intent = MajorIntent()
    assert intent.level2 == []
    assert intent.level3 == []
    assert intent.negative_level2 == []
    assert intent.negative_level3 == []


def test_city_intent_default():
    intent = CityIntent()
    assert intent.province == []
    assert intent.city == []
    assert intent.area == []


def test_user_profile_from_backend_format():
    backend_data = {
        "college_info": {
            "values": ["北京大学", "清华大学"],
            "values_emotion": ["Strong", "Strong"],
        },
        "negative_college_info": {
            "values": ["复旦大学"],
            "values_emotion": ["Strong"],
        },
        "major_intent": {
            "level2": ["工学"],
            "level3": ["计算机科学与技术"],
            "level2_emotion": ["Strong"],
            "level3_emotion": ["Strong"],
        },
        "negative_major_intent": {
            "level2": ["医学"],
            "level3": ["临床医学"],
            "level2_emotion": ["Strong"],
            "level3_emotion": ["Strong"],
        },
        "city_info": {
            "province": ["北京市"],
            "city": ["深圳市"],
            "area": ["华北"],
            "province_emotion": ["Strong"],
            "city_emotion": ["Strong"],
        },
        "strength_subject_info": {
            "values": ["数学", "物理"],
            "values_emotion": ["Strong", "Strong"],
        },
        "negative_city_info": {
            "province": ["西藏自治区"],
            "city": ["拉萨市"],
            "area": ["西北"],
            "province_emotion": ["Strong"],
            "city_emotion": ["Strong"],
        },
    }

    profile = UserProfile.from_backend_format(backend_data)
    assert profile.school.colleges == ["北京大学", "清华大学"]
    assert profile.school.negative_colleges == ["复旦大学"]
    assert profile.major.level2 == ["工学"]
    assert profile.major.level3 == ["计算机科学与技术"]
    assert profile.city.province == ["北京市"]
    assert profile.strength_subjects == ["数学", "物理"]


def test_user_profile_to_backend_format():
    profile = UserProfile(
        school=SchoolIntent(
            colleges=["北京大学"],
            colleges_emotion=["Strong"],
        ),
        major=MajorIntent(
            level3=["计算机科学与技术"],
            level3_emotion=["Strong"],
        ),
        city=CityIntent(
            province=["北京市"],
            province_emotion=["Strong"],
        ),
        strength_subjects=["数学", "物理"],
    )

    backend = profile.to_backend_format()
    assert backend["college_info"]["values"] == ["北京大学"]
    assert backend["major_intent"]["level3"] == ["计算机科学与技术"]
    assert backend["city_info"]["province"] == ["北京市"]
    assert backend["strength_subject_info"]["values"] == ["数学", "物理"]
